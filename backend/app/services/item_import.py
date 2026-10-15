"""Bringing items in from a sheet: every row is read, checked and sorted into New, Update, Duplicate or Error before anything is saved."""
import re

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.core.currency import unit_rate
from app.core.units import BOQ_ITEM_TYPES, UNITS_OF_MEASURE, canonical_unit
from app.schemas.item_master import MasterItemIn
from app.services import item_master as im

MAX_ROWS = 5000

# The columns of the template, in order, and the names a sheet might use for each. Matched by name, so a sheet may
# reorder them, leave some out or call them what its own desk calls them.
TEMPLATE_HEADERS = ["Item code", "Item name", "What is it?", "Category", "Subcategory", "Unit", "Grade or specification", "Usual purchase rate",
                    "Usual selling rate", "GST %", "HSN / SAC", "Item type", "Usual supplier", "Minimum stock", "Description", "Remarks"]
TEMPLATE_SAMPLE = [
    ["", "Cement - OPC 53 grade", "Material", "Cement", "", "Bags", "OPC 53 grade, 50 kg bag", 415, "", 18, "2523", "Purchased", "", 200, "", ""],
    ["PCC-M15", "PCC M15 in foundation", "Work item", "Concrete (PCC / RCC)", "", "cum", "M15", "", "", 18, "", "Work", "", "", "", ""],
]
ALIASES = {
    "item_code": ["itemcode", "code", "materialcode", "sku", "erpcode", "itemno", "productcode"],
    "item_name": ["itemname", "name", "material", "materialname", "particulars", "product", "productname", "item"],
    "kind": ["whatisit", "kind", "itemkind", "materialorwork"],
    "item_category": ["category", "itemcategory", "maincategory", "group"],
    "item_subcategory": ["subcategory", "subcat", "itemsubcategory", "subgroup"],
    "units_of_measure": ["unit", "uom", "units", "unitofmeasure", "unitsofmeasure", "measure"],
    "specification": ["gradeorspecification", "specification", "grade", "materialgrade", "spec"],
    "purchase_rate": ["usualpurchaserate", "purchaserate", "buyingrate", "purchaseprice", "costrate", "cost"],
    "selling_rate": ["usualsellingrate", "sellingrate", "salesrate", "saleprice", "rate", "price"],
    "gst_percent": ["gst", "gstrate", "gstpercent", "taxrate", "tax", "taxpercent"],
    "hsn_code": ["hsnsac", "hsn", "hsncode", "sac"],
    "item_type": ["itemtype", "type"],
    "preferred_supplier": ["usualsupplier", "preferredsupplier", "supplier", "vendor"],
    "reorder_level": ["minimumstock", "minimumstocklevel", "minstock", "reorderlevel", "reorder"],
    "description": ["description", "desc", "longdescription", "details"],
    "remarks": ["remarks", "notes", "note", "comments"],
}
FIELDS = list(ALIASES)
# What a sheet row, once read, is compared and saved as, field by field.
COMPARE = {"item_name": "item_name", "description": "description", "units_of_measure": "units_of_measure", "item_category": "item_category",
           "item_subcategory": "item_subcategory", "item_type": "item_type", "specification": "specification", "hsn_code": "hsn_code",
           "preferred_supplier": "preferred_supplier", "remarks": "remarks"}


def _money(text, label, problems):
    t = re.sub(r"[₹,\s]|rs\.?", "", (text or "").lower())
    if not t:
        return ""
    try:
        v = float(t)
    except ValueError:
        problems.append("%s '%s' is not a number." % (label, text))
        return text
    if v < 0 or v > 1e9:
        problems.append("%s must be 0 or more." % label)
        return text
    return ("%g" % v)


def _kind(text):
    t = (text or "").strip().lower()
    if not t:
        return "FG"
    if t in ("rm", "m") or "material" in t or "raw" in t or "store" in t:
        return "RM"
    if t in ("fg", "w") or "work" in t or "finished" in t or "boq" in t:
        return "FG"
    return ""


