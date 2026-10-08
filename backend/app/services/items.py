"""The rules and workings behind the items endpoints."""
import re

from fastapi import HTTPException

from app import models

from app.constants.items import ITEM_TYPE_ALIASES
from app.core.currency import money, unit_rate
from app.core.serials import CODE_ALPHABET, CODE_LENGTH, encode_serial, next_serial, normalise_code
from app.core.units import (
    CATEGORY_BY_KIND,
    ITEM_KINDS,
    ITEM_TYPES,
    UNITS_OF_MEASURE,
    UOM_ALIASES,
    canonical_unit,
)


def map_headers(header_row):
    """Which column is which, against the item master's vocabulary."""
    return match_headers(header_row, HEADER_ALIASES)


def detect_row_kind(row):
    """Whether a row describes raw material or a finished good.

    The sheet already says so, in two columns and again in the code prefix.
    Asking the user to declare it as well is asking for a contradiction.
    """
    cat, sub = squash(row.get("category")), squash(row.get("sub_category"))
    if "rawmaterial" in cat or cat == "raw" or sub == "rm":
        return "RM"
    if "finish" in cat or sub == "fg":
        return "FG"
    code = squash(row.get("item_code"))
    if code.startswith("rm"):
        return "RM"
    if code.startswith("fg"):
        return "FG"
    return None


def closest_option(value, aliases):
    """Map a written value onto a permitted one, or None if it is not close."""
    key = squash(value)
    if not key:
        return None
    for canonical, options in aliases.items():
        if key == squash(canonical) or key in options:
            return canonical
    for canonical, options in aliases.items():
        for option in options:
            if len(option) >= 3 and (key.startswith(option) or option.startswith(key)):
                return canonical
    return None


def normalise_tax(value):
    """'18', '18 %', 'GST 18', '0.18' all mean the same rate."""
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not match:
        return None
    number = float(match.group(1))
    if 0 < number < 1:          # 0.18 written as a fraction
        number *= 100
    text = f"{number:g}%"
    return text if text != raw else None


def repair_row(row, kind, taken_codes):
    """Correct what has exactly one right answer; leave the rest alone.

    Every change is returned so it can be shown. A silent correction to a
    price list is indistinguishable from a bug, and nobody would trust the
    next one.
    """
    repairs = []

    def fix(field, new, note):
        old = row.get(field, "")
        if new is not None and str(new) != str(old):
            row[field] = new
            repairs.append({"line": row.get("_line"), "field": field,
                            "from": str(old), "to": str(new), "note": note})

    code = (row.get("item_code") or "").strip().upper()
    if code != (row.get("item_code") or ""):
        fix("item_code", code, "tidied")

    # The kind is known by now, so the two label columns follow from it rather
    # than being a second place for the user to get it wrong.
    fix("category", CATEGORY_BY_KIND[kind], f"set from the detected {kind} rows")
    fix("sub_category", kind, f"set from the detected {kind} rows")

    # A column the sheet simply does not carry is an omission with an obvious
    # answer, not a reason to refuse the row. Defaults are logged like any
    # other change, so nothing is assumed invisibly.
    if not (row.get("units_of_measure") or "").strip():
        fix("units_of_measure", "Nos", "not given, defaulted")
    else:
        uom = closest_option(row.get("units_of_measure"), UOM_ALIASES)
        if uom:
            fix("units_of_measure", uom, "matched to a permitted unit")

    if not (row.get("item_type") or "").strip():
        fix("item_type", "Purchased", "not given, defaulted")
    else:
        itype = closest_option(row.get("item_type"), ITEM_TYPE_ALIASES)
        if itype:
            fix("item_type", itype, "matched to a permitted type")

    tax = normalise_tax(row.get("item_tax_type"))
    if tax:
        fix("item_tax_type", tax, "written as a percentage")

    # The house rule is that these two are the same thing; an empty one is an
    # omission, not a decision.
    if not (row.get("description") or "").strip() and (row.get("item_name") or "").strip():
        fix("description", row["item_name"].strip(), "copied from the item name")

    return repairs


