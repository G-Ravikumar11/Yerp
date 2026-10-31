"""The evening site report and the missing-diary reminder, and the morning delay alerts.

After seven in the evening a site that wrote its diary has the day's PDF emailed to the project manager, and to the client's contact
when the company has said so and the day is signed off; a site that wrote nothing has its people and manager reminded. Each morning
an activity newly late against its baseline is put in front of its assignee and the project manager, once a delay.
"""
from datetime import date, datetime, timedelta

import pytest

from conftest import make_employee
from app import models
from app.core import notifications
from app.core.scheduler import run_due_jobs
from app.db import SessionLocal
from app.services import site_reports

MONDAY = date.today() - timedelta(days=date.today().weekday() or 7)       # the last Monday before today: a working day, in the past
EVENING = datetime.combine(MONDAY, datetime.min.time()).replace(hour=19, minute=30)


@pytest.fixture
def sent(monkeypatch):
    mails = []
    monkeypatch.setattr(site_reports, "SYNC", True)
    monkeypatch.setattr(notifications, "send_email_background",
                        lambda to, subject, body, from_email, **kw: mails.append({"to": to, "subject": subject, "body": body, **kw}) or (True, ""))
    return mails


def site(tenant, name="Evening Towers", contact_email="engineer@client.example"):
    job = tenant.post("/api/jobs", json={"name": name, "customer_name": "Client Ltd", "status": "in_progress"}).json()
    pm = make_employee(tenant, first_name="Priya", email="pm-%s@example.com" % job["id"])
    crew = make_employee(tenant, first_name="Ravi", site_ids=[job["id"]])
    with SessionLocal() as db:
        j = db.get(models.DBJob, job["id"])
        c = models.DBContact(client_id=j.client_id, name="Client Ltd", email=contact_email)
        db.add(c)
        db.flush()
        j.contact_id, j.manager_id = c.id, pm["id"]
        db.commit()
    return job, pm, crew


def run_evening(job_id, now=EVENING):
    with SessionLocal() as db:
        client = db.get(models.DBClient, db.get(models.DBJob, job_id).client_id)
        return site_reports.evening_for(db, client, now)


def notices(emp_id):
    with SessionLocal() as db:
        return [n.title for n in db.query(models.DBNotification).filter(models.DBNotification.employee_id == emp_id).all()]


def diary(tenant, job, signed=False):
    d = tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": MONDAY.isoformat(), "work_done": "Brickwork level 3"}).json()["diary"]["id"]
    if signed:
        assert tenant.post("/api/diary/%d/submit" % d).status_code == 200
    return d


def test_a_draft_day_goes_to_the_manager_only(tenant, sent):
    job, pm, _ = site(tenant)
    tenant.put("/api/alerts/settings", json={"site_reports": {"email_client": True}})
    diary(tenant, job)
    assert run_evening(job["id"]) == {"reports": 1, "reminders": 0}
    assert [m["to"] for m in sent] == [pm["email"]]
    assert sent[0]["pdf_filename"].endswith(".pdf") and sent[0]["pdf_b64"]
    assert "not signed off" in sent[0]["body"] and "Daily progress report" in sent[0]["subject"]
    # Once a day: a second run sends nothing more.
    assert run_evening(job["id"]) == {"reports": 0, "reminders": 0} and len(sent) == 1


def test_a_signed_off_day_goes_to_the_client_too_when_the_company_says_so(tenant, sent):
    job, pm, _ = site(tenant)
    diary(tenant, job, signed=True)
    run_evening(job["id"])
    assert [m["to"] for m in sent] == [pm["email"]], "the client is not emailed until the company turns it on"

    job2, pm2, _ = site(tenant, "Second Towers", contact_email="rao@client.example")
    s = tenant.put("/api/alerts/settings", json={"site_reports": {"email_client": True}}).json()["site_reports"]
    assert s["email_client"] is True and s["email_manager"] is True
    diary(tenant, job2, signed=True)
    sent.clear()
    run_evening(job2["id"])
    assert sorted(m["to"] for m in sent) == sorted([pm2["email"], "rao@client.example"])


