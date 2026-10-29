"""Store module - control routes under /api/store/control: transfers between stores (transfer), stock counts (count) and wastage and
scrap (scrap), the stock in transit, what counts found, and what scrap fetched. Owned by P4.

Rights: store.control.view reads; .create makes, edits and deletes drafts, submits, starts a count and enters its sheet; .approve approves
(and .approve_high_value is needed for a document worth 50,000 or more); .post posts - for a transfer that is the dispatch, and receiving
it is also .post, at the destination store; .cancel cancels (a posted document is reversed); .reveal_count shows the system quantity while
a count is open. Every route works inside the stores the person is assigned to.
"""
import io
from datetime import date
from decimal import Decimal
from typing import List, Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor, store_errors
from app.db import get_db, get_read_db
from app.documents import form_pdf
from app.documents.store.control_forms import FORMS
from app.models.store_control import COUNT, SCRAP, TRANSFER, DBStoreControlLog, DBStoreCount, DBStoreScrap, DBStoreTransfer
from app.models.store_core import DBStore, DBStoreUserAssignment, DocStatus
from app.services import store_control as svc
from app.services import store_outward
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/control", tags=["store-control"])
ZERO = Decimal("0")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ACTION_RIGHT = {"submit": "store.control.create", "approve": "store.control.approve", "post": "store.control.post", "cancel": "store.control.cancel"}


# --- request bodies ---------------------------------------------------------------------------------------------------

class TransferLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    remarks: str = ""


class TransferIn(BaseModel):
    store_id: int
    to_store_id: int
    transfer_date: str
    vehicle_no: str = ""
    remarks: str = ""
    lines: List[TransferLineIn]


class CountIn(BaseModel):
    store_id: int
    count_date: str
    count_type: str = "FULL"
    item_ids: List[int] = []
    remarks: str = ""


class SheetRowIn(BaseModel):
    item_id: int
    counted_qty: str
    uom: str = ""
    reason: str = ""
    rate: str = ""                        # only for an item the books did not have


class SheetIn(BaseModel):
    rows: List[SheetRowIn]


class ScrapLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    disposal: str = "SCRAP"
    reason: str = ""
    realised_value: str = ""
    cost_head: str = ""
    writeoff_request_id: Optional[int] = None


class ScrapIn(BaseModel):
    store_id: int
    scrap_date: str
    project_id: Optional[int] = None
    buyer: str = ""
    reference: str = ""
    remarks: str = ""
    lines: List[ScrapLineIn]


class ActionIn(BaseModel):
    reason: str = ""


# --- helpers -----------------------------------------------------------------------------------------------------------

def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def _has(actor, right) -> bool:
    if actor.employee is None:
        return True
    perms = permissions_for(actor.employee)
    return right in perms or "store.admin" in perms


def _my_store(db, actor, store_id):
    """A store of this company the person works in: 404 for anybody else's (so existence is not revealed), 403 for one they are not assigned to."""
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != actor.client.id:
        raise HTTPException(404, "Store not found")
    assert_store_access(actor.user, store.id)
    return store


def _kind(key):
    kind = svc.KINDS.get(key)
    if kind is None:
        raise HTTPException(404, "Not found")
    return kind


def _doc(db, actor, kind, doc_id, *, either_end=False):
    """A document of this company in a store the person works in. A transfer may also be reached from its destination store."""
    doc = db.get(kind.header, doc_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "%s not found" % kind.label)
    if either_end and kind.key == "transfer":
        try:
            assert_store_access(actor.user, doc.store_id)
        except HTTPException:
            assert_store_access(actor.user, doc.to_store_id)
    else:
        assert_store_access(actor.user, doc.store_id)
    return doc


def _editable(doc):
    if doc.status != DocStatus.DRAFT.value:
        raise HTTPException(409, "It is %s. Only a draft can be edited; cancel it and make a new one to correct it." % doc.status.lower())


def _iso(d):
    return d.isoformat() if d else ""


def _who(actor):
    return dict(user_type="employee" if actor.employee is not None else "client", user_name=actor.name)


def _items(db, ids):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(ids) or [0])).all()}


