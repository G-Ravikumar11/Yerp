"""Material norms of BOQ work items - what one unit of the work uses up of each store material, with wastage on top.

    PCC M15 (per cum):  Cement OPC 53   4.4 Bags   + 2 %
                        River sand      0.47 cum   + 5 %
                        20 mm metal     0.9 cum    + 5 %

Set once in the Item Master, on screen or from an Excel sheet of every work item; or saved from a BOQ line of an Item sheet
whose materials have been worked out (its quantities divided by the line's quantity). The Item sheet then fills a BOQ line's
materials as BOQ quantity x norm x (1 + wastage) - a proposal the storekeeper looks over and saves, never saved by itself.
Nothing here is a standard figure supplied by the app: every norm is the business's own.
"""
import io
import re
from datetime import datetime

import openpyxl
from fastapi import HTTPException
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func

from app import models
from app.models.item_norms import DBItemNorm

HEADERS = ["Work item code", "Work item name", "Work unit", "Material code", "Material name", "Material unit", "Qty per 1 work unit",
           "Wastage %", "Remarks"]
MAX_ROWS = 20000


def _key(s) -> str:
    return " ".join(str(s or "").split()).lower()


def same_unit(a, b) -> bool:
    """Whether two units are the same once spelt the app's way ("Cu.M" and "cum")."""
    from app.core.units import canonical_unit
    if _key(a) == _key(b):
        return True
    ca, cb = canonical_unit(a, default=""), canonical_unit(b, default="")
    return bool(ca) and ca == cb


def material_unit(db, item) -> str:
    from app.services.store_outward import base_uom_of
    return base_uom_of(db, item) or item.units_of_measure or ""


def norms_of(db, client_id, work_ids):
    """{work item id: [norm rows in order]}."""
    ids = [i for i in set(work_ids) if i]
    out = {}
    if not ids:
        return out
    for n in (db.query(DBItemNorm).filter(DBItemNorm.client_id == client_id, DBItemNorm.work_item_id.in_(ids))
              .order_by(DBItemNorm.work_item_id, DBItemNorm.line_no, DBItemNorm.id).all()):
        out.setdefault(n.work_item_id, []).append(n)
    return out


def norm_counts(db, client_id, work_ids=None):
    """{work item id: how many materials its norm has}."""
    q = db.query(DBItemNorm.work_item_id, func.count(DBItemNorm.id)).filter(DBItemNorm.client_id == client_id)
    if work_ids is not None:
        q = q.filter(DBItemNorm.work_item_id.in_(list(work_ids) or [0]))
    return dict(q.group_by(DBItemNorm.work_item_id).all())


def norm_dicts(db, rows):
    mats = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([r.material_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        m = mats.get(r.material_id)
        if m is None:
            continue
        out.append({"material_id": m.id, "item_code": m.item_code, "item_name": m.item_name, "hsn": m.hsn_code or "", "unit": material_unit(db, m),
                    "qty_per_unit": round(float(r.qty_per_unit or 0), 6), "wastage_pct": round(float(r.wastage_pct or 0), 3),
                    "remarks": r.remarks or "", "is_active": m.is_active is not False and not m.merged_into_id})
    return out


def work_item_of(db, client_id, item_id):
    w = db.query(models.DBItem).filter(models.DBItem.id == item_id, models.DBItem.client_id == client_id).first()
    if w is None:
        raise HTTPException(404, "Item not found")
    if w.kind != "FG":
        raise HTTPException(400, "%s %s is a store material. Norms are set on work items (what a BOQ line is), saying which materials they use." % (w.item_code, w.item_name))
    return w


def _number(raw, label, problems, low=0.0, high=1e6, above=False):
    try:
        v = float(str(raw).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        problems.append("%s '%s' is not a number." % (label, raw))
        return None
    if v != v or v < low or v > high or (above and v <= low):
        problems.append("%s must be %s %g%s." % (label, "above" if above else "from", low, "" if above else " to %g" % high))
        return None
    return v


def check_rows(db, client_id, rows, label=lambda n: "Row %d" % n):
    """Rows [{material_id or item_code, qty_per_unit, wastage_pct, remarks}] as norm values, or every problem: (values, errors)."""
    ids = [r.get("material_id") for r in rows if r.get("material_id")]
    codes = {_key(r.get("item_code")) for r in rows if not r.get("material_id") and _key(r.get("item_code"))}
    by_id = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.id.in_(ids or [0])).all()}
    by_code = {}
    if codes:
        for i in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, func.lower(func.trim(models.DBItem.item_code)).in_(codes)).all():
            by_code[_key(i.item_code)] = i
    out, errors, seen = [], [], set()
    for n, r in enumerate(rows, 1):
        where = label(n)
        m = by_id.get(r.get("material_id")) if r.get("material_id") else by_code.get(_key(r.get("item_code")))
        problems = []
        if m is None:
            problems.append("material %s is not in the Item Master." % (r.get("item_code") or r.get("material_id") or "(none given)"))
        elif m.kind != "RM":
            problems.append("%s %s is a work item, not a store material." % (m.item_code, m.item_name))
        elif m.merged_into_id or m.is_active is False:
            problems.append("%s %s is switched off in the Item Master." % (m.item_code, m.item_name))
        qty = _number(r.get("qty_per_unit"), "the quantity", problems, 0.0, 1e6, above=True)
        waste = _number(r.get("wastage_pct") if r.get("wastage_pct") not in (None, "") else 0, "the wastage %", problems, 0.0, 100.0)
        if m is not None and m.id in seen:
            problems.append("%s is listed twice." % m.item_code)
        if problems:
            errors.append("%s: %s" % (where, " ".join(p[0].upper() + p[1:] for p in problems)))
            continue
        seen.add(m.id)
        out.append({"material_id": m.id, "qty_per_unit": round(qty, 6), "wastage_pct": round(waste, 3), "remarks": str(r.get("remarks") or "").strip()[:200]})
    return out, errors


