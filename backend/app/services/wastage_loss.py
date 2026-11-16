"""Wastage loss: material a project drew past the limit set for it, valued at what it was issued at - and the wastage the stores recorded
against the project where no limit has been set yet.

Material given to a site is the project's cost, and as long as it stays within its limit that is all it is - not a loss.
The limits are the ones already set:
    steel    the approved bar bending schedule plus its allowance (2% unless the company has set another), bar size by size
    others   the store norms on the BOQ items: BOQ quantity x quantity per unit x (1 + the norm's wastage %)
Only what was drawn beyond the limit is a loss. It is already inside "Material from store" - this says how much of that
was lost, it is not counted a second time.

Most BOQ items have no norm, and the report used to say "None" for them even when the store had written material off as
wasted or scrapped (WASTAGE_OUT, SCRAP_OUT). That wastage is now shown as it was recorded, with the comparison marked as not
available: no wastage percentage is assumed for a norm that was never set, and nothing is shown as zero for want of one.

For each row the figures are kept apart:
    expected   what the work should consume by its norm, before wastage (BOQ quantity x quantity per unit)
    used       what the stores actually issued to it, net of returns, wastage and scrap included
    wasted     the wastage: what was used past `expected`, or what the store recorded as wasted, whichever is more
    allowed    the wastage the norm allows (expected x wastage %)
    over       the wastage past the allowance - the loss, valued in `value`
    norm       OVER | WITHIN (a norm is set) | NO_NORM (none is set for the material on this project) |
               NOT_LINKED (norms are set for it, but the wastage was recorded against no BOQ item that has one) | BBS (steel)
"""
from decimal import Decimal

from app import models
from app.core.currency import money

ZERO = Decimal(0)
NORM_TEXT = {"NO_NORM": "Norm not configured", "NOT_LINKED": "Not against a BOQ item with a norm"}


def _rates(db, client_id, job_id):
    """{item_id: rate per base unit} issued to the project, net of returns."""
    from app.services.store_integration import material_cost_rows
    qty, val = {}, {}
    for _p, _h, _w, _b, item_id, q, v in material_cost_rows(db, client_id, project_id=job_id):
        qty[item_id] = qty.get(item_id, ZERO) + q
        val[item_id] = val.get(item_id, ZERO) + v
    return {i: float(val[i] / qty[i]) for i in qty if qty[i] > 0}


def _used_by_item(db, client_id, job_id):
    """{item_id: quantity} the stores consumed for the project in all, net of returns."""
    from app.services.store_integration import material_cost_rows
    out = {}
    for _p, _h, _w, _b, item_id, q, _v in material_cost_rows(db, client_id, project_id=job_id):
        out[item_id] = out.get(item_id, ZERO) + q
    return out


def recorded_wastage(db, client_id, job_id):
    """{(boq_item_id or None, item_id): [qty, value]} the stores wrote off as wasted or scrapped against the project, net of reversals."""
    from sqlalchemy import func
    from app.models.store_core import DBStore, DBStoreStockLedger, MovementType
    from app.services.store_integration import signed_qty, signed_value
    rows = (db.query(DBStoreStockLedger.boq_item_id, DBStoreStockLedger.item_id, func.sum(signed_qty()), func.sum(signed_value()))
            .join(DBStore, DBStore.id == DBStoreStockLedger.store_id)
            .filter(DBStore.client_id == client_id, DBStoreStockLedger.project_id == job_id,
                    DBStoreStockLedger.movement_type.in_([MovementType.WASTAGE_OUT.value, MovementType.SCRAP_OUT.value]))
            .group_by(DBStoreStockLedger.boq_item_id, DBStoreStockLedger.item_id).all())
    return {(b, i): [Decimal(str(q or 0)), Decimal(str(v or 0))] for b, i, q, v in rows if (q or 0) > 0}


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
        weight = steel.kg_of(it, q, base.get(item_id) or (it.units_of_measure if it else "")) if d else None
        if d and weight is not None and q > 0:
            kg[d] = kg.get(d, 0.0) + weight
            value[d] = value.get(d, 0.0) + float(v)
    out = []
    for r in rec["rows"]:
        if r["status"] != "OVER" or not r["bbs_kg"]:
            continue                                   # a size with no BBS at all is a question for the BBS, not wastage
        over = round(r["issued_kg"] - r["allowed_kg"], 1)
        if over <= 0:
            continue
        rate = (value[r["diameter_mm"]] / kg[r["diameter_mm"]]) if kg.get(r["diameter_mm"]) else 0.0
        wasted = round(r["issued_kg"] - r["bbs_kg"], 1)
        out.append({"item": "Steel %d mm" % r["diameter_mm"], "basis": "BBS + %g%%" % rec["allowance_pct"], "uom": "kg", "norm": "BBS",
                    "expected": r["bbs_kg"], "limit": r["allowed_kg"], "used": r["issued_kg"], "wasted": wasted, "allowed": round(r["allowed_kg"] - r["bbs_kg"], 1),
                    "over": over, "rate": round(rate, 2), "value": money(over * rate), "wasted_value": money(wasted * rate)})
    return out


