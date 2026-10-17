"""Store module - control routes under /api/store/control. Owned by P4.

Transfers (/transfers), stock counts (/counts), adjustments (/adjustments) and scrap (/scrap). Rights: view; create = draft, edit,
submit; approve; post; cancel. Extra rights: approve_high_value (inter-project and high-value transfers, large differences and
adjustments) and reveal_count (see the books during a count). Receiving a transfer needs store.control.post at the receiving store.
"""
import re
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.permissions import permissions_for
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.documents import form_pdf
from app.documents.store.control_forms import (
    adjustment_form_spec, count_form_spec, scrap_form_spec, transfer_form_spec, variance_form_spec, writeoff_form_spec,
)
from app.models.store_control import (
    AdjustmentReason, DBStoreAdjustment, DBStoreCount, DBStoreScrap, DBStoreTransfer, ScrapClass, WastageReason,
)
from app.models.store_core import DBStore, DocStatus
from app.routers.store_masters import accessible_store_ids
from app.services import store_control as svc
from app.services import store_outward
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/control", tags=["store-control"])

ACTION_RIGHT = {"submit": "create", "approve": "approve", "post": "post", "cancel": "cancel"}


class LineIn(BaseModel):
    item_id: Optional[int] = None
    qty: Optional[str] = None
    uom: Optional[str] = None
    scrap_class: Optional[str] = None
    direction: Optional[str] = None
    rate: Optional[str] = None
    realised_value: Optional[str] = None
    writeoff_request_id: Optional[int] = None
    counted_qty: Optional[str] = None
    remarks: Optional[str] = None


class TransferIn(BaseModel):
    store_id: Optional[int] = None
    to_store_id: Optional[int] = None
    trf_date: Optional[str] = None
    vehicle_no: Optional[str] = None
    driver_name: Optional[str] = None
    challan_no: Optional[str] = None
    challan_date: Optional[str] = None
    remarks: Optional[str] = None
    lines: Optional[List[LineIn]] = None


class LossIn(BaseModel):
    qty: Optional[str] = None
    reason: Optional[str] = None
    remarks: Optional[str] = None


class ReceiveIn(BaseModel):
    received: dict = {}
    losses: Dict[str, LossIn] = {}
    remarks: str = ""


class RecountIn(BaseModel):
    line_ids: List[int]
    reason: str = ""


class CountIn(BaseModel):
    store_id: Optional[int] = None
    count_date: Optional[str] = None
    item_ids: Optional[List[int]] = None
    categories: Optional[List[str]] = None
    bin_id: Optional[int] = None
    remarks: Optional[str] = None
    lines: Optional[List[LineIn]] = None


class AdjustmentIn(BaseModel):
    store_id: Optional[int] = None
    adj_date: Optional[str] = None
    kind: Optional[str] = None
    reason: Optional[str] = None
    reason_code: Optional[str] = None
    attachment_ref: Optional[str] = None
    project_id: Optional[int] = None
    cost_head: Optional[str] = None
    lines: Optional[List[LineIn]] = None


class ScrapIn(BaseModel):
    store_id: Optional[int] = None
    scrap_date: Optional[str] = None
    project_id: Optional[int] = None
    buyer: Optional[str] = None
    gate_pass_no: Optional[str] = None
    reason: Optional[str] = None
    lines: Optional[List[LineIn]] = None


class ActionIn(BaseModel):
    reason: str = ""


def _body(m: BaseModel) -> dict:
    return m.model_dump(exclude_unset=True)


def _can(actor, key: str) -> bool:
    """The account holder holds every right; staff hold it by permission or store.admin."""
    if actor.employee is None:
        return True
    held = permissions_for(actor.employee)
    return key in held or "store.admin" in held


def _commit(db, fn):
    try:
        with store_errors():
            out = fn()
        db.commit()
        return out
    except BaseException:
        db.rollback()
        raise


