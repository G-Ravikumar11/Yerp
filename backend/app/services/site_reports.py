"""The evening and the morning: the site reports and reminders that go out without anyone pressing a button.

Each evening after seven, for every live site that works that day:
  - a diary written: the day's progress report (the PDF on the letterhead) goes to the project manager, and to the client's contact
    when the company has said so and the day has been signed off - a draft is never sent outside the company;
  - no diary: the people placed on the site and the project manager are reminded, in their notices and on their phones.
Each morning after nine, an activity that has newly gone late against its baseline is put in front of the person it is assigned to
and the project manager, once for each new delay.
"""
import base64
import json
import threading
from datetime import datetime

from app import models
from app.core.config import logger
from app.core.scheduler import scheduled_job

LIVE = ("won", "in_progress")
SITE_REPORT_DEFAULTS = {"email_client": False, "email_manager": True, "remind_missing": True, "delay_alerts": True}
SITE_REPORT_LABELS = {
    "email_client": "Email the evening report to the client's contact (signed-off days only)",
    "email_manager": "Email the evening report to the project manager",
    "remind_missing": "Remind the site and its manager when no diary was written that day",
    "delay_alerts": "Tell an activity's assignee and the project manager when it goes late",
}
SYNC = False                 # tests set this to send inline instead of on a thread


def site_report_settings(db, client_id):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == "site_reports").first()
    try:
        saved = json.loads(row.value) if row and row.value else {}
    except ValueError:
        saved = {}
    return {k: bool(saved.get(k, v)) for k, v in SITE_REPORT_DEFAULTS.items()}


def save_site_report_settings(db, client_id, given):
    now = site_report_settings(db, client_id)
    now.update({k: bool(v) for k, v in (given or {}).items() if k in SITE_REPORT_DEFAULTS})
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == "site_reports").first()
    if row:
        row.value = json.dumps(now)
    else:
        db.add(models.DBSettings(client_id=client_id, key="site_reports", value=json.dumps(now)))
    return now


def evening_key(now=None):
    """The day, once it is past seven in the evening; before that a key per hour, so an early tick cannot use up the day."""
    now = now or datetime.now()
    return now.strftime("%Y-%m-%d") if now.hour >= 19 else now.strftime("early-%Y-%m-%d-%H")


def morning_key(now=None):
    now = now or datetime.now()
    return now.strftime("%Y-%m-%d") if now.hour >= 9 else now.strftime("early-%Y-%m-%d-%H")


def _email_of(emp):
    return ((emp.org_email or "").strip() or (emp.email or "").strip()) if emp else ""


def manager_of(db, job):
    if not job.manager_id:
        return None
    return db.query(models.DBEmployee).filter(models.DBEmployee.id == job.manager_id, models.DBEmployee.status != "terminated").first()


def site_staff(db, client_id, job):
    """The people placed on the site (HR's Sites), still employed."""
    ids = [r[0] for r in db.query(models.DBEmployeeSite.employee_id).filter(models.DBEmployeeSite.client_id == client_id,
                                                                               models.DBEmployeeSite.job_id == job.id).all()]
    if not ids:
        return []
    return db.query(models.DBEmployee).filter(models.DBEmployee.id.in_(ids), models.DBEmployee.status != "terminated").all()


def client_contact_email(db, job):
    if not job.contact_id:
        return ""
    c = db.query(models.DBContact).filter(models.DBContact.id == job.contact_id).first()
    return ((c.email or "").strip() if c else "")


def works_on(db, client_id, job, day):
    """Is the day a working day on this site: its own weekly off and holidays, from Planning & Progress."""
    from types import SimpleNamespace
    from app.services.programme import programme_calendar
    cal, _ = programme_calendar(db, client_id, SimpleNamespace(id=job.id))
    return cal.working(day)


def _mail(client, to, subject, body, pdf=None, filename="report.pdf"):
    from app.core.notifications import send_email_background
    args = (to, subject, body, client.email or "")
    kw = {"client_id": client.id}
    if pdf:
        kw.update(pdf_b64=base64.b64encode(pdf).decode(), pdf_filename=filename)
    if SYNC:
        send_email_background(*args, **kw)
    else:
        threading.Thread(target=send_email_background, args=args, kwargs=kw, daemon=True).start()


def _ran(db, client_id, job_id, on, kind):
    return db.query(models.DBSiteReportRun.id).filter(models.DBSiteReportRun.client_id == client_id, models.DBSiteReportRun.job_id == job_id,
                                                      models.DBSiteReportRun.run_on == on, models.DBSiteReportRun.kind == kind).first() is not None


