"""The project's Item sheet: every material the BOQ needs, added up item by item, with what the store and purchase have done
about it.

What a BOQ line needs comes from its budget (Projects > Budgeting): each MATERIAL row says how much of a material one unit
of the line takes. So for every material row

    required    = BOQ quantity x quantity per unit x (1 + wastage %)       the wastage % the budget is costed at
                                                                           (services/budget_wastage.py: the store's norm
                                                                           where one is set, else the budget's own)

in the item's base unit, and the same material on many BOQ lines is one row of the sheet, its lines listed under it. Beside
it, for the project:

    indented            what the project's indents asked for (approved quantity once approved; drafts and cancelled left out)
    ordered             what the project's purchase orders buy (drafts, rejected and cancelled left out)
    on its way          ordered and not yet received, on orders still open
    issued              what the store gave the project, net of what came back (the costing's own figure)
    at site             what the project's own stores hold now
    to arrange          required - issued - at site - on its way, never below nothing: what still has to be bought or
                        brought from another store

Nothing is stored: a budget row, an indent or an order changed is followed on the next read. A material typed in the budget
without picking it from the item master is listed too, under "Not in the item master", with its requirement only: the store
cannot count what it cannot name.
"""
from decimal import Decimal

from app import models
from app.core.currency import money
from app.services import budget_wastage

ZERO = Decimal("0")
NOT_INDENTED = ("DRAFT", "CANCELLED", "REJECTED")
NOT_ORDERED = ("Draft", "Rejected", "Cancelled")
OPEN_ORDER_DONE = ("Closed",)

COVERED, TO_ARRANGE, OVER_ISSUED, NO_BUDGET = "Covered", "To arrange", "Issued past need", "Not budgeted"


def _q(v) -> float:
    return round(float(v or 0), 3)


def _code(c) -> str:
    return (c or "").strip().lower()


def _boq(db, client_id, job_id):
    from app.services.boq import boq_lines_of_job, boq_of_job
    lines = [l for l in boq_lines_of_job(db, client_id, job_id) if (l.quantity or 0) > 0]
    boq = boq_of_job(db, client_id, job_id)
    # Store documents name a BOQ line by its id, which can be a line of an older revision: its key is the same throughout.
    key_of = {}
    if boq is not None:
        key_of = dict(db.query(models.DBBoqLine.id, models.DBBoqLine.key).filter(models.DBBoqLine.boq_id == boq.id).all())
    return boq, lines, key_of