def _store(db, actor, store_id):
    if not store_id:
        raise HTTPException(400, "Choose a store.")
    assert_store_access(actor.user, store_id)
    store = db.get(DBStore, store_id)
    if not store.is_active:
        raise HTTPException(400, "Store %s is switched off." % store.code)
    return store


def _doc(db, actor, model, doc_id):
    doc = db.get(model, doc_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "Document not found")
    try:
        assert_store_access(actor.user, doc.store_id)
    except HTTPException:
        # the receiving store may see a transfer coming to it
        if not isinstance(doc, DBStoreTransfer):
            raise
        assert_store_access(actor.user, doc.to_store_id)
    return doc


def _list(db, actor, model, store_id, status, q, from_date, to_date, limit, offset, date_col):
    query = db.query(model).filter(model.client_id == actor.client.id)
    mine = accessible_store_ids(actor, db)
    is_trf = model is DBStoreTransfer
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(or_(model.store_id == store_id, model.to_store_id == store_id) if is_trf else model.store_id == store_id)
    elif mine is not None:
        ids = mine or [0]
        query = query.filter(or_(model.store_id.in_(ids), model.to_store_id.in_(ids)) if is_trf else model.store_id.in_(ids))
    if status:
        if status not in {s.value for s in DocStatus}:
            raise HTTPException(400, "Unknown status.")
        query = query.filter(model.status == status)
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        query = query.filter(model.number.ilike("%" + term + "%"))
    if from_date:
        query = query.filter(date_col >= svc.to_date(from_date, "From date"))
    if to_date:
        query = query.filter(date_col <= svc.to_date(to_date, "To date"))
    return query.count(), query.order_by(model.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 200))).all()


def _pdf(db, actor, doc, spec_fn):
    if not form_pdf.PDF_AVAILABLE:
        raise HTTPException(503, "The PDF library is not installed on this server.")
    pdf = form_pdf.build_form_pdf(spec_fn(db, actor.client, doc))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % re.sub(r"[^A-Za-z0-9]+", "_", doc.number).strip("_")})


