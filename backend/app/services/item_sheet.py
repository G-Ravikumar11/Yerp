"""Store - the project's Item sheet.

The project's BOQ, as it stands, grouped by its group codes (RCC, PCC, Masonry ...): under every BOQ line, the store
materials that line needs - each an item of the Item Master (its HSN and unit come from there) with the quantity in the
item's base unit. It is made in the app, or downloaded as an Excel template (one row per BOQ line and material), filled in
and uploaded. Nothing comes from the budget.

    DRAFT -> SUBMITTED -> APPROVED (Master)          sent back by the Master: DRAFT again, with the reason
    APPROVED, then changed -> DRAFT                  the approved copy stays in force until the change is approved

Once a project has an approved sheet the store and purchase go by it:

    an indent for the project may ask only for items on the sheet          past the sheet's quantity: warned
    a purchase order for the project may buy only items on the sheet        past the sheet's quantity: flagged
    (lines with no item code - freight, loading - are not items and pass)

and the sheet follows each material through the store: ordered (approved orders), awaiting approval, received (accepted on
posted goods receipts), indented, issued (net of returns) and at site - per BOQ line where the document names the line, and
for the project in all.
"""
import io
import json
from datetime import datetime
from decimal import Decimal

import openpyxl
from fastapi import HTTPException
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func

from app import models
from app.models.item_sheet import SHEET_APPROVED, SHEET_DRAFT, SHEET_SUBMITTED, DBItemSheet, DBItemSheetLine, DBItemSheetMaterial

ZERO = Decimal("0")
HEADERS = ["Group code", "BOQ item no", "BOQ work", "BOQ unit", "BOQ qty", "Item code", "Item name", "HSN", "Unit", "Quantity", "Remarks", "Line ref"]
# Indents that hold nothing yet, or never will.
NOT_LIVE = ("DRAFT", "CANCELLED", "REJECTED")
# Purchase orders: what has been placed, and what is still on its way to being placed.
PO_PLACED = ("Approved", "Closed")
PO_AWAITING = ("Draft", "Awaiting Approval")
NO_GROUP = ""


def _q(v) -> float:
    return round(float(v or 0), 3)


def _key(s) -> str:
    return " ".join(str(s or "").split()).lower()


def _first_line(text) -> str:
    return (text or "").strip().split("\n")[0][:200]


# --- the BOQ -----------------------------------------------------------------------------------------------------------

def boq_lines(db, client_id, job_id):
    """(the BOQ's priced lines as it stands, in BOQ order; {line id: key} over every revision). Store documents name a BOQ
    line by its id, which may be a line of an older revision: its key is the same throughout."""
    from app.services.boq import boq_lines_of_job, boq_of_job
    boq = boq_of_job(db, client_id, job_id)
    if boq is None:
        return [], {}
    key_of = dict(db.query(models.DBBoqLine.id, models.DBBoqLine.key).filter(models.DBBoqLine.boq_id == boq.id).all())
    return boq_lines_of_job(db, client_id, job_id), key_of


def boq_groups(db, client_id, job_id):
    """The group codes on the project's BOQ as it stands, in BOQ order."""
    out, seen = [], set()
    for l in boq_lines(db, client_id, job_id)[0]:
        c = (l.group_code or "").strip()
        if c and _key(c) not in seen:
            seen.add(_key(c))
            out.append(c)
    return out


def _grouped(lines):
    """[(group code, [lines])] in the order the groups first appear; lines with no group code together at the end."""
    order, by = [], {}
    for l in lines:
        g = (l.group_code or "").strip()
        k = _key(g)
        if k not in by:
            by[k] = (g, [])
            order.append(k)
        by[k][1].append(l)
    if NO_GROUP in order:
        order.remove(NO_GROUP)
        order.append(NO_GROUP)
    return [by[k] for k in order]


def job_of(db, client_id, job_id):
    job = db.query(models.DBJob).filter(models.DBJob.id == job_id, models.DBJob.client_id == client_id).first()
    if job is None:
        raise HTTPException(404, "Project not found")
    return job


