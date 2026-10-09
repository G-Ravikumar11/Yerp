"""A review of a purchase order before it is approved or sent: what looks wrong, and a short plain summary.

The flags are plain code and always work. The model (Groq by default) only words a summary from the flags and the
order's own figures.

    GET /api/ai/purchase-orders/{order_id}/review
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from Ai_service import guard
from Ai_service.llm_client import ask
from app import models
from app.core.auth import require_erp_read
from app.core.currency import inr
from app.db import get_db
from app.services.crm import norm_name
from app.services.procurement import purchase_order_or_404, purchase_order_to_dict

router = APIRouter()

ACTION_KEY = "ai_po_review"
RATE_RISE = 0.10          # a price more than 10% above the last one paid is worth a look
RECENT_DAYS = 7

SYSTEM = (
    "You help a construction company's buyer read a purchase order before it goes out. You are given the order's "
    "figures and a list of checks already worked out. Write at most four short sentences in plain English: what the "
    "order is, then the most important concerns first. Use only what you are given. Do not invent reasons, and do not "
    "tell the reader to approve or reject."
)


def _last_prices(db, client_id, order_id):
    """{key: (price, order number)} - the most recent price paid per item, from earlier orders of this company."""
    out = {}
    q = db.query(models.DBPurchaseOrderLineItem, models.DBPurchaseOrder).join(
        models.DBPurchaseOrder, models.DBPurchaseOrderLineItem.order_id == models.DBPurchaseOrder.id).filter(
        models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.id < order_id,
        models.DBPurchaseOrder.status != "Cancelled", models.DBPurchaseOrderLineItem.price > 0).order_by(
        models.DBPurchaseOrder.id.asc())
    for line, po in q.all():
        key = (line.item_code or "").strip().lower() or (line.description or "").strip().lower()
        if key:
            out[key] = (line.price, po.number)
    return out


def find_flags(po: dict, last_prices: dict, supplier, recent_same_supplier: list, today=None) -> list:
    """Checks anyone could do by hand. Each flag: {level: stop|check|note, text}."""
    today = today or date.today()
    flags = []
    lines = po.get("line_items") or []
    if not lines:
        flags.append({"level": "stop", "text": "The order has no lines."})
    for l in lines:
        name = l.get("description") or l.get("item_code") or "A line"
        if (l.get("qty") or 0) <= 0:
            flags.append({"level": "stop", "text": "%s has no quantity." % name})
        if (l.get("price") or 0) <= 0:
            flags.append({"level": "stop", "text": "%s has no price." % name})
            continue
        key = (l.get("item_code") or "").strip().lower() or (l.get("description") or "").strip().lower()
        last = last_prices.get(key)
        if last and l["price"] > last[0] * (1 + RATE_RISE):
            flags.append({"level": "check", "text": "%s is %s, which is %d%% above the %s paid on %s." % (
                name, inr(l["price"]), round((l["price"] / last[0] - 1) * 100), inr(last[0]), last[1])})
    if supplier is None:
        flags.append({"level": "note", "text": "%s is not in the supplier register." % (po.get("supplier_name") or "The supplier")})
    elif not (supplier.gstin or "").strip():
        flags.append({"level": "check", "text": "%s has no GSTIN on record, so input tax credit on this order is at risk." % supplier.name})
    needed = po.get("needed_by") or ""
    if not needed:
        flags.append({"level": "note", "text": "No delivery date is set."})
    elif needed < today.isoformat() and po.get("status") in ("Draft", "Approved", None):
        flags.append({"level": "check", "text": "The needed-by date (%s) has already passed." % needed})
    if po.get("billed_total", 0) > (po.get("total") or 0) + 0.5:
        flags.append({"level": "stop", "text": "Bills against this order (%s) are more than the order itself (%s)." % (inr(po["billed_total"]), inr(po["total"]))})
    for other in recent_same_supplier:
        flags.append({"level": "check", "text": "%s to the same supplier was raised on %s for %s; this may be a duplicate." % (other["number"], other["issue_date"], inr(other["total"]))})
    return flags


@router.get("/api/ai/purchase-orders/{order_id}/review")
def review_po(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    row = purchase_order_or_404(db, client.id, order_id)
    po = purchase_order_to_dict(db, row)
    supplier = next((s for s in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client.id).all()
                     if norm_name(s.name) == norm_name(row.supplier_name)), None)
    since = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    recent = [{"number": o.number, "issue_date": o.issue_date, "total": o.total or 0} for o in db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == client.id, models.DBPurchaseOrder.id != row.id,
        models.DBPurchaseOrder.status != "Cancelled", models.DBPurchaseOrder.issue_date >= since).all()
        if norm_name(o.supplier_name) == norm_name(row.supplier_name) and row.supplier_name]
    flags = find_flags(po, _last_prices(db, client.id, row.id), supplier, recent)
    out = {"flags": flags, "stop": any(f["level"] == "stop" for f in flags), "summary": None, "ai": guard.status()}
    if not out["ai"]["available"]:
        return out
    facts = "\n".join(["order: %s" % po["number"], "supplier: %s" % po["supplier_name"], "project: %s" % po["job_name"],
                       "total: %s (tax %s)" % (inr(po["total"]), inr(po["tax_amount"])), "needed by: %s" % (po["needed_by"] or "not set"),
                       "lines: %d" % len(po["line_items"]), "checks:"] + (["- [%s] %s" % (f["level"], f["text"]) for f in flags] or ["- none raised"]))
    result = guard.run_feature(db, request, client, ACTION_KEY, "PO review %s" % po["number"], po["number"],
                               lambda: ask(SYSTEM, facts, smart=False, max_tokens=350))
    if result.ok:
        out["summary"], out["model"] = result.text, result.model
    else:
        out["ai_message"] = result.message
    return out