def clean_values(db, client_id, raw, categories):
    """One row's values, tidied and checked: (values as text for the screen, problems as sentences)."""
    problems = []
    v = {k: re.sub(r"\s+", " ", str(raw.get(k) or "")).strip() for k in FIELDS}
    v["description"] = str(raw.get("description") or "").strip()          # a description keeps its own line breaks
    v["remarks"] = str(raw.get("remarks") or "").strip()
    v["item_code"] = v["item_code"].upper()
    if v["item_code"] and " " in v["item_code"]:
        problems.append("The code has a space in it. Use letters, numbers and - _ / . only.")
    elif v["item_code"]:
        try:
            im.clean_code(v["item_code"])
        except HTTPException as exc:
            problems.append(exc.detail)
    if not v["item_name"]:
        problems.append("The item has no name.")
    kind = _kind(v["kind"])
    if not kind:
        problems.append("'%s' is not Material or Work item." % v["kind"])
    v["kind"] = kind or v["kind"]
    if not v["units_of_measure"]:
        problems.append("The unit is missing. Use one of: %s." % ", ".join(UNITS_OF_MEASURE))
    else:
        unit = canonical_unit(v["units_of_measure"], default="")
        if unit:
            v["units_of_measure"] = unit
        else:
            problems.append("'%s' is not a unit this app knows. Use one of: %s." % (v["units_of_measure"], ", ".join(UNITS_OF_MEASURE)))
    if v["item_type"]:
        match = next((t for t in BOQ_ITEM_TYPES if t.lower() == v["item_type"].lower()), "")
        if match:
            v["item_type"] = match
        else:
            problems.append("'%s' is not an item type. Use one of: %s." % (v["item_type"], ", ".join(BOQ_ITEM_TYPES)))
    elif kind:
        v["item_type"] = "Purchased" if kind == "RM" else "Work"
    cat = v["item_category"]
    if cat:
        found = categories.get(cat.lower())
        if not found:
            problems.append("The category '%s' is not set up. Add it under Categories, or choose one that is." % cat)
        else:
            v["item_category"] = found["name"]
            if v["item_subcategory"]:
                sub = found["subs"].get(v["item_subcategory"].lower())
                if sub:
                    v["item_subcategory"] = sub
                else:
                    problems.append("'%s' is not a subcategory of %s." % (v["item_subcategory"], found["name"]))
    elif v["item_subcategory"]:
        problems.append("A subcategory needs its category.")
    v["purchase_rate"] = _money(v["purchase_rate"], "The purchase rate", problems)
    v["selling_rate"] = _money(v["selling_rate"], "The selling rate", problems)
    v["reorder_level"] = _money(v["reorder_level"], "The minimum stock", problems)
    if v["gst_percent"]:
        t = v["gst_percent"].replace("%", "").strip()
        try:
            g = float(t)
            g = g * 100 if 0 < g < 1 else g
        except ValueError:
            g = None
        if g is None or g not in im.ALLOWED_GST:
            problems.append("GST '%s' is not one of 0, 5, 12, 18 or 28." % v["gst_percent"])
        else:
            v["gst_percent"] = "%g" % g
    return v, problems


def category_map(db, client_id):
    im.ensure_default_categories(db, client_id)
    rows = db.query(models.DBItemCategory).filter(models.DBItemCategory.client_id == client_id).all()
    out = {}
    for r in rows:
        if not r.parent_id:
            out[r.name.lower()] = {"id": r.id, "name": r.name, "subs": {}}
    by_id = {c["id"]: c for c in out.values()}
    for r in rows:
        if r.parent_id in by_id:
            by_id[r.parent_id]["subs"][r.name.lower()] = r.name
    return out


def _name_key(text):
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split())


def _changes(item, v):
    """What the sheet would change on an item that already exists: only what it actually says, and only where it differs."""
    out = []
    for field in COMPARE:
        new = v.get(field, "")
        if new and (getattr(item, field, "") or "") != new:
            out.append(field)
    for field in ("purchase_rate", "selling_rate", "reorder_level"):
        new = v.get(field, "")
        if new != "" and unit_rate(getattr(item, field, 0) or 0) != unit_rate(float(new)):
            out.append(field)
    if v.get("gst_percent") != "" and (item.item_tax_type or "") != "%s%%" % v["gst_percent"]:
        out.append("gst_percent")
    return out


def classify(db, client_id, entries):
    """Sort entries ({line, values, action}) into New / Update / Duplicate / Error, each with its reason.

    Reads the database once for the whole list. Nothing is written: this is what the preview shows and what a commit
    re-runs, so a row's status is never taken on trust from the screen."""
    categories = category_map(db, client_id)
    codes = {(e["values"].get("item_code") or "").strip().upper() for e in entries} - {""}
    existing, elsewhere = {}, set()
    if codes:
        for i in db.query(models.DBItem).filter(models.DBItem.item_code.in_(list(codes))).all():
            if i.client_id == client_id:
                existing[i.item_code] = i
            else:
                elsewhere.add(i.item_code)
    by_name = {}
    for i in db.query(models.DBItem.id, models.DBItem.item_code, models.DBItem.item_name).filter(models.DBItem.client_id == client_id).all():
        by_name.setdefault(_name_key(i.item_name), i)
    seen_code, seen_name, out = {}, {}, []
    for e in entries:
        v, problems = clean_values(db, client_id, e["values"], categories)
        code, line = v["item_code"], e["line"]
        chosen = e.get("action")
        row = {"line": line, "values": v, "status": "New", "reason": "", "changes": [], "existing_id": None, "kind_of_duplicate": "",
               "action": chosen or "import"}
        if problems:
            row.update(status="Error", reason=" ".join(problems), action="skip")
        elif code and code in seen_code:
            row.update(status="Duplicate", reason="Line %d has the same code. This repeat is left out." % seen_code[code], kind_of_duplicate="code_in_file", action="skip")
        elif code and code in elsewhere:
            row.update(status="Error", reason="This code is already used by another item. Use a different code.", action="skip")
        elif code and code in existing:
            item = existing[code]
            changes = _changes(item, v)
            row["existing_id"] = item.id
            if changes:
                row.update(status="Update", changes=changes, reason="Already in the master as '%s'. Changes: %s." % (item.item_name, ", ".join(c.replace("_", " ") for c in changes)))
            else:
                row.update(status="Duplicate", reason="Already in the master as '%s' with the same details." % item.item_name, kind_of_duplicate="unchanged", action="skip")
        elif not code and _name_key(v["item_name"]) in by_name:
            twin = by_name[_name_key(v["item_name"])]
            row.update(status="Duplicate", kind_of_duplicate="same_name", action=chosen or "skip",
                       reason="Same name as '%s' (code %s). Skip it, or give it a code of its own to add it as a new item." % (twin.item_name, twin.item_code))
        elif not code and _name_key(v["item_name"]) in seen_name:
            row.update(status="Duplicate", kind_of_duplicate="code_in_file", action="skip",
                       reason="Line %d has the same name. This repeat is left out." % seen_name[_name_key(v["item_name"])])
        else:
            row["reason"] = "Will be given the next free code." if not code else "A new item."
        if row["status"] not in ("Error",) and row["kind_of_duplicate"] != "code_in_file":
            if code:
                seen_code.setdefault(code, line)
            seen_name.setdefault(_name_key(v["item_name"]), line)
        out.append(row)
    return out


