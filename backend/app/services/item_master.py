"""The BOQ item master: items filed by work category, with defaults that never overwrite a site's price."""
import difflib
import math
import re

from fastapi import HTTPException
from sqlalchemy import func, or_

from app import models
from app.constants.boq import BOQ_PRICED
from app.core.currency import money, unit_rate
from app.core.serials import encode_serial
from app.core.units import BOQ_ITEM_TYPES, CATEGORY_BY_KIND, ITEM_KINDS, UNITS_OF_MEASURE, canonical_unit
from app.services.boq import BOQ_ITEM_CODE
from app.services.items import issue_item_code

# Offered the first time a business opens the item master; after that the business keeps its own list.
DEFAULT_CATEGORIES = (
    "Cement", "Steel & Reinforcement", "Sand & Aggregate", "Bricks & Blocks", "Concrete (PCC / RCC)", "Excavation & Earthwork",
    "Shuttering & Formwork", "Masonry", "Plastering", "Waterproofing", "Flooring & Tiling", "Painting", "Plumbing",
    "Electrical", "Labour", "Equipment Hire", "Other BOQ Work",
)


def now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_default_categories(db, client_id):
    if db.query(models.DBItemCategory.id).filter(models.DBItemCategory.client_id == client_id).first():
        return
    for name in DEFAULT_CATEGORIES:
        db.add(models.DBItemCategory(client_id=client_id, name=name))
    db.flush()


def clean_code(raw):
    """Trimmed, upper-case, and in the shape a BOQ line accepts. Blank stays blank (it means: issue one)."""
    code = (raw or "").strip().upper()
    if code and not BOQ_ITEM_CODE.match(code):
        raise HTTPException(400, "Item code %s: use letters, numbers and - _ / . only, up to 30 characters, with no spaces." % code)
    return code


def check_rate(value, what):
    if value is None or value == "":
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        raise HTTPException(422, "%s must be a number." % what)
    if not math.isfinite(rate) or rate < 0 or rate > 1e9:
        raise HTTPException(422, "%s must be a number from 0 up." % what)
    return unit_rate(rate)


def check_category(db, client_id, category, subcategory):
    """A category and subcategory the business has set up (blank is allowed). A subcategory belongs to its category."""
    category, subcategory = (category or "").strip(), (subcategory or "").strip()
    if subcategory and not category:
        raise HTTPException(422, "Choose the category before its subcategory.")
    if not category:
        return "", ""
    ensure_default_categories(db, client_id)
    cat = db.query(models.DBItemCategory).filter(
        models.DBItemCategory.client_id == client_id, models.DBItemCategory.parent_id.is_(None),
        func.lower(models.DBItemCategory.name) == category.lower()).first()
    if not cat:
        raise HTTPException(422, "%s is not one of your item categories. Add it under Categories first." % category)
    if subcategory:
        sub = db.query(models.DBItemCategory).filter(
            models.DBItemCategory.client_id == client_id, models.DBItemCategory.parent_id == cat.id,
            func.lower(models.DBItemCategory.name) == subcategory.lower()).first()
        if not sub:
            raise HTTPException(422, "%s is not a subcategory of %s." % (subcategory, cat.name))
        subcategory = sub.name
    return cat.name, subcategory


ALLOWED_GST = (0, 5, 12, 18, 28)


def gst_text(percent):
    if percent is None:
        return None
    if not math.isfinite(percent) or percent not in ALLOWED_GST:
        raise HTTPException(422, "GST must be one of 0, 5, 12, 18 or 28 per cent.")
    return "%g%%" % percent


def _fields(db, client_id, body):
    """The checked, normalised values from a request: the one place a create and an edit are both validated."""
    name = re.sub(r"\s+", " ", body.item_name or "").strip()
    if not name:
        raise HTTPException(400, "An item name is required.")
    unit = canonical_unit(body.units_of_measure)
    if not unit:
        raise HTTPException(400, "%s is not a unit this app knows. Use one of: %s" % (body.units_of_measure, ", ".join(UNITS_OF_MEASURE)))
    itype = (body.item_type or "").strip() or "Work"
    if itype not in BOQ_ITEM_TYPES:
        raise HTTPException(400, "Type must be one of: " + ", ".join(BOQ_ITEM_TYPES))
    category, subcategory = check_category(db, client_id, body.item_category, body.item_subcategory)
    out = {"item_name": name[:200], "description": (body.description or "").strip() or name, "units_of_measure": unit,
           "item_type": itype, "item_category": category, "item_subcategory": subcategory,
           "specification": (body.specification or "").strip()[:120], "hsn_code": (body.hsn_code or "").strip()[:20],
           "preferred_supplier": (body.preferred_supplier or "").strip()[:120], "remarks": (body.remarks or "").strip()}
    for field, label in (("purchase_rate", "Purchase rate"), ("selling_rate", "Selling rate")):
        value = check_rate(getattr(body, field), label)
        if value is not None:
            out[field] = value
    tax = gst_text(body.gst_percent)
    if tax is not None:
        out["item_tax_type"] = tax
    if body.reorder_level is not None:
        out["reorder_level"] = max(0.0, money(body.reorder_level))
    return out


def raise_if_code_taken(db, client_id, code, except_id=None):
    """A clear refusal that names the item holding the code (when it is this company's own)."""
    other = db.query(models.DBItem).filter(models.DBItem.item_code == code).first()
    if other is None or other.id == except_id:
        return
    if other.client_id == client_id:
        raise HTTPException(409, "This code is already used by '%s'. Use a different code, or open that item." % other.item_name)
    raise HTTPException(409, "This code is already used by another item. Use a different code, or leave it blank to be given the next free one.")


