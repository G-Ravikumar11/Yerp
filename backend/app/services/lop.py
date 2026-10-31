"""Paid days in a pay period: joining and leaving part-way through, loss of pay, and the pay that follows from them.

A month's pay is made for the whole month's working days. A person who joined on the 12th, left on the 20th, or was
away without pay is paid for fewer of them:

    component amount = monthly amount / working days in the month * paid days
    paid days        = working days in the person's active slice of the month - loss-of-pay days

The active slice runs from the later of the period's start and the start date to the earlier of the period's end and the
end date. Loss of pay is unpaid leave, leave past the year's entitlement, working days with neither attendance nor
approved leave, and the penalty for coming in late too often.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from app import models
from app.core.dates import _parse_date
from app.core.currency import money
from app.services.employee_portal import attendance_settings_for, is_late, is_working_day, working_days_between
from app.services.holidays import custom_holidays

DEFAULT_LATE_THRESHOLD = 3
DEFAULT_LATE_PENALTY = 0.5
UNPAID_LEAVE = "unpaid"


def active_slice(emp, period_start, period_end):
    """(start, end) of the days in the period the person was on the books, or None when there are none."""
    start, end = _parse_date(period_start), _parse_date(period_end)
    if not start or not end or end < start:
        return None
    joined, left = _parse_date(getattr(emp, "start_date", "") or ""), _parse_date(getattr(emp, "end_date", "") or "")
    if joined and joined > start:
        start = joined
    if left and left < end:
        end = left
    return (start, end) if start <= end else None


def _each_day(start, end):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _entitlement(emp, kind):
    value = emp.annual_leave_entitlement if kind == "annual" else emp.sick_leave_entitlement
    return float(value if value is not None else (25.0 if kind == "annual" else 10.0))


def _leave_days(leave, settings, holidays):
    """The working days a leave request covers, as dates."""
    start, end = _parse_date(leave.start_date), _parse_date(leave.end_date)
    if not start or not end or end < start:
        return []
    return [d for d in _each_day(start, end) if is_working_day(settings, d, holidays)]


def pay_days(db, client_id, emp, period_start, period_end, today=None, settings=None, holidays=None):
    """How many days a person is paid for in a pay period, and why not all of them.

    Returns working_days (the period's, for everyone), active_days (their share of them while on the books),
    lop_days and its parts, paid_days, and `factor`, paid_days / working_days, the fraction of a monthly amount earned.
    `holidays` is the business's holidays covering the period's whole year, when the caller already has them."""
    settings = settings if settings is not None else attendance_settings_for(db, client_id)
    start, end = _parse_date(period_start), _parse_date(period_end)
    year_start, year_end = date(start.year, 1, 1), date(end.year, 12, 31)
    holidays = holidays if holidays is not None else custom_holidays(db, client_id, year_start, year_end)
    working = working_days_between(start, end, settings, holidays=holidays)
    out = {"working_days": working, "active_days": 0.0, "unpaid_leave": 0.0, "excess_leave": 0.0, "absent": 0.0,
           "late_count": 0, "late_penalty": 0.0, "lop_days": 0.0, "paid_days": 0.0, "factor": 0.0, "tracked": False}
    sliced = active_slice(emp, period_start, period_end)
    if not sliced or working <= 0:
        return out
    s, e = sliced
    days = [d for d in _each_day(s, e) if is_working_day(settings, d, holidays)]
    out["active_days"] = float(len(days))
    today = today or datetime.now().date()

    # Leave: unpaid leave is loss of pay outright; annual and sick leave are paid up to the year's entitlement and
    # loss of pay beyond it, counting the year's approved days in date order.
    leaves = db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.client_id == client_id, models.DBLeaveRequest.employee_id == emp.id,
        models.DBLeaveRequest.status == "approved",
        models.DBLeaveRequest.start_date <= end.isoformat(), models.DBLeaveRequest.end_date >= year_start.isoformat(),
    ).all()
    on_leave, lop_dates = set(), set()
    by_kind = defaultdict(set)
    for leave in leaves:
        kind = (leave.leave_type or "").lower()
        covered = _leave_days(leave, settings, holidays)
        if kind == UNPAID_LEAVE:
            lop_dates.update(covered)
        by_kind[kind].update(covered)
        on_leave.update(covered)
    # What the person has for the year: the whole entitlement, or what has accrued when the company accrues leave.
    from app.services.leave_accrual import totals as accrued
    ledger = accrued(db, emp, start.year)
    for kind in ("annual", "sick"):
        allowed = ledger[kind] if ledger is not None else _entitlement(emp, kind)
        for index, day in enumerate(sorted(d for d in by_kind.get(kind, ()) if d.year == start.year)):
            if index >= allowed:
                lop_dates.add(day)
    # A day booked under two kinds of leave is counted once.
    in_slice = set(days)
    unpaid_days = {d for d in lop_dates if d in in_slice}
    out["unpaid_leave"] = float(len({d for d in unpaid_days if d in by_kind.get(UNPAID_LEAVE, ())}))
    out["excess_leave"] = float(len(unpaid_days)) - out["unpaid_leave"]

    # Attendance. A person who has never clocked in is not tracked by attendance at all (site labour paid on a muster
    # sheet, say), so the days they have no record are not held against them.
    A = models.DBAttendance
    records = db.query(A.date, A.status, A.clock_in).filter(
        A.client_id == client_id, A.employee_id == emp.id, A.date >= s.isoformat(), A.date <= e.isoformat()).all()
    present = {r.date for r in records if (r.status or "") != "absent"}
    # From the clock-in time, not the status: a late day reads "completed" once the person has clocked out.
    out["late_count"] = sum(1 for r in records if (r.status or "") != "absent"
                            and (r.status == "late" or is_late(r, settings)))
    out["tracked"] = bool(records) or db.query(A.id).filter(
        A.client_id == client_id, A.employee_id == emp.id, A.date <= e.isoformat()).first() is not None
    if out["tracked"]:
        out["absent"] = float(sum(1 for d in days if d <= today and d not in on_leave and d.isoformat() not in present))

    threshold = int(getattr(settings, "late_threshold", None) or DEFAULT_LATE_THRESHOLD)
    penalty = getattr(settings, "late_penalty_lop", None)
    penalty = DEFAULT_LATE_PENALTY if penalty is None else float(penalty)
    if threshold > 0:
        out["late_penalty"] = (out["late_count"] // threshold) * penalty

    lop = out["unpaid_leave"] + out["excess_leave"] + out["absent"] + out["late_penalty"]
    out["lop_days"] = round(min(lop, out["active_days"]), 2)
    out["paid_days"] = round(max(out["active_days"] - out["lop_days"], 0.0), 2)
    out["factor"] = out["paid_days"] / working        # exact: rounding it cost paise on every prorated amount
    return out


def prorated(amount, factor):
    """A monthly amount earned over `factor` of the month's working days."""
    return money(float(amount or 0) * factor) if factor < 1 else money(amount)
