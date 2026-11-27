"""The only place stock moves. Every slice posts through post_movement and undoes through reverse_document.

Moving weighted average, per store and item:
  IN   qty x rate is added; the average becomes value / qty.
  OUT  is valued at the average of the moment (rate must be left None); the average does not change. Taking the whole
       balance out takes its whole value, so rounding never leaves a residue behind a zero quantity. A purchase return is
       the one exception: given the rate it was received at, it goes back at that rate, so what stays is worth what it cost.
Stock never goes negative. Beside each store's total the ledger keeps what it holds of each lot (batch) of an item, and
records on every entry which lots it moved; the lots always add up to the total.
A frozen store (a stock count is on) still takes in deliveries - receipts, transfers, returns - but nothing leaves it and
nothing is reversed. Nothing may be dated on or before the day the company's store books are locked up to, nor further back
than the company allows (opening stock excepted). A reversal is dated the day of what it undoes, so a report for any past
day sees both or neither. Nothing here commits: the caller owns the transaction and, when one of these raises, rolls it back.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app import models
from app.core.permissions import permissions_for
from app.models.store_core import (
    IN_MOVEMENTS, NO_BATCH, BatchOnHoldError, CostHead, DBStore, DBStoreBatch, DBStoreBatchBalance, DBStoreBatchHold, DBStoreControlSetting, DBStoreFreeze,
    DBStoreItemSettings, DBStoreLedgerBatch, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion,
    DBStoreUserAssignment, InsufficientStockError, InvalidMovementError, MovementType, StockLedgerEntry, StoreFrozenError,
)

ZERO = Decimal("0")
_QTY, _VALUE, _RATE = Decimal("0.001"), Decimal("0.01"), Decimal("0.0001")
DEFAULT_BACKDATE_DAYS = 30
# What may still come into a store while it is frozen for a count: deliveries from outside it. The count adjusts the books by
# what it found against its snapshot, so what arrives meanwhile (kept apart, not counted) is neither lost nor counted twice.
FREEZE_OPEN = frozenset({MovementType.GRN_IN, MovementType.CLIENT_SUPPLY_IN, MovementType.TRANSFER_IN, MovementType.ISSUE_RETURN_IN,
                         MovementType.SUBCON_RETURN_IN})
RATED_OUT = frozenset({MovementType.PURCHASE_RETURN_OUT})
# Taking stock out for use passes over expired lots while anything else is left; a write-off or a count takes the oldest expiry first.
FOR_USE = frozenset({MovementType.ISSUE_OUT, MovementType.SUBCON_ISSUE_OUT, MovementType.TRANSFER_OUT})
# What a hold stops: going out for use, and being written off. A return to the supplier stays open, or held stock could never
# leave; a count adjustment records what is physically there.
HOLD_BLOCKED = FOR_USE | frozenset({MovementType.SCRAP_OUT, MovementType.WASTAGE_OUT})
HIDDEN_LOT = "~"            # a lot with no printed number (a receipt line that only gave a shelf life) is kept as "~GRN:<line id>"


@dataclass(frozen=True)
class StockBalance:
    qty: Decimal
    value: Decimal
    avg_rate: Decimal


def _dec(x, what="number") -> Decimal:
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        raise InvalidMovementError("%s is not a number: %r" % (what, x)) from None


def _q(x, step) -> Decimal:
    return _dec(x).quantize(step, rounding=ROUND_HALF_UP)


def _as_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise InvalidMovementError("txn_date is not a date: %r" % (x,)) from None


def _store(db, store_id) -> DBStore:
    store = db.get(DBStore, store_id) if store_id else None
    if store is None:
        raise InvalidMovementError("Store %s does not exist." % store_id)
    if not store.is_active:
        raise InvalidMovementError("Store %s (%s) is not active." % (store.code, store.name))
    return store


def is_frozen(db, store_id) -> bool:
    return db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first() is not None


def _assert_not_frozen(db, store_id, mtype=None):
    open_freeze = db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first()
    if open_freeze is not None and mtype not in FREEZE_OPEN:
        raise StoreFrozenError(store_id, open_freeze.reason or "")


# --- the dates the books are open for --------------------------------------------------------------------------------------

def control_setting(db, client_id):
    """The company's store controls: (books_locked_upto or None, max_backdate_days - 0 is no limit)."""
    row = db.query(DBStoreControlSetting).filter(DBStoreControlSetting.client_id == client_id).first()
    if row is None:
        return None, DEFAULT_BACKDATE_DAYS
    return row.books_locked_upto, int(row.max_backdate_days or 0)


def check_date(db, client_id, day, *, backdate=True, today=None):
    """Raise InvalidMovementError when `day` is in the locked period, or (with `backdate`) further back than the company allows."""
    day, today = _as_date(day), today or date.today()
    locked, limit = control_setting(db, client_id)
    if locked is not None and day <= locked:
        raise InvalidMovementError("The store books are closed up to %s, so nothing can be dated %s. Date it later, or ask for the books to be reopened."
                                   % (locked.strftime("%d %b %Y"), day.strftime("%d %b %Y")))
    if backdate and limit > 0 and day < today - timedelta(days=limit):
        raise InvalidMovementError("A store document can be dated at most %d days back (not before %s); %s is earlier."
                                   % (limit, (today - timedelta(days=limit)).strftime("%d %b %Y"), day.strftime("%d %b %Y")))


# --- balances --------------------------------------------------------------------------------------------------------------

