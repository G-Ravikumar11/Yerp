"""Cube tests due today and tomorrow, one rule for every screen and message, and the daily notice to each project.

`cube_tests_due` is the only reading of what is due. It takes the sets' own `due` list, from which cube_dict has already
left out a rejected set, so the dashboard, the API and the notice cannot disagree. Each project's today is its own.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app import models
from app.core.config import logger
from app.core.notifications import default_from_email, notify, notify_employee, send_email_background
from app.core.scheduler import scheduled_job
from app.services.quality import cube_dicts, zone_of

DEFAULT_HOUR = 8
MAX_ATTEMPTS = 5


def _setting(db, client_id, key):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == key).first()
    return (row.value or "") if row else ""


def send_hour(db, client_id):
    try:
        v = int(_setting(db, client_id, "cube_notice_hour") or DEFAULT_HOUR)
    except ValueError:
        return DEFAULT_HOUR
    return v if 0 <= v <= 23 else DEFAULT_HOUR


def project_emails(db, client_id, job_id):
    return [x.strip() for x in _setting(db, client_id, "cube_notice_emails:%d" % job_id).replace(";", ",").split(",") if x.strip()]


def cube_tests_due(db, client_id, job_id=0, now=None):
    """{job_id: {"job", "today_on", "today": [...], "tomorrow": [...]}} for every project with a test due."""
    now = now or datetime.now(ZoneInfo("UTC"))
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    q = db.query(models.DBCubeSet).filter(models.DBCubeSet.client_id == client_id)
    if job_id:
        q = q.filter(models.DBCubeSet.job_id == job_id)
    sets = q.all()
    by_id = {s.id: s for s in sets}
    out = {}
    for d in cube_dicts(db, client_id, sets):
        job = jobs.get(d["job_id"])
        if job is None:
            continue
        day = now.astimezone(zone_of(job.timezone)).date()
        s = by_id[d["id"]]
        for due in d["due"]:
            when = "today" if due["due_on"] == day.isoformat() else "tomorrow" if due["due_on"] == (day + timedelta(days=1)).isoformat() else None
            if not when:
                continue
            row = out.setdefault(job.id, {"job_id": job.id, "project": ("%s %s" % (job.number or "", job.name or "")).strip(), "name": job.name or "", "today_on": day.isoformat(), "today": [], "tomorrow": []})
            row[when].append({"set_id": s.id, "reference": "%s / %d day" % (s.number, due["age_days"]), "number": s.number, "age_days": due["age_days"], "job_id": job.id, "project": row["project"],
                              "grade": s.grade or "", "cast_on": s.cast_on or "", "due_on": due["due_on"], "status": "Due today" if when == "today" else "Due tomorrow"})
    return out


def notice_text(row):
    def block(title, tests):
        lines = ["%s:" % title]
        lines += ["- %s, %s, cast %s, due %s" % (t["reference"], t["grade"], t["cast_on"], t["due_on"]) for t in tests] or ["- None"]
        return "\n".join(lines)
    return ("Dear Project Team,\n\nThe following cube tests are scheduled:\n\n%s\n\n%s\n\n"
            "Please ensure that the required cube testing activities are completed on schedule.\n\nRegards,\nConstruction ERP System\n" % (block("Due Today", row["today"]), block("Due Tomorrow", row["tomorrow"])))


def _create(db, client_id, row):
    """One notice for a project and a day. The unique key settles two workers racing."""
    N = models.DBCubeDueNotice
    n = N(client_id=client_id, job_id=row["job_id"], run_date=row["today_on"], project=row["project"], subject="Cube Tests Due – %s" % row["name"],
          body=notice_text(row), tests=json.dumps({"today": row["today"], "tomorrow": row["tomorrow"]}), test_count=len(row["today"]) + len(row["tomorrow"]))
    db.add(n)
    try:
        db.commit()
        return n
    except IntegrityError:
        db.rollback()
        return None


def deliver(db, n, email=False):
    """Send what has not gone yet. The status change is the claim: two runs cannot both hold it. A retry goes only to those
    who did not get it, and the bell is rung once.

    The hourly run rings the bell and tells the site's staff; it emails nobody. The project's addresses are emailed only
    when somebody presses Send (`email`)."""
    N = models.DBCubeDueNotice
    claimable = ("Pending", "Failed", "Sent") if email else ("Pending", "Failed")      # a sent notice can still be emailed
    if not db.query(N).filter(N.id == n.id, N.status.in_(claimable)).update({"status": "Sending", "attempts": N.attempts + 1}, synchronize_session=False):
        db.rollback()
        return False
    db.commit()
    db.refresh(n)
    cfg_to = project_emails(db, n.client_id, n.job_id) if email else []
    done = [x for x in (n.sent_to or "").split(", ") if x]
    errors = []
    if not n.bell_sent:
        if notify(db, n.client_id, "cube_tests_due_bell", n.subject, n.body, view="quality-view", ref_type="cube_notice", ref_id=n.id, severity="action") is not None:
            for (emp,) in db.query(models.DBEmployeeSite.employee_id).filter(models.DBEmployeeSite.job_id == n.job_id).all():
                notify_employee(db, n.client_id, emp, n.subject, n.body[:500], link="/next/projects/quality")
            n.bell_sent = True
            db.commit()
        else:
            errors.append("The in-app notice could not be saved.")
    client = db.get(models.DBClient, n.client_id)
    for to in cfg_to:
        if to in done:
            continue
        try:
            ok, why = send_email_background(to, n.subject, n.body, "%s <%s>" % ((client.company_name if client else "") or "Construction ERP", default_from_email()), None, None, "", "", client_id=n.client_id)
        except Exception as exc:
            ok, why = False, type(exc).__name__
        if ok:
            done.append(to)
        else:
            errors.append("%s: not sent" % to)
            logger.error("Cube notice %s to %s failed: %s", n.id, to, str(why)[:200])
    n.sent_to = ", ".join(done)
    n.error = "; ".join(errors)[:500]
    n.status = "Failed" if errors else "Sent"
    if not errors:
        n.sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return not errors


def unsent_to(db, n):
    """The project's addresses this notice has not been emailed to."""
    done = {x for x in (n.sent_to or "").split(", ") if x}
    return [to for to in project_emails(db, n.client_id, n.job_id) if to not in done]


