"""The supplier scorecard: how each supplier has done for us, to weigh beside their price.

- On-time delivery %: of their orders with a needed-by date and goods received, the share whose last receipt came on or
  before that date.
- Rejection %: of what they delivered, the share rejected at the gate (by quantity).
- Price position: across the enquiries they quoted on, how far their total sat above the cheapest (0% = they were L1),
  and how often they were L1.
- Response time: the average days from the link going to them to their quote coming back.

Read from the goods receipts (the older ones and the Store Hub's posted GRNs), the enquiries and the quote links. The
award comparison shows it beside each supplier; a monthly scorecard goes to purchasing when the company has named an
address for it.
"""
from datetime import datetime

from app import models
from app.core.scheduler import scheduled_job
from app.services.crm import norm_name

POSTED_OLD = ("POSTED",)
LIVE_PO = ("Approved", "Closed")


def _date(raw):
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def scorecards(db, client_id):
    """{normalised supplier name: card} for every supplier with something to score."""
    from app.models.store_core import DocStatus
    from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
    cards = {}

    def card(name):
        key = norm_name(name)
        if key not in cards:
            cards[key] = {"supplier_name": name, "orders_due": 0, "orders_on_time": 0, "received_qty": 0.0, "rejected_qty": 0.0,
                          "quoted": 0, "l1": 0, "above_l1": [], "responses": []}
        return cards[key]

    # Deliveries: each order's last receipt against its needed-by date; what was rejected of what came.
    orders = {p.id: p for p in db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id,
                                                                     models.DBPurchaseOrder.status.in_(LIVE_PO)).all()}
    last = {}
    for gr in db.query(models.DBGoodsReceipt).filter(models.DBGoodsReceipt.client_id == client_id,
                                                     models.DBGoodsReceipt.status.in_(POSTED_OLD)).all():
        d = _date(gr.received_on)
        if d and gr.purchase_order_id in orders:
            last[gr.purchase_order_id] = max(last.get(gr.purchase_order_id, d), d)
        for l in db.query(models.DBGoodsReceiptLine).filter(models.DBGoodsReceiptLine.goods_receipt_id == gr.id).all():
            c = card(gr.supplier_name or (orders[gr.purchase_order_id].supplier_name if gr.purchase_order_id in orders else ""))
            c["received_qty"] += l.received_qty or 0
            c["rejected_qty"] += l.rejected_qty or 0
    hub = (db.query(DBStoreGrn, DBStoreGrnLine).join(DBStoreGrnLine, DBStoreGrnLine.grn_id == DBStoreGrn.id)
           .filter(DBStoreGrn.client_id == client_id, DBStoreGrn.status == DocStatus.POSTED.value).all())
    for g, l in hub:
        if g.po_id in orders and g.grn_date:
            last[g.po_id] = max(last.get(g.po_id, g.grn_date), g.grn_date)
        c = card(g.supplier_name or (orders[g.po_id].supplier_name if g.po_id in orders else ""))
        c["received_qty"] += float(l.received_qty or 0)
        c["rejected_qty"] += float(l.rejected_qty or 0)
    for po_id, got in last.items():
        p = orders[po_id]
        due = _date(p.needed_by)
        if due:
            c = card(p.supplier_name)
            c["orders_due"] += 1
            c["orders_on_time"] += 1 if got <= due else 0

    # Price: each quote's landed total against the cheapest on its enquiry.
    from app.services.procurement import comparative_statement
    for r in db.query(models.DBRfq).filter(models.DBRfq.client_id == client_id).all():
        sups = [s for s in comparative_statement(db, r)["suppliers"] if s["complete"] and s["landed"] > 0]
        if not sups:
            continue
        low = min(s["landed"] for s in sups)
        for s in sups:
            c = card(s["supplier_name"])
            c["quoted"] += 1
            c["l1"] += 1 if s["landed"] <= low + 0.005 else 0
            c["above_l1"].append((s["landed"] - low) / low * 100 if low else 0.0)

    # Response: the link sent to the quote back.
    for inv in db.query(models.DBRfqInvite).filter(models.DBRfqInvite.client_id == client_id, models.DBRfqInvite.submitted_at != "").all():
        a, b = _date(inv.created_at), _date(inv.submitted_at)
        if a and b:
            card(inv.supplier_name)["responses"].append((b - a).days)

    out = {}
    for key, c in cards.items():
        if not c["supplier_name"]:
            continue
        out[key] = {"supplier_name": c["supplier_name"],
                    "on_time_pct": round(c["orders_on_time"] / c["orders_due"] * 100, 1) if c["orders_due"] else None, "orders_scored": c["orders_due"],
                    "rejection_pct": round(c["rejected_qty"] / c["received_qty"] * 100, 1) if c["received_qty"] else None,
                    "above_l1_pct": round(sum(c["above_l1"]) / len(c["above_l1"]), 1) if c["above_l1"] else None,
                    "l1_wins": c["l1"], "quoted": c["quoted"],
                    "response_days": round(sum(c["responses"]) / len(c["responses"]), 1) if c["responses"] else None}
    return out


def card_for(cards, name):
    return cards.get(norm_name(name))


def scorecard_text(cards):
    """The monthly email to purchasing: one line per supplier, the best on-time first."""
    def f(v, unit):
        return "-" if v is None else "%s%s" % (v, unit)
    rows = sorted(cards.values(), key=lambda c: (-(c["on_time_pct"] or -1), c["supplier_name"]))
    lines = ["%-28s on time %-7s rejected %-7s above L1 %-7s L1 %d of %d  replies in %s" % (
        c["supplier_name"][:28], f(c["on_time_pct"], "%"), f(c["rejection_pct"], "%"), f(c["above_l1_pct"], "%"), c["l1_wins"], c["quoted"],
        f(c["response_days"], " days")) for c in rows]
    return "Supplier scorecard\n\n" + "\n".join(lines) + "\n\nOn time: orders whose last delivery came by the needed-by date. Above L1: how far " \
                                                        "their quote sat above the cheapest, on average."


def month_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m")


@scheduled_job("supplier_scorecard", month_key)
def job_supplier_scorecard(db, now):
    """Once a month: the scorecard to each company's purchasing address - only where the company has named one."""
    from app.core.notifications import default_from_email, send_email_background
    from app.core.tenant_settings import tenant_setting
    sent = 0
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        to = [e.strip() for e in (tenant_setting(db, client.id, PURCHASING_EMAILS_KEY, "") or "").split(",") if "@" in e]
        if not to:
            continue
        cards = scorecards(db, client.id)
        if not cards:
            continue
        body = scorecard_text(cards)
        for addr in to:
            ok, _ = send_email_background(addr, "Supplier scorecard - %s" % now.strftime("%B %Y"), body,
                                          "%s <%s>" % (client.company_name or "Y ERP", default_from_email()), client_id=client.id)
            sent += 1 if ok else 0
    return "%d scorecard emails" % sent


PURCHASING_EMAILS_KEY = "purchasing_emails"