def _balance_row(db, store_id, item_id) -> DBStoreStockBalance:
    """The balance row, locked for the rest of the transaction (a no-op on SQLite) and created when it is the first."""
    def find():
        return (db.query(DBStoreStockBalance)
                .filter(DBStoreStockBalance.store_id == store_id, DBStoreStockBalance.item_id == item_id)
                .with_for_update().first())
    row = find()
    if row is None:
        try:
            with db.begin_nested():
                row = DBStoreStockBalance(store_id=store_id, item_id=item_id, qty=ZERO, value=ZERO, avg_rate=ZERO)
                db.add(row)
                db.flush()
        except IntegrityError:        # somebody else made it first
            row = find()
    return row


def get_balance(db, store_id, item_id) -> StockBalance:
    row = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store_id, DBStoreStockBalance.item_id == item_id).first()
    if row is None:
        return StockBalance(ZERO, ZERO, ZERO)
    return StockBalance(_dec(row.qty), _dec(row.value), _dec(row.avg_rate))


# --- lots ------------------------------------------------------------------------------------------------------------------

def lot_label(batch) -> str:
    """The batch number to show: empty for stock with no batch, and for a lot that only has a shelf life."""
    if batch is None or (batch.batch_no or "").startswith(HIDDEN_LOT):
        return ""
    return batch.batch_no


def batch_for(db, client_id, item_id, batch_no, *, manufacturing_date=None, expiry_date=None, received=None, source="") -> int:
    """The lot id for an item's batch number, made the first time it is seen. Dates it did not have are filled in."""
    batch_no = (batch_no or "").strip()
    if not batch_no:
        return NO_BATCH
    row = db.query(DBStoreBatch).filter(DBStoreBatch.client_id == client_id, DBStoreBatch.item_id == item_id, DBStoreBatch.batch_no == batch_no).first()
    if row is None:
        try:
            with db.begin_nested():
                row = DBStoreBatch(client_id=client_id, item_id=item_id, batch_no=batch_no, manufacturing_date=manufacturing_date,
                                   expiry_date=expiry_date, first_received=received, source=(source or "")[:120])
                db.add(row)
                db.flush()
        except IntegrityError:
            row = db.query(DBStoreBatch).filter(DBStoreBatch.client_id == client_id, DBStoreBatch.item_id == item_id, DBStoreBatch.batch_no == batch_no).first()
    else:
        if row.manufacturing_date is None and manufacturing_date is not None:
            row.manufacturing_date = manufacturing_date
        if row.expiry_date is None and expiry_date is not None:
            row.expiry_date = expiry_date
        if row.first_received is None and received is not None:
            row.first_received = received
    return row.id


def grn_line_lot(db, client_id, line, grn) -> int:
    """The lot a goods receipt line brings in: its batch number, or the line itself when it gave only a shelf life."""
    number = (line.batch_no or "").strip()
    if not number and (line.expiry_date or line.manufacturing_date):
        number = "%sGRN:%d" % (HIDDEN_LOT, line.id)
    return batch_for(db, client_id, line.item_id, number, manufacturing_date=line.manufacturing_date, expiry_date=line.expiry_date,
                     received=grn.grn_date, source="Receipt %s" % grn.number)


def entry_lots(db, entry_id):
    """[(lot id, qty)] a ledger entry moved; [] for an entry made before lots were kept."""
    return [(r.batch_id, _dec(r.qty)) for r in db.query(DBStoreLedgerBatch).filter(DBStoreLedgerBatch.ledger_id == entry_id).order_by(DBStoreLedgerBatch.id).all()]


def _lot_rows(db, store_id, item_id):
    return (db.query(DBStoreBatchBalance).filter(DBStoreBatchBalance.store_id == store_id, DBStoreBatchBalance.item_id == item_id)
            .order_by(DBStoreBatchBalance.id).with_for_update().all())


def _lot_row(db, store_id, item_id, batch_id, rows):
    for r in rows:
        if r.batch_id == batch_id:
            return r
    r = DBStoreBatchBalance(store_id=store_id, item_id=item_id, batch_id=batch_id, qty=ZERO)
    db.add(r)
    rows.append(r)
    return r


def _legacy_lots(db, store, item_id, qty):
    """How stock held before lots were kept splits into lots: what is held now is taken to be the latest deliveries (first in,
    first out), each goods receipt line being the lot it recorded. [(lot id, qty)]."""
    from app.models.store_inward import GRN, DBStoreGrn, DBStoreGrnLine
    left, out = qty, []
    rows = (db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id == store.id, DBStoreStockLedger.item_id == item_id,
                                                DBStoreStockLedger.qty_in > 0, DBStoreStockLedger.reversal_of_id.is_(None))
            .order_by(DBStoreStockLedger.txn_date.desc(), DBStoreStockLedger.id.desc()).all())
    undone = {r for (r,) in db.query(DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.store_id == store.id, DBStoreStockLedger.item_id == item_id, DBStoreStockLedger.reversal_of_id.isnot(None)).all()}
    for r in rows:
        if left <= 0:
            break
        if r.id in undone:
            continue
        q = min(_dec(r.qty_in), left)
        lot = NO_BATCH
        if r.ref_doc_type == GRN and r.ref_line_id:
            line = db.get(DBStoreGrnLine, r.ref_line_id)
            grn = db.get(DBStoreGrn, line.grn_id) if line is not None else None
            if line is not None and grn is not None:
                lot = grn_line_lot(db, store.client_id, line, grn)
        out.append((lot, q))
        left -= q
    if left > 0:
        out.append((NO_BATCH, left))
    return out


