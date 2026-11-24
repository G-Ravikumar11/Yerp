"""Store - the project's Item sheet.

A project's list of the materials it will need: each line a BOQ group code (picked from the codes on the project's BOQ),
an item from the item master (its HSN and unit come from the master), a quantity in the item's base unit, and remarks.
It is made in the app, or downloaded as an Excel template, filled in and uploaded. Nothing comes from the budget.

    DRAFT -> SUBMITTED -> APPROVED (Master)          sent back by the Master: DRAFT again, with the reason
    APPROVED, then changed -> DRAFT                  the approved copy stays in force until the change is approved

Once a project has an approved sheet the store goes by it: an indent for the project may ask only for items on the sheet,
and asking for more than the sheet's quantity (with the project's other live indents) is warned, not stopped.
"""
import io
import json
from datetime import datetime
from decimal import Decimal

import openpyxl
from fastapi import HTTPException
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from app import models
from app.models.item_sheet import SHEET_APPROVED, SHEET_DRAFT, SHEET_SUBMITTED, DBItemSheet, DBItemSheetLine

ZERO = Decimal("0")
HEADERS = ["Group code", "Item code", "Item name", "HSN", "Unit", "Quantity", "Remarks"]
# Indents that hold nothing yet, or never will.
NOT_LIVE = ("DRAFT", "CANCELLED", "REJECTED")


def _q(v) -> float:
    return round(float(v or 0), 3)


def _key(s) -> str:
    return " ".join(str(s or "").split()).lower()


def boq_groups(db, client_id, job_id):
    """The group codes on the project's BOQ as it stands, in BOQ order; [] when there is no BOQ or no codes."""
    from app.services.boq import boq_of_job
    boq = boq_of_job(db, client_id, job_id)
    if boq is None:
        return []
    rev = db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq.id, models.DBBoqRevision.rev_no == boq.current_rev).first()
    if rev is None:
        return []
    out, seen = [], set()
    for (code,) in (db.query(models.DBBoqLine.group_code).filter(models.DBBoqLine.revision_id == rev.id, models.DBBoqLine.group_code != "")
                    .order_by(models.DBBoqLine.display_order).all()):
        c = (code or "").strip()
        if c and _key(c) not in seen:
            seen.add(_key(c))
            out.append(c)
    return out


def job_of(db, client_id, job_id):
    job = db.query(models.DBJob).filter(models.DBJob.id == job_id, models.DBJob.client_id == client_id).first()
    if job is None:
        raise HTTPException(404, "Project not found")
    return job


def sheet_of(db, client_id, job_id):
    return db.query(DBItemSheet).filter(DBItemSheet.client_id == client_id, DBItemSheet.job_id == job_id).first()


def lines_of(db, sheet):
    if sheet is None:
        return []
    return db.query(DBItemSheetLine).filter(DBItemSheetLine.sheet_id == sheet.id).order_by(DBItemSheetLine.line_no, DBItemSheetLine.id).all()


def _unit(db, item):
    from app.services.store_outward import base_uom_of
    return base_uom_of(db, item) or item.units_of_measure or ""


def approved_need(db, client_id, job_id):
    """{item_id: quantity} by the sheet the Master last approved, all group codes added up; None when the project has none."""
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None or not sheet.approved_lines:
        return None
    need = {}
    for l in json.loads(sheet.approved_lines):
        need[l["item_id"]] = need.get(l["item_id"], 0.0) + float(l["qty"] or 0)
    return need


def indented(db, client_id, job_id, exclude_indent_id=None):
    """{item_id: quantity} the project's live indents ask for: the approved quantity once approved, else what was asked."""
    from app.models.store_outward import DBStoreIndent, DBStoreIndentLine
    q = (db.query(DBStoreIndentLine.item_id, DBStoreIndentLine.qty, DBStoreIndentLine.approved_qty, DBStoreIndent.status)
         .join(DBStoreIndent, DBStoreIndent.id == DBStoreIndentLine.indent_id)
         .filter(DBStoreIndent.client_id == client_id, DBStoreIndent.project_id == job_id, DBStoreIndent.status.notin_(NOT_LIVE)))
    if exclude_indent_id:
        q = q.filter(DBStoreIndent.id != exclude_indent_id)
    out = {}
    for item_id, qty, approved, status in q.all():
        v = approved if approved is not None and status != "SUBMITTED" else qty
        out[item_id] = out.get(item_id, ZERO) + Decimal(str(v or 0))
    return out


