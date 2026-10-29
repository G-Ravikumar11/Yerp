"""Store module - control slice: transfers between stores (with their time in transit), stock counts and the adjustments they lead to, and
wastage and scrap. Owned by P4.

Three documents run DRAFT -> SUBMITTED -> APPROVED -> POSTED (or CANCELLED). Only POSTED moves stock; a POSTED document is immutable - cancel
it (which reverses its movements) and make a new one.

* A **transfer** is POSTED when it is dispatched: stock leaves the source at the average rate and is in transit. Receiving it at the
  destination (a second step) brings the stock in at that rate. Cancelling reverses whatever has moved, which fails if the destination has
  already used the stock.
* A **stock count** freezes the store when it is started: nothing leaves it, but deliveries (receipts, transfers in, returns from site) still
  come in and are kept apart from the count. Posting adjusts the books by what the count found against the snapshot, then unfreezes.
* **Wastage and scrap** write stock off at the average rate; scrap can record what it fetched.
Quantities are in the item's base unit. A high-value document needs store.control.approve_high_value to approve.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import (
    CostHead, DBStore, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DocStatus, InvalidMovementError, MovementType,
)
from app.models.store_control import (
    COUNT, SCRAP, TRANSFER, WASTAGE, DBStoreControlLog, DBStoreCount, DBStoreCountLine, DBStoreScrap, DBStoreScrapLine, DBStoreTransfer, DBStoreTransferLine,
)
from app.schemas.store_contracts import CountVarianceLine, InTransitLine, ScrapLine
from app.services import store_cycle, store_outward, store_reservations
from app.core.store_auth import check_not_own
from app.services.stock_ledger import check_date, convert_to_base, entry_lots, freeze_store, get_balance, post_movement, reverse_document, unfreeze_store
from app.services.store_numbering import next_doc_number

from app.services.store_common import (  # noqa: F401  (the routers and documents call svc.dec, svc.day and the rest)
    _Q, _R, _V, dec, day, q3, r4, s2, s3, s4, text, v2,
)

ZERO = Decimal("0")
HIGH_VALUE = Decimal("50000")           # at or above this, approving needs store.control.approve_high_value
LIVE = (DocStatus.SUBMITTED.value, DocStatus.APPROVED.value, DocStatus.POSTED.value)


# --- small helpers --------------------------------------------------------------------------------------------------

def item_of(db, client_id, item_id) -> models.DBItem:
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id or item.kind != "RM":
        raise HTTPException(400, "That item is not a stock item of this company.")
    return item


def to_base(db, item_id, qty: Decimal, uom: str, *, allow_zero=False) -> Decimal:
    try:
        base = convert_to_base(db, item_id, qty, uom)
    except InvalidMovementError as exc:
        raise HTTPException(400, str(exc)) from exc
    if base <= 0 and not (allow_zero and qty == 0):
        raise HTTPException(400, "That quantity is too small to count: it comes to nothing in the base unit.")
    return base


def base_uom_of(db, item) -> str:
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    return ((s.base_uom if s else item.units_of_measure) or "").strip()


def log(db, actor, doc_type, doc_id, action, before="", after="", note=""):
    db.add(DBStoreControlLog(client_id=actor.client.id, doc_type=doc_type, doc_id=doc_id, action=action, from_status=before, to_status=after,
                             user_id=actor.user_id, user_name=actor.name, note=(note or "")[:300]))


def numbered(db, doc_type, store_id, on_date) -> str:
    return next_doc_number(db, doc_type, store_id, on_date=on_date)


def store_of(db, client_id, store_id, what="store") -> DBStore:
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != client_id:
        raise HTTPException(400, "That %s does not exist." % what)
    if not store.is_active:
        raise HTTPException(409, "Store %s is not in use." % store.code)
    return store


def avg_value(db, store_id, item_id, qty: Decimal) -> Decimal:
    """What `qty` of an item is worth in a store at its current average rate."""
    return v2(qty * get_balance(db, store_id, item_id).avg_rate)


def check_stock(db, store_id, wants, on_hand=True):
    """`wants` is [(item_id, qty)]: every item must be on hand in the store and not promised to an approved indent (lines of the same item add up)."""
    want = {}
    for item_id, qty in wants:
        want[item_id] = want.get(item_id, ZERO) + Decimal(str(qty))
    held = store_reservations.reserved_map(db, [store_id], list(want), None)
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


# --- transfers ----------------------------------------------------------------------------------------------------------

def build_transfer_lines(db, client_id, rows):
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        if item.id in seen:
            raise HTTPException(400, "%s: %s is on the transfer twice." % (label, item.item_name))
        seen.add(item.id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        out.append({"item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": to_base(db, item.id, entry, uom), "remarks": text(r.remarks, "remarks", 200)})
    return out


def write_transfer_lines(db, doc, lines):
    db.query(DBStoreTransferLine).filter(DBStoreTransferLine.transfer_id == doc.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBStoreTransferLine(transfer_id=doc.id, line_no=n, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], remarks=l["remarks"]))
    db.flush()


def transfer_lines(db, doc):
    return db.query(DBStoreTransferLine).filter(DBStoreTransferLine.transfer_id == doc.id).order_by(DBStoreTransferLine.line_no, DBStoreTransferLine.id).all()


def is_inter_project(db, from_id, to_id) -> bool:
    a, b = db.get(DBStore, from_id), db.get(DBStore, to_id)
    return (a.project_id or 0) != (b.project_id or 0)


def transfer_value(db, doc) -> Decimal:
    """What the transfer is worth: its dispatched value once it has left, else at the source's average rates now."""
    lines = transfer_lines(db, doc)
    if doc.receipt_status:
        return sum((Decimal(str(l.value)) for l in lines), ZERO)
    return sum((avg_value(db, doc.store_id, l.item_id, Decimal(str(l.qty))) for l in lines), ZERO)