def _reconcile(db, store, item_id, total, rows):
    """Make the lots add up to the store's total before anything moves. Only stock held from before lots were kept (or a total
    changed by hand) is ever out: the first is split the way it was always shown, the rest is stock with no batch."""
    have = sum((_dec(r.qty) for r in rows), ZERO)
    if have == total:
        return rows
    if not rows and total > 0:
        for lot, q in _legacy_lots(db, store, item_id, total):
            r = _lot_row(db, store.id, item_id, lot, rows)
            r.qty = _dec(r.qty or 0) + q
    elif have < total:
        r = _lot_row(db, store.id, item_id, NO_BATCH, rows)
        r.qty = _dec(r.qty or 0) + (total - have)
    else:
        extra = have - total
        for r in sorted(rows, key=lambda r: r.batch_id != NO_BATCH):
            take = min(_dec(r.qty), extra)
            r.qty, extra = _dec(r.qty) - take, extra - take
            if extra <= 0:
                break
    db.flush()
    return rows


def _pick_order(db, rows, mtype, on_date):
    """The lots to take from when none is named: earliest expiry first, then stock with no expiry, oldest first. Stock taken
    out for use leaves expired lots to the very last."""
    batches = {b.id: b for b in db.query(DBStoreBatch).filter(DBStoreBatch.id.in_([r.batch_id for r in rows if r.batch_id] or [0])).all()}

    def key(r):
        b = batches.get(r.batch_id)
        expiry = b.expiry_date if b is not None else None
        expired = expiry is not None and expiry < on_date
        return (expired if mtype in FOR_USE else False, expiry or date.max, (b.first_received if b is not None else None) or date.min, r.batch_id)
    return sorted(rows, key=key)


def _held_lots(db, rows, mtype):
    """The lots under a quality hold, for stock going out for use. The batch rows are locked and read fresh, so a hold
    committed a moment ago is seen, and one being placed now waits for this movement. Bulk and automatic issues all pass here."""
    ids = sorted({r.batch_id for r in rows if r.batch_id})
    if mtype not in HOLD_BLOCKED or not ids:
        return set()
    return {b.id for b in db.query(DBStoreBatch).filter(DBStoreBatch.id.in_(ids)).order_by(DBStoreBatch.id).populate_existing().with_for_update().all() if b.on_hold or b.lot_status == "REJECTED"}


def hold_refusal(db, batch_id):
    """The refusal for a lot on hold, saying which and why."""
    batch = db.get(DBStoreBatch, batch_id)
    if batch.lot_status == "REJECTED":
        return BatchOnHoldError(lot_label(batch), "Rejected on an NCR", "LOT_REJECTED", "This material lot has been rejected and cannot be issued, transferred, or written off.")
    why = [r for (r,) in db.query(DBStoreBatchHold.reason).filter(DBStoreBatchHold.batch_id == batch_id, DBStoreBatchHold.status == "ACTIVE").all()]
    return BatchOnHoldError(lot_label(batch), "; ".join(x for x in why if x))


def _take_lots(db, store, item_id, mtype, qty, wanted, rows, on_date):
    """Take `qty` out of the lots: the ones named in `wanted` ([(lot id, qty)]), the rest by _pick_order. Returns [(lot id, qty)]."""
    taken = []
    left = qty
    held = _held_lots(db, rows, mtype)
    for lot, q in wanted or []:
        q = left if not q.is_finite() else _q(q, _QTY)       # a lot named alone gives all of it
        if q <= 0:
            continue
        if lot in held:
            raise hold_refusal(db, lot)
        r = _lot_row(db, store.id, item_id, lot, rows)
        if q > _dec(r.qty):
            b = db.get(DBStoreBatch, lot) if lot else None
            raise InsufficientStockError(store.id, item_id, _dec(r.qty), q) if b is None else InvalidMovementError(
                "Only %s of batch %s is on hand in store %s; %s was asked for." % (format(_dec(r.qty).normalize(), "f"), lot_label(b) or b.source or lot,
                                                                                  store.code, format(q.normalize(), "f")))
        r.qty = _dec(r.qty) - q
        taken.append((lot, q))
        left -= q
    if left < 0:
        raise InvalidMovementError("The batches add up to more than the quantity.")
    for r in _pick_order(db, [r for r in rows if _dec(r.qty) > 0 and r.batch_id not in held], mtype, on_date):
        if left <= 0:
            break
        q = min(_dec(r.qty), left)
        r.qty = _dec(r.qty) - q
        taken.append((r.batch_id, q))
        left -= q
    if left > 0 and held:
        raise hold_refusal(db, sorted(held)[0])
    if left > 0:                                 # the total check comes first, so this means the lots were out of step
        raise InsufficientStockError(store.id, item_id, qty - left, qty)
    return taken


def _put_lots(db, store, item_id, qty, wanted, rows):
    """Put `qty` into the lots named in `wanted` ([(lot id, qty)]); whatever they do not cover is stock with no batch."""
    put, left = [], qty
    for lot, q in wanted or []:
        q = left if not q.is_finite() else min(_q(q, _QTY), left)
        if q <= 0:
            continue
        r = _lot_row(db, store.id, item_id, lot, rows)
        r.qty = _dec(r.qty or 0) + q
        put.append((lot, q))
        left -= q
    if left > 0:
        r = _lot_row(db, store.id, item_id, NO_BATCH, rows)
        r.qty = _dec(r.qty or 0) + left
        put.append((NO_BATCH, left))
    return put


def _record_lots(db, entry, moved):
    merged = {}
    for lot, q in moved:
        merged[lot] = merged.get(lot, ZERO) + q
    db.add_all([DBStoreLedgerBatch(ledger_id=entry.id, batch_id=lot, qty=q) for lot, q in merged.items() if q > 0])


