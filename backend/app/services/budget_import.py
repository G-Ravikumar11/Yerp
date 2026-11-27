"""The budget filled in Excel and uploaded back - the sheet the Budgeting page's Excel button gives.

Somebody without a steady connection downloads the budget, fills our cost per unit for the lines still to be budgeted, and
the Master uploads it. The rules, so the upload can never make a mess:

* Each row is found in the BOQ by its item number and description (the sheet carries no ids), in the order the BOQ has
  them, so two lines with the same number and words are still told apart.
* Only a line not budgeted in the app is filled. A line already budgeted is left exactly as it is, even if the sheet shows
  other figures for it - what was done in the app is never overwritten or entered a second time.
* A row with no cost in it is left for later; nothing is made for it.
* A figure that is not a number, or is below zero, or a row whose line is not in the BOQ, is listed and skipped.
* Uploading the same sheet twice adds nothing the second time: by then every line it filled is budgeted.

The upload is looked at first (preview) and saved only on the Master's word (commit), checked again at that moment against
the budget as it then stands.
"""
import io
import re
from datetime import datetime

import openpyxl
from fastapi import HTTPException

from app import models
from app.services.boq import boq_lines_of_job
from app.services.budgeting import KIND_LABEL, replace_items, unit_costs

MAX_ROWS = 20000
KINDS = ("MATERIAL", "LABOUR", "OTHER")
# The sheet's headings, squeezed to letters and digits: what each figure is in it.
PER_UNIT = {"MATERIAL": "materialperunit", "LABOUR": "labourperunit", "OTHER": "plantotherperunit"}
AMOUNT = {"MATERIAL": "material", "LABOUR": "labour", "OTHER": "plantother"}


def _head(v):
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def _words(v):
    """A description as compared: case, spacing and line breaks do not count."""
    return " ".join(str(v or "").split()).lower()


def _no(v):
    """An item number as compared. Excel may have turned "2.10" into the number 2.1, so a number is read as it shows."""
    if v is None:
        return ""
    if isinstance(v, float):
        v = ("%f" % v).rstrip("0").rstrip(".")
    return str(v).strip().lower()


def _number(v):
    """A cell as a figure: empty is None; "1,250.50" and "Rs 1250" are read; anything else is an error (ValueError)."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError
    if isinstance(v, (int, float)):
        if v != v:
            raise ValueError
        return float(v)
    s = str(v).strip().replace(",", "").replace("₹", "")
    s = re.sub(r"^(rs\.?|inr)\s*", "", s, flags=re.I)
    if s in ("", "-"):
        return None
    return float(s)


def read_rows(content: bytes):
    """The table out of the workbook: [{row, item_no, description, quantity, per_unit{kind}, amount{kind}}]. The heading row is
    the first with Item, Description and Material per unit; the table ends at the Total row."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except Exception:
        raise HTTPException(400, "That file could not be read. Upload the .xlsx downloaded from this page, filled in.")
    ws = wb.worksheets[0]
    cols, out = None, []
    for n, r in enumerate(ws.iter_rows(values_only=True), 1):
        if n > MAX_ROWS:
            raise HTTPException(400, "That sheet has more than %d rows." % MAX_ROWS)
        if cols is None:
            heads = [_head(c) for c in r]
            if "item" in heads and "description" in heads and PER_UNIT["MATERIAL"] in heads:
                cols = {h: heads.index(h) for h in heads if h}
            continue
        cell = lambda h: r[cols[h]] if h in cols and cols[h] < len(r) else None
        if not any(c not in (None, "") for c in r):
            continue
        if _head(cell("item")) == "total" and not cell("description"):
            break
        out.append({"row": n, "item_no": cell("item"), "description": cell("description"), "quantity": cell("quantity"),
                    "per_unit": {k: cell(PER_UNIT[k]) for k in KINDS}, "amount": {k: cell(AMOUNT[k]) for k in KINDS}})
    wb.close()
    if cols is None:
        raise HTTPException(400, "This is not the budget sheet: the headings Item, Description and Material per unit were not found. "
                                 "Download the Excel from this page, fill it and upload that.")
    return out


def _budgeted_keys(db, client_id, job_id):
    return {k for (k,) in db.query(models.DBBoqBudgetItem.boq_key).filter(
        models.DBBoqBudgetItem.client_id == client_id, models.DBBoqBudgetItem.job_id == job_id).distinct()}