def evening_for(db, client, now):
    """The evening run for one company. Returns {"reports": n, "reminders": n}."""
    from app.core.notifications import notify_employee
    from app.documents.dpr_pdf import dpr_pdf
    from app.services.hr import employee_name
    cfg = site_report_settings(db, client.id)
    day = now.date()
    on = day.isoformat()
    done = {"reports": 0, "reminders": 0}
    jobs = db.query(models.DBJob).filter(models.DBJob.client_id == client.id, models.DBJob.status.in_(LIVE)).all()
    for job in jobs:
        try:
            if not works_on(db, client.id, job, day):
                continue
            site = ("%s %s" % (job.number or "", job.name or "")).strip()
            diary = db.query(models.DBSiteDiary).filter(models.DBSiteDiary.client_id == client.id, models.DBSiteDiary.job_id == job.id,
                                                        models.DBSiteDiary.diary_date == on).first()
            pm = manager_of(db, job)
            if diary:
                if _ran(db, client.id, job.id, on, "report"):
                    continue
                signed = (diary.status or "") == "SUBMITTED"
                to = []
                if cfg["email_manager"] and _email_of(pm):
                    to.append(_email_of(pm))
                contact = client_contact_email(db, job)
                if cfg["email_client"] and signed and contact:
                    to.append(contact)
                if not to:
                    continue
                pdf, name = dpr_pdf(db, client, diary)
                subject = "Daily progress report - %s - %s" % (site, day.strftime("%d %b %Y"))
                body = ("The daily progress report for %s on %s is attached.\n\n%s" % (site, day.strftime("%d %b %Y"), (diary.work_done or "")[:600])
                        + ("" if signed else "\n\nThis day is not signed off yet, so it has not been sent to the client."))
                for addr in to:
                    _mail(client, addr, subject, body, pdf, name)
                db.add(models.DBSiteReportRun(client_id=client.id, job_id=job.id, run_on=on, kind="report", sent_to=", ".join(to),
                                              note="signed off" if signed else "draft: not sent to the client"))
                done["reports"] += 1
            elif cfg["remind_missing"]:
                if _ran(db, client.id, job.id, on, "reminder"):
                    continue
                people = {e.id: e for e in site_staff(db, client.id, job)}
                if pm:
                    people[pm.id] = pm
                if not people:
                    continue
                title = "No site diary today: %s" % site
                text = ("Nothing has been recorded for %s on %s. Write the day's diary - labour, weather, work done, what held it up - "
                        "while it is fresh; a day with no record is a day that cannot be claimed." % (site, day.strftime("%d %b")))
                for e in people.values():
                    notify_employee(db, client.id, e.id, title, text, link="/projects/diary")
                db.add(models.DBSiteReportRun(client_id=client.id, job_id=job.id, run_on=on, kind="reminder",
                                              sent_to=", ".join(employee_name(e) for e in people.values())))
                done["reminders"] += 1
            db.commit()
        except Exception:
            logger.exception("Evening site report for job %s failed", job.id)
            db.rollback()
    return done


@scheduled_job("evening_site_reports", evening_key)
def job_evening_site_reports(db, now):
    if now.hour < 19:
        return "too early"
    reports = reminders = 0
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        got = evening_for(db, client, now)
        reports += got["reports"]
        reminders += got["reminders"]
    return "%d report(s), %d reminder(s)" % (reports, reminders)


def delay_alerts_for(db, client, now):
    """Tell each newly late activity's assignee and the project manager, once a delay. Returns how many delays were told."""
    from app.core.notifications import notify_employee
    from app.services.hr import employee_name
    from app.services.projects import schedule_view
    if not site_report_settings(db, client.id)["delay_alerts"]:
        return 0
    told = 0
    on = now.date().isoformat()
    jobs = db.query(models.DBJob).filter(models.DBJob.client_id == client.id, models.DBJob.status.in_(LIVE)).all()
    for job in jobs:
        try:
            if not db.query(models.DBScheduleActivity.id).filter(models.DBScheduleActivity.job_id == job.id).first():
                continue
            rows = schedule_view(db, client.id, job)["activities"]
            known = {a.activity_id: a for a in db.query(models.DBDelayAlert).filter(models.DBDelayAlert.client_id == client.id,
                                                                                     models.DBDelayAlert.job_id == job.id).all()}
            late = {r["id"]: r for r in rows if r["delay_days"] > 0 and r["actual_percent"] < 100}
            # Back on time (or finished): the record goes, so a later slip is a new delay.
            for aid, rec in known.items():
                if aid not in late or rec.promised != late[aid]["baseline_finish"]:
                    db.delete(rec)
            db.flush()
            known = {aid: rec for aid, rec in known.items() if aid in late and rec.promised == late[aid]["baseline_finish"]}
            pm = manager_of(db, job)
            site = ("%s %s" % (job.number or "", job.name or "")).strip()
            for aid, r in late.items():
                if aid in known:
                    continue
                people = {}
                if r["assigned_to_id"]:
                    e = db.query(models.DBEmployee).filter(models.DBEmployee.id == r["assigned_to_id"], models.DBEmployee.status != "terminated").first()
                    if e:
                        people[e.id] = e
                if pm:
                    people[pm.id] = pm
                name = ("%s %s" % (r["code"], r["name"])).strip()
                title = "Running late: %s" % name
                text = ("%s on %s is %d day%s behind its baseline finish of %s (forecast %s).%s" % (
                    name, site, r["delay_days"], "" if r["delay_days"] == 1 else "s", r["baseline_finish"], r["forecast_finish"] or "-",
                    " Record a hindrance or give a reason for it." if r["needs_reason"] else ""))
                for e in people.values():
                    notify_employee(db, client.id, e.id, title, text, link="/projects/programme/%d/activity/%d" % (job.id, aid))
                db.add(models.DBDelayAlert(client_id=client.id, job_id=job.id, activity_id=aid, promised=r["baseline_finish"],
                                           delay_days=r["delay_days"], told=", ".join(employee_name(e) for e in people.values()), alerted_on=on))
                told += 1
            db.commit()
        except Exception:
            logger.exception("Delay alerts for job %s failed", job.id)
            db.rollback()
    return told


@scheduled_job("delay_alerts", morning_key)
def job_delay_alerts(db, now):
    if now.hour < 9:
        return "too early"
    told = sum(delay_alerts_for(db, c, now) for c in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all())
    return "%d delay(s) told" % told
