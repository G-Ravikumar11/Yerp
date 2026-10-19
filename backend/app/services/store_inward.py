"""Store module - inward slice: goods receipts (GRN) with their quality check, returns to the supplier, material supplied by
the client, and opening stock. Owned by P2.

Every document runs DRAFT -> SUBMITTED -> APPROVED -> POSTED, or is CANCELLED. Only POSTED has touched stock: posting calls
post_movement for each line and the router commits once; cancelling a POSTED document calls reverse_document. A document
can be edited only while it is a DRAFT; a POSTED one never. Quantities are kept in the item's base unit.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import (
    DBStore, DBStoreItemSettings, DBStoreStockBalance, DocStatus, InvalidMovementError, MovementType,
)
from app.models.store_inward import (
    CLIENT_SUPPLY, GRN, OPENING, PURCHASE_RETURN, DBStoreClientSupply, DBStoreClientSupplyLine, DBStoreGrn, DBStoreGrnLine,
    DBStoreInwardLog, DBStoreOpening, DBStoreOpeningLine, DBStorePurchaseReturn, DBStorePurchaseReturnLine,
)
from app.schemas.store_contracts import PoLineReceipt
from app.services.stock_ledger import convert_to_base, post_movement, reverse_document
from app.services.store_batches import default_expiry
from app.services.store_integration import old_received_in_base
from app.services.store_numbering import next_doc_number

ZERO = Decimal("0")
_Q, _R = Decimal("0.001"), Decimal("0.0001")
LIVE = (DocStatus.SUBMITTED.value, DocStatus.APPROVED.value, DocStatus.POSTED.value)     # a document that counts against a PO or a GRN
PO_OPEN = ("Approved",)


# --- small helpers --------------------------------------------------------------------------------------------------

def dec(value, what, *, minimum=ZERO, allow_zero=True, high=Decimal("999999999999")) -> Decimal:
    try:
        d = Decimal(str(value if value is not None else "").strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite():
        raise HTTPException(400, "%s is not a number." % what)
    if d < minimum or (d == minimum and not allow_zero):
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
    if out.year < 2000:
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


def r4(x) -> Decimal:
    return Decimal(str(x)).quantize(_R, rounding=ROUND_HALF_UP)


def s3(x) -> str:
    return format(q3(x if x is not None else 0), "f")


def s4(x) -> str:
    return format(r4(x if x is not None else 0), "f")


def item_of(db, client_id, item_id) -> models.DBItem:
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id or item.kind != "RM":
        raise HTTPException(400, "That item is not a stock item of this company.")
    return item


def to_base(db, item_id, qty: Decimal, uom: str) -> Decimal:
    """`qty` counted in `uom`, as the item's base unit. An unknown unit is a 400 that says what to set up."""
    try:
        base = convert_to_base(db, item_id, qty, uom)
    except InvalidMovementError as exc:
        raise HTTPException(400, str(exc)) from exc
    if base <= 0:
        raise HTTPException(400, "That quantity is too small to count: it comes to nothing in the base unit.")
    return base


def base_uom_of(db, item) -> str:
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    return ((s.base_uom if s else item.units_of_measure) or "").strip()


def tolerance_of(db, item_id) -> Decimal:
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    return Decimal(str(s.over_receipt_tolerance_pct or 0)) if s else ZERO


def qc_required(db, item_id) -> bool:
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    return bool(s and s.qc_required)


def log(db, actor, doc_type, doc_id, action, before="", after="", note=""):
    db.add(DBStoreInwardLog(client_id=actor.client.id, doc_type=doc_type, doc_id=doc_id, action=action, from_status=before, to_status=after,
                            user_id=actor.user_id, user_name=actor.name, note=(note or "")[:300]))


def numbered(db, doc_type, store_id, on_date) -> str:
    return next_doc_number(db, doc_type, store_id, on_date=on_date)


# --- purchase orders --------------------------------------------------------------------------------------------------

def po_item(db, po, po_line) -> Optional[models.DBItem]:
    """The stock item a purchase-order line names by its item code (None when it names none)."""
    code = (po_line.item_code or "").strip()
    if not code:
        return None
    return db.query(models.DBItem).filter(models.DBItem.client_id == po.client_id, models.DBItem.item_code == code,
                                          models.DBItem.kind == "RM").first()