def transfer_check_submit(db, actor, doc):
    check_stock(db, doc.store_id, [(l.item_id, l.qty) for l in transfer_lines(db, doc)])


def transfer_post(db, actor, doc):
    """Dispatch: the stock leaves the source and is in transit until it is received."""
    src = db.get(DBStore, doc.store_id)
    check_stock(db, doc.store_id, [(l.item_id, l.qty) for l in transfer_lines(db, doc)], on_hand=False)
    for l in transfer_lines(db, doc):
        entry = post_movement(db, movement_type=MovementType.TRANSFER_OUT, store_id=doc.store_id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=doc.transfer_date,
                              project_id=src.project_id, ref_doc_type=TRANSFER, ref_doc_id=doc.id, ref_line_id=l.id, user_id=actor.user_id,
                              remarks="%s to %s" % (doc.number, db.get(DBStore, doc.to_store_id).code))
        l.rate, l.value = entry.rate, entry.value
    doc.receipt_status = "IN_TRANSIT"
    doc.inter_project = 1 if is_inter_project(db, doc.store_id, doc.to_store_id) else 0
    db.flush()


def transfer_receive(db, actor, doc):
    """Receipt at the destination: the stock comes in at the rate it left at."""
    if doc.status != DocStatus.POSTED.value or doc.receipt_status != "IN_TRANSIT":
        raise HTTPException(409, "Only a dispatched transfer that is still in transit can be received.")
    dest = db.get(DBStore, doc.to_store_id)
    if not dest.is_active:
        raise HTTPException(409, "Store %s is not in use." % dest.code)
    for l in transfer_lines(db, doc):
        # The batches arrive as they left, with their shelf life.
        sent = (db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == TRANSFER, DBStoreStockLedger.ref_doc_id == doc.id, DBStoreStockLedger.ref_line_id == l.id,
                                                    DBStoreStockLedger.qty_out > 0, DBStoreStockLedger.reversal_of_id.is_(None)).order_by(DBStoreStockLedger.id).first())
        post_movement(db, movement_type=MovementType.TRANSFER_IN, store_id=doc.to_store_id, item_id=l.item_id, qty=l.qty, rate=l.rate, txn_date=date.today(),
                      project_id=dest.project_id, ref_doc_type=TRANSFER, ref_doc_id=doc.id, ref_line_id=l.id, user_id=actor.user_id,
                      remarks="%s from %s" % (doc.number, db.get(DBStore, doc.store_id).code), lots=(entry_lots(db, sent.id) if sent is not None else None) or None)
    doc.receipt_status, doc.received_at, doc.received_by_name = "RECEIVED", datetime.now(), actor.name
    log(db, actor, TRANSFER, doc.id, "receive", doc.status, doc.status, "received at %s" % dest.code)
    db.flush()