def sheet_of(db, client_id, job_id):
    return db.query(DBItemSheet).filter(DBItemSheet.client_id == client_id, DBItemSheet.job_id == job_id).first()


def materials_of(db, sheet):
    if sheet is None:
        return []
    return db.query(DBItemSheetMaterial).filter(DBItemSheetMaterial.sheet_id == sheet.id).order_by(DBItemSheetMaterial.line_no, DBItemSheetMaterial.id).all()


def adopt_old_lines(db, sheet, lines):
    """A sheet saved in the first form (a material under a group code only): its lines go under the first BOQ line of their
    group - or the BOQ's first line, saying so, when the group is no longer on it. Returns whether anything moved."""
    if sheet is None:
        return False
    old = db.query(DBItemSheetLine).filter(DBItemSheetLine.sheet_id == sheet.id).order_by(DBItemSheetLine.line_no, DBItemSheetLine.id).all()
    if not old or not lines:
        return False
    first = {}
    for l in lines:
        first.setdefault(_key(l.group_code), l)
    have = {(m.boq_key, m.item_id): m for m in materials_of(db, sheet)}
    n = len(have)
    for o in old:
        line = first.get(_key(o.group_code))
        note = o.remarks or ""
        if line is None:
            line = lines[0]
            note = ("%s (was under group %s)" % (note, o.group_code)).strip()
        m = have.get((line.key, o.item_id))
        if m is not None:
            m.qty = round((m.qty or 0) + (o.qty or 0), 3)
            continue
        n += 1
        m = DBItemSheetMaterial(sheet_id=sheet.id, line_no=n, boq_key=line.key, group_code=(line.group_code or "").strip(), item_id=o.item_id,
                                qty=o.qty or 0, remarks=note[:300])
        db.add(m)
        have[(line.key, o.item_id)] = m
    for o in old:
        db.delete(o)
    db.flush()
    return True


def _unit(db, item):
    from app.services.store_outward import base_uom_of
    return base_uom_of(db, item) or item.units_of_measure or ""


def _items(db, ids):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(set(ids)) or [0])).all()}


# --- what the store and purchase have done -----------------------------------------------------------------------------

def approved_need(db, client_id, job_id):
    """{item_id: quantity} by the sheet the Master last approved, every BOQ line added up; None when the project has none."""
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None or not sheet.approved_lines:
        return None
    need = {}
    for l in json.loads(sheet.approved_lines):
        need[l["item_id"]] = need.get(l["item_id"], 0.0) + float(l["qty"] or 0)
    return need


def indented(db, client_id, job_id, exclude_indent_id=None, by_line=False):
    """What the project's live indents ask for - the approved quantity once approved, else what was asked: {item_id: qty},
    or with by_line {(boq line id, item_id): qty}."""
    from app.models.store_outward import DBStoreIndent, DBStoreIndentLine
    q = (db.query(DBStoreIndentLine.item_id, DBStoreIndentLine.qty, DBStoreIndentLine.approved_qty, DBStoreIndent.status, DBStoreIndent.boq_item_id)
         .join(DBStoreIndent, DBStoreIndent.id == DBStoreIndentLine.indent_id)
         .filter(DBStoreIndent.client_id == client_id, DBStoreIndent.project_id == job_id, DBStoreIndent.status.notin_(NOT_LIVE)))
    if exclude_indent_id:
        q = q.filter(DBStoreIndent.id != exclude_indent_id)
    out = {}
    for item_id, qty, approved, status, boq_id in q.all():
        v = Decimal(str((approved if approved is not None and status != "SUBMITTED" else qty) or 0))
        k = (boq_id, item_id) if by_line else item_id
        out[k] = out.get(k, ZERO) + v
    return out


def _orders(db, client_id, job_id):
    return (db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.job_id == job_id)
            .order_by(models.DBPurchaseOrder.id.desc()).all())


