"""Store module - outward slice: material issued to a project or to a subcontractor, returns, returnables and write-off
requests. Owned by P3.

Two documents run DRAFT -> SUBMITTED -> APPROVED -> POSTED (or CANCELLED): the issue (ISSUE) and the return (ISSRET). Only POSTED
moves stock: an issue is valued at the average rate of the day; a return brings stock back at the rate it left at. A POSTED
document is immutable - cancel it (which reverses its movements) and make a new one. Quantities are in the item's base unit.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import (
    CostHead, DBStore, DBStoreBin, DBStoreItemSettings, DBStoreStockLedger, DocStatus, InvalidMovementError, MovementType,
)
from app.models.store_outward import (
    AVERAGE_COST, CONTRACT_RATE, EMPLOYEE, FOREMAN, GANG, GATE_PASS, INDENT, ISSUE, ISSUE_RETURN, PERSON, SITE, SUBCONTRACTOR, DBStoreGatePass, DBStoreGatePassLine, DBStoreIndent,
    DBStoreIndentLine, DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreIssueReturnLine, DBStoreOutwardLog, DBStoreOutwardSetting, DBStoreRecovery, DBStoreReturnableClosure,
    DBStoreWriteoffRequest,
)
from app.schemas.store_contracts import ReturnableOutstanding, SubconIssueLine, WriteOffRequest
from app.core.store_auth import check_not_own
from app.services.stock_ledger import check_date, convert_to_base, entry_lots, get_balance, lot_label, post_movement, reverse_document
from app.models.store_extras import DBStoreIndentLineNote
from app.services import store_reservations
from app.services.store_batches import batches_on_hand, find_lot, usable_qty
from app.services.store_numbering import next_doc_number

from app.services.store_common import (  # noqa: F401  (the routers and documents call svc.dec, svc.day and the rest)
    _Q, _R, _V, dec, day, q3, r4, s2, s3, s4, text, v2,
)

ZERO = Decimal("0")
LIVE = (DocStatus.SUBMITTED.value, DocStatus.APPROVED.value, DocStatus.POSTED.value)
RETURNABLE_CATEGORIES = ("RETURNABLE", "TOOL")
HOLDERS = (EMPLOYEE, SUBCONTRACTOR, GANG)


# --- small helpers --------------------------------------------------------------------------------------------------

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

CLOSED_ORDERS = ("Closed", "Cancelled", "Rejected")
MAX_PCT = Decimal("100")


def outward_settings(db, client_id):
    """The company's outward defaults (created on first use): handling percentage on subcontractor recoveries and the usual recovery basis."""
    row = db.query(DBStoreOutwardSetting).filter(DBStoreOutwardSetting.client_id == client_id).first()
    if row is None:
        row = DBStoreOutwardSetting(client_id=client_id, subcon_handling_pct=ZERO, default_recovery_basis=AVERAGE_COST)
        db.add(row)
        db.flush()
    return row


def pct(value, what) -> Decimal:
    d = dec(value if str(value or "").strip() else "0", what, high=MAX_PCT)
    return d.quantize(Decimal("0.001"))


def check_issue_header(db, client_id, body):
    """Validated header values for an issue: {issue_type, received_type, received_employee_id, received_name, holder_type, holder_id, holder_name,
    order_id, indent}. Raises 400/409 in words."""
    project = db.query(models.DBJob).filter(models.DBJob.id == body.project_id, models.DBJob.client_id == client_id).first()
    if project is None:
        raise HTTPException(400, "Choose the project the material is for.")
    issue_type = (body.issue_type or SITE).strip().upper()
    if issue_type not in (SITE, SUBCONTRACTOR):
        raise HTTPException(400, "The issue is for SITE use or to a SUBCONTRACTOR.")
    wo = None
    if body.work_order_id:
        wo = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == body.work_order_id, models.DBWorkOrder.client_id == client_id, models.DBWorkOrder.job_id == body.project_id).first()
        if wo is None:
            raise HTTPException(400, "That work order is not one of this project's.")
    indent = None
    if getattr(body, "indent_id", None):
        indent = db.query(DBStoreIndent).filter(DBStoreIndent.id == body.indent_id, DBStoreIndent.client_id == client_id).first()
        if indent is None:
            raise HTTPException(400, "That indent does not exist.")
        if indent.status not in ("OPEN", "PARTIAL"):
            raise HTTPException(409, "Indent %s is %s, so nothing can be issued against it." % (indent.number, indent.status.lower()))
        if indent.project_id != body.project_id:
            raise HTTPException(400, "Indent %s is for another project." % indent.number)
        if indent.store_id != body.store_id:
            raise HTTPException(400, "Indent %s is for another store." % indent.number)
        if wo is None and indent.work_order_id:
            wo = db.get(models.DBWorkOrder, indent.work_order_id)
    if wo is not None and (wo.status or "") in CLOSED_ORDERS:
        raise HTTPException(409, "Work order %s is %s, so nothing can be issued against it." % (wo.number, (wo.status or "").lower()))
    out = {"issue_type": issue_type, "indent": indent, "work_order_id": wo.id if wo else None, "order_id": None, "holder_type": "", "holder_id": None, "holder_name": ""}
    rtype, rname = (body.received_by_type or "").strip().upper(), text(body.received_by_name, "name of who received it", 80)
    rid = body.received_by_employee_id or None
    if rtype not in (PERSON, GANG, FOREMAN):
        raise HTTPException(400, "Say who received the material: a PERSON, a GANG or a FOREMAN.")
    if rid:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == rid, models.DBEmployee.client_id == client_id).first()
        if emp is None:
            raise HTTPException(400, "That employee does not exist.")
        rname = ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()
    if not rname:
        raise HTTPException(400, "Give the name of who received the material.")
    out.update({"received_type": rtype, "received_employee_id": rid, "received_name": rname})
    if issue_type == SUBCONTRACTOR:
        con = db.query(models.DBContractor).filter(models.DBContractor.id == body.subcontractor_id, models.DBContractor.client_id == client_id).first() if body.subcontractor_id else None
        if con is None:
            raise HTTPException(400, "Choose the subcontractor the material is issued to.")
        order = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == body.subcontract_order_id, models.DBSubcontractOrder.client_id == client_id).first() if body.subcontract_order_id else None
        if order is None:
            raise HTTPException(400, "Choose the subcontract work order the material is issued under.")
        if order.contractor_id != con.id or (order.job_id and order.job_id != body.project_id):
            raise HTTPException(400, "Work order %s is not %s's order on this project." % (order.wo_number or order.id, con.company_name or "this subcontractor"))
        if (order.status or "").upper() in ("CANCELLED", "TERMINATED", "CLOSED"):
            raise HTTPException(409, "Subcontract work order %s is %s." % (order.wo_number or order.id, (order.status or "").lower()))
        out.update({"holder_type": SUBCONTRACTOR, "holder_id": con.id, "holder_name": con.company_name or "", "order_id": order.id, "subcontractor_id": con.id})
    else:
        out["subcontractor_id"] = None
        if rid:
            out.update({"holder_type": EMPLOYEE, "holder_id": rid, "holder_name": rname})
        else:
            out.update({"holder_type": GANG, "holder_id": 0, "holder_name": rname})
    return out