def requirements(db, client_id, job_id):
    """The BOQ's need of every material: ({item_id or ("free", description, uom): row}, items by id, budget lines). Each
    row has the quantity required in the item's base unit and the BOQ lines it comes from."""
    from app.services.stock_ledger import BaseUnits
    _boq_row, lines, _key_of = _boq(db, client_id, job_id)
    by_key = {l.key: l for l in lines}
    rows = (db.query(models.DBBoqBudgetItem).filter(models.DBBoqBudgetItem.client_id == client_id, models.DBBoqBudgetItem.job_id == job_id,
                                                   models.DBBoqBudgetItem.kind == "MATERIAL")
            .order_by(models.DBBoqBudgetItem.boq_key, models.DBBoqBudgetItem.display_order, models.DBBoqBudgetItem.id).all())
    # In the BOQ's own order, so a material's lines read the way the BOQ does.
    at = {l.key: n for n, l in enumerate(lines)}
    rows = sorted((r for r in rows if r.boq_key in by_key), key=lambda r: (at[r.boq_key], r.display_order or 0, r.id))
    codes = {_code(r.item_code) for r in rows if _code(r.item_code)}
    items = {}
    if codes:
        from sqlalchemy import func
        for it in db.query(models.DBItem).filter(models.DBItem.client_id == client_id,
                                                 func.lower(func.trim(models.DBItem.item_code)).in_(list(codes))).order_by(models.DBItem.id).all():
            items.setdefault(_code(it.item_code), it)
    units = BaseUnits(db, {it.id for it in items.values()})
    norms = budget_wastage.norm_percents(db, client_id, [job_id])
    need = {}
    for r in rows:
        line = by_key[r.boq_key]
        resolved = budget_wastage.for_item(norms, job_id, r.boq_key, "MATERIAL", r.item_code, r.wastage_percent)
        qty = budget_wastage.quantities(line.quantity, r.coefficient, resolved)
        item = items.get(_code(r.item_code))
        per = units.per_unit(item.id, r.uom) if item is not None else None
        if item is not None and per is None:
            # The budget's unit has no conversion to the item's: counted as it is, and said so.
            per = Decimal(1)
            unit_note = "The budget gives this in %s, and the item master has no conversion from it to %s." % (r.uom, units.base.get(item.id) or "its unit")
        else:
            unit_note = ""
        per_f = float(per) if per is not None else 1.0
        key = item.id if item is not None else ("free", (r.description or "").strip().lower(), (r.uom or "").strip().lower())
        slot = need.get(key)
        if slot is None:
            slot = need[key] = {
                "item_id": item.id if item is not None else None,
                "item_code": item.item_code if item is not None else (r.item_code or ""),
                "item_name": item.item_name if item is not None else (r.description or ""),
                "uom": (units.base.get(item.id) or item.units_of_measure or "") if item is not None else (r.uom or ""),
                "in_master": item is not None, "required": 0.0, "base": 0.0, "value": 0.0, "unit_notes": [], "lines": []}
        slot["required"] += qty["final_quantity"] * per_f
        slot["base"] += qty["base_quantity"] * per_f
        slot["value"] += qty["final_quantity"] * (r.rate or 0)
        if unit_note and unit_note not in slot["unit_notes"]:
            slot["unit_notes"].append(unit_note)
        slot["lines"].append({"key": line.key, "boq_line_id": line.id, "item_no": line.item_no or "",
                              "description": (line.description or "").strip().split("\n")[0][:160], "boq_qty": _q(line.quantity), "boq_unit": line.uom or "",
                              "per_unit": r.coefficient or 0.0, "budget_unit": r.uom or "", "wastage_percent": resolved["effective_wastage_percent"],
                              "wastage_source": resolved["wastage_source"], "required": _q(qty["final_quantity"] * per_f), "issued": 0.0})
    return need, lines


def _project_stores(db, client_id, job_id):
    from app.models.store_core import DBStore
    return [s.id for s in db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.project_id == job_id).all()]


def store_figures(db, client_id, job_id, key_of):
    """{item_id: {indented, ordered, on_way, issued, at_site}} and {(item_id, BOQ key): issued} for the project, in base units."""
    from app.models.store_core import DBStoreStockBalance
    from app.models.store_outward import DBStoreIndent, DBStoreIndentLine
    from app.services.buying_links import DEAD_PO, _base, _items_by_code
    from app.services.procurement import OrderPrefetch
    from app.services.stock_ledger import BaseUnits
    from app.services.store_integration import material_cost_rows
    out = {}

    def slot(item_id):
        return out.setdefault(item_id, {"indented": ZERO, "ordered": ZERO, "on_way": ZERO, "issued": ZERO, "at_site": ZERO})

    for status, asked, approved, item_id in (db.query(DBStoreIndent.status, DBStoreIndentLine.qty, DBStoreIndentLine.approved_qty, DBStoreIndentLine.item_id)
                                            .join(DBStoreIndentLine, DBStoreIndentLine.indent_id == DBStoreIndent.id)
                                            .filter(DBStoreIndent.client_id == client_id, DBStoreIndent.project_id == job_id,
                                                    DBStoreIndent.status.notin_(NOT_INDENTED)).all()):
        got = approved if (approved is not None and status != "SUBMITTED") else asked
        slot(item_id)["indented"] += Decimal(str(got or 0))

    orders = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.job_id == job_id,
                                                     models.DBPurchaseOrder.status.notin_(NOT_ORDERED)).all()
    if orders:
        pre = OrderPrefetch(db, orders)
        po_lines = [(po, l) for po in orders for l in pre.lines.get(po.id, [])]
        code_item = _items_by_code(db, client_id, {l.item_code for _p, l in po_lines})
        item_of = {l.id: (l.item_id or code_item.get(l.item_code)) for _p, l in po_lines}
        units = BaseUnits(db, set(item_of.values()))
        for po, l in po_lines:
            item_id = item_of[l.id]
            if not item_id:
                continue
            s = slot(item_id)
            s["ordered"] += _base(units, item_id, l.qty or 0, l.uom)
            if po.status not in DEAD_PO:
                left = max(0.0, (l.qty or 0) - pre.received(po.id).get(l.id, 0.0))
                s["on_way"] += _base(units, item_id, left, l.uom)

    by_line = {}
    for _p, _h, _w, boq_item_id, item_id, qty, _v in material_cost_rows(db, client_id, project_id=job_id):
        slot(item_id)["issued"] += qty
        key = key_of.get(boq_item_id)
        if key:
            by_line[(item_id, key)] = by_line.get((item_id, key), ZERO) + qty

    stores = _project_stores(db, client_id, job_id)
    if stores:
        for item_id, qty in db.query(DBStoreStockBalance.item_id, DBStoreStockBalance.qty).filter(DBStoreStockBalance.store_id.in_(stores)).all():
            slot(item_id)["at_site"] += Decimal(str(qty or 0))
    return out, by_line


