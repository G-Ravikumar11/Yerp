"""What a project's purchase orders still commit it to, and what a supplier bill cost - one rule for every screen.

Costs are before GST: the GST on a supplier's bill is input credit, not an expense, so a bill costs its taxable value
(the company's own profit and loss already counts it so). An order is committed for what it has not yet been billed
for: a bill for part of an order leaves the rest of it committed, rather than taking the whole order off - which made
a part-billed order's unbilled balance vanish from the forecast.
"""
from app.core.currency import money

DEAD_ORDER = ("Cancelled", "Rejected", "Closed")
DEAD_BILL = ("Cancelled", "Rejected")


def bill_cost(b):
    """A supplier bill before its GST: what it cost."""
    return money(b.amount if b.amount else max(0.0, (b.total or 0) - (b.tax_amount or 0)))


def live_bill(b):
    return (b.status or "") not in DEAD_BILL and (b.approval_status or "none") != "rejected"


def order_value(p):
    """An order before its GST."""
    return money(p.amount if p.amount else max(0.0, (p.total or 0) - (p.tax_amount or 0)))


def still_committed(orders, bills, live_statuses=None):
    """What `orders` still commit the project to: each live order's value before GST, less what live bills naming it
    have billed before GST, never below nothing. `live_statuses`, when given, are the only order statuses counted."""
    billed = {}
    for b in bills:
        if b.purchase_order_id and live_bill(b):
            billed[b.purchase_order_id] = billed.get(b.purchase_order_id, 0.0) + bill_cost(b)
    total = 0.0
    for p in orders:
        status = p.status or ""
        if status in DEAD_ORDER or (live_statuses is not None and status not in live_statuses):
            continue
        total += max(0.0, order_value(p) - billed.get(p.id, 0.0))
    return money(total)
