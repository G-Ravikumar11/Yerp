"""Recurring payments: rent, internet, hire and insurance that fall due every month, raised for approval without being typed in.

Each template carries its own next due date. A daily job raises an expense payment request for every template due on or
before today - catching up if the app was down, as the recurring invoices do - and moves the template on to the next
month. The request is a request, not a payment: it goes through the company's approval and is paid like any other, so
nothing is paid that nobody signed for. A log of the months raised (`recurring_payment_runs`) makes it impossible for one
month to be raised twice, whatever happens to the job.
"""
import calendar
import re
from datetime import date, datetime

from fastapi import HTTPException

from app import models
from app.constants.money import EXPENSE_HEADS
from app.core import checks
from app.core.auth import owned_or_404
from app.core.config import logger
from app.core.currency import inr, money
from app.core.scheduler import scheduled_job
from app.models.recurring_payments import DBRecurringPayment, DBRecurringPaymentRun
from app.schemas.money import MoneyIn
from app.services import payment_requests as preq

RAISE_LIMIT = 12          # months raised for one template in one run: more means something is wrong, not that it is behind
LARGEST = 100_000_000_000
WHO = "Recurring payment"


def _name(raw):
    return re.sub(r"\s+", " ", raw or "").strip()


def _day(text):
    try:
        return datetime.strptime((text or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def occurrence(year, month, day):
    """The day of a month this falls due: its own day, or the month's last when it is shorter (the 31st in February)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def first_due(day, on_or_after):
    """The first day this falls due that is on or after a date."""
    here = occurrence(on_or_after.year, on_or_after.month, day)
    return here if here >= on_or_after else following(on_or_after, day)


def following(due, day):
    """The month after the one a due date is in. Built from the day asked for, not the day it fell on: the 31st stays the 31st
    after a February that had to use the 28th."""
    year, month = (due.year + 1, 1) if due.month == 12 else (due.year, due.month + 1)
    return occurrence(year, month, day)


def status_of(t):
    if t.is_active:
        return "Active"
    return "Paused" if t.next_due else "Ended"


def _finish(t):
    t.is_active = False
    t.next_due = ""


def recurring_dict(t, jobs=None, accounts=None, last=None):
    job = (jobs or {}).get(t.job_id)
    account = (accounts or {}).get(t.account_id)
    return {"id": t.id, "payee": t.payee, "head": t.head, "job_id": t.job_id,
            "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "amount": money(t.amount), "day_of_month": t.day_of_month, "start_date": t.start_date or "", "end_date": t.end_date or "",
            "next_due": t.next_due or "", "status": status_of(t), "is_active": bool(t.is_active),
            "account_id": t.account_id, "account": account.name if account else "", "mode": t.mode or "", "note": t.note or "",
            "raised_count": t.raised_count or 0, "last_raised_on": t.last_raised_on or "", "last_error": t.last_error or "",
            "last_request": last or None, "created_by_name": t.created_by_name or "", "created_at": t.created_at or ""}


def list_recurring(db, client_id):
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client_id).all()}
    # The latest request each one raised, and where it stands.
    latest = {}
    for run in db.query(DBRecurringPaymentRun).filter(DBRecurringPaymentRun.client_id == client_id).order_by(DBRecurringPaymentRun.id).all():
        latest[run.recurring_id] = run
    reqs = {}
    wanted = [r.request_id for r in latest.values() if r.request_id]
    if wanted:
        reqs = {r.id: r for r in db.query(models.DBPaymentRequest).filter(models.DBPaymentRequest.id.in_(wanted)).all()}
    rows = db.query(DBRecurringPayment).filter(DBRecurringPayment.client_id == client_id).order_by(
        DBRecurringPayment.is_active.desc(), DBRecurringPayment.next_due, DBRecurringPayment.id).all()
    out = []
    for t in rows:
        run = latest.get(t.id)
        req = reqs.get(run.request_id) if run else None
        last = {"number": req.number, "status": preq.STATUS_LABEL.get(req.status, req.status), "due_on": run.due_on} if req else None
        out.append(recurring_dict(t, jobs, accounts, last))
    return out


def recurring_or_404(db, client_id, rid):
    t = db.query(DBRecurringPayment).filter(DBRecurringPayment.id == rid, DBRecurringPayment.client_id == client_id).first()
    if not t:
        raise HTTPException(404, "Recurring payment not found")
    return t


def apply_recurring(db, client_id, t, body, who, creating):
    """Check what the form sent and put it on the template. On a change, what was left out stays as it was. Returns True when
    the schedule itself (the day, or the first day) changed, so the next due date has to be worked out again."""
    def given(field):
        return getattr(body, field, None) is not None

    rescheduled = creating
    if creating or given("payee"):
        payee = _name(body.payee)
        if not payee:
            raise HTTPException(400, "Paid to whom?")
        if len(payee) > 120:
            raise HTTPException(400, "The name is too long.")
        t.payee = payee
    if creating or given("head"):
        head = next((h for h in EXPENSE_HEADS if h.lower() == _name(body.head).lower()), "")
        if not head:
            raise HTTPException(400, "Book it under one of: %s." % ", ".join(EXPENSE_HEADS))
        t.head = head
    if creating or given("amount"):
        amount = checks.between(body.amount, "amount", 0, LARGEST, unit="rupees", blank_ok=False)
        if money(amount) <= 0:
            raise HTTPException(400, "The amount has to be more than nothing.")
        t.amount = money(amount)
    if creating or given("day_of_month"):
        try:
            day = int(body.day_of_month)
        except (TypeError, ValueError):
            raise HTTPException(400, "Which day of the month is it due?") from None
        if not 1 <= day <= 31:
            raise HTTPException(400, "The day of the month is from 1 to 31. In a month with fewer days it falls on the last.")
        rescheduled = rescheduled or day != t.day_of_month
        t.day_of_month = day
    if creating or given("start_date"):
        start = checks.day(body.start_date, "first payment date", default_today=True)
        rescheduled = rescheduled or start != t.start_date
        t.start_date = start
    if given("end_date"):
        t.end_date = checks.day(body.end_date, "last payment date")
    if t.end_date and t.start_date and t.end_date < t.start_date:
        raise HTTPException(400, "The last payment date is before the first.")
    if given("job_id"):
        t.job_id = owned_or_404(db, models.DBJob, client_id, body.job_id, "Project") or None
    elif creating:
        t.job_id = None
    if given("account_id"):
        t.account_id = owned_or_404(db, models.DBBankAccount, client_id, body.account_id, "Account") or None
    if given("mode"):
        t.mode = _name(body.mode)[:30]
    if given("note"):
        t.note = _name(body.note)[:200]
    # The same rent twice would be paid twice: one live template for a payee, head and project.
    if t.next_due != "" or creating:
        from app.services.crm import norm_name
        for other in db.query(DBRecurringPayment).filter(DBRecurringPayment.client_id == client_id, DBRecurringPayment.head == t.head,
                                                         DBRecurringPayment.job_id.is_(None) if t.job_id is None else DBRecurringPayment.job_id == t.job_id).all():
            if other.id != t.id and other.next_due and norm_name(other.payee) == norm_name(t.payee):
                raise HTTPException(409, "%s is already set up for %s%s. Change that one, so it is not paid twice."
                                    % (other.payee, other.head.lower(), " on this project" if t.job_id else ""))
    if creating:
        t.created_by_name = who
        t.is_active = True
    else:
        t.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return rescheduled


def schedule(t, today=None):
    """Work out the next due date from the first day and the day of the month: never in the past, and never after the end."""
    today = today or date.today()
    start = _day(t.start_date) or today
    due = first_due(t.day_of_month, max(start, today))
    end = _day(t.end_date)
    if end and due > end:
        raise HTTPException(400, "It ends on %s, before its first payment on %s." % (end.strftime("%d %b %Y"), due.strftime("%d %b %Y")))
    t.next_due = due.isoformat()


def raise_due(db, t, today):
    """Raise a payment request for every month this has fallen due up to today, and move it on. Returns the requests raised."""
    client = db.get(models.DBClient, t.client_id)
    made, guard = [], 0
    while t.is_active and t.next_due and guard < RAISE_LIMIT:
        due = _day(t.next_due)
        if due is None or due > today:
            break
        end = _day(t.end_date)
        if end and due > end:
            _finish(t)
            break
        if not db.query(DBRecurringPaymentRun.id).filter(DBRecurringPaymentRun.recurring_id == t.id, DBRecurringPaymentRun.due_on == t.next_due).first():
            body = MoneyIn(doc_type="expense", head=t.head, party_name=t.payee, amount=t.amount, job_id=t.job_id, account_id=t.account_id,
                           mode=t.mode or "", note=("Recurring: %s, due %s" % (t.note or t.head, due.strftime("%d %b %Y")))[:300])
            r = preq.raise_request(db, client, None, WHO, body)
            db.add(DBRecurringPaymentRun(client_id=t.client_id, recurring_id=t.id, due_on=t.next_due, request_id=r.id))
            t.raised_count = (t.raised_count or 0) + 1
            t.last_raised_on = today.isoformat()
            made.append(r)
        t.last_error = ""
        nxt = following(due, t.day_of_month)
        t.next_due = nxt.isoformat()
        if end and nxt > end:
            _finish(t)
        guard += 1
    return made


@scheduled_job("recurring_payments")
def job_recurring_payments(db, now):
    """Raise whatever has fallen due: a payment request for each recurring payment due today or earlier, for approval.

    One that cannot be raised (its head no longer exists, say) is marked with why and left for tomorrow; it does not stop the rest."""
    from app.core.notifications import notify
    today = now.date()
    due = db.query(DBRecurringPayment).filter(DBRecurringPayment.is_active.is_(True), DBRecurringPayment.next_due != "",
                                              DBRecurringPayment.next_due <= today.isoformat()).order_by(
        DBRecurringPayment.client_id, DBRecurringPayment.next_due, DBRecurringPayment.id).all()
    raised, failed = {}, 0
    for t in due:
        tid, client_id = t.id, t.client_id
        try:
            made = raise_due(db, t, today)
            db.commit()
        except Exception as exc:
            db.rollback()
            failed += 1
            logger.warning("Recurring payment %s could not be raised: %s", tid, exc)
            t = db.get(DBRecurringPayment, tid)
            if t is not None:
                t.last_error = str(getattr(exc, "detail", None) or exc)[:200]
                db.commit()
            continue
        for r in made:
            raised.setdefault(client_id, []).append(r)
    for client_id, requests in raised.items():
        lines = ["- %s: %s %s (%s)" % (r.head, r.party_name, inr(r.amount), r.number) for r in requests[:8]]
        notify(db, client_id, "approval", "%d recurring payment%s waiting for approval" % (len(requests), "" if len(requests) == 1 else "s"),
               "\n".join(lines), view="payments-view", severity="action")
    total = sum(len(v) for v in raised.values())
    return "%d request(s) raised%s" % (total, ", %d could not be raised" % failed if failed else "")