def lots_on_hand(db, store_id, item_id):
    """[(DBStoreBatch or None, qty)] a store holds of an item, lots with nothing left left out. Brings old stock into lots first,
    in the caller's transaction (a read that does not commit leaves nothing behind)."""
    store = db.get(DBStore, store_id)
    if store is None:
        return []
    rows = _reconcile(db, store, item_id, get_balance(db, store_id, item_id).qty, _lot_rows(db, store_id, item_id))
    held = [(r.batch_id, _dec(r.qty)) for r in rows if _dec(r.qty) > 0]
    batches = {b.id: b for b in db.query(DBStoreBatch).filter(DBStoreBatch.id.in_([b for b, _q in held if b] or [0])).all()}
    return [(batches.get(b), q) for b, q in held]


# --- moving stock ------------------------------------------------------------------------------------------------------------

def _apply(db, *, store, item_id, mtype, qty, rate, txn_date, user_id, ref_doc_type, ref_doc_id, ref_line_id, project_id,
           work_order_id=None, boq_item_id=None, cost_head=None, subcontractor_id=None, remarks=None, lots=None) -> DBStoreStockLedger:
    """A validated movement -> its ledger row, the new balance and the lots it moved."""
    is_in = mtype in IN_MOVEMENTS
    bal = _balance_row(db, store.id, item_id)
    old_qty, old_value, old_avg = _dec(bal.qty), _dec(bal.value), _dec(bal.avg_rate)
    rows = _reconcile(db, store, item_id, old_qty, _lot_rows(db, store.id, item_id))
    if is_in:
        value = _q(qty * rate, _VALUE)
        new_qty, new_value = old_qty + qty, old_value + value
        avg = _q(new_value / new_qty, _RATE)
        entry_rate = rate
        moved = _put_lots(db, store, item_id, qty, lots, rows)
        _note_restock(db, store, item_id, new_qty)
    else:
        if qty > old_qty:
            raise InsufficientStockError(store.id, item_id, old_qty, qty)
        if qty == old_qty:
            value = old_value
        else:
            value = _q(qty * (rate if rate is not None else old_avg), _VALUE)
            if value >= old_value and rate is not None:      # dearer than all that is left: it goes at the average instead
                value = _q(qty * old_avg, _VALUE)
            if value > old_value:
                raise InvalidMovementError("That would leave store %s with a negative value for item %s." % (store.code, item_id))
        new_qty, new_value = old_qty - qty, old_value - value
        avg = _q(new_value / new_qty, _RATE) if rate is not None and new_qty > 0 else old_avg
        entry_rate = _q(value / qty, _RATE)
        moved = _take_lots(db, store, item_id, mtype, qty, lots, rows, txn_date)
        _note_reorder(db, store, item_id, old_qty, new_qty)
    bal.qty, bal.value, bal.avg_rate = new_qty, new_value, avg
    entry = DBStoreStockLedger(
        txn_date=txn_date, store_id=store.id, item_id=item_id, movement_type=mtype.value,
        qty_in=qty if is_in else ZERO, qty_out=ZERO if is_in else qty, rate=entry_rate, value=value,
        running_qty=new_qty, running_value=new_value, avg_rate=avg,
        project_id=project_id, work_order_id=work_order_id, boq_item_id=boq_item_id,
        cost_head=cost_head.value if cost_head else None, subcontractor_id=subcontractor_id,
        ref_doc_type=ref_doc_type, ref_doc_id=ref_doc_id, ref_line_id=ref_line_id,
        user_id=user_id, remarks=remarks)
    db.add(entry)
    db.flush()
    _record_lots(db, entry, moved)
    db.flush()
    return entry


def _as_lots(lots):
    """`lots` as [(lot id, qty)]: a lot id alone (for an IN, all of it goes there), a list of pairs, or None."""
    if lots is None:
        return None
    if isinstance(lots, int):
        return [(lots, Decimal("Infinity"))]
    return [(int(b), _dec(q, "batch quantity")) for b, q in lots]


def post_movement(db, *, movement_type, store_id, item_id, qty, rate, txn_date, project_id, ref_doc_type, ref_doc_id,
                  ref_line_id, user_id, work_order_id=None, boq_item_id=None, cost_head=None, subcontractor_id=None,
                  remarks=None, lots=None) -> StockLedgerEntry:
    """Record one movement. IN needs `rate`; OUT must pass rate=None (it is valued at the average) - except a purchase return,
    which may give the rate it came in at. `lots` names the batches moved: a lot id, or [(lot id, qty)]; an OUT takes the rest
    earliest expiry first, an IN puts the rest down as stock with no batch. Returns the entry.

    Raises InvalidMovementError, StoreFrozenError, InsufficientStockError. Flushes; never commits."""
    try:
        mtype = MovementType(movement_type)
    except ValueError:
        raise InvalidMovementError("Unknown movement type %r." % (movement_type,)) from None
    qty = _q(qty, _QTY)
    if qty <= 0:
        raise InvalidMovementError("Quantity must be more than zero.")
    if mtype in IN_MOVEMENTS:
        if rate is None:
            raise InvalidMovementError("%s needs a rate." % mtype.value)
        rate = _q(rate, _RATE)
        if rate < 0:
            raise InvalidMovementError("Rate cannot be negative.")
    elif rate is not None:
        if mtype not in RATED_OUT:
            raise InvalidMovementError("%s is valued at the average rate; pass rate=None." % mtype.value)
        rate = _q(rate, _RATE)
        if rate < 0:
            raise InvalidMovementError("Rate cannot be negative.")
    day = _as_date(txn_date)
    if day > date.today():
        raise InvalidMovementError("A movement cannot be dated in the future.")
    if cost_head is not None:
        try:
            cost_head = CostHead(cost_head)
        except ValueError:
            raise InvalidMovementError("Unknown cost head %r." % (cost_head,)) from None
    if not ref_doc_type or ref_doc_id is None:
        raise InvalidMovementError("Every movement names the document that caused it (ref_doc_type, ref_doc_id).")
    store = _store(db, store_id)
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != store.client_id:
        raise InvalidMovementError("Item %s does not exist for this company." % item_id)
    check_date(db, store.client_id, day, backdate=mtype != MovementType.OPENING_IN)
    _assert_not_frozen(db, store.id, mtype)
    return _apply(db, store=store, item_id=item_id, mtype=mtype, qty=qty, rate=rate, txn_date=day, user_id=user_id,
                  ref_doc_type=ref_doc_type, ref_doc_id=ref_doc_id, ref_line_id=ref_line_id, project_id=project_id,
                  work_order_id=work_order_id, boq_item_id=boq_item_id, cost_head=cost_head,
                  subcontractor_id=subcontractor_id, remarks=remarks, lots=_as_lots(lots))