def sheet_dict(db, client_id, job):
    sheet = sheet_of(db, client_id, job.id)
    rows = lines_of(db, sheet)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([l.item_id for l in rows] or [0])).all()}
    need = approved_need(db, client_id, job.id)
    asked = indented(db, client_id, job.id) if need is not None else {}
    lines = []
    for l in rows:
        it = items.get(l.item_id)
        lines.append({"id": l.id, "group_code": l.group_code, "item_id": l.item_id, "item_code": it.item_code if it else "", "item_name": it.item_name if it else "",
                      "hsn": (it.hsn_code or "") if it else "", "unit": _unit(db, it) if it else "", "qty": _q(l.qty), "remarks": l.remarks or ""})
    on_sheet = {l["item_id"] for l in lines}
    approved = json.loads(sheet.approved_lines) if sheet is not None and sheet.approved_lines else []
    changed = sheet is not None and sheet.approved_lines is not None and sorted((a["group_code"], a["item_id"], _q(a["qty"])) for a in approved) != \
        sorted((l["group_code"], l["item_id"], l["qty"]) for l in lines)
    usage = []
    if need is not None:
        names = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(set(need) | set(asked)) or [0])).all()}
        for item_id in sorted(set(need) | set(asked), key=lambda i: (names[i].item_name if i in names else "")):
            it = names.get(item_id)
            usage.append({"item_id": item_id, "item_code": it.item_code if it else "", "item_name": it.item_name if it else "", "unit": _unit(db, it) if it else "",
                          "sheet_qty": _q(need.get(item_id)), "indented": _q(asked.get(item_id)), "on_sheet": item_id in need})
    return {"job_id": job.id, "code": getattr(job, "number", "") or "", "name": job.name or "", "exists": sheet is not None,
            "status": sheet.status if sheet else None, "groups": boq_groups(db, client_id, job.id), "lines": lines,
            "approved": sheet is not None and sheet.approved_lines is not None, "changed_since_approval": changed,
            "approved_by": sheet.approved_by_name if sheet else "", "approved_at": sheet.approved_at.isoformat(timespec="seconds") if sheet and sheet.approved_at else "",
            "submitted_by": sheet.submitted_by_name if sheet else "", "submitted_at": sheet.submitted_at.isoformat(timespec="seconds") if sheet and sheet.submitted_at else "",
            "returned_note": sheet.returned_note if sheet else "", "updated_by": sheet.updated_by_name if sheet else "",
            "updated_at": sheet.updated_at.isoformat(timespec="seconds") if sheet and sheet.updated_at else "",
            "usage": usage, "item_count": len(on_sheet)}