def _ordered_base(db, po_line, item) -> Decimal:
    """What a PO line ordered, in the item's base unit; zero when the line's unit cannot be converted."""
    try:
        return convert_to_base(db, item.id, Decimal(str(po_line.qty or 0)), po_line.uom or base_uom_of(db, item))
    except InvalidMovementError:
        return ZERO


def _sum_lines(db, status_in, po_line_ids, exclude_grn=None):
    """{po_line_id: (received, accepted, rejected)} over GRNs in the given statuses."""
    if not po_line_ids:
        return {}
    q = (db.query(DBStoreGrnLine.po_line_id, func.sum(DBStoreGrnLine.received_qty), func.sum(DBStoreGrnLine.accepted_qty), func.sum(DBStoreGrnLine.rejected_qty))
         .join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id)
         .filter(DBStoreGrnLine.po_line_id.in_(list(po_line_ids)), DBStoreGrn.status.in_(status_in)))
    if exclude_grn:
        q = q.filter(DBStoreGrn.id != exclude_grn)
    return {pl: (Decimal(str(r or 0)), Decimal(str(a or 0)), Decimal(str(j or 0))) for pl, r, a, j in q.group_by(DBStoreGrnLine.po_line_id).all()}


def _returned_by_grn_line(db, grn_line_ids, statuses, exclude_return=None):
    if not grn_line_ids:
        return {}
    q = (db.query(DBStorePurchaseReturnLine.grn_line_id, func.sum(DBStorePurchaseReturnLine.qty))
         .join(DBStorePurchaseReturn, DBStorePurchaseReturn.id == DBStorePurchaseReturnLine.return_id)
         .filter(DBStorePurchaseReturnLine.grn_line_id.in_(list(grn_line_ids)), DBStorePurchaseReturn.status.in_(statuses)))
    if exclude_return:
        q = q.filter(DBStorePurchaseReturn.id != exclude_return)
    return {g: Decimal(str(n or 0)) for g, n in q.group_by(DBStorePurchaseReturnLine.grn_line_id).all()}


def get_po_receipt_summary(db, po_id) -> List[PoLineReceipt]:
    """What has been received, accepted, rejected and is still pending on each line of a purchase order.

    Counts POSTED goods receipts only, in the item's base unit. Accepted is net of what was returned to the supplier (the
    supplier owes that again), and pending is what is still to be accepted: never below zero."""
    po = db.get(models.DBPurchaseOrder, po_id) if po_id else None
    if po is None:
        return []
    lines = db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id).order_by(models.DBPurchaseOrderLineItem.id).all()
    posted = _sum_lines(db, (DocStatus.POSTED.value,), [l.id for l in lines])
    grn_lines = (db.query(DBStoreGrnLine.id, DBStoreGrnLine.po_line_id).join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id)
                 .filter(DBStoreGrnLine.po_line_id.in_([l.id for l in lines] or [0]), DBStoreGrn.status == DocStatus.POSTED.value).all())
    returned = _returned_by_grn_line(db, [g for g, _p in grn_lines], (DocStatus.POSTED.value,))
    back = {}
    for gl, pl in grn_lines:
        back[pl] = back.get(pl, ZERO) + returned.get(gl, ZERO)
    items = {l.id: po_item(db, po, l) for l in lines}
    # What the old store received on this order, before the company moved into the Hub, is received here too.
    old = old_received_in_base(db, {l.id: (l, items[l.id]) for l in lines})
    out = []
    for l in lines:
        item = items[l.id]
        ordered = _ordered_base(db, l, item) if item else Decimal(str(l.qty or 0))
        rec, acc, rej = posted.get(l.id, (ZERO, ZERO, ZERO))
        rec, acc = rec + old.get(l.id, ZERO), acc - back.get(l.id, ZERO) + old.get(l.id, ZERO)
        out.append(PoLineReceipt(po_line_id=l.id, item_id=item.id if item else None, ordered_qty=q3(ordered), received_qty=q3(rec),
                                 accepted_qty=q3(acc), rejected_qty=q3(rej), pending_qty=q3(max(ZERO, ordered - acc))))
    return out


def _category_of(db, item_id):
    s = db.query(DBStoreItemSettings.category, DBStoreItemSettings.is_batch_tracked).filter(DBStoreItemSettings.item_id == item_id).first()
    return {"category": s[0] if s else None, "batch_tracked": bool(s[1]) if s else False}