def reverse_document(db, *, ref_doc_type, ref_doc_id, user_id, reason) -> list:
    """Undo every movement a document made that is not already undone, newest first.

    Each is cancelled by an entry of the same movement_type with the quantity in the opposite column and reversal_of_id
    set, dated the day of the entry it undoes - so a report for any past day shows both or neither. An IN comes back out at
    the value it went in at, from the lots it went into; an OUT comes back in at the value it left at, into the lots it left.
    Refused when that day is in the locked period (post a correcting document instead). All or nothing: if one cannot be
    reversed (the stock has since been used) none is."""
    if not (reason or "").strip():
        raise InvalidMovementError("A reason is needed to reverse a document.")
    entries = (db.query(DBStoreStockLedger)
               .filter(DBStoreStockLedger.ref_doc_type == ref_doc_type, DBStoreStockLedger.ref_doc_id == ref_doc_id,
                       DBStoreStockLedger.reversal_of_id.is_(None))
               .order_by(DBStoreStockLedger.id.desc()).all())
    if not entries:
        raise InvalidMovementError("%s %s has posted nothing to reverse." % (ref_doc_type, ref_doc_id))
    done = {r for (r,) in db.query(DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.reversal_of_id.in_([e.id for e in entries])).all()}
    todo = [e for e in entries if e.id not in done]
    if not todo:
        raise InvalidMovementError("%s %s has already been reversed." % (ref_doc_type, ref_doc_id))
    out = []
    with db.begin_nested():
        for e in todo:
            store = db.get(DBStore, e.store_id)
            check_date(db, store.client_id, e.txn_date, backdate=False)
            _assert_not_frozen(db, store.id)
            out.append(_apply_reversal(db, e, store, user_id, reason))
    return out


def _apply_reversal(db, e, store, user_id, reason):
    """The reversing entry for one original: the opposite direction, at the original value, on the original day."""
    mtype, was_in = MovementType(e.movement_type), _dec(e.qty_in) > 0
    qty = _dec(e.qty_in) if was_in else _dec(e.qty_out)
    bal = _balance_row(db, store.id, e.item_id)
    old_qty, old_value = _dec(bal.qty), _dec(bal.value)
    rows = _reconcile(db, store, e.item_id, old_qty, _lot_rows(db, store.id, e.item_id))
    value = _dec(e.value)
    original = entry_lots(db, e.id)
    if was_in:                                  # take it back out
        if qty > old_qty:
            raise InsufficientStockError(store.id, e.item_id, old_qty, qty)
        if qty < old_qty and value > old_value:
            raise InvalidMovementError("Reversing %s %s would leave a negative value." % (e.ref_doc_type, e.ref_doc_id))
        new_qty = old_qty - qty
        taken = old_value if new_qty == 0 else value
        new_value = old_value - taken
        # What is left is worth what is left: undoing a dearer receipt brings the average back down. (Emptied, the
        # last average is kept, as an issue that empties the bin keeps it.)
        avg = _q(new_value / new_qty, _RATE) if new_qty else _dec(bal.avg_rate)
        qty_in, qty_out, value = ZERO, qty, taken
        # From the lots it went into, as far as they still hold it; what has been used of them comes from the others.
        have = {r.batch_id: _dec(r.qty) for r in rows}
        wanted = [(lot, min(q, have.get(lot, ZERO))) for lot, q in original]
        moved = _take_lots(db, store, e.item_id, MovementType.ADJUST_OUT, qty, wanted, rows, e.txn_date)
        _note_reorder(db, store, e.item_id, old_qty, new_qty)
    else:                                       # bring it back in
        new_qty, new_value = old_qty + qty, old_value + value
        avg = _q(new_value / new_qty, _RATE)
        qty_in, qty_out = qty, ZERO
        moved = _put_lots(db, store, e.item_id, qty, original, rows)
        _note_restock(db, store, e.item_id, new_qty)
    bal.qty, bal.value, bal.avg_rate = new_qty, new_value, avg
    entry = DBStoreStockLedger(
        txn_date=e.txn_date, store_id=store.id, item_id=e.item_id, movement_type=mtype.value,
        qty_in=qty_in, qty_out=qty_out, rate=_q(value / qty, _RATE), value=value,
        running_qty=new_qty, running_value=new_value, avg_rate=avg, project_id=e.project_id,
        work_order_id=e.work_order_id, boq_item_id=e.boq_item_id, cost_head=e.cost_head,
        subcontractor_id=e.subcontractor_id, ref_doc_type=e.ref_doc_type, ref_doc_id=e.ref_doc_id,
        ref_line_id=e.ref_line_id, reversal_of_id=e.id, user_id=user_id, remarks="Reversal: " + reason.strip())
    db.add(entry)
    db.flush()
    _record_lots(db, entry, moved)
    db.flush()
    return entry