def test_no_diary_reminds_the_site_and_its_manager(tenant, sent):
    job, pm, crew = site(tenant)
    assert run_evening(job["id"]) == {"reports": 0, "reminders": 1}
    for emp in (pm, crew):
        assert any("No site diary today" in t for t in notices(emp["id"])), emp
    assert sent == []
    run_evening(job["id"])
    assert len([t for t in notices(crew["id"]) if "No site diary" in t]) == 1, "once a day"


def test_a_sites_day_off_and_a_closed_site_are_left_alone(tenant, sent):
    job, pm, crew = site(tenant)
    sunday = EVENING - timedelta(days=1)
    assert run_evening(job["id"], sunday) == {"reports": 0, "reminders": 0}      # the site's weekly off
    tenant.put("/api/jobs/%d" % job["id"], json={"name": job["name"], "status": "on_hold"})
    assert run_evening(job["id"]) == {"reports": 0, "reminders": 0}


def test_the_switches_turn_them_off(tenant, sent):
    job, pm, crew = site(tenant)
    tenant.put("/api/alerts/settings", json={"site_reports": {"remind_missing": False, "email_manager": False}})
    assert run_evening(job["id"]) == {"reports": 0, "reminders": 0}
    diary(tenant, job)
    assert run_evening(job["id"]) == {"reports": 0, "reminders": 0} and sent == []
    labels = tenant.get("/api/alerts/settings").json()["site_report_labels"]
    assert set(labels) == {"email_client", "email_manager", "remind_missing", "delay_alerts"}


def test_the_evening_job_waits_for_seven(tenant, sent):
    res = run_due_jobs(now=EVENING.replace(hour=18), only="evening_site_reports")
    assert res[0]["status"] == "done" and "too early" in res[0]["detail"]


# --- delay alerts ---------------------------------------------------------------------------------------------------------------

def late_activity(tenant, job, assignee):
    start = (date.today() - timedelta(days=20)).isoformat()
    finish = (date.today() - timedelta(days=10)).isoformat()
    res = tenant.post("/api/jobs/%d/schedule/activities" % job["id"], json={"name": "Plastering", "planned_start": start, "planned_finish": finish,
                                                                            "assigned_to_id": assignee["id"]})
    assert res.status_code == 200, res.text
    return res.json()["schedule"]["activities"][0]["id"]


def run_morning(job_id, now=None):
    with SessionLocal() as db:
        client = db.get(models.DBClient, db.get(models.DBJob, job_id).client_id)
        return site_reports.delay_alerts_for(db, client, now or datetime.now().replace(hour=9, minute=30))


def test_a_late_activity_is_told_to_its_assignee_and_the_manager_once(tenant):
    job, pm, crew = site(tenant)
    aid = late_activity(tenant, job, crew)
    assert run_morning(job["id"]) == 1
    for emp in (pm, crew):
        assert any(t == "Running late: A10 Plastering" or t.startswith("Running late") for t in notices(emp["id"])), emp
    assert run_morning(job["id"]) == 0, "the same delay is told once"
    # Finished: the delay is over; it is not told again.
    assert tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 100}).status_code == 200
    assert run_morning(job["id"]) == 0
    with SessionLocal() as db:
        assert db.query(models.DBDelayAlert).filter(models.DBDelayAlert.activity_id == aid).count() == 0
    # Opened again and still late: a new delay, told again.
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 60})
    assert run_morning(job["id"]) == 1


def test_delay_alerts_can_be_turned_off(tenant):
    job, pm, crew = site(tenant)
    late_activity(tenant, job, crew)
    tenant.put("/api/alerts/settings", json={"site_reports": {"delay_alerts": False}})
    assert run_morning(job["id"]) == 0