def open_purchase_orders(db, client_id, visible_projects=None, q=""):
    """Approved purchase orders that still have something to receive, with each line's pending quantity."""
    query = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.status.in_(PO_OPEN))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(models.DBPurchaseOrder.number.ilike(like) | models.DBPurchaseOrder.supplier_name.ilike(like))
    out = []
    for po in query.order_by(models.DBPurchaseOrder.id.desc()).limit(50).all():
        summary = {s.po_line_id: s for s in get_po_receipt_summary(db, po.id)}
        lines = db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id).order_by(models.DBPurchaseOrderLineItem.id).all()
        rows = []
        for l in lines:
            sm = summary.get(l.id)
            item = po_item(db, po, l)
            if sm is None or item is None or sm.pending_qty <= 0:
                continue
            rows.append({"po_line_id": l.id, "item_id": item.id, "item_code": item.item_code, "item_name": item.item_name, "description": l.description or "",
                         "po_uom": l.uom or "", "po_qty": s3(l.qty), "price": s4(l.price), "base_uom": base_uom_of(db, item), "ordered": s3(sm.ordered_qty),
                         "accepted": s3(sm.accepted_qty), "pending": s3(sm.pending_qty), **_category_of(db, item.id)})
        if rows:
            out.append({"id": po.id, "number": po.number, "supplier_name": po.supplier_name or "", "project_id": po.job_id, "issue_date": po.issue_date or "", "lines": rows})
    return out


# --- GRN ---------------------------------------------------------------------------------------------------------------

def _po_for(db, client_id, po_id):
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None or po.client_id != client_id:
        raise HTTPException(400, "That purchase order does not exist.")
    if po.status not in PO_OPEN:
        raise HTTPException(409, "Purchase order %s is %s, so nothing can be received against it." % (po.number, (po.status or "not approved").lower()))
    return po


def check_project(db, client_id, project_id):
    if project_id and not db.query(models.DBJob.id).filter(models.DBJob.id == project_id, models.DBJob.client_id == client_id).first():
        raise HTTPException(400, "That project does not exist.")


def build_grn_lines(db, client_id, po, rows, grn_id=None):
    """Validated line values for a GRN from what the screen sent. Nothing is written."""
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    out, seen_po = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        po_line = None
        if r.po_line_id:
            if po is None:
                raise HTTPException(400, "%s: a purchase-order line needs the purchase order." % label)
            po_line = db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.id == r.po_line_id, models.DBPurchaseOrderLineItem.order_id == po.id).first()
            if po_line is None:
                raise HTTPException(400, "%s is not a line of purchase order %s." % (label, po.number))
            if po_line.id in seen_po:
                raise HTTPException(400, "%s: that purchase-order line is on the receipt twice." % label)
            seen_po.add(po_line.id)
            item = po_item(db, po, po_line)
            if item is None:
                raise HTTPException(400, "%s: the purchase-order line has no stock item code, so it cannot be received into stock." % label)
        else:
            if po is not None:
                raise HTTPException(400, "%s: choose the purchase-order line it is for." % label)
            item = item_of(db, client_id, r.item_id)
        uom = text(r.uom, "unit", 20) or (po_line.uom if po_line and po_line.uom else base_uom_of(db, item))
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        received = to_base(db, item.id, entry, uom)
        rejected_entry = dec(r.rejected_qty or "0", label + " rejected quantity")
        rejected = to_base(db, item.id, rejected_entry, uom) if rejected_entry > 0 else ZERO
        if rejected > received:
            raise HTTPException(400, "%s: more was rejected than was received." % label)
        reason = text(r.reject_reason, "rejection reason", 200)
        if rejected > 0 and not reason:
            raise HTTPException(400, "%s: say why the goods were rejected." % label)
        price = r.rate if (r.rate or "").strip() else (str(po_line.price) if po_line else "")
        if not (price or "").strip():
            raise HTTPException(400, "%s: give the rate." % label)
        rate_entry = dec(price, label + " rate", allow_zero=False)
        rate = r4(rate_entry * entry / received)                       # per base unit
        status = "PENDING" if qc_required(db, item.id) else "NOT_REQUIRED"
        made = day(getattr(r, "manufacturing_date", ""), label + " manufacturing date", required=False)
        expiry = day(getattr(r, "expiry_date", ""), label + " expiry date", allow_future=True, required=False) or default_expiry(item, made)
        if made and expiry and expiry < made:
            raise HTTPException(400, "%s: the expiry date is before the manufacturing date." % label)
        out.append({"po_line": po_line, "manufacturing_date": made, "expiry_date": expiry, "item": item, "entry_uom": uom, "entry_qty": q3(entry), "received": received, "rejected": rejected,
                    "accepted": ZERO if status == "PENDING" else received - rejected, "rate": rate, "qc_status": status, "reject_reason": reason,
                    "batch_no": text(r.batch_no, "batch", 40), "bin_id": r.bin_id or None, "remarks": text(r.remarks, "remarks", 200), "label": label})
    return out