def _boq_line(db, client_id, project_id, boq_item_id):
    row = (db.query(models.DBBoqLine).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
           .filter(models.DBBoqLine.id == boq_item_id, models.DBBoq.client_id == client_id, models.DBBoq.job_id == project_id).first())
    if row is None or row.kind not in ("item", "sub"):
        raise HTTPException(400, "That BOQ item is not one of this project's priced items.")
    return row


def indent_pending(db, indent, exclude_issue=None):
    """{indent_line_id: quantity still to be issued}: what was approved less what posted and in-flight issues already take."""
    lines = indent_lines(db, indent)
    ids = [l.id for l in lines]
    taken = {}
    if ids:
        q = (db.query(DBStoreIssueLine.indent_line_id, func.sum(DBStoreIssueLine.qty)).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
             .filter(DBStoreIssueLine.indent_line_id.in_(ids), DBStoreIssue.status.in_(LIVE)))
        if exclude_issue:
            q = q.filter(DBStoreIssue.id != exclude_issue)
        taken = {i: Decimal(str(n or 0)) for i, n in q.group_by(DBStoreIssueLine.indent_line_id).all()}
    return {l.id: Decimal(str(l.approved_qty if l.approved_qty is not None else 0)) - taken.get(l.id, ZERO) for l in lines}


def build_issue_lines(db, client_id, body, head, on_date, issue_id=None):
    if not body.lines:
        raise HTTPException(400, "Add at least one line.")
    issue_type, indent = head["issue_type"], head["indent"]
    cfg = outward_settings(db, client_id)
    pending = indent_pending(db, indent, exclude_issue=issue_id) if indent else {}
    ilines = {l.id: l for l in indent_lines(db, indent)} if indent else {}
    out, seen, asked = [], set(), {}
    for n, r in enumerate(body.lines, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        qty = to_base(db, item.id, entry, uom)
        il_id = getattr(r, "indent_line_id", None) or None
        if indent is not None:
            il = ilines.get(il_id)
            if il is None:
                raise HTTPException(400, "%s: choose the line of indent %s it fills." % (label, indent.number))
            if il.item_id != item.id:
                raise HTTPException(400, "%s: indent %s asked for a different item on that line." % (label, indent.number))
            asked[il.id] = asked.get(il.id, ZERO) + qty
            if asked[il.id] > pending.get(il.id, ZERO):
                raise HTTPException(409, "%s: only %s %s of %s is still to be issued on indent %s." % (label, s3(max(ZERO, pending.get(il.id, ZERO))), base_uom_of(db, item), item.item_name, indent.number))
        elif il_id:
            raise HTTPException(400, "%s: an indent line was named but no indent was chosen." % label)
        boq_id = r.boq_item_id or (indent.boq_item_id if indent is not None and not r.cost_head else None) or None
        head_name = (r.cost_head or "").strip().upper() or None
        if boq_id:
            _boq_line(db, client_id, body.project_id, boq_id)
        if head_name and head_name not in {c.value for c in CostHead}:
            raise HTTPException(400, "%s: the cost head must be one of: %s." % (label, ", ".join(c.value for c in CostHead)))
        if boq_id and head_name:
            raise HTTPException(400, "%s: charge it to a BOQ item or to a cost head, not both." % label)
        if issue_type == SITE and not boq_id and not head_name:
            raise HTTPException(400, "%s: say where the cost goes - a BOQ item or a cost head." % label)
        key = (item.id, boq_id, head_name, il_id)
        if key in seen:
            raise HTTPException(400, "%s: %s is on the issue twice for the same cost." % (label, item.item_name))
        seen.add(key)
        chargeable = bool(r.chargeable)
        basis, handling, rate = "", ZERO, ZERO
        if chargeable and issue_type != SUBCONTRACTOR:
            raise HTTPException(400, "%s: only material issued to a subcontractor is recovered from their bill." % label)
        if chargeable:
            basis = (r.recovery_basis or cfg.default_recovery_basis or AVERAGE_COST).strip().upper()
            if basis not in (CONTRACT_RATE, AVERAGE_COST):
                raise HTTPException(400, "%s: the recovery rate is the CONTRACT_RATE or the AVERAGE_COST." % label)
            handling = pct(r.handling_pct if str(r.handling_pct or "").strip() else cfg.subcon_handling_pct, label + " handling percentage")
            if basis == CONTRACT_RATE:
                rate = dec(r.recovery_rate or "0", label + " contract rate", allow_zero=False)
        due = day(r.expected_return_date, "Expected return date", allow_future=True, required=False)
        returnable = is_returnable(db, item.id)
        if due is not None and not returnable:
            raise HTTPException(400, "%s: only returnable items and tools have a return date." % label)
        if due is not None and due < on_date:
            raise HTTPException(400, "%s: the return date is before the issue date." % label)
        batch = text(getattr(r, "batch_no", ""), "batch", 40)
        _check_batch(db, body.store_id, item, batch, qty, on_date, label)
        out.append({"item": item, "batch_no": batch, "entry_uom": uom, "entry_qty": q3(entry), "qty": qty, "boq_item_id": boq_id, "cost_head": head_name, "chargeable": 1 if chargeable else 0,
                    "recovery_rate": q3(rate), "recovery_basis": basis, "handling_pct": handling, "due": due, "remarks": text(r.remarks, "remarks", 200), "label": label, "indent_line_id": il_id})
    return out


def _check_batch(db, store_id, item, batch, qty, on_date, label):
    """An issue takes from a batch the store holds enough of, and not one past its expiry: expired cement or admixture is not
    used on site. With no batch named it takes the earliest expiry first, passing over expired stock - so there must be enough
    that has not expired."""
    if batch:
        lot = next((b for b in batches_on_hand(db, store_id, item.id, on_date) if b["batch_no"] == batch), None)
        if lot is None:
            raise HTTPException(409, "%s: the store holds no batch %s of %s." % (label, batch, item.item_name))
        if lot["state"] == "EXPIRED":
            raise HTTPException(409, "%s: batch %s of %s expired on %s and is not issued. Write it off under Control, or choose another batch." % (
                label, batch, item.item_name, lot["expiry_date"]))
        if qty > Decimal(lot["qty"]):
            raise HTTPException(409, "%s: only %s %s of batch %s is on hand; %s was asked for. Split the line over another batch." % (
                label, lot["qty"], base_uom_of(db, item), batch, s3(qty)))
        return
    held, fit = get_balance(db, store_id, item.id).qty, usable_qty(db, store_id, item.id, on_date)
    if fit < held and qty > fit:
        raise HTTPException(409, "%s: only %s %s of %s has not expired (%s %s has). Write the expired stock off under Control." % (
            label, s3(fit), base_uom_of(db, item), item.item_name, s3(held - fit), base_uom_of(db, item)))


def write_issue_lines(db, issue, lines):
    db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBStoreIssueLine(issue_id=issue.id, line_no=n, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], boq_item_id=l["boq_item_id"],
                                cost_head=l["cost_head"], chargeable=l["chargeable"], recovery_rate=l["recovery_rate"], recovery_basis=l["recovery_basis"], handling_pct=l["handling_pct"],
                                expected_return_date=l["due"], remarks=l["remarks"], indent_line_id=l["indent_line_id"], batch_no=l["batch_no"]))
    db.flush()


