"""Leave earned month by month, carried into the next year up to a limit, and the rest lapsing.

Off unless the company switches it on (Settings: leave_accrual). Off, a person has their whole year's entitlement from
1 January, as before. On:

    each month      annual entitlement / 12 is credited on the 1st, for anybody on the books in that month
    on 1 January    last year's unused annual leave carries forward up to leave_carry_max_annual (30 days unless
                    set), sick leave up to leave_carry_max_sick (none unless set); the rest lapses

Switching it on credits the months of this year already begun, so nobody starts the year with nothing. The balance every
screen and check uses (employee_portal.leave_balance_for) then reads the year's credits from here.
"""
import calendar
from datetime import date, datetime

from app import models
from app.core.config import logger
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.dates import _parse_date
from app.core.scheduler import scheduled_job

KINDS = ("annual", "sick")
ENABLED_KEY = "leave_accrual"
CARRY_KEYS = {"annual": "leave_carry_max_annual", "sick": "leave_carry_max_sick"}
DEFAULT_CARRY = {"annual": 30.0, "sick": 0.0}


def _setting(db, client_id, key):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == key).first()
    return row.value if row else None


def _put(db, client_id, key, value):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == key).first()
    if row:
        row.value = value
    else:
        db.add(models.DBSettings(client_id=client_id, key=key, value=value))


_SEEN = "leave_accrual_on"       # in the session's own notes: the switch as read in this request


def _is_on(value):
    return str(value or "").strip() in ("1", "true", "on")


def enabled(db, client_id):
    """Whether this company accrues leave. Read once per session (a request), not once per person: a list of
    payslips or leave balances would otherwise ask the database the same question for every row."""
    seen = db.info.setdefault(_SEEN, {})
    if client_id not in seen:
        seen[client_id] = _is_on(_setting(db, client_id, ENABLED_KEY))
    return seen[client_id]


def remember(db, client_id, value):
    """For a caller that has just read all the company's settings: tell us the switch, so it is not read a second time."""
    db.info.setdefault(_SEEN, {})[client_id] = _is_on(value)


def carry_limits(db, client_id):
    out = {}
    for kind in KINDS:
        try:
            out[kind] = float(_setting(db, client_id, CARRY_KEYS[kind]))
        except (TypeError, ValueError):
            out[kind] = DEFAULT_CARRY[kind]
    return out


def entitlement(emp, kind):
    value = emp.annual_leave_entitlement if kind == "annual" else emp.sick_leave_entitlement
    return float(value if value is not None else (25.0 if kind == "annual" else 10.0))


def _month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def on_books_in(emp, year, month):
    first, last = date(year, month, 1), _month_end(year, month)
    joined, left = _parse_date(emp.start_date or ""), _parse_date(emp.end_date or "")
    return (not joined or joined <= last) and (not left or left >= first)


def _add(db, emp, kind, entry, period, on, days, note="", by="system"):
    """Adds one entry unless that one is there already. Returns whether it was added."""
    L = models.DBLeaveLedger
    if db.query(L.id).filter(L.employee_id == emp.id, L.leave_type == kind, L.kind == entry, L.period == period).first():
        return False
    db.add(L(client_id=emp.client_id, employee_id=emp.id, leave_type=kind, kind=entry, period=period,
             entry_date=on.isoformat(), days=round(days, 4), note=note, created_by=by))
    db.flush()          # sessions here do not flush by themselves: without this the next check could not see this entry
    return True


def accrue_month(db, emp, year, month):
    """Credits a month's share of the year's annual and sick leave. Nothing for a month they were not on the books."""
    if not on_books_in(emp, year, month):
        return 0
    added = 0
    for kind in KINDS:
        added += _add(db, emp, kind, "accrual", "%04d-%02d" % (year, month), date(year, month, 1),
                      entitlement(emp, kind) / 12.0, "1/12 of %g days" % entitlement(emp, kind))
    return added


def credited(db, emp, kind, year):
    """Everything credited (and lapsed) for this kind of leave in a calendar year."""
    L = models.DBLeaveLedger
    rows = db.query(L.days).filter(L.employee_id == emp.id, L.leave_type == kind,
                                   L.entry_date >= "%04d-01-01" % year, L.entry_date <= "%04d-12-31" % year).all()
    return round(sum(r[0] or 0 for r in rows), 2)


def taken_in(db, emp, kind, year):
    R = models.DBLeaveRequest
    rows = db.query(R.days).filter(R.employee_id == emp.id, R.client_id == emp.client_id, R.leave_type == kind,
                                   R.status == "approved", R.start_date.like("%04d-%%" % year)).all()
    return round(sum(r[0] or 0 for r in rows), 2)


def close_year(db, emp, year, limits):
    """At the turn of the year: carry over what is left up to the limit, lapse the rest."""
    done = 0
    for kind in KINDS:
        left = credited(db, emp, kind, year) - taken_in(db, emp, kind, year)
        carry = min(max(left, 0.0), limits[kind])
        lapse = max(left, 0.0) - carry
        if lapse > 0:
            done += _add(db, emp, kind, "lapse", "%04d" % year, date(year, 12, 31), -lapse,
                         "Unused beyond the %g day(s) that carry over" % limits[kind])
        if carry > 0:
            done += _add(db, emp, kind, "carry_forward", "%04d" % (year + 1), date(year + 1, 1, 1), carry,
                         "Carried over from %d" % year)
    return done


def totals(db, emp, year):
    """{"annual": days, "sick": days} credited for the year, or None when the company does not accrue leave."""
    if not emp or not enabled(db, emp.client_id):
        return None
    return {kind: credited(db, emp, kind, year) for kind in KINDS}


def _people(db, client_id):
    return db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id,
                                              models.DBEmployee.status.notin_(PAYROLL_EXCLUDED_STATUSES)).all()


def backfill(db, client_id, today=None):
    """Credits every month of this year already begun, for everybody: what switching accrual on does."""
    today = today or datetime.now().date()
    added = 0
    for emp in _people(db, client_id):
        for month in range(1, today.month + 1):
            added += accrue_month(db, emp, today.year, month)
    return added


def set_accrual(db, client_id, on, carry_annual=None, carry_sick=None, today=None):
    _put(db, client_id, ENABLED_KEY, "1" if on else "0")
    remember(db, client_id, "1" if on else "0")
    for kind, value in (("annual", carry_annual), ("sick", carry_sick)):
        if value is not None:
            _put(db, client_id, CARRY_KEYS[kind], "%g" % float(value))
    db.flush()
    return backfill(db, client_id, today) if on else 0


def run_month(db, client_id, today):
    """The 1st of a month: in January close last year first, then credit the new month."""
    limits = carry_limits(db, client_id)
    added = 0
    for emp in _people(db, client_id):
        if today.month == 1:
            added += close_year(db, emp, today.year - 1, limits)
        added += accrue_month(db, emp, today.year, today.month)
    return added


def month_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m")


@scheduled_job("leave_accrual", month_key)
def job_leave_accrual(db, now):
    done, failed = [], []
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        if not enabled(db, client.id):
            continue
        try:
            added = run_month(db, client.id, now.date())
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Leave accrual failed for client %s", client.id)
            failed.append("%s: %s" % (client.id, exc))
            continue
        if added:
            done.append("%s:%d" % (client.id, added))
    summary = "leave credited for " + (", ".join(done) if done else "no company")
    if failed:
        raise RuntimeError("%s. Failed for %s" % (summary, "; ".join(failed)))
    return summary