def transfer_cancel_hook(db, doc):
    """Cancelling a dispatched transfer takes back whatever has moved; the document no longer has anything in transit."""
    doc.receipt_status = ""


# --- stock counts -------------------------------------------------------------------------------------------------------

def count_lines(db, doc):
    return db.query(DBStoreCountLine).filter(DBStoreCountLine.count_id == doc.id).order_by(DBStoreCountLine.id).all()


def count_variance(l) -> Decimal:
    return Decimal(str(l.counted_qty)) - Decimal(str(l.system_qty)) if l.counted_qty is not None else ZERO


def count_total_variance_value(lines) -> Decimal:
    """The total size of what the count found, ignoring direction: shortages and surpluses both count."""
    return sum((abs(v2(count_variance(l) * Decimal(str(l.avg_rate)))) for l in lines), ZERO)


def count_scope(db, client_id, doc, item_ids):
    """The items a PARTIAL count covers; checked and stored as empty lines until the count starts."""
    if doc.count_type != "PARTIAL":
        return
    if not item_ids:
        raise HTTPException(400, "Choose the items to count, or make it a full count.")
    seen = set()
    for i in item_ids:
        item = item_of(db, client_id, i)
        if item.id in seen:
            continue
        seen.add(item.id)
        db.add(DBStoreCountLine(count_id=doc.id, item_id=item.id, system_qty=ZERO, avg_rate=ZERO, counted_qty=None, in_snapshot=1))
    db.flush()


def in_transit_to(db, store_id):
    """Transfers dispatched to a store and not yet received: [{id, number, from_store, dispatched_on, value}]. A count started
    meanwhile does not see them - they are received into the store, apart from the count, when they arrive."""
    rows = (db.query(DBStoreTransfer).filter(DBStoreTransfer.to_store_id == store_id, DBStoreTransfer.status == DocStatus.POSTED.value,
                                             DBStoreTransfer.receipt_status == "IN_TRANSIT").order_by(DBStoreTransfer.transfer_date, DBStoreTransfer.id).all())
    out = []
    for t in rows:
        src = db.get(DBStore, t.store_id)
        out.append({"id": t.id, "number": t.number, "from_store": src.code if src else "", "dispatched_on": t.transfer_date.isoformat() if t.transfer_date else "",
                    "value": s2(sum((Decimal(str(l.value or 0)) for l in transfer_lines(db, t)), ZERO))})
    return out


