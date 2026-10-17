"""The only place stock moves. Every slice posts through post_movement and undoes through reverse_document.

Moving weighted average, per store and item:
  IN   qty x rate is added; the average becomes value / qty.
  OUT  is valued at the average of the moment (rate must be left None); the average does not change. Taking the whole
       balance out takes its whole value, so rounding never leaves a residue behind a zero quantity.
Stock never goes negative and a frozen store does not move. Nothing here commits: the caller owns the transaction and,
when one of these raises, rolls it back.

Concurrency. Every movement first locks its store + item balance row and reads it fresh, so two documents posting the
same item at once queue behind each other instead of both spending the same stock. On Postgres the lock is SELECT ...
FOR UPDATE; SQLite ignores FOR UPDATE, so there the lock is taken with a write to the row first (SQLite has one writer
at a time, and a write is what makes a connection that writer). A document posting several items locks them in the
order it posts them; reverse_document locks in store, item order.

Dates. A movement may not be dated before the last movement of the same store and item: the running quantities and
the item card then read the same in date order as in posting order, and nothing is slipped in under a later issue.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app import models
from app.core.permissions import permissions_for
from app.models.store_core import (
    IN_MOVEMENTS, CostHead, DBStore, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance,
    DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, InsufficientStockError, InvalidMovementError,
    MovementType, StockLedgerEntry, StoreFrozenError,
)

ZERO = Decimal("0")
_QTY, _VALUE, _RATE = Decimal("0.001"), Decimal("0.01"), Decimal("0.0001")
# What a count may still post while its own freeze holds the store.
_COUNT_MOVEMENTS = frozenset({MovementType.ADJUST_IN, MovementType.ADJUST_OUT})


@dataclass(frozen=True)
class StockBalance:
    qty: Decimal
    value: Decimal
    avg_rate: Decimal


def _dec(x, what="number") -> Decimal:
    if isinstance(x, Decimal):
        out = x
    else:
        if isinstance(x, bool) or x is None:
            raise InvalidMovementError("%s is not a number: %r" % (what, x))
        try:
            out = Decimal(str(x).strip())
        except (InvalidOperation, ValueError):
            raise InvalidMovementError("%s is not a number: %r" % (what, x)) from None
    if not out.is_finite():
        raise InvalidMovementError("%s is not a number: %r" % (what, x))
    return out


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


def _item_label(db, item_id) -> str:
    """How a person knows the item: its code and name."""
    item = db.get(models.DBItem, item_id) if item_id else None
    return ("%s %s" % (item.item_code or "", item.item_name or "")).strip() if item else "item %s" % item_id


def _base_uom(db, item_id) -> str:
    settings = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    if settings and settings.base_uom:
        return settings.base_uom
    item = db.get(models.DBItem, item_id)
    return (item.units_of_measure if item else "") or ""


def _short(store, db, item_id, available, requested, doing="") -> InsufficientStockError:
    """The not-enough-stock error, worded with the item, the store and the unit."""
    uom = _base_uom(db, item_id)
    msg = "%sonly %s %s of %s is on hand in %s (%s); %s %s is needed." % (
        doing, _plain(available), uom, _item_label(db, item_id), store.code, store.name, _plain(requested), uom)
    return InsufficientStockError(store.id, item_id, available, requested, message=msg[0].upper() + msg[1:])


def _plain(x) -> str:
    """12.500 -> 12.5, 40.000 -> 40: quantities as a person writes them."""
    s = format(_dec(x), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _open_freeze(db, store_id):
    return (db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None))
            .order_by(DBStoreFreeze.id.desc()).first())


def is_frozen(db, store_id) -> bool:
    return db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first() is not None


def _assert_not_frozen(db, store_id, mtype=None, ref_doc_type=None, ref_doc_id=None):
    """StoreFrozenError while the store is frozen - except for the ADJUST_IN / ADJUST_OUT of the count the freeze is
    for (freeze_store_for_count), which is how a count books what it found."""
    open_freeze = _open_freeze(db, store_id)
    if open_freeze is None:
        return
    if (mtype in _COUNT_MOVEMENTS and open_freeze.ref_doc_type and ref_doc_type == open_freeze.ref_doc_type
            and ref_doc_id is not None and ref_doc_id == open_freeze.ref_doc_id):
        return
    raise StoreFrozenError(store_id, open_freeze.reason or "")


def _balance_row(db, store_id, item_id) -> DBStoreStockBalance:
    """The balance row, locked for the rest of the transaction and read fresh from the database (not from what this
    session saw earlier), created when it is the first."""
    if db.get_bind().dialect.name == "sqlite":
        # FOR UPDATE means nothing to SQLite. A write does: it makes this connection the database's one writer until
        # the transaction ends, so a second poster waits here and then reads what the first committed.
        db.execute(text("UPDATE store_stock_balance SET qty = qty WHERE store_id = :s AND item_id = :i"),
                   {"s": store_id, "i": item_id})

    def find():
        return (db.query(DBStoreStockBalance)
                .filter(DBStoreStockBalance.store_id == store_id, DBStoreStockBalance.item_id == item_id)
                .populate_existing().with_for_update().first())
    row = find()
    if row is None:
        try:
            with db.begin_nested():
                row = DBStoreStockBalance(store_id=store_id, item_id=item_id, qty=ZERO, value=ZERO, avg_rate=ZERO)
                db.add(row)
                db.flush()
        except IntegrityError:        # somebody else made it first; theirs is now committed and ours is gone
            row = find()
    return row


def _last_date(db, store_id, item_id):
    return db.query(func.max(DBStoreStockLedger.txn_date)).filter(
        DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id).scalar()


def _assert_in_order(db, store, item_id, day):
    last = _last_date(db, store.id, item_id)
    if isinstance(last, str):                 # SQLite hands a bare column back as text in an aggregate
        last = _as_date(last)
    if last is not None and day < last:
        raise InvalidMovementError(
            "%s in %s already has a movement dated %s; a movement cannot be dated before it (%s was given)."
            % (_item_label(db, item_id), store.code, last.isoformat(), day.isoformat()))


def get_balance(db, store_id, item_id) -> StockBalance:
    row = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store_id, DBStoreStockBalance.item_id == item_id).first()
    if row is None:
        return StockBalance(ZERO, ZERO, ZERO)
    return StockBalance(_dec(row.qty), _dec(row.value), _dec(row.avg_rate))


def _apply(db, *, store, item_id, mtype, qty, rate, txn_date, user_id, ref_doc_type, ref_doc_id, ref_line_id, project_id,
           work_order_id=None, boq_item_id=None, cost_head=None, subcontractor_id=None, remarks=None) -> DBStoreStockLedger:
    """A validated movement -> its ledger row and the new balance. The balance is locked before anything is read."""
    is_in = mtype in IN_MOVEMENTS
    bal = _balance_row(db, store.id, item_id)
    # Checked under the lock, so a freeze or a later-dated movement committed a moment ago is seen.
    _assert_not_frozen(db, store.id, mtype, ref_doc_type, ref_doc_id)
    _assert_in_order(db, store, item_id, txn_date)
    old_qty, old_value, old_avg = _dec(bal.qty), _dec(bal.value), _dec(bal.avg_rate)
    if is_in:
        value = _q(qty * rate, _VALUE)
        new_qty, new_value = old_qty + qty, old_value + value
        avg = _q(new_value / new_qty, _RATE)
        entry_rate = rate
    else:
        if qty > old_qty:
            raise _short(store, db, item_id, old_qty, qty)
        if qty == old_qty:
            value = old_value
        else:
            value = _q(qty * old_avg, _VALUE)
            if value > old_value:
                raise InvalidMovementError("That would leave %s in %s with a negative value." % (_item_label(db, item_id), store.code))
        new_qty, new_value, avg = old_qty - qty, old_value - value, old_avg
        entry_rate = _q(value / qty, _RATE)
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
    return entry


def post_movement(db, *, movement_type, store_id, item_id, qty, rate, txn_date, project_id, ref_doc_type, ref_doc_id,
                  ref_line_id, user_id, work_order_id=None, boq_item_id=None, cost_head=None, subcontractor_id=None,
                  remarks=None) -> StockLedgerEntry:
    """Record one movement. IN needs `rate`; OUT must pass rate=None (it is valued at the average). Returns the entry.

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
        raise InvalidMovementError("%s is valued at the average rate; pass rate=None." % mtype.value)
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
    _assert_not_frozen(db, store.id, mtype, ref_doc_type, ref_doc_id)    # fail fast; checked again under the lock
    return _apply(db, store=store, item_id=item_id, mtype=mtype, qty=qty, rate=rate, txn_date=day, user_id=user_id,
                  ref_doc_type=ref_doc_type, ref_doc_id=ref_doc_id, ref_line_id=ref_line_id, project_id=project_id,
                  work_order_id=work_order_id, boq_item_id=boq_item_id, cost_head=cost_head,
                  subcontractor_id=subcontractor_id, remarks=remarks)


