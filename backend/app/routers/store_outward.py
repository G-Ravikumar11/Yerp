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
from app.models.store_core import DBStore, DBStoreBin, DBStoreUserAssignment, DocStatus
from app.models.store_outward import (
    INDENT, ISSUE, ISSUE_RETURN, SITE, DBStoreGatePass, DBStoreIndent, DBStoreIndentLine, DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreOutwardLog, DBStoreWriteoffRequest,
)
from app.models.store_extras import DBStoreIndentLineNote
from app.services import store_outward as svc
from app.services.store_batches import batches_on_hand
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
    indent_line_id: Optional[int] = None  # the indent line this fills, when issued against an indent
    batch_no: str = ""                    # the batch it is taken from; an expired one is refused
    chargeable: bool = False              # subcontractor issue: recovered from their bill (false = free of cost)
    recovery_basis: str = ""              # CONTRACT_RATE | AVERAGE_COST (the company's usual when left out)
    recovery_rate: str = ""               # the contract rate, per base unit, when the basis is CONTRACT_RATE
    handling_pct: str = ""                # added to the rate for handling (the company's default when left out)
    expected_return_date: str = ""
    remarks: str = ""


class IssueIn(BaseModel):
    store_id: int
    issue_date: str
    issue_type: str = SITE
    project_id: int
    work_order_id: Optional[int] = None
    indent_id: Optional[int] = None
    subcontractor_id: Optional[int] = None
    subcontract_order_id: Optional[int] = None
    received_by_type: str = "PERSON"      # PERSON | GANG | FOREMAN
    received_by_employee_id: Optional[int] = None
    received_by_name: str = ""
    purpose: str = ""
    remarks: str = ""
    lines: List[IssueLineIn]


class ReturnLineIn(BaseModel):
    issue_line_id: int
    qty_returned: str = ""
    qty_lost: str = ""
    uom: str = ""
    reason: str = ""
    condition: str = "GOOD"               # GOOD | DAMAGED (damaged goods need a bin)
    bin_id: Optional[int] = None


class ReturnIn(BaseModel):
    issue_id: int
    return_date: str
    remarks: str = ""
    lines: List[ReturnLineIn]


class IndentLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    purpose: str = ""


class IndentIn(BaseModel):
    store_id: int
    indent_date: str = ""
    required_by: str = ""
    project_id: int
    work_order_id: Optional[int] = None
    boq_item_id: Optional[int] = None
    activity: str = ""
    remarks: str = ""
    lines: List[IndentLineIn]


class ApproveLineIn(BaseModel):
    line_id: int
    approved_qty: str
    uom: str = ""
    reason: str = ""                          # why it was cut back (or the approval's remarks are taken)
    substitute_item_id: Optional[int] = None  # another item given in place of what was cut
    substitute_qty: str = ""
    substitute_uom: str = ""


class ApproveIn(BaseModel):
    lines: List[ApproveLineIn] = []       # lines left out are approved as asked
    remarks: str = ""


class ConvertIn(BaseModel):
    qty: str
    uom: str = ""
    rate: str
    handling_pct: str = ""
    reason: str


class WriteoffIn(BaseModel):
    qty: str
    uom: str = ""
    reason: str


class GateLineIn(BaseModel):
    issue_line_id: int
    qty: str
    uom: str = ""


class GatePassIn(BaseModel):
    issue_id: int
    gate_date: str
    vehicle_no: str = ""
    driver_name: str = ""
    destination: str
    purpose: str = ""
    expected_return_date: str = ""
    remarks: str = ""
    lines: List[GateLineIn] = []          # left out: everything on the issue


class SettingsIn(BaseModel):
    subcon_handling_pct: str = "0"
    default_recovery_basis: str = "AVERAGE_COST"


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


def _has(actor, right) -> bool:
    if actor.employee is None:
        return True
    perms = permissions_for(actor.employee)
    return right in perms or "store.admin" in perms