def doc_dict(db, kind, doc, actor, detail=False):
    store = db.get(DBStore, doc.store_id)
    out = {"kind": kind.key, "id": doc.id, "number": doc.number, "status": doc.status, "store_id": doc.store_id, "store_code": store.code if store else "", "store_name": store.name if store else "",
           "date": _iso(getattr(doc, kind.date_attr)), "remarks": doc.remarks or "", "cancel_reason": doc.cancel_reason or "", "created_by": doc.created_by_name or "",
           "created_at": doc.created_at.isoformat(timespec="seconds") if doc.created_at else "", "posted_at": doc.posted_at.isoformat(timespec="seconds") if doc.posted_at else ""}
    if kind.key == "transfer":
        to = db.get(DBStore, doc.to_store_id)
        lines = svc.transfer_lines(db, doc)
        out.update({"to_store_id": doc.to_store_id, "to_store_code": to.code if to else "", "to_store_name": to.name if to else "", "vehicle_no": doc.vehicle_no or "", "receipt_status": doc.receipt_status or "",
                    "received_at": doc.received_at.isoformat(timespec="seconds") if doc.received_at else "", "received_by": doc.received_by_name or "", "inter_project": bool(doc.inter_project),
                    "line_count": len(lines), "value": svc.s2(svc.transfer_value(db, doc))})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                             "entry_uom": l.entry_uom or "", "entry_qty": svc.s3(l.entry_qty), "qty": svc.s3(l.qty), "rate": svc.s4(l.rate), "value": svc.s2(l.value), "remarks": l.remarks or ""} for l in lines]
    elif kind.key == "count":
        lines = svc.count_lines(db, doc)
        reveal = _has(actor, "store.control.reveal_count") or doc.status != DocStatus.DRAFT.value or doc.started_at is None
        out.update({"count_type": doc.count_type, "started": doc.started_at is not None, "started_at": doc.started_at.isoformat(timespec="seconds") if doc.started_at else "",
                    "started_by": doc.started_by_name or "", "line_count": len(lines), "counted": sum(1 for l in lines if l.counted_qty is not None), "revealed": reveal,
                    "variance_value": svc.s2(sum((svc.v2(svc.count_variance(l) * Decimal(str(l.avg_rate))) for l in lines), ZERO)) if reveal else None,
                    "frozen": bool(doc.freeze_id and doc.status not in (DocStatus.POSTED.value, DocStatus.CANCELLED.value))})
        if detail:
            # Not started yet: what is on its way to the store, which the count will not see. Started: what has come in since.
            out["in_transit"] = svc.in_transit_to(db, doc.store_id) if doc.status == DocStatus.DRAFT.value and doc.started_at is None else []
            live = out["frozen"] and doc.started_at is not None
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                             "in_snapshot": bool(l.in_snapshot), "counted_qty": None if l.counted_qty is None else svc.s3(l.counted_qty), "reason": l.reason or "",
                             "system_qty": svc.s3(l.system_qty) if reveal else None, "avg_rate": svc.s4(l.avg_rate) if reveal else None,
                             "variance_qty": svc.s3(svc.count_variance(l)) if reveal and l.counted_qty is not None else None,
                             "variance_value": svc.s2(svc.count_variance(l) * Decimal(str(l.avg_rate))) if reveal and l.counted_qty is not None else None,
                             "arrived_since": svc.s3(max(ZERO, svc.get_balance(db, doc.store_id, l.item_id).qty - Decimal(str(l.system_qty)))) if reveal and live else None} for l in lines]
    else:
        job = db.get(models.DBJob, doc.project_id) if doc.project_id else None
        lines = svc.scrap_lines(db, doc)
        out.update({"project_id": doc.project_id, "project": ("%s - %s" % (job.number, job.name)) if job else "", "buyer": doc.buyer or "", "reference": doc.reference or "", "line_count": len(lines),
                    "realised": svc.s2(sum((Decimal(str(l.realised_value or 0)) for l in lines), ZERO))})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                             "entry_uom": l.entry_uom or "", "entry_qty": svc.s3(l.entry_qty), "qty": svc.s3(l.qty), "disposal": l.disposal, "reason": l.reason or "",
                             "realised_value": svc.s2(l.realised_value), "cost_head": l.cost_head, "writeoff_request_id": l.writeoff_request_id} for l in lines]
    if detail:
        out["history"] = [{"action": h.action, "from": h.from_status, "to": h.to_status, "by": h.user_name, "at": h.at.isoformat(timespec="seconds") if h.at else "", "note": h.note or ""}
                          for h in db.query(DBStoreControlLog).filter(DBStoreControlLog.doc_type == kind.ref, DBStoreControlLog.doc_id == doc.id).order_by(DBStoreControlLog.id).all()]
    return out


