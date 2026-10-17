"""Store module - outward routes under /api/store/outward: material issues to a project or a subcontractor (issue), what comes back
(returns), the returnables still out, subcontractor recovery and write-off requests. Owned by P3.

Rights: store.outward.view reads; .create makes, edits and deletes drafts and submits; .approve approves; .post posts to stock;
.cancel cancels (a posted document is reversed); .direct_issue issues, approves and posts in one step. Every route works inside
the stores the person is assigned to. Posting is one transaction: every line moves stock or none does.
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
from app.documents.store.outward_forms import FORMS
from app.models.store_core import DBStore, DBStoreUserAssignment, DocStatus
from app.models.store_outward import (
    ISSUE, ISSUE_RETURN, SITE, DBStoreIssue, DBStoreIssueReturn, DBStoreOutwardLog, DBStoreWriteoffRequest,
)
from app.services import store_outward as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/outward", tags=["store-outward"])
ZERO = Decimal("0")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ACTION_RIGHT = {"submit": "store.outward.create", "approve": "store.outward.approve", "post": "store.outward.post", "cancel": "store.outward.cancel"}


# --- request bodies ---------------------------------------------------------------------------------------------------

class IssueLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    boq_item_id: Optional[int] = None
    cost_head: str = ""
    chargeable: bool = False
    recovery_rate: str = ""              # per base unit; subcontractor issues only
    expected_return_date: str = ""
    remarks: str = ""


class IssueIn(BaseModel):
    store_id: int
    issue_date: str
    issue_type: str = SITE
    project_id: int
    work_order_id: Optional[int] = None
    subcontractor_id: Optional[int] = None
    holder_type: str = ""
    holder_id: Optional[int] = None
    holder_name: str = ""
    purpose: str = ""
    remarks: str = ""
    lines: List[IssueLineIn]


class ReturnLineIn(BaseModel):
    issue_line_id: int
    qty_returned: str = ""
    qty_lost: str = ""
    uom: str = ""
    reason: str = ""


class ReturnIn(BaseModel):
    issue_id: int
    return_date: str
    remarks: str = ""
    lines: List[ReturnLineIn]


class ActionIn(BaseModel):
    reason: str = ""


# --- helpers -----------------------------------------------------------------------------------------------------------

def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


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


def _editable(doc):
    if doc.status != DocStatus.DRAFT.value:
        raise HTTPException(409, "It is %s. Only a draft can be edited; cancel it and make a new one to correct it." % doc.status.lower())


def _iso(d):
    return d.isoformat() if d else ""


def _who(actor):
    return dict(user_type="employee" if actor.employee is not None else "client", user_name=actor.name)


def _items(db, ids):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(ids) or [0])).all()}


def doc_dict(db, kind, doc, detail=False):
    store = db.get(DBStore, doc.store_id)
    out = {"kind": kind.key, "id": doc.id, "number": doc.number, "status": doc.status, "store_id": doc.store_id, "store_code": store.code if store else "", "store_name": store.name if store else "",
           "date": _iso(getattr(doc, kind.date_attr)), "remarks": doc.remarks or "", "cancel_reason": doc.cancel_reason or "", "created_by": doc.created_by_name or "",
           "created_at": doc.created_at.isoformat(timespec="seconds") if doc.created_at else "", "posted_at": doc.posted_at.isoformat(timespec="seconds") if doc.posted_at else ""}
    if kind.key == "issue":
        job = db.get(models.DBJob, doc.project_id)
        wo = db.get(models.DBWorkOrder, doc.work_order_id) if doc.work_order_id else None
        lines = svc.issue_lines(db, doc)
        out.update({"issue_type": doc.issue_type, "project_id": doc.project_id, "project": ("%s - %s" % (job.number, job.name)) if job else "", "work_order_id": doc.work_order_id,
                    "work_order": wo.number if wo else "", "subcontractor_id": doc.subcontractor_id, "holder_type": doc.holder_type or "", "holder_id": doc.holder_id,
                    "holder_name": doc.holder_name or "", "purpose": doc.purpose or "", "direct": bool(doc.direct), "line_count": len(lines)})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            outstanding = svc.outstanding_on(db, doc) if doc.status == DocStatus.POSTED.value else {}
            boqs = {b.id: b for b in db.query(models.DBBoqLine).filter(models.DBBoqLine.id.in_([l.boq_item_id for l in lines if l.boq_item_id] or [0])).all()}
            out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                             "entry_uom": l.entry_uom or "", "entry_qty": svc.s3(l.entry_qty), "qty": svc.s3(l.qty), "boq_item_id": l.boq_item_id,
                             "boq_item": ("%s %s" % (boqs[l.boq_item_id].item_no or "", (boqs[l.boq_item_id].description or "").split("\n")[0][:60])).strip() if l.boq_item_id in boqs else "",
                             "cost_head": l.cost_head, "chargeable": bool(l.chargeable), "recovery_rate": svc.s3(l.recovery_rate), "expected_return_date": _iso(l.expected_return_date),
                             "returnable": svc.is_returnable(db, l.item_id), "outstanding": svc.s3(outstanding.get(l.id, ZERO)) if doc.status == DocStatus.POSTED.value else None,
                             "remarks": l.remarks or ""} for l in lines]
    else:
        issue = db.get(DBStoreIssue, doc.issue_id)
        lines = svc.return_lines(db, doc)
        out.update({"issue_id": doc.issue_id, "issue_number": issue.number if issue else "", "holder_name": issue.holder_name if issue else "", "line_count": len(lines)})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            out["lines"] = [{"id": l.id, "issue_line_id": l.issue_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
                             "base_uom": svc.base_uom_of(db, items[l.item_id]), "entry_uom": l.entry_uom or "", "qty_returned": svc.s3(l.qty_returned), "qty_lost": svc.s3(l.qty_lost),
                             "reason": l.reason or ""} for l in lines]
    if detail:
        out["history"] = [{"action": h.action, "from": h.from_status, "to": h.to_status, "by": h.user_name, "at": h.at.isoformat(timespec="seconds") if h.at else "", "note": h.note or ""}
                          for h in db.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == kind.ref, DBStoreOutwardLog.doc_id == doc.id).order_by(DBStoreOutwardLog.id).all()]
    return out


def _created(db, actor, kind, doc, request, direct=False):
    doc.created_by_id, doc.created_by_name = actor.user_id, actor.name
    db.flush()
    svc.log(db, actor, kind.ref, doc.id, "create", "", doc.status)
    log_audit(db, actor.client.id, "store_%s_created" % kind.key, "store_doc", doc.id, doc.number, "direct" if direct else "", request=request, **_who(actor))


# --- the front door and pickers ----------------------------------------------------------------------------------------------

@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: the latest issues this person may see."""
    return {"slice": "outward", "items": list_documents("issue", request, limit=20, db=db)["items"]}