def issue_lines(db, issue):
    return db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id).order_by(DBStoreIssueLine.line_no, DBStoreIssueLine.id).all()


def check_stock(db, store_id, lines, exclude_indent_id=None, on_hand=True):
    """Everything asked for must be on hand now and not promised to another indent (posting checks again, in the same transaction as the
    movement). An issue filling an indent uses what that indent has reserved."""
    want = {}
    for l in lines:
        item_id = l.item_id if hasattr(l, "item_id") else l["item"].id
        want[item_id] = want.get(item_id, ZERO) + Decimal(str(l.qty if hasattr(l, "qty") else l["qty"]))
    held = store_reservations.reserved_map(db, [store_id], list(want), exclude_indent_id)
    for item_id, qty in want.items():
        have = get_balance(db, store_id, item_id).qty
        item = db.get(models.DBItem, item_id)
        if qty > have:
            if on_hand:
                raise HTTPException(409, "Only %s %s of %s on hand in this store; %s was asked for." % (s3(have), base_uom_of(db, item), item.item_name, s3(qty)))
            continue                                # at posting the ledger itself refuses what is not there
        promised = held.get((store_id, item_id), ZERO)
        if qty > have - promised:
            raise HTTPException(409, "Only %s %s of %s is free in this store - %s of the %s on hand is promised to approved indents; %s was asked for." % (
                s3(max(ZERO, have - promised)), base_uom_of(db, item), item.item_name, s3(promised), s3(have), s3(qty)))


def _recheck_issue(db, issue):
    """What can have changed since the issue was made: its work order closing, its indent being cancelled or already filled."""
    if issue.work_order_id:
        wo = db.get(models.DBWorkOrder, issue.work_order_id)
        if wo is not None and (wo.status or "") in CLOSED_ORDERS:
            raise HTTPException(409, "Work order %s is %s, so nothing can be issued against it." % (wo.number, (wo.status or "").lower()))
    if issue.indent_id:
        indent = db.get(DBStoreIndent, issue.indent_id)
        if indent is None or indent.status not in ("OPEN", "PARTIAL"):
            raise HTTPException(409, "Indent %s is %s, so nothing can be issued against it." % (indent.number if indent else issue.indent_id, (indent.status if indent else "gone").lower()))
        pending = indent_pending(db, indent, exclude_issue=issue.id)
        asked = {}
        for l in issue_lines(db, issue):
            asked[l.indent_line_id] = asked.get(l.indent_line_id, ZERO) + Decimal(str(l.qty))
        for il_id, qty in asked.items():
            if qty > pending.get(il_id, ZERO):
                item = db.get(models.DBItem, db.get(DBStoreIndentLine, il_id).item_id)
                raise HTTPException(409, "Only %s %s of %s is still to be issued on indent %s; this issue takes %s." % (s3(max(ZERO, pending.get(il_id, ZERO))), base_uom_of(db, item), item.item_name, indent.number, s3(qty)))


def issue_check_submit(db, actor, issue):
    _recheck_issue(db, issue)
    lines = issue_lines(db, issue)
    check_stock(db, issue.store_id, lines, issue.indent_id)
    for l in lines:
        _check_batch(db, issue.store_id, db.get(models.DBItem, l.item_id), l.batch_no or "", Decimal(str(l.qty)), issue.issue_date, "Line %d" % (l.line_no or 0))


def issue_post(db, actor, issue):
    _recheck_issue(db, issue)
    check_stock(db, issue.store_id, issue_lines(db, issue), issue.indent_id, on_hand=False)
    mtype = MovementType.SUBCON_ISSUE_OUT if issue.issue_type == SUBCONTRACTOR else MovementType.ISSUE_OUT
    for l in issue_lines(db, issue):
        item = db.get(models.DBItem, l.item_id)
        _check_batch(db, issue.store_id, item, l.batch_no or "", Decimal(str(l.qty)), issue.issue_date, "Line %d" % (l.line_no or 0))
        # The batch named comes out of that batch; with none named, the earliest expiry that has not expired.
        lot = find_lot(db, issue.store_id, l.item_id, l.batch_no) if (l.batch_no or "").strip() else None
        entry = post_movement(db, movement_type=mtype, store_id=issue.store_id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=issue.issue_date, project_id=issue.project_id,
                              work_order_id=issue.work_order_id, boq_item_id=l.boq_item_id, cost_head=l.cost_head, subcontractor_id=issue.subcontractor_id, ref_doc_type=ISSUE,
                              ref_doc_id=issue.id, ref_line_id=l.id, user_id=actor.user_id, remarks=issue.number + ((" - " + issue.purpose) if issue.purpose else ""),
                              lots=[(lot[0], l.qty)] if lot else None)
        if not (l.batch_no or "").strip():      # say on the line which batches it took, for tracing a bad lot to where it went
            from app.models.store_core import DBStoreBatch
            names = [lot_label(db.get(DBStoreBatch, b)) for b, _q in entry_lots(db, entry.id) if b]
            l.batch_no = ", ".join(n for n in names if n)[:120]
        if l.chargeable:                      # the record P5 reads into the subcontractor's bill: the rate is fixed now, at the cost the stock left at or the contract rate
            base = Decimal(str(entry.rate)) if l.recovery_basis == AVERAGE_COST else Decimal(str(l.recovery_rate))
            handling = Decimal(str(l.handling_pct or 0))
            db.add(DBStoreRecovery(client_id=issue.client_id, source="ISSUE", issue_line_id=l.id, store_id=issue.store_id, project_id=issue.project_id, subcontractor_id=issue.subcontractor_id,
                                   subcontract_order_id=issue.subcontract_order_id, holder_type=issue.holder_type or "", holder_id=issue.holder_id, holder_name=issue.holder_name or "",
                                   item_id=l.item_id, qty=l.qty, qty_returned=ZERO, basis=l.recovery_basis, base_rate=base.quantize(_R, rounding=ROUND_HALF_UP), handling_pct=handling,
                                   recovery_rate=(base * (1 + handling / 100)).quantize(_R, rounding=ROUND_HALF_UP), status="OPEN"))
    db.flush()


