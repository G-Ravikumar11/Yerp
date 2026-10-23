"""Batches and shelf life: what is left of each lot of an item in a store, and whether it is still fit to use.

The ledger keeps what each store holds of each lot (app/services/stock_ledger.py): a goods receipt line brings in the batch it
recorded, with its manufacturing and expiry dates; a transfer carries its lots to the other store; an issue takes the batch it
names, or the earliest expiry. Stock with no batch behind it (opening stock, client supply, a count surplus) is a lot of its own.

Cement loses strength after about ninety days, so a cement receipt given only its manufacturing date expires ninety days
on. A lot within fifteen days of its expiry is flagged; an expired one is not issued.
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from app.models.store_core import NO_BATCH
from app.services.stock_ledger import lot_label, lots_on_hand

CEMENT_SHELF_DAYS = 90
NEAR_EXPIRY_DAYS = 15
_CEMENT = re.compile(r"\bcement\b", re.I)
ZERO = Decimal("0")

def is_cement(item) -> bool:
    return bool(item is not None and _CEMENT.search(item.item_name or ""))


def default_expiry(item, manufactured):
    """Cement's expiry when only its manufacturing date is known: ninety days on. None for anything else."""
    return manufactured + timedelta(days=CEMENT_SHELF_DAYS) if manufactured and is_cement(item) else None


def shelf_state(expiry, on_date):
    """EXPIRED, NEAR (within fifteen days) or OK; '' when the lot has no expiry date."""
    if expiry is None:
        return ""
    if expiry < on_date:
        return "EXPIRED"
    return "NEAR" if expiry <= on_date + timedelta(days=NEAR_EXPIRY_DAYS) else "OK"


def batches_on_hand(db, store_id, item_id, on_date=None):
    """The lots of an item a store holds, earliest expiry first (so an expired lot is at the top, to be written off), then the
    lots with no expiry, oldest first:
    [{lot_id, batch_no, source, received_on, manufacturing_date, expiry_date, qty, state, recommended}]. `recommended` marks
    the one to issue first - the earliest expiry not yet expired."""
    on_date = on_date or date.today()
    held = lots_on_hand(db, store_id, item_id)

    def key(pair):
        b, _q = pair
        expiry = b.expiry_date if b is not None else None
        return (expiry or date.max, (b.first_received if b is not None else None) or date.min, b.id if b is not None else 0)
    out = []
    for b, q in sorted(held, key=key):
        out.append({"lot_id": b.id if b is not None else NO_BATCH, "batch_no": lot_label(b),
                    "source": (b.source if b is not None else "") or ("Stock with no batch" if b is None else "Batch"),
                    "received_on": b.first_received.isoformat() if b is not None and b.first_received else "",
                    "manufacturing_date": b.manufacturing_date.isoformat() if b is not None and b.manufacturing_date else "",
                    "expiry_date": b.expiry_date.isoformat() if b is not None and b.expiry_date else "",
                    "qty": format(q.quantize(Decimal("0.001")), "f"), "state": shelf_state(b.expiry_date if b is not None else None, on_date),
                    "recommended": False})
    first = next((l for l in out if l["state"] != "EXPIRED"), None)
    if first is not None:
        first["recommended"] = True
    return out


def usable_qty(db, store_id, item_id, on_date=None) -> Decimal:
    """What of an item a store holds that has not expired."""
    on_date = on_date or date.today()
    return sum((q for b, q in lots_on_hand(db, store_id, item_id) if not (b is not None and b.expiry_date and b.expiry_date < on_date)), ZERO)


def find_lot(db, store_id, item_id, batch_no):
    """(lot id, qty held) for a batch number the person picked ('' = stock with no batch), or None when the store holds none of it."""
    batch_no = (batch_no or "").strip()
    for b, q in lots_on_hand(db, store_id, item_id):
        if (b is None and not batch_no) or (b is not None and batch_no and lot_label(b) == batch_no):
            return (b.id if b is not None else NO_BATCH, q)
    return None