def item_sheet(db, client_id, job):
    """The Item sheet of one project (see the module's note)."""
    boq, _lines, key_of = _boq(db, client_id, job.id)
    need, lines = requirements(db, client_id, job.id)
    if boq is None:
        return {"job_id": job.id, "code": job.number or "", "name": job.name or "", "boq": False, "totals": None, "rows": []}
    figures, by_line = store_figures(db, client_id, job.id, key_of)
    names = {}
    extra = [i for i in figures if i not in need and i is not None]
    if extra:
        names = {it.id: it for it in db.query(models.DBItem).filter(models.DBItem.id.in_(extra)).all()}
    rows = []
    for n in need.values():
        f = figures.get(n["item_id"]) if n["item_id"] else None
        rows.append(_row(n, f, by_line))
    # What the store gave or holds for the project that no BOQ line's budget asks for: shown, so nothing goes unseen.
    for item_id in extra:
        it = names.get(item_id)
        if it is None:
            continue
        f = figures[item_id]
        if not any(f[k] for k in ("indented", "ordered", "issued", "at_site")):
            continue
        rows.append(_row({"item_id": item_id, "item_code": it.item_code, "item_name": it.item_name, "uom": it.units_of_measure or "",
                          "in_master": True, "required": 0.0, "base": 0.0, "value": 0.0, "unit_notes": [], "lines": []}, f, by_line, budgeted=False))
    order = {TO_ARRANGE: 0, OVER_ISSUED: 1, NO_BUDGET: 2, COVERED: 3}
    rows.sort(key=lambda r: (not r["in_master"], order.get(r["status"], 9), r["item_name"].lower()))
    budgeted_keys = {l["key"] for r in rows for l in r["lines"]}
    totals = {"items": len([r for r in rows if r["required"] > 0]), "to_arrange": len([r for r in rows if r["status"] == TO_ARRANGE]),
              "over_issued": len([r for r in rows if r["status"] == OVER_ISSUED]), "not_in_master": len([r for r in rows if not r["in_master"]]),
              "not_budgeted": len([r for r in rows if r["status"] == NO_BUDGET]),
              "value": money(sum(r["value"] for r in rows)), "to_arrange_value": money(sum(r["to_arrange_value"] for r in rows)),
              "boq_lines": len(lines), "boq_lines_with_materials": len(budgeted_keys)}
    return {"job_id": job.id, "code": job.number or "", "name": job.name or "", "boq": boq is not None, "totals": totals, "rows": rows}


def _row(n, f, by_line, budgeted=True):
    f = f or {"indented": ZERO, "ordered": ZERO, "on_way": ZERO, "issued": ZERO, "at_site": ZERO}
    required = _q(n["required"])
    issued, at_site, on_way = float(f["issued"]), float(f["at_site"]), float(f["on_way"])
    to_arrange = _q(max(0.0, required - issued - at_site - on_way)) if n["in_master"] else _q(required)
    if not budgeted:
        status = NO_BUDGET
    elif n["in_master"] and issued > required + 0.0005:
        status = OVER_ISSUED
    elif to_arrange > 0.0005:
        status = TO_ARRANGE
    else:
        status = COVERED
    rate = (n["value"] / required) if required else 0.0
    for l in n["lines"]:
        l["issued"] = _q(by_line.get((n["item_id"], l["key"]), ZERO)) if n["item_id"] else 0.0
    return {"item_id": n["item_id"], "item_code": n["item_code"], "item_name": n["item_name"], "uom": n["uom"], "in_master": n["in_master"],
            "required": required, "without_wastage": _q(n["base"]), "value": money(n["value"]),
            "indented": _q(f["indented"]), "ordered": _q(f["ordered"]), "on_way": _q(on_way), "issued": _q(issued), "at_site": _q(at_site),
            "to_arrange": to_arrange, "to_arrange_value": money(to_arrange * rate), "status": status,
            "unit_notes": n["unit_notes"], "lines": n["lines"]}