def doc_dict(db, kind, doc, detail=False):
    store = db.get(DBStore, doc.store_id)
    out = {"kind": kind.key, "id": doc.id, "number": doc.number, "status": doc.status, "store_id": doc.store_id, "store_code": store.code if store else "", "store_name": store.name if store else "",
           "date": _iso(getattr(doc, kind.date_attr)), "remarks": doc.remarks or "", "cancel_reason": doc.cancel_reason or "", "created_by": doc.created_by_name or "",
           "created_at": doc.created_at.isoformat(timespec="seconds") if doc.created_at else "", "posted_at": doc.posted_at.isoformat(timespec="seconds") if doc.posted_at else ""}
    if kind.key == "issue":
        job = db.get(models.DBJob, doc.project_id)
        wo = db.get(models.DBWorkOrder, doc.work_order_id) if doc.work_order_id else None
        indent = db.get(DBStoreIndent, doc.indent_id) if doc.indent_id else None
        order = db.get(models.DBSubcontractOrder, doc.subcontract_order_id) if doc.subcontract_order_id else None
        lines = svc.issue_lines(db, doc)
        out.update({"issue_type": doc.issue_type, "project_id": doc.project_id, "project": ("%s - %s" % (job.number, job.name)) if job else "", "work_order_id": doc.work_order_id,
                    "work_order": wo.number if wo else "", "indent_id": doc.indent_id, "indent_number": indent.number if indent else "", "subcontractor_id": doc.subcontractor_id,
                    "subcontract_order_id": doc.subcontract_order_id, "subcontract_order": (order.wo_number or str(order.id)) if order else "", "received_by_type": doc.received_by_type or "",
                    "received_by_employee_id": doc.received_by_employee_id, "received_by_name": doc.received_by_name or "", "holder_type": doc.holder_type or "", "holder_id": doc.holder_id,
                    "holder_name": doc.holder_name or "", "purpose": doc.purpose or "", "direct": bool(doc.direct), "line_count": len(lines)})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            outstanding = svc.outstanding_on(db, doc) if doc.status == DocStatus.POSTED.value else {}
            boqs = {b.id: b for b in db.query(models.DBBoqLine).filter(models.DBBoqLine.id.in_([l.boq_item_id for l in lines if l.boq_item_id] or [0])).all()}
            recs = {r.issue_line_id: r for r in db.query(svc.DBStoreRecovery).filter(svc.DBStoreRecovery.issue_line_id.in_([l.id for l in lines] or [0]), svc.DBStoreRecovery.source == "ISSUE",
                                                                                      svc.DBStoreRecovery.status == "OPEN").all()}
            out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                             "entry_uom": l.entry_uom or "", "entry_qty": svc.s3(l.entry_qty), "qty": svc.s3(l.qty), "boq_item_id": l.boq_item_id, "indent_line_id": l.indent_line_id,
                             "boq_item": ("%s %s" % (boqs[l.boq_item_id].item_no or "", (boqs[l.boq_item_id].description or "").split("\n")[0][:60])).strip() if l.boq_item_id in boqs else "",
                             "cost_head": l.cost_head, "chargeable": bool(l.chargeable), "recovery_basis": l.recovery_basis or "", "handling_pct": svc.s3(l.handling_pct),
                             "recovery_rate": svc.s3(l.recovery_rate), "resolved_rate": svc.s3(recs[l.id].recovery_rate) if l.id in recs else None,
                             "expected_return_date": _iso(l.expected_return_date), "returnable": svc.is_returnable(db, l.item_id),
                             "outstanding": svc.s3(outstanding.get(l.id, ZERO)) if doc.status == DocStatus.POSTED.value else None, "remarks": l.remarks or "", "batch_no": l.batch_no or ""} for l in lines]
            out["warnings"] = svc.norm_warnings(db, doc)
            out["gate_passes"] = [{"id": g.id, "number": g.number, "status": g.status} for g in db.query(DBStoreGatePass).filter(DBStoreGatePass.issue_id == doc.id).order_by(DBStoreGatePass.id).all()]
    else:
        issue = db.get(DBStoreIssue, doc.issue_id)
        lines = svc.return_lines(db, doc)
        out.update({"issue_id": doc.issue_id, "issue_number": issue.number if issue else "", "holder_name": issue.holder_name if issue else "", "line_count": len(lines)})
        if detail:
            items = _items(db, [l.item_id for l in lines])
            bins = {b.id: b for b in db.query(DBStoreBin).filter(DBStoreBin.id.in_([l.bin_id for l in lines if l.bin_id] or [0])).all()}
            out["lines"] = [{"id": l.id, "issue_line_id": l.issue_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
                             "base_uom": svc.base_uom_of(db, items[l.item_id]), "entry_uom": l.entry_uom or "", "qty_returned": svc.s3(l.qty_returned), "qty_lost": svc.s3(l.qty_lost),
                             "reason": l.reason or "", "condition": l.condition or "GOOD", "bin_id": l.bin_id, "bin": bins[l.bin_id].code if l.bin_id in bins else ""} for l in lines]
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


@router.get("/batches")
def batches(request: Request, store_id: int, item_id: int, on: str = "", db: Session = Depends(get_db)):
    """The batches of an item a store holds, oldest first, with their shelf life: the one to issue first is marked."""
    actor = store_actor(request, db, "store.outward.view")
    svc.store_of(db, actor.client.id, store_id)
    assert_store_access(actor.user, store_id)
    svc.item_of(db, actor.client.id, item_id)
    on_date = svc.day(on, "date", allow_future=True, required=False) or date.today()
    return {"batches": batches_on_hand(db, store_id, item_id, on_date)}


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


