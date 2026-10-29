"""Salary increments: each one is kept, so what somebody earned on any date can be told, and a payslip for an earlier
period is still made from the salary of the time."""
from datetime import datetime

from fastapi import HTTPException

from app import models
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.notifications import notify, notify_employee
from app.core.scheduler import scheduled_job


class SalaryAsOf:
    """An employee as they were paid on a date: the same person, with the salary of the time. The record itself is not
    touched, so an old period's payslip can be made without changing what the employee is paid today."""

    def __init__(self, emp, salary):
        self._emp, self.salary = emp, salary

    def __getattr__(self, name):
        return getattr(self._emp, name)


def revisions(db, client_id, emp_id):
    R = models.DBSalaryRevision
    return db.query(R).filter(R.client_id == client_id, R.employee_id == emp_id).order_by(R.effective_date, R.id).all()


def salary_on(db, emp, on):
    """The monthly salary in force on `on` (a date string). The first increment after that date says what it was before."""
    day = _parse_date(on)
    if day:
        for r in revisions(db, emp.client_id, emp.id):
            eff = _parse_date(r.effective_date)
            if eff and eff > day:
                return r.old_salary
    return emp.salary


def employee_on(db, emp, on):
    """`emp`, or the employee as paid on that date when an increment since then changes the salary."""
    salary = salary_on(db, emp, on)
    return emp if salary == emp.salary else SalaryAsOf(emp, salary)


def give_increment(db, client_id, emp, mode, value, effective_date, reason, by, valid_until=None):
    """Raise the salary by a percentage or to a new amount, and keep the change. Returns the revision."""
    old = float(emp.salary or 0)
    if old <= 0:
        raise HTTPException(status_code=400, detail="This employee has no monthly salary to raise. Set one first.")
    if mode not in ("percent", "amount"):
        raise HTTPException(status_code=400, detail="Give the increment as a percentage or as the new salary.")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Enter the increment as a number.")
    if value <= 0:
        raise HTTPException(status_code=400, detail="The increment must be more than zero." if mode == "percent" else "The new salary must be more than zero.")
    new = money(old * (1 + value / 100.0)) if mode == "percent" else money(value)
    eff = _parse_date(effective_date)
    if not eff:
        raise HTTPException(status_code=400, detail="Give the date the increment takes effect.")
    if eff > datetime.now().date():
        raise HTTPException(status_code=400, detail="The effective date cannot be in the future. Record it on the day it takes effect.")
    start = _parse_date(emp.start_date)
    if start and eff < start:
        raise HTTPException(status_code=400, detail="The effective date cannot be before the employee joined.")
    if new == old:
        raise HTTPException(status_code=400, detail="That is the salary already.")
    until = _parse_date(valid_until) if valid_until else _a_year_on(eff)
    if not until:
        raise HTTPException(status_code=400, detail="Give the date it runs until.")
    if until <= eff:
        raise HTTPException(status_code=400, detail="It must run until a day after it takes effect.")
    if revisions(db, client_id, emp.id) and any((_parse_date(r.effective_date) or eff) > eff for r in revisions(db, client_id, emp.id)):
        raise HTTPException(status_code=409, detail="A later increment is already recorded. Record this one after it.")
    rev = models.DBSalaryRevision(
        client_id=client_id, employee_id=emp.id, old_salary=old, new_salary=new, mode=mode,
        percent=value if mode == "percent" else money((new - old) / old * 100.0),
        effective_date=eff.strftime("%Y-%m-%d"), valid_until=until.strftime("%Y-%m-%d"), reason=(reason or "").strip()[:500], changed_by=by)
    emp.salary = new
    db.add(rev)
    return rev


def record_salary_change(db, client_id, emp, new, by):
    """A salary typed straight into the Edit form, kept in the history as from today, so it is never a silent change
    and it starts the review clock like any increment."""
    old, new = float(emp.salary or 0), money(new)
    if old <= 0 or new <= 0 or new == old:
        return None
    today = datetime.now().date()
    rev = models.DBSalaryRevision(
        client_id=client_id, employee_id=emp.id, old_salary=old, new_salary=new, mode="amount",
        percent=money((new - old) / old * 100.0), effective_date=today.strftime("%Y-%m-%d"),
        valid_until=_a_year_on(today).strftime("%Y-%m-%d"), reason="Changed in the Edit form", changed_by=by)
    db.add(rev)
    return rev


def revision_payload(r):
    return {"id": r.id, "old_salary": r.old_salary, "new_salary": r.new_salary, "percent": r.percent, "effective_date": r.effective_date,
            "valid_until": r.valid_until or _a_year_on(_parse_date(r.effective_date)).strftime("%Y-%m-%d"), "reason": r.reason or "", "changed_by": r.changed_by or "", "created_at": r.created_at}


def _a_year_on(day):
    try:
        return day.replace(year=day.year + 1)
    except ValueError:                       # 29 February
        return day.replace(year=day.year + 1, day=28)


@scheduled_job("increment_reminders")
def job_increment_reminders(db, now):
    """A year after somebody's last increment, tell HR it is time to look at theirs again.

    HR gets it in its own notices; the Master gets it on the bell. Nothing is emailed on its own. Each increment is reminded once, and
    only while it is still the employee's latest, so a newer one starts the year again."""
    today = now.date()
    latest = {}
    for r in db.query(models.DBSalaryRevision).order_by(models.DBSalaryRevision.effective_date, models.DBSalaryRevision.id).all():
        latest[(r.client_id, r.employee_id)] = r
    sent = 0
    for (client_id, emp_id), rev in latest.items():
        eff = _parse_date(rev.effective_date)
        due = _parse_date(rev.valid_until) if rev.valid_until else (_a_year_on(eff) if eff else None)
        if not eff or not due or due > today:
            continue
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client_id).first()
        if not emp or (emp.status or "active") in PAYROLL_EXCLUDED_STATUSES:
            continue
        if db.query(models.DBAlert.id).filter(models.DBAlert.client_id == client_id, models.DBAlert.kind == "increment_due",
                                              models.DBAlert.ref_type == "salary_revision", models.DBAlert.ref_id == rev.id).first():
            continue
        name = "%s %s" % (emp.first_name, emp.last_name)
        title = "Increment due: %s" % name
        body = ("%s was last given an increment on %s (%.2f to %.2f, %s%%). It ran until %s, so it is time to review their salary. "
                "Their salary now is %.2f a month." % (name, rev.effective_date, rev.old_salary, rev.new_salary, rev.percent, due, emp.salary or 0))
        hr = [e for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
              if (e.permission_role or "").lower() == "hr" and (e.status or "active") not in PAYROLL_EXCLUDED_STATUSES]
        for h in hr:
            notify_employee(db, client_id, h.id, title, body, link="/people/employees/%d" % emp.id)
        # On screen only: an email goes out only when somebody clicks send. The office bell is read by everyone in the
        # office, so it names the person and leaves the figures to HR's own notice.
        notify(db, client_id, "increment_due", title, "%s is due for a salary review: their last increment ran until %s." % (name, due),
               ref_type="salary_revision", ref_id=rev.id, severity="warning")
        sent += 1
    return "%d reminder(s)" % sent