def _created(db, actor, kind, doc, request):
    doc.created_by_id, doc.created_by_name = actor.user_id, actor.name
    db.flush()
    svc.log(db, actor, kind.ref, doc.id, "create", "", doc.status)
    log_audit(db, actor.client.id, "store_%s_created" % kind.key, "store_doc", doc.id, doc.number, "", request=request, **_who(actor))


# --- the front door, pickers and reports -------------------------------------------------------------------------------------

@router.get("")
def index(request: Request, db: Session = Depends(get_read_db)):
    """The slice's front door: the latest transfers this person may see."""
    return {"slice": "control", "items": list_documents("transfer", request, limit=20, db=db)["items"]}


@router.get("/pick/writeoffs")
def pick_writeoffs(store_id: int, request: Request, db: Session = Depends(get_read_db)):
    """Open write-off requests (raised by outward returns) for a store, to be dealt with on a scrap document."""
    actor = store_actor(request, db, "store.control.view")
    _my_store(db, actor, store_id)
    rows = [w for w in store_outward.list_writeoff_requests(db, "OPEN") if w.store_id == store_id]
    items = _items(db, [w.item_id for w in rows])
    return {"items": [{"id": w.request_id, "item_id": w.item_id, "item_code": items[w.item_id].item_code, "item_name": items[w.item_id].item_name, "qty": svc.s3(w.qty), "reason": w.reason} for w in rows]}


@router.get("/pick/stores")
def pick_stores(request: Request, db: Session = Depends(get_read_db)):
    """Every active store of the company, for choosing where a transfer goes. A transfer may be sent to a store the sender does not
    work in; only receiving it needs access to that store."""
    actor = store_actor(request, db, "store.control.view")
    rows = db.query(DBStore).filter(DBStore.client_id == actor.client.id, DBStore.is_active.is_(True)).order_by(DBStore.code).all()
    return {"items": [{"id": s.id, "code": s.code, "name": s.name, "type": s.type, "project_id": s.project_id} for s in rows]}