def convert_to_base(db, item_id, qty, uom_code) -> Decimal:
    """`qty` of an item counted in `uom_code`, as its base unit (3 decimals). The base unit itself is returned as is."""
    qty = _dec(qty, "qty")
    settings = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    item = db.get(models.DBItem, item_id)
    if item is None:
        raise InvalidMovementError("Item %s does not exist." % item_id)
    base = (settings.base_uom if settings else item.units_of_measure) or ""
    code = (uom_code or "").strip()
    if code.lower() == base.strip().lower():
        return _q(qty, _QTY)
    for conv in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item_id).all():
        if conv.from_uom.strip().lower() == code.lower():
            return _q(qty * _dec(conv.to_base_factor), _QTY)
    raise InvalidMovementError("No conversion from %r to %r is set for item %s." % (uom_code, base, item_id))


class BaseUnits:
    """convert_to_base for many items at once: every item's base unit and conversions are read up front, in three queries,
    instead of three for each line converted. The answers are convert_to_base's own - the same unit matching, the same
    rounding, the same refusal for a unit with no conversion. An item not given up front is looked up as before."""

    def __init__(self, db, item_ids):
        self.db = db
        ids = sorted({i for i in item_ids if i})
        self.base, self.convs = {}, {}
        for n in range(0, len(ids), 500):
            chunk = ids[n:n + 500]
            items = dict(db.query(models.DBItem.id, models.DBItem.units_of_measure).filter(models.DBItem.id.in_(chunk)).all())
            settings = {}
            for s in db.query(DBStoreItemSettings.item_id, DBStoreItemSettings.base_uom).filter(DBStoreItemSettings.item_id.in_(chunk)).order_by(DBStoreItemSettings.id).all():
                settings.setdefault(s[0], s)                       # .first(), as convert_to_base reads it
            for iid, uom in items.items():
                s = settings.get(iid)
                self.base[iid] = (s.base_uom if s else uom) or ""
            for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id.in_(chunk)).order_by(DBStoreUomConversion.id).all():
                self.convs.setdefault(c.item_id, []).append((c.from_uom.strip().lower(), c.to_base_factor))
        self.known = set(ids)

    def convert(self, item_id, qty, uom_code) -> Decimal:
        if item_id not in self.known:
            return convert_to_base(self.db, item_id, qty, uom_code)
        qty = _dec(qty, "qty")
        if item_id not in self.base:
            raise InvalidMovementError("Item %s does not exist." % item_id)
        base = self.base[item_id]
        code = (uom_code or "").strip().lower()
        if code == base.strip().lower():
            return _q(qty, _QTY)
        for frm, factor in self.convs.get(item_id, ()):
            if frm == code:
                return _q(qty * _dec(factor), _QTY)
        raise InvalidMovementError("No conversion from %r to %r is set for item %s." % (uom_code, base, item_id))

    def per_unit(self, item_id, uom):
        """How many base units one `uom` is: 1 for the base unit (or no unit), None when there is no conversion - as
        store_integration._per_unit answers it."""
        if item_id not in self.base:
            return None
        code = (uom or "").strip().lower()
        if not code or code == self.base[item_id].strip().lower():
            return Decimal(1)
        factor = next((f for frm, f in self.convs.get(item_id, ()) if frm == code), None)
        return Decimal(str(factor)) if factor else None


def assert_store_access(user, store_id):
    """403 unless `user` may work in the store. `user` is the signed-in DBEmployee or the account holder (DBClient),
    attached to a session. The account holder reaches every store of their company; staff reach the stores they are
    assigned to, and every store with store.admin. Nobody reaches another company's store."""
    db = object_session(user) if user is not None else None
    store = db.get(DBStore, store_id) if db is not None and store_id else None
    if store is None:
        raise HTTPException(404, "Store not found")
    if isinstance(user, models.DBClient):
        allowed = user.id == store.client_id
    elif getattr(user, "client_id", None) != store.client_id:
        allowed = False
    else:
        allowed = "store.admin" in permissions_for(user) or db.query(DBStoreUserAssignment.id).filter(
            DBStoreUserAssignment.store_id == store.id, DBStoreUserAssignment.employee_id == user.id,
            DBStoreUserAssignment.is_active.is_(True)).first() is not None
    if not allowed:
        raise HTTPException(403, "You are not assigned to store %s." % store.code)


def freeze_store(db, store_id, reason, user_id):
    """Stop stock leaving a store (for a stock count); deliveries still come in. One open freeze at a time."""
    store = _store(db, store_id)
    if not (reason or "").strip():
        raise InvalidMovementError("A reason is needed to freeze a store.")
    if is_frozen(db, store.id):
        raise InvalidMovementError("Store %s is already frozen." % store.code)
    freeze = DBStoreFreeze(store_id=store.id, reason=reason.strip(), frozen_by=user_id)
    db.add(freeze)
    db.flush()
    return freeze


def unfreeze_store(db, store_id, user_id):
    freeze = db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first()
    if freeze is None:
        raise InvalidMovementError("Store %s is not frozen." % store_id)
    freeze.unfrozen_at, freeze.unfrozen_by = datetime.now(), user_id
    db.flush()
    return freeze