@router.get("/pick/boq-items")
def pick_boq_items(project_id: int, request: Request, q: str = "", db: Session = Depends(get_db)):
    """A project's priced BOQ items (current revision), for charging an issue to."""
    actor = store_actor(request, db, "store.outward.view")
    boq = db.query(models.DBBoq).filter(models.DBBoq.job_id == project_id, models.DBBoq.client_id == actor.client.id).first()
    if boq is None:
        return {"items": []}
    query = (db.query(models.DBBoqLine).join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
             .filter(models.DBBoqLine.boq_id == boq.id, models.DBBoqRevision.rev_no == boq.current_rev, models.DBBoqLine.kind.in_(["item", "sub"])))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBBoqLine.description.ilike(like), models.DBBoqLine.item_no.ilike(like)))
    rows = query.order_by(models.DBBoqLine.display_order).limit(200).all()
    return {"items": [{"id": r.id, "item_no": r.item_no or "", "description": (r.description or "").split("\n")[0][:90], "uom": r.uom or ""} for r in rows]}


@router.get("/pick/work-orders")
def pick_work_orders(project_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    rows = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == actor.client.id, models.DBWorkOrder.job_id == project_id).order_by(models.DBWorkOrder.id.desc()).limit(100).all()
    return {"items": [{"id": w.id, "number": w.number or "", "status": w.status or ""} for w in rows]}


