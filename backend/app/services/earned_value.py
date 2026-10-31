"""Budget against actual, by BOQ line and heading, with earned value.

For every BOQ line of a project:
  - budget (BAC): what the budget says the line costs us in all (Budgeting: its material, labour and other, with overheads);
  - planned value (PV): the budget times how far the plan has the work by today;
  - earned value (EV): the budget times how far the work actually is (the programme's activities drawn on the line);
  - actual cost (AC): material the stores issued against the line, and subcontract work measured on it at the order's rate.
Headings add up the lines under them. For the project, CPI = EV / AC (above 1, the work costs less than budgeted) and
SPI = EV / PV (above 1, ahead of the plan).

A heading whose actual cost has run past its budget times the share done - more spent than the work done so far was worth - is an
overrun, and is put on "What needs you" (and so in the morning digest).
"""
import json
from datetime import date

from app import models
from app.core.currency import money

# Orders whose measured work is a cost: placed and not called off.
LIVE_ORDERS = ("PROVISIONAL", "APPROVED", "EXECUTED", "AMENDED", "CLOSED")


def _ratio(a, b):
    return round(a / b, 2) if b else None


def line_progress(db, client_id, job, on=None):
    """{BOQ key: (planned %, done %)} from the programme: the activities drawn on each line, weighted by their share of the job.
    An activity drawn on a heading counts for the lines under it that have none of their own."""
    from app.services.projects import ScheduleContext
    on = on or date.today()
    ctx = ScheduleContext(db, client_id, job.id)
    if not ctx.acts:
        return {}
    acc = {}
    for a in ctx.leaves:
        key = (a.boq_key or "").strip()
        if not key:
            continue
        w = ctx.weight.get(a.id, 0.0) or 1e-9
        s = acc.setdefault(key, [0.0, 0.0, 0.0])
        s[0] += w * ctx.planned(a, on)
        s[1] += w * ctx.actual(a, on)
        s[2] += w
    return {k: (round(p / w, 1), round(d / w, 1)) for k, (p, d, w) in acc.items() if w}


def actual_costs(db, client_id, job):
    """({BOQ key: {"material": .., "subcontract": ..}}, {"material": .., "subcontract": ..} not against any BOQ line)."""
    from app.services.store_integration import material_cost_rows
    by_key, loose = {}, {"material": 0.0, "subcontract": 0.0}

    rows = material_cost_rows(db, client_id, project_id=job.id)
    ids = {b for _, _, _, b, _, _, _ in rows if b}
    keys = dict(db.query(models.DBBoqLine.id, models.DBBoqLine.key).filter(models.DBBoqLine.id.in_(ids)).all()) if ids else {}
    for _, _, _, boq_item_id, _, _, value in rows:
        key = keys.get(boq_item_id)
        if key:
            by_key.setdefault(key, {"material": 0.0, "subcontract": 0.0})["material"] += float(value)
        else:
            loose["material"] += float(value)

    orders = [o for (o,) in db.query(models.DBSubcontractOrder.id).filter(models.DBSubcontractOrder.client_id == client_id,
                                                                           models.DBSubcontractOrder.job_id == job.id,
                                                                           models.DBSubcontractOrder.status.in_(LIVE_ORDERS)).all()]
    if orders:
        items = {i.id: i for i in db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id.in_(orders)).all()}
        measured = {}
        # The work measured, held back from billing or not: the cost is incurred when the work is done, not when it is paid.
        for item_id, qty in db.query(models.DBSubMeasurement.item_id, models.DBSubMeasurement.quantity).filter(
                models.DBSubMeasurement.order_id.in_(orders), (models.DBSubMeasurement.kind == "") | models.DBSubMeasurement.kind.is_(None)).all():
            measured[item_id] = measured.get(item_id, 0.0) + (qty or 0.0)
        for item_id, qty in measured.items():
            i = items.get(item_id)
            if i is None or i.is_header:
                continue
            cost = qty * (i.unit_rate or 0.0)
            parts = []
            try:
                parts = [p for p in json.loads(i.boq_parts or "[]") if p.get("key")]
            except (ValueError, TypeError, AttributeError):
                parts = []
            if parts:
                whole = sum(float(p.get("qty") or 0) for p in parts) or float(len(parts))
                for p in parts:
                    share = (float(p.get("qty") or 0) or 1.0) / whole
                    by_key.setdefault(p["key"], {"material": 0.0, "subcontract": 0.0})["subcontract"] += cost * share
            elif (i.boq_key or "").strip():
                by_key.setdefault(i.boq_key, {"material": 0.0, "subcontract": 0.0})["subcontract"] += cost
            else:
                loose["subcontract"] += cost
    return by_key, loose