def suggest_free_code(code, taken):
    """The next code in the same series that nobody is using."""
    match = re.match(r"^(.*?)(\d+)$", code or "")
    if not match:
        return None
    stem, number = match.group(1), int(match.group(2))
    width = len(match.group(2))
    for step in range(1, 500):
        candidate = f"{stem}{str(number + step).zfill(width)}"
        if candidate.upper() not in taken:
            return candidate
    return None


def codes_in_use(db, codes) -> set:
    """Which of these codes already belong to something.

    Asks about the codes in hand rather than loading the item master to find
    out. The earlier version pulled every row in the system on each call - fine
    with a demo, ruinous once a business has a hundred thousand parts, and it
    ran on every save. The lookup is an indexed IN, chunked because databases
    have a ceiling on how many bind parameters one statement may carry.
    """
    wanted = {normalise_code(c) for c in codes if c}
    if not wanted:
        return set()
    found, batch = set(), 900
    ordered = list(wanted)
    for start in range(0, len(ordered), batch):
        chunk = ordered[start:start + batch]
        found.update(row[0].upper() for row in db.query(models.DBItem.item_code).filter(
            models.DBItem.item_code.in_(chunk)).all())
    return found


def code_is_free(db, code) -> bool:
    return normalise_code(code) not in codes_in_use(db, [code])


def issue_item_code(db, taken=None) -> str:
    """The next unused code.

    The sequence is the source of truth, but it is checked against what has
    actually been issued: a restored backup or an imported code could otherwise
    leave the counter behind the data, and the insert would fail on the unique
    index rather than here where it can be explained.
    """
    claimed = {normalise_code(c) for c in (taken or set())}
    for _ in range(64):
        code = encode_serial(next_serial(db, "item"))
        if code in claimed:
            continue
        if db.query(models.DBItem).filter(models.DBItem.item_code == code).first():
            continue
        return code
    raise HTTPException(500, "Could not issue a free code; the series may need resetting.")


def build_item(db, client_id, body, taken):
    kind = (body.kind or "").upper()
    if kind not in ITEM_KINDS:
        raise HTTPException(400, "Choose raw material or a finished good")
    name = (body.item_name or "").strip()
    if not name:
        raise HTTPException(400, "An item name is required")

    typed = normalise_code(body.item_code)
    if typed:
        if len(typed) != CODE_LENGTH:
            raise HTTPException(
                400, "A code is exactly %d characters. Leave it blank to be issued one."
                     % CODE_LENGTH)
        if set(typed) - set(CODE_ALPHABET):
            raise HTTPException(
                400, "A code uses %s only." % "".join(CODE_ALPHABET))
        if typed in taken or db.query(models.DBItem).filter(
                models.DBItem.item_code == typed).first():
            raise HTTPException(
                409, typed + " is already in use. Leave the code blank to be issued the next one.")
        code = typed
    else:
        code = issue_item_code(db, taken)

    unit = canonical_unit(body.units_of_measure)
    if not unit:
        raise HTTPException(400, "%s is not a unit this app knows. Use one of: %s"
                                 % (body.units_of_measure, ", ".join(UNITS_OF_MEASURE)))
    itype = (body.item_type or "").strip() or "Purchased"
    if itype not in ITEM_TYPES:
        raise HTTPException(400, "Type must be one of: " + ", ".join(ITEM_TYPES))

    item = models.DBItem(
        client_id=client_id, kind=kind, item_code=code, item_name=name,
        segment=(body.segment or "").strip(),
        # The house rule is that these two are the same unless told otherwise.
        description=(body.description or "").strip() or name,
        category=CATEGORY_BY_KIND[kind], sub_category=kind,
        hsn_code=(body.hsn_code or "").strip(),
        item_tax_type=(body.item_tax_type or "").strip(),
        item_type=itype, units_of_measure=unit, make=(body.make or "").strip())
    db.add(item)
    taken.add(code)
    return item


def item_row(item):
    return {"id": item.id, "kind": item.kind, "item_code": item.item_code,
            "item_name": item.item_name, "description": item.description,
            "item_type": item.item_type, "units_of_measure": item.units_of_measure,
            "hsn_code": item.hsn_code, "item_tax_type": item.item_tax_type,
            "last_rate": unit_rate(item.last_rate),
            "reorder_level": money(item.reorder_level)}


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.sheets import HEADER_ALIASES, match_headers, squash
