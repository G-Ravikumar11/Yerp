"""Store module - reorder, minimum and maximum levels per store. An item has levels of its own (its store settings); a store may override any
of the three for that item, because a site that uses a tonne a day needs more cover than a yard that uses a bag. A leaf module: the ledger
reads it, so it imports no other service."""
from decimal import Decimal

from app.models.store_core import DBStoreItemSettings
from app.models.store_extras import DBStoreItemLevel

ZERO = Decimal("0")


def _d(x):
    return Decimal(str(x)) if x is not None else ZERO


def effective(settings, override):
    """(reorder_level, min_qty, max_qty) from the item's settings, each replaced by the store's own where it has set one."""
    def pick(name):
        if override is not None and getattr(override, name) is not None:
            return _d(getattr(override, name))
        return _d(getattr(settings, name, None)) if settings is not None else ZERO
    return pick("reorder_level"), pick("min_qty"), pick("max_qty")


def levels_for(db, store_id, item_id):
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    o = db.query(DBStoreItemLevel).filter(DBStoreItemLevel.store_id == store_id, DBStoreItemLevel.item_id == item_id).first()
    return effective(s, o)


def overrides(db, store_ids):
    """{(store_id, item_id): DBStoreItemLevel} for the stores."""
    if not store_ids:
        return {}
    return {(o.store_id, o.item_id): o for o in db.query(DBStoreItemLevel).filter(DBStoreItemLevel.store_id.in_(list(store_ids))).all()}