def tracking(db, client_id, job_id, key_of):
    """Every figure the sheet shows beside its materials, in each item's base unit:
    ({item_id: {ordered, awaiting, received, indented, issued, at_site}}, {(boq key, item_id): {ordered, received, indented,
    issued}}, the project's orders with their lines)."""
    from app.models.store_core import DBStore, DBStoreStockBalance
    from app.services.store_integration import material_cost_rows
    from app.services.store_inward import po_receipt_summaries, short_closed
    blank = lambda: {"ordered": ZERO, "awaiting": ZERO, "received": ZERO, "indented": ZERO, "issued": ZERO, "at_site": ZERO}
    per_item, per_line = {}, {}

    def add(item_id, field, qty, boq_key=None):
        per_item.setdefault(item_id, blank())[field] += qty
        if boq_key:
            per_line.setdefault((boq_key, item_id), blank())[field] += qty

    orders = _orders(db, client_id, job_id)
    summaries, lines_by, items, units = po_receipt_summaries(db, orders) if orders else ({}, {}, {}, None)
    order_rows = []
    for po in orders:
        sm = {s.po_line_id: s for s in summaries.get(po.id, [])}
        rows = []
        for l in lines_by.get(po.id, []):
            item, s = items.get(l.id), sm.get(l.id)
            row = {"po_line_id": l.id, "item_id": item.id if item else None, "item_code": item.item_code if item else (l.item_code or ""),
                   "item_name": item.item_name if item else (l.description or ""), "boq_key": l.boq_key or "",
                   "unit": (units.base.get(item.id, "") if item and units else "") or (l.uom or ""), "po_qty": _q(l.qty), "po_uom": l.uom or "",
                   "price": round(float(l.price or 0), 4), "ordered": _q(s.ordered_qty) if s else _q(l.qty), "received": _q(s.accepted_qty) if s else 0.0,
                   "pending": _q(s.pending_qty) if s else 0.0}
            rows.append(row)
            if item is None or s is None:
                continue
            if po.status in PO_PLACED:
                add(item.id, "ordered", s.ordered_qty, l.boq_key)
                add(item.id, "received", s.accepted_qty, l.boq_key)
            elif po.status in PO_AWAITING:
                add(item.id, "awaiting", s.ordered_qty, l.boq_key)
        order_rows.append({"id": po.id, "number": po.number or "", "supplier": po.supplier_name or "", "status": po.status or "",
                           "date": (po.issue_date or "")[:10], "total": round(float(po.total or 0), 2), "lines": rows,
                           "receivable": po.status == "Approved" and any(r["pending"] > 0 and r["item_id"] for r in rows) and not short_closed(db, po.id)})
    for (boq_id, item_id), qty in indented(db, client_id, job_id, by_line=True).items():
        add(item_id, "indented", qty, key_of.get(boq_id))
    for _p, _h, _w, boq_id, item_id, qty, _v in material_cost_rows(db, client_id, project_id=job_id):
        add(item_id, "issued", qty, key_of.get(boq_id))
    for item_id, qty in (db.query(DBStoreStockBalance.item_id, func.sum(DBStoreStockBalance.qty)).join(DBStore, DBStore.id == DBStoreStockBalance.store_id)
                         .filter(DBStore.client_id == client_id, DBStore.project_id == job_id).group_by(DBStoreStockBalance.item_id).all()):
        if qty:
            add(item_id, "at_site", Decimal(str(qty)))
    return per_item, per_line, order_rows