def _not_reversed(db, ref_doc_type, ref_doc_id):
    """The document's original movements that no reversal points at yet, newest first."""
    entries = (db.query(DBStoreStockLedger)
               .filter(DBStoreStockLedger.ref_doc_type == ref_doc_type, DBStoreStockLedger.ref_doc_id == ref_doc_id,
                       DBStoreStockLedger.reversal_of_id.is_(None))
               .order_by(DBStoreStockLedger.id.desc()).all())
    if not entries:
        return entries, False
    done = {r for (r,) in db.query(DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.reversal_of_id.in_([e.id for e in entries])).all()}
    return [e for e in entries if e.id not in done], True


def reverse_document(db, *, ref_doc_type, ref_doc_id, user_id, reason) -> list:
    """Undo every movement a document made that is not already undone, newest first.

    Each is cancelled by an entry of the same movement_type with the quantity in the opposite column and
    reversal_of_id set, dated today. An IN comes back out at the rate it went in at, an OUT comes back in at the
    rate it left at. All or nothing: if one cannot be reversed (the stock has since been used) none is."""
    if not (reason or "").strip():
        raise InvalidMovementError("A reason is needed to reverse a document.")
    todo, posted = _not_reversed(db, ref_doc_type, ref_doc_id)
    if not posted:
        raise InvalidMovementError("%s %s has posted nothing to reverse." % (ref_doc_type, ref_doc_id))
    if not todo:
        raise InvalidMovementError("%s %s has already been reversed." % (ref_doc_type, ref_doc_id))
    out = []
    try:
        with db.begin_nested():
            # Lock every balance the document touched, in one fixed order, then look again: another cancel of the
            # same document that got in first has now committed, and its reversals are seen.
            for store_id, item_id in sorted({(e.store_id, e.item_id) for e in todo}):
                _balance_row(db, store_id, item_id)
            todo, _ = _not_reversed(db, ref_doc_type, ref_doc_id)
            if not todo:
                raise InvalidMovementError("%s %s has already been reversed." % (ref_doc_type, ref_doc_id))
            for e in todo:
                store = db.get(DBStore, e.store_id)
                _assert_not_frozen(db, store.id, MovementType(e.movement_type), e.ref_doc_type, e.ref_doc_id)
                out.append(_apply_reversal(db, e, store, user_id, reason))
    except IntegrityError:
        # The unique index on reversal_of_id: somebody reversed one of these between our look and our write.
        raise InvalidMovementError("%s %s has already been reversed." % (ref_doc_type, ref_doc_id)) from None
    return out


