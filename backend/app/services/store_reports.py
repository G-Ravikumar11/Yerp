"""Store module - reports slice: stock valuation, stock movement, material consumption, norms against actual use, slow-moving stock and
reorder. Owned by P5.

Every report reads the stock ledger (and the balances kept from it) and nothing else, so what a report says always adds up to the stock the
stores hold. A reversal is a ledger row of the same movement type in the opposite column, so summing signed quantities and values nets it with
the original: nothing is filtered out. Quantities are in each item's base unit.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import case, func

from app import models
from app.models.store_core import (
    DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, MovementType,
)
from app.models.store_reports import DBStoreMaterialNorm
from app.services import store_integration

ZERO = Decimal("0")
_Q, _V, _R = Decimal("0.001"), Decimal("0.01"), Decimal("0.0001")

# The movement buckets of the movement report: each shows its net (in less out) quantity and value.
BUCKETS = (
    ("receipts", "Receipts", (MovementType.GRN_IN, MovementType.CLIENT_SUPPLY_IN, MovementType.OPENING_IN)),
    ("returns_to_supplier", "Returned to supplier", (MovementType.PURCHASE_RETURN_OUT,)),
    ("issues", "Issues (net of returns)", (MovementType.ISSUE_OUT, MovementType.ISSUE_RETURN_IN, MovementType.SUBCON_ISSUE_OUT, MovementType.SUBCON_RETURN_IN)),
    ("transfers", "Transfers", (MovementType.TRANSFER_IN, MovementType.TRANSFER_OUT)),
    ("adjustments", "Adjustments, wastage and scrap", (MovementType.ADJUST_IN, MovementType.ADJUST_OUT, MovementType.WASTAGE_OUT, MovementType.SCRAP_OUT)),
)
CATEGORY_NONE = "UNSET"


def q3(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(_Q, rounding=ROUND_HALF_UP)


def v2(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(_V, rounding=ROUND_HALF_UP)


def r4(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(_R, rounding=ROUND_HALF_UP)


def parse_day(raw, what, *, required=False, allow_future=True) -> Optional[date]:
    if raw in (None, ""):
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return None
    try:
        out = datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % what) from None
    if out.year < 2000 or out.year > 2100:
        raise HTTPException(400, "%s is not a sensible date." % what)
    if not allow_future and out > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)
    return out


def _signed_qty():
    return DBStoreStockLedger.qty_in - DBStoreStockLedger.qty_out


def _signed_value():
    return case((DBStoreStockLedger.qty_in > 0, DBStoreStockLedger.value), else_=-DBStoreStockLedger.value)


def _stores(db, client_id, store_ids):
    q = db.query(DBStore).filter(DBStore.client_id == client_id)
    if store_ids is not None:
        q = q.filter(DBStore.id.in_(list(store_ids) or [0]))
    return {s.id: s for s in q.all()}


def _items(db, ids):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(list(ids) or [0])).all()}


def _settings(db, ids):
    return {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(list(ids) or [0])).all()}


def _like(term):
    return "%" + term.replace("%", "").replace("_", "") + "%"


def _item_filter(query, term, item_col):
    if term:
        like = _like(term)
        query = query.join(models.DBItem, models.DBItem.id == item_col).filter(models.DBItem.item_code.ilike(like) | models.DBItem.item_name.ilike(like))
    return query


# --- valuation -------------------------------------------------------------------------------------------------------------

def valuation(db, client_id, store_ids=None, as_on=None, category="", q="", include_zero=False):
    """What each store holds of each item and what it is worth: today from the balances, or on a past date from the ledger up to it."""
    stores = _stores(db, client_id, store_ids)
    if not stores:
        return {"as_on": (as_on or date.today()).isoformat(), "rows": [], "total_qty_rows": 0, "total_value": ZERO, "by_category": []}
    today = date.today()
    if as_on is None or as_on >= today:
        query = db.query(DBStoreStockBalance.store_id, DBStoreStockBalance.item_id, DBStoreStockBalance.qty, DBStoreStockBalance.value).filter(DBStoreStockBalance.store_id.in_(list(stores)))
        if not include_zero:
            query = query.filter(DBStoreStockBalance.qty > 0)
        query = _item_filter(query, (q or "").strip(), DBStoreStockBalance.item_id)
        data = [(s, i, Decimal(str(qty or 0)), Decimal(str(val or 0))) for s, i, qty, val in query.all()]
    else:
        query = (db.query(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, func.sum(_signed_qty()), func.sum(_signed_value()))
                 .filter(DBStoreStockLedger.store_id.in_(list(stores)), DBStoreStockLedger.txn_date <= as_on))
        query = _item_filter(query, (q or "").strip(), DBStoreStockLedger.item_id)
        data = [(s, i, Decimal(str(qty or 0)), Decimal(str(val or 0))) for s, i, qty, val in query.group_by(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id).all()]
        if not include_zero:
            data = [d for d in data if d[2] > 0]
    items, settings = _items(db, [d[1] for d in data]), _settings(db, [d[1] for d in data])
    rows = []
    for sid, iid, qty, val in data:
        cat = settings[iid].category if iid in settings else CATEGORY_NONE
        if category and cat != category.strip().upper():
            continue
        rows.append({"store_id": sid, "store_code": stores[sid].code, "store_name": stores[sid].name, "item_id": iid, "item_code": items[iid].item_code, "item_name": items[iid].item_name,
                     "category": cat, "base_uom": (settings[iid].base_uom if iid in settings else items[iid].units_of_measure) or "", "qty": q3(qty), "avg_rate": r4(val / qty) if qty > 0 else ZERO,
                     "value": v2(val)})
    rows.sort(key=lambda r: (r["store_code"], r["item_name"]))
    cats = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"category": r["category"], "lines": 0, "value": ZERO})
        c["lines"] += 1
        c["value"] += r["value"]
    return {"as_on": (as_on or today).isoformat(), "rows": rows, "total_value": sum((r["value"] for r in rows), ZERO), "by_category": sorted(cats.values(), key=lambda c: c["category"])}


# --- movement --------------------------------------------------------------------------------------------------------------

def movement(db, client_id, store_ids, start: date, end: date, q=""):
    """Opening, what moved in each bucket, and closing, for every (store, item) that had stock or movement in the period."""
    if end < start:
        raise HTTPException(400, "The last day cannot be before the first.")
    stores = _stores(db, client_id, store_ids)
    if not stores:
        return {"from": start.isoformat(), "to": end.isoformat(), "buckets": [{"key": k, "label": l} for k, l, _t in BUCKETS], "rows": [], "totals": {}}
    sid_list = list(stores)
    opening = (db.query(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, func.sum(_signed_qty()), func.sum(_signed_value()))
               .filter(DBStoreStockLedger.store_id.in_(sid_list), DBStoreStockLedger.txn_date < start))
    opening = _item_filter(opening, (q or "").strip(), DBStoreStockLedger.item_id).group_by(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id).all()
    period = (db.query(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, DBStoreStockLedger.movement_type, func.sum(_signed_qty()), func.sum(_signed_value()))
              .filter(DBStoreStockLedger.store_id.in_(sid_list), DBStoreStockLedger.txn_date >= start, DBStoreStockLedger.txn_date <= end))
    period = _item_filter(period, (q or "").strip(), DBStoreStockLedger.item_id).group_by(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, DBStoreStockLedger.movement_type).all()
    bucket_of = {t.value: key for key, _l, types in BUCKETS for t in types}
    table = {}
    for sid, iid, qty, val in opening:
        row = table.setdefault((sid, iid), _blank_row())
        row["opening_qty"], row["opening_value"] = Decimal(str(qty or 0)), Decimal(str(val or 0))
    for sid, iid, mtype, qty, val in period:
        row = table.setdefault((sid, iid), _blank_row())
        b = bucket_of.get(mtype, "adjustments")
        row[b + "_qty"] += Decimal(str(qty or 0))
        row[b + "_value"] += Decimal(str(val or 0))
    items = _items(db, [i for _s, i in table])
    rows = []
    for (sid, iid), r in table.items():
        r["closing_qty"] = r["opening_qty"] + sum((r[k + "_qty"] for k, _l, _t in BUCKETS), ZERO)
        r["closing_value"] = r["opening_value"] + sum((r[k + "_value"] for k, _l, _t in BUCKETS), ZERO)
        if r["opening_qty"] == 0 and r["closing_qty"] == 0 and all(r[k + "_qty"] == 0 and r[k + "_value"] == 0 for k, _l, _t in BUCKETS):
            continue
        out = {"store_id": sid, "store_code": stores[sid].code, "item_id": iid, "item_code": items[iid].item_code, "item_name": items[iid].item_name}
        for k, v in r.items():
            out[k] = q3(v) if k.endswith("_qty") else v2(v)
        rows.append(out)
    rows.sort(key=lambda r: (r["store_code"], r["item_name"]))
    totals = {}
    for key in ["opening", *[k for k, _l, _t in BUCKETS], "closing"]:
        totals[key + "_value"] = sum((r[key + "_value"] for r in rows), ZERO)
    return {"from": start.isoformat(), "to": end.isoformat(), "buckets": [{"key": k, "label": l} for k, l, _t in BUCKETS], "rows": rows, "totals": totals}


def _blank_row():
    row = {"opening_qty": ZERO, "opening_value": ZERO}
    for k, _l, _t in BUCKETS:
        row[k + "_qty"] = ZERO
        row[k + "_value"] = ZERO
    return row


# --- consumption -----------------------------------------------------------------------------------------------------------

GROUPS = ("project", "cost_head", "work_order", "boq_item", "item")


def consumption(db, client_id, store_ids, project_id=0, start=None, end=None, group_by="project"):
    """Material consumed by project, cost head, work order, BOQ item or item: issues (and scrap and wastage) less what came back."""
    if group_by not in GROUPS:
        raise HTTPException(400, "Group by one of: %s." % ", ".join(GROUPS))
    rows = store_integration.material_cost_rows(db, client_id, project_id=project_id or None, from_date=start, to_date=end, store_ids=store_ids)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.id.in_({r[0] for r in rows} or {0})).all()}
    wos = {w.id: w for w in db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id.in_({r[2] for r in rows if r[2]} or {0})).all()}
    boqs = {b.id: b for b in db.query(models.DBBoqLine).filter(models.DBBoqLine.id.in_({r[3] for r in rows if r[3]} or {0})).all()}
    items = _items(db, {r[4] for r in rows})

    def label(r):
        p, head, wo, boq, item, _qty, _val = r
        if group_by == "project":
            return (p, "%s - %s" % (jobs[p].number, jobs[p].name) if p in jobs else str(p))
        if group_by == "cost_head":
            return (head or "BOQ WORK", (head or "BOQ work").replace("_", " ").title())
        if group_by == "work_order":
            return (wo or 0, wos[wo].number if wo in wos else "No work order")
        if group_by == "boq_item":
            return (boq or 0, ("%s %s" % (boqs[boq].item_no or "", (boqs[boq].description or "").split("\n")[0][:60])).strip() if boq in boqs else "Not charged to a BOQ item")
        return (item, "%s - %s" % (items[item].item_code, items[item].item_name))

    groups = {}
    for r in rows:
        key, name = label(r)
        g = groups.setdefault(key, {"key": key, "name": name, "value": ZERO, "items": {}})
        g["value"] += r[6]
        it = g["items"].setdefault(r[4], {"item_id": r[4], "item_code": items[r[4]].item_code, "item_name": items[r[4]].item_name, "qty": ZERO, "value": ZERO})
        it["qty"] += r[5]
        it["value"] += r[6]
    out = []
    for g in sorted(groups.values(), key=lambda g: -g["value"]):
        out.append({"key": g["key"] if not isinstance(g["key"], str) else g["key"], "name": g["name"], "value": v2(g["value"]),
                    "items": [{**i, "qty": q3(i["qty"]), "value": v2(i["value"])} for i in sorted(g["items"].values(), key=lambda i: -i["value"])]})
    return {"group_by": group_by, "total_value": sum((g["value"] for g in out), ZERO), "groups": out}


# --- norms ---------------------------------------------------------------------------------------------------------------------

def get_theoretical_requirement(db, boq_item_id, item_id) -> Optional[Decimal]:
    """What the BOQ item should consume of an item by its quantity and norms: BOQ quantity x quantity per unit x (1 + wastage %), in the
    item's base unit. None when no norm is set for the pair (or the BOQ item does not exist)."""
    norm = db.query(DBStoreMaterialNorm).filter(DBStoreMaterialNorm.boq_item_id == boq_item_id, DBStoreMaterialNorm.item_id == item_id).first()
    line = db.get(models.DBBoqLine, boq_item_id) if norm is not None else None
    if norm is None or line is None:
        return None
    need = Decimal(str(line.quantity or 0)) * Decimal(str(norm.qty_per_unit)) * (1 + Decimal(str(norm.wastage_pct or 0)) / 100)
    return q3(need)