def _norms(db, client_id, job_id, rates, skip_steel, recorded):
    """Materials with a norm on a BOQ item - the same comparison as the store's Norms report - valued at what that material was issued
    at. A row is shown when there was wastage at all; `recorded` loses the entries it accounts for."""
    from app.services import steel_allowance as steel
    from app.services.store_reports import norm_variance, q3
    rep = norm_variance(db, client_id, None, job_id)
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([r["item_id"] for r in rep["rows"]] or [0])).all()}
    units = steel._base_uoms(db, items)
    out = []
    for r in rep["rows"]:
        it = items.get(r["item_id"])
        if skip_steel and it is not None and steel.diameter_of(it):
            recorded.pop((r["boq_item_id"], r["item_id"]), None)
            continue                                   # steel is held to its BBS, not counted twice
        theory = Decimal(str(r["theoretical_qty"]))
        expected = q3(Decimal(str(r["boq_qty"])) * Decimal(str(r["qty_per_unit"])))
        allowed = max(ZERO, theory - expected)
        used = Decimal(str(r["actual_qty"]))
        written_off = recorded.pop((r["boq_item_id"], r["item_id"]), [ZERO, ZERO])[0]
        wasted = max(ZERO, used - expected, written_off)
        over = max(ZERO, used - theory)
        if wasted <= 0 and over <= 0:
            continue                                   # used within what the work needs: cost, and nothing to say
        rate = float(Decimal(str(r["actual_value"])) / used) if used > 0 else rates.get(r["item_id"], 0.0)
        out.append({"item": r["item_name"], "item_id": r["item_id"], "boq_item": r["boq_item"], "norm": "OVER" if over > 0 else "WITHIN",
                    "basis": "Store norm + %s%% wastage" % format(Decimal(str(r["wastage_pct"])).normalize(), "f"),
                    "uom": units.get(r["item_id"]) or (it.units_of_measure if it is not None else "") or "",
                    "expected": float(expected), "limit": float(theory), "used": float(used), "wasted": float(wasted), "allowed": float(allowed), "over": float(over),
                    "rate": round(rate, 2), "value": money(float(over) * rate), "wasted_value": money(float(wasted) * rate)})
    return out


def _unchecked(db, client_id, job_id, recorded, skip_steel, normed_items):
    """Wastage the stores recorded against the project with no norm to measure it by: shown as recorded, at the value it left the
    store at. Nothing is compared and nothing is called a loss past a limit, since no limit was set."""
    if not recorded:
        return []
    from app.services import steel_allowance as steel
    by_item = {}
    for (_b, item_id), (q, v) in recorded.items():
        a = by_item.setdefault(item_id, [ZERO, ZERO])
        a[0] += q
        a[1] += v
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(by_item) or [0])).all()}
    units = steel._base_uoms(db, items)
    used = _used_by_item(db, client_id, job_id)
    out = []
    for item_id, (q, v) in by_item.items():
        it = items.get(item_id)
        if it is None or q <= 0:
            continue
        if skip_steel and steel.diameter_of(it):
            continue                                   # steel written off is already in what the BBS check counts as issued
        norm = "NOT_LINKED" if item_id in normed_items else "NO_NORM"
        out.append({"item": it.item_name, "item_id": item_id, "boq_item": None, "norm": norm, "basis": NORM_TEXT[norm],
                    "uom": units.get(item_id) or it.units_of_measure or "", "expected": None, "limit": None, "used": float(used.get(item_id, q)),
                    "wasted": float(q), "allowed": None, "over": None, "rate": round(float(v / q), 2) if q else 0.0, "value": 0.0, "wasted_value": money(float(v))})
    return out