def count_start(db, actor, doc):
    """Freeze the store and take the snapshot of the books that the count will be compared with."""
    if doc.status != DocStatus.DRAFT.value:
        raise HTTPException(409, "A count that is %s cannot be started." % doc.status.lower())
    if doc.started_at is not None:
        raise HTTPException(409, "This count has already been started.")
    if db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id == doc.store_id, DBStoreFreeze.unfrozen_at.is_(None)).first():
        raise HTTPException(409, "The store is already frozen (another count is on). Finish that one first.")
    try:
        freeze = freeze_store(db, doc.store_id, "Stock count %s" % doc.number, actor.user_id)
    except InvalidMovementError as exc:
        raise HTTPException(409, str(exc)) from exc
    doc.freeze_id, doc.started_at, doc.started_by_name = freeze.id, datetime.now(), actor.name
    if doc.count_type == "FULL":
        held = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == doc.store_id, DBStoreStockBalance.qty > 0).all()
        for b in held:
            db.add(DBStoreCountLine(count_id=doc.id, item_id=b.item_id, system_qty=b.qty, avg_rate=b.avg_rate, counted_qty=None, in_snapshot=1))
    else:
        for l in count_lines(db, doc):
            bal = get_balance(db, doc.store_id, l.item_id)
            l.system_qty, l.avg_rate = bal.qty, bal.avg_rate
    db.flush()
    if not count_lines(db, doc):
        raise HTTPException(409, "The store holds nothing to count. Add the items found while counting once it has been started, or cancel.")
    log(db, actor, COUNT, doc.id, "start", doc.status, doc.status, "store frozen")


def count_sheet(db, actor, doc, rows):
    """Record what was counted. An item the books did not have may be added: its rate is what the stock will be valued at."""
    if doc.status != DocStatus.DRAFT.value or doc.started_at is None:
        raise HTTPException(409, "Start the count first; counts can only be entered while it is open.")
    if not rows:
        raise HTTPException(400, "Enter at least one count.")
    lines = {l.item_id: l for l in count_lines(db, doc)}
    seen = set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        item = item_of(db, actor.client.id, r.item_id)
        if item.id in seen:
            raise HTTPException(400, "%s: %s is on the sheet twice." % (label, item.item_name))
        seen.add(item.id)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.counted_qty, label + " counted quantity")
        counted = to_base(db, item.id, entry, uom, allow_zero=True) if entry > 0 else ZERO
        line = lines.get(item.id)
        if line is None:
            if doc.count_type == "PARTIAL":
                raise HTTPException(400, "%s: %s is not part of this count." % (label, item.item_name))
            rate = dec(r.rate or "0", label + " rate")
            if counted > 0 and rate <= 0:
                raise HTTPException(400, "%s: %s is not in the books, so give the rate it is worth." % (label, item.item_name))
            line = DBStoreCountLine(count_id=doc.id, item_id=item.id, system_qty=ZERO, avg_rate=r4(rate), in_snapshot=0)
            db.add(line)
        line.counted_qty = counted
        store_cycle.clear_recount(db, line)
        line.reason = text(r.reason, "reason", 200)        # a reason for each difference is asked for at submit, once everything is counted
    db.flush()


def count_check_submit(db, actor, doc):
    lines = count_lines(db, doc)
    if doc.started_at is None:
        raise HTTPException(409, "Start the count first.")
    missing = [l for l in lines if l.counted_qty is None]
    if missing:
        names = ", ".join(db.get(models.DBItem, l.item_id).item_name for l in missing[:3])
        raise HTTPException(409, "%d item%s still to count (%s%s)." % (len(missing), "" if len(missing) == 1 else "s", names, ", ..." if len(missing) > 3 else ""))
    store_cycle.assert_recounted(db, doc)
    unexplained = [l for l in lines if count_variance(l) != 0 and not (l.reason or "").strip()]
    if unexplained:
        raise HTTPException(409, "Say why %s differs from the books." % db.get(models.DBItem, unexplained[0].item_id).item_name)


