"""Store module - inward routes under /api/store/inward. Owned by P2.

GRN (goods received note, with quality check) and purchase returns, each DRAFT -> SUBMITTED -> APPROVED -> POSTED or
CANCELLED. Rights: view; create = draft, edit and submit; approve = approve and record the quality check; post; cancel.
"""
import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.documents import form_pdf
from app.documents.store.inward_forms import grn_form_spec, prn_form_spec
from app.models.store_core import DBStore, DocStatus
from app.models.store_inward import DBStoreGrn, DBStoreGrnLine, DBStorePurchaseReturn
from app.routers.store_masters import accessible_store_ids
from app.services import store_inward as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/inward", tags=["store-inward"])

ACTION_RIGHT = {"submit": "create", "approve": "approve", "post": "post", "cancel": "cancel"}


class GrnLineIn(BaseModel):
    po_line_id: Optional[int] = None
    item_id: Optional[int] = None
    qty: str
    uom: Optional[str] = None
    rate: Optional[str] = None
    bin_id: Optional[int] = None
    batch_no: str = ""
    remarks: str = ""


class GrnIn(BaseModel):
    store_id: Optional[int] = None
    grn_date: Optional[str] = None
    po_id: Optional[int] = None
    supplier_name: Optional[str] = None
    challan_no: Optional[str] = None
    challan_date: Optional[str] = None
    vehicle_no: Optional[str] = None
    remarks: Optional[str] = None
    lines: Optional[List[GrnLineIn]] = None


class QcLineIn(BaseModel):
    line_id: int
    accepted_qty: str
    rejected_qty: str = "0"
    remarks: str = ""


class QcIn(BaseModel):
    lines: List[QcLineIn]


class ReturnLineIn(BaseModel):
    grn_line_id: Optional[int] = None
    item_id: Optional[int] = None
    qty: str
    remarks: str = ""


class ReturnIn(BaseModel):
    store_id: Optional[int] = None
    return_date: Optional[str] = None
    grn_id: Optional[int] = None
    supplier_name: Optional[str] = None
    reason: Optional[str] = None
    remarks: Optional[str] = None
    lines: Optional[List[ReturnLineIn]] = None


class ActionIn(BaseModel):
    reason: str = ""


def _body(m: BaseModel) -> dict:
    return m.model_dump(exclude_unset=True)


def _commit(db, fn):
    """Run `fn` inside the module's error mapping and one transaction."""
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


def _doc(db, actor, model, doc_id, right="view"):
    doc = db.get(model, doc_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "Document not found")
    assert_store_access(actor.user, doc.store_id)
    return doc


def _list(db, actor, model, store_id, status, q, from_date, to_date, limit, offset, date_col):
    query = db.query(model).filter(model.client_id == actor.client.id)
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(model.store_id == store_id)
    else:
        mine = accessible_store_ids(actor, db)
        if mine is not None:
            query = query.filter(model.store_id.in_(mine or [0]))
    if status:
        if status not in {s.value for s in DocStatus}:
            raise HTTPException(400, "Unknown status.")
        query = query.filter(model.status == status)
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        query = query.filter(model.number.ilike("%" + term + "%") | model.supplier_name.ilike("%" + term + "%"))
    for value, op, what in ((from_date, ">=", "From date"), (to_date, "<=", "To date")):
        if value:
            d = svc._date(value, what)
            query = query.filter(getattr(date_col, "__ge__" if op == ">=" else "__le__")(d))
    total = query.count()
    rows = query.order_by(model.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 200))).all()
    return total, rows


