"""Late deliveries chased: an approved order whose needed-by date has come with nothing received.

On the needed-by date itself and every three days after (a few times at most), the buyer is told - on the bell and in
their notices - and, where the company has turned it on, the supplier is emailed asking when the goods will come, with
what is still to come. A chaser is counted from the last one sent, so a day the server missed does not skip one. It stops the moment anything is received against the order, or the order is closed or cancelled. Emailing the
supplier is the company's choice (purchase settings): nothing leaves the company on its own unless it is turned on.
"""
from datetime import date, datetime

from app import models
from app.core.audit import log_audit
from app.core.notifications import default_from_email, notify, notify_employee, send_email_background
from app.core.scheduler import scheduled_job
from app.core.tenant_settings import tenant_setting
from app.services.po_sending import EMAIL
from app.services.rfq_chasers import _day

CHASE_EVERY = 3          # days between chasers
MAX_CHASES = 5
EMAIL_SUPPLIERS_KEY = "late_delivery_emails"


def emails_on(db, client_id):
    return (tenant_setting(db, client_id, EMAIL_SUPPLIERS_KEY, "1") or "1") == "1"


def _late_days(po, today):
    due = _day(po.needed_by)
    return (today - due).days if due else None


def due_a_chaser(po, today):
    """On the needed-by date, then once CHASE_EVERY days have gone by since the last chaser."""
    late = _late_days(po, today)
    if late is None or late < 0 or (po.late_chases or 0) >= MAX_CHASES:
        return False
    last = _day(po.late_chased_on)
    return last is None or (today - last).days >= CHASE_EVERY


def still_to_come(db, po, received):
    """'50 Bags of Cement OPC 53; 2 MT of TMT 12mm' - each line's ordered quantity less what has been received."""
    out = []
    for l in db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id).order_by(
            models.DBPurchaseOrderLineItem.id).all():
        left = (l.qty or 0) - (received.get(l.id, 0) or 0)
        if left > 0.0005:
            out.append("%g %s of %s" % (round(left, 3), (l.uom or "").strip() or "no.", l.description or l.item_code or "the item"))
    return out


def chase(db, client, po, late, today, lines=None):
    """Tell the buyer, and email the supplier where the company has turned that on. Returns whether the email went."""
    from app.services.po_sending import supplier_email
    when = "is needed today" if late == 0 else "was needed by %s - %d day%s late" % (po.needed_by, late, "" if late == 1 else "s")
    text = "%s from %s %s, and nothing has been received." % (po.number, po.supplier_name, when)
    emailed = False
    if emails_on(db, client.id):
        to = supplier_email(db, client.id, po)
        if EMAIL.match(to or ""):
            company = client.company_name or "Our company"
            owed = "".join("\n  - %s" % l for l in (lines or []))
            ask = ("Our purchase order %s is needed today, %s, and has not reached us yet." % (po.number, po.needed_by) if late == 0 else
                   "Our purchase order %s was needed by %s, and nothing has reached us yet." % (po.number, po.needed_by))
            body = ("Dear %s,\n\n%s%s\n\nPlease let us know when the goods will be delivered.\n\nThank you,\n%s" % (
                po.supplier_name, ask, ("\n\nStill to come:" + owed) if owed else "", company))
            subject = ("Delivery due today: %s" if late == 0 else "Delivery overdue: %s") % po.number
            emailed, _why = send_email_background(to, subject, body, "%s <%s>" % (company, default_from_email()), client_id=client.id)
            if emailed:
                log_audit(db, client.id, "late_delivery_chased", "purchase_order", po.id, po.number or "", to)
    notify(db, client.id, "late_delivery", ("Due today, not received: %s" if late == 0 else "Late: %s") % po.number, text + (" The supplier has been emailed." if emailed else ""),
           view="purchase-orders-view", ref_type="purchase_order", ref_id=po.id, severity="action")
    notify_employee(db, client.id, po.submitted_by, ("Delivery due today: %s" if late == 0 else "Late delivery: %s") % po.number, text, link="/next/store/purchase-orders")
    po.late_chased_on, po.late_chases = today.isoformat(), (po.late_chases or 0) + 1
    return emailed


@scheduled_job("late_deliveries")
def job_late_deliveries(db, now):
    from app.services.procurement import OrderPrefetch
    today = now.date() if isinstance(now, datetime) else date.today()
    orders = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.status == "Approved", models.DBPurchaseOrder.needed_by != "",
                                                     models.DBPurchaseOrder.needed_by <= today.isoformat()).all()
    if not orders:
        return "nothing late"
    pre = OrderPrefetch(db, orders)
    chased = mailed = 0
    clients = {}
    for po in orders:
        got = pre.received(po.id)
        if any(v > 0 for v in got.values()):
            continue                        # goods have come: the chasing stops
        if not due_a_chaser(po, today):
            continue
        client = clients.get(po.client_id) or clients.setdefault(po.client_id, db.get(models.DBClient, po.client_id))
        mailed += 1 if chase(db, client, po, _late_days(po, today), today, still_to_come(db, po, got)) else 0
        chased += 1
    db.commit()
    return "%d late orders chased, %d suppliers emailed" % (chased, mailed)