def count_post(db, actor, doc):
    """Adjust the books to the count, then let the store move again - all in the posting transaction."""
    freeze = db.get(DBStoreFreeze, doc.freeze_id) if doc.freeze_id else None
    if freeze is None or freeze.unfrozen_at is not None:
        raise HTTPException(409, "The store is no longer frozen for this count, so the books may have moved. Cancel it and count again.")
    lines = count_lines(db, doc)
    for l in lines:
        # Only deliveries can have come in since the snapshot; anything less than it means the books moved some other way.
        if get_balance(db, doc.store_id, l.item_id).qty < Decimal(str(l.system_qty)):
            raise HTTPException(409, "The books changed for %s since the count started. Cancel it and count again." % db.get(models.DBItem, l.item_id).item_name)
    try:
        unfreeze_store(db, doc.store_id, actor.user_id)
    except InvalidMovementError as exc:
        raise HTTPException(409, str(exc)) from exc
    for l in lines:
        var = count_variance(l)
        if var > 0:
            post_movement(db, movement_type=MovementType.ADJUST_IN, store_id=doc.store_id, item_id=l.item_id, qty=var, rate=Decimal(str(l.avg_rate)), txn_date=doc.count_date, project_id=None,
                          ref_doc_type=COUNT, ref_doc_id=doc.id, ref_line_id=l.id, user_id=actor.user_id, remarks="%s: %s" % (doc.number, l.reason or "count surplus"))
        elif var < 0:
            post_movement(db, movement_type=MovementType.ADJUST_OUT, store_id=doc.store_id, item_id=l.item_id, qty=-var, rate=None, txn_date=doc.count_date, project_id=None,
                          ref_doc_type=COUNT, ref_doc_id=doc.id, ref_line_id=l.id, user_id=actor.user_id, remarks="%s: %s" % (doc.number, l.reason or "count shortage"))


def count_check_cancel(db, doc):
    return None


def count_cancel_hook(db, actor, doc):
    """A count that is cancelled before it posts lets the store move again."""
    if doc.status != DocStatus.POSTED.value and doc.freeze_id:
        freeze = db.get(DBStoreFreeze, doc.freeze_id)
        if freeze is not None and freeze.unfrozen_at is None:
            unfreeze_store(db, doc.store_id, actor.user_id)


# --- wastage and scrap ----------------------------------------------------------------------------------------------------

def build_scrap_lines(db, client_id, store_id, rows):
    if not rows:
        raise HTTPException(400, "Add at least one line.")
    open_requests = {w.request_id: w for w in store_outward.list_writeoff_requests(db, "OPEN")}
    out, seen = [], set()
    for n, r in enumerate(rows, 1):
        label = "Line %d" % n
        item = item_of(db, client_id, r.item_id)
        disposal = (r.disposal or "SCRAP").strip().upper()
        if disposal not in ("SCRAP", WASTAGE):
            raise HTTPException(400, "%s: the disposal is SCRAP or WASTAGE." % label)
        uom = text(r.uom, "unit", 20) or base_uom_of(db, item)
        entry = dec(r.qty, label + " quantity", allow_zero=False)
        qty = to_base(db, item.id, entry, uom)
        reason = text(r.reason, "reason", 200, required=True)
        realised = v2(dec(r.realised_value or "0", label + " amount realised")) if disposal == "SCRAP" else ZERO
        if disposal == WASTAGE and (r.realised_value or "").strip() not in ("", "0"):
            raise HTTPException(400, "%s: wastage fetches nothing; record a sale as scrap." % label)
        head = (r.cost_head or "").strip().upper() or None
        if head and head not in {c.value for c in CostHead}:
            raise HTTPException(400, "%s: the cost head must be one of: %s." % (label, ", ".join(c.value for c in CostHead)))
        req_id = r.writeoff_request_id or None
        if req_id:
            req = open_requests.get(req_id)
            if req is None or req.store_id != store_id or req.item_id != item.id:
                raise HTTPException(400, "%s: that write-off request is not open for this item in this store." % label)
            if qty > Decimal(str(req.qty)):
                raise HTTPException(400, "%s: the write-off request is for %s, not %s." % (label, s3(req.qty), s3(qty)))
            if req_id in seen:
                raise HTTPException(400, "%s: that write-off request is on the document twice." % label)
            seen.add(req_id)
        out.append({"item": item, "entry_uom": uom, "entry_qty": q3(entry), "qty": qty, "disposal": disposal, "reason": reason, "realised": realised, "cost_head": head, "req": req_id})
    return out