def check_over_receipt(db, po, lines, exclude_grn=None):
    """No line may take the accepted total on a purchase-order line past what was ordered plus the item's tolerance."""
    if po is None:
        return
    ids = [l["po_line"].id for l in lines if l["po_line"] is not None]
    prior = _sum_lines(db, LIVE, ids, exclude_grn=exclude_grn)
    old = old_received_in_base(db, {l["po_line"].id: (l["po_line"], l["item"]) for l in lines if l["po_line"] is not None})
    for pl_id, qty in old.items():
        r, a, j = prior.get(pl_id, (ZERO, ZERO, ZERO))
        prior[pl_id] = (r + qty, a + qty, j)
    for l in lines:
        pl = l["po_line"]
        if pl is None:
            continue
        ordered = _ordered_base(db, pl, l["item"])
        if ordered <= 0:
            raise HTTPException(400, "%s: the order's unit %s cannot be converted to %s. Set the conversion in the item settings." % (
                l["label"], pl.uom or "?", base_uom_of(db, l["item"])))
        cap = ordered * (1 + tolerance_of(db, l["item"].id) / 100)
        now = l["received"] - l["rejected"] if l["qc_status"] == "PENDING" else l["accepted"]
        total = prior.get(pl.id, (ZERO, ZERO, ZERO))[1] + now
        if total > cap:
            room = max(ZERO, cap - prior.get(pl.id, (ZERO, ZERO, ZERO))[1])
            raise HTTPException(409, "%s: %s of %s would come to %s, more than the %s ordered%s. At most %s can still be accepted." % (
                l["label"], s3(now), l["item"].item_name, s3(total), s3(ordered), " (with the tolerance %s)" % s3(cap) if cap != ordered else "", s3(room)))


def write_grn_lines(db, grn, lines):
    db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBStoreGrnLine(grn_id=grn.id, line_no=n, po_line_id=l["po_line"].id if l["po_line"] else None, item_id=l["item"].id, entry_uom=l["entry_uom"],
                              entry_qty=l["entry_qty"], received_qty=l["received"], accepted_qty=l["accepted"], rejected_qty=l["rejected"], rate=l["rate"],
                              qc_status=l["qc_status"], reject_reason=l["reject_reason"], batch_no=l["batch_no"], bin_id=l["bin_id"], remarks=l["remarks"],
                              manufacturing_date=l["manufacturing_date"], expiry_date=l["expiry_date"]))
    db.flush()


def grn_lines(db, grn):
    return db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id).order_by(DBStoreGrnLine.line_no, DBStoreGrnLine.id).all()


def grn_check_submit(db, actor, grn):
    lines = grn_lines(db, grn)
    pending = [l for l in lines if l.qc_status == "PENDING"]
    if pending:
        raise HTTPException(409, "%d line%s still need a quality check before the receipt can be submitted." % (len(pending), "" if len(pending) == 1 else "s"))
    _recheck_grn(db, grn, lines)


def _recheck_grn(db, grn, lines):
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn.po_id else None
    if po is not None and po.status not in PO_OPEN:
        raise HTTPException(409, "Purchase order %s is %s, so nothing can be received against it." % (po.number, (po.status or "not approved").lower()))
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in lines])).all()}
    rows = [{"po_line": db.get(models.DBPurchaseOrderLineItem, l.po_line_id) if l.po_line_id else None, "item": items[l.item_id], "received": Decimal(str(l.received_qty)),
             "rejected": Decimal(str(l.rejected_qty)), "accepted": Decimal(str(l.accepted_qty)), "qc_status": l.qc_status, "label": "Line %d" % (l.line_no or 0)} for l in lines]
    check_over_receipt(db, po, rows, exclude_grn=grn.id)