# --- more pickers, settings and recoveries ------------------------------------------------------------------------------------

@router.get("/pick/subcontract-orders")
def pick_subcontract_orders(subcontractor_id: int, request: Request, project_id: int = 0, db: Session = Depends(get_db)):
    """A subcontractor's work orders (on a project, if one is given), for the issue to be made under."""
    actor = store_actor(request, db, "store.outward.view")
    q = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.client_id == actor.client.id, models.DBSubcontractOrder.contractor_id == subcontractor_id)
    if project_id:
        q = q.filter((models.DBSubcontractOrder.job_id == project_id) | models.DBSubcontractOrder.job_id.is_(None))
    return {"items": [{"id": o.id, "number": o.wo_number or str(o.id), "subject": (o.subject or "")[:80], "status": o.status or ""} for o in q.order_by(models.DBSubcontractOrder.id.desc()).limit(100).all()]}


@router.get("/pick/bins")
def pick_bins(store_id: int, request: Request, db: Session = Depends(get_db)):
    """A store's bins, for the bin damaged goods are returned into."""
    actor = store_actor(request, db, "store.outward.view")
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != actor.client.id:
        raise HTTPException(404, "Store not found")
    assert_store_access(actor.user, store.id)
    return {"items": [{"id": b.id, "code": b.code, "description": b.description or ""} for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == store.id, DBStoreBin.is_active.is_(True)).order_by(DBStoreBin.code).all()]}


def _settings_dict(row):
    return {"subcon_handling_pct": svc.s3(row.subcon_handling_pct), "default_recovery_basis": row.default_recovery_basis or "AVERAGE_COST"}


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    """The company's outward defaults: the handling percentage added to what is recovered from a subcontractor, and how that rate is usually set."""
    actor = store_actor(request, db, "store.outward.view")
    row = svc.outward_settings(db, actor.client.id)
    db.commit()
    return _settings_dict(row)


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.approve")
    basis = (body.default_recovery_basis or "").strip().upper()
    if basis not in (svc.CONTRACT_RATE, svc.AVERAGE_COST):
        raise HTTPException(400, "The usual recovery rate is the CONTRACT_RATE or the AVERAGE_COST.")
    row = svc.outward_settings(db, actor.client.id)
    row.subcon_handling_pct, row.default_recovery_basis = svc.pct(body.subcon_handling_pct, "The handling percentage"), basis
    log_audit(db, actor.client.id, "store_outward_settings", "store_outward", row.id, "settings", "%s%% %s" % (row.subcon_handling_pct, basis), request=request, **_who(actor))
    db.commit()
    return _settings_dict(row)