def check_rows(db, client_id, job_id, rows):
    """Rows [{group_code, item_code, qty, remarks, row}] turned into lines, or every problem found: (lines, errors). Nothing
    is half-saved - a sheet with any error is not saved at all."""
    groups = {_key(g): g for g in boq_groups(db, client_id, job_id)}
    errors, out, seen = [], [], set()
    codes = {_key(r.get("item_code")) for r in rows if _key(r.get("item_code"))}
    from sqlalchemy import func
    items = {}
    if codes:
        for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, func.lower(func.trim(models.DBItem.item_code)).in_(codes)).all():
            items[_key(it.item_code)] = it
    if not groups:
        errors.append("The project's BOQ has no group codes. Give its lines group codes (RCC, PCC ...) under Clients > BOQ first.")
        return [], errors
    for n, r in enumerate(rows, 1):
        label = "Row %s" % r.get("row", n)
        g, code = _key(r.get("group_code")), _key(r.get("item_code"))
        if not g and not code and r.get("qty") in (None, "", 0):
            continue
        bad = False
        if g not in groups:
            errors.append("%s: group code '%s' is not on the project's BOQ." % (label, r.get("group_code") or ""))
            bad = True
        it = items.get(code)
        if not code:
            errors.append("%s: give the item code." % label)
            bad = True
        elif it is None:
            errors.append("%s: item code '%s' is not in the item master." % (label, r.get("item_code")))
            bad = True
        elif it.kind != "RM" or it.merged_into_id:
            errors.append("%s: %s is not a stock item that is in use." % (label, it.item_code))
            bad = True
        try:
            qty = float(r.get("qty"))
        except (TypeError, ValueError):
            qty = 0.0
        if not qty > 0:
            errors.append("%s: give a quantity above 0." % label)
            bad = True
        if bad:
            continue
        if (g, it.id) in seen:
            errors.append("%s: %s is under %s twice." % (label, it.item_code, groups[g]))
            continue
        seen.add((g, it.id))
        out.append({"group_code": groups[g], "item_id": it.id, "qty": round(qty, 3), "remarks": str(r.get("remarks") or "").strip()[:300]})
    if not out and not errors:
        errors.append("Add at least one line.")
    return out, errors


def save_lines(db, client_id, job_id, lines, who):
    """Replace the sheet's lines (made if new). An approved or submitted sheet that is changed goes back to draft; the copy
    last approved stays in force."""
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None:
        sheet = DBItemSheet(client_id=client_id, job_id=job_id, status=SHEET_DRAFT)
        db.add(sheet)
        db.flush()
    db.query(DBItemSheetLine).filter(DBItemSheetLine.sheet_id == sheet.id).delete(synchronize_session=False)
    for n, l in enumerate(lines, 1):
        db.add(DBItemSheetLine(sheet_id=sheet.id, line_no=n, **l))
    sheet.status = SHEET_DRAFT
    sheet.updated_by_name, sheet.updated_at = who, datetime.now()
    db.flush()
    return sheet


def submit(db, client_id, job_id, who):
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None or not lines_of(db, sheet):
        raise HTTPException(400, "Add the sheet's lines before sending it for approval.")
    if sheet.status != SHEET_DRAFT:
        raise HTTPException(409, "It is %s already." % ("waiting for the Master" if sheet.status == SHEET_SUBMITTED else "approved"))
    sheet.status, sheet.submitted_by_name, sheet.submitted_at, sheet.returned_note = SHEET_SUBMITTED, who, datetime.now(), ""
    return sheet


def approve(db, client_id, job_id, who):
    sheet = sheet_of(db, client_id, job_id)
    rows = lines_of(db, sheet)
    if sheet is None or not rows:
        raise HTTPException(400, "There is no sheet to approve.")
    if sheet.status == SHEET_APPROVED:
        raise HTTPException(409, "It is approved already.")
    sheet.approved_lines = json.dumps([{"group_code": l.group_code, "item_id": l.item_id, "qty": l.qty} for l in rows])
    sheet.status, sheet.approved_by_name, sheet.approved_at, sheet.returned_note = SHEET_APPROVED, who, datetime.now(), ""
    return sheet


def send_back(db, client_id, job_id, note):
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None or sheet.status != SHEET_SUBMITTED:
        raise HTTPException(409, "Only a sheet waiting for approval can be sent back.")
    note = (note or "").strip()
    if not note:
        raise HTTPException(400, "Say what has to change.")
    sheet.status, sheet.returned_note = SHEET_DRAFT, note[:300]
    return sheet


# --- the store going by it -------------------------------------------------------------------------------------------------

def check_indent(db, client_id, job_id, items):
    """An indent for a project with an approved sheet may ask only for items on it. `items`: the DBItems asked for."""
    need = approved_need(db, client_id, job_id)
    if need is None:
        return
    off = [it for it in items if it.id not in need]
    if off:
        raise HTTPException(400, "%s %s not on the project's approved Item sheet. Add %s to the sheet and have the Master approve it first." % (
            ", ".join("%s %s" % (it.item_code, it.item_name) for it in off), "is" if len(off) == 1 else "are", "it" if len(off) == 1 else "them"))