def _apply_reversal(db, e, store, user_id, reason):
    """The reversing entry for one original: the opposite direction, at the original rate (so the original value)."""
    mtype, was_in = MovementType(e.movement_type), _dec(e.qty_in) > 0
    qty = _dec(e.qty_in) if was_in else _dec(e.qty_out)
    bal = _balance_row(db, store.id, e.item_id)
    old_qty, old_value, old_avg = _dec(bal.qty), _dec(bal.value), _dec(bal.avg_rate)
    value = _dec(e.value)
    if was_in:                                  # take it back out
        if qty > old_qty:
            raise _short(store, db, e.item_id, old_qty, qty, doing="Cannot reverse %s %s: " % (e.ref_doc_type, e.ref_doc_id))
        new_qty = old_qty - qty
        if new_qty == 0:
            taken = old_value                   # all of it: no residue left behind a zero quantity
        else:
            if value > old_value:
                raise InvalidMovementError(
                    "Cannot reverse %s %s: %s in %s is now worth %s, less than the %s it came in at, so taking it back "
                    "out at its own rate would leave a negative value." % (
                        e.ref_doc_type, e.ref_doc_id, _item_label(db, e.item_id), store.code, old_value, value))
            taken = value
        new_value = old_value - taken
        # What is left is re-averaged: it no longer contains the reversed receipt.
        avg = _q(new_value / new_qty, _RATE) if new_qty else old_avg
        qty_in, qty_out, value = ZERO, qty, taken
    else:                                       # bring it back in
        new_qty, new_value = old_qty + qty, old_value + value
        avg = _q(new_value / new_qty, _RATE)
        qty_in, qty_out = qty, ZERO
    bal.qty, bal.value, bal.avg_rate = new_qty, new_value, avg
    entry = DBStoreStockLedger(
        txn_date=date.today(), store_id=store.id, item_id=e.item_id, movement_type=mtype.value,
        qty_in=qty_in, qty_out=qty_out, rate=_q(value / qty, _RATE), value=value,
        running_qty=new_qty, running_value=new_value, avg_rate=avg, project_id=e.project_id,
        work_order_id=e.work_order_id, boq_item_id=e.boq_item_id, cost_head=e.cost_head,
        subcontractor_id=e.subcontractor_id, ref_doc_type=e.ref_doc_type, ref_doc_id=e.ref_doc_id,
        ref_line_id=e.ref_line_id, reversal_of_id=e.id, user_id=user_id, remarks="Reversal: " + reason.strip())
    db.add(entry)
    db.flush()
    return entry