@router.get("/recoveries")
def recoveries(request: Request, subcontractor_id: int = 0, project_id: int = 0, status: str = "OPEN", db: Session = Depends(get_db)):
    """What the store has charged to subcontractors and holders to be recovered: chargeable issues and returnables converted to a charge."""
    actor = store_actor(request, db, "store.outward.view")
    seen = _visible(db, actor)
    q = db.query(svc.DBStoreRecovery).filter(svc.DBStoreRecovery.client_id == actor.client.id)
    if status:
        q = q.filter(svc.DBStoreRecovery.status == status.strip().upper())
    if subcontractor_id:
        q = q.filter(svc.DBStoreRecovery.subcontractor_id == subcontractor_id)
    if project_id:
        q = q.filter(svc.DBStoreRecovery.project_id == project_id)
    if seen is not None:
        q = q.filter(svc.DBStoreRecovery.store_id.in_(seen or {0}))
    rows = q.order_by(svc.DBStoreRecovery.id.desc()).limit(500).all()
    items = _items(db, [r.item_id for r in rows])
    issues = {l.id: i for l, i in db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id).filter(DBStoreIssueLine.id.in_([r.issue_line_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        net = max(ZERO, Decimal(str(r.qty)) - Decimal(str(r.qty_returned)))
        out.append({"id": r.id, "source": r.source, "issue_number": issues[r.issue_line_id].number if r.issue_line_id in issues else "", "issue_line_id": r.issue_line_id, "holder_type": r.holder_type or "",
                    "holder_name": r.holder_name or "", "subcontractor_id": r.subcontractor_id, "subcontract_order_id": r.subcontract_order_id, "project_id": r.project_id, "item_code": items[r.item_id].item_code,
                    "item_name": items[r.item_id].item_name, "qty": svc.s3(r.qty), "qty_returned": svc.s3(r.qty_returned), "basis": r.basis, "base_rate": svc.s3(r.base_rate), "handling_pct": svc.s3(r.handling_pct),
                    "recovery_rate": svc.s3(r.recovery_rate), "amount": format((net * Decimal(str(r.recovery_rate))).quantize(Decimal("0.01")), "f"), "status": r.status,
                    "created_at": r.created_at.isoformat(timespec="seconds") if r.created_at else ""})
    return {"total_amount": format(sum((Decimal(o["amount"]) for o in out if o["status"] == "OPEN"), ZERO), "f"), "items": out}


# --- converting a returnable to a recovery, or to a write-off request ---------------------------------------------------------------

def _line_issue(db, actor, issue_line_id):
    line = db.get(DBStoreIssueLine, issue_line_id)
    issue = db.get(DBStoreIssue, line.issue_id) if line else None
    if issue is None or issue.client_id != actor.client.id:
        raise HTTPException(404, "Issue line not found")
    assert_store_access(actor.user, issue.store_id)
    return line, issue


@router.post("/returnables/{issue_line_id}/convert")
def convert_returnable(issue_line_id: int, body: ConvertIn, request: Request, db: Session = Depends(get_db)):
    """Close what is still out on an issue line by charging the holder for it: a recovery at a rate (and handling percentage) to be taken from their bill.
    Needs store.outward.approve."""
    actor = store_actor(request, db, "store.outward.approve")
    _line_issue(db, actor, issue_line_id)
    rec, closure = svc.convert_returnable(db, actor, issue_line_id, body.qty, body.uom, body.rate, body.handling_pct, body.reason)
    log_audit(db, actor.client.id, "store_returnable_converted", "store_issue_line", issue_line_id, "recovery %s" % rec.id, body.reason, request=request, **_who(actor))
    db.commit()
    return {"message": "Converted to a recovery", "recovery_id": rec.id, "recovery_rate": svc.s3(rec.recovery_rate), "qty": svc.s3(closure.qty),
            "amount": format((Decimal(str(rec.qty)) * Decimal(str(rec.recovery_rate))).quantize(Decimal("0.01")), "f")}


@router.post("/returnables/{issue_line_id}/writeoff")
def writeoff_returnable(issue_line_id: int, body: WriteoffIn, request: Request, db: Session = Depends(get_db)):
    """Close what is still out by asking for it to be written off. This only raises the request; the write-off is posted by the control slice."""
    actor = store_actor(request, db, "store.outward.create")
    _line_issue(db, actor, issue_line_id)
    req, closure = svc.writeoff_returnable(db, actor, issue_line_id, body.qty, body.uom, body.reason)
    log_audit(db, actor.client.id, "store_returnable_writeoff_requested", "store_issue_line", issue_line_id, "request %s" % req.id, body.reason, request=request, **_who(actor))
    db.commit()
    return {"message": "Write-off requested", "request_id": req.id, "qty": svc.s3(closure.qty)}


# --- indents ----------------------------------------------------------------------------------------------------------------------

def _indent_or_404(db, actor, indent_id):
    indent = db.get(DBStoreIndent, indent_id)
    if indent is None or indent.client_id != actor.client.id:
        raise HTTPException(404, "Indent not found")
    assert_store_access(actor.user, indent.store_id)
    return indent


def indent_dict(db, indent, detail=False):
    store = db.get(DBStore, indent.store_id)
    job = db.get(models.DBJob, indent.project_id)
    wo = db.get(models.DBWorkOrder, indent.work_order_id) if indent.work_order_id else None
    boq = db.get(models.DBBoqLine, indent.boq_item_id) if indent.boq_item_id else None
    lines = svc.indent_lines(db, indent)
    done = svc.indent_fulfilled(db, indent)
    asked = sum((Decimal(str(l.qty)) for l in lines), ZERO)
    approved = sum((Decimal(str(l.approved_qty or 0)) for l in lines), ZERO)
    out = {"id": indent.id, "number": indent.number, "status": indent.status, "store_id": indent.store_id, "store_code": store.code if store else "", "store_name": store.name if store else "",
           "date": _iso(indent.indent_date), "required_by": _iso(indent.required_by), "project_id": indent.project_id, "project": ("%s - %s" % (job.number, job.name)) if job else "",
           "work_order_id": indent.work_order_id, "work_order": wo.number if wo else "", "boq_item_id": indent.boq_item_id,
           "boq_item": ("%s %s" % (boq.item_no or "", (boq.description or "").split("\n")[0][:60])).strip() if boq else "", "activity": indent.activity or "", "remarks": indent.remarks or "",
           "requested_by": indent.requested_by_name or "", "approved_by": indent.approved_by_name or "", "approved_at": indent.approved_at.isoformat(timespec="seconds") if indent.approved_at else "",
           "approver_remarks": indent.approver_remarks or "", "cancel_reason": indent.cancel_reason or "", "short_closed": bool(indent.short_closed), "line_count": len(lines),
           "fulfilled_pct": float((sum(done.values(), ZERO) / approved * 100).quantize(Decimal("0.1"))) if approved > 0 else 0.0,
           "overdue": bool(indent.required_by and indent.required_by < date.today() and indent.status in ("OPEN", "PARTIAL")), "created_at": indent.created_at.isoformat(timespec="seconds") if indent.created_at else ""}
    if detail:
        items = _items(db, [l.item_id for l in lines])
        notes = {n.indent_line_id: n for n in db.query(DBStoreIndentLineNote).filter(DBStoreIndentLineNote.indent_line_id.in_([l.id for l in lines] or [0])).all()}
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                         "entry_uom": l.entry_uom or "", "entry_qty": svc.s3(l.entry_qty), "qty": svc.s3(l.qty), "approved_qty": None if l.approved_qty is None else svc.s3(l.approved_qty),
                         "fulfilled": svc.s3(done.get(l.id, ZERO)), "pending": svc.s3(max(ZERO, Decimal(str(l.approved_qty or 0)) - done.get(l.id, ZERO))) if l.approved_qty is not None else None,
                         "purpose": l.purpose or "", "reason": notes[l.id].reason or "" if l.id in notes else "", "substitute_for_line_id": notes[l.id].substitute_for_line_id if l.id in notes else None}
                        for l in lines]
        out["history"] = [{"action": h.action, "from": h.from_status, "to": h.to_status, "by": h.user_name, "at": h.at.isoformat(timespec="seconds") if h.at else "", "note": h.note or ""}
                          for h in db.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == INDENT, DBStoreOutwardLog.doc_id == indent.id).order_by(DBStoreOutwardLog.id).all()]
        out["issues"] = [{"id": i.id, "number": i.number, "status": i.status} for i in db.query(DBStoreIssue).filter(DBStoreIssue.indent_id == indent.id).order_by(DBStoreIssue.id).all()]
    return out


