"""Batches and shelf life: what is left of each delivery of an item in a store, and whether it is still fit to use.

The ledger keeps stock by store and item, not by batch. What is left of each batch is worked out the way the store is
meant to be run - first in, first out: the stock held now is taken to be the latest deliveries, so the oldest lots are
the ones used up first. Each lot carries the batch, manufacturing and expiry dates its goods receipt line recorded; stock
that came in another way (opening stock, a transfer, a return from site) is a lot with no batch.

Cement loses strength after about ninety days, so a cement receipt given only its manufacturing date expires ninety days
on. A lot within fifteen days of its expiry is flagged; an expired one is not issued.
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from app.models.store_core import DBStoreStockBalance, DBStoreStockLedger
from app.models.store_inward import GRN, DBStoreGrn, DBStoreGrnLine

CEMENT_SHELF_DAYS = 90
NEAR_EXPIRY_DAYS = 15
_CEMENT = re.compile(r"\bcement\b", re.I)
ZERO = Decimal("0")

# What a lot with no goods receipt behind it is called, by the ledger's document type.
SOURCES = {"OSTK": "Opening stock", "TRANSFER": "Transfer in", "CSUP": "Client supply", "ISSRET": "Returned from site", "ISSUE": "Issue cancelled",
           "COUNT": "Stock count"}


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
    """The lots of an item a store holds, oldest first: [{batch_no, source, received_on, manufacturing_date, expiry_date,
    qty, state, recommended}]. `recommended` marks the one to issue first - the oldest not expired."""
    on_date = on_date or date.today()
    bal = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store_id, DBStoreStockBalance.item_id == item_id).first()
    left = Decimal(str(bal.qty)) if bal is not None else ZERO
    if left <= 0:
        return []
    rows = (db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id,
                                                DBStoreStockLedger.qty_in > 0)
            .order_by(DBStoreStockLedger.txn_date.desc(), DBStoreStockLedger.id.desc()).all())
    undone = {r for (r,) in db.query(DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id, DBStoreStockLedger.reversal_of_id.isnot(None),
        DBStoreStockLedger.qty_out > 0).all()}
    taken = []
    for r in rows:                              # newest first: what is held now is what came in last
        if r.id in undone:
            continue
        q = min(Decimal(str(r.qty_in)), left)
        taken.append((r, q))
        left -= q
        if left <= 0:
            break
    grn_lines = {l.id: (l, g) for l, g in db.query(DBStoreGrnLine, DBStoreGrn).join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id).filter(
        DBStoreGrnLine.id.in_([r.ref_line_id for r, _q in taken if r.ref_doc_type == GRN and r.ref_line_id] or [0])).all()}
    lots = {}
    for r, q in reversed(taken):                # oldest first
        got = grn_lines.get(r.ref_line_id) if r.ref_doc_type == GRN else None
        line, grn = got if got else (None, None)
        batch = (line.batch_no or "").strip() if line is not None else ""
        key = ("B", batch, line.expiry_date) if batch else ("R", r.id)
        lot = lots.get(key)
        if lot is None:
            lot = lots[key] = {"batch_no": batch, "source": ("Receipt %s" % grn.number) if grn is not None else SOURCES.get(r.ref_doc_type, r.ref_doc_type or "Stock"),
                               "received_on": r.txn_date.isoformat() if r.txn_date else "",
                               "manufacturing_date": line.manufacturing_date.isoformat() if line is not None and line.manufacturing_date else "",
                               "expiry_date": line.expiry_date.isoformat() if line is not None and line.expiry_date else "",
                               "qty": ZERO, "state": shelf_state(line.expiry_date if line is not None else None, on_date), "recommended": False}
        lot["qty"] += q
    out = list(lots.values())
    first = next((l for l in out if l["state"] != "EXPIRED"), None)
    if first is not None:
        first["recommended"] = True
    for l in out:
        l["qty"] = format(l["qty"].quantize(Decimal("0.001")), "f")
    return out