def _documents(db, client_id, job_id, key_of, lines_by_key):
    """The project's goods receipts, indents and issues, newest first, for the sheet's Documents tab."""
    from app.models.store_core import DBStore
    from app.models.store_inward import DBStoreGrn
    from app.models.store_outward import DBStoreIndent, DBStoreIssue
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == client_id).all()}
    po_ids = [i for (i,) in db.query(models.DBPurchaseOrder.id).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.job_id == job_id).all()]
    pos = dict(db.query(models.DBPurchaseOrder.id, models.DBPurchaseOrder.number).filter(models.DBPurchaseOrder.id.in_(po_ids or [0])).all())
    grns = (db.query(DBStoreGrn).filter(DBStoreGrn.client_id == client_id)
            .filter((DBStoreGrn.project_id == job_id) | (DBStoreGrn.po_id.in_(po_ids or [0]))).order_by(DBStoreGrn.id.desc()).limit(100).all())
    indents = db.query(DBStoreIndent).filter(DBStoreIndent.client_id == client_id, DBStoreIndent.project_id == job_id).order_by(DBStoreIndent.id.desc()).limit(100).all()
    issues = db.query(DBStoreIssue).filter(DBStoreIssue.client_id == client_id, DBStoreIssue.project_id == job_id).order_by(DBStoreIssue.id.desc()).limit(100).all()
    numbers = dict(db.query(DBStoreIndent.id, DBStoreIndent.number).filter(DBStoreIndent.id.in_([i.indent_id for i in issues if i.indent_id] or [0])).all())
    code = lambda sid: stores[sid].code if sid in stores else ""
    day = lambda d: d.isoformat() if d else ""

    def boq_label(boq_id):
        line = lines_by_key.get(key_of.get(boq_id))
        return ("%s %s" % (line.item_no or "", _first_line(line.description)[:60])).strip() if line is not None else ""
    return {
        "receipts": [{"id": g.id, "number": g.number, "status": g.status, "date": day(g.grn_date), "po_id": g.po_id, "po_number": pos.get(g.po_id, ""),
                      "supplier": g.supplier_name or "", "store_code": code(g.store_id)} for g in grns],
        "indents": [{"id": i.id, "number": i.number, "status": i.status, "date": day(i.indent_date), "store_id": i.store_id, "store_code": code(i.store_id),
                     "boq_key": key_of.get(i.boq_item_id) or "", "boq_item": boq_label(i.boq_item_id), "activity": i.activity or "",
                     "requested_by": i.requested_by_name or ""} for i in indents],
        "issues": [{"id": i.id, "number": i.number, "status": i.status, "date": day(i.issue_date), "store_code": code(i.store_id),
                    "indent_id": i.indent_id, "indent_number": numbers.get(i.indent_id, ""), "received_by": i.received_by_name or ""} for i in issues],
    }


def _stores(db, actor, job_id):
    """Stores the person can work in, the project's own first: for the receive, indent and issue forms."""
    from app.models.store_core import DBStore
    from app.routers.store_masters import visible_store_ids
    q = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    seen = visible_store_ids(db, actor)
    if seen is not None:
        q = q.filter(DBStore.id.in_(seen or {0}))
    rows = [s for s in q.all() if s.is_active is not False]
    rows.sort(key=lambda s: (s.project_id != job_id, s.code or ""))
    return [{"id": s.id, "code": s.code, "name": s.name, "type": s.type, "this_project": s.project_id == job_id} for s in rows]


