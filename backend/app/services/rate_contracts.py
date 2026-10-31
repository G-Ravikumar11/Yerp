"""Rate contracts: rates agreed with a supplier for chosen items, usually for a year.

A contract is numbered (RC-0001) and holds one rate per item; each item is a row of rate_contracts carrying the
contract's number. While it is in force, an order to that supplier picks the contract rate for the item by itself, and
an order priced above it is flagged (services/po_controls.py). Purchasing is told 30 and 7 days before a contract runs
out - on the bell, as the company's rule is that nothing is emailed on its own.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core.currency import unit_rate
from app.core.notifications import notify
from app.core.scheduler import scheduled_job
from app.services.crm import norm_name

REMIND_DAYS = (30, 7)


def next_number(db, client_id):
    top = 0
    for (n,) in db.query(models.DBRateContract.contract_no).filter(models.DBRateContract.client_id == client_id).all():
        tail = (n or "")[3:]
        if (n or "").startswith("RC-") and tail.isdigit():
            top = max(top, int(tail))
    return "RC-%04d" % (top + 1)


def _day(raw, what):
    try:
        return datetime.strptime((raw or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "The %s is not a date (YYYY-MM-DD)." % what) from None


def make(db, client_id, actor_name, body):
    """One contract: a supplier, the period (a year from the start unless given) and its items with their rates."""
    supplier = (body.get("supplier_name") or "").strip()
    items = body.get("items")
    if items is None and body.get("item_code"):               # one item, as the item's own page adds it
        items = [{"item_code": body.get("item_code"), "rate": body.get("rate")}]
    rows = []
    for it in items or []:
        code = (it.get("item_code") or "").strip()
        try:
            rate = float(it.get("rate") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        if code and rate > 0:
            rows.append((code[:60], rate))
    if not supplier or not rows:
        raise HTTPException(400, "The supplier, and at least one item with its agreed rate.")
    if len({c for c, _ in rows}) != len(rows):
        raise HTTPException(400, "An item is on the contract twice.")
    start = _day(body.get("valid_from") or date.today().isoformat(), "start date")
    if body.get("valid_to"):
        end = _day(body["valid_to"], "end date")
    else:                                   # a year: to the day before the start comes round again (29 February counts 364 days)
        try:
            end = start.replace(year=start.year + 1) - timedelta(days=1)
        except ValueError:
            end = start + timedelta(days=364)
    if end < start:
        raise HTTPException(400, "It cannot end before it starts.")
    no = next_number(db, client_id)
    for code, rate in rows:
        db.add(models.DBRateContract(client_id=client_id, contract_no=no, supplier_name=supplier[:120], item_code=code, rate=rate,
                                     valid_from=start.isoformat(), valid_to=end.isoformat(), reference=(body.get("reference") or "").strip()[:120],
                                     created_by_name=actor_name))
    return no, start, end, len(rows)


def contracts(db, client_id):
    """Every contract with its items, the newest first: [{contract_no, supplier_name, valid_from, valid_to, status, items}]."""
    today = date.today().isoformat()
    names = {i.item_code: i.item_name for i in db.query(models.DBItem.item_code, models.DBItem.item_name).filter(models.DBItem.client_id == client_id).all()}
    out = {}
    for c in db.query(models.DBRateContract).filter(models.DBRateContract.client_id == client_id).order_by(models.DBRateContract.id.desc()).all():
        key = c.contract_no or "RC-%d" % c.id
        k = out.setdefault(key, {"contract_no": key, "supplier_name": c.supplier_name or "", "valid_from": c.valid_from or "",
                                 "valid_to": c.valid_to or "", "reference": c.reference or "", "items": []})
        k["items"].append({"id": c.id, "item_code": c.item_code or "", "item_name": names.get(c.item_code, ""), "rate": unit_rate(c.rate)})
    for k in out.values():
        k["status"] = ("not started" if k["valid_from"] > today else "expired" if k["valid_to"] and k["valid_to"] < today else "in force")
        k["days_left"] = (datetime.strptime(k["valid_to"], "%Y-%m-%d").date() - date.today()).days if k["valid_to"] else None
    return list(out.values())


def active_rates(db, client_id, supplier, on=None):
    """{item_code: rate} the supplier's contracts set today: what an order to them picks by itself."""
    on = (on or date.today().isoformat())[:10]
    out = {}
    for c in db.query(models.DBRateContract).filter(models.DBRateContract.client_id == client_id).all():
        if norm_name(c.supplier_name) == norm_name(supplier) and (c.valid_from or "") <= on and (not c.valid_to or c.valid_to >= on):
            out[c.item_code] = unit_rate(c.rate)
    return out


@scheduled_job("rate_contract_expiry")
def job_rate_contract_expiry(db, now):
    """Purchasing is told 30 days and 7 days before a contract runs out - once each."""
    today = now.date()
    told = 0
    seen = set()
    for c in db.query(models.DBRateContract).filter(models.DBRateContract.valid_to != "", models.DBRateContract.valid_to.isnot(None)).all():
        try:
            left = (datetime.strptime(c.valid_to, "%Y-%m-%d").date() - today).days
        except ValueError:
            continue
        for days, flag in ((30, "reminded_30"), (7, "reminded_7")):
            if 0 <= left <= days and not getattr(c, flag):
                setattr(c, flag, 1)
                key = (c.client_id, c.contract_no or c.id, days)
                if key in seen:
                    continue
                seen.add(key)
                items = db.query(models.DBRateContract.id).filter(models.DBRateContract.client_id == c.client_id,
                                                                  models.DBRateContract.contract_no == c.contract_no).count() if c.contract_no else 1
                notify(db, c.client_id, "rate_contract_expiring",
                       "Rate contract %s with %s ends in %d day%s" % (c.contract_no or "", c.supplier_name, left, "" if left == 1 else "s"),
                       "%d item%s at agreed rates until %s. Renew it, or enquire again before it lapses." % (items, "" if items == 1 else "s", c.valid_to),
                       view="rate-contracts-view", ref_type="rate_contract", ref_id=c.id, severity="action")
                told += 1
    db.commit()
    return "%d expiry notices" % told