def peek_next_code(db):
    """The code the next blank item would be given, without using it up: a suggestion, which the person can change."""
    row = db.query(models.DBCodeSequence).filter(models.DBCodeSequence.name == "item").first()
    number = (row.next_value if row else 1) or 1
    for _ in range(64):
        code = encode_serial(number)
        if not db.query(models.DBItem.id).filter(models.DBItem.item_code == code).first():
            return code
        number += 1
    raise HTTPException(500, "Could not find a free code; the series may need resetting.")


def _words(text):
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()


def similar_items(db, client_id, name, code="", exclude_id=None, limit=5):
    """Items already in the master that this name or code might be a repeat of: the exact code, the same name, or a close one."""
    out, seen = [], set()

    def add(item, reason):
        if item.id != exclude_id and item.id not in seen:
            seen.add(item.id)
            out.append({"id": item.id, "item_code": item.item_code, "item_name": item.item_name, "units_of_measure": item.units_of_measure or "",
                        "item_category": item.item_category or "", "is_active": item.is_active is not False, "reason": reason})

    code = (code or "").strip().upper()
    if code:
        same = db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.item_code == code).first()
        if same:
            add(same, "Same code")
    words = _words(name)
    if words:
        key = " ".join(words)
        longest = sorted(set(words), key=len, reverse=True)[:2]
        query = db.query(models.DBItem).filter(models.DBItem.client_id == client_id)
        pool = query.filter(or_(*[models.DBItem.item_name.ilike("%" + w + "%") for w in longest])).limit(300).all()
        scored = []
        for item in pool:
            theirs = " ".join(_words(item.item_name))
            if theirs == key:
                scored.append((2.0, item, "Same name"))
                continue
            ratio = difflib.SequenceMatcher(None, key, theirs).ratio()
            if ratio >= 0.78 or (len(words) >= 2 and set(words) <= set(theirs.split())):
                scored.append((ratio, item, "Looks similar"))
        for _, item, reason in sorted(scored, key=lambda t: -t[0]):
            add(item, reason)
    return out[:limit]


def create_master_item(db, client_id, body, who, taken=None):
    """A new item, or a clear refusal: a code already in use is never made a second time. Does not commit."""
    kind = (body.kind or "FG").upper()
    if kind not in ITEM_KINDS:
        raise HTTPException(400, "kind must be RM or FG")
    fields = _fields(db, client_id, body)
    code = clean_code(body.item_code)
    if code:
        raise_if_code_taken(db, client_id, code)
    else:
        code = issue_item_code(db, taken)
    item = models.DBItem(client_id=client_id, kind=kind, item_code=code, category=CATEGORY_BY_KIND[kind], sub_category=kind,
                         is_active=body.is_active is not False, created_by_name=who, updated_by_name=who, updated_at=now(),
                         **fields)
    db.add(item)
    db.flush()
    return item


def update_master_item(db, item, body, who):
    """Change an item's details. Its code is never changed here: orders, BOQ lines and bills point at it."""
    for key, value in _fields(db, item.client_id, body).items():
        setattr(item, key, value)
    item.updated_by_name, item.updated_at = who, now()
    return item


def default_rate(item):
    return unit_rate(item.selling_rate) if (item.selling_rate or 0) > 0 else None


def sites_using(db, client_id, codes):
    """{item_code: {job_id, ...}} - the sites whose current BOQ revision has a priced line with the code."""
    if not codes:
        return {}
    rows = db.query(models.DBBoq.job_id, models.DBBoqLine.item_code).join(
        models.DBBoqRevision, models.DBBoqRevision.boq_id == models.DBBoq.id).join(
        models.DBBoqLine, models.DBBoqLine.revision_id == models.DBBoqRevision.id).filter(
        models.DBBoq.client_id == client_id, models.DBBoqRevision.rev_no == models.DBBoq.current_rev,
        models.DBBoqLine.kind.in_(BOQ_PRICED), models.DBBoqLine.item_code.in_(list(codes))).distinct().all()
    out = {}
    for job_id, code in rows:
        out.setdefault(code, set()).add(job_id)
    return out


def stock_of(db, client_id, codes):
    """{item_code: on_hand} for the codes, in one query: the store's running total, not a replay of the ledger."""
    if not codes:
        return {}
    return {c: m for c, m in db.query(models.DBStockBalance.item_code, models.DBStockBalance.on_hand).filter(
        models.DBStockBalance.client_id == client_id, models.DBStockBalance.item_code.in_(list(codes))).all()}


def item_dict(item, site_count=0, stock=None):
    return {"id": item.id, "kind": item.kind, "item_code": item.item_code, "item_name": item.item_name,
            "description": item.description or "", "item_category": item.item_category or "",
            "item_subcategory": item.item_subcategory or "", "item_type": item.item_type or "",
            "units_of_measure": item.units_of_measure or "", "specification": item.specification or "",
            "purchase_rate": unit_rate(item.purchase_rate), "selling_rate": unit_rate(item.selling_rate),
            "last_rate": unit_rate(item.last_rate),            # what it was last bought or sold at, from before rates were kept here
            "default_rate": default_rate(item), "hsn_code": item.hsn_code or "", "item_tax_type": item.item_tax_type or "",
            "preferred_supplier": item.preferred_supplier or "", "reorder_level": money(item.reorder_level),
            "remarks": item.remarks or "", "is_active": item.is_active is not False, "sites": site_count,
            "stock": money(stock) if stock is not None else None,        # None: the store holds no record of it
            "created_by": item.created_by_name or "", "updated_by": item.updated_by_name or "",
            "created_at": item.created_at or "", "updated_at": item.updated_at or ""}