def wastage_loss(db, client_id, job_id):
    """One project's wastage, item by item:
    {"total": loss past the limits, "wasted_value": all the wastage, "unchecked_value": wastage with no norm to check it by, "rows": [...]}"""
    from app.models.store_reports import DBStoreMaterialNorm
    from app.services.steel_allowance import bbs_kg
    rates = _rates(db, client_id, job_id)
    skip_steel = bool(bbs_kg(db, client_id, job_id))
    recorded = recorded_wastage(db, client_id, job_id)
    normed_items = {i for (i,) in db.query(DBStoreMaterialNorm.item_id).join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id)
                    .join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
                    .filter(DBStoreMaterialNorm.client_id == client_id, models.DBBoq.job_id == job_id).distinct().all()}
    rows = _steel(db, client_id, job_id, rates) + _norms(db, client_id, job_id, rates, skip_steel, recorded)
    rows += _unchecked(db, client_id, job_id, recorded, skip_steel, normed_items)
    rows.sort(key=lambda r: (-r["value"], -r["wasted_value"]))
    unchecked = [r for r in rows if r["norm"] in NORM_TEXT]
    return {"total": money(sum(r["value"] for r in rows)), "wasted_value": money(sum(r["wasted_value"] for r in rows)),
            "unchecked_value": money(sum(r["wasted_value"] for r in unchecked)), "unchecked": len(unchecked), "rows": rows}


def _jobs_to_check(db, client_id):
    """Projects with something to report: an approved BBS, store norms on its BOQ, or wastage the stores recorded against it."""
    from app.models.store_core import DBStore, DBStoreStockLedger, MovementType
    from app.models.store_reports import DBStoreMaterialNorm
    with_bbs = {j for (j,) in db.query(models.DBBbsEntry.job_id).filter(models.DBBbsEntry.client_id == client_id,
                                                                          models.DBBbsEntry.status == "Approved").distinct().all()}
    with_norms = {j for (j,) in db.query(models.DBBoq.job_id).join(models.DBBoqLine, models.DBBoqLine.boq_id == models.DBBoq.id)
                  .join(DBStoreMaterialNorm, DBStoreMaterialNorm.boq_item_id == models.DBBoqLine.id)
                  .filter(DBStoreMaterialNorm.client_id == client_id).distinct().all()}
    with_writeoffs = {j for (j,) in db.query(DBStoreStockLedger.project_id).join(DBStore, DBStore.id == DBStoreStockLedger.store_id)
                      .filter(DBStore.client_id == client_id, DBStoreStockLedger.project_id.isnot(None),
                              DBStoreStockLedger.movement_type.in_([MovementType.WASTAGE_OUT.value, MovementType.SCRAP_OUT.value])).distinct().all()}
    return with_bbs | with_norms | with_writeoffs


def wastage_detail_by_job(db, client_id, job_ids=None):
    """{job_id: {"loss", "wasted", "unchecked"}} for every project with wastage of any kind."""
    out = {}
    for j in _jobs_to_check(db, client_id):
        if j is None or (job_ids is not None and j not in job_ids):
            continue
        got = wastage_loss(db, client_id, j)
        if got["total"] > 0 or got["wasted_value"] > 0:
            out[j] = {"loss": got["total"], "wasted": got["wasted_value"], "unchecked": got["unchecked_value"]}
    return out


def wastage_by_job(db, client_id, job_ids=None):
    """{job_id: loss} for every project that went past a limit: an approved BBS or store norms on its BOQ."""
    return {j: d["loss"] for j, d in wastage_detail_by_job(db, client_id, job_ids).items() if d["loss"] > 0}
