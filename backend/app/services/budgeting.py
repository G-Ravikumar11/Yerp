"""The project budget: our cost against the BOQ's rate, and the profit that leaves.

For every priced line of the project's BOQ (its current revision):

    revenue         = the line's amount (quantity x the client's rate; a rate-only line is nothing until it has a quantity)
    cost per unit   = sum over the line's items of coefficient x rate, split into material, labour and other
    direct cost     = quantity x cost per unit
    overheads       = overhead % of direct cost; contingency = contingency % of direct cost
    profit          = revenue - direct cost - overheads - contingency          margin = profit / revenue

A line with no items yet is not budgeted: it counts in the BOQ value but has no cost, and the page says how much of the
BOQ is still unbudgeted rather than showing its whole value as profit.
"""
from fastapi import HTTPException

from app import models
from app.core.currency import money
from app.services.boq import boq_lines_of_job, boq_of_job

KINDS = ("MATERIAL", "LABOUR", "OTHER")
KIND_LABEL = {"MATERIAL": "Material", "LABOUR": "Labour", "OTHER": "Plant & other"}
MAX_ITEMS_PER_LINE = 60


def _pct(value, what):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "%s is a percentage." % what)
    if v != v or v < 0 or v > 100:
        raise HTTPException(400, "%s must be between 0 and 100." % what)
    return round(v, 2)


def settings_of(db, client_id, job_id):
    return db.query(models.DBBoqBudget).filter(models.DBBoqBudget.client_id == client_id,
                                                   models.DBBoqBudget.job_id == job_id).first()


def save_settings(db, client_id, job_id, overhead, contingency, note, who):
    row = settings_of(db, client_id, job_id)
    if row is None:
        row = models.DBBoqBudget(client_id=client_id, job_id=job_id)
        db.add(row)
    row.overhead_percent = _pct(overhead, "Overheads")
    row.contingency_percent = _pct(contingency, "Contingency")
    row.note = (note or "").strip()[:2000]
    row.updated_by_name = who
    from datetime import datetime
    row.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return row


def item_dict(i):
    return {"id": i.id, "kind": i.kind, "description": i.description or "", "uom": i.uom or "",
            "coefficient": i.coefficient or 0.0, "rate": money(i.rate), "item_code": i.item_code or "",
            "per_unit": money((i.coefficient or 0) * (i.rate or 0))}


def clean_items(rows):
    """What a line's items are sent as, checked: a known kind, a description, and a coefficient and rate that are numbers
    from zero up. A row with nothing in it is dropped."""
    out = []
    for r in rows or []:
        description = (r.get("description") or "").strip()
        try:
            coefficient, rate = float(r.get("coefficient") or 0), float(r.get("rate") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Quantity and rate are numbers.")
        if not description and not coefficient and not rate:
            continue
        if not description:
            raise HTTPException(400, "Say what the %s is for." % KIND_LABEL.get((r.get("kind") or "").upper(), "cost").lower())
        kind = (r.get("kind") or "MATERIAL").upper()
        if kind not in KINDS:
            raise HTTPException(400, "A cost is material, labour or plant & other.")
        for what, v in (("Quantity", coefficient), ("Rate", rate)):
            if v != v or v < 0 or v > 1e9:
                raise HTTPException(400, "%s must be a number from 0 up." % what)
        out.append({"kind": kind, "description": description[:200], "uom": (r.get("uom") or "").strip()[:20],
                    "coefficient": round(coefficient, 6), "rate": round(rate, 4),
                    "item_code": (r.get("item_code") or "").strip()[:40]})
    if len(out) > MAX_ITEMS_PER_LINE:
        raise HTTPException(400, "A line has at most %d items." % MAX_ITEMS_PER_LINE)
    return out


def replace_items(db, client_id, job_id, boq_key, rows, who):
    from datetime import datetime
    db.query(models.DBBoqBudgetItem).filter(models.DBBoqBudgetItem.client_id == client_id, models.DBBoqBudgetItem.job_id == job_id,
                                         models.DBBoqBudgetItem.boq_key == boq_key).delete(synchronize_session=False)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for n, r in enumerate(clean_items(rows)):
        db.add(models.DBBoqBudgetItem(client_id=client_id, job_id=job_id, boq_key=boq_key, display_order=n,
                                   updated_by_name=who, updated_at=now, **r))


def boq_headings(db, boq, lines):
    """The BOQ's section headings, each with the key of the priced line it stands above ('' for one after the last), so the
    budget can show them in bold where they are in the BOQ. `lines` are the priced lines, in order."""
    rev = db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq.id, models.DBBoqRevision.rev_no == boq.current_rev).first()
    if rev is None:
        return []
    from app.services.boq_outline import boq_outline
    every = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(
        models.DBBoqLine.display_order, models.DBBoqLine.id).all()
    outline, _, _ = boq_outline(every)
    heads = [l for l in every if l.kind == "section"]
    out, at = [], 0
    for h in heads:
        while at < len(lines) and (lines[at].display_order or 0) <= (h.display_order or 0):
            at += 1
        # How deep it sits (0 a main heading) and the headings above it, so a main heading folds its sub-headings too.
        out.append({"key": h.key, "item_no": h.item_no or "", "description": h.description or "", "before": lines[at].key if at < len(lines) else "",
                    "level": outline[h.key]["level"], "path": outline[h.key]["path"]})
    return out


