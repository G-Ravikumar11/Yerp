"""The daily summary email, sent every morning from seven.

    The Master     Money position (receivables, payables, bank balance) and everything pending across the company.
    Each employee  Their own pending work only: approvals waiting on them, tasks given to them, programme activities
                   they own that are late or due, site diaries they must sign off. Nobody gets an email on a day with
                   nothing pending for them.

An employee's email goes to the address the organisation gave them; when they have none, to their personal email.
Wording is plain business terms: "Receivables", "Payables", "Pending with you", each item with what to do and a link
to the page where it is done.
"""
import html
import os
import threading
from datetime import date, timedelta

from app import models
from app.core.config import logger

# Every item on the company-wide list in plain business terms, by its kind: (title, what to do).
PLAIN = {
    "unbilled": ("Work measured, not yet billed", "Raise the RA bill for it."),
    "over_run": ("Work done beyond the order quantity", "Raise a variation or amend the order."),
    "certify": ("RA bills pending certification", "Certify them or send them back."),
    "variations": ("Variations pending approval", "Approve or reject them."),
    "negative_stock": ("Negative stock in the store", "Post the pending receipts or correct the issues."),
    "low_stock": ("Items below reorder level", "Raise indents or purchase orders."),
    "diaries": ("Site diaries not signed off", "Sign off each day's diary."),
    "receipts": ("Goods receipts not posted", "Approve and post them."),
    "receivables": ("Overdue receivables", "Follow up for payment."),
    "retention": ("Retention due on completed projects", "Claim the retention."),
    "ra_receivable": ("Certified bills not yet paid", "Follow up for payment."),
    "emd": ("EMD not refunded", "Follow up for the refund."),
    "bids_due": ("Tenders due this week", "Prepare and submit the bids."),
    "programme": ("Programme behind schedule", "Review the late activities."),
    "budget_overrun": ("Cost over budget for work done", "Review the cost against the budget."),
    "delay_unexplained": ("Delayed activities without a reason", "Record the reason on each delayed activity."),
    "plant": ("Plant service or documents overdue", "Book the service or renew the documents."),
    "cubes_due": ("Cube tests due", "Send the cubes for testing."),
    "cubes_below": ("Cube results below grade", "Review the concrete and record the action taken."),
    "ncr_overdue": ("NCRs past their due date", "Close them or record the action taken."),
    "permits_expired": ("Expired work permits still open", "Close or renew them."),
    "incidents_open": ("Serious incidents not closed", "Investigate and close them."),
    "eway": ("Material moved without an e-way bill", "Generate the e-way bills."),
    "rfq": ("Enquiries with fewer than three quotes", "Get more quotes before ordering."),
    "assets_unbooked": ("Assets without depreciation", "Book the depreciation."),
    "billed_ahead": ("Bills received before the goods", "Hold payment until the goods are received."),
    "late_deliveries": ("Late deliveries from suppliers", "Follow up with the suppliers."),
    "indents_unbought": ("Indents with no purchase action", "Raise an enquiry or a purchase order."),
    "drawings_for_approval": ("Drawings awaiting approval", "Approve or return them."),
    "doc_control_overdue": ("Overdue transmittals, RFIs and submittals", "Respond to them."),
    "journals_pending": ("Journals pending your approval", "Approve or reject them."),
}