def sheet_dict(db, actor, job):
    from app.core.units import UNITS_OF_MEASURE
    client_id = actor.client.id
    sheet = sheet_of(db, client_id, job.id)
    lines, key_of = boq_lines(db, client_id, job.id)
    mats = materials_of(db, sheet)
    items = _items(db, [m.item_id for m in mats])
    need = approved_need(db, client_id, job.id)
    per_item, per_line, orders = tracking(db, client_id, job.id, key_of)
    items.update(_items(db, [i for i in per_item if i not in items]))
    keys = {l.key for l in lines}
    by_key = {}
    for m in mats:
        by_key.setdefault(m.boq_key, []).append(m)

    def material(m):
        it = items.get(m.item_id)
        t = per_line.get((m.boq_key, m.item_id), {})
        return {"id": m.id, "boq_key": m.boq_key, "item_id": m.item_id, "item_code": it.item_code if it else "", "item_name": it.item_name if it else "",
                "hsn": (it.hsn_code or "") if it else "", "unit": _unit(db, it) if it else "", "qty": _q(m.qty), "remarks": m.remarks or "",
                "ordered": _q(t.get("ordered")), "awaiting": _q(t.get("awaiting")), "received": _q(t.get("received")), "indented": _q(t.get("indented")),
                "issued": _q(t.get("issued"))}

    groups = []
    for code, ls in _grouped(lines):
        groups.append({"code": code, "lines": [{"key": l.key, "line_id": l.id, "item_no": l.item_no or "", "description": _first_line(l.description),
                                                 "unit": l.uom or "", "qty": _q(l.quantity), "boq_item_code": l.item_code or "",
                                                 "materials": [material(m) for m in by_key.get(l.key, [])]} for l in ls]})
    # Materials under a line the BOQ no longer has (taken out in a revision): still on the sheet, shown apart, to move or remove.
    orphans = [material(m) for m in mats if m.boq_key not in keys]

    required = {}
    for m in mats:
        required[m.item_id] = required.get(m.item_id, 0.0) + float(m.qty or 0)
    totals = []
    for item_id in sorted(set(required) | set(per_item), key=lambda i: (i not in required, items[i].item_name if i in items else "")):
        it, t = items.get(item_id), per_item.get(item_id, {})
        if it is None:
            continue
        req = required.get(item_id, 0.0)
        ordered, received = float(t.get("ordered", 0)), float(t.get("received", 0))
        totals.append({"item_id": item_id, "item_code": it.item_code, "item_name": it.item_name, "hsn": it.hsn_code or "", "unit": _unit(db, it),
                       "on_sheet": item_id in required, "required": _q(req), "approved_qty": _q(need.get(item_id)) if need is not None else None,
                       "ordered": _q(ordered), "awaiting": _q(t.get("awaiting")), "received": _q(received), "indented": _q(t.get("indented")),
                       "issued": _q(t.get("issued")), "at_site": _q(t.get("at_site")), "to_order": _q(max(0.0, req - ordered)),
                       "to_receive": _q(max(0.0, ordered - received))})

    approved = json.loads(sheet.approved_lines) if sheet is not None and sheet.approved_lines else []
    if approved and any("boq_key" not in a for a in approved):
        # Approved in the sheet's first form, which had no BOQ lines: the same items in the same quantities is no change.
        add_up = lambda pairs: sorted((i, _q(sum(q for j, q in pairs if j == i))) for i in {j for j, _q2 in pairs})
        changed = add_up([(a["item_id"], float(a["qty"] or 0)) for a in approved]) != add_up([(m.item_id, float(m.qty or 0)) for m in mats])
    else:
        changed = sheet is not None and sheet.approved_lines is not None and             sorted((a["boq_key"], a["item_id"], _q(a["qty"])) for a in approved) != sorted((m.boq_key, m.item_id, _q(m.qty)) for m in mats)
    stamp = lambda d: d.isoformat(timespec="seconds") if d else ""
    return {"job_id": job.id, "code": job.number or "", "name": job.name or "", "exists": sheet is not None,
            "status": sheet.status if sheet else None, "has_boq": bool(lines), "group_codes": [g["code"] for g in groups if g["code"]],
            "groups": groups, "orphans": orphans, "material_count": len(mats), "item_count": len(required),
            "approved": sheet is not None and sheet.approved_lines is not None, "changed_since_approval": changed,
            "approved_by": sheet.approved_by_name if sheet else "", "approved_at": stamp(sheet.approved_at) if sheet else "",
            "submitted_by": sheet.submitted_by_name if sheet else "", "submitted_at": stamp(sheet.submitted_at) if sheet else "",
            "returned_note": sheet.returned_note if sheet else "", "updated_by": sheet.updated_by_name if sheet else "",
            "updated_at": stamp(sheet.updated_at) if sheet else "",
            "totals": totals, "orders": orders, **_documents(db, client_id, job.id, key_of, {l.key: l for l in lines}),
            "stores": _stores(db, actor, job.id), "units": list(UNITS_OF_MEASURE), "is_master": actor.employee is None}