def budget_requirement(db, boq_line, item):
    """What a BOQ line needs of an item by its budget, in the item's base unit - the store's warnings read this where no
    store norm is set for the pair. None when the budget has no such material on the line."""
    from app.services.boq import boq_lines_of_job
    from app.services.stock_ledger import BaseUnits
    boq = db.get(models.DBBoq, boq_line.boq_id) if boq_line is not None else None
    if boq is None or item is None or not _code(item.item_code):
        return None
    rows = [r for r in db.query(models.DBBoqBudgetItem).filter(models.DBBoqBudgetItem.client_id == boq.client_id, models.DBBoqBudgetItem.job_id == boq.job_id,
                                                              models.DBBoqBudgetItem.boq_key == boq_line.key, models.DBBoqBudgetItem.kind == "MATERIAL").all()
            if _code(r.item_code) == _code(item.item_code)]
    if not rows:
        return None
    # The quantity is the current revision's, whichever revision's line the store document names.
    current = next((l for l in boq_lines_of_job(db, boq.client_id, boq.job_id) if l.key == boq_line.key), boq_line)
    norms = budget_wastage.norm_percents(db, boq.client_id, [boq.job_id])
    units = BaseUnits(db, {item.id})
    total = ZERO
    for r in rows:
        resolved = budget_wastage.for_item(norms, boq.job_id, r.boq_key, "MATERIAL", r.item_code, r.wastage_percent)
        qty = budget_wastage.quantities(current.quantity, r.coefficient, resolved)["final_quantity"]
        per = units.per_unit(item.id, r.uom) or Decimal(1)
        total += Decimal(str(qty)) * per
    return total.quantize(Decimal("0.001"))


def indent_warnings(db, indent, lines):
    """Warnings (never a block) on an indent: an item asked for past what the project's BOQ needs of it, all the project's
    indents counted. Silent for an item the budget does not ask for."""
    if not indent.project_id:
        return []
    need, _lines = requirements(db, indent.client_id, indent.project_id)
    if not need:
        return []
    from app.models.store_outward import DBStoreIndent, DBStoreIndentLine
    asked = {}
    for status, qty, approved, item_id in (db.query(DBStoreIndent.status, DBStoreIndentLine.qty, DBStoreIndentLine.approved_qty, DBStoreIndentLine.item_id)
                                          .join(DBStoreIndentLine, DBStoreIndentLine.indent_id == DBStoreIndent.id)
                                          .filter(DBStoreIndent.client_id == indent.client_id, DBStoreIndent.project_id == indent.project_id,
                                                  DBStoreIndent.id != indent.id, DBStoreIndent.status.notin_(NOT_INDENTED)).all()):
        got = approved if (approved is not None and status != "SUBMITTED") else qty
        asked[item_id] = asked.get(item_id, ZERO) + Decimal(str(got or 0))
    out = []
    for l in lines:
        n = need.get(l.item_id)
        if n is None:
            continue
        mine = Decimal(str(l.approved_qty if (l.approved_qty is not None and indent.status != "SUBMITTED") else l.qty or 0))
        total = asked.get(l.item_id, ZERO) + mine
        required = Decimal(str(round(n["required"], 3)))
        if total > required + Decimal("0.0005"):
            out.append("%s: %s %s asked for on this project's indents with this one, against %s %s the BOQ needs by its Item sheet."
                       % (n["item_name"], _show(total), n["uom"], _show(required), n["uom"]))
    return out


def _show(d) -> str:
    return ("%.3f" % float(d)).rstrip("0").rstrip(".")
