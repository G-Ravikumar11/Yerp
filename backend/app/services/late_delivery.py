"""Late deliveries chased: an approved order whose needed-by date has passed with nothing received.

Each day it is late, on the first day and every few days after (a few times at most), the buyer is told - on the bell
and in their notices - and, where the company has turned it on, the supplier is emailed asking when the goods will
come. It stops the moment anything is received against the order, or the order is closed or cancelled. Emailing the
supplier is the company's choice (purchase settings): nothing leaves the company on its own unless it is turned on.
"""
from datetime import date, datetime

from app import models
from app.core.audit import log_audit
from app.core.notifications import default_from_email, notify, notify_employee, send_email_background
from app.core.scheduler import scheduled_job
from app.core.tenant_settings import tenant_setting

CHASE_EVERY = 3          # days between chasers
MAX_CHASES = 5
EMAIL_SUPPLIERS_KEY = "late_delivery_emails"


def emails_on(db, client_id):
    return (tenant_setting(db, client_id, EMAIL_SUPPLIERS_KEY, "0") or "0") == "1"


def _late_days(po, today):
    try:
        due = datetime.strptime((po.needed_by or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - due).days


def due_a_chaser(po, today):
    late = _late_days(po, today)
    if late is None or late < 1 or (po.late_chases or 0) >= MAX_CHASES or (po.late_chased_on or "") == today.isoformat():
        return False
    return (po.late_chases or 0) == 0 or (late - 1) % CHASE_EVERY == 0


def chase(db, client, po, late, today):
    """Tell the buyer, and email the supplier where the company has turned that on. Returns whether the email went."""
    from app.services.po_sending import supplier_email
    text = "%s from %s was needed by %s and nothing has been received - %d day%s late." % (
        po.number, po.supplier_name, po.needed_by, late, "" if late == 1 else "s")
    emailed = False
    if emails_on(db, client.id):
        to = supplier_email(db, client.id, po)
        if to:
            company = client.company_name or "Our company"
            body = ("Dear %s,\n\nOur purchase order %s was needed by %s, and nothing has reached us yet. Please let us know when the "
                    "goods will be delivered.\n\nThank you,\n%s" % (po.supplier_name, po.number, po.needed_by, company))
            emailed, _why = send_email_background(to, "Delivery overdue: %s" % po.number, body, "%s <%s>" % (company, default_from_email()),
                                                  client_id=client.id)
            if emailed:
                log_audit(db, client.id, "late_delivery_chased", "purchase_order", po.id, po.number or "", to)
    notify(db, client.id, "late_delivery", "Late: %s" % po.number, text + (" The supplier has been emailed." if emailed else ""),
           view="purchase-orders-view", ref_type="purchase_order", ref_id=po.id, severity="action")
    notify_employee(db, client.id, po.submitted_by, "Late delivery: %s" % po.number, text, link="/next/store/purchase-orders")
    po.late_chased_on, po.late_chases = today.isoformat(), (po.late_chases or 0) + 1
    return emailed


@scheduled_job("late_deliveries")
def job_late_deliveries(db, now):
    from app.services.procurement import OrderPrefetch
    today = now.date() if isinstance(now, datetime) else date.today()
    orders = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.status == "Approved", models.DBPurchaseOrder.needed_by != "",
                                                     models.DBPurchaseOrder.needed_by < today.isoformat()).all()
    if not orders:
        return "nothing late"
    pre = OrderPrefetch(db, orders)
    chased = mailed = 0
    clients = {}
    for po in orders:
        if any(v > 0 for v in pre.received(po.id).values()):
            continue                        # goods have come: the chasing stops
        if not due_a_chaser(po, today):
            continue
        client = clients.get(po.client_id) or clients.setdefault(po.client_id, db.get(models.DBClient, po.client_id))
        mailed += 1 if chase(db, client, po, _late_days(po, today), today) else 0
        chased += 1
    db.commit()
    return "%d late orders chased, %d suppliers emailed" % (chased, mailed)