# Where each kind of item is dealt with in the app (the dashboard's own map, api/dashboard.ts attentionHref).
PAGES = {
    "subcontracts-view": "/subcontractors/work-orders", "purchase-orders-view": "/store/purchase-orders",
    "indents-view": "/store/hub/outward/indent", "drawings-view": "/projects/drawings", "documents-view": "/projects/documents",
    "rate-contracts-view": "/store/rate-contracts", "subbills-view": "/subcontractors/ra-bills", "vendors-view": "/subcontractors/vendors",
    "compliance-view": "/subcontractors/compliance", "approvals-view": "/approvals", "items-view": "/store/items",
    "measurement-view": "/clients/measurement", "workorders-view": "/projects/boq", "leads-view": "/clients/pipeline",
    "estimates-view": "/clients/estimates", "customers-view": "/clients/customers", "money-view": "/money/owed",
    "ledger-view": "/money/ledgers", "payments-view": "/money/approvals", "sitecash-view": "/money/expenses?tab=cash",
    "bills-view": "/money/supplier-bills", "owe-view": "/money/owed?tab=owe", "adjustments-view": "/money/adjustments",
    "bank-payments-view": "/money/bank-payments", "claims-view": "/money/expenses?tab=claims",
    "store-accounts-view": "/store/hub/reports/accounts", "gst-view": "/money/gst", "fixedassets-view": "/money/assets",
    "registers-view": "/money/registers", "stock-view": "/store/hub/enquiry", "reorder-view": "/store/hub/reports/reorder",
    "stores-view": "/store/hub/inward/grn", "eway-view": "/store/eway", "diary-view": "/projects/diary",
    "schedule-view": "/projects/programme", "loans-view": "/money/loans", "budgeting-view": "/projects/budgeting",
    "chat-view": "/projects/chart", "attendance-view": "/people/attendance", "leave-view": "/people/leave",
    "payroll-view": "/people/payroll", "settings-view": "/settings",
}

SYNC = False                     # tests send inline instead of on a thread
TASK_OPEN = ("Open", "In Progress", "Blocked")


def base_url():
    return (os.getenv("APP_BASE_URL") or "").rstrip("/")


def link(path):
    """The full address of a page of the app, when the server knows its own address; else the path alone."""
    path = "/next" + (path if path.startswith("/") else "/" + path)
    return base_url() + path if base_url() else ""


def day_label(d):
    return "%d %s %d" % (d.day, d.strftime("%b"), d.year)


def first_sentence(text):
    """An item's detail up to its first full stop: the fact, without the commentary after it."""
    t = " ".join((text or "").split())
    cut = t.find(". ")
    return t[:cut + 1] if cut > 0 else t


def email_of(emp):
    """The organisation's address when they have one, else their personal email."""
    return ((emp.org_email or "").strip() or (emp.email or "").strip()) if emp else ""


# --- the Master's summary -----------------------------------------------------------------------------------------------

def money_rows(db, client):
    """[(label, amount text)]: receivables, payables, bank balance."""
    from app.core.currency import inr, money
    from app.routers.money import all_accounts_book, payables_payload, receivables_payload
    owed_in = receivables_payload(db, client)["summary"]
    owed_out = payables_payload(db, client)["summary"]
    opening, entries = all_accounts_book(db, client.id)
    cash = money(opening + sum((e.amount if e.direction == "IN" else -e.amount) for e in entries))
    return [("Receivables", "%s (%s overdue)" % (inr(owed_in["owed"]), inr(owed_in["overdue"]))),
            ("Payables", "%s (%s overdue)" % (inr(owed_out["owed"]), inr(owed_out["overdue"]))),
            ("Bank balance", inr(cash))]


def company_items(db, client, today):
    """The company-wide pending list, each as {title, detail, action, href}."""
    from app.services.accounts_watch import accounts_items
    from app.services.attention_buying import buying_items
    from app.services.projects import attention_items
    out = []
    for i in attention_items(db, client.id) + buying_items(db, client.id) + accounts_items(db, client, today):
        title, action = PLAIN.get(i.get("kind"), (i.get("title") or "", ""))
        out.append({"title": title, "detail": first_sentence(i.get("detail")), "action": action,
                    "href": link(PAGES.get(i.get("view") or "", "/"))})
    return out


# --- one employee's own work --------------------------------------------------------------------------------------------