@router.get("/pick/subcontractors")
def pick_subcontractors(request: Request, q: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    query = db.query(models.DBContractor).filter(models.DBContractor.client_id == actor.client.id)
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBContractor.company_name.ilike(like), models.DBContractor.vendor_code.ilike(like)))
    return {"items": [{"id": c.id, "code": c.vendor_code or "", "name": c.company_name or ""} for c in query.order_by(models.DBContractor.company_name).limit(100).all()]}


@router.get("/pick/employees")
def pick_employees(request: Request, q: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    query = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == actor.client.id, models.DBEmployee.status.in_(["active", "onboarding"]))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBEmployee.first_name.ilike(like), models.DBEmployee.last_name.ilike(like)))
    return {"items": [{"id": e.id, "name": ("%s %s" % (e.first_name or "", e.last_name or "")).strip(), "job_title": e.job_title or ""} for e in query.order_by(models.DBEmployee.first_name).limit(100).all()]}


@router.get("/issue-lines/{issue_id}")
def returnable_lines(issue_id: int, request: Request, db: Session = Depends(get_db)):
    """What is still out on a posted issue, line by line, for the return form."""
    actor = store_actor(request, db, "store.outward.view")
    issue = _doc(db, actor, svc.KINDS["issue"], issue_id)
    lines = svc.issue_lines(db, issue)
    room = svc.outstanding_on(db, issue)
    items = _items(db, [l.item_id for l in lines])
    return {"issue": {"id": issue.id, "number": issue.number, "status": issue.status, "store_id": issue.store_id, "holder_name": issue.holder_name or ""},
            "lines": [{"issue_line_id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                       "issued": svc.s3(l.qty), "outstanding": svc.s3(max(ZERO, room.get(l.id, ZERO))), "returnable": svc.is_returnable(db, l.item_id)} for l in lines]}


def _returnable_rows(db, actor, project_id, store_id):
    seen = _visible(db, actor)
    rows = svc.get_outstanding_returnables(db, project_id=project_id or None, store_id=store_id or None)
    lines = {l.id: l for l in db.query(svc.DBStoreIssueLine).filter(svc.DBStoreIssueLine.id.in_([r.issue_line_id for r in rows] or [0])).all()}
    issues = {i.id: i for i in db.query(DBStoreIssue).filter(DBStoreIssue.id.in_([l.issue_id for l in lines.values()] or [0])).all()}
    items = _items(db, [r.item_id for r in rows])
    out = []
    for r in rows:
        il = lines[r.issue_line_id]
        issue = issues[il.issue_id]
        if issue.client_id != actor.client.id or (seen is not None and issue.store_id not in seen):
            continue
        out.append({"issue_line_id": r.issue_line_id, "issue_id": issue.id, "issue_number": issue.number, "issue_date": _iso(issue.issue_date), "store_id": issue.store_id,
                    "project_id": issue.project_id, "item_id": r.item_id, "item_code": items[r.item_id].item_code, "item_name": items[r.item_id].item_name, "holder_type": r.holder_type,
                    "holder_id": r.holder_id, "holder_name": issue.holder_name or "", "qty_outstanding": svc.s3(r.qty_outstanding), "expected_return_date": _iso(r.expected_return_date),
                    "overdue_days": r.overdue_days})
    return out


@router.get("/returnables")
def returnables(request: Request, project_id: int = 0, store_id: int = 0, overdue_only: bool = False, db: Session = Depends(get_db)):
    """Returnable items and tools still out, who holds them and how late they are."""
    actor = store_actor(request, db, "store.outward.view")
    if store_id:
        assert_store_access(actor.user, store_id)
    rows = _returnable_rows(db, actor, project_id, store_id)
    if overdue_only:
        rows = [r for r in rows if r["overdue_days"] > 0]
    return {"total": len(rows), "overdue": sum(1 for r in rows if r["overdue_days"] > 0), "items": rows}


@router.get("/returnables/export")
def export_returnables(request: Request, project_id: int = 0, store_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Returnables out"
    ws.append(["Issue", "Issued on", "Item code", "Item", "Held by", "Holder type", "Quantity out", "Expected back", "Days overdue"])
    for r in _returnable_rows(db, actor, project_id, store_id):
        ws.append([r["issue_number"], r["issue_date"], r["item_code"], r["item_name"], r["holder_name"], r["holder_type"], float(r["qty_outstanding"]), r["expected_return_date"], r["overdue_days"]])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="returnables-out.xlsx"'})


@router.get("/writeoffs")
def writeoffs(request: Request, status: str = "OPEN", db: Session = Depends(get_db)):
    """Returnables reported lost or damaged and waiting to be dealt with."""
    actor = store_actor(request, db, "store.outward.view")
    seen = _visible(db, actor)
    q = db.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.client_id == actor.client.id)
    if status:
        q = q.filter(DBStoreWriteoffRequest.status == status.strip().upper())
    if seen is not None:
        q = q.filter(DBStoreWriteoffRequest.store_id.in_(seen or {0}))
    rows = q.order_by(DBStoreWriteoffRequest.id.desc()).limit(500).all()
    items = _items(db, [w.item_id for w in rows])
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.id.in_([w.store_id for w in rows] or [0])).all()}
    return {"items": [{"id": w.id, "store_id": w.store_id, "store_code": stores[w.store_id].code, "item_id": w.item_id, "item_code": items[w.item_id].item_code, "item_name": items[w.item_id].item_name,
                       "qty": svc.s3(w.qty), "reason": w.reason or "", "status": w.status, "created_at": w.created_at.isoformat(timespec="seconds") if w.created_at else "",
                       "closed_ref": ("%s #%s" % (w.closed_ref_type, w.closed_ref_id)) if w.closed_ref_type else ""} for w in rows]}


@router.get("/subcontractors/{subcontractor_id}/recovery")
def subcontractor_recovery(subcontractor_id: int, request: Request, upto: str = "", db: Session = Depends(get_db)):
    """Material issued to one subcontractor, what came back and what is to be recovered from their bill."""
    actor = store_actor(request, db, "store.outward.view")
    con = db.query(models.DBContractor).filter(models.DBContractor.id == subcontractor_id, models.DBContractor.client_id == actor.client.id).first()
    if con is None:
        raise HTTPException(404, "Subcontractor not found")
    rows = svc.get_subcon_issues(db, con.id, svc.day(upto, "Up-to date", allow_future=True, required=False) or date.today())
    items = _items(db, [r.item_id for r in rows])
    total = sum((r.recovery_value for r in rows), ZERO)
    return {"subcontractor": {"id": con.id, "name": con.company_name or ""}, "total_recovery": format(total.quantize(Decimal("0.01")), "f"),
            "items": [{"issue_line_id": r.issue_line_id, "issue_date": _iso(r.issue_date), "item_id": r.item_id, "item_code": items[r.item_id].item_code, "item_name": items[r.item_id].item_name,
                       "qty_issued": svc.s3(r.qty_issued), "qty_returned": svc.s3(r.qty_returned), "chargeable": r.chargeable, "recovery_rate": svc.s3(r.recovery_rate),
                       "recovery_value": format(r.recovery_value.quantize(Decimal("0.01")), "f")} for r in rows]}


# --- listing ------------------------------------------------------------------------------------------------------------

@router.get("/{kind_key}")
def list_documents(kind_key: str, request: Request, status: str = "", store_id: int = 0, q: str = "", project_id: int = 0, from_date: str = "", to_date: str = "",
                   limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.outward.view")
    query = db.query(kind.header).filter(kind.header.client_id == actor.client.id)
    seen = _visible(db, actor)
    if seen is not None:
        query = query.filter(kind.header.store_id.in_(seen or {0}))
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(kind.header.store_id == store_id)
    if status:
        query = query.filter(kind.header.status == status.strip().upper())
    if project_id and kind.key == "issue":
        query = query.filter(DBStoreIssue.project_id == project_id)
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        cond = [kind.header.number.ilike(like)]
        if kind.key == "issue":
            cond.append(DBStoreIssue.holder_name.ilike(like))
        query = query.filter(or_(*cond))
    date_col = getattr(kind.header, kind.date_attr)
    if from_date:
        query = query.filter(date_col >= svc.day(from_date, "From date", allow_future=True))
    if to_date:
        query = query.filter(date_col <= svc.day(to_date, "To date", allow_future=True))
    total = query.count()
    rows = query.order_by(kind.header.id.desc()).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
    return {"total": total, "items": [doc_dict(db, kind, r) for r in rows]}


@router.get("/{kind_key}/export")
def export_documents(kind_key: str, request: Request, status: str = "", store_id: int = 0, q: str = "", db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    rows = list_documents(kind_key, request, status=status, store_id=store_id, q=q, limit=500, db=db)["items"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = kind.label
    cols = ["number", "date", "status", "store_code"] + (["issue_type", "project", "work_order", "holder_name", "purpose"] if kind.key == "issue" else ["issue_number", "holder_name"]) + ["line_count", "created_by", "remarks"]
    ws.append([c.replace("_", " ").title() for c in cols])
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="outward-%s.xlsx"' % kind.key})


@router.get("/{kind_key}/{doc_id}")
def get_document(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.outward.view")
    return doc_dict(db, kind, _doc(db, actor, kind, doc_id), detail=True)


@router.get("/{kind_key}/{doc_id}/print")
def print_document(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.outward.view")
    doc = _doc(db, actor, kind, doc_id)
    try:
        pdf = form_pdf.build_form_pdf(FORMS[kind.key][1](db, actor.client, doc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % doc.number.replace("/", "-")})


# --- making and editing -------------------------------------------------------------------------------------------------

def _issue_values(db, actor, body, issue=None):
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    on = svc.day(body.issue_date, "Issue date")
    issue_type, htype, hid, hname = svc.check_issue_header(db, actor.client.id, body)
    lines = svc.build_issue_lines(db, actor.client.id, body, issue_type, htype, on)
    return store, on, issue_type, htype, hid, hname, lines


def _fill_issue(issue, body, on, issue_type, htype, hid, hname):
    issue.issue_date, issue.issue_type, issue.project_id, issue.work_order_id = on, issue_type, body.project_id, body.work_order_id or None
    issue.subcontractor_id = body.subcontractor_id if issue_type == "SUBCONTRACTOR" else None
    issue.holder_type, issue.holder_id, issue.holder_name = htype, hid, hname
    issue.purpose, issue.remarks = svc.text(body.purpose, "purpose", 200), svc.text(body.remarks, "remarks", 500)


def _new_issue(db, actor, body, request):
    store, on, issue_type, htype, hid, hname, lines = _issue_values(db, actor, body)
    issue = DBStoreIssue(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, ISSUE, store.id, on), status=DocStatus.DRAFT.value)
    _fill_issue(issue, body, on, issue_type, htype, hid, hname)
    db.add(issue)
    db.flush()
    svc.write_issue_lines(db, issue, lines)
    return issue


@router.post("/issue")
def create_issue(body: IssueIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    issue = _new_issue(db, actor, body, request)
    _created(db, actor, svc.KINDS["issue"], issue, request)
    db.commit()
    return doc_dict(db, svc.KINDS["issue"], issue, detail=True)


@router.post("/issue/direct")
def direct_issue(body: IssueIn, request: Request, db: Session = Depends(get_db)):
    """Issue, approve and post in one step - for the storekeeper handing out material at the counter. It needs its own right
    (store.outward.direct_issue), is marked as direct on the document and in the log, and is all-or-nothing like any posting."""
    actor = store_actor(request, db, "store.outward.direct_issue")
    kind = svc.KINDS["issue"]
    try:
        with store_errors():
            issue = _new_issue(db, actor, body, request)
            issue.direct = 1
            _created(db, actor, kind, issue, request, direct=True)
            svc.advance(db, actor, kind, issue, "submit")
            svc.advance(db, actor, kind, issue, "approve")
            svc.advance(db, actor, kind, issue, "post")
            svc.log(db, actor, ISSUE, issue.id, "direct", DocStatus.DRAFT.value, issue.status, "issued, approved and posted in one step")
        log_audit(db, actor.client.id, "store_issue_direct", "store_doc", issue.id, issue.number, issue.status, request=request, **_who(actor))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, issue, detail=True)


@router.put("/issue/{doc_id}")
def edit_issue(doc_id: int, body: IssueIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    issue = _doc(db, actor, svc.KINDS["issue"], doc_id)
    _editable(issue)
    if body.store_id != issue.store_id:
        raise HTTPException(400, "An issue cannot be moved to another store; cancel it and make a new one.")
    _store, on, issue_type, htype, hid, hname, lines = _issue_values(db, actor, body, issue)
    _fill_issue(issue, body, on, issue_type, htype, hid, hname)
    svc.write_issue_lines(db, issue, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["issue"], issue, detail=True)


@router.post("/returns")
def create_return(body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    issue = _doc(db, actor, svc.KINDS["issue"], body.issue_id)
    on = svc.day(body.return_date, "Return date")
    lines = svc.build_return_lines(db, actor.client.id, issue, body.lines)
    ret = DBStoreIssueReturn(client_id=actor.client.id, store_id=issue.store_id, number=svc.numbered(db, ISSUE_RETURN, issue.store_id, on), status=DocStatus.DRAFT.value, return_date=on,
                             issue_id=issue.id, remarks=svc.text(body.remarks, "remarks", 500))
    db.add(ret)
    db.flush()
    svc.write_return_lines(db, ret, lines)
    _created(db, actor, svc.KINDS["returns"], ret, request)
    db.commit()
    return doc_dict(db, svc.KINDS["returns"], ret, detail=True)


@router.put("/returns/{doc_id}")
def edit_return(doc_id: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    ret = _doc(db, actor, svc.KINDS["returns"], doc_id)
    _editable(ret)
    if body.issue_id != ret.issue_id:
        raise HTTPException(400, "A return cannot be moved to another issue; cancel it and make a new one.")
    issue = _doc(db, actor, svc.KINDS["issue"], ret.issue_id)
    on = svc.day(body.return_date, "Return date")
    lines = svc.build_return_lines(db, actor.client.id, issue, body.lines, return_id=ret.id)
    ret.return_date, ret.remarks = on, svc.text(body.remarks, "remarks", 500)
    svc.write_return_lines(db, ret, lines)
    db.commit()
    return doc_dict(db, svc.KINDS["returns"], ret, detail=True)


@router.delete("/{kind_key}/{doc_id}")
def delete_draft(kind_key: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Throw a draft away. Anything submitted or posted is cancelled instead, so its history stays."""
    kind = _kind(kind_key)
    actor = store_actor(request, db, "store.outward.create")
    doc = _doc(db, actor, kind, doc_id)
    _editable(doc)
    db.query(kind.line).filter(getattr(kind.line, kind.fk) == doc.id).delete(synchronize_session=False)
    db.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == kind.ref, DBStoreOutwardLog.doc_id == doc.id).delete(synchronize_session=False)
    number = doc.number
    db.delete(doc)
    log_audit(db, actor.client.id, "store_%s_deleted" % kind.key, "store_doc", doc_id, number, "draft", request=request, **_who(actor))
    db.commit()
    return {"message": "Draft deleted"}


# --- the lifecycle ------------------------------------------------------------------------------------------------------

@router.post("/{kind_key}/{doc_id}/{action}")
def act(kind_key: str, doc_id: int, action: str, request: Request, body: Optional[ActionIn] = None, db: Session = Depends(get_db)):
    """submit, approve, post or cancel (with a reason). Posting and cancelling a posted document move stock in one transaction:
    if any line cannot move, nothing does."""
    kind = _kind(kind_key)
    if action not in ACTION_RIGHT:
        raise HTTPException(404, "There is no such action.")
    actor = store_actor(request, db, ACTION_RIGHT[action])
    doc = _doc(db, actor, kind, doc_id)
    try:
        with store_errors():
            svc.advance(db, actor, kind, doc, action, body.reason if body else "")
        log_audit(db, actor.client.id, "store_%s_%s" % (kind.key, action), "store_doc", doc.id, doc.number, doc.status, request=request, **_who(actor))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return doc_dict(db, kind, doc, detail=True)