# --- saving it ---------------------------------------------------------------------------------------------------------

def check_rows(db, client_id, job_id, rows):
    """Rows [{boq_key or item_no, item_code, qty, remarks, row}] turned into materials, or every problem found: (materials,
    errors). Nothing is half-saved - a sheet with any error is not saved at all. Rows with no item code are BOQ lines with
    no material yet, and are passed over."""
    lines, _key_of = boq_lines(db, client_id, job_id)
    if not lines:
        return [], ["The project has no BOQ yet. Add it under Projects > BOQ first: the sheet's materials go under its lines."]
    by_key = {l.key: l for l in lines}
    by_no = {}
    for l in lines:
        if (l.item_no or "").strip():
            by_no.setdefault(_key(l.item_no), []).append(l)
    codes = {_key(r.get("item_code")) for r in rows if _key(r.get("item_code"))}
    items = {}
    if codes:
        for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, func.lower(func.trim(models.DBItem.item_code)).in_(codes)).all():
            items[_key(it.item_code)] = it
    errors, out, seen = [], [], set()
    for n, r in enumerate(rows, 1):
        label = "Row %s" % r.get("row", n)
        code = _key(r.get("item_code"))
        if not code:
            if r.get("qty") not in (None, "", 0, 0.0):
                errors.append("%s: give the item code of the material." % label)
            continue
        line = by_key.get(str(r.get("boq_key") or "").strip())
        if line is None and _key(r.get("item_no")):
            found = by_no.get(_key(r.get("item_no")), [])
            line = found[0] if len(found) == 1 else None
            if len(found) > 1:
                errors.append("%s: BOQ item no %s is on the BOQ more than once - keep the Line ref column as downloaded." % (label, r.get("item_no")))
                continue
        bad = False
        if line is None:
            errors.append("%s: that BOQ line is not on the project's BOQ as it stands. Download the template again and fill that." % label)
            bad = True
        it = items.get(code)
        if it is None:
            errors.append("%s: item code '%s' is not in the item master." % (label, r.get("item_code")))
            bad = True
        elif it.merged_into_id or it.is_active is False:
            errors.append("%s: %s %s is switched off in the item master." % (label, it.item_code, it.item_name))
            bad = True
        elif it.kind != "RM":
            errors.append("%s: %s %s is a BOQ work item, not a store material. If it is a material, change it to Material in the Item Master." % (label, it.item_code, it.item_name))
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
        if (line.key, it.id) in seen:
            errors.append("%s: %s is under BOQ line %s twice." % (label, it.item_code, line.item_no or _first_line(line.description)[:40]))
            continue
        seen.add((line.key, it.id))
        out.append({"boq_key": line.key, "group_code": (line.group_code or "").strip(), "item_id": it.id, "qty": round(qty, 3),
                    "remarks": str(r.get("remarks") or "").strip()[:300]})
    if not out and not errors:
        errors.append("Add at least one material.")
    return out, errors


def save_materials(db, client_id, job_id, mats, who, keep_keys=()):
    """Replace the sheet's materials (made if new). `keep_keys`: BOQ keys no longer on the BOQ whose materials stay as they
    are. A sheet that is changed goes back to draft; the copy last approved stays in force."""
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None:
        sheet = DBItemSheet(client_id=client_id, job_id=job_id, status=SHEET_DRAFT)
        db.add(sheet)
        db.flush()
    q = db.query(DBItemSheetMaterial).filter(DBItemSheetMaterial.sheet_id == sheet.id)
    if keep_keys:
        q = q.filter(DBItemSheetMaterial.boq_key.notin_(list(keep_keys)))
    q.delete(synchronize_session=False)
    db.query(DBItemSheetLine).filter(DBItemSheetLine.sheet_id == sheet.id).delete(synchronize_session=False)
    for n, m in enumerate(mats, 1):
        db.add(DBItemSheetMaterial(sheet_id=sheet.id, line_no=n, **m))
    sheet.status = SHEET_DRAFT
    sheet.updated_by_name, sheet.updated_at = who, datetime.now()
    db.flush()
    return sheet