def ledger_position(db, store_id, item_id) -> StockBalance:
    """What the ledger adds up to for a store and item - quantity and value netted by direction. It must always equal
    get_balance; the enquiry screens and the tests use it to show that it does."""
    qty_in, qty_out, val_in, val_out = db.query(
        func.coalesce(func.sum(DBStoreStockLedger.qty_in), 0), func.coalesce(func.sum(DBStoreStockLedger.qty_out), 0),
        func.coalesce(func.sum(DBStoreStockLedger.value).filter(DBStoreStockLedger.qty_in > 0), 0),
        func.coalesce(func.sum(DBStoreStockLedger.value).filter(DBStoreStockLedger.qty_out > 0), 0),
    ).filter(DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id).one()
    qty, value = _q(qty_in, _QTY) - _q(qty_out, _QTY), _q(val_in, _VALUE) - _q(val_out, _VALUE)
    return StockBalance(qty, value, _q(value / qty, _RATE) if qty else ZERO)


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
    """Stop all movement in a store (for a stock count). One open freeze at a time."""
    store = _store(db, store_id)
    if not (reason or "").strip():
        raise InvalidMovementError("A reason is needed to freeze a store.")
    if is_frozen(db, store.id):
        raise InvalidMovementError("Store %s is already frozen." % store.code)
    freeze = DBStoreFreeze(store_id=store.id, reason=reason.strip(), frozen_by=user_id)
    db.add(freeze)
    db.flush()
    return freeze


def freeze_store_for_count(db, store_id, reason, user_id, *, count_doc_id, count_doc_type="COUNT"):
    """freeze_store for a stock count: the same freeze, naming the count, so that the count's own ADJUST_IN /
    ADJUST_OUT (ref_doc_type `count_doc_type`, ref_doc_id `count_doc_id`) post - and reverse - while everything else
    in the store is held. Added in store_002_foundation; freeze_store itself is unchanged."""
    if count_doc_id is None or not count_doc_type:
        raise InvalidMovementError("A count freeze names its count (count_doc_type, count_doc_id).")
    freeze = freeze_store(db, store_id, reason, user_id)
    freeze.ref_doc_type, freeze.ref_doc_id = count_doc_type, count_doc_id
    db.flush()
    return freeze


def unfreeze_store(db, store_id, user_id):
    freeze = db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first()
    if freeze is None:
        raise InvalidMovementError("Store %s is not frozen." % store_id)
    freeze.unfrozen_at, freeze.unfrozen_by = datetime.now(), user_id
    db.flush()
    return freeze