def _pdf(db, actor, doc, spec_fn):
    if not form_pdf.PDF_AVAILABLE:
        raise HTTPException(503, "The PDF library is not installed on this server.")
    pdf = form_pdf.build_form_pdf(spec_fn(db, actor.client, doc))
    name = re.sub(r"[^A-Za-z0-9]+", "_", doc.number).strip("_")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % name})


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door (kept as the skeleton's smoke test expects); the documents are under /grn and /returns."""
    store_actor(request, db, "store.inward.view")
    return {"slice": "inward", "items": []}


# ------------------------------------------------------------------------------------------------ purchase orders
@router.get("/pos")
def open_pos(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Approved purchase orders that can be received against."""
    actor = store_actor(request, db, "store.inward.view")
    query = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == actor.client.id, models.DBPurchaseOrder.status == "Approved")
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        query = query.filter(models.DBPurchaseOrder.number.ilike("%" + term + "%") | models.DBPurchaseOrder.supplier_name.ilike("%" + term + "%"))
    rows = query.order_by(models.DBPurchaseOrder.id.desc()).limit(50).all()
    return {"pos": [{"id": p.id, "number": p.number, "supplier_name": p.supplier_name or "", "issue_date": p.issue_date or "", "project_id": p.job_id} for p in rows]}


@router.get("/pos/{po_id}/lines")
def po_lines(po_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return svc.po_lines_for_receipt(db, actor.client.id, po_id)


# ------------------------------------------------------------------------------------------------ GRN
@router.get("/grn")
def list_grn(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
             limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    total, rows = _list(db, actor, DBStoreGrn, store_id, status, q, from_date, to_date, limit, offset, DBStoreGrn.grn_date)
    return {"total": total, "rows": [svc.grn_dict(db, g, with_lines=False) for g in rows]}


@router.post("/grn", status_code=201)
def create_grn(body: GrnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    store = _store(db, actor, body.store_id)
    grn = _commit(db, lambda: svc.create_grn(db, actor, store, _body(body)))
    return svc.grn_dict(db, grn)


@router.get("/grn/{grn_id}")
def get_grn(grn_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return svc.grn_dict(db, _doc(db, actor, DBStoreGrn, grn_id))


@router.put("/grn/{grn_id}")
def edit_grn(grn_id: int, body: GrnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    grn = _doc(db, actor, DBStoreGrn, grn_id)
    _commit(db, lambda: svc.update_grn(db, actor, grn, db.get(DBStore, grn.store_id), _body(body)))
    return svc.grn_dict(db, grn)


@router.post("/grn/{grn_id}/qc")
def grn_qc(grn_id: int, body: QcIn, request: Request, db: Session = Depends(get_db)):
    """Record the quality check: accepted and rejected quantity (base unit) per line."""
    actor = store_actor(request, db, "store.inward.approve")
    grn = _doc(db, actor, DBStoreGrn, grn_id)
    _commit(db, lambda: svc.record_qc(db, actor, grn, [l.model_dump() for l in body.lines]))
    return svc.grn_dict(db, grn)


@router.post("/grn/{grn_id}/{action}")
def grn_action(grn_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "Unknown action")
    actor = store_actor(request, db, "store.inward." + ACTION_RIGHT[action])
    grn = _doc(db, actor, DBStoreGrn, grn_id)
    _commit(db, lambda: svc.grn_action(db, actor, grn, action, body.reason))
    return svc.grn_dict(db, grn)


@router.get("/grn/{grn_id}/returnable")
def grn_returnable(grn_id: int, request: Request, db: Session = Depends(get_db)):
    """The lines of a posted GRN with how much of each can still be sent back."""
    actor = store_actor(request, db, "store.inward.view")
    grn = _doc(db, actor, DBStoreGrn, grn_id)
    d = svc.grn_dict(db, grn)
    return {"grn": {"id": grn.id, "number": grn.number, "status": grn.status, "supplier_name": grn.supplier_name},
            "lines": [{"grn_line_id": l["id"], "item_id": l["item_id"], "item_code": l["item_code"], "item_name": l["item_name"], "base_uom": l["base_uom"],
                       "accepted_qty": l["accepted_qty"], "returnable_qty": str(max(svc.dec(l["accepted_qty"]) - svc._returned(db, l["id"]), svc.ZERO))}
                      for l in d["lines"]] if grn.status == DocStatus.POSTED.value else []}


@router.get("/grn/{grn_id}/pdf")
def grn_pdf(grn_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return _pdf(db, actor, _doc(db, actor, DBStoreGrn, grn_id), grn_form_spec)


# ------------------------------------------------------------------------------------------------ purchase returns
@router.get("/returns")
def list_returns(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                 limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    total, rows = _list(db, actor, DBStorePurchaseReturn, store_id, status, q, from_date, to_date, limit, offset, DBStorePurchaseReturn.return_date)
    return {"total": total, "rows": [svc.return_dict(db, r, with_lines=False) for r in rows]}


@router.post("/returns", status_code=201)
def create_return(body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    store = _store(db, actor, body.store_id)
    prn = _commit(db, lambda: svc.create_return(db, actor, store, _body(body)))
    return svc.return_dict(db, prn)


@router.get("/returns/{return_id}")
def get_return(return_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return svc.return_dict(db, _doc(db, actor, DBStorePurchaseReturn, return_id))


@router.put("/returns/{return_id}")
def edit_return(return_id: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    prn = _doc(db, actor, DBStorePurchaseReturn, return_id)
    _commit(db, lambda: svc.update_return(db, actor, prn, db.get(DBStore, prn.store_id), _body(body)))
    return svc.return_dict(db, prn)


@router.post("/returns/{return_id}/{action}")
def return_action(return_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "Unknown action")
    actor = store_actor(request, db, "store.inward." + ACTION_RIGHT[action])
    prn = _doc(db, actor, DBStorePurchaseReturn, return_id)
    _commit(db, lambda: svc.return_action(db, actor, prn, action, body.reason))
    return svc.return_dict(db, prn)


@router.get("/returns/{return_id}/pdf")
def return_pdf(return_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return _pdf(db, actor, _doc(db, actor, DBStorePurchaseReturn, return_id), prn_form_spec)