def _act(request, db, action, model, doc_id):
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "Unknown action")
    actor = store_actor(request, db, "store.control." + ACTION_RIGHT[action])
    return actor, _doc(db, actor, model, doc_id)


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door (kept as the skeleton's smoke test expects); the documents are under /transfers, /counts, /adjustments and /scrap."""
    store_actor(request, db, "store.control.view")
    return {"slice": "control", "items": []}


@router.get("/meta")
def meta(request: Request, db: Session = Depends(get_db)):
    """The reason codes and classes the screens offer."""
    store_actor(request, db, "store.control.view")
    return {"adjustment_reasons": [e.value for e in AdjustmentReason], "wastage_reasons": [e.value for e in WastageReason], "scrap_classes": [e.value for e in ScrapClass],
            "high_value_limit": str(svc.HIGH_VALUE_LIMIT)}


@router.get("/reorder-alerts")
def reorder_alerts(request: Request, store_id: int = 0, format: str = "json", db: Session = Depends(get_db)):
    """Items at or below their reorder level per store, with suggested qty = max - (on hand + pending on purchase orders). Export only: nothing is ordered."""
    actor = store_actor(request, db, "store.control.view")
    if store_id:
        assert_store_access(actor.user, store_id)
        stores = [db.get(DBStore, store_id)]
    else:
        mine = accessible_store_ids(actor, db)
        q = db.query(DBStore).filter(DBStore.client_id == actor.client.id, DBStore.is_active.is_(True))
        stores = (q.filter(DBStore.id.in_(mine or [0])) if mine is not None else q).order_by(DBStore.code).all()
    rows = svc.get_reorder_alerts(db, actor.client.id, stores)
    if format == "json":
        return {"rows": rows}
    if format == "xlsx":
        return Response(svc.reorder_xlsx(rows, actor.client.company_name or ""), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="reorder_alerts.xlsx"'})
    raise HTTPException(400, "format must be json or xlsx.")


# ------------------------------------------------------------------------------------------------ transfers
@router.get("/transfers")
def list_transfers(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                   limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    total, rows = _list(db, actor, DBStoreTransfer, store_id, status, q, from_date, to_date, limit, offset, DBStoreTransfer.trf_date)
    return {"total": total, "rows": [svc.transfer_dict(db, r, with_lines=False) for r in rows]}


@router.get("/in-transit")
def in_transit(request: Request, project_id: int = 0, db: Session = Depends(get_db)):
    """Dispatched transfers not yet received, for the stores the person can reach."""
    actor = store_actor(request, db, "store.control.view")
    mine = accessible_store_ids(actor, db)
    seen, rows = set(), []
    for r in svc.get_in_transit(db, project_id=project_id or None):
        if r.transfer_id in seen:
            continue
        t = db.get(DBStoreTransfer, r.transfer_id)
        if t.client_id != actor.client.id or (mine is not None and t.store_id not in mine and t.to_store_id not in mine):
            continue
        seen.add(r.transfer_id)
        rows.append(svc.transfer_dict(db, t, with_lines=False))
    return {"rows": rows}


@router.post("/transfers", status_code=201)
def create_transfer(body: TransferIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    store = _store(db, actor, body.store_id)
    return svc.transfer_dict(db, _commit(db, lambda: svc.create_transfer(db, actor, store, _body(body))))


@router.get("/transfers/{doc_id}")
def get_transfer(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    return svc.transfer_dict(db, _doc(db, actor, DBStoreTransfer, doc_id))


@router.put("/transfers/{doc_id}")
def edit_transfer(doc_id: int, body: TransferIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    t = _doc(db, actor, DBStoreTransfer, doc_id)
    _commit(db, lambda: svc.update_transfer(db, actor, t, db.get(DBStore, t.store_id), _body(body)))
    return svc.transfer_dict(db, t)


@router.post("/transfers/{doc_id}/receive")
def receive_transfer(doc_id: int, request: Request, body: ReceiveIn = ReceiveIn(), db: Session = Depends(get_db)):
    """The receiving store confirms what arrived (default: all of it); a shortage goes back to the sender."""
    actor = store_actor(request, db, "store.control.post")
    t = db.get(DBStoreTransfer, doc_id)
    if t is None or t.client_id != actor.client.id:
        raise HTTPException(404, "Document not found")
    assert_store_access(actor.user, t.to_store_id)
    _commit(db, lambda: svc.receive_transfer(db, actor, t, {int(k): v for k, v in body.received.items()}, {int(k): v.model_dump(exclude_none=True) for k, v in body.losses.items()}, body.remarks))
    return svc.transfer_dict(db, t)


@router.post("/transfers/{doc_id}/approve-loss")
def approve_transfer_loss(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Approve the loss in transit reported at receipt: it is posted as wastage on the transfer document."""
    actor = store_actor(request, db, "store.control.approve")
    t = _doc(db, actor, DBStoreTransfer, doc_id)
    _commit(db, lambda: svc.approve_transfer_loss(db, actor, t, can_high=_can(actor, "store.control.approve_high_value")))
    return svc.transfer_dict(db, t)


@router.post("/transfers/{doc_id}/{action}")
def transfer_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    actor, t = _act(request, db, action, DBStoreTransfer, doc_id)
    if action in ("submit", "approve", "post"):
        assert_store_access(actor.user, t.store_id)               # the sender's side moves the stock
    _commit(db, lambda: svc.transfer_action(db, actor, t, action, body.reason, can_high=_can(actor, "store.control.approve_high_value")))
    return svc.transfer_dict(db, t)


@router.get("/transfers/{doc_id}/pdf")
def transfer_pdf(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    return _pdf(db, actor, _doc(db, actor, DBStoreTransfer, doc_id), transfer_form_spec)


# ------------------------------------------------------------------------------------------------ counts
@router.get("/counts")
def list_counts(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    total, rows = _list(db, actor, DBStoreCount, store_id, status, q, from_date, to_date, limit, offset, DBStoreCount.count_date)
    reveal = _can(actor, "store.control.reveal_count")
    return {"total": total, "rows": [svc.count_dict(db, r, with_lines=False, reveal=reveal) for r in rows]}


@router.post("/counts", status_code=201)
def create_count(body: CountIn, request: Request, db: Session = Depends(get_db)):
    """Starts a count: the store is frozen and the books are snapshotted."""
    actor = store_actor(request, db, "store.control.create")
    store = _store(db, actor, body.store_id)
    return svc.count_dict(db, _commit(db, lambda: svc.create_count(db, actor, store, _body(body))), reveal=_can(actor, "store.control.reveal_count"))


@router.get("/counts/{doc_id}")
def get_count(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    return svc.count_dict(db, _doc(db, actor, DBStoreCount, doc_id), reveal=_can(actor, "store.control.reveal_count"))


@router.put("/counts/{doc_id}")
def enter_counts(doc_id: int, body: CountIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    c = _doc(db, actor, DBStoreCount, doc_id)
    _commit(db, lambda: svc.update_count(db, actor, c, db.get(DBStore, c.store_id), _body(body)))
    return svc.count_dict(db, c, reveal=_can(actor, "store.control.reveal_count"))


@router.post("/counts/{doc_id}/recount")
def recount(doc_id: int, body: RecountIn, request: Request, db: Session = Depends(get_db)):
    """Send some lines of a submitted count back to be counted again."""
    actor = store_actor(request, db, "store.control.approve")
    c = _doc(db, actor, DBStoreCount, doc_id)
    _commit(db, lambda: svc.request_recount(db, actor, c, body.line_ids, body.reason))
    return svc.count_dict(db, c, reveal=_can(actor, "store.control.reveal_count"))


@router.post("/counts/{doc_id}/{action}")
def count_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    actor, c = _act(request, db, action, DBStoreCount, doc_id)
    _commit(db, lambda: svc.count_action(db, actor, c, action, body.reason, can_high=_can(actor, "store.control.approve_high_value")))
    return svc.count_dict(db, c, reveal=_can(actor, "store.control.reveal_count"))


@router.get("/counts/{doc_id}/pdf")
def count_pdf(doc_id: int, request: Request, form: str = "sheet", db: Session = Depends(get_db)):
    """form=sheet (the count sheet, blind until approved) or form=variance (the variance statement, quantity and value)."""
    actor = store_actor(request, db, "store.control.view")
    c = _doc(db, actor, DBStoreCount, doc_id)
    if form not in ("sheet", "variance"):
        raise HTTPException(400, "form must be sheet or variance.")
    if form == "variance" and c.status not in (DocStatus.APPROVED.value, DocStatus.POSTED.value) and not _can(actor, "store.control.reveal_count"):
        raise HTTPException(403, "The variance statement is printed once the count is approved.")
    return _pdf(db, actor, c, variance_form_spec if form == "variance" else count_form_spec)


# ------------------------------------------------------------------------------------------------ adjustments
@router.get("/writeoff-requests")
def open_writeoffs(request: Request, store_id: int = 0, db: Session = Depends(get_db)):
    """Open write-off requests from the outward slice that an adjustment of kind WRITEOFF can close."""
    actor = store_actor(request, db, "store.control.view")
    mine = accessible_store_ids(actor, db)
    rows = []
    for r in store_outward.list_writeoff_requests(db, "OPEN"):
        st = db.get(DBStore, r.store_id)
        if st.client_id != actor.client.id or (mine is not None and r.store_id not in mine) or (store_id and r.store_id != store_id):
            continue
        from app import models
        item = db.get(models.DBItem, r.item_id)
        rows.append({"request_id": r.request_id, "store_id": r.store_id, "store_code": st.code, "item_id": r.item_id, "item_code": item.item_code, "item_name": item.item_name,
                     "qty": str(r.qty), "reason": r.reason})
    return {"rows": rows}


@router.get("/adjustments")
def list_adjustments(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                     limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    total, rows = _list(db, actor, DBStoreAdjustment, store_id, status, q, from_date, to_date, limit, offset, DBStoreAdjustment.adj_date)
    return {"total": total, "rows": [svc.adjustment_dict(db, r, with_lines=False) for r in rows]}


@router.post("/adjustments", status_code=201)
def create_adjustment(body: AdjustmentIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    store = _store(db, actor, body.store_id)
    return svc.adjustment_dict(db, _commit(db, lambda: svc.create_adjustment(db, actor, store, _body(body))))


@router.get("/adjustments/{doc_id}")
def get_adjustment(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    return svc.adjustment_dict(db, _doc(db, actor, DBStoreAdjustment, doc_id))


@router.put("/adjustments/{doc_id}")
def edit_adjustment(doc_id: int, body: AdjustmentIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    a = _doc(db, actor, DBStoreAdjustment, doc_id)
    _commit(db, lambda: svc.update_adjustment(db, actor, a, db.get(DBStore, a.store_id), _body(body)))
    return svc.adjustment_dict(db, a)


@router.post("/adjustments/{doc_id}/{action}")
def adjustment_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    actor, a = _act(request, db, action, DBStoreAdjustment, doc_id)
    _commit(db, lambda: svc.adjustment_action(db, actor, a, action, body.reason, can_high=_can(actor, "store.control.approve_high_value")))
    return svc.adjustment_dict(db, a)


@router.get("/adjustments/{doc_id}/pdf")
def adjustment_pdf(doc_id: int, request: Request, form: str = "", db: Session = Depends(get_db)):
    """The adjustment voucher; a wastage or write-off prints as a write-off note (or form=voucher / form=writeoff to choose)."""
    actor = store_actor(request, db, "store.control.view")
    a = _doc(db, actor, DBStoreAdjustment, doc_id)
    if form not in ("", "voucher", "writeoff"):
        raise HTTPException(400, "form must be voucher or writeoff.")
    note = form == "writeoff" or (form == "" and a.kind in ("WASTAGE", "WRITEOFF"))
    return _pdf(db, actor, a, writeoff_form_spec if note else adjustment_form_spec)


# ------------------------------------------------------------------------------------------------ scrap
@router.get("/scrap")
def list_scrap(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
               limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    total, rows = _list(db, actor, DBStoreScrap, store_id, status, q, from_date, to_date, limit, offset, DBStoreScrap.scrap_date)
    return {"total": total, "rows": [svc.scrap_dict(db, r, with_lines=False) for r in rows]}


@router.post("/scrap", status_code=201)
def create_scrap(body: ScrapIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    store = _store(db, actor, body.store_id)
    return svc.scrap_dict(db, _commit(db, lambda: svc.create_scrap(db, actor, store, _body(body))))


@router.get("/scrap/{doc_id}")
def get_scrap(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    return svc.scrap_dict(db, _doc(db, actor, DBStoreScrap, doc_id))


@router.put("/scrap/{doc_id}")
def edit_scrap(doc_id: int, body: ScrapIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    s = _doc(db, actor, DBStoreScrap, doc_id)
    _commit(db, lambda: svc.update_scrap(db, actor, s, db.get(DBStore, s.store_id), _body(body)))
    return svc.scrap_dict(db, s)


@router.post("/scrap/{doc_id}/{action}")
def scrap_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    actor, s = _act(request, db, action, DBStoreScrap, doc_id)
    _commit(db, lambda: svc.scrap_action(db, actor, s, action, body.reason))
    return svc.scrap_dict(db, s)


@router.get("/scrap/{doc_id}/pdf")
def scrap_pdf(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    return _pdf(db, actor, _doc(db, actor, DBStoreScrap, doc_id), scrap_form_spec)
