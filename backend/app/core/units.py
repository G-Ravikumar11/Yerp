"""Units of measure and the ways people write them."""
import re


# ITEMS, WORK ORDERS AND BOM
#
# The contracting side of an ERP, hung off the existing job:
#
#   Item master (RM/FG)  ->  Work order (what was sold, in FG codes)
#                        ->  BOM/budget (what it consumes, in RM codes)
#
# A work order carries no customer or project of its own. The job already
# knows who it is for, and duplicating that is how the two drift apart.
# Approval runs through the same chain as bills and purchase orders, so a
# signature means the same thing wherever it is given.
ITEM_KINDS = ("RM", "FG")
CATEGORY_BY_KIND = {"RM": "RAW MATERIAL", "FG": "FINISHED GOOD"}
ITEM_TYPES = ("Purchased", "Service")
# The permitted units. Same list drives the pickers and the validators, so a
# value the form offers can never be one the server refuses.
#
# The first six are all this app once had - the units an invoicing product
# ships with. A civil contractor cannot name a single item with them: concrete
# is measured in cubic metres, shuttering in square metres, reinforcement in
# tonnes, cement in bags, and nothing could be created in any of those. That
# one omission stopped the whole chain: no item, so no work order, so nothing
# to measure or bill.
UNITS_OF_MEASURE = (
    # Volume, area and length - what site work is actually measured in
    "cum", "sqm", "rmt", "cft", "sqft",
    # Count and weight
    "Nos", "Sets", "MT", "Quintal", "Kgs", "Bags", "Brass",
    # Fluids
    "Litres", "KL",
    # Time, for labour and plant on hire
    "Hours", "Days", "Months",
    # Everything else
    "Meters", "Lot", "Job",
)
# What the same unit gets called on somebody else's sheet. A schedule that
# says "Cu.M" or "R.Mt" means cum and rmt, and refusing it - or worse, taking
# it as a different unit - is how one item ends up measured two ways.
UNIT_ALIASES = {
    "cubicmeter": "cum", "cubicmetre": "cum", "cbm": "cum", "m3": "cum", "cmt": "cum",
    "squaremeter": "sqm", "squaremetre": "sqm", "m2": "sqm", "smt": "sqm",
    "runningmeter": "rmt", "runningmetre": "rmt", "rm": "rmt", "rft": "rmt",
    "meter": "Meters", "metre": "Meters", "mtr": "Meters", "m": "Meters",
    "no": "Nos", "each": "Nos", "ea": "Nos", "pcs": "Nos", "piece": "Nos",
    "pieces": "Nos", "unit": "Nos", "number": "Nos",
    "kg": "Kgs", "kilogram": "Kgs", "kgs": "Kgs",
    "ton": "MT", "tonne": "MT", "tonnes": "MT", "mt": "MT", "metricton": "MT",
    "bag": "Bags", "qtl": "Quintal", "quintals": "Quintal",
    "ltr": "Litres", "litre": "Litres", "liter": "Litres", "l": "Litres",
    "hour": "Hours", "hr": "Hours", "hrs": "Hours",
    "day": "Days", "month": "Months", "set": "Sets",
    "lumpsum": "Lot", "ls": "Lot", "ls.": "Lot",
    "cubicfeet": "cft", "cuft": "cft", "squarefeet": "sqft", "sft": "sqft",
    "kiloliter": "KL", "kilolitre": "KL",
}


def canonical_unit(value, default="Nos"):
    """The unit as this app spells it, or nothing if it is not one.

    Matched without regard to case, spacing or full stops, because a unit
    typed as "Cu.M", "CUM" and "cum" is one unit, and holding three spellings
    of it is how a stock balance splits in three.
    """
    raw = str(value or "").strip()
    if not raw:
        return default
    for unit in UNITS_OF_MEASURE:
        if raw.lower() == unit.lower():
            return unit
    key = re.sub(r"[^a-z0-9]", "", raw.lower())
    if key in UNIT_ALIASES:
        return UNIT_ALIASES[key]
    for unit in UNITS_OF_MEASURE:
        if key == re.sub(r"[^a-z0-9]", "", unit.lower()):
            return unit
    return ""


def _uom_alias_table():
    """The import's alias table, built from the one unit vocabulary.

    It used to be a third list, written separately: it had no cum and no sqm,
    so every concrete and shuttering line on an imported BOQ was quietly read
    as "Nos", and it mapped rmt onto Meters, turning a civil unit into the
    invoicing one on the way in.
    """
    table = {unit: [unit.lower()] for unit in UNITS_OF_MEASURE}
    for alias, unit in UNIT_ALIASES.items():
        table.setdefault(unit, []).append(alias)
    # Plurals people type that are not worth a line of their own.
    for unit, extra in (("Nos", ["num", "pc"]), ("Kgs", ["kilo", "kilos", "kilograms"]),
                        ("Litres", ["ltrs", "liters", "litres"]), ("Lot", ["lots"]),
                        ("Meters", ["mtrs", "metres"]), ("Bags", ["bag"]),
                        ("Days", ["dys"]), ("Sets", ["set"])):
        table.setdefault(unit, []).extend(extra)
    return {unit: sorted(set(aliases)) for unit, aliases in table.items()}


UOM_ALIASES = _uom_alias_table()