def issue_check_cancel(db, issue):
    live = db.query(DBStoreIssueReturn.number).filter(DBStoreIssueReturn.issue_id == issue.id, DBStoreIssueReturn.status.in_(LIVE)).first()
    if live:
        raise HTTPException(409, "Return %s was made against this issue. Cancel the return first." % live[0])
    gate = db.query(DBStoreGatePass.number).filter(DBStoreGatePass.issue_id == issue.id, DBStoreGatePass.status != "CANCELLED").first()
    if gate:
        raise HTTPException(409, "Gate pass %s was made for this issue. Cancel the gate pass first." % gate[0])
    if issue.status == DocStatus.POSTED.value:
        closed = (db.query(DBStoreReturnableClosure.id).join(DBStoreIssueLine, DBStoreIssueLine.id == DBStoreReturnableClosure.issue_line_id).filter(DBStoreIssueLine.issue_id == issue.id).first())
        if closed:
            raise HTTPException(409, "Some of what was issued has been converted to a recovery or handed to a write-off request, so the issue cannot be cancelled.")


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


def closed_qty(db, issue_line_ids):
    """{issue_line_id: quantity closed by conversion to a recovery or by a write-off request}."""
    if not issue_line_ids:
        return {}
    rows = (db.query(DBStoreReturnableClosure.issue_line_id, func.sum(DBStoreReturnableClosure.qty)).filter(DBStoreReturnableClosure.issue_line_id.in_(list(issue_line_ids)))
            .group_by(DBStoreReturnableClosure.issue_line_id).all())
    return {i: Decimal(str(n or 0)) for i, n in rows}


def outstanding_on(db, issue, exclude_return=None):
    """{issue_line_id: quantity still out on the line}, counting every live return and everything closed some other way."""
    lines = issue_lines(db, issue)
    ids = [l.id for l in lines]
    taken, closed = _taken_back(db, ids, LIVE, exclude_return), closed_qty(db, ids)
    return {l.id: Decimal(str(l.qty)) - sum(taken.get(l.id, (ZERO, ZERO))) - closed.get(l.id, ZERO) for l in lines}


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
            raise HTTPException(400, "%s: say what happened to what was lost." % label)
        condition = (getattr(r, "condition", "") or "GOOD").strip().upper()
        if condition not in ("GOOD", "DAMAGED"):
            raise HTTPException(400, "%s: the condition is GOOD or DAMAGED." % label)
        bin_id = getattr(r, "bin_id", None) or None
        if condition == "DAMAGED":
            if back <= 0:
                raise HTTPException(400, "%s: only goods that came back can be damaged." % label)
            if not reason:
                raise HTTPException(400, "%s: say what is wrong with the damaged goods." % label)
            row = db.get(DBStoreBin, bin_id) if bin_id else None
            if row is None or row.store_id != issue.store_id or not row.is_active:
                raise HTTPException(400, "%s: damaged goods go into a bin kept for them - choose one of %s's bins." % (label, db.get(DBStore, issue.store_id).code))
        else:
            bin_id = None
        if back + lost > room.get(il.id, ZERO):
            raise HTTPException(409, "%s: only %s %s of %s is still out%s." % (label, s3(max(ZERO, room.get(il.id, ZERO))), base_uom_of(db, item), item.item_name,
                                                                              ", the rest is already on a return or closed" if room.get(il.id, ZERO) < Decimal(str(il.qty)) else ""))
        out.append({"il": il, "item": item, "entry_uom": uom, "back": back, "lost": lost, "reason": reason, "condition": condition, "bin_id": bin_id})
    return out


def write_return_lines(db, ret, lines):
    db.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id == ret.id).delete(synchronize_session=False)
    for l in lines:
        db.add(DBStoreIssueReturnLine(return_id=ret.id, issue_line_id=l["il"].id, item_id=l["item"].id, entry_uom=l["entry_uom"], qty_returned=l["back"], qty_lost=l["lost"], reason=l["reason"],
                                      condition=l["condition"], bin_id=l["bin_id"]))
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
            self.condition, self.bin_id = l.condition or "GOOD", l.bin_id
    build_return_lines(db, ret.client_id, issue, [_R(l) for l in return_lines(db, ret)], return_id=ret.id)


def _issue_entry(db, issue, line):
    row = (db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == ISSUE, DBStoreStockLedger.ref_doc_id == issue.id, DBStoreStockLedger.ref_line_id == line.id,
                                               DBStoreStockLedger.reversal_of_id.is_(None)).order_by(DBStoreStockLedger.id).first())
    if row is None:
        raise HTTPException(409, "Issue %s has no stock entry for that line, so it cannot be returned." % issue.number)
    return row


def _recovery_rows(db, issue_line_id):
    return db.query(DBStoreRecovery).filter(DBStoreRecovery.issue_line_id == issue_line_id, DBStoreRecovery.source == "ISSUE", DBStoreRecovery.status == "OPEN").all()


def return_post(db, actor, ret):
    return_check_submit(db, actor, ret)
    issue = db.get(DBStoreIssue, ret.issue_id)
    lines = {l.id: l for l in issue_lines(db, issue)}
    mtype = MovementType.SUBCON_RETURN_IN if issue.issue_type == SUBCONTRACTOR else MovementType.ISSUE_RETURN_IN
    for rl in return_lines(db, ret):
        il = lines[rl.issue_line_id]
        if Decimal(str(rl.qty_returned)) > 0:
            went = _issue_entry(db, issue, il)          # it comes back at the rate it left at, into the batches it left from
            post_movement(db, movement_type=mtype, store_id=ret.store_id, item_id=rl.item_id, qty=rl.qty_returned, rate=Decimal(str(went.rate)), txn_date=ret.return_date,
                          project_id=issue.project_id, work_order_id=issue.work_order_id, boq_item_id=il.boq_item_id, cost_head=il.cost_head, subcontractor_id=issue.subcontractor_id,
                          ref_doc_type=ISSUE_RETURN, ref_doc_id=ret.id, ref_line_id=rl.id, user_id=actor.user_id,
                          remarks="%s - against %s%s" % (ret.number, issue.number, " (damaged)" if rl.condition == "DAMAGED" else ""),
                          lots=entry_lots(db, went.id) or None)
            for rec in _recovery_rows(db, il.id):         # what is recovered is only what stayed out
                rec.qty_returned = min(Decimal(str(rec.qty)), Decimal(str(rec.qty_returned)) + Decimal(str(rl.qty_returned)))
        if Decimal(str(rl.qty_lost)) > 0:
            db.add(DBStoreWriteoffRequest(client_id=ret.client_id, store_id=ret.store_id, item_id=rl.item_id, qty=rl.qty_lost, reason=rl.reason or "Lost", requested_by_id=ret.created_by_id,
                                          source_issue_line_id=il.id, source_return_id=ret.id, status="OPEN"))
    db.flush()