def norm_variance(db, client_id, store_ids, project_id, tolerance_pct=ZERO):
    """For every BOQ item of a project with a norm: what it should consume, what the stores actually issued to it, and the difference."""
    norms = (db.query(DBStoreMaterialNorm, models.DBBoqLine).join(models.DBBoqLine, models.DBBoqLine.id == DBStoreMaterialNorm.boq_item_id)
             .join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(DBStoreMaterialNorm.client_id == client_id, models.DBBoq.job_id == project_id).all())
    actual = {}
    for p, head, wo, boq, item, qty, val in store_integration.material_cost_rows(db, client_id, project_id=project_id, store_ids=store_ids):
        if boq:
            a = actual.setdefault((boq, item), [ZERO, ZERO])
            a[0] += qty
            a[1] += val
    items = _items(db, [n.item_id for n, _l in norms])
    rows = []
    for n, line in norms:
        theory = get_theoretical_requirement(db, line.id, n.item_id) or ZERO
        qty, val = actual.get((line.id, n.item_id), [ZERO, ZERO])
        diff = qty - theory
        pct = (diff / theory * 100) if theory > 0 else None
        over = qty > theory * (1 + tolerance_pct / 100) if theory > 0 else qty > 0
        rows.append({"boq_item_id": line.id, "boq_item": ("%s %s" % (line.item_no or "", (line.description or "").split("\n")[0][:60])).strip(), "boq_qty": q3(line.quantity), "boq_uom": line.uom or "",
                     "item_id": n.item_id, "item_code": items[n.item_id].item_code, "item_name": items[n.item_id].item_name, "qty_per_unit": Decimal(str(n.qty_per_unit)), "wastage_pct": Decimal(str(n.wastage_pct or 0)),
                     "theoretical_qty": theory, "actual_qty": q3(qty), "actual_value": v2(val), "variance_qty": q3(diff), "variance_pct": pct.quantize(Decimal("0.1")) if pct is not None else None,
                     "status": "OVER" if over else ("UNDER" if qty < theory else "OK")})
    rows.sort(key=lambda r: (r["boq_item"], r["item_name"]))
    return {"project_id": project_id, "tolerance_pct": tolerance_pct, "over": sum(1 for r in rows if r["status"] == "OVER"), "rows": rows}


