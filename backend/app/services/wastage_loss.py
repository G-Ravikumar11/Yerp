"""Wastage loss: material a project drew past the limit set for it, valued at what it was issued at.

Material given to a site is the project's cost, and as long as it stays within its limit that is all it is - not a loss.
The limits are the ones already set:
    steel    the approved bar bending schedule plus its allowance (2% unless the company has set another), bar size by size
    others   the store norms on the BOQ items: BOQ quantity x quantity per unit x (1 + the norm's wastage %)
Only what was drawn beyond the limit is a loss. It is already inside "Material from store" - this says how much of that
was lost, it is not counted a second time.
"""
from decimal import Decimal

from app import models
from app.core.currency import money

ZERO = Decimal(0)


def _rates(db, client_id, job_id):
    """{item_id: rate per base unit} issued to the project, net of returns."""
    from app.services.store_integration import material_cost_rows
    qty, val = {}, {}
    for _p, _h, _w, _b, item_id, q, v in material_cost_rows(db, client_id, project_id=job_id):
        qty[item_id] = qty.get(item_id, ZERO) + q
        val[item_id] = val.get(item_id, ZERO) + v
    return {i: float(val[i] / qty[i]) for i in qty if qty[i] > 0}


def _steel(db, client_id, job_id, rates):
    """Steel past BBS + allowance, bar size by size, valued at the project's own average rate for that size."""
    from app.services import steel_allowance as steel
    rec = steel.reconciliation(db, client_id, job_id)
    if not rec["checked"]:
        return []
    # A rate per kg for each bar size, from the steel actually issued to this project.
    from app.services.store_integration import material_cost_rows
    kg, value = {}, {}
    rows = material_cost_rows(db, client_id, project_id=job_id)
    ids = {r[4] for r in rows}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(ids) or [0])).all()}
    base = steel._base_uoms(db, ids)
    for _p, _h, _w, _b, item_id, q, v in rows:
        it = items.get(item_id)
        d = steel.diameter_of(it) if it else 0
        f = steel.kg_per(base.get(item_id) or (it.units_of_measure if it else "")) if d else 0
        if d and f and q > 0:
            kg[d] = kg.get(d, 0.0) + float(q) * f
            value[d] = value.get(d, 0.0) + float(v)
    out = []
    for r in rec["rows"]:
        if r["status"] != "OVER" or not r["bbs_kg"]:
            continue                                   # a size with no BBS at all is a question for the BBS, not wastage
        over = round(r["issued_kg"] - r["allowed_kg"], 1)
        if over <= 0:
            continue
        rate = (value[r["diameter_mm"]] / kg[r["diameter_mm"]]) if kg.get(r["diameter_mm"]) else 0.0
        out.append({"item": "Steel %d mm" % r["diameter_mm"], "basis": "BBS + %g%%" % rec["allowance_pct"], "uom": "kg",
                    "limit": r["allowed_kg"], "used": r["issued_kg"], "over": over, "rate": round(rate, 2), "value": money(over * rate)})
    return out


def _norms(db, client_id, job_id, rates, skip_steel):
    """Other materials past their norm (with its wastage %) on each BOQ item - the same comparison as the store's Norms
    report - valued at what that material was issued at."""
    from app.services import steel_allowance as steel
    from app.services.store_reports import norm_variance
    rep = norm_variance(db, client_id, None, job_id)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([r["item_id"] for r in rep["rows"]] or [0])).all()}
    units = steel._base_uoms(db, items)
    out = []
    for r in rep["rows"]:
        over = Decimal(str(r["variance_qty"]))
        if r["status"] != "OVER" or over <= 0:
            continue
        it = items.get(r["item_id"])
        if skip_steel and it is not None and steel.diameter_of(it):
            continue                                   # steel is held to its BBS, not counted twice
        used = Decimal(str(r["actual_qty"]))
        rate = float(Decimal(str(r["actual_value"])) / used) if used > 0 else rates.get(r["item_id"], 0.0)
        out.append({"item": r["item_name"], "boq_item": r["boq_item"], "basis": "Store norm + %s%% wastage" % format(r["wastage_pct"].normalize(), "f"),
                    "uom": units.get(r["item_id"]) or (it.units_of_measure if it is not None else "") or "", "limit": float(r["theoretical_qty"]), "used": float(used), "over": float(over), "rate": round(rate, 2),
                    "value": money(float(over) * rate)})
    return out


def wastage_loss(db, client_id, job_id):
    """{"total", "rows": [...]} for one project: what was lost past the limits, item by item."""
    rates = _rates(db, client_id, job_id)
    steel_rows = _steel(db, client_id, job_id, rates)
    from app.services.steel_allowance import bbs_kg
    rows = steel_rows + _norms(db, client_id, job_id, rates, skip_steel=bool(bbs_kg(db, client_id, job_id)))
    rows.sort(key=lambda r: -r["value"])
    return {"total": money(sum(r["value"] for r in rows)), "rows": rows}


def wastage_by_job(db, client_id, job_ids=None):
    """{job_id: loss} for every project that has a limit to be over: an approved BBS or store norms on its BOQ."""
    from app.models.store_reports import DBStoreMaterialNorm
    with_bbs = {j for (j,) in db.query(models.DBBbsEntry.job_id).filter(models.DBBbsEntry.client_id == client_id,
                                                                          models.DBBbsEntry.status == "Approved").distinct().all()}
    with_norms = {j for (j,) in db.query(models.DBBoq.job_id).join(models.DBBoqLine, models.DBBoqLine.boq_id == models.DBBoq.id)
                  .join(DBStoreMaterialNorm, DBStoreMaterialNorm.boq_item_id == models.DBBoqLine.id)
                  .filter(DBStoreMaterialNorm.client_id == client_id).distinct().all()}
    out = {}
    for j in (with_bbs | with_norms):
        if j is None or (job_ids is not None and j not in job_ids):
            continue
        total = wastage_loss(db, client_id, j)["total"]
        if total > 0:
            out[j] = total
    return out