def _indent_values(db, actor, body):
    store = svc.store_of(db, actor.client.id, body.store_id)
    assert_store_access(actor.user, store.id)
    on = svc.day(body.indent_date, "Indent date") if body.indent_date else date.today()
    needed = svc.day(body.required_by, "Required-by date", allow_future=True, required=False)
    if needed is not None and needed < on:
        raise HTTPException(400, "The required-by date is before the indent date.")
    project, _wo = svc.check_indent_header(db, actor.client.id, body)
    return store, on, needed, svc.build_indent_lines(db, actor.client.id, body.lines)


@router.get("/indent")
def list_indents(request: Request, status: str = "", store_id: int = 0, project_id: int = 0, q: str = "", limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    query = db.query(DBStoreIndent).filter(DBStoreIndent.client_id == actor.client.id)
    seen = _visible(db, actor)
    if seen is not None:
        query = query.filter(DBStoreIndent.store_id.in_(seen or {0}))
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(DBStoreIndent.store_id == store_id)
    if status:
        query = query.filter(DBStoreIndent.status == status.strip().upper())
    if project_id:
        query = query.filter(DBStoreIndent.project_id == project_id)
    if (q or "").strip():
        like = "%" + q.strip().replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(DBStoreIndent.number.ilike(like), DBStoreIndent.activity.ilike(like), DBStoreIndent.requested_by_name.ilike(like)))
    total = query.count()
    rows = query.order_by(DBStoreIndent.id.desc()).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
    return {"total": total, "items": [indent_dict(db, r) for r in rows]}


@router.get("/indent/export")
def export_indents(request: Request, status: str = "", store_id: int = 0, project_id: int = 0, q: str = "", db: Session = Depends(get_db)):
    rows = list_indents(request, status=status, store_id=store_id, project_id=project_id, q=q, limit=500, db=db)["items"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Indents"
    cols = ["number", "date", "required_by", "status", "store_code", "project", "work_order", "activity", "requested_by", "approved_by", "line_count", "fulfilled_pct"]
    ws.append([c.replace("_", " ").title() for c in cols])
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="outward-indents.xlsx"'})


@router.get("/indent-lines/{indent_id}")
def indent_pending_lines(indent_id: int, request: Request, db: Session = Depends(get_db)):
    """What is still to be issued on an approved indent, line by line, for the issue form."""
    actor = store_actor(request, db, "store.outward.view")
    indent = _indent_or_404(db, actor, indent_id)
    pending = svc.indent_pending(db, indent)
    items = _items(db, [l.item_id for l in svc.indent_lines(db, indent)])
    boq = db.get(models.DBBoqLine, indent.boq_item_id) if indent.boq_item_id else None
    return {"indent": {"id": indent.id, "number": indent.number, "status": indent.status, "store_id": indent.store_id, "project_id": indent.project_id, "work_order_id": indent.work_order_id,
                       "boq_item_id": indent.boq_item_id, "boq_item": ("%s %s" % (boq.item_no or "", (boq.description or "")[:60])).strip() if boq else ""},
            "lines": [{"indent_line_id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "base_uom": svc.base_uom_of(db, items[l.item_id]),
                       "approved": svc.s3(l.approved_qty or 0), "pending": svc.s3(max(ZERO, pending.get(l.id, ZERO)))} for l in svc.indent_lines(db, indent) if pending.get(l.id, ZERO) > 0]}


@router.post("/indent")
def create_indent(body: IndentIn, request: Request, db: Session = Depends(get_db)):
    """A site engineer asks for material. It is a draft until submitted, and then waits for the project manager."""
    actor = store_actor(request, db, "store.outward.create")
    store, on, needed, lines = _indent_values(db, actor, body)
    indent = DBStoreIndent(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, svc.INDENT, store.id, on), status="DRAFT", indent_date=on, required_by=needed, project_id=body.project_id,
                           work_order_id=body.work_order_id or None, boq_item_id=body.boq_item_id or None, activity=svc.text(body.activity, "activity", 200), remarks=svc.text(body.remarks, "remarks", 500),
                           requested_by_id=actor.user_id, requested_by_name=actor.name)
    db.add(indent)
    db.flush()
    svc.write_indent_lines(db, indent, lines)
    svc.log(db, actor, svc.INDENT, indent.id, "create", "", "DRAFT")
    log_audit(db, actor.client.id, "store_indent_created", "store_doc", indent.id, indent.number, "", request=request, **_who(actor))
    db.commit()
    return indent_dict(db, indent, detail=True)