def summarise(rows):
    s = {"total": len(rows), "new": 0, "update": 0, "duplicate": 0, "error": 0}
    for r in rows:
        s[r["status"].lower()] += 1
    return s


def read_rows(header, body):
    """Entries from a read sheet. The first row the sheet gives is its header; rows with nothing in any known column are dropped."""
    from app.core.sheets import map_headers_with, mapping_report, rows_from
    mapping, unmapped = map_headers_with(header, ALIASES)
    if "item_name" not in mapping.values():
        raise HTTPException(400, "No item name column found. Expected a column headed 'Item name' (or 'Name', 'Material', 'Particulars'). Download the template for the layout.")
    rows = rows_from(header, body, mapping)
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, "That sheet has %d rows. Split it into parts of %d or fewer." % (len(rows), MAX_ROWS))
    return [{"line": r["_line"], "values": {k: r.get(k, "") for k in FIELDS}} for r in rows], mapping_report(header, mapping), unmapped


def apply_update(item, v, who):
    """Change only what the sheet actually says: a blank cell never wipes what the master already holds."""
    for field in COMPARE:
        if v.get(field):
            setattr(item, field, v[field])
    if v.get("purchase_rate") != "":
        item.purchase_rate = unit_rate(float(v["purchase_rate"]))
    if v.get("selling_rate") != "":
        item.selling_rate = unit_rate(float(v["selling_rate"]))
    if v.get("reorder_level") != "":
        item.reorder_level = float(v["reorder_level"])
    if v.get("gst_percent") != "":
        item.item_tax_type = "%s%%" % v["gst_percent"]
    item.updated_by_name, item.updated_at = who, im.now()


def new_item_body(v):
    num = lambda t: float(t) if t != "" else None
    return MasterItemIn(item_code=v["item_code"], item_name=v["item_name"], description=v["description"], kind=v["kind"],
                        item_category=v["item_category"], item_subcategory=v["item_subcategory"], item_type=v["item_type"],
                        units_of_measure=v["units_of_measure"], specification=v["specification"], purchase_rate=num(v["purchase_rate"]),
                        selling_rate=num(v["selling_rate"]), hsn_code=v["hsn_code"], gst_percent=num(v["gst_percent"]),
                        preferred_supplier=v["preferred_supplier"], reorder_level=num(v["reorder_level"]), remarks=v["remarks"])


def commit(db, client_id, entries, who):
    """Save what the person chose to import, after checking every row again. All the good rows go in together or none do.

    Returns {created, updated, skipped, errors}; a row that is skipped or fails is listed with the reason."""
    rows = classify(db, client_id, entries)
    created = updated = skipped = 0
    problems = []
    taken = set()
    for r in rows:
        v, line = r["values"], r["line"]
        wants = r["action"] == "import"
        if not wants:
            skipped += 1
            problems.append({"line": line, "code": v["item_code"], "name": v["item_name"], "reason": "Skipped. " + r["reason"] if r["status"] != "Error" else r["reason"]})
            continue
        if r["status"] == "Error" or r["kind_of_duplicate"] in ("code_in_file", "unchanged"):
            skipped += 1
            problems.append({"line": line, "code": v["item_code"], "name": v["item_name"], "reason": r["reason"]})
            continue
        if r["status"] == "Update":
            apply_update(db.query(models.DBItem).get(r["existing_id"]), v, who)
            updated += 1
            continue
        try:
            item = im.create_master_item(db, client_id, new_item_body(v), who, taken)
            taken.add(item.item_code)
            created += 1
        except HTTPException as exc:
            skipped += 1
            problems.append({"line": line, "code": v["item_code"], "name": v["item_name"], "reason": str(exc.detail)})
    return {"created": created, "updated": updated, "skipped": skipped, "errors": problems}