# --- reorder alerts ------------------------------------------------------------------------------------------------------
# An item is low in a store when what the store can actually give out of it - its AVAILABLE stock - is at or below its reorder level for that
# store (the store's own level where it has set one, else the item's). Available is the stock ledger's balance less what is on quality hold,
# rejected or expired (it cannot be issued) and less what approved indents still have reserved (it is promised): available_map below, the one
# place this is worked out.
#
# One alert per store and item (DBStoreReorderAlert). Its whole life is kept here:
#   low, none open      -> raised (told once: the bell, and email or WhatsApp where the company has asked)
#   low, already open   -> its figures and last-checked time are brought up to date; nothing is told again
#   back above level    -> resolved: when, and what was available then. It is never deleted.
#   low again later     -> the resolved episode goes into the alert's history and the alert is raised afresh
# An indent or enquiry raised for an alert is recorded on it and never resolves it: only the stock recovering does.
#
# Every posting and reversal notes the store and item it touched; once the posting is saved (never if it is rolled back) each is checked
# again, so a receipt, a return, an adjustment or a transfer in resolves the alert straight away. The morning scan
# (accounts_watch.scan_reorder_levels) checks everything again, as a safety net for what changes availability without a posting - a hold
# placed or lifted, an indent approved - and for levels that were changed.

REORDER_KEY = "store_reorder_alerts"


def _level(db, store, item_id):
    from app.services.store_levels import levels_for
    return levels_for(db, store.id, item_id)[0]


def note_stock_check(db, store_id, item_id, client_id=None):
    """Ask for the store's alert on an item to be checked once this transaction is saved."""
    db.info.setdefault(REORDER_KEY, []).append((client_id, store_id, item_id))


def _note_reorder(db, store, item_id, before, after):
    note_stock_check(db, store.id, item_id, store.client_id)


def _note_restock(db, store, item_id, after):
    note_stock_check(db, store.id, item_id, store.client_id)


def available_map(db, store_ids, item_ids=None):
    """{(store_id, item_id): {"on_hand", "unusable", "reserved", "available"}} for what the stores hold, in a few grouped queries.
    unusable = lots on quality hold, rejected for good, or past their expiry date (they cannot be issued); reserved = what approved indents
    still have to be issued (store_reservations). available = on hand - unusable - reserved, never below zero."""
    from app.services.store_reservations import reserved_map
    store_ids = list(store_ids or [])
    if not store_ids:
        return {}
    q = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(store_ids))
    if item_ids is not None:
        q = q.filter(DBStoreStockBalance.item_id.in_(list(item_ids) or [0]))
    held = {(b.store_id, b.item_id): _dec(b.qty or 0) for b in q.all()}
    if not held:
        return {}
    today = date.today()
    q = (db.query(DBStoreBatchBalance.store_id, DBStoreBatchBalance.item_id, DBStoreBatchBalance.qty, DBStoreBatch.on_hold, DBStoreBatch.lot_status, DBStoreBatch.expiry_date)
         .join(DBStoreBatch, DBStoreBatch.id == DBStoreBatchBalance.batch_id)
         .filter(DBStoreBatchBalance.store_id.in_(store_ids), DBStoreBatchBalance.qty > 0))
    if item_ids is not None:
        q = q.filter(DBStoreBatchBalance.item_id.in_(list(item_ids) or [0]))
    unusable = {}
    for s, i, qty, on_hold, lot_status, expiry in q.all():
        if on_hold or lot_status == "REJECTED" or (expiry is not None and expiry < today):
            unusable[(s, i)] = unusable.get((s, i), ZERO) + _dec(qty)
    reserved = reserved_map(db, store_ids, item_ids)
    out = {}
    for key, on_hand in held.items():
        bad = min(on_hand, unusable.get(key, ZERO))
        res = reserved.get(key, ZERO)
        out[key] = {"on_hand": on_hand, "unusable": bad, "reserved": res, "available": max(ZERO, on_hand - bad - res)}
    return out


def reorder_target(level, high):
    """(target level, the words for it) by the store's reorder policy, the one the Reorder report uses: up to the maximum where one is set above
    the reorder level, else to twice the reorder level. (None, why) when there is no reorder level to work from."""
    level, high = _dec(level or 0), _dec(high or 0)
    if level <= 0:
        return None, "No reorder level is set"
    if high > level:
        return high, "Up to the maximum stock level (%s)" % format(_q(high, _QTY).normalize(), "f")
    return level * 2, "Twice the reorder level (no maximum stock level set)"


def reorder_figures(db, store, item_id, figures=None):
    """Everything the alert is decided and kept by, for one store and item: {on_hand, unusable, reserved, available, reorder_level, min_qty,
    max_qty, target, basis, suggested, low}. `figures` is the available_map entry when the caller already has it."""
    from app.services.store_levels import levels_for
    level, low, high = levels_for(db, store.id, item_id)
    f = figures or available_map(db, [store.id], [item_id]).get((store.id, item_id)) or {"on_hand": ZERO, "unusable": ZERO, "reserved": ZERO, "available": ZERO}
    target, basis = reorder_target(level, high)
    suggested = _q(max(ZERO, target - f["available"]), _QTY) if target is not None else None
    return {**f, "reorder_level": level, "min_qty": low, "max_qty": high, "target": target, "basis": basis, "suggested": suggested,
            "low": level > 0 and f["available"] <= level}


def _history(row):
    import json
    try:
        got = json.loads(row.history or "[]")
        return got if isinstance(got, list) else []
    except ValueError:
        return []


def _stamp(d):
    return d.isoformat(timespec="seconds") if d else ""


def _num(x):
    return format(_q(_dec(x), _QTY), "f") if x is not None else None