def submit(db, client_id, job_id, who):
    sheet = sheet_of(db, client_id, job_id)
    if sheet is None or not materials_of(db, sheet):
        raise HTTPException(400, "Add the sheet's materials before sending it for approval.")
    if sheet.status != SHEET_DRAFT:
        raise HTTPException(409, "It is %s already." % ("waiting for the Master" if sheet.status == SHEET_SUBMITTED else "approved"))
    sheet.status, sheet.submitted_by_name, sheet.submitted_at, sheet.returned_note = SHEET_SUBMITTED, who, datetime.now(), ""
    return sheet


def approve(db, client_id, job_id, who):
    sheet = sheet_of(db, client_id, job_id)
    mats = materials_of(db, sheet)
    if sheet is None or not mats:
        raise HTTPException(400, "There is no sheet to approve.")
    if sheet.status == SHEET_APPROVED:
        raise HTTPException(409, "It is approved already.")
    sheet.approved_lines = json.dumps([{"boq_key": m.boq_key, "group_code": m.group_code, "item_id": m.item_id, "qty": m.qty} for m in mats])
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


def new_item(db, client_id, name, unit, hsn, make, who):
    """A store material added to the Item Master from the sheet, with the next item code. The master's own checks apply: a
    unit it does not know, or an item already there with the same details, is refused."""
    from app.schemas.item_master import MasterItemIn
    from app.services.item_master import create_master_item
    body = MasterItemIn(item_name=name or "", units_of_measure=unit or "", hsn_code=hsn or "", make=make or "", kind="RM", item_type="Purchased")
    return create_master_item(db, client_id, body, who)


# --- the store and purchase going by it --------------------------------------------------------------------------------

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
    items = _items(db, list(mine))
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


def check_order_lines(db, client_id, order, lines):
    """A purchase order for a project with an approved sheet: every line that names an item must name one on the sheet
    (lines with no item code - freight, loading - pass). Returns the flags for buying past the sheet's quantity, with the
    project's other live orders, as rate-flag rows {item_code, description, rate, last_rate, contract_rate, why, kind}."""
    if not order.job_id:
        return []
    need = approved_need(db, client_id, order.job_id)
    if need is None:
        return []
    from app.services.stock_ledger import BaseUnits
    codes = {_key(l.get("item_code")) for l in lines if _key(l.get("item_code"))}
    items = {}
    if codes:
        for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, func.lower(func.trim(models.DBItem.item_code)).in_(codes)).all():
            items[_key(it.item_code)] = it
    off = sorted({str(l.get("item_code")).strip() for l in lines if _key(l.get("item_code")) and (items.get(_key(l.get("item_code"))) is None
                                                                                                     or items[_key(l.get("item_code"))].id not in need)})
    if off:
        raise HTTPException(400, "%s %s not on the project's approved Item sheet, so %s cannot be bought for it. Add %s to the sheet and have the Master approve it first." % (
            ", ".join(off), "is" if len(off) == 1 else "are", "it" if len(off) == 1 else "they", "it" if len(off) == 1 else "them"))
    units = BaseUnits(db, {it.id for it in items.values()})
    this = {}
    for l in lines:
        it = items.get(_key(l.get("item_code")))
        if it is None:
            continue
        try:
            q = units.convert(it.id, Decimal(str(l.get("qty") or 0)), (l.get("uom") or "").strip() or units.base.get(it.id, ""))
        except Exception:
            continue                                         # a unit the item cannot be counted in: nothing to compare
        this[it.id] = this.get(it.id, ZERO) + q
    if not this:
        return []
    from app.services.store_inward import po_receipt_summaries
    others = [o for o in _orders(db, client_id, order.job_id) if o.id != order.id and o.status in PO_PLACED + PO_AWAITING]
    before = {}
    if others:
        summaries, _lines, po_items, _u = po_receipt_summaries(db, others)
        for rows in summaries.values():
            for s in rows:
                if s.item_id in this:
                    before[s.item_id] = before.get(s.item_id, ZERO) + s.ordered_qty
    out = []
    by_id = {it.id: it for it in items.values()}
    for item_id, q in this.items():
        total = q + before.get(item_id, ZERO)
        if total > Decimal(str(need[item_id])) + Decimal("0.0005"):
            it = by_id[item_id]
            out.append({"item_code": it.item_code, "description": it.item_name, "rate": 0, "last_rate": None, "contract_rate": None, "kind": "sheet",
                        "why": "past the Item sheet: %s %s ordered for the project with this order, against %s on its approved sheet" % (
                            _fmt(total), _unit(db, it), _fmt(need[item_id]))})
    return out