def run_for_client(db, client_id, now=None):
    now = now or datetime.now(ZoneInfo("UTC"))
    hour = send_hour(db, client_id)
    sent = 0
    N = models.DBCubeDueNotice
    # Those that failed an earlier run first: one that fails below waits for the next hour, not the next line.
    for n in db.query(N).filter(N.client_id == client_id, N.status == "Failed", N.attempts < MAX_ATTEMPTS).all():
        deliver(db, n)
    for row in cube_tests_due(db, client_id, now=now).values():
        job = db.get(models.DBJob, row["job_id"])
        if now.astimezone(zone_of(job.timezone)).hour < hour:
            continue
        n = _create(db, client_id, row)
        if n is not None:
            deliver(db, n)
            sent += 1
    return sent


def hourly_key(now_=None):
    return (now_ or datetime.now()).strftime("%Y-%m-%d-%H")


@scheduled_job("cube_tests_due", hourly_key)
def cube_due_job(db, now_):
    """Looks every hour, because each project's morning comes at its own time; the notice is still one a day for a project."""
    total = 0
    for (cid,) in db.query(models.DBCubeSet.client_id).distinct().all():
        try:
            total += run_for_client(db, cid)
        except Exception:
            logger.exception("Cube notices failed for company %s", cid)
            db.rollback()
    return "%d notices" % total


def notice_dict(n):
    return {"id": n.id, "job_id": n.job_id, "project": n.project or "", "run_date": n.run_date, "subject": n.subject or "", "test_count": n.test_count or 0, "tests": json.loads(n.tests or "{}"),
            "status": n.status, "attempts": n.attempts or 0, "sent_to": n.sent_to or "", "sent_at": n.sent_at or "", "error": n.error or "", "created_at": n.created_at or ""}
