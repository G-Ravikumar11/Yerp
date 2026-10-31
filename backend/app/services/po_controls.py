"""A purchase order checked before the money is committed: against the project's budget, and against what the item has
cost before.

Budget. A PO line can name the BOQ line or heading it buys for. Each such line is set against that item's budget, read
from the project's budget-against-actual (services/earned_value.py): what is already spent on it (store issues and
measured subcontract work), what other live orders on it have still to deliver, and this line. Past the budget, the
order needs a reason, and goes on to the higher approver - the Master - never approved on the nod.

Price. Every purchase order approved is a price paid: the last price per item per supplier is read from them. A line
whose rate is more than the company's alert % (10 unless set) above the supplier's last price - or anyone's, when this
supplier has not sold it before - or above a rate contract in force, is flagged on the order and in Approvals. The
item's price trend is the same list, in date order.
"""
import json
from datetime import date

from fastapi import HTTPException

from app import models
from app.core.currency import money, unit_rate
from app.core.tenant_settings import put_setting, tenant_setting
from app.services.crm import norm_name

PAID = ("Approved", "Closed")                    # an order whose prices were paid (or are being)
LIVE = ("Draft", "Awaiting Approval", "Approved")
RATE_ALERT_KEY = "rate_alert_pct"


# --- the budget ---------------------------------------------------------------------------------------------------

def budget_heads(db, client_id, job):
    """{BOQ key: {"key", "label", "budget", "spent", "lines": [keys]}} for every budgeted line and heading of the job."""
    from app.services.earned_value import earned_value
    ev = earned_value(db, client_id, job)
    out = {}
    for l in ev["lines"]:
        if l["budget"] > 0:
            out[l["key"]] = {"key": l["key"], "label": ("%s %s" % (l["item_no"] or "", (l["description"] or "").split("\n")[0][:60])).strip(),
                             "budget": l["budget"], "spent": l["ac"], "lines": [l["key"]], "heading": False}
    for h in ev["headings"]:
        if h["budget"] > 0:
            out[h["key"]] = {"key": h["key"], "label": ("%s %s" % (h["item_no"] or "", (h["description"] or "").split("\n")[0][:60])).strip(),
                             "budget": h["budget"], "spent": h["ac"], "heading": True,
                             "lines": [l["key"] for l in ev["lines"] if h["key"] in l["path"]]}
    return out


def _open_value(db, client_id, job_id, exclude_po_id):
    """{BOQ key: value still to be delivered on live orders of the project}, before GST."""
    from app.services.procurement import OrderPrefetch
    orders = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.job_id == job_id,
                                                     models.DBPurchaseOrder.status.in_(LIVE), models.DBPurchaseOrder.id != (exclude_po_id or 0)).all()
    if not orders:
        return {}
    pre = OrderPrefetch(db, orders)
    out = {}
    for po in orders:
        got = pre.received(po.id)
        for l in pre.lines.get(po.id, []):
            if l.boq_key:
                left = max(0.0, (l.qty or 0) - got.get(l.id, 0.0))
                out[l.boq_key] = out.get(l.boq_key, 0.0) + left * (l.price or 0)
    return out


def budget_check(db, client_id, job_id, lines, exclude_po_id=None):
    """For each BOQ key the lines name: its budget, spent, committed on other orders, this order, and how far over."""
    keyed = [l for l in lines if (l.get("boq_key") or "").strip()]
    if not job_id or not keyed:
        return []
    job = db.query(models.DBJob).filter(models.DBJob.id == job_id, models.DBJob.client_id == client_id).first()
    if job is None:
        return []
    heads = budget_heads(db, client_id, job)
    open_ = _open_value(db, client_id, job_id, exclude_po_id)
    this = {}
    for l in keyed:
        this[l["boq_key"]] = this.get(l["boq_key"], 0.0) + float(l.get("qty") or 0) * float(l.get("price") or 0)
    out = []
    for key, value in this.items():
        h = heads.get(key)
        if h is None:
            out.append({"key": key, "label": key, "budget": None, "spent": None, "committed": None, "this": money(value), "over_by": 0.0,
                        "note": "No budget is set for it."})
            continue
        committed = money(sum(v for k, v in open_.items() if k in h["lines"] or k == key))
        used = money(h["spent"] + committed + value)
        out.append({"key": key, "label": h["label"], "budget": h["budget"], "spent": h["spent"], "committed": committed,
                    "this": money(value), "over_by": money(max(0.0, used - h["budget"])), "note": ""})
    return out


def over_budget(rows):
    return [r for r in rows if r["over_by"] > 0.5]


# --- prices -------------------------------------------------------------------------------------------------------