def indent_warnings(db, indent, lines):
    """Where this indent, with the project's other live indents, asks for more than the approved sheet's quantity."""
    need = approved_need(db, indent.client_id, indent.project_id)
    if need is None:
        return []
    others = indented(db, indent.client_id, indent.project_id, exclude_indent_id=indent.id)
    mine = {}
    for l in lines:
        v = l.approved_qty if l.approved_qty is not None and indent.status != "SUBMITTED" else l.qty
        mine[l.item_id] = mine.get(l.item_id, ZERO) + Decimal(str(v or 0))
    out = []
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(mine) or [0])).all()}
    for item_id, q in mine.items():
        if item_id not in need:
            continue
        total = q + others.get(item_id, ZERO)
        if total > Decimal(str(need[item_id])) + Decimal("0.0005"):
            it = items[item_id]
            u = _unit(db, it)
            out.append("%s: %s %s asked for on this project's indents with this one, against %s %s on its approved Item sheet." % (
                it.item_name, _fmt(total), u, _fmt(need[item_id]), u))
    return out


def _fmt(v) -> str:
    return ("%.3f" % float(v)).rstrip("0").rstrip(".")


# --- Excel ---------------------------------------------------------------------------------------------------------------

def workbook(db, client_id, job):
    """The template, with the sheet's lines already in it when it has some: fill it, or change it, and upload it back."""
    d = sheet_dict(db, client_id, job)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Item sheet"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for l in d["lines"]:
        ws.append([l["group_code"], l["item_code"], l["item_name"], l["hsn"], l["unit"], l["qty"], l["remarks"]])
    for col, w in zip("ABCDEFG", (14, 18, 36, 12, 10, 12, 30)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    lists = wb.create_sheet("BOQ group codes")
    lists.append(["Group codes on the BOQ of %s" % (d["name"] or "the project")])
    lists["A1"].font = Font(bold=True)
    for g in d["groups"]:
        lists.append([g])
    if d["groups"]:
        dv = DataValidation(type="list", formula1="='BOQ group codes'!$A$2:$A$%d" % (len(d["groups"]) + 1), allow_blank=True,
                            error="Pick a group code from the project's BOQ.", errorTitle="Group code", showErrorMessage=True)
        ws.add_data_validation(dv)
        dv.add("A2:A2000")
    notes = wb.create_sheet("How to fill")
    for t in ("Group code: one of the codes on the 'BOQ group codes' tab (the project's BOQ).",
              "Item code: the item's code from the item master. Item name, HSN and unit are filled from the master on upload;",
              "    what is typed in those columns is not read.",
              "Quantity: in the item's unit (the Unit column). The same item may be under more than one group code.",
              "Uploading replaces the whole sheet. It then needs the Master's approval before the store goes by it."):
        notes.append([t])
    notes.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_upload(content: bytes):
    """Rows of an uploaded sheet: the first row that has an 'Item code' heading is the heading row."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True, keep_links=False)
    except Exception:
        raise HTTPException(400, "That is not an Excel workbook (.xlsx). Download the template and fill that.")
    ws = wb["Item sheet"] if "Item sheet" in wb.sheetnames else wb.worksheets[0]
    cols, rows = None, []
    for n, r in enumerate(ws.iter_rows(values_only=True), 1):
        cells = [_key(c) for c in r]
        if cols is None:
            if "item code" in cells:
                cols = {h: cells.index(h) for h in ("group code", "item code", "quantity", "qty", "remarks") if h in cells}
            continue
        get = lambda h: r[cols[h]] if h in cols and cols[h] < len(r) else None
        rows.append({"row": n, "group_code": get("group code"), "item_code": get("item code"),
                     "qty": get("quantity") if "quantity" in cols else get("qty"), "remarks": get("remarks")})
    if cols is None or "group code" not in cols:
        raise HTTPException(400, "The sheet has no 'Group code' and 'Item code' headings. Download the template and fill that.")
    return rows