# --- slow-moving and reorder --------------------------------------------------------------------------------------------------

def slow_moving(db, client_id, store_ids, days=90):
    """Stock that has not moved for `days` days or more: what is held, what it is worth and when it last moved."""
    if days < 1 or days > 3650:
        raise HTTPException(400, "Days must be between 1 and 3650.")
    stores = _stores(db, client_id, store_ids)
    if not stores:
        return {"days": days, "total_value": ZERO, "rows": []}
    held = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(list(stores)), DBStoreStockBalance.qty > 0).all()
    last = {(s, i): d for s, i, d in db.query(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id, func.max(DBStoreStockLedger.txn_date)).filter(
        DBStoreStockLedger.store_id.in_(list(stores))).group_by(DBStoreStockLedger.store_id, DBStoreStockLedger.item_id).all()}
    items = _items(db, [b.item_id for b in held])
    today = date.today()
    rows = []
    for b in held:
        moved = last.get((b.store_id, b.item_id))
        idle = (today - moved).days if moved else None
        if idle is None or idle >= days:
            rows.append({"store_id": b.store_id, "store_code": stores[b.store_id].code, "item_id": b.item_id, "item_code": items[b.item_id].item_code, "item_name": items[b.item_id].item_name,
                         "qty": q3(b.qty), "value": v2(b.value), "last_moved": moved.isoformat() if moved else "", "days_idle": idle})
    rows.sort(key=lambda r: -r["value"])
    return {"days": days, "total_value": sum((r["value"] for r in rows), ZERO), "rows": rows}


