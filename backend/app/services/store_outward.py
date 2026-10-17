"""Store module - outward slice: material issued to a project or to a subcontractor, returns, returnables and write-off
requests. Owned by P3.

Two documents run DRAFT -> SUBMITTED -> APPROVED -> POSTED (or CANCELLED): the issue (ISSUE) and the return (ISSRET). Only POSTED
moves stock: an issue is valued at the average rate of the day; a return brings stock back at the rate it left at. A POSTED
document is immutable - cancel it (which reverses its movements) and make a new one. Quantities are in the item's base unit.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import (
    CostHead, DBStore, DBStoreItemSettings, DBStoreStockLedger, DocStatus, InvalidMovementError, MovementType,
)
from app.models.store_outward import (
    EMPLOYEE, GANG, ISSUE, ISSUE_RETURN, SITE, SUBCONTRACTOR, DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreIssueReturnLine,
    DBStoreOutwardLog, DBStoreWriteoffRequest,
)
from app.schemas.store_contracts import ReturnableOutstanding, SubconIssueLine, WriteOffRequest
from app.services.stock_ledger import convert_to_base, get_balance, post_movement, reverse_document
from app.services.store_numbering import next_doc_number

ZERO = Decimal("0")
_Q = Decimal("0.001")
LIVE = (DocStatus.SUBMITTED.value, DocStatus.APPROVED.value, DocStatus.POSTED.value)
RETURNABLE_CATEGORIES = ("RETURNABLE", "TOOL")
HOLDERS = (EMPLOYEE, SUBCONTRACTOR, GANG)


# --- small helpers --------------------------------------------------------------------------------------------------

def dec(value, what, *, allow_zero=True, high=Decimal("999999999999")) -> Decimal:
    try:
        d = Decimal(str(value if value is not None else "").strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite():
        raise HTTPException(400, "%s is not a number." % what)
    if d < 0 or (d == 0 and not allow_zero):
        raise HTTPException(400, "%s must be %s." % (what, "more than zero" if not allow_zero else "zero or more"))
    if d > high:
        raise HTTPException(400, "%s is too large." % what)
    return d


def day(raw, what, *, allow_future=False, required=True) -> Optional[date]:
    if raw in (None, ""):
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return None
    if isinstance(raw, date):
        out = raw
    else:
        try:
            out = datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % what) from None
    if not allow_future and out > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)
    if out.year < 2000 or out.year > 2100:
        raise HTTPException(400, "%s is not a sensible date." % what)
    return out


def text(value, what, limit, required=False) -> str:
    out = " ".join((value or "").split())
    if required and not out:
        raise HTTPException(400, "Give the %s." % what)
    if len(out) > limit:
        raise HTTPException(400, "Keep the %s to %d characters." % (what, limit))
    return out


def q3(x) -> Decimal:
    return Decimal(str(x)).quantize(_Q, rounding=ROUND_HALF_UP)


def s3(x) -> str:
    return format(q3(x if x is not None else 0), "f")


def item_of(db, client_id, item_id) -> models.DBItem:
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id or item.kind != "RM":
        raise HTTPException(400, "That item is not a stock item of this company.")
    return item


def to_base(db, item_id, qty: Decimal, uom: str) -> Decimal:
    try:
        base = convert_to_base(db, item_id, qty, uom)
    except InvalidMovementError as exc:
        raise HTTPException(400, str(exc)) from exc
    if base <= 0:
        raise HTTPException(400, "That quantity is too small to count: it comes to nothing in the base unit.")
    return base


def settings_of(db, item_id):
    return db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()


def base_uom_of(db, item) -> str:
    s = settings_of(db, item.id)
    return ((s.base_uom if s else item.units_of_measure) or "").strip()


def is_returnable(db, item_id) -> bool:
    s = settings_of(db, item_id)
    return bool(s and s.category in RETURNABLE_CATEGORIES)


def log(db, actor, doc_type, doc_id, action, before="", after="", note=""):
    db.add(DBStoreOutwardLog(client_id=actor.client.id, doc_type=doc_type, doc_id=doc_id, action=action, from_status=before, to_status=after,
                             user_id=actor.user_id, user_name=actor.name, note=(note or "")[:300]))


def numbered(db, doc_type, store_id, on_date) -> str:
    return next_doc_number(db, doc_type, store_id, on_date=on_date)


def store_of(db, client_id, store_id) -> DBStore:
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != client_id:
        raise HTTPException(400, "That store does not exist.")
    if not store.is_active:
        raise HTTPException(409, "Store %s is not in use." % store.code)
    return store


# --- issues --------------------------------------------------------------------------------------------------------------

def check_issue_header(db, client_id, body):
    """Validated header values for an issue. Returns (issue_type, holder_type, holder_id, holder_name)."""
    if not db.query(models.DBJob.id).filter(models.DBJob.id == body.project_id, models.DBJob.client_id == client_id).first():
        raise HTTPException(400, "Choose the project the material is for.")
    issue_type = (body.issue_type or SITE).strip().upper()
    if issue_type not in (SITE, SUBCONTRACTOR):
        raise HTTPException(400, "The issue is for SITE use or to a SUBCONTRACTOR.")
    if body.work_order_id and not db.query(models.DBWorkOrder.id).filter(models.DBWorkOrder.id == body.work_order_id, models.DBWorkOrder.client_id == client_id,
                                                                         models.DBWorkOrder.job_id == body.project_id).first():
        raise HTTPException(400, "That work order is not one of this project's.")
    htype, hid, hname = (body.holder_type or "").strip().upper(), body.holder_id, text(body.holder_name, "holder name", 80)
    if issue_type == SUBCONTRACTOR:
        con = db.query(models.DBContractor).filter(models.DBContractor.id == body.subcontractor_id, models.DBContractor.client_id == client_id).first() if body.subcontractor_id else None
        if con is None:
            raise HTTPException(400, "Choose the subcontractor the material is issued to.")
        htype, hid, hname = SUBCONTRACTOR, con.id, con.company_name or ""
    elif htype:
        if htype not in HOLDERS:
            raise HTTPException(400, "The holder is an EMPLOYEE, a SUBCONTRACTOR or a GANG.")
        if htype == EMPLOYEE:
            emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == hid, models.DBEmployee.client_id == client_id).first() if hid else None
            if emp is None:
                raise HTTPException(400, "Choose the employee who is taking it.")
            hname = ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()
        elif htype == SUBCONTRACTOR:
            con = db.query(models.DBContractor).filter(models.DBContractor.id == hid, models.DBContractor.client_id == client_id).first() if hid else None
            if con is None:
                raise HTTPException(400, "Choose the subcontractor who is taking it.")
            hname = con.company_name or ""
        else:
            if not hname:
                raise HTTPException(400, "Give the gang's name.")
            hid = 0
    else:
        htype, hid, hname = "", None, ""
    return issue_type, htype, hid, hname


def _boq_line(db, client_id, project_id, boq_item_id):
    row = (db.query(models.DBBoqLine).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
           .filter(models.DBBoqLine.id == boq_item_id, models.DBBoq.client_id == client_id, models.DBBoq.job_id == project_id).first())
    if row is None or row.kind not in ("item", "sub"):
        raise HTTPException(400, "That BOQ item is not one of this project's priced items.")
    return row


def build_issue_lines(db, client_id, body, issue_type, holder_type, on_date):
    if not body.lines:
        raise HTTPException(400, "Add at least one line.")
    out, seen = [], set()
    for n, r in enumerate(body.lines, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        qty = to_base(db, item.id, entry, uom)
        boq_id = r.boq_item_id or None
        head = (r.cost_head or "").strip().upper() or None
        if boq_id:
            _boq_line(db, client_id, body.project_id, boq_id)
        if head and head not in {c.value for c in CostHead}:
            raise HTTPException(400, "%s: the cost head must be one of: %s." % (label, ", ".join(c.value for c in CostHead)))
        if boq_id and head:
            raise HTTPException(400, "%s: charge it to a BOQ item or to a cost head, not both." % label)
        if issue_type == SITE and not boq_id and not head:
            raise HTTPException(400, "%s: say where the cost goes - a BOQ item or a cost head." % label)
        key = (item.id, boq_id, head)
        if key in seen:
            raise HTTPException(400, "%s: %s is on the issue twice for the same cost." % (label, item.item_name))
        seen.add(key)
        chargeable = bool(r.chargeable)
        rate = dec(r.recovery_rate or "0", label + " recovery rate")
        if chargeable and issue_type != SUBCONTRACTOR:
            raise HTTPException(400, "%s: only material issued to a subcontractor is recovered from their bill." % label)
        if chargeable and rate <= 0:
            raise HTTPException(400, "%s: give the rate to recover from the subcontractor." % label)
        due = day(r.expected_return_date, "Expected return date", allow_future=True, required=False)
        returnable = is_returnable(db, item.id)
        if due is not None and not returnable:
            raise HTTPException(400, "%s: only returnable items and tools have a return date." % label)
        if due is not None and due < on_date:
            raise HTTPException(400, "%s: the return date is before the issue date." % label)
        if returnable and not holder_type:
            raise HTTPException(400, "%s: %s is returnable, so say who is taking it." % (label, item.item_name))
        out.append({"item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": qty, "boq_item_id": boq_id, "cost_head": head, "chargeable": 1 if chargeable else 0,
                    "recovery_rate": q3(rate), "due": due, "remarks": text(r.remarks, "remarks", 200), "label": label})
    return out


def write_issue_lines(db, issue, lines):
    db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBStoreIssueLine(issue_id=issue.id, line_no=n, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], boq_item_id=l["boq_item_id"],
                                cost_head=l["cost_head"], chargeable=l["chargeable"], recovery_rate=l["recovery_rate"], expected_return_date=l["due"], remarks=l["remarks"]))
    db.flush()


def issue_lines(db, issue):
    return db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id).order_by(DBStoreIssueLine.line_no, DBStoreIssueLine.id).all()


def check_stock(db, store_id, lines):
    """Everything asked for must be on hand now (posting checks again, in the same transaction as the movement)."""
    want = {}
    for l in lines:
        item_id = l.item_id if hasattr(l, "item_id") else l["item"].id
        want[item_id] = want.get(item_id, ZERO) + Decimal(str(l.qty if hasattr(l, "qty") else l["qty"]))
    for item_id, qty in want.items():
        have = get_balance(db, store_id, item_id).qty
        if qty > have:
            item = db.get(models.DBItem, item_id)
            raise HTTPException(409, "Only %s %s of %s on hand in this store; %s was asked for." % (s3(have), base_uom_of(db, item), item.item_name, s3(qty)))


def issue_check_submit(db, actor, issue):
    check_stock(db, issue.store_id, issue_lines(db, issue))


def issue_post(db, actor, issue):
    mtype = MovementType.SUBCON_ISSUE_OUT if issue.issue_type == SUBCONTRACTOR else MovementType.ISSUE_OUT
    for l in issue_lines(db, issue):
        post_movement(db, movement_type=mtype, store_id=issue.store_id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=issue.issue_date, project_id=issue.project_id,
                      work_order_id=issue.work_order_id, boq_item_id=l.boq_item_id, cost_head=l.cost_head, subcontractor_id=issue.subcontractor_id, ref_doc_type=ISSUE,
                      ref_doc_id=issue.id, ref_line_id=l.id, user_id=actor.user_id, remarks=issue.number + ((" - " + issue.purpose) if issue.purpose else ""))


def issue_check_cancel(db, issue):
    live = db.query(DBStoreIssueReturn.number).filter(DBStoreIssueReturn.issue_id == issue.id, DBStoreIssueReturn.status.in_(LIVE)).first()
    if live:
        raise HTTPException(409, "Return %s was made against this issue. Cancel the return first." % live[0])


# --- returns -----------------------------------------------------------------------------------------------------------------

def _taken_back(db, issue_line_ids, statuses, exclude_return=None):
    """{issue_line_id: (returned, lost)} on returns in the given statuses."""
    if not issue_line_ids:
        return {}
    q = (db.query(DBStoreIssueReturnLine.issue_line_id, func.sum(DBStoreIssueReturnLine.qty_returned), func.sum(DBStoreIssueReturnLine.qty_lost))
         .join(DBStoreIssueReturn, DBStoreIssueReturn.id == DBStoreIssueReturnLine.return_id)
         .filter(DBStoreIssueReturnLine.issue_line_id.in_(list(issue_line_ids)), DBStoreIssueReturn.status.in_(statuses)))
    if exclude_return:
        q = q.filter(DBStoreIssueReturn.id != exclude_return)
    return {i: (Decimal(str(r or 0)), Decimal(str(x or 0))) for i, r, x in q.group_by(DBStoreIssueReturnLine.issue_line_id).all()}


def outstanding_on(db, issue, exclude_return=None):
    """{issue_line_id: quantity still out on the line}, counting every live return."""
    lines = issue_lines(db, issue)
    taken = _taken_back(db, [l.id for l in lines], LIVE, exclude_return)
    return {l.id: Decimal(str(l.qty)) - sum(taken.get(l.id, (ZERO, ZERO))) for l in lines}


def build_return_lines(db, client_id, issue, rows, return_id=None):
    if issue.status != DocStatus.POSTED.value:
        raise HTTPException(409, "Only a posted issue can have material returned against it.")
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    lines = {l.id: l for l in issue_lines(db, issue)}
    room = outstanding_on(db, issue, exclude_return=return_id)
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        il = lines.get(r.issue_line_id)
        if il is None:
            raise HTTPException(400, "%s is not a line of issue %s." % (label, issue.number))
        if il.id in seen:
            raise HTTPException(400, "%s: that issue line is on the return twice." % label)
        seen.add(il.id)
        item = db.get(models.DBItem, il.item_id)
        uom = text(r.uom, "unit", 20) or il.entry_uom or base_uom_of(db, item)
        back_e, lost_e = dec(r.qty_returned or "0", label + " returned quantity"), dec(r.qty_lost or "0", label + " lost quantity")
        if back_e <= 0 and lost_e <= 0:
            raise HTTPException(400, "%s: give how much came back, or how much was lost." % label)
        back = to_base(db, item.id, back_e, uom) if back_e > 0 else ZERO
        lost = to_base(db, item.id, lost_e, uom) if lost_e > 0 else ZERO
        if lost > 0 and not is_returnable(db, item.id):
            raise HTTPException(400, "%s: %s is a consumable, which is used up rather than written off." % (label, item.item_name))
        reason = text(r.reason, "reason", 200)
        if lost > 0 and not reason:
            raise HTTPException(400, "%s: say what happened to what was lost or damaged." % label)
        if back + lost > room.get(il.id, ZERO):
            raise HTTPException(409, "%s: only %s %s of %s is still out%s." % (label, s3(max(ZERO, room.get(il.id, ZERO))), base_uom_of(db, item), item.item_name,
                                                                              ", the rest is already on a return" if room.get(il.id, ZERO) < Decimal(str(il.qty)) else ""))
        out.append({"il": il, "item": item, "entry_uom": uom, "back": back, "lost": lost, "reason": reason})
    return out


def write_return_lines(db, ret, lines):
    db.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id == ret.id).delete(synchronize_session=False)
    for l in lines:
        db.add(DBStoreIssueReturnLine(return_id=ret.id, issue_line_id=l["il"].id, item_id=l["item"].id, entry_uom=l["entry_uom"], qty_returned=l["back"], qty_lost=l["lost"], reason=l["reason"]))
    db.flush()


def return_lines(db, ret):
    return db.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id == ret.id).order_by(DBStoreIssueReturnLine.id).all()


def return_check_submit(db, actor, ret):
    issue = db.get(DBStoreIssue, ret.issue_id)

    class _R:                                         # the draft's own check, again, on what is stored
        def __init__(self, l):                        # the stored quantities are in the base unit, so say so
            self.issue_line_id, self.reason = l.issue_line_id, l.reason
            self.uom = base_uom_of(db, db.get(models.DBItem, l.item_id))
            self.qty_returned, self.qty_lost = str(l.qty_returned), str(l.qty_lost)
    build_return_lines(db, ret.client_id, issue, [_R(l) for l in return_lines(db, ret)], return_id=ret.id)


def _issue_rate(db, issue, line):
    """What a line left at: the rate of its posted (not reversed) ledger entry."""
    row = (db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == ISSUE, DBStoreStockLedger.ref_doc_id == issue.id, DBStoreStockLedger.ref_line_id == line.id,
                                               DBStoreStockLedger.reversal_of_id.is_(None)).order_by(DBStoreStockLedger.id).first())
    if row is None:
        raise HTTPException(409, "Issue %s has no stock entry for that line, so it cannot be returned." % issue.number)
    return Decimal(str(row.rate))


def return_post(db, actor, ret):
    return_check_submit(db, actor, ret)
    issue = db.get(DBStoreIssue, ret.issue_id)
    lines = {l.id: l for l in issue_lines(db, issue)}
    mtype = MovementType.SUBCON_RETURN_IN if issue.issue_type == SUBCONTRACTOR else MovementType.ISSUE_RETURN_IN
    for rl in return_lines(db, ret):
        il = lines[rl.issue_line_id]
        if Decimal(str(rl.qty_returned)) > 0:
            post_movement(db, movement_type=mtype, store_id=ret.store_id, item_id=rl.item_id, qty=rl.qty_returned, rate=_issue_rate(db, issue, il), txn_date=ret.return_date,
                          project_id=issue.project_id, work_order_id=issue.work_order_id, boq_item_id=il.boq_item_id, cost_head=il.cost_head, subcontractor_id=issue.subcontractor_id,
                          ref_doc_type=ISSUE_RETURN, ref_doc_id=ret.id, ref_line_id=rl.id, user_id=actor.user_id, remarks="%s - against %s" % (ret.number, issue.number))
        if Decimal(str(rl.qty_lost)) > 0:
            db.add(DBStoreWriteoffRequest(client_id=ret.client_id, store_id=ret.store_id, item_id=rl.item_id, qty=rl.qty_lost, reason=rl.reason or "Lost or damaged",
                                          source_issue_line_id=il.id, source_return_id=ret.id, status="OPEN"))
    db.flush()


def return_check_cancel(db, ret):
    closed = db.query(DBStoreWriteoffRequest.id).filter(DBStoreWriteoffRequest.source_return_id == ret.id, DBStoreWriteoffRequest.status == "CLOSED").first()
    if closed:
        raise HTTPException(409, "A write-off raised by this return has already been dealt with, so the return cannot be cancelled.")


# --- the lifecycle ---------------------------------------------------------------------------------------------------------------

STEPS = {"submit": (DocStatus.DRAFT, DocStatus.SUBMITTED), "approve": (DocStatus.SUBMITTED, DocStatus.APPROVED), "post": (DocStatus.APPROVED, DocStatus.POSTED)}


class Kind:
    def __init__(self, key, ref, label, header, line, fk, date_attr, count_lines, post, check_submit=None, check_cancel=None, reverses=None):
        self.key, self.ref, self.label, self.header, self.line, self.fk, self.date_attr = key, ref, label, header, line, fk, date_attr
        self.count_lines, self.post, self.check_submit, self.check_cancel, self.reverses = count_lines, post, check_submit, check_cancel, reverses


def _return_moved_stock(db, ret):
    return any(Decimal(str(l.qty_returned)) > 0 for l in return_lines(db, ret))


KINDS = {
    "issue": Kind("issue", ISSUE, "Issue", DBStoreIssue, DBStoreIssueLine, "issue_id", "issue_date", lambda db, d: len(issue_lines(db, d)), issue_post, issue_check_submit, issue_check_cancel),
    "returns": Kind("returns", ISSUE_RETURN, "Return", DBStoreIssueReturn, DBStoreIssueReturnLine, "return_id", "return_date", lambda db, d: len(return_lines(db, d)), return_post,
                    return_check_submit, return_check_cancel, _return_moved_stock),
}


def advance(db, actor, kind, doc, action, reason=""):
    """Move a document one step: submit, approve, post, or cancel (with a reason). Posting and cancelling a posted document move
    stock: the caller wraps this in store_errors() and commits once, and rolls back on any error."""
    now = doc.status
    if action == "cancel":
        reason = text(reason, "reason", 200)
        if len(reason) < 3:
            raise HTTPException(400, "Say why it is being cancelled.")
        if now == DocStatus.CANCELLED.value:
            raise HTTPException(409, "It is already cancelled.")
        if kind.check_cancel:
            kind.check_cancel(db, doc)
        if now == DocStatus.POSTED.value:
            if kind.reverses is None or kind.reverses(db, doc):
                reverse_document(db, ref_doc_type=kind.ref, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
            if kind.key == "returns":
                for w in db.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.source_return_id == doc.id, DBStoreWriteoffRequest.status == "OPEN").all():
                    w.status = "WITHDRAWN"
        doc.status, doc.cancel_reason = DocStatus.CANCELLED.value, reason
        log(db, actor, kind.ref, doc.id, "cancel", now, doc.status, reason)
        return doc
    if action not in STEPS:
        raise HTTPException(404, "There is no such action.")
    need, to = STEPS[action]
    if now != need.value:
        raise HTTPException(409, "It is %s, so it cannot be %s now." % (now.lower(), {"submit": "submitted", "approve": "approved", "post": "posted"}[action]))
    if action == "submit":
        if not kind.count_lines(db, doc):
            raise HTTPException(400, "Add at least one line before submitting.")
        if kind.check_submit:
            kind.check_submit(db, actor, doc)
    if action == "post":
        kind.post(db, actor, doc)
        doc.posted_at = datetime.now()
    doc.status = to.value
    log(db, actor, kind.ref, doc.id, action, now, doc.status)
    return doc


# --- what other slices ask for ---------------------------------------------------------------------------------------------------

def _as_day(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def get_subcon_issues(db, subcontractor_id, upto_date) -> List[SubconIssueLine]:
    """Material issued to a subcontractor up to a date, for recovery on their RA bill.

    Posted issues only. qty_returned is what came back; what was lost or never returned is still the subcontractor's, so the
    recovery value is (issued - returned) x the recovery rate for lines marked chargeable, and nothing for the rest."""
    upto = _as_day(upto_date)
    rows = (db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
            .filter(DBStoreIssue.subcontractor_id == subcontractor_id, DBStoreIssue.issue_type == SUBCONTRACTOR, DBStoreIssue.status == DocStatus.POSTED.value,
                    DBStoreIssue.issue_date <= upto).order_by(DBStoreIssue.issue_date, DBStoreIssueLine.id).all())
    back = _taken_back(db, [l.id for l, _i in rows], (DocStatus.POSTED.value,))
    out = []
    for l, issue in rows:
        returned = back.get(l.id, (ZERO, ZERO))[0]
        left = max(ZERO, Decimal(str(l.qty)) - returned)
        rate = Decimal(str(l.recovery_rate or 0))
        out.append(SubconIssueLine(issue_line_id=l.id, issue_date=issue.issue_date, item_id=l.item_id, qty_issued=q3(l.qty), qty_returned=q3(returned), chargeable=bool(l.chargeable),
                                   recovery_rate=q3(rate), recovery_value=(left * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if l.chargeable else ZERO))
    return out


def get_outstanding_returnables(db, project_id=None, store_id=None) -> List[ReturnableOutstanding]:
    """Returnable items and tools issued and not yet back: issued less what has been returned or reported lost, per issue line."""
    q = (db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
         .join(DBStoreItemSettings, DBStoreItemSettings.item_id == DBStoreIssueLine.item_id)
         .filter(DBStoreIssue.status == DocStatus.POSTED.value, DBStoreItemSettings.category.in_(RETURNABLE_CATEGORIES)))
    if project_id:
        q = q.filter(DBStoreIssue.project_id == project_id)
    if store_id:
        q = q.filter(DBStoreIssue.store_id == store_id)
    rows = q.order_by(DBStoreIssue.issue_date, DBStoreIssueLine.id).all()
    taken = _taken_back(db, [l.id for l, _i in rows], (DocStatus.POSTED.value,))
    today = date.today()
    out = []
    for l, issue in rows:
        left = Decimal(str(l.qty)) - sum(taken.get(l.id, (ZERO, ZERO)))
        if left <= 0:
            continue
        due = l.expected_return_date
        out.append(ReturnableOutstanding(issue_line_id=l.id, item_id=l.item_id, holder_type=issue.holder_type or "", holder_id=issue.holder_id or 0, qty_outstanding=q3(left),
                                         expected_return_date=due, overdue_days=max(0, (today - due).days) if due else 0))
    return out


def list_writeoff_requests(db, status="OPEN") -> List[WriteOffRequest]:
    """Requests to write off a returnable that did not come back (every company's: filter by store before showing them)."""
    q = db.query(DBStoreWriteoffRequest)
    if status:
        q = q.filter(DBStoreWriteoffRequest.status == status)
    return [WriteOffRequest(request_id=w.id, store_id=w.store_id, item_id=w.item_id, qty=q3(w.qty), reason=w.reason or "", source_issue_line_id=w.source_issue_line_id, status=w.status)
            for w in q.order_by(DBStoreWriteoffRequest.id).all()]


def close_writeoff_request(db, request_id, ref_doc_type, ref_doc_id, user_id) -> None:
    """Mark a write-off request dealt with by the document that did it (a bill recovery, an adjustment, a scrap). Flushes; never commits."""
    w = db.get(DBStoreWriteoffRequest, request_id)
    if w is None:
        raise HTTPException(404, "Write-off request not found")
    if w.status != "OPEN":
        raise HTTPException(409, "That write-off request is already %s." % w.status.lower())
    w.status, w.closed_at, w.closed_ref_type, w.closed_ref_id, w.closed_by = "CLOSED", datetime.now(), ref_doc_type, ref_doc_id, user_id
    db.flush()
