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


# --- the item's own reorder level ------------------------------------------------------------------------------------
#
# An item has one reorder level, and it is this one: its Store Hub setting, in the unit the stores count it in (its
# base unit; the item master's own unit while it has no settings). The Item Master, its import and the older store
# screens read and write it here. A store may still set its own (above) - an exception to the one level, not a second.

QTY_STEP = Decimal("0.001")


def item_reorder_levels(db, items):
    """{item_id: (level, unit)} for the items, in two queries however many there are. No settings: (0, the item's unit)."""
    ids = [i.id for i in items if i.id]
    rows = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(ids)).all()} if ids else {}
    out = {}
    for i in items:
        s = rows.get(i.id)
        out[i.id] = (_d(s.reorder_level) if s else ZERO, ((s.base_uom if s else i.units_of_measure) or "").strip())
    return out


def set_item_reorder_level(db, item, level):
    """Write the item's one reorder level, in its base unit. An item the stores have no settings for gets them now, counted
    in its own unit - what the stores already assume for it. Only a material is kept in stock, so only a material has one."""
    if item.kind != "RM":
        return
    level = max(ZERO, _d(level)).quantize(QTY_STEP)
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    if s is None:
        if not level:
            return
        s = DBStoreItemSettings(item_id=item.id, base_uom=(item.units_of_measure or "Nos").strip())
        db.add(s)
    s.reorder_level = level


def company_reorder_levels(db, client_id):
    """{item_code: (level, base unit, {other unit (lower case): how many base units one of it is})} for the company's
    materials that have a level - for the older screens, which count stock by item code in a unit of their own."""
    from app import models
    from app.models.store_core import DBStoreUomConversion
    rows = (db.query(models.DBItem.id, models.DBItem.item_code, models.DBItem.units_of_measure, DBStoreItemSettings.reorder_level,
                     DBStoreItemSettings.base_uom)
            .join(DBStoreItemSettings, DBStoreItemSettings.item_id == models.DBItem.id)
            .filter(models.DBItem.client_id == client_id, DBStoreItemSettings.reorder_level > 0).all())
    if not rows:
        return {}
    factors = {}
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id.in_([r[0] for r in rows])).all():
        factors.setdefault(c.item_id, {})[(c.from_uom or "").strip().lower()] = _d(c.to_base_factor)
    return {code: (_d(level), (base or unit or "").strip(), factors.get(item_id, {})) for item_id, code, unit, level, base in rows}


def level_in(entry, uom):
    """An item's level (from company_reorder_levels) in the unit some stock is counted in, as a float; 0 when there is no
    level or the units cannot be compared - a level that cannot be compared stays quiet rather than warning wrongly."""
    if not entry:
        return 0.0
    level, base, factors = entry
    unit = (uom or "").strip().lower()
    if not unit or unit == base.lower():
        return float(level)
    factor = factors.get(unit)
    return float(level / factor) if factor else 0.0