def qc_decide(db, actor, grn, line_id, result, rejected_qty=None, note=""):
    """Record the quality check of one line: PASSED takes in what was received less any rejected; FAILED rejects it all."""
    if grn.status not in (DocStatus.DRAFT.value, DocStatus.SUBMITTED.value):
        raise HTTPException(409, "The quality check can only be recorded before the receipt is approved.")
    line = db.query(DBStoreGrnLine).filter(DBStoreGrnLine.id == line_id, DBStoreGrnLine.grn_id == grn.id).first()
    if line is None:
        raise HTTPException(404, "Receipt line not found")
    if line.qc_status == "NOT_REQUIRED":
        raise HTTPException(409, "That item needs no quality check.")
    result = (result or "").strip().upper()
    if result not in ("PASSED", "FAILED"):
        raise HTTPException(400, "The result is PASSED or FAILED.")
    received = Decimal(str(line.received_qty))
    note = text(note, "note", 200)
    if result == "FAILED":
        if not note:
            raise HTTPException(400, "Say why the check failed.")
        line.accepted_qty, line.rejected_qty, line.reject_reason = ZERO, received, note
    else:
        rej = ZERO
        if (rejected_qty or "").strip() not in ("", "0"):
            rej = to_base(db, line.item_id, dec(rejected_qty, "Rejected quantity"), line.entry_uom or base_uom_of(db, db.get(models.DBItem, line.item_id)))
        if rej > received:
            raise HTTPException(400, "More was rejected than was received.")
        if rej > 0 and not note:
            raise HTTPException(400, "Say why some of it was rejected.")
        line.accepted_qty, line.rejected_qty = received - rej, rej
        line.reject_reason = note if rej > 0 else ""
    line.qc_status, line.qc_by_name, line.qc_note = result, actor.name, note
    log(db, actor, GRN, grn.id, "qc", grn.status, grn.status, "%s line %s: %s" % (result, line.line_no, note))
    db.flush()
    _recheck_grn(db, grn, grn_lines(db, grn))


def grn_post(db, actor, grn):
    lines = grn_lines(db, grn)
    if any(l.qc_status == "PENDING" for l in lines):
        raise HTTPException(409, "A quality check is still pending.")
    _recheck_grn(db, grn, lines)
    project = grn.project_id
    posted = 0
    for l in lines:
        if Decimal(str(l.accepted_qty)) <= 0:
            continue
        post_movement(db, movement_type=MovementType.GRN_IN, store_id=grn.store_id, item_id=l.item_id, qty=l.accepted_qty, rate=l.rate, txn_date=grn.grn_date,
                      project_id=project, ref_doc_type=GRN, ref_doc_id=grn.id, ref_line_id=l.id, user_id=actor.user_id,
                      remarks="%s%s" % (grn.number, (" - " + grn.supplier_name) if grn.supplier_name else ""))
        posted += 1
    if not posted:
        raise HTTPException(409, "Nothing was accepted on this receipt, so there is nothing to post. Cancel it instead.")


# --- gate deliveries ---------------------------------------------------------------------------------------------------
# A lorry of sand or steel arrives after hours with no purchase order raised for it yet. It is unloaded and received on its
# own delivery challan, posted to stock so the site can use it, and linked to the order once purchasing raises one.

def check_gate_delivery(body, po):
    """A gate delivery has no order yet, and carries the challan, vehicle and driver's word it will be matched on later."""
    if po is not None:
        raise HTTPException(400, "A gate delivery is one with no purchase order yet. Choose the order, or leave it out and link it later.")
    missing = [name for name, v in (("challan number", body.challan_no), ("challan date", body.challan_date), ("vehicle number", body.vehicle_no),
                                    ("driver or transporter remarks", body.driver_remarks)) if not (v or "").strip()]
    if missing:
        raise HTTPException(400, "A gate delivery needs its %s." % ", ".join(missing))


def gate_rates(db, client_id, store_id, rows):
    """A rate for each gate-delivery line given none, so the stock has a value until the order settles it: what the store
    holds the item at, or else the rate it is usually bought at. Filled into the rows, per the unit each was counted in."""
    from app.services.store_integration import _per_unit
    for n, r in enumerate(rows, 1):
        if (r.rate or "").strip() or not r.item_id:
            continue
        item = item_of(db, client_id, r.item_id)
        held = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store_id, DBStoreStockBalance.item_id == item.id).first()
        base = Decimal(str(held.avg_rate)) if held is not None and held.qty and held.avg_rate else Decimal(str(item.purchase_rate or 0))
        if base <= 0:
            raise HTTPException(400, "Line %d: give an estimated rate for %s - it has no stock or purchase rate to take one from." % (n, item.item_name))
        per = _per_unit(db, item, (r.uom or "").strip() or base_uom_of(db, item), {}) or Decimal(1)
        r.rate = str(r4(base * per))


