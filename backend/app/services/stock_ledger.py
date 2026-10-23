"""The only place stock moves. Every slice posts through post_movement and undoes through reverse_document.

Moving weighted average, per store and item:
  IN   qty x rate is added; the average becomes value / qty.
  OUT  is valued at the average of the moment (rate must be left None); the average does not change. Taking the whole
       balance out takes its whole value, so rounding never leaves a residue behind a zero quantity.
Stock never goes negative and a frozen store does not move. Nothing here commits: the caller owns the transaction and,
when one of these raises, rolls it back.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app import models
from app.core.permissions import permissions_for
from app.models.store_core import (
    IN_MOVEMENTS, CostHead, DBStore, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance,
    DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, InsufficientStockError, InvalidMovementError,
    MovementType, StockLedgerEntry, StoreFrozenError,
)

ZERO = Decimal("0")
_QTY, _VALUE, _RATE = Decimal("0.001"), Decimal("0.01"), Decimal("0.0001")


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


def _assert_not_frozen(db, store_id):
    open_freeze = db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first()
    if open_freeze is not None:
        raise StoreFrozenError(store_id, open_freeze.reason or "")


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


def _apply(db, *, store, item_id, mtype, qty, rate, txn_date, user_id, ref_doc_type, ref_doc_id, ref_line_id, project_id,
           work_order_id=None, boq_item_id=None, cost_head=None, subcontractor_id=None, remarks=None) -> DBStoreStockLedger:
    """A validated movement -> its ledger row and the new balance."""
    is_in = mtype in IN_MOVEMENTS
    bal = _balance_row(db, store.id, item_id)
    old_qty, old_value, old_avg = _dec(bal.qty), _dec(bal.value), _dec(bal.avg_rate)
    if is_in:
        value = _q(qty * rate, _VALUE)
        new_qty, new_value = old_qty + qty, old_value + value
        avg = _q(new_value / new_qty, _RATE)
        entry_rate = rate
        _note_restock(db, store, item_id, new_qty)
    else:
        if qty > old_qty:
            raise InsufficientStockError(store.id, item_id, old_qty, qty)
        if qty == old_qty:
            value = old_value
        else:
            value = _q(qty * old_avg, _VALUE)
            if value > old_value:
                raise InvalidMovementError("That would leave store %s with a negative value for item %s." % (store.code, item_id))
        new_qty, new_value, avg = old_qty - qty, old_value - value, old_avg
        entry_rate = _q(value / qty, _RATE)
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
    _assert_not_frozen(db, store.id)
    return _apply(db, store=store, item_id=item_id, mtype=mtype, qty=qty, rate=rate, txn_date=day, user_id=user_id,
                  ref_doc_type=ref_doc_type, ref_doc_id=ref_doc_id, ref_line_id=ref_line_id, project_id=project_id,
                  work_order_id=work_order_id, boq_item_id=boq_item_id, cost_head=cost_head,
                  subcontractor_id=subcontractor_id, remarks=remarks)


def reverse_document(db, *, ref_doc_type, ref_doc_id, user_id, reason) -> list:
    """Undo every movement a document made that is not already undone, newest first.

    Each is cancelled by an entry of the same movement_type with the quantity in the opposite column and
    reversal_of_id set, dated today. An IN comes back out at the value it went in at, an OUT comes back in at the
    value it left at. All or nothing: if one cannot be reversed (the stock has since been used) none is."""
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
            _assert_not_frozen(db, store.id)
            out.append(_apply_reversal(db, e, store, user_id, reason))
    return out


def _apply_reversal(db, e, store, user_id, reason):
    """The reversing entry for one original: the opposite direction, at the original value."""
    mtype, was_in = MovementType(e.movement_type), _dec(e.qty_in) > 0
    qty = _dec(e.qty_in) if was_in else _dec(e.qty_out)
    bal = _balance_row(db, store.id, e.item_id)
    old_qty, old_value = _dec(bal.qty), _dec(bal.value)
    value = _dec(e.value)
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


def unfreeze_store(db, store_id, user_id):
    freeze = db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id, DBStoreFreeze.unfrozen_at.is_(None)).first()
    if freeze is None:
        raise InvalidMovementError("Store %s is not frozen." % store_id)
    freeze.unfrozen_at, freeze.unfrozen_by = datetime.now(), user_id
    db.flush()
    return freeze


# --- reorder alerts ------------------------------------------------------------------------------------------------------
# Stock that goes out and leaves a store at or below an item's reorder level for that store (the store's own level where it has set one,
# else the item's) puts an alert on the dashboard (the bell, and email or WhatsApp where the company has asked for them). One alert stays open
# until stock comes back above the level, so it is raised once, not on every issue below it. The ledger never commits, and an alert is saved
# and sent on its own, so it is only noted here and goes out once the posting itself is saved; a posting rolled back sends nothing.

REORDER_KEY = "store_reorder_alerts"


def _level(db, store, item_id):
    from app.services.store_levels import levels_for
    return levels_for(db, store.id, item_id)[0]


def _note_reorder(db, store, item_id, before, after):
    level = _level(db, store, item_id)
    if level > 0 and after <= level:
        db.info.setdefault(REORDER_KEY, []).append(("out", store.client_id, store.id, item_id, after, level))


def _note_restock(db, store, item_id, after):
    level = _level(db, store, item_id)
    if level > 0 and after > level:
        db.info.setdefault(REORDER_KEY, []).append(("in", store.client_id, store.id, item_id, after, level))


def raise_reorder_alert(s, client_id, store, item, left, level):
    """One open alert per store and item: raised (and told) only if there is none open. Returns whether it was raised."""
    from datetime import datetime as _dt
    from app.core.notifications import notify
    from app.models.store_extras import DBStoreReorderAlert
    row = s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.store_id == store.id, DBStoreReorderAlert.item_id == item.id).first()
    if row is not None and row.cleared_at is None:
        return False
    if row is None:
        s.add(DBStoreReorderAlert(client_id=client_id, store_id=store.id, item_id=item.id))
    else:
        row.alerted_at, row.cleared_at = _dt.now(), None
    settings = s.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    unit = (settings.base_uom if settings else item.units_of_measure) or ""
    notify(s, client_id, "store_reorder", "%s is at its reorder level in %s" % (item.item_name, store.code),
           "%s %s left in %s - %s; the reorder level is %s. Raise a purchase enquiry for it from the Reorder report."
           % (format(_q(left, _QTY).normalize(), "f"), unit, store.code, store.name, format(_q(level, _QTY).normalize(), "f")),
           view="reorder-view", ref_type="store_item", ref_id=item.id, severity="action")
    return True


def _send_reorder_alerts(session):
    pending = session.info.pop(REORDER_KEY, None)
    if not pending:
        return
    from datetime import datetime as _dt
    from app.db.session import SessionLocal
    from app.models.store_extras import DBStoreReorderAlert
    with SessionLocal() as s:
        for kind, client_id, store_id, item_id, left, level in pending:
            if kind == "in":
                row = s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.store_id == store_id, DBStoreReorderAlert.item_id == item_id,
                                                          DBStoreReorderAlert.cleared_at.is_(None)).first()
                if row is not None:
                    row.cleared_at = _dt.now()
                continue
            store, item = s.get(DBStore, store_id), s.get(models.DBItem, item_id)
            if store is None or item is None:
                continue
            raise_reorder_alert(s, client_id, store, item, left, level)
            s.flush()
        s.commit()


def _drop_reorder_alerts(session):
    session.info.pop(REORDER_KEY, None)


event.listen(Session, "after_commit", _send_reorder_alerts)
event.listen(Session, "after_rollback", _drop_reorder_alerts)