def unit_costs(db, client_id, job_id):
    """{BOQ key: {"MATERIAL": .., "LABOUR": .., "OTHER": ..}} - what one unit of each budgeted line is planned to cost."""
    out = {}
    for i in db.query(models.DBBoqBudgetItem).filter(models.DBBoqBudgetItem.client_id == client_id,
                                                  models.DBBoqBudgetItem.job_id == job_id).all():
        unit = out.setdefault(i.boq_key, {"MATERIAL": 0.0, "LABOUR": 0.0, "OTHER": 0.0})
        unit[i.kind if i.kind in unit else "OTHER"] += (i.coefficient or 0) * (i.rate or 0)
    return out


def budget_view(db, client_id, job):
    """The whole budget for a project: every priced BOQ line with its cost and profit, and the totals."""
    boq = boq_of_job(db, client_id, job.id)
    lines = boq_lines_of_job(db, client_id, job.id) if boq else []
    items = {}
    for i in db.query(models.DBBoqBudgetItem).filter(models.DBBoqBudgetItem.client_id == client_id,
                                                  models.DBBoqBudgetItem.job_id == job.id).order_by(
            models.DBBoqBudgetItem.boq_key, models.DBBoqBudgetItem.display_order, models.DBBoqBudgetItem.id).all():
        items.setdefault(i.boq_key, []).append(i)
    cfg = settings_of(db, client_id, job.id)
    oh, ct = (cfg.overhead_percent or 0.0) if cfg else 0.0, (cfg.contingency_percent or 0.0) if cfg else 0.0

    headings = boq_headings(db, boq, lines) if boq else []
    grades = {}
    if boq:
        from app.services.boq_outline import boq_current_lines, boq_outline, line_materials
        every = boq_current_lines(db, client_id, job.id)
        heads_, path_, _ = boq_outline(every)
        grades = line_materials(every, heads_, path_)
    # Which heading each line is under: the nearest one above it in the BOQ ('' before the first), so the screen can fold a section away.
    standing_over = {}
    for h in headings:
        standing_over[h["before"]] = h["key"]
    under, current = {}, ""
    for l in lines:
        current = standing_over.get(l.key, current)
        under[l.key] = current

    rows, tot = [], {"revenue": 0.0, "material": 0.0, "labour": 0.0, "other": 0.0, "unbudgeted_value": 0.0, "budgeted": 0}
    sections = {}
    for l in lines:
        got = items.get(l.key, [])
        qty = l.quantity or 0.0
        revenue = 0.0 if l.rate_only else money(l.amount if l.amount else qty * (l.rate or 0))
        unit = {"MATERIAL": 0.0, "LABOUR": 0.0, "OTHER": 0.0}
        for i in got:
            unit[i.kind if i.kind in unit else "OTHER"] += (i.coefficient or 0) * (i.rate or 0)
        mat, lab, oth = (money(qty * unit[k]) for k in ("MATERIAL", "LABOUR", "OTHER"))
        direct = money(mat + lab + oth)
        overheads, contingency = money(direct * oh / 100), money(direct * ct / 100)
        cost = money(direct + overheads + contingency)
        budgeted = bool(got)
        profit = money(revenue - cost) if budgeted else None
        sec = l.group_code or ""
        rows.append({
            "key": l.key, "under": under.get(l.key, ""), "item_no": l.item_no or "", "group_code": sec, "description": l.description or "",
            "uom": l.uom or "", "quantity": money(qty), "rate": money(l.rate), "revenue": revenue, "rate_only": bool(l.rate_only),
            "item_code": l.item_code or "", "grade": grades.get(l.key, ""), "budgeted": budgeted, "items": [item_dict(i) for i in got],
            "unit_material": round(unit["MATERIAL"], 4), "unit_labour": round(unit["LABOUR"], 4), "unit_other": round(unit["OTHER"], 4),
            "unit_cost": round(sum(unit.values()), 4), "material": mat, "labour": lab, "other": oth, "direct": direct,
            "overheads": overheads, "contingency": contingency, "cost": cost, "profit": profit,
            "margin": round(profit / revenue * 100, 1) if budgeted and revenue else None})
        tot["revenue"] += revenue
        if budgeted:
            tot["budgeted"] += 1
            tot["material"] += mat
            tot["labour"] += lab
            tot["other"] += oth
            s = sections.setdefault(sec, {"group": sec, "revenue": 0.0, "cost": 0.0})
            s["revenue"] += revenue
            s["cost"] += cost
        else:
            tot["unbudgeted_value"] += revenue
    direct = money(tot["material"] + tot["labour"] + tot["other"])
    overheads, contingency = money(direct * oh / 100), money(direct * ct / 100)
    cost = money(direct + overheads + contingency)
    budgeted_revenue = money(tot["revenue"] - tot["unbudgeted_value"])
    profit = money(budgeted_revenue - cost)
    total = {
        "boq_value": money(tot["revenue"]), "budgeted_value": budgeted_revenue, "unbudgeted_value": money(tot["unbudgeted_value"]),
        "material": money(tot["material"]), "labour": money(tot["labour"]), "other": money(tot["other"]), "direct": direct,
        "overheads": overheads, "contingency": contingency, "cost": cost, "profit": profit,
        "margin": round(profit / budgeted_revenue * 100, 1) if budgeted_revenue else None,
        "lines": len(rows), "lines_budgeted": tot["budgeted"],
        "losing": len([r for r in rows if r["profit"] is not None and r["profit"] < 0]),
        # What the whole BOQ would leave if the unbudgeted lines cost what the budgeted ones do, as a share of their value.
        "projected_profit": money(tot["revenue"] * profit / budgeted_revenue) if budgeted_revenue else None}
    return {"job": {"id": job.id, "number": job.number or "", "name": job.name or ""},
            "boq": {"id": boq.id, "number": boq.number, "revision": boq.current_rev} if boq else None,
            "overhead_percent": oh, "contingency_percent": ct, "note": (cfg.note if cfg else "") or "",
            "updated_by_name": (cfg.updated_by_name if cfg else "") or "", "rows": rows, "total": total,
            "headings": headings,
            "sections": [{"group": s["group"], "revenue": money(s["revenue"]), "cost": money(s["cost"]),
                          "profit": money(s["revenue"] - s["cost"]),
                          "margin": round((s["revenue"] - s["cost"]) / s["revenue"] * 100, 1) if s["revenue"] else None}
                         for s in sections.values()]}


def suggest_items(db, client_id, q, limit=15):
    """Materials from the item master, with the rate we last paid (or the default purchase rate), to start a line from."""
    q = (q or "").strip()
    query = db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.kind == "RM",
                                           models.DBItem.is_active.isnot(False))
    if q:
        like = "%" + q.replace("%", "").replace("_", "") + "%"
        query = query.filter(models.DBItem.item_name.ilike(like) | models.DBItem.item_code.ilike(like))
    return [{"code": i.item_code, "name": i.item_name, "uom": i.units_of_measure or "",
             "rate": money(i.last_rate or i.purchase_rate or 0)}
            for i in query.order_by(models.DBItem.item_name).limit(limit).all()]
