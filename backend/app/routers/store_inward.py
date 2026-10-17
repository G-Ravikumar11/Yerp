"""Store module - inward routes under /api/store/inward: goods receipts (grn), returns to the supplier (returns), material the
client supplies (client-supply) and opening stock (opening). Owned by P2.

Rights: store.inward.view reads; .create makes, edits, deletes drafts and submits; .approve approves and records the quality
check; .post posts to stock; .cancel cancels (a posted document is reversed). Every route works inside the stores the person
is assigned to. Posting is one transaction: every line moves stock or none does.
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
from app.db import get_db
from app.documents import form_pdf
from app.documents.store.inward_forms import FORMS
from app.models.store_core import DBStore, DBStoreUserAssignment, DocStatus
from app.models.store_inward import (
    CLIENT_SUPPLY, GRN, OPENING, PURCHASE_RETURN, DBStoreClientSupply, DBStoreGrn, DBStoreInwardLog, DBStoreOpening, DBStorePurchaseReturn,
)
from app.services import store_inward as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/inward", tags=["store-inward"])
ZERO = Decimal("0")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ACTION_RIGHT = {"submit": "store.inward.create", "approve": "store.inward.approve", "post": "store.inward.post", "cancel": "store.inward.cancel"}


# --- request bodies ---------------------------------------------------------------------------------------------------

class GrnLineIn(BaseModel):
    po_line_id: Optional[int] = None
    item_id: Optional[int] = None
    qty: str
    uom: str = ""
    rate: str = ""                       # per `uom`; the purchase order's price when left out
    rejected_qty: str = ""
    reject_reason: str = ""
    batch_no: str = ""
    bin_id: Optional[int] = None
    remarks: str = ""


class GrnIn(BaseModel):
    store_id: int
    grn_date: str
    po_id: Optional[int] = None
    supplier_name: str = ""
    challan_no: str = ""
    challan_date: str = ""
    vehicle_no: str = ""
    project_id: Optional[int] = None
    remarks: str = ""
    lines: List[GrnLineIn]


class QcIn(BaseModel):
    result: str
    rejected_qty: str = ""
    note: str = ""


class ReturnLineIn(BaseModel):
    grn_line_id: int
    qty: str
    uom: str = ""
    reason: str = ""


class ReturnIn(BaseModel):
    grn_id: int
    return_date: str
    reason: str = ""
    remarks: str = ""
    lines: List[ReturnLineIn]


class SupplyLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    rate: str = ""
    remarks: str = ""


class SupplyIn(BaseModel):
    store_id: int
    supply_date: str
    project_id: int
    work_order_id: Optional[int] = None
    client_ref: str = ""
    remarks: str = ""
    lines: List[SupplyLineIn]


class OpeningLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    rate: str


class OpeningIn(BaseModel):
    store_id: int
    as_on_date: str
    remarks: str = ""
    lines: List[OpeningLineIn]


class ActionIn(BaseModel):
    reason: str = ""


# --- helpers -----------------------------------------------------------------------------------------------------------

def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id,
                                                                            DBStoreUserAssignment.is_active.is_(True)).all()}


def _kind(key):
    kind = svc.KINDS.get(key)
    if kind is None:
        raise HTTPException(404, "Not found")
    return kind


def _doc(db, actor, kind, doc_id):
    doc = db.get(kind.header, doc_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "%s not found" % kind.label)
    assert_store_access(actor.user, doc.store_id)
    return doc


def _editable(doc, kind):
    if doc.status != DocStatus.DRAFT.value:
        raise HTTPException(409, "It is %s. Only a draft can be edited; cancel it and make a new one to correct it." % doc.status.lower())


def _iso(d):
    return d.isoformat() if d else ""


def _store_names(db, ids):
    return {s.id: s for s in db.query(DBStore).filter(DBStore.id.in_(list(ids) or [0])).all()}


def _head_dict(kind, doc, store):
    return {"kind": kind.key, "id": doc.id, "number": doc.number, "status": doc.status, "store_id": doc.store_id, "store_code": store.code if store else "",
            "store_name": store.name if store else "", "date": _iso(getattr(doc, kind.date_attr)), "remarks": doc.remarks or "", "cancel_reason": doc.cancel_reason or "",
            "created_by": doc.created_by_name or "", "created_at": doc.created_at.isoformat(timespec="seconds") if doc.created_at else "",
            "posted_at": doc.posted_at.isoformat(timespec="seconds") if doc.posted_at else ""}


def _items(db, ids):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(ids) or [0])).all()}


def _line_common(db, l, it, extra):
    return {"id": l.id, "item_id": l.item_id, "item_code": it.item_code if it else "", "item_name": it.item_name if it else "",
            "base_uom": svc.base_uom_of(db, it) if it else "", "entry_uom": l.entry_uom or "", "entry_qty": svc.s3(l.entry_qty), **extra}


def doc_dict(db, kind, doc, detail=False):
    store = db.get(DBStore, doc.store_id)
    out = _head_dict(kind, doc, store)
    if kind.key == "grn":
        po = db.get(models.DBPurchaseOrder, doc.po_id) if doc.po_id else None
        job = db.get(models.DBJob, doc.project_id) if doc.project_id else None
        lines = svc.grn_lines(db, doc)
        value = sum((Decimal(str(l.accepted_qty)) * Decimal(str(l.rate)) for l in lines), ZERO)
        out.update({"po_id": doc.po_id, "po_number": po.number if po else "", "supplier_name": doc.supplier_name or "", "challan_no": doc.challan_no or "",
                    "challan_date": _iso(doc.challan_date), "vehicle_no": doc.vehicle_no or "", "project_id": doc.project_id,
                    "project": ("%s - %s" % (job.number, job.name)) if job else "", "line_count": len(lines), "value": format(value.quantize(Decimal("0.01")), "f"),
                    "qc_pending": sum(1 for l in lines if l.qc_status == "PENDING")})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [_line_common(db, l, items.get(l.item_id), {"po_line_id": l.po_line_id, "received_qty": svc.s3(l.received_qty), "accepted_qty": svc.s3(l.accepted_qty),
                                                                       "rejected_qty": svc.s3(l.rejected_qty), "rate": svc.s4(l.rate), "qc_status": l.qc_status, "qc_by": l.qc_by_name or "",
                                                                       "qc_note": l.qc_note or "", "reject_reason": l.reject_reason or "", "batch_no": l.batch_no or "", "bin_id": l.bin_id,
                                                                       "remarks": l.remarks or ""}) for l in lines]
    elif kind.key == "returns":
        grn = db.get(DBStoreGrn, doc.grn_id)
        lines = svc.return_lines(db, doc)
        out.update({"grn_id": doc.grn_id, "grn_number": grn.number if grn else "", "supplier_name": doc.supplier_name or "", "reason": doc.reason or "", "line_count": len(lines)})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [_line_common(db, l, items.get(l.item_id), {"grn_line_id": l.grn_line_id, "qty": svc.s3(l.qty), "reason": l.reason or ""}) for l in lines]
    elif kind.key == "client-supply":
        job = db.get(models.DBJob, doc.project_id)
        lines = svc.supply_lines(db, doc)
        out.update({"project_id": doc.project_id, "project": ("%s - %s" % (job.number, job.name)) if job else "", "work_order_id": doc.work_order_id, "client_ref": doc.client_ref or "",
                    "line_count": len(lines)})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [_line_common(db, l, items.get(l.item_id), {"qty": svc.s3(l.qty), "rate": svc.s4(l.rate), "remarks": l.remarks or ""}) for l in lines]
    else:
        lines = svc.opening_lines(db, doc)
        out.update({"line_count": len(lines), "value": format(sum((Decimal(str(l.qty)) * Decimal(str(l.rate)) for l in lines), ZERO).quantize(Decimal("0.01")), "f")})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [_line_common(db, l, items.get(l.item_id), {"qty": svc.s3(l.qty), "rate": svc.s4(l.rate)}) for l in lines]
    if detail:
        out["history"] = [{"action": h.action, "from": h.from_status, "to": h.to_status, "by": h.user_name, "at": h.at.isoformat(timespec="seconds") if h.at else "", "note": h.note or ""}
                          for h in db.query(DBStoreInwardLog).filter(DBStoreInwardLog.doc_type == kind.ref, DBStoreInwardLog.doc_id == doc.id).order_by(DBStoreInwardLog.id).all()]
    return out


def _created(db, actor, kind, doc, request):
    doc.created_by_id, doc.created_by_name = actor.user_id, actor.name
    db.flush()
    svc.log(db, actor, kind.ref, doc.id, "create", "", doc.status)
    log_audit(db, actor.client.id, "store_%s_created" % kind.key.replace("-", "_"), "store_doc", doc.id, doc.number, "", request=request,
              user_type="employee" if actor.employee is not None else "client", user_name=actor.name)


# --- the front door and pickers -----------------------------------------------------------------------------------------

@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: the latest goods receipts this person may see."""
    return {"slice": "inward", "items": list_documents("grn", request, limit=20, db=db)["items"]}


