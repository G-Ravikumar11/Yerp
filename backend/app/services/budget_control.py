"""HO QS budget control: how much of each live project's BOQ is budgeted, and what is left to give sub contractors.

A BOQ line's budget is the Budgeting tab's cost of one unit (services/budgeting.unit_costs). What a sub contractor is paid
for is its labour and its plant & other, so a line is

    Budgeted            labour + plant & other per unit is set (a work order can be held against it)
    Partially budgeted  it has budget items, but none of them is labour or plant & other (material only, say)
    Not budgeted        it has no budget items at all

Only lines with a quantity are applicable: a rate-only line is nothing until it has one (the same rule the Budgeting
tab follows). For each applicable line:

    approved            the BOQ's quantity and value (quantity x the client's rate, the line's amount)
    budgeted            the whole line once it is Budgeted (a per-unit budget covers every unit), else nothing
    remaining           approved - budgeted: what HO QS has still to budget
    contractor budget   labour + plant & other per unit x the BOQ quantity
    committed           what work orders already give against it - sent, approved, running, or closed at what was
                        billed; drafts, cancelled, rejected and amended orders are not counted, and an order being
                        amended counts once, through its revision
    available           BOQ quantity - committed quantity, and contractor budget - committed value

Nothing here is stored: it is worked out from the BOQ, the budget and the orders each time, so a budget item removed, an
order cancelled or a revision approved is followed on the next read. The work-order checks (subcontract_orders.wo_apply)
read the same rows, so the screens and the server never disagree.
"""
from app import models
from app.core.currency import money

NOT_LIVE_JOBS = ("complete", "cancelled")           # as the Setup Check reads a live project
NOT_COMMITTED = ("DRAFT", "CANCELLED", "AMENDED", "REJECTED")
EPS = 0.0005

BUDGETED, PARTIAL, NONE = "Budgeted", "Partially budgeted", "Not budgeted"


def is_live(job):
    return job is not None and (job.status or "") not in NOT_LIVE_JOBS


def _q(v):
    return round(float(v or 0), 3)


def line_status(unit):
    if not unit:
        return NONE
    return BUDGETED if (unit["LABOUR"] + unit["OTHER"]) > 0 else PARTIAL


def committed_by_line(db, client_id, job_id, exclude_order_id=None):
    """{BOQ key: {"qty", "value"}} given to sub contractors on the project's committed orders, the order being checked
    left out (it is weighed against what the others have left)."""
    from app.services.boq import boq_shares_of
    O, I = models.DBSubcontractOrder, models.DBSubcontractItem
    orders = {o.id: o for o in db.query(O).filter(O.client_id == client_id, O.job_id == job_id, O.status.notin_(NOT_COMMITTED)).all()}
    if exclude_order_id:
        orders.pop(exclude_order_id, None)
    # An order being amended stays live until its revision is approved; the revision stands for it meanwhile.
    amended = {o.supersedes_id for o in orders.values() if o.supersedes_id}
    billed = {}
    out = {}
    for it in db.query(I).filter(I.order_id.in_(list(orders) or [0]), I.is_header.isnot(True)).all():
        order = orders[it.order_id]
        if order.id in amended:
            continue
        if order.status == "CLOSED":
            # A closed order gave the contractor only what it billed; the rest is free again.
            if order.id not in billed:
                from app.services.subcontract_rules import billed_qty_by_item
                billed[order.id] = billed_qty_by_item(db, order.id)
            qty = billed[order.id].get(it.id, 0.0)
            value = money(qty * (it.unit_rate or 0))
        else:
            qty, value = it.quantity or 0, it.total_amount or money((it.quantity or 0) * (it.unit_rate or 0))
        for key, share in boq_shares_of(it):
            g = out.setdefault(key, {"qty": 0.0, "value": 0.0})
            g["qty"] += qty * share
            g["value"] += value * share
    return out


def budget_lines(db, client_id, job_id, exclude_order_id=None):
    """Every applicable BOQ line of the project with its budget, what is committed and what is available."""
    from app.services.boq import boq_lines_of_job
    from app.services.budgeting import unit_costs
    lines = [l for l in boq_lines_of_job(db, client_id, job_id) if (l.quantity or 0) > 0]
    costs = unit_costs(db, client_id, job_id)
    committed = committed_by_line(db, client_id, job_id, exclude_order_id)
    rows = []
    for l in lines:
        unit = costs.get(l.key)
        status = line_status(unit)
        qty = _q(l.quantity)
        value = money(l.amount if l.amount else (l.quantity or 0) * (l.rate or 0))
        per_unit = money((unit["LABOUR"] + unit["OTHER"]) if unit else 0.0)
        done = status == BUDGETED
        c = committed.get(l.key, {"qty": 0.0, "value": 0.0})
        contractor_budget = money(per_unit * (l.quantity or 0))
        rows.append({
            "key": l.key, "item_no": l.item_no or "", "item_code": l.item_code or "", "description": (l.description or "").strip(), "unit": l.uom or "",
            "status": status, "approved_qty": qty, "approved_value": value,
            "budgeted_qty": qty if done else 0.0, "budgeted_value": value if done else 0.0,
            "remaining_qty": 0.0 if done else qty, "remaining_value": 0.0 if done else value,
            "budget_per_unit": per_unit, "contractor_budget": contractor_budget,
            "committed_qty": _q(c["qty"]), "committed_value": money(c["value"]),
            "available_qty": _q(qty - c["qty"]), "available_value": money(contractor_budget - c["value"]),
        })
    return rows


