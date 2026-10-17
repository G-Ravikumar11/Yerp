"""Store module - outward slice (requisitions, issues, issue returns, write-off requests). Owned by P3.

Rules that matter:
  * An issue takes stock out only when POSTED (ISSUE_OUT, or SUBCON_ISSUE_OUT for a subcontractor), valued at the store's
    average, carrying its project / work order / BOQ item / cost head / subcontractor so cost reports can read it. Material
    must be charged to a project or a cost head.
  * An issue made against an approved requisition may not exceed what the requisition still allows. An issue without a
    requisition is a direct issue and needs store.outward.direct_issue (checked by the route).
  * Returnable items (category RETURNABLE or TOOL) must name who holds them; what has not come back is "outstanding".
  * A return brings stock back at the rate it left at (ISSUE_RETURN_IN / SUBCON_RETURN_IN) with the same costing, so cost nets
    out. Quantity declared lost raises a write-off request for the control slice to close.
  * Nothing here commits: the caller owns the transaction (see routers/store_outward.py).
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from fastapi import HTTPException

from app import models
from app.models.store_core import CostHead, DBStore, DBStoreItemSettings, DocStatus, ItemCategory, MovementType, StoreError
from app.models.store_outward import (
    DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreIssueReturnLine, DBStoreOutwardLog, DBStoreRequisition,
    DBStoreRequisitionLine, DBStoreWriteoffRequest,
)
from app.schemas.store_contracts import ReturnableOutstanding, SubconIssueLine, WriteOffRequest
from app.services.stock_ledger import convert_to_base, post_movement, reverse_document
from app.services.store_numbering import next_doc_number

ZERO = Decimal("0")
_Q3, _R4 = Decimal("0.001"), Decimal("0.0001")
S = DocStatus
RETURNABLE_CATEGORIES = (ItemCategory.RETURNABLE.value, ItemCategory.TOOL.value)
ISSUE_TYPES = ("SITE", "SUBCONTRACTOR")
HOLDER_TYPES = ("EMPLOYEE", "SUBCONTRACTOR", "GANG")
NEXT = {"submit": (S.DRAFT, S.SUBMITTED), "approve": (S.SUBMITTED, S.APPROVED), "post": (S.APPROVED, S.POSTED)}
PAST = {"submit": "submitted", "approve": "approved", "post": "posted"}


def dec(v, what="Quantity") -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        raise HTTPException(400, "%s is not a number." % what) from None


def q3(v) -> Decimal:
    return dec(v).quantize(_Q3, rounding=ROUND_HALF_UP)


def to_date(v, what):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s must be a date like 2026-04-01." % what) from None


def _past(d, what):
    if d > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)
    return d


def _iso(d):
    return d.isoformat() if d else None


def log_status(db, doc_type, doc, new_status, actor, note=""):
    db.add(DBStoreOutwardLog(doc_type=doc_type, doc_id=doc.id, from_status=doc.status or "", to_status=new_status, user_id=actor.user_id,
                             user_name=actor.name, note=note or ""))
    doc.status = new_status


def doc_log(db, doc_type, doc_id):
    rows = db.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == doc_type, DBStoreOutwardLog.doc_id == doc_id).order_by(DBStoreOutwardLog.id).all()
    return [{"from": r.from_status, "to": r.to_status, "user": r.user_name, "at": _iso(r.at), "note": r.note} for r in rows]


def _item(db, client_id, item_id):
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id:
        raise HTTPException(404, "Item %s not found" % item_id)
    return item


def _is_returnable(db, item_id) -> bool:
    st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    return bool(st and st.category in RETURNABLE_CATEGORIES)


def _qty_in_base(db, item, ln, n):
    entered = q3(ln.get("qty"))
    if entered <= 0:
        raise HTTPException(400, "Line %d: the quantity must be more than zero." % n)
    st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    uom = (ln.get("uom") or "").strip() or (st.base_uom if st else item.units_of_measure or "")
    try:
        base = convert_to_base(db, item.id, entered, uom)
    except Exception as exc:
        raise HTTPException(400, "Line %d: %s" % (n, exc)) from None
    if base <= 0:
        raise HTTPException(400, "Line %d: that quantity is too small to count in the base unit." % n)
    return uom, entered, base


def _costing(db, actor, store, body, fallback=None):
    """Validate and normalise where an issue or requisition is charged: (project, work order, BOQ item, cost head)."""
    g = lambda k: body.get(k) if body.get(k) is not None else (getattr(fallback, k, None) if fallback is not None else None)   # noqa: E731
    project_id, wo_id, boq_id, head = g("project_id") or store.project_id, g("work_order_id"), g("boq_item_id"), g("cost_head")
    if project_id and not db.query(models.DBJob.id).filter(models.DBJob.id == project_id, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(404, "Project not found")
    wo = None
    if wo_id:
        wo = db.get(models.DBWorkOrder, wo_id)
        if wo is None or wo.client_id != actor.client.id:
            raise HTTPException(404, "Work order not found")
        if project_id and wo.job_id != project_id:
            raise HTTPException(400, "That work order belongs to a different project.")
        project_id = wo.job_id
    if boq_id:
        if wo is None:
            raise HTTPException(400, "Name the work order the BOQ item belongs to.")
        line = db.get(models.DBBoqLine, boq_id)
        if line is None or line.boq_id != wo.boq_id:
            raise HTTPException(400, "That BOQ item is not on the work order.")
    if head:
        try:
            head = CostHead(head).value
        except ValueError:
            raise HTTPException(400, "Unknown cost head.") from None
    return project_id, wo_id, boq_id, head


# =============================================================================================== requisition
def _fill_requisition_lines(db, actor, req, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    db.query(DBStoreRequisitionLine).filter(DBStoreRequisitionLine.requisition_id == req.id).delete(synchronize_session=False)
    seen = set()
    for n, ln in enumerate(lines_in, 1):
        item = _item(db, actor.client.id, ln.get("item_id"))
        if item.id in seen:
            raise HTTPException(400, "Line %d: %s is already on the requisition." % (n, item.item_name))
        seen.add(item.id)
        uom, entered, base = _qty_in_base(db, item, ln, n)
        db.add(DBStoreRequisitionLine(requisition_id=req.id, item_id=item.id, uom=uom, entered_qty=entered, qty=base, remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def create_requisition(db, actor, store, body):
    project_id, wo_id, boq_id, head = _costing(db, actor, store, body)
    d = _past(to_date(body.get("req_date") or date.today(), "Date"), "Date")
    req = DBStoreRequisition(client_id=actor.client.id, store_id=store.id, req_date=d, project_id=project_id, work_order_id=wo_id, boq_item_id=boq_id,
                             cost_head=head, required_by=to_date(body["required_by"], "Required by") if body.get("required_by") else None,
                             purpose=(body.get("purpose") or "").strip(), status=S.DRAFT.value, created_by=actor.user_id, created_by_name=actor.name, number="")
    db.add(req)
    db.flush()
    req.number = next_doc_number(db, "MRQ", store.id, on_date=d)
    _fill_requisition_lines(db, actor, req, body.get("lines") or [])
    log_status(db, "MRQ", req, S.DRAFT.value, actor, "Created")
    return req


def update_requisition(db, actor, req, store, body):
    if req.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft requisition can be edited.")
    req.project_id, req.work_order_id, req.boq_item_id, req.cost_head = _costing(db, actor, store, body, fallback=req)
    if body.get("req_date"):
        req.req_date = _past(to_date(body["req_date"], "Date"), "Date")
    if "required_by" in body:
        req.required_by = to_date(body["required_by"], "Required by") if body["required_by"] else None
    if body.get("purpose") is not None:
        req.purpose = body["purpose"].strip()
    if body.get("lines") is not None:
        _fill_requisition_lines(db, actor, req, body["lines"])


def requisition_lines(db, req):
    return db.query(DBStoreRequisitionLine).filter(DBStoreRequisitionLine.requisition_id == req.id).order_by(DBStoreRequisitionLine.id).all()


def _issued_on_req_line(db, req_line_id, exclude_issue_id=None):
    q = db.query(DBStoreIssueLine).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id).filter(
        DBStoreIssueLine.requisition_line_id == req_line_id, DBStoreIssue.status == S.POSTED.value)
    if exclude_issue_id:
        q = q.filter(DBStoreIssue.id != exclude_issue_id)
    return sum((l.qty for l in q.all()), ZERO)


def requisition_action(db, actor, req, action, reason=""):
    if action == "post":
        raise HTTPException(409, "A requisition moves no stock; issue against it instead.")
    if action == "cancel":
        live = db.query(DBStoreIssue).filter(DBStoreIssue.requisition_id == req.id, DBStoreIssue.status != S.CANCELLED.value).first()
        if live is not None:
            raise HTTPException(409, "Issue %s was made against this requisition; cancel it first." % live.number)
        reason = (reason or "").strip()
        if not reason:
            raise HTTPException(400, "A reason is needed to cancel.")
        if req.status == S.CANCELLED.value:
            raise HTTPException(409, "%s is already cancelled." % req.number)
        req.cancel_reason = reason
        return log_status(db, "MRQ", req, S.CANCELLED.value, actor, reason)
    frm, to = NEXT[action]
    if req.status != frm.value:
        raise HTTPException(409, "Requisition %s is %s; it cannot be %s now." % (req.number, req.status, PAST[action]))
    if action == "submit" and not requisition_lines(db, req):
        raise HTTPException(400, "A requisition needs at least one line.")
    log_status(db, "MRQ", req, to.value, actor)


# =============================================================================================== issue
def _fill_issue_lines(db, actor, issue, store, req, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    req_lines = {l.item_id: l for l in requisition_lines(db, req)} if req is not None else {}
    db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id).delete(synchronize_session=False)
    asked = {}
    returnable_any = False
    for n, ln in enumerate(lines_in, 1):
        item = _item(db, actor.client.id, ln.get("item_id"))
        uom, entered, base = _qty_in_base(db, item, ln, n)
        rl = None
        if req is not None:
            rl = req_lines.get(item.id)
            if rl is None:
                raise HTTPException(400, "Line %d: %s is not on requisition %s." % (n, item.item_name, req.number))
            asked[rl.id] = asked.get(rl.id, ZERO) + base
            room = rl.qty - _issued_on_req_line(db, rl.id, exclude_issue_id=issue.id)
            if asked[rl.id] > room:
                raise HTTPException(409, "Line %d: the requisition allows only %s more of %s." % (n, max(room, ZERO), item.item_name))
        returnable = _is_returnable(db, item.id)
        returnable_any = returnable_any or returnable
        chargeable = bool(ln.get("chargeable")) and issue.issue_type == "SUBCONTRACTOR"
        recovery = ZERO
        if chargeable and ln.get("recovery_rate") not in (None, ""):
            recovery = (dec(ln["recovery_rate"], "Recovery rate") * entered / base).quantize(_R4, rounding=ROUND_HALF_UP)
            if recovery < 0:
                raise HTTPException(400, "Line %d: the recovery rate cannot be negative." % n)
        db.add(DBStoreIssueLine(issue_id=issue.id, requisition_line_id=rl.id if rl else None, item_id=item.id, uom=uom, entered_qty=entered, qty=base,
                                returnable=returnable, chargeable=chargeable, recovery_rate=recovery, remarks=(ln.get("remarks") or "").strip()))
    db.flush()
    if returnable_any and not (issue.holder_type and (issue.holder_id or (issue.holder_name or "").strip())):
        raise HTTPException(400, "Returnable items need the person, gang or subcontractor who will hold them.")


def _holder(db, actor, issue, body):
    """Who holds the returnable items. A subcontractor issue is held by the subcontractor."""
    if issue.issue_type == "SUBCONTRACTOR":
        c = db.get(models.DBContractor, issue.subcontractor_id)
        issue.holder_type, issue.holder_id, issue.holder_name = "SUBCONTRACTOR", c.id, c.company_name or ""
        return
    htype = body.get("holder_type", issue.holder_type)
    if not htype:
        issue.holder_type, issue.holder_id, issue.holder_name = None, None, ""
        return
    if htype not in HOLDER_TYPES:
        raise HTTPException(400, "Holder must be one of %s." % ", ".join(HOLDER_TYPES))
    hid, name = body.get("holder_id", issue.holder_id), (body.get("holder_name", issue.holder_name) or "").strip()
    if htype == "EMPLOYEE":
        e = db.get(models.DBEmployee, hid) if hid else None
        if e is None or e.client_id != actor.client.id:
            raise HTTPException(404, "Employee not found")
        name = ("%s %s" % (e.first_name, e.last_name)).strip()
    elif htype == "SUBCONTRACTOR":
        c = db.get(models.DBContractor, hid) if hid else None
        if c is None or c.client_id != actor.client.id:
            raise HTTPException(404, "Subcontractor not found")
        name = c.company_name or ""
    elif not name:
        raise HTTPException(400, "Name the gang.")
    issue.holder_type, issue.holder_id, issue.holder_name = htype, hid or None, name


def _apply_issue_header(db, actor, issue, store, body, req):
    itype = body.get("issue_type", issue.issue_type) or "SITE"
    if itype not in ISSUE_TYPES:
        raise HTTPException(400, "Issue type must be SITE or SUBCONTRACTOR.")
    issue.issue_type = itype
    nothing_yet = not (issue.project_id or issue.work_order_id or issue.boq_item_id or issue.cost_head)
    carrier = req if (req is not None and nothing_yet and not any(body.get(k) is not None for k in ("project_id", "work_order_id", "boq_item_id", "cost_head"))) else issue
    issue.project_id, issue.work_order_id, issue.boq_item_id, issue.cost_head = _costing(db, actor, store, body, fallback=carrier if carrier.id else None)
    if not (issue.project_id or issue.cost_head):
        raise HTTPException(400, "Say where the material is charged: a project, or a cost head.")
    sub = body.get("subcontractor_id", issue.subcontractor_id)
    if itype == "SUBCONTRACTOR":
        c = db.get(models.DBContractor, sub) if sub else None
        if c is None or c.client_id != actor.client.id:
            raise HTTPException(400, "Choose the subcontractor the material is issued to.")
        issue.subcontractor_id = c.id
    else:
        issue.subcontractor_id = None
    if "expected_return_date" in body:
        issue.expected_return_date = to_date(body["expected_return_date"], "Expected return date") if body["expected_return_date"] else None
    if body.get("purpose") is not None:
        issue.purpose = body["purpose"].strip()
    _holder(db, actor, issue, body)


def _requisition_for(db, actor, store, requisition_id):
    if not requisition_id:
        return None
    req = db.get(DBStoreRequisition, requisition_id)
    if req is None or req.client_id != actor.client.id:
        raise HTTPException(404, "Requisition not found")
    if req.store_id != store.id:
        raise HTTPException(400, "That requisition is for a different store.")
    if req.status != S.APPROVED.value:
        raise HTTPException(409, "Requisition %s is %s; only an approved requisition can be issued against." % (req.number, req.status))
    return req


def create_issue(db, actor, store, body) -> DBStoreIssue:
    req = _requisition_for(db, actor, store, body.get("requisition_id"))
    d = _past(to_date(body.get("issue_date") or date.today(), "Issue date"), "Issue date")
    issue = DBStoreIssue(client_id=actor.client.id, store_id=store.id, issue_date=d, requisition_id=req.id if req else None, status=S.DRAFT.value,
                         created_by=actor.user_id, created_by_name=actor.name, number="", issue_type="SITE")
    db.add(issue)
    db.flush()
    _apply_issue_header(db, actor, issue, store, body, req)
    issue.number = next_doc_number(db, "ISSUE", store.id, on_date=d)
    _fill_issue_lines(db, actor, issue, store, req, body.get("lines") or [])
    log_status(db, "ISSUE", issue, S.DRAFT.value, actor, "Created" if req else "Created (direct issue)")
    return issue


def update_issue(db, actor, issue, store, body):
    if issue.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft issue can be edited.")
    req = db.get(DBStoreRequisition, issue.requisition_id) if issue.requisition_id else None
    if body.get("issue_date"):
        issue.issue_date = _past(to_date(body["issue_date"], "Issue date"), "Issue date")
    _apply_issue_header(db, actor, issue, store, body, req)
    if body.get("lines") is not None:
        _fill_issue_lines(db, actor, issue, store, req, body["lines"])
    elif any(l.returnable for l in issue_lines(db, issue)) and not (issue.holder_type and (issue.holder_id or issue.holder_name)):
        raise HTTPException(400, "Returnable items need the person, gang or subcontractor who will hold them.")


def issue_lines(db, issue):
    return db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id).order_by(DBStoreIssueLine.id).all()


def _live_return(db, issue_id):
    return db.query(DBStoreIssueReturn).filter(DBStoreIssueReturn.issue_id == issue_id, DBStoreIssueReturn.status != S.CANCELLED.value).first()


def _recheck_requisition(db, issue, lines):
    for l in lines:
        if l.requisition_line_id:
            rl = db.get(DBStoreRequisitionLine, l.requisition_line_id)
            if l.qty > rl.qty - _issued_on_req_line(db, rl.id, exclude_issue_id=issue.id):
                raise HTTPException(409, "More than the requisition allows would be issued.")


def _cancel(db, actor, doc_type, doc, reason, guard):
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is needed to cancel.")
    if doc.status == S.CANCELLED.value:
        raise HTTPException(409, "%s is already cancelled." % doc.number)
    if doc.status == S.POSTED.value:
        guard()
        from app.models.store_core import DBStoreStockLedger
        if db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.ref_doc_type == doc_type, DBStoreStockLedger.ref_doc_id == doc.id).first():
            reverse_document(db, ref_doc_type=doc_type, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
    doc.cancel_reason = reason
    log_status(db, doc_type, doc, S.CANCELLED.value, actor, reason)


def issue_action(db, actor, issue, action, reason=""):
    store = db.get(DBStore, issue.store_id)
    lines = issue_lines(db, issue)
    if action == "cancel":
        def guard():
            live = _live_return(db, issue.id)
            if live is not None:
                raise HTTPException(409, "Return %s was made against this issue; cancel it first." % live.number)
        return _cancel(db, actor, "ISSUE", issue, reason, guard)
    frm, to = NEXT[action]
    if issue.status != frm.value:
        raise HTTPException(409, "Issue %s is %s; it cannot be %s now." % (issue.number, issue.status, PAST[action]))
    if action == "submit":
        if not lines:
            raise HTTPException(400, "An issue needs at least one line.")
        _recheck_requisition(db, issue, lines)
    elif action == "post":
        _recheck_requisition(db, issue, lines)
        mtype = MovementType.SUBCON_ISSUE_OUT if issue.issue_type == "SUBCONTRACTOR" else MovementType.ISSUE_OUT
        for l in lines:
            e = post_movement(db, movement_type=mtype, store_id=store.id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=issue.issue_date,
                              project_id=issue.project_id, work_order_id=issue.work_order_id, boq_item_id=issue.boq_item_id, cost_head=issue.cost_head,
                              subcontractor_id=issue.subcontractor_id, ref_doc_type="ISSUE", ref_doc_id=issue.id, ref_line_id=l.id, user_id=actor.user_id,
                              remarks="Issue %s" % issue.number)
            l.rate, l.value = e.rate, e.value
            if l.chargeable and l.recovery_rate <= 0:
                l.recovery_rate = e.rate
        issue.posted_at = datetime.now()
    log_status(db, "ISSUE", issue, to.value, actor)


# =============================================================================================== return
def _gone_from_issue_line(db, issue_line_id, exclude_return_id=None, posted_only=False):
    """(returned, lost) quantities on an issue line from returns that are not cancelled (or only the posted ones)."""
    q = db.query(DBStoreIssueReturnLine).join(DBStoreIssueReturn, DBStoreIssueReturn.id == DBStoreIssueReturnLine.return_id).filter(
        DBStoreIssueReturnLine.issue_line_id == issue_line_id)
    q = q.filter(DBStoreIssueReturn.status == S.POSTED.value) if posted_only else q.filter(DBStoreIssueReturn.status != S.CANCELLED.value)
    if exclude_return_id:
        q = q.filter(DBStoreIssueReturn.id != exclude_return_id)
    rows = q.all()
    return sum((r.qty for r in rows), ZERO), sum((r.lost_qty for r in rows), ZERO)


def _fill_return_lines(db, actor, rtn, issue, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    own = {l.id: l for l in issue_lines(db, issue)}
    db.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id == rtn.id).delete(synchronize_session=False)
    asked = {}
    for n, ln in enumerate(lines_in, 1):
        il = own.get(ln.get("issue_line_id"))
        if il is None:
            raise HTTPException(400, "Line %d is not on issue %s." % (n, issue.number))
        qty, lost = q3(ln.get("qty") or 0), q3(ln.get("lost_qty") or 0)
        if qty < 0 or lost < 0 or qty + lost <= 0:
            raise HTTPException(400, "Line %d: give a quantity returned or lost." % n)
        asked[il.id] = asked.get(il.id, ZERO) + qty + lost
        back, gone = _gone_from_issue_line(db, il.id, exclude_return_id=rtn.id)
        room = il.qty - back - gone
        if asked[il.id] > room:
            raise HTTPException(409, "Line %d: only %s of that issue line is still out." % (n, max(room, ZERO)))
        if lost > 0 and not (ln.get("remarks") or "").strip():
            raise HTTPException(400, "Line %d: say why the quantity was lost." % n)
        db.add(DBStoreIssueReturnLine(return_id=rtn.id, issue_line_id=il.id, item_id=il.item_id, qty=qty, lost_qty=lost, rate=il.rate, remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def create_return(db, actor, store, body) -> DBStoreIssueReturn:
    issue = db.get(DBStoreIssue, body.get("issue_id")) if body.get("issue_id") else None
    if issue is None or issue.client_id != actor.client.id:
        raise HTTPException(404, "Issue not found")
    if issue.status != S.POSTED.value:
        raise HTTPException(409, "Only material from a posted issue can be returned.")
    if issue.store_id != store.id:
        raise HTTPException(400, "That issue was made from a different store.")
    d = _past(to_date(body.get("return_date") or date.today(), "Return date"), "Return date")
    if d < issue.issue_date:
        raise HTTPException(400, "A return cannot be dated before the issue.")
    rtn = DBStoreIssueReturn(client_id=actor.client.id, store_id=store.id, issue_id=issue.id, return_date=d, remarks=body.get("remarks") or "",
                             status=S.DRAFT.value, created_by=actor.user_id, created_by_name=actor.name, number="")
    db.add(rtn)
    db.flush()
    rtn.number = next_doc_number(db, "RTN", store.id, on_date=d)
    _fill_return_lines(db, actor, rtn, issue, body.get("lines") or [])
    log_status(db, "RTN", rtn, S.DRAFT.value, actor, "Created")
    return rtn


def update_return(db, actor, rtn, store, body):
    if rtn.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft return can be edited.")
    issue = db.get(DBStoreIssue, rtn.issue_id)
    if body.get("return_date"):
        d = _past(to_date(body["return_date"], "Return date"), "Return date")
        if d < issue.issue_date:
            raise HTTPException(400, "A return cannot be dated before the issue.")
        rtn.return_date = d
    if body.get("remarks") is not None:
        rtn.remarks = body["remarks"]
    if body.get("lines") is not None:
        _fill_return_lines(db, actor, rtn, issue, body["lines"])


def return_lines(db, rtn):
    return db.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id == rtn.id).order_by(DBStoreIssueReturnLine.id).all()


def return_action(db, actor, rtn, action, reason=""):
    store = db.get(DBStore, rtn.store_id)
    issue = db.get(DBStoreIssue, rtn.issue_id)
    lines = return_lines(db, rtn)
    if action == "cancel":
        def guard():
            closed = db.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.source_return_id == rtn.id, DBStoreWriteoffRequest.status == "CLOSED").first()
            if closed is not None:
                raise HTTPException(409, "The loss on this return has already been written off; that must be undone first.")
        _cancel(db, actor, "RTN", rtn, reason, guard)
        for w in db.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.source_return_id == rtn.id, DBStoreWriteoffRequest.status == "OPEN").all():
            w.status = "CANCELLED"
        return
    frm, to = NEXT[action]
    if rtn.status != frm.value:
        raise HTTPException(409, "Return %s is %s; it cannot be %s now." % (rtn.number, rtn.status, PAST[action]))
    if action == "submit" and not lines:
        raise HTTPException(400, "A return needs at least one line.")
    if action in ("submit", "post"):                                  # another return may have used up the quantity meanwhile
        for l in lines:
            il = db.get(DBStoreIssueLine, l.issue_line_id)
            back, gone = _gone_from_issue_line(db, il.id, exclude_return_id=rtn.id)
            if l.qty + l.lost_qty > il.qty - back - gone:
                raise HTTPException(409, "More than is still out would be returned.")
    if action == "post":
        mtype = MovementType.SUBCON_RETURN_IN if issue.issue_type == "SUBCONTRACTOR" else MovementType.ISSUE_RETURN_IN
        for l in lines:
            il = db.get(DBStoreIssueLine, l.issue_line_id)
            if l.qty > 0:
                e = post_movement(db, movement_type=mtype, store_id=store.id, item_id=l.item_id, qty=l.qty, rate=il.rate, txn_date=rtn.return_date,
                                  project_id=issue.project_id, work_order_id=issue.work_order_id, boq_item_id=issue.boq_item_id, cost_head=issue.cost_head,
                                  subcontractor_id=issue.subcontractor_id, ref_doc_type="RTN", ref_doc_id=rtn.id, ref_line_id=l.id, user_id=actor.user_id,
                                  remarks="Return %s against %s" % (rtn.number, issue.number))
                l.rate, l.value = e.rate, e.value
            if l.lost_qty > 0:
                db.add(DBStoreWriteoffRequest(client_id=rtn.client_id, store_id=store.id, item_id=l.item_id, qty=l.lost_qty, reason=l.remarks or "Not returned",
                                              source_issue_line_id=il.id, source_return_id=rtn.id, status="OPEN"))
        rtn.posted_at = datetime.now()
    log_status(db, "RTN", rtn, to.value, actor)


# =============================================================================================== cross-slice
def get_subcon_issues(db, subcontractor_id, upto_date) -> List[SubconIssueLine]:
    """Material issued to a subcontractor up to a date, with what came back and what is recoverable from their bill."""
    upto = to_date(upto_date, "Date") if upto_date else date.today()
    rows = db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id).filter(
        DBStoreIssue.subcontractor_id == subcontractor_id, DBStoreIssue.issue_type == "SUBCONTRACTOR", DBStoreIssue.status == S.POSTED.value,
        DBStoreIssue.issue_date <= upto).order_by(DBStoreIssue.issue_date, DBStoreIssueLine.id).all()
    out = []
    for l, i in rows:
        back, _lost = _gone_from_issue_line(db, l.id, posted_only=True)
        net = max(l.qty - back, ZERO)
        out.append(SubconIssueLine(issue_line_id=l.id, issue_date=i.issue_date, item_id=l.item_id, qty_issued=l.qty, qty_returned=back, chargeable=bool(l.chargeable),
                                   recovery_rate=l.recovery_rate or ZERO, recovery_value=(net * (l.recovery_rate or ZERO)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if l.chargeable else ZERO))
    return out


def get_outstanding_returnables(db, project_id=None, store_id=None) -> List[ReturnableOutstanding]:
    """Returnable items issued and not yet returned or written off, with who holds them and how overdue."""
    q = db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id).filter(
        DBStoreIssueLine.returnable.is_(True), DBStoreIssue.status == S.POSTED.value)
    if project_id:
        q = q.filter(DBStoreIssue.project_id == project_id)
    if store_id:
        q = q.filter(DBStoreIssue.store_id == store_id)
    out, today = [], date.today()
    for l, i in q.order_by(DBStoreIssue.issue_date, DBStoreIssueLine.id).all():
        back, lost = _gone_from_issue_line(db, l.id, posted_only=True)
        left = l.qty - back - lost
        if left > 0:
            late = (today - i.expected_return_date).days if i.expected_return_date and today > i.expected_return_date else 0
            out.append(ReturnableOutstanding(issue_line_id=l.id, item_id=l.item_id, holder_type=i.holder_type or "GANG", holder_id=i.holder_id or 0,
                                             qty_outstanding=left, expected_return_date=i.expected_return_date, overdue_days=late))
    return out


def _writeoff(w) -> WriteOffRequest:
    return WriteOffRequest(request_id=w.id, store_id=w.store_id, item_id=w.item_id, qty=w.qty, reason=w.reason or "", source_issue_line_id=w.source_issue_line_id, status=w.status)


def list_writeoff_requests(db, status="OPEN") -> List[WriteOffRequest]:
    q = db.query(DBStoreWriteoffRequest)
    if status:
        q = q.filter(DBStoreWriteoffRequest.status == status)
    return [_writeoff(w) for w in q.order_by(DBStoreWriteoffRequest.id).all()]


def close_writeoff_request(db, request_id, ref_doc_type, ref_doc_id, user_id) -> None:
    """Mark a request written off by the document that did it. Flushes; the caller commits."""
    w = db.get(DBStoreWriteoffRequest, request_id)
    if w is None:
        raise StoreError("Write-off request %s not found." % request_id)
    if w.status != "OPEN":
        raise StoreError("Write-off request %s is %s, not open." % (request_id, w.status))
    w.status, w.closed_by_doc_type, w.closed_by_doc_id, w.closed_by, w.closed_at = "CLOSED", ref_doc_type, ref_doc_id, user_id, datetime.now()
    db.flush()


# =============================================================================================== views
def _names(db, ids):
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(ids or [0])).all()}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(ids or [0])).all()}
    return items, sets


def _line_base(items, sets, i):
    return (sets[i].base_uom if i in sets else items[i].units_of_measure) or ""


def _where(db, d):
    wo = db.get(models.DBWorkOrder, d.work_order_id) if d.work_order_id else None
    job = db.get(models.DBJob, d.project_id) if d.project_id else None
    return {"project_id": d.project_id, "project_name": job.name if job else "", "work_order_id": d.work_order_id, "work_order_number": wo.number if wo else "",
            "boq_item_id": d.boq_item_id, "cost_head": d.cost_head}


def requisition_dict(db, req, with_lines=True):
    store = db.get(DBStore, req.store_id)
    lines = requisition_lines(db, req)
    out = {"id": req.id, "number": req.number, "store_id": req.store_id, "store_code": store.code, "store_name": store.name, "req_date": _iso(req.req_date),
           "required_by": _iso(req.required_by), "purpose": req.purpose or "", "status": req.status, "cancel_reason": req.cancel_reason or "",
           "created_by": req.created_by_name or "", "line_count": len(lines), **_where(db, req)}
    if with_lines:
        items, sets = _names(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
                         "base_uom": _line_base(items, sets, l.item_id), "uom": l.uom, "entered_qty": str(l.entered_qty), "qty": str(l.qty),
                         "issued_qty": str(_issued_on_req_line(db, l.id)), "remarks": l.remarks or ""} for l in lines]
        out["log"] = doc_log(db, "MRQ", req.id)
    return out


def issue_dict(db, issue, with_lines=True):
    store = db.get(DBStore, issue.store_id)
    req = db.get(DBStoreRequisition, issue.requisition_id) if issue.requisition_id else None
    sub = db.get(models.DBContractor, issue.subcontractor_id) if issue.subcontractor_id else None
    lines = issue_lines(db, issue)
    out = {"id": issue.id, "number": issue.number, "store_id": issue.store_id, "store_code": store.code, "store_name": store.name, "issue_date": _iso(issue.issue_date),
           "issue_type": issue.issue_type, "requisition_id": issue.requisition_id, "requisition_number": req.number if req else "", "direct": req is None,
           "subcontractor_id": issue.subcontractor_id, "subcontractor_name": (sub.company_name if sub else "") or "", "holder_type": issue.holder_type,
           "holder_id": issue.holder_id, "holder_name": issue.holder_name or "", "expected_return_date": _iso(issue.expected_return_date), "purpose": issue.purpose or "",
           "status": issue.status, "cancel_reason": issue.cancel_reason or "", "created_by": issue.created_by_name or "", "line_count": len(lines),
           "total_value": str(sum((l.value for l in lines), ZERO)), **_where(db, issue)}
    if with_lines:
        items, sets = _names(db, [l.item_id for l in lines])
        out["lines"] = []
        for l in lines:
            back, lost = _gone_from_issue_line(db, l.id, posted_only=True)
            out["lines"].append({"id": l.id, "requisition_line_id": l.requisition_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code,
                                 "item_name": items[l.item_id].item_name, "base_uom": _line_base(items, sets, l.item_id), "uom": l.uom, "entered_qty": str(l.entered_qty),
                                 "qty": str(l.qty), "rate": str(l.rate), "value": str(l.value), "returnable": bool(l.returnable), "chargeable": bool(l.chargeable),
                                 "recovery_rate": str(l.recovery_rate), "returned_qty": str(back), "lost_qty": str(lost),
                                 "outstanding_qty": str(max(l.qty - back - lost, ZERO)) if issue.status == S.POSTED.value else "0", "remarks": l.remarks or ""})
        out["log"] = doc_log(db, "ISSUE", issue.id)
    return out


def return_dict(db, rtn, with_lines=True):
    store = db.get(DBStore, rtn.store_id)
    issue = db.get(DBStoreIssue, rtn.issue_id)
    lines = return_lines(db, rtn)
    out = {"id": rtn.id, "number": rtn.number, "store_id": rtn.store_id, "store_code": store.code, "store_name": store.name, "issue_id": rtn.issue_id,
           "issue_number": issue.number, "return_date": _iso(rtn.return_date), "remarks": rtn.remarks or "", "status": rtn.status, "cancel_reason": rtn.cancel_reason or "",
           "created_by": rtn.created_by_name or "", "line_count": len(lines), "holder_name": issue.holder_name or "",
           "total_value": str(sum((l.value for l in lines), ZERO))}
    if with_lines:
        items, sets = _names(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "issue_line_id": l.issue_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
                         "base_uom": _line_base(items, sets, l.item_id), "qty": str(l.qty), "lost_qty": str(l.lost_qty), "rate": str(l.rate), "value": str(l.value),
                         "remarks": l.remarks or ""} for l in lines]
        out["log"] = doc_log(db, "RTN", rtn.id)
    return out


def writeoff_dict(db, w):
    item = db.get(models.DBItem, w.item_id)
    store = db.get(DBStore, w.store_id)
    return {"id": w.id, "store_id": w.store_id, "store_code": store.code, "item_id": w.item_id, "item_code": item.item_code, "item_name": item.item_name,
            "qty": str(w.qty), "reason": w.reason or "", "status": w.status, "closed_by_doc_type": w.closed_by_doc_type, "closed_by_doc_id": w.closed_by_doc_id,
            "created_at": _iso(w.created_at)}
