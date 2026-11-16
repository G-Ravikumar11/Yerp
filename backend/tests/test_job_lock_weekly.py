"""The weekly Site Lock summary for HR, the Monday notice, and letting a refused person clock in anywhere."""
from datetime import date, datetime, timedelta

from app import db as database
from app import models
from app.core.scheduler import run_due_jobs
from conftest import make_employee
from test_job_lock import HOME, SITE, clock_in, project, staff_on


def refuse(tenant, portal, times=1):
    site = project(tenant, "Tellapur Towers", SITE)
    e = staff_on(tenant, portal, [site])
    for _ in range(times):
        assert clock_in(portal, HOME).status_code == 403
    return e


def weekly(tenant, **params):
    res = tenant.get("/api/attendance/job-lock/weekly", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def age_refusals(days):
    with database.SessionLocal() as db:
        for r in db.query(models.DBClockRefusal).all():
            r.at = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db.commit()


def test_the_week_is_read_by_day_and_by_person_against_the_week_before(tenant, portal):
    e = refuse(tenant, portal, times=3)
    w = weekly(tenant)
    assert w["refused"] == 3 and w["people"] == 1 and w["previous_refused"] == 0 and w["change"] == 3
    assert len(w["by_day"]) == 7 and w["by_day"][-1] == {"date": date.today().isoformat(), "count": 3}
    p = w["by_person"][0]
    assert p["employee_id"] == e["id"] and p["refused"] == 3 and p["repeat"] is True and p["exempt"] is False
    assert "km from" in p["reason"] and p["farthest_m"] > 100000
    assert w["repeat_people"] == 1

    age_refusals(8)                                          # now they belong to the week before
    w = weekly(tenant)
    assert w["refused"] == 0 and w["previous_refused"] == 3 and w["change"] == -3 and w["by_person"] == []


def test_a_past_week_can_be_asked_for_and_a_bad_day_is_refused(tenant, portal):
    refuse(tenant, portal, times=2)
    last_week = (date.today() - timedelta(days=7)).isoformat()
    assert weekly(tenant, week_ending=last_week)["refused"] == 0
    assert tenant.get("/api/attendance/job-lock/weekly", params={"week_ending": "31/12/2026"}).status_code == 400


def test_allowing_a_refused_person_lets_them_clock_in_and_the_summary_says_so(tenant, portal):
    e = refuse(tenant, portal)
    assert tenant.get("/api/attendance/job-lock").json()["refused"][0]["exempt"] is False
    assert tenant.put("/api/attendance/job-lock/exempt/%d" % e["id"], json={"exempt": True}).status_code == 200
    row = tenant.get("/api/attendance/job-lock").json()["refused"][0]
    assert row["employee_id"] == e["id"] and row["exempt"] is True
    assert weekly(tenant)["by_person"][0]["exempt"] is True
    assert clock_in(portal, HOME).status_code == 200


def test_monday_morning_hr_is_told_once_about_the_week_just_ended(tenant, portal):
    e = refuse(tenant, portal, times=3)
    age_refusals(1)                                          # yesterday, the last day of the week just ended
    morning = datetime.combine(date.today(), datetime.min.time()).replace(hour=8)
    first = run_due_jobs(morning, only="job_lock_weekly")
    assert first[0]["status"] == "done" and "told" in first[0]["detail"], first
    assert run_due_jobs(morning, only="job_lock_weekly")[0]["status"] == "already_done"
    with database.SessionLocal() as db:
        cid = db.get(models.DBEmployee, e["id"]).client_id
        n = db.query(models.DBAlert).filter(models.DBAlert.kind == "job_lock_weekly", models.DBAlert.client_id == cid).one()
    assert "3 refused clock-ins from 1 person" in n.body and "again and again" in n.body.lower()
    assert n.title == "Site Lock this week: 3 refused clock-ins" and n.severity == "action"


def test_a_quiet_week_sends_nothing_and_an_early_tick_does_not_use_up_the_week(tenant):
    make_employee(tenant)
    far = datetime.combine(date.today() + timedelta(days=70), datetime.min.time())       # a week nobody was refused in
    early = far.replace(hour=3)
    assert run_due_jobs(early, only="job_lock_weekly")[0]["detail"] == "too early"
    res = run_due_jobs(far.replace(hour=9), only="job_lock_weekly")
    assert res[0]["status"] == "done" and res[0]["detail"] == "0 companies told"
    with database.SessionLocal() as db:
        assert db.query(models.DBAlert).filter(models.DBAlert.kind == "job_lock_weekly", models.DBAlert.created_at >= far.strftime("%Y-%m-%d")).count() == 0


def test_another_company_sees_none_of_it(tenant, second_tenant, portal):
    refuse(tenant, portal)
    assert weekly(second_tenant)["refused"] == 0