@router.put("/indent/{indent_id}")
def edit_indent(indent_id: int, body: IndentIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    indent = _indent_or_404(db, actor, indent_id)
    if indent.status != "DRAFT":
        raise HTTPException(409, "It is %s. Only a draft can be edited; cancel it and raise a new one to correct it." % indent.status.lower())
    if body.store_id != indent.store_id:
        raise HTTPException(400, "An indent cannot be moved to another store; cancel it and raise a new one.")
    _store, on, needed, lines = _indent_values(db, actor, body)
    indent.indent_date, indent.required_by, indent.project_id = on, needed, body.project_id
    indent.work_order_id, indent.boq_item_id = body.work_order_id or None, body.boq_item_id or None
    indent.activity, indent.remarks = svc.text(body.activity, "activity", 200), svc.text(body.remarks, "remarks", 500)
    svc.write_indent_lines(db, indent, lines)
    db.commit()
    return indent_dict(db, indent, detail=True)


@router.get("/indent/{indent_id}")
def get_indent(indent_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return indent_dict(db, _indent_or_404(db, actor, indent_id), detail=True)


@router.get("/indent/{indent_id}/print")
def print_indent(indent_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    indent = _indent_or_404(db, actor, indent_id)
    try:
        pdf = form_pdf.build_form_pdf(FORMS["indent"][1](db, actor.client, indent))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % indent.number.replace("/", "-")})


@router.post("/indent/{indent_id}/submit")
def submit_indent(indent_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    indent = _indent_or_404(db, actor, indent_id)
    svc.indent_submit(db, actor, indent)
    log_audit(db, actor.client.id, "store_indent_submitted", "store_doc", indent.id, indent.number, "", request=request, **_who(actor))
    db.commit()
    return indent_dict(db, indent, detail=True)


@router.post("/indent/{indent_id}/approve")
def approve_indent(indent_id: int, request: Request, body: Optional[ApproveIn] = None, db: Session = Depends(get_db)):
    """Approve an indent as the project manager. The approver can reduce any quantity (to nothing) but not raise it; lines left out are approved as asked."""
    actor = store_actor(request, db, "store.outward.approve")
    indent = _indent_or_404(db, actor, indent_id)
    body = body or ApproveIn()
    svc.indent_approve(db, actor, indent, body.lines, body.remarks, _has(actor, "store.admin"))
    log_audit(db, actor.client.id, "store_indent_approved", "store_doc", indent.id, indent.number, "", request=request, **_who(actor))
    db.commit()
    return indent_dict(db, indent, detail=True)


@router.post("/indent/{indent_id}/cancel")
def cancel_indent(indent_id: int, request: Request, body: Optional[ActionIn] = None, db: Session = Depends(get_db)):
    actor = store_actor(request, db, ("store.outward.create", "store.outward.cancel"))
    indent = _indent_or_404(db, actor, indent_id)
    if indent.status in ("OPEN", "PARTIAL") and not _has(actor, "store.outward.cancel"):
        raise HTTPException(403, "An approved indent is cancelled by someone who holds the cancel right.")
    svc.indent_cancel(db, actor, indent, body.reason if body else "")
    log_audit(db, actor.client.id, "store_indent_cancelled", "store_doc", indent.id, indent.number, "", request=request, **_who(actor))
    db.commit()
    return indent_dict(db, indent, detail=True)


@router.post("/indent/{indent_id}/close")
def close_indent(indent_id: int, request: Request, body: Optional[ActionIn] = None, db: Session = Depends(get_db)):
    """Close an approved indent short: whatever is still pending will not be issued."""
    actor = store_actor(request, db, "store.outward.approve")
    indent = _indent_or_404(db, actor, indent_id)
    svc.indent_close(db, actor, indent, body.reason if body else "")
    log_audit(db, actor.client.id, "store_indent_closed", "store_doc", indent.id, indent.number, "", request=request, **_who(actor))
    db.commit()
    return indent_dict(db, indent, detail=True)


@router.delete("/indent/{indent_id}")
def delete_indent(indent_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    indent = _indent_or_404(db, actor, indent_id)
    if indent.status != "DRAFT":
        raise HTTPException(409, "It is %s. Only a draft can be deleted." % indent.status.lower())
    db.query(DBStoreIndentLine).filter(DBStoreIndentLine.indent_id == indent.id).delete(synchronize_session=False)
    db.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == svc.INDENT, DBStoreOutwardLog.doc_id == indent.id).delete(synchronize_session=False)
    number = indent.number
    db.delete(indent)
    log_audit(db, actor.client.id, "store_indent_deleted", "store_doc", indent_id, number, "draft", request=request, **_who(actor))
    db.commit()
    return {"message": "Draft deleted"}


# --- gate passes ----------------------------------------------------------------------------------------------------------------------

def _gate_or_404(db, actor, gate_id):
    gp = db.get(DBStoreGatePass, gate_id)
    if gp is None or gp.client_id != actor.client.id:
        raise HTTPException(404, "Gate pass not found")
    assert_store_access(actor.user, gp.store_id)
    return gp


def gate_dict(db, gp, detail=False):
    store = db.get(DBStore, gp.store_id)
    issue = db.get(DBStoreIssue, gp.issue_id)
    lines = svc.gate_lines(db, gp)
    out = {"id": gp.id, "number": gp.number, "status": gp.status, "store_id": gp.store_id, "store_code": store.code if store else "", "date": _iso(gp.gate_date), "issue_id": gp.issue_id,
           "issue_number": issue.number if issue else "", "vehicle_no": gp.vehicle_no or "", "driver_name": gp.driver_name or "", "destination": gp.destination or "", "purpose": gp.purpose or "",
           "returnable": bool(gp.returnable), "expected_return_date": _iso(gp.expected_return_date), "authorised_by": gp.authorised_by_name or "", "remarks": gp.remarks or "", "cancel_reason": gp.cancel_reason or "",
           "overdue_days": max(0, (date.today() - gp.expected_return_date).days) if gp.returnable and gp.status == "ISSUED" and gp.expected_return_date else 0, "line_count": len(lines),
           "received_by": (issue.received_by_name or issue.holder_name or "") if issue else "", "created_by": gp.created_by_name or ""}
    if detail:
        items = _items(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "issue_line_id": l.issue_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
                         "base_uom": svc.base_uom_of(db, items[l.item_id]), "qty": svc.s3(l.qty)} for l in lines]
        out["history"] = [{"action": h.action, "from": h.from_status, "to": h.to_status, "by": h.user_name, "at": h.at.isoformat(timespec="seconds") if h.at else "", "note": h.note or ""}
                          for h in db.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == svc.GATE_PASS, DBStoreOutwardLog.doc_id == gp.id).order_by(DBStoreOutwardLog.id).all()]
    return out