def employee_items(db, client, emp, today):
    """What is pending with this one person, each as {title, detail, action, href}."""
    from app.core.permissions import employee_can
    from app.services.approvals import approval_doc
    from app.services.employee_portal import employee_can_access_job, filter_jobs_for_employee
    out = []

    # Approvals waiting on them now (their step is the document's current one).
    waiting = []
    for s in db.query(models.DBApprovalChain).filter(models.DBApprovalChain.client_id == client.id, models.DBApprovalChain.approver_id == emp.id,
                                                    models.DBApprovalChain.status == "pending").all():
        doc = approval_doc(db, s.entity_type, s.entity_id, client.id)
        if not doc or doc.approval_status != "pending" or s.step != (doc.current_approval_step or 0):
            continue
        if getattr(doc, "job_id", None) and not employee_can_access_job(db, emp, doc.job_id):
            continue
        kind = {"purchase_order": "PO", "bill": "Bill", "invoice": "Invoice", "work_order": "Work order"}.get(s.entity_type, s.entity_type.replace("_", " ").title())
        waiting.append("%s %s" % (kind, getattr(doc, "number", "") or doc.id))
    if waiting:
        out.append({"title": "Approvals pending with you", "detail": "%d: %s." % (len(waiting), ", ".join(waiting[:6]) + (" and more" if len(waiting) > 6 else "")),
                    "action": "Approve or send back each one.", "href": link("/approvals")})

    # Tasks given to them in project conversations.
    tasks = (db.query(models.DBChatTask).filter(models.DBChatTask.client_id == client.id, models.DBChatTask.assignee == "employee:%d" % emp.id,
                                               models.DBChatTask.status.in_(TASK_OPEN)).order_by(models.DBChatTask.due_date, models.DBChatTask.id).all())
    iso = today.isoformat()
    for t in tasks[:10]:
        due = (t.due_date or "")[:10]
        when = ("overdue since %s" % due) if due and due < iso else ("due today" if due == iso else ("due %s" % due if due else "no due date"))
        out.append({"title": "Task: %s" % (t.title or "untitled")[:90], "detail": "%s, %s." % (t.status, when),
                    "action": "Update its status when done.", "href": link("/projects/chart")})

    # Programme activities they own that are late, or due to finish in the next three days.
    acts = (db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.client_id == client.id, models.DBScheduleActivity.assigned_to_id == emp.id,
                                                      (models.DBScheduleActivity.actual_finish == "") | models.DBScheduleActivity.actual_finish.is_(None))
            .all())
    late, soon = [], []
    if acts:
        from app.services.projects import ScheduleContext
        for job_id in sorted({a.job_id for a in acts}):
            try:
                ctx = ScheduleContext(db, client.id, job_id)
                if not ctx.prog:
                    continue
                mine = {a.id for a in acts if a.job_id == job_id}
                for a in ctx.leaves:
                    if a.id not in mine or (a.status or "") == "Completed":
                        continue
                    _start, end = ctx.dates(a)
                    end = str(end)[:10] if end else ""
                    if not end:
                        continue
                    if end < iso:
                        late.append("%s (finish was %s)" % (a.name, end))
                    elif end <= (today + timedelta(days=3)).isoformat():
                        soon.append("%s (finish %s)" % (a.name, end))
            except Exception as exc:
                logger.error("Daily email: programme of job %s for employee %s failed: %s", job_id, emp.id, exc)
    if late:
        out.append({"title": "Your activities behind schedule", "detail": "%d: %s." % (len(late), "; ".join(late[:5])),
                    "action": "Update progress, or record the reason for the delay.", "href": link("/projects/programme")})
    if soon:
        out.append({"title": "Your activities due in the next 3 days", "detail": "; ".join(soon[:5]) + ".",
                    "action": "Make sure they finish on time.", "href": link("/projects/programme")})

    # Site diaries to sign off, on the projects they may see.
    if employee_can(emp, "site.signoff"):
        jobs = [j.id for j in filter_jobs_for_employee(db.query(models.DBJob).filter(models.DBJob.client_id == client.id), emp, db).all()]
        if jobs:
            n = db.query(models.DBSiteDiary).filter(models.DBSiteDiary.client_id == client.id, models.DBSiteDiary.job_id.in_(jobs),
                                                    models.DBSiteDiary.status == "DRAFT", models.DBSiteDiary.diary_date < iso).count()
            if n:
                out.append({"title": "Site diaries to sign off", "detail": "%d day%s still in draft." % (n, "" if n == 1 else "s"),
                            "action": "Sign off each day's diary.", "href": link("/projects/diary")})
    return out


# --- the email itself ---------------------------------------------------------------------------------------------------