def plan(db, client_id, job, content: bytes):
    """What the upload would do, row by row, saving nothing."""
    rows = read_rows(content)
    lines = boq_lines_of_job(db, client_id, job.id)
    budgeted = _budgeted_keys(db, client_id, job.id)
    in_app = unit_costs(db, client_id, job.id)
    # The BOQ's lines by number and words, each list in BOQ order; a row takes the first not yet taken.
    by_both, by_words = {}, {}
    for l in lines:
        by_both.setdefault((_no(l.item_no), _words(l.description)), []).append(l)
        by_words.setdefault(_words(l.description), []).append(l)
    taken = set()

    def find(r):
        free = [l for l in by_both.get((_no(r["item_no"]), _words(r["description"])), []) if l.key not in taken]
        if free:
            return free[0]
        # The number was changed or mangled: the words alone, when only one free line has them.
        free = [l for l in by_words.get(_words(r["description"]), []) if l.key not in taken]
        return free[0] if len(free) == 1 else None

    out = []
    for r in rows:
        label = ("%s %s" % (_no(r["item_no"]) if r["item_no"] is not None else "", " ".join(str(r["description"] or "").split())[:80])).strip()
        entry = {"row": r["row"], "item": label, "key": "", "status": "", "message": "", "unit": {k: 0.0 for k in KINDS}}
        out.append(entry)
        try:
            per_unit = {k: _number(r["per_unit"][k]) for k in KINDS}
            amount = {k: _number(r["amount"][k]) for k in KINDS}
        except (TypeError, ValueError):
            entry.update(status="error", message="A cost is not a number. Type figures only, like 1250.50.")
            continue
        if any(v is not None and v < 0 for v in list(per_unit.values()) + list(amount.values())):
            entry.update(status="error", message="A cost is below zero.")
            continue
        line = find(r)
        if line is None:
            if not any(per_unit.values()) and not any(amount.values()):
                continue                                   # nothing to put in, so nothing to find
            entry.update(status="error", message="This line is not in the project's BOQ now (or is in the sheet twice).")
            continue
        taken.add(line.key)
        entry["key"] = line.key
        qty = line.quantity or 0
        unit = {k: per_unit[k] or 0.0 for k in KINDS}
        # Only the amounts filled (Material, Labour, Plant & other for the whole line): worked back to one unit.
        if not any(unit.values()) and any(amount.values()) and qty:
            unit = {k: (amount[k] or 0.0) / qty for k in KINDS}
        entry["unit"] = {k: round(v, 4) for k, v in unit.items()}
        if line.key in budgeted:
            have = in_app.get(line.key) or {}
            differs = any(unit.values()) and any(abs(unit[k] - (have.get(k) or 0)) > 0.01 for k in KINDS)
            entry.update(status="kept", message="Already budgeted in the app - left as it is." + (
                " The sheet has other figures for it; change it on the page if they are right." if differs else ""))
        elif not any(unit.values()):
            entry.update(status="empty", message="No cost filled - left for later.")
        else:
            entry.update(status="add", message="Will be added: " + ", ".join(
                "%s %s" % (KIND_LABEL[k].lower(), ("%.2f" % unit[k]).rstrip("0").rstrip(".")) for k in KINDS if unit[k]) + " per %s" % (line.uom or "unit"))
            entry["uom"] = line.uom or ""
    counts = {s: len([e for e in out if e["status"] == s]) for s in ("add", "kept", "empty", "error")}
    return {"rows": out, "counts": counts, "lines": len(lines), "budgeted_before": len(budgeted)}


def commit(db, client_id, job, content: bytes, who):
    """Add the lines the plan says to add, checked against the budget as it stands now. Returns the plan with what was done."""
    p = plan(db, client_id, job, content)
    added = 0
    for e in p["rows"]:
        if e["status"] != "add":
            continue
        items = [{"kind": k, "description": "%s (from the Excel budget)" % KIND_LABEL[k], "uom": e.get("uom", ""),
                  "coefficient": 1, "rate": e["unit"][k], "wastage_percent": 0} for k in KINDS if e["unit"][k]]
        replace_items(db, client_id, job.id, e["key"], items, who)
        added += 1
    p["added"] = added
    p["at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return p