def write_scrap_lines(db, doc, lines):
    db.query(DBStoreScrapLine).filter(DBStoreScrapLine.scrap_id == doc.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBStoreScrapLine(scrap_id=doc.id, line_no=n, item_id=l["item"].id, entry_uom=l["entry_uom"], entry_qty=l["entry_qty"], qty=l["qty"], disposal=l["disposal"], reason=l["reason"],
                                realised_value=l["realised"], cost_head=l["cost_head"], writeoff_request_id=l["req"]))
    db.flush()


def scrap_lines(db, doc):
    return db.query(DBStoreScrapLine).filter(DBStoreScrapLine.scrap_id == doc.id).order_by(DBStoreScrapLine.line_no, DBStoreScrapLine.id).all()


def scrap_value(db, doc) -> Decimal:
    """What the document writes off at average rates; lines that only deal with a write-off request move no stock and are not counted."""
    return sum((avg_value(db, doc.store_id, l.item_id, Decimal(str(l.qty))) for l in scrap_lines(db, doc) if not l.writeoff_request_id), ZERO)


def scrap_check_submit(db, actor, doc):
    check_stock(db, doc.store_id, [(l.item_id, l.qty) for l in scrap_lines(db, doc) if not l.writeoff_request_id])


def scrap_post(db, actor, doc):
    """Each line writes stock off at the average rate. A line that deals with an outward write-off request moves no stock: the tool or material it
    names was lost after it was issued, so it left the store at the issue; the line only records who dealt with it and closes the request."""
    check_stock(db, doc.store_id, [(l.item_id, l.qty) for l in scrap_lines(db, doc) if not l.writeoff_request_id], on_hand=False)
    for l in scrap_lines(db, doc):
        if l.writeoff_request_id:
            store_outward.close_writeoff_request(db, l.writeoff_request_id, SCRAP, doc.id, actor.user_id)
            continue
        post_movement(db, movement_type=MovementType.SCRAP_OUT if l.disposal == "SCRAP" else MovementType.WASTAGE_OUT, store_id=doc.store_id, item_id=l.item_id, qty=l.qty, rate=None,
                      txn_date=doc.scrap_date, project_id=doc.project_id, cost_head=l.cost_head, ref_doc_type=SCRAP, ref_doc_id=doc.id, ref_line_id=l.id, user_id=actor.user_id,
                      remarks="%s: %s" % (doc.number, l.reason))


def scrap_check_cancel(db, doc):
    if doc.status == DocStatus.POSTED.value and any(l.writeoff_request_id for l in scrap_lines(db, doc)):
        raise HTTPException(409, "This document dealt with a write-off request, which cannot be reopened, so it cannot be cancelled.")


# --- the lifecycle ----------------------------------------------------------------------------------------------------------

STEPS = {"submit": (DocStatus.DRAFT, DocStatus.SUBMITTED), "approve": (DocStatus.SUBMITTED, DocStatus.APPROVED), "post": (DocStatus.APPROVED, DocStatus.POSTED)}


class Kind:
    def __init__(self, key, ref, label, header, line, fk, date_attr, count, post, check_submit=None, check_cancel=None, reverses=None, value=None):
        self.key, self.ref, self.label, self.header, self.line, self.fk, self.date_attr = key, ref, label, header, line, fk, date_attr
        self.count, self.post, self.check_submit, self.check_cancel, self.reverses, self.value = count, post, check_submit, check_cancel, reverses, value


def _count_has_adjustments(db, doc):
    return any(count_variance(l) != 0 for l in count_lines(db, doc))


def _scrap_moved_stock(db, doc):
    return any(not l.writeoff_request_id for l in scrap_lines(db, doc))


