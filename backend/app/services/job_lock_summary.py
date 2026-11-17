"""The weekly Site Lock summary for HR: who was turned away from clocking in, how often, and where.

A refusal is written down the moment Job Lock turns somebody away (models.DBClockRefusal). One by one they are a list to
scroll; read as a week they say who keeps being refused (a person on the wrong site assignment, a phone whose GPS is
poor, somebody who works away from a fixed site and should be let off the lock) and whether it is getting better.
The week is seven days ending on the day asked for, set against the seven before it.

Every Monday morning HR is told, when there was anything to say. Nothing is changed by the summary: letting somebody
clock in anywhere is HR's call, made from the Job Lock tab (attendance.job_lock_exempt).
"""
from collections import Counter
from datetime import date, datetime, timedelta

from app import models
from app.core.config import logger
from app.core.scheduler import scheduled_job

REPEAT_FROM = 3          # refused this many times in the week: a pattern, not an accident


def week_key(now=None):
    """The ISO week, from seven in the morning: before that a key per hour, so an early tick cannot use up the week's
    summary before there is a morning to send it in (as digest_key does for the day)."""
    now = now or datetime.now()
    return now.strftime("%G-W%V") if now.hour >= 7 else now.strftime("early-%G-W%V-%d-%H")


def _stamp(day, end_of_day=False):
    return day.strftime("%Y-%m-%d") + (" 23:59:59" if end_of_day else " 00:00:00")


def window(week_ending):
    """(first day, last day) of the seven days ending on `week_ending`."""
    return week_ending - timedelta(days=6), week_ending


def _refusals(db, client_id, first, last):
    R = models.DBClockRefusal
    return db.query(R).filter(R.client_id == client_id, R.at >= _stamp(first), R.at <= _stamp(last, True)).order_by(R.at).all()


def summary(db, client_id, week_ending=None):
    """The week's refusals read as a summary: totals against the week before, by day, by person and by place."""
    week_ending = week_ending or date.today()
    first, last = window(week_ending)
    rows = _refusals(db, client_id, first, last)
    before = _refusals(db, client_id, first - timedelta(days=7), first - timedelta(days=1))
    people = {e.id: e for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id,
        models.DBEmployee.id.in_({r.employee_id for r in rows} | {0})).all()}

    def name(emp_id):
        e = people.get(emp_id)
        return ("%s %s" % (e.first_name or "", e.last_name or "")).strip() if e else ""

    per_day = Counter((r.at or "")[:10] for r in rows)
    by_day = [{"date": (first + timedelta(days=i)).isoformat(), "count": per_day.get((first + timedelta(days=i)).isoformat(), 0)}
              for i in range(7)]
    grouped = {}
    for r in rows:
        grouped.setdefault(r.employee_id, []).append(r)
    by_person = []
    for emp_id, mine in grouped.items():
        reasons = Counter(x.reason for x in mine if x.reason)
        e = people.get(emp_id)
        distances = [x.distance_m for x in mine if x.distance_m is not None]
        by_person.append({
            "employee_id": emp_id, "name": name(emp_id), "job_title": (e.job_title or "") if e else "",
            "refused": len(mine), "days": len({(x.at or "")[:10] for x in mine}), "last_at": mine[-1].at,
            "reason": reasons.most_common(1)[0][0] if reasons else "",
            "nearest": Counter(x.nearest for x in mine if x.nearest).most_common(1)[0][0] if any(x.nearest for x in mine) else "",
            "farthest_m": max(distances) if distances else None,
            "repeat": len(mine) >= REPEAT_FROM, "exempt": bool(e.job_lock_exempt) if e else False})
    by_person.sort(key=lambda p: (-p["refused"], p["name"].lower()))
    places = Counter(r.nearest for r in rows if r.nearest)
    flagged = db.query(models.DBAttendance.id).filter(
        models.DBAttendance.client_id == client_id, models.DBAttendance.location_flag != "",
        models.DBAttendance.location_flag.isnot(None), models.DBAttendance.date >= first.isoformat(),
        models.DBAttendance.date <= last.isoformat()).count()
    return {"from": first.isoformat(), "to": last.isoformat(), "refused": len(rows), "people": len(grouped),
            "previous_refused": len(before), "change": len(rows) - len(before), "flagged_punches": flagged,
            "repeat_people": sum(1 for p in by_person if p["repeat"]),
            "by_day": by_day, "by_person": by_person,
            "by_place": [{"place": p, "refused": n} for p, n in places.most_common(5)]}


def message(s):
    """The notice HR reads: the week in two or three lines."""
    lines = ["%d refused clock-in%s from %d %s, %s." % (
        s["refused"], "" if s["refused"] == 1 else "s", s["people"], "person" if s["people"] == 1 else "people",
        ("up %d on the week before" % s["change"]) if s["change"] > 0 else
        ("down %d on the week before" % -s["change"]) if s["change"] < 0 else "the same as the week before")]
    top = [p for p in s["by_person"] if p["repeat"]][:4]
    if top:
        lines.append("Refused again and again: " + ", ".join("%s (%d)" % (p["name"] or "?", p["refused"]) for p in top)
                     + ". If they work away from a fixed site, let them clock in anywhere from the Job Lock tab.")
    if s["flagged_punches"]:
        lines.append("%d punch%s let through but worth a look." % (s["flagged_punches"], "" if s["flagged_punches"] == 1 else "es"))
    return " ".join(lines)


def tell_hr(db, client_id, s):
    from app.core.notifications import notify, tell_approvers
    title = "Site Lock this week: %d refused clock-in%s" % (s["refused"], "" if s["refused"] == 1 else "s")
    body = message(s)
    notify(db, client_id, "job_lock_weekly", title, body, view="attendance", severity="action" if s["repeat_people"] else "info")
    tell_approvers(db, client_id, title, body, rights=("people.manage",), link="/next/people/attendance", owner=False)
    db.commit()


@scheduled_job("job_lock_weekly", week_key)
def job_lock_weekly(db, now):
    """Monday morning: the week just ended (Monday to Sunday), to whoever manages people. Companies with nothing to
    report are left alone."""
    if now.hour < 7:
        return "too early"
    ended = now.date() - timedelta(days=1)
    told = 0
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        try:
            s = summary(db, client.id, ended)
            if s["refused"] or s["flagged_punches"]:
                tell_hr(db, client.id, s)
                told += 1
        except Exception:
            db.rollback()
            logger.exception("Weekly Site Lock summary failed for company %s", client.id)
    return "%d compan%s told" % (told, "y" if told == 1 else "ies")