@router.get("/po-options")
def po_options(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Approved purchase orders with something still to receive, line by line with the quantity pending."""
    actor = store_actor(request, db, "store.inward.view")
    return {"items": svc.open_purchase_orders(db, actor.client.id, q=q)}


@router.get("/po-summary/{po_id}")
def po_summary(po_id: int, request: Request, db: Session = Depends(get_db)):
    """Received / accepted / rejected / pending per line of one purchase order (posted receipts only)."""
    actor = store_actor(request, db, "store.inward.view")
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None or po.client_id != actor.client.id:
        raise HTTPException(404, "Purchase order not found")
    return {"po_id": po.id, "number": po.number, "lines": [{"po_line_id": s.po_line_id, "item_id": s.item_id, "ordered_qty": svc.s3(s.ordered_qty), "received_qty": svc.s3(s.received_qty),
                                                              "accepted_qty": svc.s3(s.accepted_qty), "rejected_qty": svc.s3(s.rejected_qty), "pending_qty": svc.s3(s.pending_qty)}
                                                             for s in svc.get_po_receipt_summary(db, po.id)]}


@router.get("/grn-lines/{grn_id}")
def returnable_lines(grn_id: int, request: Request, db: Session = Depends(get_db)):
    """What can still be sent back from a posted receipt, line by line."""
    actor = store_actor(request, db, "store.inward.view")
    grn = _doc(db, actor, svc.KINDS["grn"], grn_id)
    lines = svc.grn_lines(db, grn)
    already = svc._returned_by_grn_line(db, [l.id for l in lines], svc.LIVE)
    items = _items(db, [l.item_id for l in lines])
    return {"grn": {"id": grn.id, "number": grn.number, "status": grn.status, "store_id": grn.store_id, "supplier_name": grn.supplier_name or ""},
            "lines": [{"grn_line_id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                       "accepted": svc.s3(l.accepted_qty), "returnable": svc.s3(max(ZERO, Decimal(str(l.accepted_qty)) - already.get(l.id, ZERO)))} for l in lines]}


# --- listing ------------------------------------------------------------------------------------------------------------

@router.get("/{kind_key}")
def list_documents(kind_key: str, request: Request, status: str = "", store_id: int = 0, q: str = "", from_date: str = "", to_date: str = "", po_id: int = 0,
                   limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.inward.view")
    query = db.query(kind.header).filter(kind.header.client_id == actor.client.id)
    seen = _visible(db, actor)
    if seen is not None:
        query = query.filter(kind.header.store_id.in_(seen or {0}))
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(kind.header.store_id == store_id)
    if status:
        query = query.filter(kind.header.status == status.strip().upper())
    term = (q or "").strip()
    date_col = getattr(kind.header, kind.date_attr)
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        cond = [kind.header.number.ilike(like)]
        if kind.key in ("grn", "returns"):
            cond.append(kind.header.supplier_name.ilike(like))
        query = query.filter(or_(*cond))
    if from_date:
        query = query.filter(date_col >= svc.day(from_date, "From date", allow_future=True))
    if to_date:
        query = query.filter(date_col <= svc.day(to_date, "To date", allow_future=True))
    if po_id and kind.key == "grn":
        query = query.filter(DBStoreGrn.po_id == po_id)
    total = query.count()
    rows = query.order_by(kind.header.id.desc()).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
    stores = _store_names(db, {r.store_id for r in rows})
    return {"total": total, "items": [{**doc_dict(db, kind, r), "store_code": stores[r.store_id].code if r.store_id in stores else ""} for r in rows]}


@router.get("/{kind_key}/export")
def export_documents(kind_key: str, request: Request, status: str = "", store_id: int = 0, q: str = "", db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    rows = list_documents(kind_key, request, status=status, store_id=store_id, q=q, limit=500, db=db)["items"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = kind.label[:30]
    cols = ["number", "date", "status", "store_code"] + {"grn": ["po_number", "supplier_name", "challan_no", "project", "value"], "returns": ["grn_number", "supplier_name", "reason"],
                                                         "client-supply": ["project", "client_ref"], "opening": ["value"]}[kind.key] + ["line_count", "created_by", "remarks"]
    ws.append([c.replace("_", " ").title() for c in cols])
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="inward-%s.xlsx"' % kind.key})


@router.get("/{kind_key}/{doc_id}")
def get_document(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.inward.view")
    return doc_dict(db, kind, _doc(db, actor, kind, doc_id), detail=True)


@router.get("/{kind_key}/{doc_id}/print")
def print_document(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """The printed form of the document, as a PDF."""
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.inward.view")
    doc = _doc(db, actor, kind, doc_id)
    try:
        pdf = form_pdf.build_form_pdf(FORMS[kind.key][1](db, actor.client, doc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % doc.number.replace("/", "-")})


# --- making and editing -------------------------------------------------------------------------------------------------

def _grn_header(db, actor, body, grn=None):
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    on = svc.day(body.grn_date, "Receipt date")
    po = svc._po_for(db, actor.client.id, body.po_id) if body.po_id else None
    supplier = svc.text(body.supplier_name, "supplier", 120) or (po.supplier_name if po else "")
    if not supplier:
        raise HTTPException(400, "Give the supplier.")
    project = body.project_id or (po.job_id if po else None)
    svc.check_project(db, actor.client.id, project)
    challan_date = svc.day(body.challan_date, "Challan date", required=False)
    lines = svc.build_grn_lines(db, actor.client.id, po, body.lines)
    svc.check_over_receipt(db, po, lines, exclude_grn=grn.id if grn else None)
    return store, on, po, supplier, project, challan_date, lines


def _fill_grn(grn, body, on, po, supplier, project, challan_date):
    grn.grn_date, grn.po_id, grn.supplier_name, grn.project_id = on, po.id if po else None, supplier, project
    grn.challan_no, grn.challan_date, grn.vehicle_no = svc.text(body.challan_no, "challan number", 60), challan_date, svc.text(body.vehicle_no, "vehicle number", 30)
    grn.remarks = svc.text(body.remarks, "remarks", 500)


@router.post("/grn")
def create_grn(body: GrnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    store, on, po, supplier, project, challan_date, lines = _grn_header(db, actor, body)
    grn = DBStoreGrn(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, GRN, store.id, on), status=DocStatus.DRAFT.value)
    _fill_grn(grn, body, on, po, supplier, project, challan_date)
    db.add(grn)
    db.flush()
    svc.write_grn_lines(db, grn, lines)
    _created(db, actor, svc.KINDS["grn"], grn, request)
    db.commit()
    return doc_dict(db, svc.KINDS["grn"], grn, detail=True)


@router.put("/grn/{doc_id}")
def edit_grn(doc_id: int, body: GrnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    grn = _doc(db, actor, svc.KINDS["grn"], doc_id)
    _editable(grn, svc.KINDS["grn"])
    if body.store_id != grn.store_id:
        raise HTTPException(400, "A receipt cannot be moved to another store; cancel it and make a new one.")
    _store, on, po, supplier, project, challan_date, lines = _grn_header(db, actor, body, grn)
    _fill_grn(grn, body, on, po, supplier, project, challan_date)
    svc.write_grn_lines(db, grn, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["grn"], grn, detail=True)


@router.post("/grn/{doc_id}/qc/{line_id}")
def record_qc(doc_id: int, line_id: int, body: QcIn, request: Request, db: Session = Depends(get_db)):
    """The quality check of one line: PASSED (optionally rejecting part of it) or FAILED."""
    actor = store_actor(request, db, "store.inward.approve")
    grn = _doc(db, actor, svc.KINDS["grn"], doc_id)
    svc.qc_decide(db, actor, grn, line_id, body.result, body.rejected_qty, body.note)
    db.commit()
    return doc_dict(db, svc.KINDS["grn"], grn, detail=True)


@router.post("/returns")
def create_return(body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    grn = _doc(db, actor, svc.KINDS["grn"], body.grn_id)
    on = svc.day(body.return_date, "Return date")
    lines = svc.build_return_lines(db, actor.client.id, grn, body.lines)
    ret = DBStorePurchaseReturn(client_id=actor.client.id, store_id=grn.store_id, number=svc.numbered(db, PURCHASE_RETURN, grn.store_id, on), status=DocStatus.DRAFT.value,
                                return_date=on, grn_id=grn.id, supplier_name=grn.supplier_name or "", reason=svc.text(body.reason, "reason", 200), remarks=svc.text(body.remarks, "remarks", 500))
    db.add(ret)
    db.flush()
    svc.write_return_lines(db, ret, lines)
    _created(db, actor, svc.KINDS["returns"], ret, request)
    db.commit()
    return doc_dict(db, svc.KINDS["returns"], ret, detail=True)


@router.put("/returns/{doc_id}")
def edit_return(doc_id: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    ret = _doc(db, actor, svc.KINDS["returns"], doc_id)
    _editable(ret, svc.KINDS["returns"])
    if body.grn_id != ret.grn_id:
        raise HTTPException(400, "A return cannot be moved to another receipt; cancel it and make a new one.")
    grn = _doc(db, actor, svc.KINDS["grn"], ret.grn_id)
    on = svc.day(body.return_date, "Return date")
    lines = svc.build_return_lines(db, actor.client.id, grn, body.lines, return_id=ret.id)
    ret.return_date, ret.reason, ret.remarks = on, svc.text(body.reason, "reason", 200), svc.text(body.remarks, "remarks", 500)
    svc.write_return_lines(db, ret, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["returns"], ret, detail=True)


def _supply_header(db, actor, body):
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    on = svc.day(body.supply_date, "Receipt date")
    svc.check_project(db, actor.client.id, body.project_id)
    if not body.project_id:
        raise HTTPException(400, "Choose the project the client's material is for.")
    if body.work_order_id and not db.query(models.DBWorkOrder.id).filter(models.DBWorkOrder.id == body.work_order_id, models.DBWorkOrder.client_id == actor.client.id,
                                                                         models.DBWorkOrder.job_id == body.project_id).first():
        raise HTTPException(400, "That work order is not one of this project's.")
    return store, on, svc.build_supply_lines(db, actor.client.id, body.lines)


@router.post("/client-supply")
def create_supply(body: SupplyIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    store, on, lines = _supply_header(db, actor, body)
    doc = DBStoreClientSupply(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, CLIENT_SUPPLY, store.id, on), status=DocStatus.DRAFT.value, supply_date=on,
                              project_id=body.project_id, work_order_id=body.work_order_id or None, client_ref=svc.text(body.client_ref, "client reference", 80),
                              remarks=svc.text(body.remarks, "remarks", 500))
    db.add(doc)
    db.flush()
    svc.write_supply_lines(db, doc, lines)
    _created(db, actor, svc.KINDS["client-supply"], doc, request)
    db.commit()
    return doc_dict(db, svc.KINDS["client-supply"], doc, detail=True)


@router.put("/client-supply/{doc_id}")
def edit_supply(doc_id: int, body: SupplyIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    doc = _doc(db, actor, svc.KINDS["client-supply"], doc_id)
    _editable(doc, svc.KINDS["client-supply"])
    if body.store_id != doc.store_id:
        raise HTTPException(400, "A receipt cannot be moved to another store; cancel it and make a new one.")
    _store, on, lines = _supply_header(db, actor, body)
    doc.supply_date, doc.project_id, doc.work_order_id = on, body.project_id, body.work_order_id or None
    doc.client_ref, doc.remarks = svc.text(body.client_ref, "client reference", 80), svc.text(body.remarks, "remarks", 500)
    svc.write_supply_lines(db, doc, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["client-supply"], doc, detail=True)


def _opening_header(db, actor, body):
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    return store, svc.day(body.as_on_date, "As-on date"), svc.build_opening_lines(db, actor.client.id, body.lines)


@router.post("/opening")
def create_opening(body: OpeningIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    store, on, lines = _opening_header(db, actor, body)
    doc = DBStoreOpening(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, OPENING, store.id, on), status=DocStatus.DRAFT.value, as_on_date=on,
                         remarks=svc.text(body.remarks, "remarks", 500))
    db.add(doc)
    db.flush()
    svc.write_opening_lines(db, doc, lines)
    _created(db, actor, svc.KINDS["opening"], doc, request)
    db.commit()
    return doc_dict(db, svc.KINDS["opening"], doc, detail=True)


@router.put("/opening/{doc_id}")
def edit_opening(doc_id: int, body: OpeningIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    doc = _doc(db, actor, svc.KINDS["opening"], doc_id)
    _editable(doc, svc.KINDS["opening"])
    if body.store_id != doc.store_id:
        raise HTTPException(400, "A sheet cannot be moved to another store; cancel it and make a new one.")
    _store, on, lines = _opening_header(db, actor, body)
    doc.as_on_date, doc.remarks = on, svc.text(body.remarks, "remarks", 500)
    svc.write_opening_lines(db, doc, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["opening"], doc, detail=True)


@router.delete("/{kind_key}/{doc_id}")
def delete_draft(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Throw a draft away. Anything submitted or posted is cancelled instead, so its history stays."""
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.inward.create")
    doc = _doc(db, actor, kind, doc_id)
    _editable(doc, kind)
    db.query(kind.line).filter(getattr(kind.line, kind.fk) == doc.id).delete(synchronize_session=False)
    db.query(DBStoreInwardLog).filter(DBStoreInwardLog.doc_type == kind.ref, DBStoreInwardLog.doc_id == doc.id).delete(synchronize_session=False)
    number = doc.number
    db.delete(doc)
    log_audit(db, actor.client.id, "store_%s_deleted" % kind.key.replace("-", "_"), "store_doc", doc_id, number, "draft", request=request,
              user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
    db.commit()
    return {"message": "Draft deleted"}


# --- the lifecycle ------------------------------------------------------------------------------------------------------

@router.post("/{kind_key}/{doc_id}/{action}")
def act(kind_key: str, doc_id: int, action: str, request: Request, body: Optional[ActionIn] = None, db: Session = Depends(get_db)):
    """submit, approve, post or cancel (with a reason). Posting and cancelling a posted document move stock in one
    transaction: if any line cannot move, nothing does."""
    kind = _kind(kind_key)
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "There is no such action.")
    actor = store_actor(request, db, ACTION_RIGHT[action])
    doc = _doc(db, actor, kind, doc_id)
    try:
        with store_errors():
            svc.advance(db, actor, kind, doc, action, body.reason if body else "")
        log_audit(db, actor.client.id, "store_%s_%s" % (kind.key.replace("-", "_"), action), "store_doc", doc.id, doc.number, doc.status, request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, doc, detail=True)