def earned_value(db, client_id, job, on=None):
    from app.services.boq_outline import boq_current_lines, boq_outline
    from app.services.budgeting import budget_view
    on = on or date.today()
    budget = budget_view(db, client_id, job)
    every = boq_current_lines(db, client_id, job.id) if budget["boq"] else []
    heads, path, _ = boq_outline(every) if every else ({}, {}, {})
    progress = line_progress(db, client_id, job, on)
    spent, loose = actual_costs(db, client_id, job)

    # A heading's progress stands for lines under it that have none of their own (a programme drawn by section).
    def progress_of(key):
        if key in progress:
            return progress[key], "line"
        for h in reversed(path.get(key, [])):
            if h in progress:
                return progress[h], "heading"
        return None, ""

    lines, known = [], set()
    for r in budget["rows"]:
        known.add(r["key"])
        bac = r["cost"] if r["budgeted"] else 0.0
        got, source = progress_of(r["key"])
        plan, done = got if got else (0.0, 0.0)
        cost = spent.get(r["key"], {"material": 0.0, "subcontract": 0.0})
        ac = money(cost["material"] + cost["subcontract"])
        pv, ev = money(bac * plan / 100.0), money(bac * done / 100.0)
        lines.append({"key": r["key"], "item_no": r["item_no"], "description": r["description"], "uom": r["uom"], "budgeted": r["budgeted"],
                      "path": path.get(r["key"], []), "budget": money(bac), "planned_percent": plan, "done_percent": done,
                      "progress_from": source, "pv": pv, "ev": ev, "ac": ac, "material": money(cost["material"]),
                      "subcontract": money(cost["subcontract"]), "variance": money(ev - ac), "cpi": _ratio(ev, ac), "spi": _ratio(ev, pv),
                      "overrun": bool(bac and ac > ev + 0.5)})
    # Cost booked to a heading, or to a line the BOQ no longer has (taken out in a revision), still counts, as not against a line.
    for key, cost in spent.items():
        if key not in known:
            loose["material"] += cost["material"]
            loose["subcontract"] += cost["subcontract"]

    headings = []
    for key, h in heads.items():
        under = [l for l in lines if key in l["path"]]
        if not under:
            continue
        bac = money(sum(l["budget"] for l in under))
        pv, ev, ac = (money(sum(l[f] for l in under)) for f in ("pv", "ev", "ac"))
        headings.append({"key": key, "item_no": h["item_no"], "description": h["description"], "level": h["level"], "path": h["path"],
                         "lines": len(under), "budget": bac, "pv": pv, "ev": ev, "ac": ac,
                         "done_percent": round(ev / bac * 100, 1) if bac else 0.0, "planned_percent": round(pv / bac * 100, 1) if bac else 0.0,
                         "variance": money(ev - ac), "cpi": _ratio(ev, ac), "spi": _ratio(ev, pv),
                         # More spent than the work done so far was worth, on a heading that has a budget.
                         "overrun": bool(bac and ac > ev + 0.5), "over_by": money(max(0.0, ac - ev))})

    bac = money(sum(l["budget"] for l in lines))
    pv, ev = money(sum(l["pv"] for l in lines)), money(sum(l["ev"] for l in lines))
    ac_lines = money(sum(l["ac"] for l in lines))
    ac = money(ac_lines + loose["material"] + loose["subcontract"])
    cpi, spi = _ratio(ev, ac_lines), _ratio(ev, pv)
    return {"job": budget["job"], "boq": budget["boq"], "as_of": on.isoformat(), "lines": lines, "headings": headings,
            "not_against_a_line": {"material": money(loose["material"]), "subcontract": money(loose["subcontract"])},
            "total": {"budget": bac, "pv": pv, "ev": ev, "ac": ac, "ac_on_lines": ac_lines, "variance": money(ev - ac_lines),
                      "cpi": cpi, "spi": spi,
                      # What the whole job will cost at the rate it is going, and what that leaves against the budget.
                      "eac": money(bac / cpi) if cpi else None, "vac": money(bac - bac / cpi) if cpi else None,
                      "done_percent": round(ev / bac * 100, 1) if bac else 0.0, "planned_percent": round(pv / bac * 100, 1) if bac else 0.0,
                      "lines_with_progress": len([l for l in lines if l["progress_from"]]), "lines": len(lines),
                      "overruns": len([h for h in headings if h["overrun"] and h["level"] == 0])}}


def overruns_for(db, client_id, jobs):
    """[(job, heading)] for the main headings over budget for the work done, on the projects that have a budget."""
    budgeted = {j for (j,) in db.query(models.DBBoqBudgetItem.job_id).filter(models.DBBoqBudgetItem.client_id == client_id).distinct().all()}
    out = []
    for job in jobs:
        if job.id not in budgeted:
            continue
        ev = earned_value(db, client_id, job)
        for h in ev["headings"]:
            if h["overrun"] and h["level"] == 0:
                out.append((job, h))
    return out