def _fmt(v) -> str:
    return ("%.3f" % float(v)).rstrip("0").rstrip(".")


# --- Excel ---------------------------------------------------------------------------------------------------------------

def workbook(db, actor, job):
    """The template: one row per BOQ line with no material yet, one per material of a line that has some - so it can be
    filled, or changed, and uploaded back. Only Item code, Quantity and Remarks are read, with Line ref saying which BOQ line."""
    client_id = actor.client.id
    lines, _key_of = boq_lines(db, client_id, job.id)
    sheet = sheet_of(db, client_id, job.id)
    mats = materials_of(db, sheet)
    items = _items(db, [m.item_id for m in mats])
    by_key = {}
    for m in mats:
        by_key.setdefault(m.boq_key, []).append(m)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Item sheet"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    grey = PatternFill("solid", fgColor="EEF2F7")
    for code, ls in _grouped(lines):
        for l in ls:
            boq = [code, l.item_no or "", _first_line(l.description), l.uom or "", _q(l.quantity)]
            rows = by_key.get(l.key) or [None]
            for m in rows:
                it = items.get(m.item_id) if m is not None else None
                ws.append(boq + ([it.item_code, it.item_name, it.hsn_code or "", _unit(db, it), _q(m.qty), m.remarks or ""] if it is not None
                                 else ["", "", "", "", None, ""]) + [l.key])
                for c in ws[ws.max_row][:5]:
                    c.fill = grey
    for col, w in zip("ABCDEFGHIJKL", (12, 11, 46, 9, 11, 16, 32, 11, 9, 11, 26, 14)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "F2"
    notes = wb.create_sheet("How to fill")
    for t in ("Every line of the project's BOQ is listed, grouped by its group code. Under each, put the store materials it needs:",
              "    Item code: the material's code in the Item Master. Item name, HSN and unit are filled from the master on upload.",
              "    Quantity: in the item's unit (the Unit column, or the item's unit in the master).",
              "    A BOQ line that needs several materials: copy its row, once for each material, keeping its Line ref.",
              "    Leave Item code empty on a line that needs no material.",
              "Line ref says which BOQ line the row is for - keep it as it is.",
              "Uploading replaces the whole sheet. It then needs the Master's approval before purchase and the store go by it."):
        notes.append([t])
    notes.column_dimensions["A"].width = 120
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
                cols = {h: cells.index(h) for h in ("line ref", "boq item no", "item code", "quantity", "qty", "remarks") if h in cells}
            continue
        get = lambda h: r[cols[h]] if h in cols and cols[h] < len(r) else None
        rows.append({"row": n, "boq_key": get("line ref"), "item_no": get("boq item no"), "item_code": get("item code"),
                     "qty": get("quantity") if "quantity" in cols else get("qty"), "remarks": get("remarks")})
    if cols is None or not ({"line ref", "boq item no"} & set(cols)):
        raise HTTPException(400, "The sheet has no 'Line ref' (or 'BOQ item no') and 'Item code' headings. Download the template and fill that.")
    return rows
