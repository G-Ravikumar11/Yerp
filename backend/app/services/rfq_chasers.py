"""Suppliers chased for their quotes.

An enquiry with a quotes-due date is followed up by the server: the link is emailed to each supplier invited with an
email address; a supplier who has not quoted is reminded two days before the date and on the day itself (once a day
at most); and on the due date the buyer is given the L1 summary - who quoted, who is cheapest, and by how much. An
enquiry without a due date is never chased: setting the date is what asks for it.
"""
from datetime import date, datetime

from app import models
from app.core.audit import log_audit
from app.core.currency import inr
from app.core.notifications import default_from_email, notify, notify_employee, send_email_background
from app.core.scheduler import scheduled_job
from app.services.po_sending import EMAIL

REMIND_DAYS_LEFT = (2, 0)          # two days before the quotes are due, and on the day


def _day(raw):
    try:
        return datetime.strptime((raw or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def link_of(rfq, inv):
    return "%s/next/quote?token=%s" % ((rfq.link_base or "").rstrip("/"), inv.token)


def email_invite(db, client, rfq, inv, reminder=False):
    """Email a supplier the link to his own quote page. Returns (ok, message); nothing is raised."""
    if not EMAIL.match(inv.email or ""):
        return False, "no valid email for %s" % (inv.supplier_name or "the supplier")
    if not (rfq.link_base or "").startswith("http"):
        return False, "the site's address is not known yet"
    company = client.company_name or "Our company"
    due = (" Quotes are due by %s." % _day(rfq.quotes_due).strftime("%d %b %Y")) if _day(rfq.quotes_due) else ""
    subject = ("Reminder: " if reminder else "") + "Request for quotation %s: %s" % (rfq.number, rfq.title or "")
    body = ("Dear %s,\n\n%s requests your quotation for %s (%s)%s.%s\n\nSee the items and send your rates, or your quotation "
            "file (PDF, Word, Excel or a photo), here:\n%s\n\nThank you." % (
                inv.supplier_name, company, rfq.title or "the items listed", rfq.number,
                (", needed by %s" % rfq.needed_by) if rfq.needed_by else "", due, link_of(rfq, inv)))
    ok, message = send_email_background(inv.email, subject[:200], body, "%s <%s>" % (company, default_from_email()), client_id=client.id)
    if ok:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if reminder:
            inv.reminded_on, inv.reminders = now[:10], (inv.reminders or 0) + 1
        else:
            inv.emailed_at = now
        log_audit(db, client.id, "rfq_invite_reminded" if reminder else "rfq_invite_emailed", "rfq", rfq.id, rfq.number,
                  "%s <%s>" % (inv.supplier_name, inv.email))
    return ok, message


def answered(inv):
    return bool(inv.quote_id or inv.submitted_at or inv.document_id)


def l1_summary(db, rfq):
    """The buyer's summary on the due date, in a line or two."""
    from app.services.procurement import comparative_statement
    st = comparative_statement(db, rfq)
    invites = db.query(models.DBRfqInvite).filter(models.DBRfqInvite.rfq_id == rfq.id).all()
    quoted = len(st["suppliers"])
    asked = max(len(invites), quoted)
    if not quoted:
        return "%s: quotes were due today and nobody has quoted (%d asked)." % (rfq.number, asked)
    head = "%s: quotes due today, %d of %d quoted." % (rfq.number, quoted, asked)
    if st.get("l1"):
        l1 = next(s for s in st["suppliers"] if s["supplier_name"] == st["l1"])
        saving = (" %s less than L2." % inr(st["saving_vs_l2"])) if st.get("saving_vs_l2") else ""
        return "%s L1 is %s at %s landed.%s" % (head, st["l1"], inr(l1["landed"]), saving)
    return "%s Nobody has priced every item yet; the comparison shows the lowest for each." % head


@scheduled_job("rfq_chasers")
def job_rfq_chasers(db, now):
    """Remind the suppliers who have not quoted, and give the buyer the L1 summary on the due date."""
    today = now.date() if isinstance(now, datetime) else date.today()
    reminded = summaries = 0
    for rfq in db.query(models.DBRfq).filter(models.DBRfq.status == "OPEN", models.DBRfq.quotes_due.isnot(None),
                                             models.DBRfq.quotes_due != "").all():
        due = _day(rfq.quotes_due)
        if due is None:
            continue
        client = db.get(models.DBClient, rfq.client_id)
        left = (due - today).days
        if left in REMIND_DAYS_LEFT:
            for inv in db.query(models.DBRfqInvite).filter(models.DBRfqInvite.rfq_id == rfq.id).all():
                if answered(inv) or (inv.reminded_on or "") == today.isoformat() or not EMAIL.match(inv.email or ""):
                    continue
                ok, _ = email_invite(db, client, rfq, inv, reminder=True)
                reminded += 1 if ok else 0
        if left <= 0 and not rfq.l1_sent_at:
            text = l1_summary(db, rfq)
            notify(db, rfq.client_id, "rfq_l1", text, view="enquiries", ref_type="rfq", ref_id=rfq.id, severity="action")
            notify_employee(db, rfq.client_id, rfq.created_by_id, "Quotes due: %s" % rfq.number, text, link="/next/store/enquiries/%d" % rfq.id)
            rfq.l1_sent_at = now.strftime("%Y-%m-%d %H:%M:%S")
            summaries += 1
        db.commit()
    return "%d reminders sent, %d L1 summaries" % (reminded, summaries)