def compose(company, greeting, today, items, money=None):
    """(subject, plain text, html) of one person's summary."""
    subject = "%s - Daily summary - %s" % (company or "Y ERP", day_label(today))
    text = ["%s," % greeting, ""]
    if money:
        text.append("MONEY POSITION")
        text += ["  %-14s %s" % (k, v) for k, v in money]
        text.append("")
    text.append("PENDING WITH YOU (%d)" % len(items))
    for n, i in enumerate(items, 1):
        text.append("  %d. %s" % (n, i["title"]))
        if i["detail"]:
            text.append("     %s" % i["detail"])
        if i["action"]:
            text.append("     %s" % i["action"])
        if i["href"]:
            text.append("     %s" % i["href"])
    text += ["", "This summary is sent every morning by Y ERP when something is pending with you."]

    e = html.escape
    rows = []
    for n, i in enumerate(items, 1):
        open_link = ('<a href="%s" style="color:#1d4ed8;text-decoration:none;font-weight:600;">Open</a>' % e(i["href"])) if i["href"] else ""
        rows.append(
            '<tr><td style="padding:12px 0;border-top:1px solid #e5e7eb;vertical-align:top;width:28px;color:#6b7280;">%d.</td>'
            '<td style="padding:12px 8px 12px 0;border-top:1px solid #e5e7eb;">'
            '<div style="font-weight:600;color:#111827;">%s</div>'
            '<div style="color:#374151;margin-top:2px;">%s</div>'
            '<div style="color:#6b7280;margin-top:2px;">%s</div></td>'
            '<td style="padding:12px 0;border-top:1px solid #e5e7eb;vertical-align:top;text-align:right;white-space:nowrap;">%s</td></tr>'
            % (n, e(i["title"]), e(i["detail"]), e(i["action"]), open_link))
    money_html = ""
    if money:
        money_html = ('<h3 style="margin:24px 0 8px;font-size:13px;letter-spacing:.04em;color:#6b7280;">MONEY POSITION</h3>'
                      '<table role="presentation" style="border-collapse:collapse;width:100%%;">%s</table>' % "".join(
                          '<tr><td style="padding:4px 0;color:#374151;">%s</td><td style="padding:4px 0;text-align:right;font-weight:600;color:#111827;">%s</td></tr>'
                          % (e(k), e(v)) for k, v in money))
    body = (
        '<div style="background:#f3f4f6;padding:24px 12px;font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.45;">'
        '<div style="max-width:620px;margin:0 auto;background:#ffffff;border-radius:8px;padding:24px;">'
        '<div style="font-size:12px;color:#6b7280;">%s</div>'
        '<h2 style="margin:4px 0 16px;font-size:20px;color:#111827;">Daily summary - %s</h2>'
        '<p style="margin:0;color:#111827;">%s,</p>%s'
        '<h3 style="margin:24px 0 8px;font-size:13px;letter-spacing:.04em;color:#6b7280;">PENDING WITH YOU (%d)</h3>'
        '<table role="presentation" style="border-collapse:collapse;width:100%%;">%s</table>'
        '<p style="margin:24px 0 0;font-size:12px;color:#9ca3af;">Sent every morning by Y ERP when something is pending with you.</p>'
        '</div></div>' % (e(company or "Y ERP"), e(day_label(today)), e(greeting), money_html, len(items), "".join(rows)))
    return subject, "\n".join(text), body


def send(client, to, subject, text, body):
    from app.core.notifications import send_email_background
    args = (to, subject, text, client.email or "")
    kw = {"html_body": body, "client_id": client.id}
    if SYNC:
        send_email_background(*args, **kw)
    else:
        threading.Thread(target=send_email_background, args=args, kwargs=kw, daemon=True).start()


def staff_emails(db, client, today):
    """Each active employee with something pending gets their own summary. Returns how many were sent."""
    sent = 0
    staff = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.status != "terminated").all()
    for emp in staff:
        to = email_of(emp)
        if not to:
            continue
        try:
            items = employee_items(db, client, emp, today)
        except Exception as exc:
            logger.error("Daily email for employee %s failed: %s", emp.id, exc)
            continue
        if not items:
            continue
        name = (emp.first_name or "").strip() or "there"
        subject, text, body = compose(client.company_name, "Good morning %s" % name, today, items)
        send(client, to, subject, text, body)
        sent += 1
    return sent