def summary(rows):
    approved = money(sum(r["approved_value"] for r in rows))
    budgeted = money(sum(r["budgeted_value"] for r in rows))
    full = len([r for r in rows if r["status"] == BUDGETED])
    part = len([r for r in rows if r["status"] == PARTIAL])
    none = len([r for r in rows if r["status"] == NONE])
    total = len(rows)
    return {"lines": total, "budgeted": full, "partial": part, "unbudgeted": none,
            "approved_value": approved, "budgeted_value": budgeted, "remaining_value": money(approved - budgeted),
            # Quantities are in each line's own unit, so they are added up per line only, never across lines.
            "completion_percent": round(full / total * 100, 1) if total else 100.0,
            "value_percent": round(budgeted / approved * 100, 1) if approved else (100.0 if not total else 0.0),
            "status": "No BOQ lines" if not total else ("Complete" if full == total else ("Not started" if full == 0 and part == 0 else "Incomplete"))}


def project_budget(db, client_id, job):
    rows = budget_lines(db, client_id, job.id)
    return {"job_id": job.id, "code": job.number or "", "name": job.name or "", "live": is_live(job), "summary": summary(rows), "lines": rows}


def live_projects(db, client_id):
    """Every live project with a BOQ, with its budget summary - for HO QS's dashboard and the Setup Check."""
    from app.services.boq import boq_of_job
    out = []
    for job in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).order_by(models.DBJob.number, models.DBJob.id).all():
        if not is_live(job) or boq_of_job(db, client_id, job.id) is None:
            continue
        rows = budget_lines(db, client_id, job.id)
        out.append({"job_id": job.id, "code": job.number or "", "name": job.name or "", "summary": summary(rows)})
    return out


# ---- the work order checks -------------------------------------------------------------------------

def order_needs(db, order):
    """{BOQ key: {"qty", "value", "label"}} this order gives, a line for a heading shared out over its lines."""
    from app.services.boq import boq_shares_of
    out = {}
    for it in db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id, models.DBSubcontractItem.is_header.isnot(True)).all():
        if not (it.item_description or "").strip():
            continue
        value = it.total_amount or money((it.quantity or 0) * (it.unit_rate or 0))
        for key, share in boq_shares_of(it):
            g = out.setdefault(key, {"qty": 0.0, "value": 0.0})
            g["qty"] += (it.quantity or 0) * share
            g["value"] += value * share
    return out


def _label(r):
    return ("%s %s" % (r["item_no"], r["description"][:50])).strip()


def order_check(db, order):
    """What stands between an order and being sent or approved, as data: the project's lines still to budget, the lines
    this order takes past the BOQ quantity left, and those past the contractor budget left. An order on a project with
    no BOQ, or on a project that is not live, is left to the existing checks."""
    job = db.query(models.DBJob).filter(models.DBJob.id == order.job_id).first() if order.job_id else None
    from app.services.boq import boq_of_job
    if job is None or not is_live(job) or boq_of_job(db, order.client_id, job.id) is None:
        return {"applies": False, "project": None, "missing": [], "over_quantity": [], "over_value": [], "lines": []}
    rows = budget_lines(db, order.client_id, job.id, exclude_order_id=order.id)
    by_key = {r["key"]: r for r in rows}
    need = order_needs(db, order)
    missing = [{"key": r["key"], "item": _label(r), "status": r["status"], "unit": r["unit"], "quantity": r["approved_qty"], "value": r["approved_value"]}
               for r in rows if r["status"] != BUDGETED]
    over_qty, over_value, lines = [], [], []
    for key, n in need.items():
        r = by_key.get(key)
        if r is None:
            continue                                   # a rate-only or loose line: the existing checks decide
        line = {"key": key, "item": _label(r), "unit": r["unit"], "this_order_qty": _q(n["qty"]), "this_order_value": money(n["value"]),
                "available_qty": r["available_qty"], "available_value": r["available_value"], "budget_per_unit": r["budget_per_unit"]}
        lines.append(line)
        if n["qty"] > r["available_qty"] + EPS:
            over_qty.append(dict(line, short_qty=_q(n["qty"] - r["available_qty"])))
        if r["status"] == BUDGETED and n["value"] > r["available_value"] + 0.009:
            over_value.append(dict(line, short_value=money(n["value"] - r["available_value"])))
    return {"applies": True, "project": {"job_id": job.id, "code": job.number or "", "name": job.name or ""},
            "missing": missing, "over_quantity": over_qty, "over_value": over_value, "lines": lines}


def lock_project(db, job_id):
    """Take the project's row until this save ends, so two orders on one project are weighed one after the other and
    cannot together give out more than is left. (On SQLite writes are one at a time already.)"""
    if job_id and db.bind is not None and db.bind.dialect.name == "postgresql":
        db.query(models.DBJob).filter(models.DBJob.id == job_id).with_for_update().first()


def refuse_unless_within(db, order):
    """409 unless the project's BOQ is wholly budgeted. A line past the BOQ quantity left, or past its contractor budget,
    is not refused here: each keeps its existing rule (past the BOQ, the Master overrides at approval with a reason; past
    the budget, a reason to send it and the Master signs) - order_check() shows both before the order is sent."""
    from fastapi import HTTPException
    lock_project(db, order.job_id)
    c = order_check(db, order)
    if not c["applies"] or not c["missing"]:
        return c
    p = c["project"]
    where = ("%s %s" % (p["code"], p["name"])).strip()
    first = c["missing"][:3]
    raise HTTPException(409, "%s: the HO QS budget is not complete - %d BOQ line%s still to budget, %s of value. No work order on the project is "
                             "sent or approved until every line is budgeted on the Budgeting tab (first: %s)." % (
                                 where, len(c["missing"]), "" if len(c["missing"]) == 1 else "s",
                                 money(sum(m["value"] for m in c["missing"])),
                                 "; ".join("%s - %s" % (m["item"], m["status"].lower()) for m in first)))
