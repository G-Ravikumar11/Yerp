"""Safe man-hours: how many hours have been worked on site since the last lost-time injury, and the rates a site reports.

Hours worked come from what is already recorded, day by day:
    contractors' labour   each site diary's labour lines, headcount x hours
    staff                 attendance hours tagged to the site (clock-in inside its fence)
A day with no diary counts nothing, so the figure is only as full as the diaries are.

Rates are per 1,000,000 man-hours, as Indian sites report them (IS 3786):
    LTIFR            lost-time injuries x 1,000,000 / man-hours
    severity rate    days lost x 1,000,000 / man-hours
    recordable rate  recordable injuries (lost time, medical treatment, restricted work, illness, fatality) x 1,000,000 / man-hours

A lost-time injury is one recorded as such or as a fatality, or any injury that cost a day or more off work.
"""
from datetime import date

from app import models
from app.core.currency import money

LTI_KINDS = ("Lost time injury", "Fatality")
RECORDABLE_KINDS = ("Lost time injury", "Fatality", "Medical treatment", "Restricted work case", "Occupational illness")
PER = 1_000_000


def is_lti(i) -> bool:
    return (i.kind or "") in LTI_KINDS or (i.lost_days or 0) >= 1


def hours_by_day(db, client_id, job_id=0):
    """{day: [contractors' hours, staff hours]} for one site, or every site."""
    days = {}
    q = db.query(models.DBSiteDiary.diary_date, models.DBDiaryLabour.headcount, models.DBDiaryLabour.hours).join(
        models.DBDiaryLabour, models.DBDiaryLabour.site_diary_id == models.DBSiteDiary.id).filter(models.DBSiteDiary.client_id == client_id)
    if job_id:
        q = q.filter(models.DBSiteDiary.job_id == job_id)
    for on, heads, hours in q.all():
        days.setdefault((on or "")[:10], [0.0, 0.0])[0] += (heads or 0) * (hours if hours is not None else 8.0)
    q = db.query(models.DBAttendance.date, models.DBAttendance.total_hours).filter(
        models.DBAttendance.client_id == client_id, models.DBAttendance.job_id.isnot(None))
    if job_id:
        q = q.filter(models.DBAttendance.job_id == job_id)
    for on, hours in q.all():
        days.setdefault((on or "")[:10], [0.0, 0.0])[1] += hours or 0
    days.pop("", None)
    return days


def safe_hours(db, client_id, job_id=0, today=None):
    today = today or date.today().isoformat()
    q = db.query(models.DBSafetyIncident).filter(models.DBSafetyIncident.client_id == client_id)
    if job_id:
        q = q.filter(models.DBSafetyIncident.job_id == job_id)
    incidents = [i for i in q.all() if i.happened_on]
    ltis = sorted((i for i in incidents if is_lti(i)), key=lambda i: i.happened_on)
    recordable = [i for i in incidents if (i.kind or "") in RECORDABLE_KINDS or is_lti(i)]
    days = hours_by_day(db, client_id, job_id)
    total = sum(a + b for a, b in days.values())
    last = ltis[-1].happened_on[:10] if ltis else None
    since = sum(a + b for on, (a, b) in days.items() if last is None or on > last)
    lost = sum(i.lost_days or 0 for i in incidents)

    def rate(n):
        return round(n * PER / total, 2) if total else None

    months = {}
    for on, (a, b) in days.items():
        m = months.setdefault(on[:7], {"month": on[:7], "contractor_hours": 0.0, "staff_hours": 0.0, "ltis": 0, "incidents": 0})
        m["contractor_hours"] += a
        m["staff_hours"] += b
    for i in incidents:
        m = months.setdefault(i.happened_on[:7], {"month": i.happened_on[:7], "contractor_hours": 0.0, "staff_hours": 0.0, "ltis": 0, "incidents": 0})
        m["incidents"] += 1
        m["ltis"] += 1 if is_lti(i) else 0
    # The longest stretch of hours worked between two lost-time injuries, the current one included.
    best, run, marks = 0.0, 0.0, sorted({i.happened_on[:10] for i in ltis})
    for on in sorted(days):
        while marks and on > marks[0]:
            best, run = max(best, run), 0.0
            marks.pop(0)
        run += sum(days[on])
    best = max(best, run)
    return {
        "safe_hours": round(since), "since": last, "total_hours": round(total), "best_run_hours": round(best),
        "contractor_hours": round(sum(a for a, _ in days.values())), "staff_hours": round(sum(b for _, b in days.values())),
        "days_recorded": len([d for d in days.values() if sum(d)]), "ltis": len(ltis), "recordable": len(recordable),
        "days_lost": money(lost), "ltifr": rate(len(ltis)), "severity_rate": rate(lost), "recordable_rate": rate(len(recordable)),
        "this_month_hours": round(sum(sum(v) for k, v in days.items() if k[:7] == today[:7])),
        "by_month": [{**m, "contractor_hours": round(m["contractor_hours"]), "staff_hours": round(m["staff_hours"]),
                      "hours": round(m["contractor_hours"] + m["staff_hours"])} for m in sorted(months.values(), key=lambda m: m["month"], reverse=True)],
    }