def replace_norms(db, client_id, work, values, who):
    db.query(DBItemNorm).filter(DBItemNorm.client_id == client_id, DBItemNorm.work_item_id == work.id).delete(synchronize_session=False)
    now = datetime.now()
    for n, v in enumerate(values, 1):
        db.add(DBItemNorm(client_id=client_id, work_item_id=work.id, line_no=n, updated_by_name=who, updated_at=now, **v))
    db.flush()


def save_norms(db, client_id, item_id, rows, who):
    work = work_item_of(db, client_id, item_id)
    values, errors = check_rows(db, client_id, rows)
    if errors:
        raise HTTPException(400, "The norms were not saved:\n" + "\n".join(errors))
    replace_norms(db, client_id, work, values, who)
    return work


# --- Excel: every work item and its norms ------------------------------------------------------------------------------

def workbook(db, client_id) -> bytes:
    """Every active work item, one row per material of its norm - or one row with the material left blank, to fill."""
    works = (db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.kind == "FG", models.DBItem.merged_into_id.is_(None),
                                            models.DBItem.is_active.isnot(False)).order_by(models.DBItem.item_code).all())
    norms = norms_of(db, client_id, [w.id for w in works])
    mats = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_({n.material_id for ns in norms.values() for n in ns} or {0})).all()}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Norms"
    ws.append(HEADERS)
    for w in works:
        rows = [n for n in norms.get(w.id, []) if n.material_id in mats]
        if not rows:
            ws.append([w.item_code, w.item_name, w.units_of_measure or "", "", "", "", None, None, ""])
        for n in rows:
            m = mats[n.material_id]
            ws.append([w.item_code, w.item_name, w.units_of_measure or "", m.item_code, m.item_name, material_unit(db, m),
                       float(n.qty_per_unit or 0), float(n.wastage_pct or 0), n.remarks or ""])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    for col, width in zip("ABCDEFGHI", (16, 40, 10, 16, 36, 12, 18, 11, 30)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    how = wb.create_sheet("How to fill")
    for t in ("One row for each material a work item uses. Put the work item's code on every row of its materials.",
              "Qty per 1 work unit: how much of the material ONE unit of the work uses, in the material's unit "
              "(1 cum of PCC M15 uses 4.4 Bags of cement: 4.4).",
              "Wastage %: added on top when the Item sheet works out a BOQ line's quantity. Leave blank for none.",
              "A work item in the file gets exactly the materials listed for it. One listed with no material has its norms cleared.",
              "Work items not in the file keep their norms as they are. Names and units are for reading; the codes are what count.",
              "Nothing is saved if any row has a problem: every problem is listed, to fix and upload again."):
        how.append([t])
    how.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_upload(db, client_id, content, who):
    """Norms from the sheet, all or nothing: {work_items, materials}."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
    except Exception:
        raise HTTPException(400, "That file could not be read. Upload the .xlsx downloaded from here, filled in.")
    ws = wb["Norms"] if "Norms" in wb.sheetnames else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    head = [re.sub(r"[^a-z0-9]", "", str(h or "").lower()) for h in next(it, [])]
    want = {"work": "workitemcode", "material": "materialcode", "qty": "qtyper1workunit", "waste": "wastage", "remarks": "remarks"}
    col = {k: next((i for i, h in enumerate(head) if h.startswith(v)), None) for k, v in want.items()}
    if col["work"] is None or col["material"] is None or col["qty"] is None:
        raise HTTPException(400, "The columns Work item code, Material code and Qty per 1 work unit were not found. Download the template and fill that.")
    cell = lambda row, k: row[col[k]] if col[k] is not None and col[k] < len(row) else None
    by_work, order, errors = {}, [], []
    for n, row in enumerate(it, 2):
        if n > MAX_ROWS:
            raise HTTPException(400, "That sheet has more than %d rows. Split it." % MAX_ROWS)
        work = str(cell(row, "work") or "").strip()
        mat = str(cell(row, "material") or "").strip()
        if not work and not mat:
            continue
        if not work:
            errors.append("Row %d: give the work item code." % n)
            continue
        k = _key(work)
        if k not in by_work:
            by_work[k] = (work, [])
            order.append(k)
        if mat or cell(row, "qty") not in (None, ""):
            by_work[k][1].append((n, {"item_code": mat, "qty_per_unit": cell(row, "qty"), "wastage_pct": cell(row, "waste"), "remarks": cell(row, "remarks") or ""}))
    works = {}
    if by_work:
        for w in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, func.lower(func.trim(models.DBItem.item_code)).in_(list(by_work))).all():
            works[_key(w.item_code)] = w
    saves = []
    for k in order:
        code, rows = by_work[k]
        w = works.get(k)
        if w is None:
            errors.append("Work item %s is not in the Item Master." % code)
            continue
        if w.kind != "FG":
            errors.append("%s %s is a store material, not a work item: norms go on work items." % (w.item_code, w.item_name))
            continue
        values, problems = check_rows(db, client_id, [r for _, r in rows], label=lambda i, rows=rows: "Row %d" % rows[i - 1][0])
        errors.extend(problems)
        saves.append((w, values))
    if errors:
        raise HTTPException(400, "Nothing was saved. Fix these and upload again:\n" + "\n".join(errors[:200]))
    if not saves:
        raise HTTPException(400, "The sheet has no rows.")
    for w, values in saves:
        replace_norms(db, client_id, w, values, who)
    return {"work_items": len(saves), "materials": sum(len(v) for _, v in saves)}