def return_check_cancel(db, ret):
    closed = db.query(DBStoreWriteoffRequest.id).filter(DBStoreWriteoffRequest.source_return_id == ret.id, DBStoreWriteoffRequest.status == "CLOSED").first()
    if closed:
        raise HTTPException(409, "A write-off raised by this return has already been dealt with, so the return cannot be cancelled.")


def return_undo_recoveries(db, ret):
    """A posted return that is cancelled puts back what it had taken off the recoveries."""
    lines = {l.id: l for l in issue_lines(db, db.get(DBStoreIssue, ret.issue_id))}
    for rl in return_lines(db, ret):
        if rl.issue_line_id in lines and Decimal(str(rl.qty_returned)) > 0:
            for rec in _recovery_rows(db, rl.issue_line_id):
                rec.qty_returned = max(ZERO, Decimal(str(rec.qty_returned)) - Decimal(str(rl.qty_returned)))


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


def advance(db, actor, kind, doc, action, reason="", direct=False):
    """Move a document one step: submit, approve, post, or cancel (with a reason). Posting and cancelling a posted document move
    stock: the caller wraps this in store_errors() and commits once, and rolls back on any error. Approving is for someone other
    than whoever made or submitted it - except a `direct` issue, made, approved and posted in one step under its own right."""
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
        db.flush()
        if kind.key == "issue":
            for rec in db.query(DBStoreRecovery).filter(DBStoreRecovery.issue_line_id.in_([l.id for l in issue_lines(db, doc)] or [0]), DBStoreRecovery.source == "ISSUE").all():
                rec.status = "CANCELLED"
            if doc.indent_id:
                refresh_indent(db, db.get(DBStoreIndent, doc.indent_id))
        if kind.key == "returns" and now == DocStatus.POSTED.value:
            return_undo_recoveries(db, doc)
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
    if action in ("submit", "post"):
        try:
            check_date(db, actor.client.id, getattr(doc, kind.date_attr))
        except InvalidMovementError as exc:
            raise HTTPException(400, str(exc)) from exc
    if action == "approve" and not direct:
        check_not_own(db, actor, doc, DBStoreOutwardLog, kind.ref, kind.label)
    if action == "post":
        kind.post(db, actor, doc)
        doc.posted_at = datetime.now()
    doc.status = to.value
    if kind.key == "issue" and action == "post" and doc.indent_id:
        db.flush()
        refresh_indent(db, db.get(DBStoreIndent, doc.indent_id))
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

    Posted issues only. qty_returned is what came back; the recovery rate is the one fixed when the issue posted (the contract rate or the average cost,
    plus handling), so a line marked chargeable recovers (issued - returned) x that rate and a free-of-cost line recovers nothing. Returnables converted
    to a charge are listed too, on the issue line they came from, with the quantity converted as qty_issued."""
    upto = _as_day(upto_date)
    rows = (db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
            .filter(DBStoreIssue.subcontractor_id == subcontractor_id, DBStoreIssue.issue_type == SUBCONTRACTOR, DBStoreIssue.status == DocStatus.POSTED.value,
                    DBStoreIssue.issue_date <= upto).order_by(DBStoreIssue.issue_date, DBStoreIssueLine.id).all())
    ids = [l.id for l, _i in rows]
    back = _taken_back(db, ids, (DocStatus.POSTED.value,))
    recs = {r.issue_line_id: r for r in db.query(DBStoreRecovery).filter(DBStoreRecovery.issue_line_id.in_(ids or [0]), DBStoreRecovery.source == "ISSUE", DBStoreRecovery.status == "OPEN").all()}
    out = []
    for l, issue in rows:
        returned = back.get(l.id, (ZERO, ZERO))[0]
        rec = recs.get(l.id)
        rate = Decimal(str(rec.recovery_rate)) if rec is not None else ZERO
        left = max(ZERO, Decimal(str(l.qty)) - returned)
        out.append(SubconIssueLine(issue_line_id=l.id, issue_date=issue.issue_date, item_id=l.item_id, qty_issued=q3(l.qty), qty_returned=q3(returned), chargeable=bool(l.chargeable),
                                   recovery_rate=q3(rate), recovery_value=(left * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if (l.chargeable and rec is not None) else ZERO))
    for rec in (db.query(DBStoreRecovery).filter(DBStoreRecovery.subcontractor_id == subcontractor_id, DBStoreRecovery.source == "CONVERSION", DBStoreRecovery.status == "OPEN").order_by(DBStoreRecovery.id).all()):
        when = rec.created_at.date() if rec.created_at else date.today()
        if when > upto:
            continue
        rate = Decimal(str(rec.recovery_rate))
        out.append(SubconIssueLine(issue_line_id=rec.issue_line_id, issue_date=when, item_id=rec.item_id, qty_issued=q3(rec.qty), qty_returned=q3(rec.qty_returned), chargeable=True, recovery_rate=q3(rate),
                                   recovery_value=(max(ZERO, Decimal(str(rec.qty)) - Decimal(str(rec.qty_returned))) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))
    return out


def get_outstanding_returnables(db, project_id=None, store_id=None, client_id=None) -> List[ReturnableOutstanding]:
    """Returnable items and tools issued and not yet back: issued less what has been returned, reported lost, converted to a recovery or handed to a
    write-off request, per issue line."""
    q = (db.query(DBStoreIssueLine, DBStoreIssue).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
         .join(DBStoreItemSettings, DBStoreItemSettings.item_id == DBStoreIssueLine.item_id)
         .filter(DBStoreIssue.status == DocStatus.POSTED.value, DBStoreItemSettings.category.in_(RETURNABLE_CATEGORIES)))
    if client_id:
        q = q.filter(DBStoreIssue.client_id == client_id)
    if project_id:
        q = q.filter(DBStoreIssue.project_id == project_id)
    if store_id:
        q = q.filter(DBStoreIssue.store_id == store_id)
    rows = q.order_by(DBStoreIssue.issue_date, DBStoreIssueLine.id).all()
    ids = [l.id for l, _i in rows]
    taken, closed = _taken_back(db, ids, (DocStatus.POSTED.value,)), closed_qty(db, ids)
    today = date.today()
    out = []
    for l, issue in rows:
        left = Decimal(str(l.qty)) - sum(taken.get(l.id, (ZERO, ZERO))) - closed.get(l.id, ZERO)
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


# --- indents ------------------------------------------------------------------------------------------------------------------

def indent_lines(db, indent):
    return db.query(DBStoreIndentLine).filter(DBStoreIndentLine.indent_id == indent.id).order_by(DBStoreIndentLine.line_no, DBStoreIndentLine.id).all()


def indent_fulfilled(db, indent):
    """{indent_line_id: quantity issued so far}: posted issues only."""
    ids = [l.id for l in indent_lines(db, indent)]
    if not ids:
        return {}
    rows = (db.query(DBStoreIssueLine.indent_line_id, func.sum(DBStoreIssueLine.qty)).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
            .filter(DBStoreIssueLine.indent_line_id.in_(ids), DBStoreIssue.status == DocStatus.POSTED.value).group_by(DBStoreIssueLine.indent_line_id).all())
    return {i: Decimal(str(n or 0)) for i, n in rows}


def refresh_indent(db, indent):
    """OPEN -> PARTIAL -> CLOSED as issues post and are cancelled. An indent that was closed short by hand stays closed."""
    if indent is None or indent.status not in ("OPEN", "PARTIAL", "CLOSED") or indent.short_closed:
        return
    done = indent_fulfilled(db, indent)
    lines = [l for l in indent_lines(db, indent) if Decimal(str(l.approved_qty or 0)) > 0]
    if lines and all(done.get(l.id, ZERO) >= Decimal(str(l.approved_qty)) for l in lines):
        indent.status = "CLOSED"
    elif any(done.get(l.id, ZERO) > 0 for l in lines):
        indent.status = "PARTIAL"
    else:
        indent.status = "OPEN"


def check_indent_header(db, client_id, body):
    project = db.query(models.DBJob).filter(models.DBJob.id == body.project_id, models.DBJob.client_id == client_id).first()
    if project is None:
        raise HTTPException(400, "Choose the project the material is for.")
    wo = None
    if body.work_order_id:
        wo = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == body.work_order_id, models.DBWorkOrder.client_id == client_id, models.DBWorkOrder.job_id == project.id).first()
        if wo is None:
            raise HTTPException(400, "That work order is not one of this project's.")
        if (wo.status or "") in CLOSED_ORDERS:
            raise HTTPException(409, "Work order %s is %s, so material cannot be asked for against it." % (wo.number, (wo.status or "").lower()))
    if body.boq_item_id:
        _boq_line(db, client_id, project.id, body.boq_item_id)
    activity = text(body.activity, "activity", 200)
    if not (wo or body.boq_item_id or activity):
        raise HTTPException(400, "Say what the material is for: a work order, a BOQ item or an activity.")
    return project, wo


def build_indent_lines(db, client_id, rows):
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        if item.id in seen:
            raise HTTPException(400, "%s: %s is on the indent twice." % (label, item.item_name))
        seen.add(item.id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        out.append({"item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": to_base(db, item.id, entry, uom), "purpose": text(r.purpose, "purpose", 200)})
    return out


def write_indent_lines(db, indent, lines):
    db.query(DBStoreIndentLine).filter(DBStoreIndentLine.indent_id == indent.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBStoreIndentLine(indent_id=indent.id, line_no=n, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], purpose=l["purpose"]))
    db.flush()


def indent_submit(db, actor, indent):
    if indent.status != "DRAFT":
        raise HTTPException(409, "It is %s, so it cannot be submitted now." % indent.status.lower())
    if not indent_lines(db, indent):
        raise HTTPException(400, "Add at least one line before submitting.")
    indent.status = "SUBMITTED"
    log(db, actor, INDENT, indent.id, "submit", "DRAFT", "SUBMITTED")


def can_approve_indent(db, actor, indent, has_admin):
    """The project manager approves an indent. If the project names one, only they (or store.admin, or the account holder) may; if it names none, any holder of the right may."""
    job = db.get(models.DBJob, indent.project_id)
    if actor.employee is not None and job is not None and job.manager_id and job.manager_id != actor.employee.id and not has_admin:
        mgr = db.get(models.DBEmployee, job.manager_id)
        raise HTTPException(403, "Only the project manager (%s) can approve an indent for this project." % (("%s %s" % (mgr.first_name, mgr.last_name)).strip() if mgr else "not found"))


def indent_approve(db, actor, indent, rows, remarks, has_admin):
    """Approve an indent, with the quantities the approver allows: each can be cut back (to nothing) but never raised. A line cut back says why
    (its own reason, or the approval's remarks), and may be replaced by another item - the substitute becomes a line of the indent in its own right,
    so it is reserved, issued against and closed like any other."""
    if indent.status != "SUBMITTED":
        raise HTTPException(409, "It is %s, so it cannot be approved now." % indent.status.lower())
    can_approve_indent(db, actor, indent, has_admin)
    lines = {l.id: l for l in indent_lines(db, indent)}
    overall = text(remarks, "remarks", 200)
    given, why, subs = {}, {}, []
    for r in rows or []:
        if r.line_id not in lines:
            raise HTTPException(400, "Line %s is not on this indent." % r.line_id)
        if r.line_id in given:
            raise HTTPException(400, "A line is on the approval twice.")
        line = lines[r.line_id]
        item = db.get(models.DBItem, line.item_id)
        uom = text(r.uom, "unit", 20) or line.entry_uom or base_uom_of(db, item)
        entry = dec(r.approved_qty, "Approved quantity")
        given[r.line_id] = to_base(db, item.id, entry, uom) if entry > 0 else ZERO
        if given[r.line_id] > Decimal(str(line.qty)):
            raise HTTPException(409, "%s: the approver can reduce what was asked for (%s %s), not raise it." % (item.item_name, s3(line.qty), base_uom_of(db, item)))
        reason = text(getattr(r, "reason", ""), "reason", 200) or overall
        if given[r.line_id] < Decimal(str(line.qty)):
            if len(reason) < 3:
                raise HTTPException(400, "%s: say why it was cut back." % item.item_name)
            why[r.line_id] = reason
        sub_id = getattr(r, "substitute_item_id", None)
        if sub_id:
            if given[r.line_id] >= Decimal(str(line.qty)):
                raise HTTPException(400, "%s: cut the original quantity back before giving a substitute for it." % item.item_name)
            sub = item_of(db, indent.client_id, sub_id)
            if sub.id == item.id:
                raise HTTPException(400, "%s: the substitute must be a different item." % item.item_name)
            sub_uom = text(getattr(r, "substitute_uom", ""), "unit", 20) or base_uom_of(db, sub)
            sub_entry = dec(getattr(r, "substitute_qty", ""), "%s substitute quantity" % sub.item_name, allow_zero=False)
            subs.append((line, sub, sub_uom, sub_entry, to_base(db, sub.id, sub_entry, sub_uom)))
    for l in lines.values():
        l.approved_qty = given.get(l.id, Decimal(str(l.qty)))
    next_no = max([l.line_no or 0 for l in lines.values()] or [0])
    for line, sub, sub_uom, sub_entry, sub_base in subs:
        next_no += 1
        extra = DBStoreIndentLine(indent_id=indent.id, line_no=next_no, item_id=sub.id, entry_uom=sub_uom, entry_qty=q3(sub_entry), qty=sub_base, approved_qty=sub_base,
                                  purpose="Substitute for %s" % db.get(models.DBItem, line.item_id).item_name)
        db.add(extra)
        db.flush()
        db.add(DBStoreIndentLineNote(indent_line_id=extra.id, reason=why.get(line.id, overall), substitute_for_line_id=line.id))
    for line_id, reason in why.items():
        db.add(DBStoreIndentLineNote(indent_line_id=line_id, reason=reason))
    db.flush()
    if not any(Decimal(str(l.approved_qty)) > 0 for l in indent_lines(db, indent)):
        raise HTTPException(400, "Everything was cut to nothing. Cancel the indent instead.")
    indent.status, indent.approved_by_name, indent.approved_at = "OPEN", actor.name, datetime.now()
    indent.approver_remarks = overall
    log(db, actor, INDENT, indent.id, "approve", "SUBMITTED", "OPEN", indent.approver_remarks)


def indent_cancel(db, actor, indent, reason):
    reason = text(reason, "reason", 200)
    if len(reason) < 3:
        raise HTTPException(400, "Say why it is being cancelled.")
    if indent.status in ("CANCELLED", "CLOSED"):
        raise HTTPException(409, "It is already %s." % indent.status.lower())
    if indent.status == "PARTIAL" or db.query(DBStoreIssue.id).filter(DBStoreIssue.indent_id == indent.id, DBStoreIssue.status.in_(LIVE)).first():
        raise HTTPException(409, "Material has been issued against it. Close it short instead, or cancel the issues first.")
    before = indent.status
    indent.status, indent.cancel_reason = "CANCELLED", reason
    log(db, actor, INDENT, indent.id, "cancel", before, "CANCELLED", reason)


def indent_close(db, actor, indent, reason):
    """Close an indent short: what is still pending will not be issued."""
    reason = text(reason, "reason", 200)
    if len(reason) < 3:
        raise HTTPException(400, "Say why it is being closed.")
    if indent.status not in ("OPEN", "PARTIAL"):
        raise HTTPException(409, "It is %s, so it cannot be closed now." % indent.status.lower())
    before = indent.status
    indent.status, indent.short_closed, indent.cancel_reason = "CLOSED", 1, reason
    log(db, actor, INDENT, indent.id, "close", before, "CLOSED", reason)


# --- converting a returnable to a recovery, and handing it to a write-off request ----------------------------------------------------

def _returnable_line(db, actor, issue_line_id):
    line = db.get(DBStoreIssueLine, issue_line_id) if issue_line_id else None
    issue = db.get(DBStoreIssue, line.issue_id) if line else None
    if line is None or issue is None or issue.client_id != actor.client.id:
        raise HTTPException(404, "Issue line not found")
    if issue.status != DocStatus.POSTED.value:
        raise HTTPException(409, "Only a posted issue has anything out.")
    if not is_returnable(db, line.item_id):
        raise HTTPException(409, "That is a consumable, not a returnable item or tool.")
    return line, issue


def _closing_qty(db, line, issue, qty_text, uom):
    item = db.get(models.DBItem, line.item_id)
    qty = to_base(db, item.id, dec(qty_text, "Quantity", allow_zero=False), text(uom, "unit", 20) or base_uom_of(db, item))
    left = outstanding_on(db, issue).get(line.id, ZERO)
    if qty > left:
        raise HTTPException(409, "Only %s %s of %s is still out." % (s3(max(ZERO, left)), base_uom_of(db, item), item.item_name))
    return item, qty


def convert_returnable(db, actor, issue_line_id, qty_text, uom, rate_text, handling_text, reason):
    """Close what is still out by charging the holder for it: a recovery at a rate and handling percentage, to be taken from their bill."""
    line, issue = _returnable_line(db, actor, issue_line_id)
    item, qty = _closing_qty(db, line, issue, qty_text, uom)
    reason = text(reason, "reason", 200, required=True)
    rate = dec(rate_text, "Rate to recover", allow_zero=False).quantize(_R)
    handling = pct(handling_text if str(handling_text or "").strip() else outward_settings(db, actor.client.id).subcon_handling_pct, "The handling percentage")
    rec = DBStoreRecovery(client_id=actor.client.id, source="CONVERSION", issue_line_id=line.id, store_id=issue.store_id, project_id=issue.project_id, subcontractor_id=issue.subcontractor_id,
                          subcontract_order_id=issue.subcontract_order_id, holder_type=issue.holder_type or "", holder_id=issue.holder_id, holder_name=issue.holder_name or "", item_id=item.id, qty=qty,
                          qty_returned=ZERO, basis="CONVERSION", base_rate=rate, handling_pct=handling, recovery_rate=(rate * (1 + handling / 100)).quantize(_R, rounding=ROUND_HALF_UP), status="OPEN")
    db.add(rec)
    db.flush()
    closure = DBStoreReturnableClosure(client_id=actor.client.id, issue_line_id=line.id, kind="CONVERSION", qty=qty, reason=reason, recovery_id=rec.id, created_by_name=actor.name)
    db.add(closure)
    db.flush()
    return rec, closure


def writeoff_returnable(db, actor, issue_line_id, qty_text, uom, reason):
    """Close what is still out by asking for it to be written off: this creates the request; P4 posts the write-off."""
    line, issue = _returnable_line(db, actor, issue_line_id)
    item, qty = _closing_qty(db, line, issue, qty_text, uom)
    reason = text(reason, "reason", 200, required=True)
    req = DBStoreWriteoffRequest(client_id=actor.client.id, store_id=issue.store_id, item_id=item.id, qty=qty, reason=reason, source_issue_line_id=line.id, status="OPEN",
                                 requested_by_id=actor.user_id)
    db.add(req)
    db.flush()
    closure = DBStoreReturnableClosure(client_id=actor.client.id, issue_line_id=line.id, kind="WRITEOFF", qty=qty, reason=reason, writeoff_request_id=req.id, created_by_name=actor.name)
    db.add(closure)
    db.flush()
    return req, closure


# --- gate passes ----------------------------------------------------------------------------------------------------------------

def gate_lines(db, gp):
    return db.query(DBStoreGatePassLine).filter(DBStoreGatePassLine.gate_pass_id == gp.id).order_by(DBStoreGatePassLine.id).all()


def create_gate_pass(db, actor, body):
    """A pass for material leaving the store's premises, from a posted issue: all of it or the lines (and quantities) named."""
    issue = db.get(DBStoreIssue, body.issue_id)
    if issue is None or issue.client_id != actor.client.id:
        raise HTTPException(404, "Issue not found")
    if issue.status != DocStatus.POSTED.value:
        raise HTTPException(409, "A gate pass is made for material that has been issued: post the issue first.")
    iss_lines = {l.id: l for l in issue_lines(db, issue)}
    given = {}
    for r in (body.lines or []):
        if r.issue_line_id not in iss_lines:
            raise HTTPException(400, "A line is not on issue %s." % issue.number)
        if r.issue_line_id in given:
            raise HTTPException(400, "A line is on the pass twice.")
        l = iss_lines[r.issue_line_id]
        item = db.get(models.DBItem, l.item_id)
        given[l.id] = to_base(db, item.id, dec(r.qty, "Quantity", allow_zero=False), text(r.uom, "unit", 20) or l.entry_uom or base_uom_of(db, item))
    if not given:
        given = {l.id: Decimal(str(l.qty)) for l in iss_lines.values()}
    already = {i: Decimal(str(n or 0)) for i, n in (db.query(DBStoreGatePassLine.issue_line_id, func.sum(DBStoreGatePassLine.qty)).join(DBStoreGatePass, DBStoreGatePass.id == DBStoreGatePassLine.gate_pass_id)
                                                     .filter(DBStoreGatePassLine.issue_line_id.in_(list(given)), DBStoreGatePass.status != "CANCELLED").group_by(DBStoreGatePassLine.issue_line_id).all())}
    for lid, qty in given.items():
        l = iss_lines[lid]
        if qty + already.get(lid, ZERO) > Decimal(str(l.qty)):
            item = db.get(models.DBItem, l.item_id)
            raise HTTPException(409, "%s: only %s %s was issued, and %s already has a gate pass." % (item.item_name, s3(l.qty), base_uom_of(db, item), s3(already.get(lid, ZERO))))
    returnable = any(is_returnable(db, iss_lines[lid].item_id) for lid in given)
    due = day(body.expected_return_date, "Expected return date", allow_future=True, required=False)
    if returnable and due is None:
        due = max((iss_lines[lid].expected_return_date for lid in given if iss_lines[lid].expected_return_date), default=None)
    if returnable and due is None:
        raise HTTPException(400, "A pass for returnable items or tools says when they are due back.")
    on = day(body.gate_date, "Date")
    if due is not None and due < on:
        raise HTTPException(400, "The return date is before the pass date.")
    gp = DBStoreGatePass(client_id=actor.client.id, store_id=issue.store_id, number=numbered(db, GATE_PASS, issue.store_id, on), status="ISSUED", gate_date=on, issue_id=issue.id,
                         vehicle_no=text(body.vehicle_no, "vehicle number", 30), driver_name=text(body.driver_name, "driver", 80), destination=text(body.destination, "destination", 200, required=True),
                         purpose=text(body.purpose, "purpose", 200), returnable=1 if returnable else 0, expected_return_date=due if returnable else None,
                         authorised_by_name=actor.name, remarks=text(body.remarks, "remarks", 500), created_by_id=actor.user_id, created_by_name=actor.name)
    db.add(gp)
    db.flush()
    for lid, qty in given.items():
        db.add(DBStoreGatePassLine(gate_pass_id=gp.id, issue_line_id=lid, item_id=iss_lines[lid].item_id, qty=qty))
    log(db, actor, GATE_PASS, gp.id, "create", "", "ISSUED", "for %s" % issue.number)
    db.flush()
    return gp


def gate_close(db, actor, gp):
    if gp.status != "ISSUED" or not gp.returnable:
        raise HTTPException(409, "Only the pass of returnable material that is still out can be closed.")
    gp.status, gp.closed_at = "CLOSED", datetime.now()
    log(db, actor, GATE_PASS, gp.id, "close", "ISSUED", "CLOSED", "material is back")


def gate_cancel(db, actor, gp, reason):
    reason = text(reason, "reason", 200)
    if len(reason) < 3:
        raise HTTPException(400, "Say why it is being cancelled.")
    if gp.status != "ISSUED":
        raise HTTPException(409, "It is %s, so it cannot be cancelled." % gp.status.lower())
    gp.status, gp.cancel_reason = "CANCELLED", reason
    log(db, actor, GATE_PASS, gp.id, "cancel", "ISSUED", "CANCELLED", reason)


# --- the norm warning -----------------------------------------------------------------------------------------------------------------

def norm_warnings(db, issue) -> List[str]:
    """Warnings (never blocks) when what has been issued to a BOQ item, with this issue, is more than its norm says it needs. Silent when
    the reports slice is not there or no norm is set."""
    try:
        from app.services.store_reports import get_theoretical_requirement
    except ImportError:
        return []
    out = []
    for l in issue_lines(db, issue):
        if not l.boq_item_id:
            continue
        need = get_theoretical_requirement(db, l.boq_item_id, l.item_id)
        if need is None:
            continue
        posted_lines = (db.query(DBStoreIssueLine.id, DBStoreIssueLine.qty).join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
                        .filter(DBStoreIssueLine.boq_item_id == l.boq_item_id, DBStoreIssueLine.item_id == l.item_id, DBStoreIssue.status == DocStatus.POSTED.value, DBStoreIssue.id != issue.id).all())
        back = _taken_back(db, [i for i, _q in posted_lines], (DocStatus.POSTED.value,))
        total = sum((Decimal(str(q)) - back.get(i, (ZERO, ZERO))[0] for i, q in posted_lines), ZERO) + Decimal(str(l.qty))
        if total > Decimal(str(need)):
            item = db.get(models.DBItem, l.item_id)
            boq = db.get(models.DBBoqLine, l.boq_item_id)
            out.append("%s on BOQ item %s: %s %s issued in all with this, against %s %s by its norms." % (item.item_name, (boq.item_no or boq.id) if boq else l.boq_item_id, s3(total), base_uom_of(db, item), s3(need), base_uom_of(db, item)))
    return out
