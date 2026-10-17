"""Store module - outward routes under /api/store/outward. Owned by P3.

Requisitions (/requisitions), issues to site and subcontractors (/issues), issue returns (/returns), plus the outstanding
returnables and write-off requests. Rights: view; create = draft, edit, submit; approve; post; cancel. An issue with no
requisition (a direct issue) also needs store.outward.direct_issue.
"""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.documents import form_pdf
from app.documents.store.outward_forms import issue_form_spec, requisition_form_spec, return_form_spec
from app.models.store_core import CostHead, DBStore, DocStatus
from app.models.store_outward import (
    DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreRequisition, DBStoreWriteoffRequest,
)
from app.routers.store_masters import accessible_store_ids
from app.services import store_outward as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/outward", tags=["store-outward"])

ACTION_RIGHT = {"submit": "create", "approve": "approve", "post": "post", "cancel": "cancel"}


class Costing(BaseModel):
    project_id: Optional[int] = None
    work_order_id: Optional[int] = None
    boq_item_id: Optional[int] = None
    cost_head: Optional[str] = None


class ReqLineIn(BaseModel):
    item_id: int
    qty: str
    uom: Optional[str] = None
    remarks: str = ""


class RequisitionIn(Costing):
    store_id: Optional[int] = None
    req_date: Optional[str] = None
    required_by: Optional[str] = None
    purpose: Optional[str] = None
    lines: Optional[List[ReqLineIn]] = None


class IssueLineIn(BaseModel):
    item_id: int
    qty: str
    uom: Optional[str] = None
    chargeable: bool = False
    recovery_rate: Optional[str] = None
    remarks: str = ""


class IssueIn(Costing):
    store_id: Optional[int] = None
    issue_date: Optional[str] = None
    issue_type: Optional[str] = None
    requisition_id: Optional[int] = None
    subcontractor_id: Optional[int] = None
    holder_type: Optional[str] = None
    holder_id: Optional[int] = None
    holder_name: Optional[str] = None
    expected_return_date: Optional[str] = None
    purpose: Optional[str] = None
    lines: Optional[List[IssueLineIn]] = None


class ReturnLineIn(BaseModel):
    issue_line_id: int
    qty: str = "0"
    lost_qty: str = "0"
    remarks: str = ""


class ReturnIn(BaseModel):
    store_id: Optional[int] = None
    issue_id: Optional[int] = None
    return_date: Optional[str] = None
    remarks: Optional[str] = None
    lines: Optional[List[ReturnLineIn]] = None


class ActionIn(BaseModel):
    reason: str = ""


def _body(m: BaseModel) -> dict:
    return m.model_dump(exclude_unset=True)


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


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door (kept as the skeleton's smoke test expects); the documents are under /requisitions, /issues and /returns."""
    store_actor(request, db, "store.outward.view")
    return {"slice": "outward", "items": []}


# ------------------------------------------------------------------------------------------------ pickers
@router.get("/options")
def options(request: Request, db: Session = Depends(get_db)):
    """What the forms choose from: projects, work orders, subcontractors, staff, cost heads."""
    actor = store_actor(request, db, "store.outward.view")
    cid = actor.client.id
    return {"projects": [{"id": j.id, "name": j.name, "number": j.number} for j in db.query(models.DBJob).filter(models.DBJob.client_id == cid).order_by(models.DBJob.name).limit(300).all()],
            "work_orders": [{"id": w.id, "number": w.number, "project_id": w.job_id} for w in db.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == cid).order_by(models.DBWorkOrder.id.desc()).limit(300).all()],
            "subcontractors": [{"id": c.id, "name": c.company_name or ""} for c in db.query(models.DBContractor).filter(models.DBContractor.client_id == cid).order_by(models.DBContractor.company_name).limit(300).all()],
            "employees": [{"id": e.id, "name": ("%s %s" % (e.first_name, e.last_name)).strip()} for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == cid).order_by(models.DBEmployee.first_name).limit(300).all()],
            "cost_heads": [c.value for c in CostHead]}


