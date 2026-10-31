"""The nightly attendance check, run once a day for the day that has just ended.

1. A shift still open is closed at the company's auto clock-out time (auto_clockout_hours after the clock-in), not at
   midnight or whenever the job happens to run. A forgotten clock-out earns no overtime.
2. Anybody due at work that day - a working day, not a company holiday, on the books, not on approved leave - with no
   attendance at all is marked absent. Only people whose attendance is kept (they have clocked in at least once) are:
   site labour paid from a muster sheet would otherwise be absent every day.
3. Late arrivals are counted for the month. The day somebody reaches the company's threshold (and each multiple of it)
   they and HR are told the loss of pay that will follow; the days themselves are taken when the payslip is made
   (services.lop), so nothing here is counted twice.
4. Each reporting manager is told, in their own notices, who in their team was absent or late.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from app import models
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.dates import _parse_date
from app.core.scheduler import daily_key, scheduled_job
from app.services.employee_portal import (attendance_settings_for, end_shift, is_late, is_working_day, minutes_late,
                                          shift_limit_hours)
from app.services.holidays import custom_holidays
from app.services.lop import DEFAULT_LATE_PENALTY, DEFAULT_LATE_THRESHOLD

AUTO_CLOSED_NOTE = "Clocked out automatically after %g hours: no clock-out was recorded."
ABSENT_NOTE = "Marked absent by the nightly check: no clock-in and no approved leave."


def _name(emp):
    return ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()


def close_open_shifts(db, client_id, settings, before_day, now=None):
    """Closes every shift opened on or before `before_day` that was never clocked out and has run its longest length.
    A shift that has not - an evening shift still going at midnight - is left, and the portal still treats it as the
    person's current shift (employee_portal.running_shift); the next night's check closes it if it was forgotten.
    Returns the records closed."""
    now = now or datetime.now()
    hours = shift_limit_hours(settings)         # end_shift reads a shift as at most one night long
    A = models.DBAttendance
    closed = []
    for att in db.query(A).filter(A.client_id == client_id, A.date <= before_day, A.clock_in != "",
                                  A.clock_in.isnot(None), (A.clock_out == "") | A.clock_out.is_(None)).all():
        try:
            began = datetime.strptime("%s %s" % (att.date, att.clock_in[:8]), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        if began + timedelta(hours=hours) > now:
            continue                            # still within its length: they may well be working
        end_shift(db, att, client_id, now=began + timedelta(hours=hours))
        att.overtime_hours = 0.0                # nobody asked for these hours: they are not overtime
        att.notes = ((att.notes or "") + " " + AUTO_CLOSED_NOTE % hours).strip()
        closed.append(att)
    return closed


def _tracked_ids(db, client_id, day):
    """Employees with any attendance on or before `day`: the ones whose attendance is kept."""
    A = models.DBAttendance
    return {r[0] for r in db.query(A.employee_id).filter(A.client_id == client_id, A.date <= day.isoformat()).distinct()}


def _on_books(emp, day):
    joined, left = _parse_date(emp.start_date or ""), _parse_date(emp.end_date or "")
    return (not joined or joined <= day) and (not left or left >= day)


def mark_absences(db, client_id, settings, day, holidays):
    """Marks absent everybody due at work on `day` with no attendance and no approved leave. Returns the employees."""
    if not is_working_day(settings, day, holidays):
        return []
    iso = day.isoformat()
    tracked = _tracked_ids(db, client_id, day)
    if not tracked:
        return []
    A, L = models.DBAttendance, models.DBLeaveRequest
    seen = {r[0] for r in db.query(A.employee_id).filter(A.client_id == client_id, A.date == iso)}
    on_leave = {r[0] for r in db.query(L.employee_id).filter(
        L.client_id == client_id, L.status == "approved", L.start_date <= iso, L.end_date >= iso)}
    absent = []
    for emp in db.query(models.DBEmployee).filter(
            models.DBEmployee.client_id == client_id, models.DBEmployee.id.in_(tracked - seen - on_leave),
            models.DBEmployee.status.notin_(PAYROLL_EXCLUDED_STATUSES)).all():
        if not _on_books(emp, day):
            continue
        db.add(models.DBAttendance(client_id=client_id, employee_id=emp.id, date=iso, status="absent",
                                   check_type="system", notes=ABSENT_NOTE))
        absent.append(emp)
    return absent


def late_arrivals(db, client_id, settings, day):
    """[(employee, minutes late, lates this month so far)] for those who came in late on `day`."""
    A = models.DBAttendance
    iso = day.isoformat()
    todays = [a for a in db.query(A).filter(A.client_id == client_id, A.date == iso).all()
              if a.status != "absent" and is_late(a, settings)]
    if not todays:
        return []
    month_start = day.replace(day=1).isoformat()
    counts = defaultdict(int)
    for a in db.query(A).filter(A.client_id == client_id, A.date >= month_start, A.date <= iso,
                                A.employee_id.in_({a.employee_id for a in todays})).all():
        if a.status != "absent" and is_late(a, settings):
            counts[a.employee_id] += 1
    people = {e.id: e for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.id.in_({a.employee_id for a in todays})).all()}
    return [(people[a.employee_id], minutes_late(a, settings), counts[a.employee_id])
            for a in todays if a.employee_id in people]


def warn_late_penalties(db, client_id, settings, day, late):
    """The day somebody's lates reach the threshold (or a multiple of it), they and HR hear what it will cost."""
    from app.core.notifications import notify, notify_employee
    threshold = int(getattr(settings, "late_threshold", None) or DEFAULT_LATE_THRESHOLD)
    penalty = getattr(settings, "late_penalty_lop", None)
    penalty = DEFAULT_LATE_PENALTY if penalty is None else float(penalty)
    if threshold <= 0 or penalty <= 0:
        return []
    month = day.strftime("%B %Y")
    hit = [(emp, count) for emp, _mins, count in late if count % threshold == 0]
    for emp, count in hit:
        days = (count // threshold) * penalty
        notify_employee(db, client_id, emp.id, "Late %d times in %s" % (count, month),
                        "Every %d late arrivals cost %g day(s) of pay. So far this month that is %g day(s), taken on "
                        "your %s payslip." % (threshold, penalty, days, month), link="/me/attendance")
    if hit:
        notify(db, client_id, "attendance_late_penalty", "%d %s reached the late limit" % (
            len(hit), "person" if len(hit) == 1 else "people"),
            "; ".join("%s: %d lates, %g day(s) loss of pay" % (_name(e), c, (c // threshold) * penalty) for e, c in hit),
            view="attendance-view", severity="action")
    return hit


def tell_managers(db, client_id, day, absent, late):
    """Each reporting manager hears about their own team only."""
    from app.core.notifications import notify_employee
    teams = defaultdict(lambda: {"absent": [], "late": []})
    for emp in absent:
        if emp.reports_to:
            teams[emp.reports_to]["absent"].append(_name(emp))
    for emp, mins, _count in late:
        if emp.reports_to:
            teams[emp.reports_to]["late"].append("%s (%d min)" % (_name(emp), mins))
    when = day.strftime("%a %d %b")
    for manager_id, team in teams.items():
        parts = []
        if team["absent"]:
            parts.append("Absent: " + ", ".join(sorted(team["absent"])))
        if team["late"]:
            parts.append("Late: " + ", ".join(sorted(team["late"])))
        notify_employee(db, client_id, manager_id, "Your team on %s" % when, ". ".join(parts) + ".",
                        link="/attendance")
    return len(teams)


def nightly_for_client(db, client, day, now=None):
    settings = attendance_settings_for(db, client.id)
    holidays = custom_holidays(db, client.id, day, day)
    closed = close_open_shifts(db, client.id, settings, day.isoformat(), now)
    absent = mark_absences(db, client.id, settings, day, holidays)
    late = late_arrivals(db, client.id, settings, day) if settings else []
    db.commit()                                 # notify() commits and rolls back on its own: the day's work goes first
    warned = warn_late_penalties(db, client.id, settings, day, late) if settings else []
    managers = tell_managers(db, client.id, day, absent, late)
    db.commit()
    return {"closed": len(closed), "absent": len(absent), "late": len(late), "warned": len(warned), "managers": managers}


@scheduled_job("nightly_attendance", daily_key)
def job_nightly_attendance(db, now):
    """Runs on the first tick of a day, for the day before."""
    from app.core.config import logger
    day = (now - timedelta(days=1)).date()
    done, failed = [], []
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        try:
            r = nightly_for_client(db, client, day, now)
        except Exception as exc:
            # One company's trouble must not leave everybody else's day unchecked.
            db.rollback()
            logger.exception("Nightly attendance failed for client %s", client.id)
            failed.append("%s: %s" % (client.id, exc))
            continue
        if any(r.values()):
            done.append("%s:%s" % (client.id, ",".join("%s=%d" % kv for kv in r.items() if kv[1])))
    summary = "%s: %s" % (day.isoformat(), "; ".join(done) if done else "nothing to do")
    if failed:
        # Recorded as a failed run, with what did get done, so an operator sees it.
        raise RuntimeError("%s. Failed for %s" % (summary, "; ".join(failed)))
    return summary
