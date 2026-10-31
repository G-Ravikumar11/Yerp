"""Where a month's payroll stands: Draft, Approved, Paid, then Locked.

    Draft -> Approved -> Paid -> Locked          (reopen: Locked -> Paid, the Master only, with a reason)

A month with no row is a Draft. A payslip belongs to the month its period ends in. Nothing in a Locked month can be
made, changed or deleted until the Master reopens it.
"""
import re
from datetime import datetime

from fastapi import HTTPException

from app import models

DRAFT, APPROVED, PAID, LOCKED = "Draft", "Approved", "Paid", "Locked"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MIN_REASON = 5


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def month_of(period_end="", period_start="", pay_date=""):
    """The YYYY-MM a payslip belongs to: the month its period ends in."""
    for value in (period_end, period_start, pay_date):
        if value and MONTH_RE.match(str(value)[:7]):
            return str(value)[:7]
    return ""


def clean_month(value):
    month = str(value or "").strip()
    if not MONTH_RE.match(month):
        raise HTTPException(status_code=400, detail="Give the month as YYYY-MM, like 2026-10.")
    return month


def get_month(db, client_id, month):
    return db.query(models.DBPayrollMonth).filter(
        models.DBPayrollMonth.client_id == client_id, models.DBPayrollMonth.month == month).first()


def status_of(db, client_id, month):
    row = get_month(db, client_id, month) if month else None
    return row.status if row else DRAFT


def assert_open(db, client_id, *months):
    """Refuses (409) a change to any of these months if it is Locked."""
    for month in sorted({m for m in months if m}):
        if status_of(db, client_id, month) == LOCKED:
            raise HTTPException(
                status_code=409,
                detail="Payroll for %s is locked. The Master can reopen it, with a reason, to change anything in it." % month)


def locked_months_of(db, client_id, employee_id):
    """The locked months in which this employee has a payslip."""
    locked = {r.month for r in db.query(models.DBPayrollMonth).filter(
        models.DBPayrollMonth.client_id == client_id, models.DBPayrollMonth.status == LOCKED).all()}
    if not locked:
        return []
    ends = db.query(models.DBPayslip.period_end).filter(
        models.DBPayslip.client_id == client_id, models.DBPayslip.employee_id == employee_id).all()
    return sorted({e[0][:7] for e in ends if e[0]} & locked)


def payslips_of(db, client_id, month):
    """The month's payslips that count (not void)."""
    P = models.DBPayslip
    return [p for p in db.query(P).filter(P.client_id == client_id, P.status != "Void",
                                          P.period_end.like(month + "%")).all()]


def _row(db, client_id, month):
    row = get_month(db, client_id, month)
    if not row:
        row = models.DBPayrollMonth(client_id=client_id, month=month, status=DRAFT)
        db.add(row)
        db.flush()
    return row


def _move(row, expected, target, verb):
    if row.status != expected:
        raise HTTPException(
            status_code=409,
            detail="Payroll for %s is %s: only a %s month can be %s." % (row.month, row.status, expected, verb))
    row.status = target


def approve(db, client_id, month, by):
    row = _row(db, client_id, month)
    slips = payslips_of(db, client_id, month)
    if row.status == DRAFT and not slips:
        raise HTTPException(status_code=400, detail="There are no payslips for %s to approve." % month)
    _move(row, DRAFT, APPROVED, "approved")
    row.approved_at, row.approved_by = now(), by
    return row, slips


def pay(db, client_id, month, by):
    """Marks the month paid and every payslip in it with it."""
    row = _row(db, client_id, month)
    _move(row, APPROVED, PAID, "paid")
    row.paid_at = now()
    slips = payslips_of(db, client_id, month)
    today = datetime.now().strftime("%Y-%m-%d")
    for p in slips:
        p.status = "Paid"
        p.pay_date = p.pay_date or today
    return row, slips


def lock(db, client_id, month, by):
    row = _row(db, client_id, month)
    _move(row, PAID, LOCKED, "locked")
    row.locked_at, row.locked_by = now(), by
    return row


def reopen(db, client_id, month, by, reason):
    """Unlocks a locked month, back to Paid. The reason is kept on the month and in the audit log."""
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise HTTPException(status_code=400, detail="Say why the month is being reopened (at least %d characters)." % MIN_REASON)
    row = _row(db, client_id, month)
    _move(row, LOCKED, PAID, "reopened")
    row.reopened_at, row.reopened_by, row.reopen_reason = now(), by, reason
    return row


def as_dict(row, slips=None):
    out = {"month": row.month, "status": row.status, "approved_at": row.approved_at or "", "approved_by": row.approved_by or "",
           "paid_at": row.paid_at or "", "locked_at": row.locked_at or "", "locked_by": row.locked_by or "",
           "reopened_at": row.reopened_at or "", "reopened_by": row.reopened_by or "", "reopen_reason": row.reopen_reason or ""}
    if slips is not None:
        out["payslips"] = len(slips)
        out["net_pay"] = round(sum(p.net_pay or 0 for p in slips), 2)
    return out


RELEASED_MONTHS = (APPROVED, PAID, LOCKED)
SEEN_STATUSES = ("Sent", "Paid")


def visible_to_staff(db, client_id, payslips):
    """The payslips an employee may see: ones sent to them or paid, and any whose month has been approved. A draft in a
    month still being worked on is HR's, and a void one is nobody's."""
    states = {r.month: r.status for r in db.query(models.DBPayrollMonth).filter(
        models.DBPayrollMonth.client_id == client_id).all()} if payslips else {}
    out = []
    for p in payslips:
        if p.status == "Void":
            continue
        if p.status in SEEN_STATUSES or states.get(month_of(p.period_end, p.period_start, p.pay_date)) in RELEASED_MONTHS:
            out.append(p)
    return out