def link_gate_delivery(db, actor, grn, po_id, pairs=None):
    """Tie a posted gate delivery to the purchase order raised for it. Each line goes to the order's line for its item (or the
    one chosen in `pairs`, {grn line id: order line id}) and is checked against what was ordered, with the tolerance, as any
    receipt is - from then on the order counts it received and its bill can be matched. The stock keeps the value it came in
    at; the difference from the order's rate is kept on the receipt as its price variance. Returns the variance."""
    if not grn.gate_delivery:
        raise HTTPException(409, "Only a gate delivery is linked to its purchase order afterwards.")
    if grn.po_id:
        po = db.get(models.DBPurchaseOrder, grn.po_id)
        raise HTTPException(409, "%s is already linked to purchase order %s." % (grn.number, po.number if po else grn.po_id))
    if grn.status != DocStatus.POSTED.value:
        raise HTTPException(409, "Post the gate delivery before linking it; a draft is simply given its order when it is edited.")
    po = _po_for(db, actor.client.id, po_id)
    def same(a, b):
        return " ".join((a or "").lower().split()) == " ".join((b or "").lower().split())
    if grn.supplier_name and po.supplier_name and not same(grn.supplier_name, po.supplier_name):
        raise HTTPException(409, "%s was delivered by %s, but purchase order %s is with %s." % (grn.number, grn.supplier_name, po.number, po.supplier_name))
    if grn.project_id and po.job_id and grn.project_id != po.job_id:
        raise HTTPException(409, "%s was received for another project than purchase order %s." % (grn.number, po.number))
    po_lines = db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id).order_by(models.DBPurchaseOrderLineItem.id).all()
    stock_item = {pl.id: po_item(db, po, pl) for pl in po_lines}
    chosen = {int(k): int(v) for k, v in (pairs or {}).items()}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in grn_lines(db, grn)] or [0])).all()}
    rows, used = [], set()
    for l in grn_lines(db, grn):
        label, item = "Line %d" % (l.line_no or 0), items[l.item_id]
        if l.id in chosen:
            pl = next((p for p in po_lines if p.id == chosen[l.id]), None)
            if pl is None:
                raise HTTPException(400, "%s: that is not a line of purchase order %s." % (label, po.number))
            if stock_item.get(pl.id) is None or stock_item[pl.id].id != item.id:
                raise HTTPException(400, "%s: the order line chosen is not for %s." % (label, item.item_name))
        else:
            fits = [p for p in po_lines if stock_item.get(p.id) is not None and stock_item[p.id].id == item.id]
            if not fits:
                raise HTTPException(409, "%s: purchase order %s has no line for %s." % (label, po.number, item.item_name))
            if len(fits) > 1:
                raise HTTPException(409, "%s: purchase order %s has %d lines for %s; choose which one it was." % (label, po.number, len(fits), item.item_name))
            pl = fits[0]
        if pl.id in used:
            raise HTTPException(400, "%s: two lines of the delivery are on the same order line." % label)
        used.add(pl.id)
        rows.append({"po_line": pl, "item": item, "received": Decimal(str(l.received_qty)), "rejected": Decimal(str(l.rejected_qty)),
                     "accepted": Decimal(str(l.accepted_qty)), "qc_status": l.qc_status, "label": label, "line": l})
    check_over_receipt(db, po, rows, exclude_grn=grn.id)
    variance = ZERO
    for r in rows:
        pl, l = r["po_line"], r["line"]
        ordered = _ordered_base(db, pl, r["item"])
        po_rate = Decimal(str(pl.price or 0)) * Decimal(str(pl.qty or 0)) / ordered if ordered > 0 else Decimal(str(l.rate))
        variance += r["accepted"] * (po_rate - Decimal(str(l.rate)))
        l.po_line_id = pl.id
    grn.po_id = po.id
    grn.supplier_name = grn.supplier_name or po.supplier_name or ""
    grn.project_id = grn.project_id or po.job_id
    grn.linked_at, grn.linked_by_name = datetime.now(), actor.name
    grn.price_variance = variance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    log(db, actor, GRN, grn.id, "link", grn.status, grn.status, "to %s; price variance %s" % (po.number, format(grn.price_variance, "f")))
    db.flush()
    return grn.price_variance