@router.get("/in-transit")
def in_transit(request: Request, project_id: int = 0, db: Session = Depends(get_read_db)):
    """Stock sent from one store and not yet received at the other, with what it is worth."""
    actor = store_actor(request, db, "store.control.view")
    seen = _visible(db, actor)
    rows = svc.get_in_transit(db, project_id=project_id or None)
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.id.in_([r.from_store_id for r in rows] + [r.to_store_id for r in rows] or [0])).all()}
    items = _items(db, [r.item_id for r in rows])
    docs = {t.id: t for t in db.query(DBStoreTransfer).filter(DBStoreTransfer.id.in_([r.transfer_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        t = docs[r.transfer_id]
        if t.client_id != actor.client.id or (seen is not None and r.from_store_id not in seen and r.to_store_id not in seen):
            continue
        out.append({"transfer_id": t.id, "number": t.number, "from_store": stores[r.from_store_id].code, "to_store": stores[r.to_store_id].code, "item_id": r.item_id, "item_code": items[r.item_id].item_code,
                    "item_name": items[r.item_id].item_name, "qty": svc.s3(r.qty), "value": svc.s2(r.value), "dispatched_on": _iso(r.dispatched_on), "days": (date.today() - r.dispatched_on).days,
                    "inter_project": r.inter_project})
    total = sum((Decimal(r["value"]) for r in out), ZERO)
    return {"total": len(out), "total_value": svc.s2(total), "items": out}


@router.get("/count-variances")
def count_variances(store_id: int, request: Request, from_date: str = "", to_date: str = "", db: Session = Depends(get_read_db)):
    """What posted stock counts found against the books at a store."""
    actor = store_actor(request, db, "store.control.view")
    _my_store(db, actor, store_id)
    rows = svc.get_count_variances(db, store_id, svc.day(from_date, "From date", allow_future=True, required=False) or date(2000, 1, 1), svc.day(to_date, "To date", allow_future=True, required=False) or date.today())
    items = _items(db, [r.item_id for r in rows])
    counts = {c.id: c for c in db.query(DBStoreCount).filter(DBStoreCount.id.in_([r.count_id for r in rows] or [0])).all()}
    shown = [r for r in rows if r.variance_qty != 0]
    return {"store_id": store_id, "net_value": svc.s2(sum((r.variance_value for r in shown), ZERO)), "items": [
        {"count_id": r.count_id, "number": counts[r.count_id].number, "count_date": _iso(counts[r.count_id].count_date), "item_id": r.item_id, "item_code": items[r.item_id].item_code,
         "item_name": items[r.item_id].item_name, "system_qty": svc.s3(r.system_qty), "counted_qty": svc.s3(r.counted_qty), "variance_qty": svc.s3(r.variance_qty), "variance_value": svc.s2(r.variance_value)} for r in shown]}


@router.get("/scrap-realisation")
def scrap_realisation(request: Request, project_id: int = 0, from_date: str = "", to_date: str = "", db: Session = Depends(get_read_db)):
    """Scrap sold or written off: what it was worth in the books against what it fetched."""
    actor = store_actor(request, db, "store.control.view")
    if project_id and not db.query(models.DBJob.id).filter(models.DBJob.id == project_id, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(404, "Project not found")
    seen = _visible(db, actor)
    rows = svc.get_scrap_realisation(db, project_id or None, svc.day(from_date, "From date", allow_future=True, required=False) or date(2000, 1, 1), svc.day(to_date, "To date", allow_future=True, required=False) or date.today())
    docs = {s.id: s for s in db.query(DBStoreScrap).filter(DBStoreScrap.id.in_([r.scrap_doc_id for r in rows] or [0])).all()}
    items = _items(db, [r.item_id for r in rows])
    out = [r for r in rows if docs[r.scrap_doc_id].client_id == actor.client.id and (seen is None or docs[r.scrap_doc_id].store_id in seen)]
    return {"book_value": svc.s2(sum((r.book_value for r in out), ZERO)), "realised_value": svc.s2(sum((r.realised_value for r in out), ZERO)),
            "items": [{"scrap_doc_id": r.scrap_doc_id, "number": docs[r.scrap_doc_id].number, "date": _iso(docs[r.scrap_doc_id].scrap_date), "item_id": r.item_id, "item_code": items[r.item_id].item_code,
                       "item_name": items[r.item_id].item_name, "qty": svc.s3(r.qty), "book_value": svc.s2(r.book_value), "realised_value": svc.s2(r.realised_value),
                       "gain": svc.s2(r.realised_value - r.book_value)} for r in out]}


# --- listing ------------------------------------------------------------------------------------------------------------

@router.get("/{kind_key}")
def list_documents(kind_key: str, request: Request, status: str = "", store_id: int = 0, q: str = "", from_date: str = "", to_date: str = "", limit: int = 100, offset: int = 0,
                   db: Session = Depends(get_read_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.control.view")
    query = db.query(kind.header).filter(kind.header.client_id == actor.client.id)
    seen = _visible(db, actor)
    if seen is not None:
        mine = kind.header.store_id.in_(seen or {0})
        query = query.filter(or_(mine, DBStoreTransfer.to_store_id.in_(seen or {0})) if kind.key == "transfer" else mine)
    if store_id:
        _my_store(db, actor, store_id)
        query = query.filter(or_(kind.header.store_id == store_id, DBStoreTransfer.to_store_id == store_id) if kind.key == "transfer" else kind.header.store_id == store_id)
    if status:
        query = query.filter(kind.header.status == status.strip().upper())
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(kind.header.number.ilike(like))
    date_col = getattr(kind.header, kind.date_attr)
    if from_date:
        query = query.filter(date_col >= svc.day(from_date, "From date", allow_future=True))
    if to_date:
        query = query.filter(date_col <= svc.day(to_date, "To date", allow_future=True))
    total = query.count()
    rows = query.order_by(kind.header.id.desc()).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
    return {"total": total, "items": [doc_dict(db, kind, r, actor) for r in rows]}


@router.get("/{kind_key}/export")
def export_documents(kind_key: str, request: Request, status: str = "", store_id: int = 0, q: str = "", db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    rows = list_documents(kind_key, request, status=status, store_id=store_id, q=q, limit=500, db=db)["items"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = kind.label[:30]
    cols = ["number", "date", "status", "store_code"] + {"transfer": ["to_store_code", "receipt_status", "inter_project", "value"], "count": ["count_type", "counted", "line_count", "variance_value"],
                                                        "scrap": ["project", "buyer", "reference", "realised"]}[kind.key] + ["created_by", "remarks"]
    ws.append([c.replace("_", " ").title() for c in cols])
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="control-%s.xlsx"' % kind.key})


@router.get("/{kind_key}/{doc_id}")
def get_document(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_read_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.control.view")
    return doc_dict(db, kind, _doc(db, actor, kind, doc_id, either_end=True), actor, detail=True)


@router.get("/{kind_key}/{doc_id}/print")
def print_document(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_read_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.control.view")
    doc = _doc(db, actor, kind, doc_id, either_end=True)
    try:
        pdf = form_pdf.build_form_pdf(FORMS[kind.key][1](db, actor.client, doc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % doc.number.replace("/", "-")})


# --- transfers ----------------------------------------------------------------------------------------------------------

def _transfer_values(db, actor, body):
    src = svc.store_of(db, actor.client.id, body.store_id, "source store")
    assert_store_access(actor.user, src.id)
    dst = svc.store_of(db, actor.client.id, body.to_store_id, "destination store")
    if dst.id == src.id:
        raise HTTPException(400, "A transfer goes from one store to another, not to the same store.")
    return src, dst, svc.day(body.transfer_date, "Transfer date"), svc.build_transfer_lines(db, actor.client.id, body.lines)


@router.post("/transfer")
def create_transfer(body: TransferIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    src, dst, on, lines = _transfer_values(db, actor, body)
    doc = DBStoreTransfer(client_id=actor.client.id, store_id=src.id, to_store_id=dst.id, number=svc.numbered(db, "TRF", src.id, on), status=DocStatus.DRAFT.value,
                          transfer_date=on, vehicle_no=svc.text(body.vehicle_no, "vehicle number", 30), remarks=svc.text(body.remarks, "remarks", 500),
                          inter_project=1 if svc.is_inter_project(db, src.id, dst.id) else 0)
    db.add(doc)
    db.flush()
    svc.write_transfer_lines(db, doc, lines)
    _created(db, actor, svc.KINDS["transfer"], doc, request)
    db.commit()
    return doc_dict(db, svc.KINDS["transfer"], doc, actor, detail=True)


@router.put("/transfer/{doc_id}")
def edit_transfer(doc_id: int, body: TransferIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    doc = _doc(db, actor, svc.KINDS["transfer"], doc_id)
    _editable(doc)
    if body.store_id != doc.store_id:
        raise HTTPException(400, "A transfer cannot be moved to another source store; cancel it and make a new one.")
    src, dst, on, lines = _transfer_values(db, actor, body)
    doc.to_store_id, doc.transfer_date, doc.vehicle_no, doc.remarks = dst.id, on, svc.text(body.vehicle_no, "vehicle number", 30), svc.text(body.remarks, "remarks", 500)
    doc.inter_project = 1 if svc.is_inter_project(db, src.id, dst.id) else 0
    svc.write_transfer_lines(db, doc, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["transfer"], doc, actor, detail=True)


@router.post("/transfer/{doc_id}/receive")
def receive_transfer(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Receipt at the destination store: the stock that was in transit comes in at the rate it left at. Needs store.control.post and
    access to the destination store."""
    actor = store_actor(request, db, "store.control.post")
    kind = svc.KINDS["transfer"]
    doc = db.get(DBStoreTransfer, doc_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "Transfer not found")
    assert_store_access(actor.user, doc.to_store_id)
    try:
        with store_errors():
            svc.transfer_receive(db, actor, doc)
        log_audit(db, actor.client.id, "store_transfer_received", "store_doc", doc.id, doc.number, doc.receipt_status, request=request, **_who(actor))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, doc, actor, detail=True)


# --- stock counts --------------------------------------------------------------------------------------------------------

@router.post("/count")
def create_count(body: CountIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    on = svc.day(body.count_date, "Count date")
    ctype = (body.count_type or "FULL").strip().upper()
    if ctype not in ("FULL", "PARTIAL"):
        raise HTTPException(400, "A count is FULL or PARTIAL.")
    doc = DBStoreCount(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, COUNT, store.id, on), status=DocStatus.DRAFT.value, count_date=on, count_type=ctype,
                       remarks=svc.text(body.remarks, "remarks", 500))
    db.add(doc)
    db.flush()
    svc.count_scope(db, actor.client.id, doc, body.item_ids)
    _created(db, actor, svc.KINDS["count"], doc, request)
    db.commit()
    return doc_dict(db, svc.KINDS["count"], doc, actor, detail=True)


@router.post("/count/{doc_id}/start")
def start_count(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Freeze the store and take the snapshot of the books. Nothing leaves the store until the count is posted or cancelled; deliveries are
    still received, apart from the count."""
    actor = store_actor(request, db, "store.control.create")
    kind = svc.KINDS["count"]
    doc = _doc(db, actor, kind, doc_id)
    try:
        with store_errors():
            svc.count_start(db, actor, doc)
        log_audit(db, actor.client.id, "store_count_started", "store_doc", doc.id, doc.number, "frozen", request=request, **_who(actor))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, doc, actor, detail=True)


@router.put("/count/{doc_id}/sheet")
def count_sheet(doc_id: int, body: SheetIn, request: Request, db: Session = Depends(get_db)):
    """Enter what was counted. Can be called again to recount."""
    actor = store_actor(request, db, "store.control.create")
    kind = svc.KINDS["count"]
    doc = _doc(db, actor, kind, doc_id)
    try:
        svc.count_sheet(db, actor, doc, body.rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, doc, actor, detail=True)


# --- wastage and scrap ----------------------------------------------------------------------------------------------------

def _scrap_values(db, actor, body):
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    if body.project_id and not db.query(models.DBJob.id).filter(models.DBJob.id == body.project_id, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(400, "That project does not exist.")
    return store, svc.day(body.scrap_date, "Date"), svc.build_scrap_lines(db, actor.client.id, store.id, body.lines)


@router.post("/scrap")
def create_scrap(body: ScrapIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    store, on, lines = _scrap_values(db, actor, body)
    doc = DBStoreScrap(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, SCRAP, store.id, on), status=DocStatus.DRAFT.value, scrap_date=on, project_id=body.project_id or None,
                       buyer=svc.text(body.buyer, "buyer", 120), reference=svc.text(body.reference, "reference", 80), remarks=svc.text(body.remarks, "remarks", 500))
    db.add(doc)
    db.flush()
    svc.write_scrap_lines(db, doc, lines)
    _created(db, actor, svc.KINDS["scrap"], doc, request)
    db.commit()
    return doc_dict(db, svc.KINDS["scrap"], doc, actor, detail=True)


@router.put("/scrap/{doc_id}")
def edit_scrap(doc_id: int, body: ScrapIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    doc = _doc(db, actor, svc.KINDS["scrap"], doc_id)
    _editable(doc)
    if body.store_id != doc.store_id:
        raise HTTPException(400, "A document cannot be moved to another store; cancel it and make a new one.")
    _store, on, lines = _scrap_values(db, actor, body)
    doc.scrap_date, doc.project_id, doc.buyer = on, body.project_id or None, svc.text(body.buyer, "buyer", 120)
    doc.reference, doc.remarks = svc.text(body.reference, "reference", 80), svc.text(body.remarks, "remarks", 500)
    svc.write_scrap_lines(db, doc, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["scrap"], doc, actor, detail=True)


# --- the common end -------------------------------------------------------------------------------------------------------

@router.delete("/{kind_key}/{doc_id}")
def delete_draft(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Throw a draft away. Anything submitted, started or posted is cancelled instead, so its history stays."""
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.control.create")
    doc = _doc(db, actor, kind, doc_id)
    _editable(doc)
    if kind.key == "count" and doc.started_at is not None:
        raise HTTPException(409, "This count has been started and the store is frozen. Cancel it instead.")
    db.query(kind.line).filter(getattr(kind.line, kind.fk) == doc.id).delete(synchronize_session=False)
    db.query(DBStoreControlLog).filter(DBStoreControlLog.doc_type == kind.ref, DBStoreControlLog.doc_id == doc.id).delete(synchronize_session=False)
    number = doc.number
    db.delete(doc)
    log_audit(db, actor.client.id, "store_%s_deleted" % kind.key, "store_doc", doc_id, number, "draft", request=request, **_who(actor))
    db.commit()
    return {"message": "Draft deleted"}


@router.post("/{kind_key}/{doc_id}/{action}")
def act(kind_key: str, doc_id: int, action: str, request: Request, body: Optional[ActionIn] = None, db: Session = Depends(get_db)):
    """submit, approve, post or cancel (with a reason). Posting - and cancelling a posted document - moves stock in one transaction:
    if any line cannot move, nothing does."""
    kind = _kind(kind_key)
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "There is no such action.")
    actor = store_actor(request, db, ACTION_RIGHT[action])
    doc = _doc(db, actor, kind, doc_id)
    try:
        with store_errors():
            svc.advance(db, actor, kind, doc, action, body.reason if body else "", can_high_value=_has(actor, "store.control.approve_high_value"))
        log_audit(db, actor.client.id, "store_%s_%s" % (kind.key, action), "store_doc", doc.id, doc.number, doc.status, request=request, **_who(actor))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, doc, actor, detail=True)