@router.get("/gate-pass")
def list_gate_passes(request: Request, status: str = "", store_id: int = 0, q: str = "", limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    query = db.query(DBStoreGatePass).filter(DBStoreGatePass.client_id == actor.client.id)
    seen = _visible(db, actor)
    if seen is not None:
        query = query.filter(DBStoreGatePass.store_id.in_(seen or {0}))
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(DBStoreGatePass.store_id == store_id)
    if status:
        query = query.filter(DBStoreGatePass.status == status.strip().upper())
    if (q or "").strip():
        like = "%" + q.strip().replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(DBStoreGatePass.number.ilike(like), DBStoreGatePass.vehicle_no.ilike(like), DBStoreGatePass.destination.ilike(like)))
    total = query.count()
    rows = query.order_by(DBStoreGatePass.id.desc()).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
    return {"total": total, "items": [gate_dict(db, g) for g in rows]}


@router.get("/gate-pass/export")
def export_gate_passes(request: Request, status: str = "", store_id: int = 0, q: str = "", db: Session = Depends(get_db)):
    rows = list_gate_passes(request, status=status, store_id=store_id, q=q, limit=500, db=db)["items"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Gate passes"
    cols = ["number", "date", "status", "store_code", "issue_number", "vehicle_no", "driver_name", "destination", "returnable", "expected_return_date", "overdue_days", "received_by"]
    ws.append([c.replace("_", " ").title() for c in cols])
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(content=buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="gate-passes.xlsx"'})


@router.post("/gate-pass")
def create_gate_pass(body: GatePassIn, request: Request, db: Session = Depends(get_db)):
    """A pass for material leaving the store's premises, made from a posted issue. It moves no stock."""
    actor = store_actor(request, db, "store.outward.create")
    issue = db.get(DBStoreIssue, body.issue_id)
    if issue is None or issue.client_id != actor.client.id:
        raise HTTPException(404, "Issue not found")
    assert_store_access(actor.user, issue.store_id)
    gp = svc.create_gate_pass(db, actor, body)
    log_audit(db, actor.client.id, "store_gate_pass_created", "store_doc", gp.id, gp.number, issue.number, request=request, **_who(actor))
    db.commit()
    return gate_dict(db, gp, detail=True)


@router.get("/gate-pass/{gate_id}")
def get_gate_pass(gate_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return gate_dict(db, _gate_or_404(db, actor, gate_id), detail=True)


@router.get("/gate-pass/{gate_id}/print")
def print_gate_pass(gate_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    gp = _gate_or_404(db, actor, gate_id)
    try:
        pdf = form_pdf.build_form_pdf(FORMS["gate-pass"][1](db, actor.client, gp))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % gp.number.replace("/", "-")})


@router.post("/gate-pass/{gate_id}/close")
def close_gate_pass(gate_id: int, request: Request, db: Session = Depends(get_db)):
    """The material of a returnable pass is back."""
    actor = store_actor(request, db, "store.outward.create")
    gp = _gate_or_404(db, actor, gate_id)
    svc.gate_close(db, actor, gp)
    db.commit()
    return gate_dict(db, gp, detail=True)


@router.post("/gate-pass/{gate_id}/cancel")
def cancel_gate_pass(gate_id: int, request: Request, body: Optional[ActionIn] = None, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.cancel")
    gp = _gate_or_404(db, actor, gate_id)
    svc.gate_cancel(db, actor, gp, body.reason if body else "")
    log_audit(db, actor.client.id, "store_gate_pass_cancelled", "store_doc", gp.id, gp.number, "", request=request, **_who(actor))
    db.commit()
    return gate_dict(db, gp, detail=True)


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
    head = svc.check_issue_header(db, actor.client.id, body)
    if head["issue_type"] == "SITE" and head["indent"] is None and not _has(actor, "store.outward.direct_issue"):
        raise HTTPException(403, "A site issue is made against an approved indent, unless you hold the direct-issue right.")
    lines = svc.build_issue_lines(db, actor.client.id, body, head, on, issue_id=issue.id if issue else None)
    return store, on, head, lines


def _fill_issue(issue, body, on, head):
    issue.issue_date, issue.issue_type, issue.project_id, issue.work_order_id = on, head["issue_type"], body.project_id, head["work_order_id"]
    issue.indent_id = head["indent"].id if head["indent"] is not None else None
    issue.subcontractor_id, issue.subcontract_order_id = head["subcontractor_id"], head["order_id"]
    issue.holder_type, issue.holder_id, issue.holder_name = head["holder_type"], head["holder_id"], head["holder_name"]
    issue.received_by_type, issue.received_by_employee_id, issue.received_by_name = head["received_type"], head["received_employee_id"], head["received_name"]
    issue.direct = 1 if (head["issue_type"] == "SITE" and head["indent"] is None) else 0
    issue.purpose, issue.remarks = svc.text(body.purpose, "purpose", 200), svc.text(body.remarks, "remarks", 500)


def _new_issue(db, actor, body, request):
    store, on, head, lines = _issue_values(db, actor, body)
    issue = DBStoreIssue(client_id=actor.client.id, store_id=store.id, number=svc.numbered(db, ISSUE, store.id, on), status=DocStatus.DRAFT.value)
    _fill_issue(issue, body, on, head)
    db.add(issue)
    db.flush()
    svc.write_issue_lines(db, issue, lines)
    return issue


@router.post("/issue")
def create_issue(body: IssueIn, request: Request, db: Session = Depends(get_db)):
    """A draft issue, against an approved indent (`indent_id`) or - for someone who holds store.outward.direct_issue - on its own."""
    actor = store_actor(request, db, "store.outward.create")
    issue = _new_issue(db, actor, body, request)
    _created(db, actor, svc.KINDS["issue"], issue, request, direct=bool(issue.direct))
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
            _created(db, actor, kind, issue, request, direct=True)
            svc.advance(db, actor, kind, issue, "submit", direct=True)
            svc.advance(db, actor, kind, issue, "approve", direct=True)
            svc.advance(db, actor, kind, issue, "post", direct=True)
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
    _store, on, head, lines = _issue_values(db, actor, body, issue)
    _fill_issue(issue, body, on, head)
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