KINDS = {
    "transfer": Kind("transfer", TRANSFER, "Transfer", DBStoreTransfer, DBStoreTransferLine, "transfer_id", "transfer_date", lambda db, d: len(transfer_lines(db, d)), transfer_post,
                     transfer_check_submit, None, None, transfer_value),
    "count": Kind("count", COUNT, "Stock count", DBStoreCount, DBStoreCountLine, "count_id", "count_date", lambda db, d: len(count_lines(db, d)), count_post, count_check_submit,
                  count_check_cancel, _count_has_adjustments, lambda db, d: count_total_variance_value(count_lines(db, d))),
    "scrap": Kind("scrap", SCRAP, "Wastage and scrap", DBStoreScrap, DBStoreScrapLine, "scrap_id", "scrap_date", lambda db, d: len(scrap_lines(db, d)), scrap_post, scrap_check_submit,
                  scrap_check_cancel, _scrap_moved_stock, scrap_value),
}


def advance(db, actor, kind, doc, action, reason="", can_high_value=False):
    """Move a document one step: submit, approve, post, or cancel (with a reason). Posting and cancelling a posted document move stock:
    the caller wraps this in store_errors() and commits once, and rolls back on any error."""
    now = doc.status
    if action == "cancel":
        reason = text(reason, "reason", 200)
        if len(reason) < 3:
            raise HTTPException(400, "Say why it is being cancelled.")
        if now == DocStatus.CANCELLED.value:
            raise HTTPException(409, "It is already cancelled.")
        if kind.check_cancel:
            kind.check_cancel(db, doc)
        if kind.key == "count":
            count_cancel_hook(db, actor, doc)
        if now == DocStatus.POSTED.value:
            if kind.reverses is None or kind.reverses(db, doc):
                reverse_document(db, ref_doc_type=kind.ref, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
            if kind.key == "transfer":
                transfer_cancel_hook(db, doc)
        doc.status, doc.cancel_reason = DocStatus.CANCELLED.value, reason
        log(db, actor, kind.ref, doc.id, "cancel", now, doc.status, reason)
        return doc
    if action not in STEPS:
        raise HTTPException(404, "There is no such action.")
    need, to = STEPS[action]
    if now != need.value:
        raise HTTPException(409, "It is %s, so it cannot be %s now." % (now.lower(), {"submit": "submitted", "approve": "approved", "post": "posted"}[action]))
    if action == "submit":
        if not kind.count(db, doc):
            raise HTTPException(400, "Add at least one line before submitting.")
        if kind.check_submit:
            kind.check_submit(db, actor, doc)
    if action in ("submit", "post"):
        try:
            check_date(db, actor.client.id, getattr(doc, kind.date_attr))
        except InvalidMovementError as exc:
            raise HTTPException(400, str(exc)) from exc
    if action == "approve":
        raised = []
        if kind.key == "scrap":                 # nor by whoever asked for the write-offs it settles
            ids = [l.writeoff_request_id for l in scrap_lines(db, doc) if l.writeoff_request_id]
            from app.models.store_outward import DBStoreWriteoffRequest
            raised = [r for (r,) in db.query(DBStoreWriteoffRequest.requested_by_id).filter(DBStoreWriteoffRequest.id.in_(ids or [0])).all()]
        if kind.key == "count" and doc.started_at is not None:
            raised = [h.user_id for h in db.query(DBStoreControlLog).filter(DBStoreControlLog.doc_type == COUNT, DBStoreControlLog.doc_id == doc.id,
                                                                             DBStoreControlLog.action == "start").all()]
        check_not_own(db, actor, doc, DBStoreControlLog, kind.ref, kind.label, also=raised)
    if action == "approve" and kind.value is not None and not can_high_value:
        worth = kind.value(db, doc)
        if worth >= HIGH_VALUE:
            raise HTTPException(403, "This is worth %s, so approving it needs the right to approve high-value documents (from %s)." % (s2(worth), s2(HIGH_VALUE)))
    if action == "post":
        kind.post(db, actor, doc)
        doc.posted_at = datetime.now()
    doc.status = to.value
    log(db, actor, kind.ref, doc.id, action, now, doc.status)
    return doc


# --- what other slices ask for ------------------------------------------------------------------------------------------------

def _as_day(x, default) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except ValueError:
        return default


def get_in_transit(db, project_id=None) -> List[InTransitLine]:
    """Stock sent from one store and not yet received at the other (dispatched transfers, valued at what they left at).
    With a project, the transfers that leave or arrive at one of its stores."""
    q = (db.query(DBStoreTransferLine, DBStoreTransfer).join(DBStoreTransfer, DBStoreTransfer.id == DBStoreTransferLine.transfer_id)
         .filter(DBStoreTransfer.status == DocStatus.POSTED.value, DBStoreTransfer.receipt_status == "IN_TRANSIT"))
    if project_id:
        ids = [s for (s,) in db.query(DBStore.id).filter(DBStore.project_id == project_id).all()] or [0]
        q = q.filter((DBStoreTransfer.store_id.in_(ids)) | (DBStoreTransfer.to_store_id.in_(ids)))
    out = []
    for l, t in q.order_by(DBStoreTransfer.transfer_date, DBStoreTransferLine.id).all():
        out.append(InTransitLine(transfer_id=t.id, from_store_id=t.store_id, to_store_id=t.to_store_id, item_id=l.item_id, qty=q3(l.qty), value=v2(l.value or 0),
                                 dispatched_on=t.transfer_date, inter_project=bool(t.inter_project)))
    return out


def get_count_variances(db, store_id, from_date, to_date) -> List[CountVarianceLine]:
    """What stock counts found against the books at a store, between two dates (posted counts, by count date). Variance is counted less
    system, so a shortage is negative; its value is at the average rate when the count started."""
    lo, hi = _as_day(from_date, date.min), _as_day(to_date, date.max)
    rows = (db.query(DBStoreCountLine, DBStoreCount).join(DBStoreCount, DBStoreCount.id == DBStoreCountLine.count_id)
            .filter(DBStoreCount.store_id == store_id, DBStoreCount.status == DocStatus.POSTED.value, DBStoreCount.count_date >= lo, DBStoreCount.count_date <= hi)
            .order_by(DBStoreCount.count_date, DBStoreCountLine.id).all())
    out = []
    for l, c in rows:
        var = count_variance(l)
        out.append(CountVarianceLine(count_id=c.id, item_id=l.item_id, system_qty=q3(l.system_qty), counted_qty=q3(l.counted_qty or 0), variance_qty=q3(var),
                                     variance_value=v2(var * Decimal(str(l.avg_rate)))))
    return out


def get_scrap_realisation(db, project_id, from_date, to_date) -> List[ScrapLine]:
    """Scrap sold or written off for a project: book value (what the ledger took it out at) against what it fetched. Posted scrap lines only."""
    lo, hi = _as_day(from_date, date.min), _as_day(to_date, date.max)
    q = (db.query(DBStoreScrapLine, DBStoreScrap).join(DBStoreScrap, DBStoreScrap.id == DBStoreScrapLine.scrap_id)
         .filter(DBStoreScrap.status == DocStatus.POSTED.value, DBStoreScrapLine.disposal == "SCRAP", DBStoreScrap.scrap_date >= lo, DBStoreScrap.scrap_date <= hi))
    if project_id:
        q = q.filter(DBStoreScrap.project_id == project_id)
    rows = q.order_by(DBStoreScrap.scrap_date, DBStoreScrapLine.id).all()
    values = {r: Decimal(str(v)) for r, v in db.query(DBStoreStockLedger.ref_line_id, func.sum(DBStoreStockLedger.value)).filter(
        DBStoreStockLedger.ref_doc_type == SCRAP, DBStoreStockLedger.reversal_of_id.is_(None), DBStoreStockLedger.ref_line_id.in_([l.id for l, _s in rows] or [0])).group_by(DBStoreStockLedger.ref_line_id).all()}
    return [ScrapLine(scrap_doc_id=s.id, item_id=l.item_id, qty=q3(l.qty), book_value=v2(values.get(l.id, ZERO)), realised_value=v2(l.realised_value or 0)) for l, s in rows]