def grn_check_cancel(db, grn):
    live = (db.query(DBStorePurchaseReturn.number).filter(DBStorePurchaseReturn.grn_id == grn.id, DBStorePurchaseReturn.status.in_(LIVE)).first())
    if live:
        raise HTTPException(409, "Return %s was made against this receipt. Cancel the return first." % live[0])


# --- purchase returns ---------------------------------------------------------------------------------------------------

def build_return_lines(db, client_id, grn, rows, return_id=None):
    if grn.status != DocStatus.POSTED.value:
        raise HTTPException(409, "Only a posted receipt can have goods returned against it.")
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    glines = {l.id: l for l in grn_lines(db, grn)}
    already = _returned_by_grn_line(db, list(glines), LIVE, exclude_return=return_id)
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        gl = glines.get(r.grn_line_id)
        if gl is None:
            raise HTTPException(400, "%s is not a line of receipt %s." % (label, grn.number))
        if gl.id in seen:
            raise HTTPException(400, "%s: that receipt line is on the return twice." % label)
        seen.add(gl.id)
        item = db.get(models.DBItem, gl.item_id)
        uom = text(r.uom, "unit", 20) or gl.entry_uom or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        qty = to_base(db, gl.item_id, entry, uom)
        room = Decimal(str(gl.accepted_qty)) - already.get(gl.id, ZERO)
        if qty > room:
            raise HTTPException(409, "%s: only %s of %s can still be returned (%s was accepted%s)." % (
                label, s3(max(ZERO, room)), item.item_name, s3(gl.accepted_qty), ", the rest is already on a return" if already.get(gl.id) else ""))
        reason = text(r.reason, "reason", 200)
        out.append({"gl": gl, "item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": qty, "reason": reason})
    return out


def write_return_lines(db, ret, lines):
    db.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id == ret.id).delete(synchronize_session=False)
    for l in lines:
        db.add(DBStorePurchaseReturnLine(return_id=ret.id, grn_line_id=l["gl"].id, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], reason=l["reason"]))
    db.flush()


def return_lines(db, ret):
    return db.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id == ret.id).order_by(DBStorePurchaseReturnLine.id).all()


def return_check_submit(db, actor, ret):
    grn = db.get(DBStoreGrn, ret.grn_id)
    rows = return_lines(db, ret)

    class _R:                                         # the same check the draft went through, on what is stored
        def __init__(self, l):
            self.grn_line_id, self.qty, self.uom, self.reason = l.grn_line_id, str(l.entry_qty), l.entry_uom, l.reason
    build_return_lines(db, ret.client_id, grn, [_R(l) for l in rows], return_id=ret.id)


def return_post(db, actor, ret):
    return_check_submit(db, actor, ret)
    grn = db.get(DBStoreGrn, ret.grn_id)
    for l in return_lines(db, ret):
        post_movement(db, movement_type=MovementType.PURCHASE_RETURN_OUT, store_id=ret.store_id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=ret.return_date,
                      project_id=grn.project_id, ref_doc_type=PURCHASE_RETURN, ref_doc_id=ret.id, ref_line_id=l.id, user_id=actor.user_id,
                      remarks="%s - against %s" % (ret.number, grn.number))


# --- client supply ----------------------------------------------------------------------------------------------------

def build_supply_lines(db, client_id, rows):
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        if item.id in seen:
            raise HTTPException(400, "%s: %s is on the receipt twice." % (label, item.item_name))
        seen.add(item.id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        qty = to_base(db, item.id, entry, uom)
        rate = r4(dec(r.rate, label + " rate") * entry / qty) if (r.rate or "").strip() else ZERO     # the client's own value, if it gives one
        out.append({"item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": qty, "rate": rate, "remarks": text(r.remarks, "remarks", 200)})
    return out


def write_supply_lines(db, doc, lines):
    db.query(DBStoreClientSupplyLine).filter(DBStoreClientSupplyLine.supply_id == doc.id).delete(synchronize_session=False)
    for l in lines:
        db.add(DBStoreClientSupplyLine(supply_id=doc.id, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], rate=l["rate"], remarks=l["remarks"]))
    db.flush()


def supply_lines(db, doc):
    return db.query(DBStoreClientSupplyLine).filter(DBStoreClientSupplyLine.supply_id == doc.id).order_by(DBStoreClientSupplyLine.id).all()


