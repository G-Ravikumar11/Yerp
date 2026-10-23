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
    IN_MOVEMENTS, NO_BATCH, CostHead, DBStore, DBStoreBatch, DBStoreBatchBalance, DBStoreControlSetting, DBStoreFreeze,
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


def date_problem(db, client_id, day, *, backdate=True) -> str:
    """check_date as a message ('' when the date is fine), for screens that warn before anything is posted."""
    try:
        check_date(db, client_id, day, backdate=backdate)
    except InvalidMovementError as exc:
        return str(exc)
    return ""


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


def _take_lots(db, store, item_id, mtype, qty, wanted, rows, on_date):
    """Take `qty` out of the lots: the ones named in `wanted` ([(lot id, qty)]), the rest by _pick_order. Returns [(lot id, qty)]."""
    taken = []
    left = qty
    for lot, q in wanted or []:
        q = left if not q.is_finite() else _q(q, _QTY)       # a lot named alone gives all of it
        if q <= 0:
            continue
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
    for r in _pick_order(db, [r for r in rows if _dec(r.qty) > 0], mtype, on_date):
        if left <= 0:
            break
        q = min(_dec(r.qty), left)
        r.qty = _dec(r.qty) - q
        taken.append((r.batch_id, q))
        left -= q
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


def lot_split(db, store_id, item_id, qty, mtype=MovementType.ISSUE_OUT, on_date=None):
    """[(DBStoreBatch or None, qty)] that taking `qty` out the usual way would take, without taking it."""
    held = lots_on_hand(db, store_id, item_id)            # brings old stock into lots
    order = _pick_order(db, [r for r in _lot_rows(db, store_id, item_id) if _dec(r.qty) > 0], mtype, on_date or date.today()) if held else []
    out, left = [], _dec(qty)
    for r in order:
        if left <= 0:
            break
        q = min(_dec(r.qty), left)
        out.append((db.get(DBStoreBatch, r.batch_id) if r.batch_id else None, q))
        left -= q
    return out


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
# Stock that goes out and takes a store down to an item's reorder level puts an alert on the dashboard (the bell, and email
# or WhatsApp where the company has asked for them) - once, as it crosses the level, not on every issue below it. The
# ledger never commits, and an alert is saved and sent on its own, so it is only noted here and goes out once the posting
# itself is saved; a posting rolled back sends nothing.

REORDER_KEY = "store_reorder_alerts"


def _note_reorder(db, store, item_id, before, after):
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    level = _dec(s.reorder_level) if s is not None and s.reorder_level else ZERO
    if level > 0 and before > level >= after:
        db.info.setdefault(REORDER_KEY, []).append((store.client_id, store.id, item_id, after, level))


def _send_reorder_alerts(session):
    pending = session.info.pop(REORDER_KEY, None)
    if not pending:
        return
    from app.core.notifications import notify
    from app.db.session import SessionLocal
    with SessionLocal() as s:
        for client_id, store_id, item_id, left, level in pending:
            store, item = s.get(DBStore, store_id), s.get(models.DBItem, item_id)
            if store is None or item is None:
                continue
            settings = s.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
            unit = (settings.base_uom if settings else item.units_of_measure) or ""
            notify(s, client_id, "store_reorder", "%s is at its reorder level in %s" % (item.item_name, store.code),
                   "%s %s left in %s - %s; the reorder level is %s. Raise a purchase enquiry for it from the Reorder report."
                   % (format(_q(left, _QTY).normalize(), "f"), unit, store.code, store.name, format(_q(level, _QTY).normalize(), "f")),
                   view="reorder-view", ref_type="store_item", ref_id=item_id, severity="action")


def _drop_reorder_alerts(session):
    session.info.pop(REORDER_KEY, None)


event.listen(Session, "after_commit", _send_reorder_alerts)
event.listen(Session, "after_rollback", _drop_reorder_alerts)
