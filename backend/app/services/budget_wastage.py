"""Which wastage percentage a budget's material is costed at: the store's norm where one is set, else the budget's own.

Two places hold a wastage percentage for a material on a BOQ item: the budget line's item (Budgeting) and the store's material
norm (Store > Reports > Set norms). Left to themselves they drift apart, and the budget then plans for one quantity while the
store measures wastage against another. So there is one answer, worked out here and nowhere else:

    a norm is set for the material on that BOQ item of that project   -> the norm's percentage (0% is a norm like any other)
    no norm is set                                                     -> the budget's own percentage

The budget's own figure is never changed by this: it stays as it was typed, is shown beside the norm's, and is what the budget
falls back to the moment the norm is removed. Nothing is stored about the answer, so a norm added, changed or removed is
followed on the next read.

A norm is matched on the project, the BOQ item and the material themselves - never on a material's name, since the same
material is allowed a different wastage on another BOQ item or another project:
    project    the BOQ the norm's line belongs to is this project's
    BOQ item   the norm's BOQ line has the budget line's key (a key stays the same through every revision of the BOQ)
    material   the norm's item is the item master's item the budget item was picked as (its code, which is one item everywhere)
A budget material typed without picking it from the item master is no item of the master, so no norm can apply to it.
Where an older revision of the BOQ line also carries a norm, the one on the current revision wins, then the latest changed.
"""
from app import models
from app.models.store_reports import DBStoreMaterialNorm

STORE_NORM, BUDGETING = "STORE_NORM", "BUDGETING"


def _pct(value) -> float:
    return round(float(value or 0), 3)


def _show(value) -> str:
    return "%g" % value


def resolve(budgeting_percent, norm_percent):
    """The effective wastage percentage and where it came from. `norm_percent` is None when no norm is set - and only then:
    a norm of 0 is a norm."""
    own = _pct(budgeting_percent)
    if norm_percent is None:
        return {"budgeting_wastage_percent": own, "store_norm_wastage_percent": None, "effective_wastage_percent": own,
                "wastage_source": BUDGETING, "has_wastage_mismatch": False, "mismatch_message": None}
    norm = _pct(norm_percent)
    differs = norm != own
    return {"budgeting_wastage_percent": own, "store_norm_wastage_percent": norm, "effective_wastage_percent": norm,
            "wastage_source": STORE_NORM, "has_wastage_mismatch": differs,
            "mismatch_message": ("Budgeting wastage is %s%%, but Store Material Norm wastage is %s%%. Store Norm percentage is being used."
                                 % (_show(own), _show(norm))) if differs else None}


def norm_percents(db, client_id, job_ids):
    """{(project id, BOQ key, item code in lower case): the norm's wastage %} for these projects, in one query."""
    job_ids = [j for j in job_ids if j]
    if not job_ids:
        return {}
    rows = (db.query(DBStoreMaterialNorm, models.DBBoqLine.key, models.DBBoq.job_id, models.DBBoq.current_rev, models.DBBoqRevision.rev_no, models.DBItem.item_code)
            .join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id)
            .join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id)
            .join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
            .join(models.DBItem, models.DBItem.id == DBStoreMaterialNorm.item_id)
            .filter(DBStoreMaterialNorm.client_id == client_id, models.DBBoq.client_id == client_id, models.DBItem.client_id == client_id,
                    models.DBBoq.job_id.in_(job_ids)).all())
    best = {}
    for norm, key, job_id, current_rev, rev_no, code in rows:
        at = (job_id, key, (code or "").strip().lower())
        rank = (rev_no == current_rev, norm.updated_at.isoformat() if norm.updated_at else "", norm.id)
        if at not in best or rank > best[at][0]:
            best[at] = (rank, _pct(norm.wastage_pct))
    return {at: pct for at, (_rank, pct) in best.items()}


def for_item(norms, job_id, boq_key, kind, item_code, budgeting_percent):
    """The answer for one budget item. Only a material wastes: labour and plant carry no wastage and get none."""
    if (kind or "MATERIAL") != "MATERIAL":
        return resolve(0, None)
    code = (item_code or "").strip().lower()
    return resolve(budgeting_percent, norms.get((job_id, boq_key, code)) if code else None)


def quantities(boq_quantity, coefficient, resolved):
    """Base = BOQ quantity x quantity per unit; wastage = base x effective % / 100; final = base + wastage. Wastage goes on once, here."""
    base = (boq_quantity or 0) * (coefficient or 0)
    waste = base * resolved["effective_wastage_percent"] / 100.0
    return {"base_quantity": round(base, 3), "wastage_quantity": round(waste, 3), "final_quantity": round(base + waste, 3)}


def factor(resolved) -> float:
    return 1 + resolved["effective_wastage_percent"] / 100.0