@router.get("/work-orders/{wo_id}/boq")
def work_order_boq(wo_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    wo = db.get(models.DBWorkOrder, wo_id)
    if wo is None or wo.client_id != actor.client.id:
        raise HTTPException(404, "Work order not found")
    rows = db.query(models.DBBoqLine).filter(models.DBBoqLine.boq_id == wo.boq_id, models.DBBoqLine.kind == "item").order_by(models.DBBoqLine.id).all() if wo.boq_id else []
    return {"items": [{"id": b.id, "item_no": b.item_no, "description": b.description, "uom": b.uom} for b in rows]}


# ------------------------------------------------------------------------------------------------ requisitions
@router.get("/requisitions")
def list_requisitions(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                      limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    total, rows = _list(db, actor, DBStoreRequisition, store_id, status, q, from_date, to_date, limit, offset, DBStoreRequisition.req_date)
    return {"total": total, "rows": [svc.requisition_dict(db, r, with_lines=False) for r in rows]}


@router.post("/requisitions", status_code=201)
def create_requisition(body: RequisitionIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    store = _store(db, actor, body.store_id)
    return svc.requisition_dict(db, _commit(db, lambda: svc.create_requisition(db, actor, store, _body(body))))


@router.get("/requisitions/{doc_id}")
def get_requisition(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return svc.requisition_dict(db, _doc(db, actor, DBStoreRequisition, doc_id))


@router.put("/requisitions/{doc_id}")
def edit_requisition(doc_id: int, body: RequisitionIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    req = _doc(db, actor, DBStoreRequisition, doc_id)
    _commit(db, lambda: svc.update_requisition(db, actor, req, db.get(DBStore, req.store_id), _body(body)))
    return svc.requisition_dict(db, req)


@router.post("/requisitions/{doc_id}/{action}")
def requisition_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "Unknown action")
    actor = store_actor(request, db, "store.outward." + ACTION_RIGHT[action])
    req = _doc(db, actor, DBStoreRequisition, doc_id)
    _commit(db, lambda: svc.requisition_action(db, actor, req, action, body.reason))
    return svc.requisition_dict(db, req)


@router.get("/requisitions/{doc_id}/pdf")
def requisition_pdf(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return _pdf(db, actor, _doc(db, actor, DBStoreRequisition, doc_id), requisition_form_spec)


# ------------------------------------------------------------------------------------------------ issues
@router.get("/issues")
def list_issues(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    total, rows = _list(db, actor, DBStoreIssue, store_id, status, q, from_date, to_date, limit, offset, DBStoreIssue.issue_date)
    return {"total": total, "rows": [svc.issue_dict(db, r, with_lines=False) for r in rows]}


@router.post("/issues", status_code=201)
def create_issue(body: IssueIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    if not body.requisition_id:
        actor = store_actor(request, db, "store.outward.direct_issue")           # no requisition: a direct issue needs its own right
    store = _store(db, actor, body.store_id)
    return svc.issue_dict(db, _commit(db, lambda: svc.create_issue(db, actor, store, _body(body))))


@router.get("/issues/{doc_id}")
def get_issue(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return svc.issue_dict(db, _doc(db, actor, DBStoreIssue, doc_id))


@router.put("/issues/{doc_id}")
def edit_issue(doc_id: int, body: IssueIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    issue = _doc(db, actor, DBStoreIssue, doc_id)
    _commit(db, lambda: svc.update_issue(db, actor, issue, db.get(DBStore, issue.store_id), _body(body)))
    return svc.issue_dict(db, issue)


@router.get("/issues/{doc_id}/returnable")
def issue_returnable(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """The lines of a posted issue with how much of each is still out."""
    actor = store_actor(request, db, "store.outward.view")
    issue = _doc(db, actor, DBStoreIssue, doc_id)
    d = svc.issue_dict(db, issue)
    posted = issue.status == DocStatus.POSTED.value
    live = {r.issue_line_id for r in db.query(svc.DBStoreIssueReturnLine).join(DBStoreIssueReturn, DBStoreIssueReturn.id == svc.DBStoreIssueReturnLine.return_id).filter(
        DBStoreIssueReturn.issue_id == issue.id, DBStoreIssueReturn.status.in_(["DRAFT", "SUBMITTED", "APPROVED"])).all()}
    out = []
    for l in d["lines"] if posted else []:
        back, gone = svc._gone_from_issue_line(db, l["id"])
        out.append({"issue_line_id": l["id"], "item_id": l["item_id"], "item_code": l["item_code"], "item_name": l["item_name"], "base_uom": l["base_uom"],
                    "issued_qty": l["qty"], "still_out_qty": str(max(svc.dec(l["qty"]) - back - gone, svc.ZERO)), "returnable": l["returnable"], "has_pending_return": l["id"] in live})
    return {"issue": {"id": issue.id, "number": issue.number, "status": issue.status, "holder_name": issue.holder_name}, "lines": out}


@router.post("/issues/{doc_id}/{action}")
def issue_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "Unknown action")
    actor = store_actor(request, db, "store.outward." + ACTION_RIGHT[action])
    issue = _doc(db, actor, DBStoreIssue, doc_id)
    _commit(db, lambda: svc.issue_action(db, actor, issue, action, body.reason))
    return svc.issue_dict(db, issue)


@router.get("/issues/{doc_id}/pdf")
def issue_pdf(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return _pdf(db, actor, _doc(db, actor, DBStoreIssue, doc_id), issue_form_spec)


# ------------------------------------------------------------------------------------------------ returns
@router.get("/returns")
def list_returns(request: Request, store_id: int = 0, status: str = "", q: str = "", from_date: str = "", to_date: str = "",
                 limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    total, rows = _list(db, actor, DBStoreIssueReturn, store_id, status, q, from_date, to_date, limit, offset, DBStoreIssueReturn.return_date)
    return {"total": total, "rows": [svc.return_dict(db, r, with_lines=False) for r in rows]}


@router.post("/returns", status_code=201)
def create_return(body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    store = _store(db, actor, body.store_id)
    return svc.return_dict(db, _commit(db, lambda: svc.create_return(db, actor, store, _body(body))))


@router.get("/returns/{doc_id}")
def get_return(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return svc.return_dict(db, _doc(db, actor, DBStoreIssueReturn, doc_id))


@router.put("/returns/{doc_id}")
def edit_return(doc_id: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    rtn = _doc(db, actor, DBStoreIssueReturn, doc_id)
    _commit(db, lambda: svc.update_return(db, actor, rtn, db.get(DBStore, rtn.store_id), _body(body)))
    return svc.return_dict(db, rtn)


@router.post("/returns/{doc_id}/{action}")
def return_action(doc_id: int, action: str, request: Request, body: ActionIn = ActionIn(), db: Session = Depends(get_db)):
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "Unknown action")
    actor = store_actor(request, db, "store.outward." + ACTION_RIGHT[action])
    rtn = _doc(db, actor, DBStoreIssueReturn, doc_id)
    _commit(db, lambda: svc.return_action(db, actor, rtn, action, body.reason))
    return svc.return_dict(db, rtn)


@router.get("/returns/{doc_id}/pdf")
def return_pdf(doc_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return _pdf(db, actor, _doc(db, actor, DBStoreIssueReturn, doc_id), return_form_spec)


# ------------------------------------------------------------------------------------------------ outstanding and write-offs
@router.get("/outstanding")
def outstanding(request: Request, store_id: int = 0, project_id: int = 0, db: Session = Depends(get_db)):
    """Returnable items issued and not yet back, who holds them, and how late they are."""
    actor = store_actor(request, db, "store.outward.view")
    if store_id:
        assert_store_access(actor.user, store_id)
    mine = accessible_store_ids(actor, db)
    rows = []
    for r in svc.get_outstanding_returnables(db, project_id=project_id or None, store_id=store_id or None):
        line = db.get(DBStoreIssueLine, r.issue_line_id)
        issue = db.get(DBStoreIssue, line.issue_id)
        if issue.client_id != actor.client.id or (mine is not None and issue.store_id not in mine):
            continue
        item = db.get(models.DBItem, r.item_id)
        rows.append({"issue_line_id": r.issue_line_id, "issue_id": issue.id, "issue_number": issue.number, "store_code": db.get(DBStore, issue.store_id).code,
                     "item_id": r.item_id, "item_code": item.item_code, "item_name": item.item_name, "holder_type": r.holder_type, "holder_name": issue.holder_name or "",
                     "qty_outstanding": str(r.qty_outstanding), "expected_return_date": r.expected_return_date.isoformat() if r.expected_return_date else None,
                     "overdue_days": r.overdue_days})
    return {"rows": rows}


@router.get("/writeoffs")
def writeoffs(request: Request, status: str = "OPEN", db: Session = Depends(get_db)):
    """Material issued and declared lost, waiting for the control slice to write it off."""
    actor = store_actor(request, db, "store.outward.view")
    q = db.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.client_id == actor.client.id)
    mine = accessible_store_ids(actor, db)
    if mine is not None:
        q = q.filter(DBStoreWriteoffRequest.store_id.in_(mine or [0]))
    if status:
        q = q.filter(DBStoreWriteoffRequest.status == status)
    return {"rows": [svc.writeoff_dict(db, w) for w in q.order_by(DBStoreWriteoffRequest.id.desc()).limit(200).all()]}