def supply_post(db, actor, doc):
    for l in supply_lines(db, doc):
        post_movement(db, movement_type=MovementType.CLIENT_SUPPLY_IN, store_id=doc.store_id, item_id=l.item_id, qty=l.qty, rate=l.rate, txn_date=doc.supply_date,
                      project_id=doc.project_id, work_order_id=doc.work_order_id, ref_doc_type=CLIENT_SUPPLY, ref_doc_id=doc.id, ref_line_id=l.id,
                      user_id=actor.user_id, remarks="%s%s" % (doc.number, (" - " + doc.client_ref) if doc.client_ref else ""))


# --- opening stock ----------------------------------------------------------------------------------------------------

def build_opening_lines(db, client_id, rows):
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        if item.id in seen:
            raise HTTPException(400, "%s: %s is on the sheet twice." % (label, item.item_name))
        seen.add(item.id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        qty = to_base(db, item.id, entry, uom)
        out.append({"item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": qty, "rate": r4(dec(r.rate, label + " rate") * entry / qty)})
    return out


def write_opening_lines(db, doc, lines):
    db.query(DBStoreOpeningLine).filter(DBStoreOpeningLine.opening_id == doc.id).delete(synchronize_session=False)
    for l in lines:
        db.add(DBStoreOpeningLine(opening_id=doc.id, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], rate=l["rate"]))
    db.flush()


def opening_lines(db, doc):
    return db.query(DBStoreOpeningLine).filter(DBStoreOpeningLine.opening_id == doc.id).order_by(DBStoreOpeningLine.id).all()


def opening_post(db, actor, doc):
    for l in opening_lines(db, doc):
        post_movement(db, movement_type=MovementType.OPENING_IN, store_id=doc.store_id, item_id=l.item_id, qty=l.qty, rate=l.rate, txn_date=doc.as_on_date,
                      project_id=None, ref_doc_type=OPENING, ref_doc_id=doc.id, ref_line_id=l.id, user_id=actor.user_id, remarks=doc.number)


# --- the lifecycle ----------------------------------------------------------------------------------------------------

STEPS = {"submit": (DocStatus.DRAFT, DocStatus.SUBMITTED), "approve": (DocStatus.SUBMITTED, DocStatus.APPROVED), "post": (DocStatus.APPROVED, DocStatus.POSTED)}


def advance(db, actor, kind, doc, action, reason=""):
    """Move a document one step: submit, approve, post, or cancel (with a reason). Posting and cancelling a posted document
    move stock, so the caller wraps this in store_errors() and commits once; on any error it rolls back."""
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
            reverse_document(db, ref_doc_type=kind.ref, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
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


class Kind:
    """What differs between the four inward documents; the lifecycle and the routes are the same for all."""

    def __init__(self, key, ref, label, header, line, fk, date_attr, count_lines, post, check_submit=None, check_cancel=None):
        self.key, self.ref, self.label, self.header, self.line, self.fk, self.date_attr = key, ref, label, header, line, fk, date_attr
        self.count_lines, self.post, self.check_submit, self.check_cancel = count_lines, post, check_submit, check_cancel


KINDS = {
    "grn": Kind("grn", GRN, "Goods receipt", DBStoreGrn, DBStoreGrnLine, "grn_id", "grn_date", lambda db, d: len(grn_lines(db, d)), grn_post, grn_check_submit, lambda db, d: grn_check_cancel(db, d)),
    "returns": Kind("returns", PURCHASE_RETURN, "Purchase return", DBStorePurchaseReturn, DBStorePurchaseReturnLine, "return_id", "return_date",
                    lambda db, d: len(return_lines(db, d)), return_post, return_check_submit),
    "client-supply": Kind("client-supply", CLIENT_SUPPLY, "Client supply", DBStoreClientSupply, DBStoreClientSupplyLine, "supply_id", "supply_date",
                          lambda db, d: len(supply_lines(db, d)), supply_post),
    "opening": Kind("opening", OPENING, "Opening stock", DBStoreOpening, DBStoreOpeningLine, "opening_id", "as_on_date", lambda db, d: len(opening_lines(db, d)), opening_post),
}


def store_of(db, client_id, store_id) -> DBStore:
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != client_id:
        raise HTTPException(400, "That store does not exist.")
    if not store.is_active:
        raise HTTPException(409, "Store %s is not in use." % store.code)
    return store