def alert_pct(db, client_id):
    try:
        return float(tenant_setting(db, client_id, RATE_ALERT_KEY, "10") or 10)
    except ValueError:
        return 10.0


def set_alert_pct(db, client_id, pct):
    pct = float(pct)
    if pct < 0 or pct > 500:
        raise HTTPException(400, "The alert is a % between 0 and 500.")
    put_setting(db, client_id, RATE_ALERT_KEY, str(pct))


def price_points(db, client_id, item_code, exclude_po_id=None):
    """Every price this item was bought at, oldest first: [{on, rate, supplier, po, po_id}]."""
    code = (item_code or "").strip()
    if not code:
        return []
    rows = (db.query(models.DBPurchaseOrder, models.DBPurchaseOrderLineItem)
            .join(models.DBPurchaseOrderLineItem, models.DBPurchaseOrderLineItem.order_id == models.DBPurchaseOrder.id)
            .filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.status.in_(PAID),
                    models.DBPurchaseOrder.id != (exclude_po_id or 0), models.DBPurchaseOrderLineItem.item_code == code).all())
    out = [{"on": (po.issue_date or po.created_at or "")[:10], "rate": unit_rate(l.price), "supplier": po.supplier_name or "",
            "po": po.number or "", "po_id": po.id} for po, l in rows if (l.price or 0) > 0]
    return sorted(out, key=lambda p: (p["on"], p["po_id"]))


def last_prices(points):
    """{supplier: the last point} - the last purchase price per supplier."""
    last = {}
    for p in points:
        last[norm_name(p["supplier"])] = p
    return last


def contract_rate(db, client_id, supplier, item_code, on=None):
    on = (on or date.today().isoformat())[:10]
    for c in db.query(models.DBRateContract).filter(models.DBRateContract.client_id == client_id,
                                                    models.DBRateContract.item_code == (item_code or "").strip()).all():
        if norm_name(c.supplier_name) == norm_name(supplier) and (c.valid_from or "") <= on and (not c.valid_to or c.valid_to >= on):
            return c
    return None


def rate_flags(db, client_id, supplier, lines, exclude_po_id=None):
    """Lines priced more than the alert % over the supplier's last price (or anyone's), or over a rate contract in force."""
    pct = alert_pct(db, client_id)
    out = []
    for l in lines:
        code, rate = (l.get("item_code") or "").strip(), float(l.get("price") or 0)
        if not code or rate <= 0:
            continue
        points = price_points(db, client_id, code, exclude_po_id)
        last = last_prices(points).get(norm_name(supplier)) or (points[-1] if points else None)
        c = contract_rate(db, client_id, supplier, code)
        reasons = []
        if last and rate > last["rate"] * (1 + pct / 100.0) + 0.0001:
            reasons.append("%.1f%% above the last price %s (%s, %s)" % ((rate / last["rate"] - 1) * 100, last["rate"], last["supplier"], last["po"]))
        if c and rate > c.rate + 0.0001:
            reasons.append("above the rate contract %s" % unit_rate(c.rate))
        if reasons:
            out.append({"item_code": code, "description": l.get("description") or "", "rate": unit_rate(rate),
                        "last_rate": last["rate"] if last else None, "contract_rate": unit_rate(c.rate) if c else None,
                        "why": "; ".join(reasons)})
    return out


# --- the order ---------------------------------------------------------------------------------------------------

def check_order(db, client_id, order, lines, reason=""):
    """Check an order's lines as it is saved. Over the budget without a reason is refused; with one, the order is marked
    over budget (and goes to the higher approver). Price alerts are kept on the order. Returns (budget rows, rate flags)."""
    rows = budget_check(db, client_id, order.job_id, lines, order.id)
    over = over_budget(rows)
    reason = (reason or "").strip()
    if over and len(reason) < 5:
        raise HTTPException(409, "Over the project's budget: %s. Give the reason for going over (budget_reason) to save it; "
                                 "it then goes to the higher approver." % "; ".join(
                                     "%s by %s" % (r["label"], r["over_by"]) for r in over))
    order.over_budget = bool(over)
    order.budget_reason = reason if over else ""
    flags = rate_flags(db, client_id, order.supplier_name, lines, order.id)
    order.rate_flags = json.dumps(flags) if flags else ""
    return rows, flags


def warnings_of(order):
    """What an approver should see about an order before signing it."""
    out = []
    if getattr(order, "over_budget", False):
        out.append("Over the project budget: %s" % (order.budget_reason or "no reason given"))
    try:
        flags = json.loads(getattr(order, "rate_flags", "") or "[]")
    except ValueError:
        flags = []
    out += ["Rate alert - %s: %s" % (f.get("description") or f.get("item_code"), f.get("why")) for f in flags]
    return out