def _set_figures(row, fig, now):
    row.on_hand, row.available, row.reorder_level = _q(fig["on_hand"], _QTY), _q(fig["available"], _QTY), _q(fig["reorder_level"], _QTY)
    row.target_level = _q(fig["target"], _QTY) if fig["target"] is not None else None
    row.suggested_qty, row.suggest_basis, row.last_checked_at = fig["suggested"], fig["basis"], now


def _alert_row(s, store_id, item_id, lock=False):
    from app.models.store_extras import DBStoreReorderAlert
    q = s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.store_id == store_id, DBStoreReorderAlert.item_id == item_id)
    return (q.with_for_update() if lock else q).first()


def raise_reorder_alert(s, client_id, store, item, left, level, figures=None):
    """Open the store's alert on the item, or bring the open one up to date. Returns whether it was raised now (and told).

    Before, the alert was a bare flag: raised once and never touched again while open, so it held nothing a person could act on (the
    stock, the level, how much to order), the morning scan only ever raised and never resolved, and reopening wrote over the earlier
    episode. Now an open alert is updated on every check, and reopening keeps the earlier episode in the alert's history."""
    from app.core.notifications import notify
    from app.models.store_extras import REORDER_OPEN, DBStoreReorderAlert
    fig = figures or reorder_figures(s, store, item.id)
    now = datetime.now()
    row = _alert_row(s, store.id, item.id)
    if row is not None and row.cleared_at is None:
        _set_figures(row, fig, now)
        row.status = REORDER_OPEN
        return False
    if row is None:
        row = DBStoreReorderAlert(client_id=client_id, store_id=store.id, item_id=item.id, history="[]", times_raised=1)
        s.add(row)
    else:
        import json
        past = _history(row)
        past.append({"alerted_at": _stamp(row.alerted_at), "resolved_at": _stamp(row.cleared_at), "available": _num(row.available),
                     "reorder_level": _num(row.reorder_level), "suggested_qty": _num(row.suggested_qty), "resolved_qty": _num(row.resolved_qty),
                     "action": row.action or "", "action_ref": row.action_ref or "", "action_qty": _num(row.action_qty), "action_by": row.action_by or "",
                     "action_at": _stamp(row.action_at)})
        row.history = json.dumps(past[-50:])
        row.times_raised = (row.times_raised or 1) + 1
        row.cleared_at, row.resolved_qty = None, None
        row.action, row.action_doc_id, row.action_ref, row.action_qty, row.action_by, row.action_at, row.action_key = "", None, "", None, "", None, ""
    row.alerted_at, row.status, row.project_id = now, REORDER_OPEN, store.project_id
    _set_figures(row, fig, now)
    settings = s.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    unit = (settings.base_uom if settings else item.units_of_measure) or ""
    shown = fig["available"] if figures is not None or left is None else _dec(left)
    notify(s, client_id, "store_reorder", "%s is at its reorder level in %s" % (item.item_name, store.code),
           "%s %s left to issue in %s - %s; the reorder level is %s.%s Raise an indent or enquiry for it from the Low Stock list."
           % (format(_q(shown, _QTY).normalize(), "f"), unit, store.code, store.name, format(_q(fig["reorder_level"] or level, _QTY).normalize(), "f"),
              (" Suggested reorder: %s %s." % (format(fig["suggested"].normalize(), "f"), unit)) if fig["suggested"] else ""),
           view="reorder-view", ref_type="store_item", ref_id=item.id, severity="action")
    return True


def resolve_reorder_alert(row, fig=None):
    """The stock is back above the level: the alert is resolved, with when and what was available. Kept, never deleted."""
    from app.models.store_extras import REORDER_RESOLVED
    now = datetime.now()
    if fig is not None:
        _set_figures(row, fig, now)
    row.cleared_at, row.status = now, REORDER_RESOLVED
    row.resolved_qty = _q(fig["available"], _QTY) if fig is not None else row.available
    return row


def check_reorder(s, client_id, store, item_id, figures=None):
    """Check one store's item now and raise, update or resolve its alert to match. Returns "raised" | "updated" | "resolved" | ""."""
    fig = reorder_figures(s, store, item_id, figures)
    row = _alert_row(s, store.id, item_id)
    if fig["low"]:
        item = s.get(models.DBItem, item_id)
        if item is None:
            return ""
        return "raised" if raise_reorder_alert(s, client_id, store, item, None, fig["reorder_level"], fig) else "updated"
    if row is not None and row.cleared_at is None:
        resolve_reorder_alert(row, fig)
        return "resolved"
    return ""


def _send_reorder_alerts(session):
    pending = session.info.pop(REORDER_KEY, None)
    if not pending:
        return
    from app.db.session import SessionLocal
    with SessionLocal() as s:
        for client_id, store_id, item_id in dict.fromkeys(pending):
            store = s.get(DBStore, store_id)
            if store is None:
                continue
            # Nothing to do for an item with no level here and no alert open: most postings stop at this one look.
            if _level(s, store, item_id) <= 0 and not s.query(_alert_model().id).filter(_alert_model().store_id == store_id, _alert_model().item_id == item_id,
                                                                                    _alert_model().cleared_at.is_(None)).first():
                continue
            check_reorder(s, client_id or store.client_id, store, item_id)
            s.flush()
        s.commit()


def _alert_model():
    from app.models.store_extras import DBStoreReorderAlert
    return DBStoreReorderAlert


def _drop_reorder_alerts(session):
    session.info.pop(REORDER_KEY, None)


event.listen(Session, "after_commit", _send_reorder_alerts)
event.listen(Session, "after_rollback", _drop_reorder_alerts)
