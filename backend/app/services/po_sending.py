"""Sending a purchase order to its supplier: the order's PDF, by email, from the company's connected Gmail (or the
server's own mail account).

The buyer's "Send email" button sends any order, with wording they have read. An order made by awarding an enquiry is
sent by itself the moment it is finally approved: the supplier was chosen on the comparison and the order says what
they quoted, so nobody has to remember to send it. If it cannot go - no email on file, mail not connected - the buyer
is told, and the approval stands.
"""
import base64
import re

from app import models
from app.core.audit import log_audit
from app.core.notifications import default_from_email, notify, notify_employee, send_email_background
from app.services.crm import norm_name

EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def pdf_name(order):
    return "%s.pdf" % re.sub(r"[^A-Za-z0-9]+", "_", order.number or "order").strip("_")


def supplier_email(db, client_id, order):
    """The order's own supplier email, else the supplier master's, else the address the supplier was invited at."""
    if (order.supplier_email or "").strip():
        return order.supplier_email.strip()
    sup = next((s for s in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client_id).all()
                if norm_name(s.name) == norm_name(order.supplier_name)), None)
    if sup is not None and (sup.email or "").strip():
        return sup.email.strip()
    inv = next((i for i in db.query(models.DBRfqInvite).join(models.DBRfq, models.DBRfq.id == models.DBRfqInvite.rfq_id)
                .filter(models.DBRfq.client_id == client_id).order_by(models.DBRfqInvite.id.desc()).all()
                if norm_name(i.supplier_name) == norm_name(order.supplier_name) and (i.email or "").strip()), None)
    return inv.email.strip() if inv is not None else ""


def send_order(db, client, order, to, subject=None, text=None):
    """Email the order and its PDF. Returns (ok, message)."""
    from app.documents import form_pdf
    from app.documents.forms import po_form_spec
    from app.ai.po_supplier_email import plain_draft
    from app.services.procurement import purchase_order_to_dict
    if not EMAIL.match(to or ""):
        return False, "no valid supplier email address"
    if not form_pdf.PDF_AVAILABLE:
        return False, "the PDF library is not installed on this server"
    company = client.company_name or "Our company"
    draft = plain_draft(purchase_order_to_dict(db, order), company)
    pdf = form_pdf.build_form_pdf(po_form_spec(db, client, order))
    return send_email_background(to, (subject or draft["subject"]).strip()[:200], (text or draft["body"]).strip(),
                                 "%s <%s>" % (company, default_from_email()), client_id=client.id,
                                 pdf_b64=base64.b64encode(pdf).decode(), pdf_filename=pdf_name(order))


def from_an_award(db, order):
    return db.query(models.DBPurchaseOrderLineItem.id).filter(models.DBPurchaseOrderLineItem.order_id == order.id,
                                                             models.DBPurchaseOrderLineItem.rfq_line_id.isnot(None)).first() is not None


def send_when_approved(db, client_id, order, request=None):
    """Called once an order is finally approved: an order from an award goes to its supplier now. Never raises - a mail
    that cannot go must not undo the approval; the buyer is told instead."""
    try:
        if not from_an_award(db, order):
            return None
        client = db.get(models.DBClient, client_id)
        to = supplier_email(db, client_id, order)
        ok, message = send_order(db, client, order, to) if to else (False, "no email for %s on file" % (order.supplier_name or "the supplier"))
        if ok:
            order.supplier_email = order.supplier_email or to
            log_audit(db, client_id, "purchase_order_emailed", "purchase_order", order.id, order.number or "",
                      "Sent to %s on approval" % to, request)
            text = "%s approved and sent to %s (%s)." % (order.number, order.supplier_name, to)
        else:
            text = "%s is approved but was not sent to %s: %s. Send it from the order." % (order.number, order.supplier_name, message)
        notify(db, client_id, "po_sent" if ok else "po_not_sent", text, view="purchase-orders", ref_type="purchase_order",
               ref_id=order.id, severity="info" if ok else "action")
        notify_employee(db, client_id, order.submitted_by, "Sent to supplier" if ok else "Send it yourself", text)
        db.commit()
        return ok
    except Exception:                       # pragma: no cover - mail must never fail an approval
        import logging
        logging.getLogger(__name__).exception("Sending %s on approval failed", getattr(order, "number", order))
        return False