def reorder(db, client_id, store_ids):
    """Items at or below their reorder level in a store, with a suggested quantity to bring them back up (to the maximum, or to twice the reorder level)."""
    stores = _stores(db, client_id, store_ids)
    if not stores:
        return {"rows": []}
    q = (db.query(DBStoreStockBalance, DBStoreItemSettings).join(DBStoreItemSettings, DBStoreItemSettings.item_id == DBStoreStockBalance.item_id)
         .filter(DBStoreStockBalance.store_id.in_(list(stores)), DBStoreItemSettings.reorder_level > 0, DBStoreStockBalance.qty <= DBStoreItemSettings.reorder_level))
    pairs = q.all()
    items = _items(db, [b.item_id for b, _s in pairs])
    rows = []
    for b, s in pairs:
        qty, level = Decimal(str(b.qty)), Decimal(str(s.reorder_level))
        target = Decimal(str(s.max_qty)) if s.max_qty and Decimal(str(s.max_qty)) > level else level * 2
        rows.append({"store_id": b.store_id, "store_code": stores[b.store_id].code, "item_id": b.item_id, "item_code": items[b.item_id].item_code, "item_name": items[b.item_id].item_name,
                     "base_uom": s.base_uom or "", "qty": q3(qty), "reorder_level": q3(level), "min_qty": q3(s.min_qty), "suggested_qty": q3(max(ZERO, target - qty)), "below_minimum": bool(s.min_qty and qty < Decimal(str(s.min_qty)))})
    rows.sort(key=lambda r: (r["store_code"], r["item_name"]))
    return {"rows": rows}
