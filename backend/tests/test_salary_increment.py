"""A salary increment: HR and the Master give it, it is kept, and a payslip for an earlier period uses the salary of the time."""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from conftest import make_employee

PASSWORD = "Crew1234"


@pytest.fixture(autouse=True)
def _no_structure(tenant):
    for c in tenant.get("/api/salary-structure").json()["components"]:
        tenant.delete("/api/salary-structure/%d" % c["id"])


@pytest.fixture
def member(tenant):
    main.rate_limiter._hits.clear()
    email = "mate-%s@example.com" % uuid.uuid4().hex[:8]
    assert tenant.post("/api/team/invite", json={"email": email, "role": "admin", "name": "Colleague", "password": "Colleague123"}).status_code == 200
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/client/login", json={"email": email, "password": "Colleague123"}).status_code == 200
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def hr(tenant):
    email = "hr-%s@example.com" % uuid.uuid4().hex[:6]
    make_employee(tenant, email=email, password=PASSWORD, permission_role="hr", status="active")
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/employee/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    yield c
    c.__exit__(None, None, None)


def day(delta):
    return (datetime.now() + timedelta(days=delta)).strftime("%Y-%m-%d")


def test_a_percentage_raise_is_applied_and_kept(tenant):
    emp = make_employee(tenant, salary=50000.0, start_date="2020-01-01")
    res = tenant.post("/api/employees/%d/increment" % emp["id"], json={"mode": "percent", "value": 10, "effective_date": day(0), "reason": "Appraisal"})
    assert res.status_code == 200, res.text
    assert res.json()["salary"] == 55000.0
    hist = tenant.get("/api/employees/%d/salary-history" % emp["id"]).json()
    assert hist["salary"] == 55000.0
    assert [(r["old_salary"], r["new_salary"], r["percent"], r["reason"]) for r in hist["revisions"]] == [(50000.0, 55000.0, 10.0, "Appraisal")]
    assert tenant.get("/api/employees/%d?view=profile" % emp["id"]).json()["salary"] == 55000.0


def test_a_new_amount_works_out_the_percentage(tenant):
    emp = make_employee(tenant, salary=40000.0, start_date="2020-01-01")
    r = tenant.post("/api/employees/%d/increment" % emp["id"], json={"mode": "amount", "value": 46000, "effective_date": day(0)}).json()
    assert r["salary"] == 46000.0 and r["revision"]["percent"] == 15.0


def test_bad_increments_are_refused(tenant):
    emp = make_employee(tenant, salary=40000.0, start_date="2020-01-01")
    url = "/api/employees/%d/increment" % emp["id"]
    assert tenant.post(url, json={"mode": "percent", "value": 0, "effective_date": day(0)}).status_code == 400
    assert tenant.post(url, json={"mode": "percent", "value": 5, "effective_date": day(3)}).status_code == 400      # the future
    assert tenant.post(url, json={"mode": "percent", "value": 5, "effective_date": "2019-01-01"}).status_code == 400  # before they joined
    assert tenant.post(url, json={"mode": "amount", "value": 40000, "effective_date": day(0)}).status_code == 400     # no change
    assert tenant.post(url, json={"mode": "percent", "value": 5, "effective_date": day(-1)}).status_code == 200
    assert tenant.post(url, json={"mode": "percent", "value": 5, "effective_date": day(-5)}).status_code == 409       # older than the last
    no_pay = make_employee(tenant, salary=0.0)
    assert tenant.post("/api/employees/%d/increment" % no_pay["id"], json={"mode": "percent", "value": 5, "effective_date": day(0)}).status_code == 400


def test_a_payslip_for_an_earlier_period_uses_the_salary_of_the_time(tenant):
    emp = make_employee(tenant, salary=50000.0, start_date="2020-01-01")
    assert tenant.post("/api/employees/%d/increment" % emp["id"], json={"mode": "percent", "value": 20, "effective_date": "2026-08-01"}).status_code == 200
    old = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-07-01", "period_end": "2026-07-31", "pay_date": "2026-07-31"}).json()
    new = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}).json()
    assert old["gross_pay"] == 50000.0 and new["gross_pay"] == 60000.0
    assert tenant.get("/api/employees/%d?view=profile" % emp["id"]).json()["salary"] == 60000.0     # the record itself is not changed by it


def test_only_hr_and_the_master_may(tenant, member, hr):
    emp = make_employee(tenant, salary=40000.0, start_date="2020-01-01")
    url = "/api/employees/%d/increment" % emp["id"]
    assert member.post(url, json={"mode": "percent", "value": 5, "effective_date": day(0)}).status_code == 403
    assert member.get("/api/employees/%d/salary-history" % emp["id"]).status_code == 403
    assert hr.post(url, json={"mode": "percent", "value": 5, "effective_date": day(0)}).status_code == 200
    assert tenant.get("/api/employees/%d/salary-history" % emp["id"]).json()["revisions"][0]["changed_by"] == "HR"


def test_hr_cannot_raise_the_masters_own_salary(tenant, hr):
    masters = [e for e in tenant.get("/api/employees").json() if e.get("permission_role") == "owner"]
    for m in masters:
        assert hr.post("/api/employees/%d/increment" % m["id"], json={"mode": "percent", "value": 5, "effective_date": day(0)}).status_code in (400, 403)


# --- the reminder, a year on ------------------------------------------------------------------------------------------
def _run_reminders(monkeypatch):
    from app.db import SessionLocal
    from app.services import salary_revisions as sr
    mails = []
    from _patching import patch_app
    patch_app(monkeypatch, "send_email_background", lambda to, subject, body, *a, **k: mails.append((to, subject, body)) or (True, ""))
    with SessionLocal() as db:
        out = sr.job_increment_reminders(db, datetime.now())
    return out, mails


def _notes(c):
    return [n for n in c.get("/api/employee/notifications").json()["notifications"] if n["title"].startswith("Increment due")]


def test_hr_is_reminded_a_year_after_an_increment(tenant, hr, monkeypatch):
    emp = make_employee(tenant, first_name="Priya", last_name="Nair", salary=50000.0, start_date="2020-01-01")
    last_year = day(-366)
    assert tenant.post("/api/employees/%d/increment" % emp["id"], json={"mode": "percent", "value": 10, "effective_date": last_year}).status_code == 200
    out, mails = _run_reminders(monkeypatch)
    assert out == "1 reminder(s)"
    notes = _notes(hr)
    assert len(notes) == 1 and "Priya Nair" in notes[0]["title"] and last_year in notes[0]["message"]
    assert mails == [], "on screen only: nothing is emailed unless somebody clicks send"
    assert any(a["title"] == "Increment due: Priya Nair" for a in tenant.get("/api/alerts").json().get("alerts", tenant.get("/api/alerts").json()) if isinstance(a, dict))
    # once only
    assert _run_reminders(monkeypatch)[0] == "0 reminder(s)"
    assert len(_notes(hr)) == 1


def test_no_reminder_before_the_year_is_up_or_after_a_newer_increment(tenant, hr, monkeypatch):
    soon = make_employee(tenant, salary=50000.0, start_date="2020-01-01")
    assert tenant.post("/api/employees/%d/increment" % soon["id"], json={"mode": "percent", "value": 10, "effective_date": day(-200)}).status_code == 200
    renewed = make_employee(tenant, salary=50000.0, start_date="2020-01-01")
    for when in (day(-500), day(-30)):
        assert tenant.post("/api/employees/%d/increment" % renewed["id"], json={"mode": "percent", "value": 5, "effective_date": when}).status_code == 200
    assert _run_reminders(monkeypatch)[0] == "0 reminder(s)"
    assert _notes(hr) == []


def test_an_increment_runs_a_year_unless_told_otherwise_and_the_reminder_follows_it(tenant, hr, monkeypatch):
    a = make_employee(tenant, salary=50000.0, start_date="2020-01-01")
    b = make_employee(tenant, salary=50000.0, start_date="2020-01-01")
    start = day(-100)
    ra = tenant.post("/api/employees/%d/increment" % a["id"], json={"mode": "percent", "value": 10, "effective_date": start}).json()["revision"]
    assert ra["valid_until"] == (datetime.strptime(start, "%Y-%m-%d").replace(year=datetime.strptime(start, "%Y-%m-%d").year + 1)).strftime("%Y-%m-%d")
    url = "/api/employees/%d/increment" % b["id"]
    assert tenant.post(url, json={"mode": "percent", "value": 10, "effective_date": start, "valid_until": start}).status_code == 400   # not after it began
    assert tenant.post(url, json={"mode": "percent", "value": 10, "effective_date": start, "valid_until": day(-1)}).status_code == 200   # six months, already over
    assert _run_reminders(monkeypatch)[0] == "1 reminder(s)"                                                                         # only b's is due
    assert len(_notes(hr)) == 1


def test_a_salary_typed_in_the_edit_form_is_kept_in_the_history(tenant):
    emp = make_employee(tenant, salary=40000.0, start_date="2020-01-01")
    assert tenant.put("/api/employees/%d" % emp["id"], json={"salary": 44000}).status_code == 200
    revs = tenant.get("/api/employees/%d/salary-history" % emp["id"]).json()["revisions"]
    assert [(r["old_salary"], r["new_salary"], r["percent"], r["reason"]) for r in revs] == [(40000.0, 44000.0, 10.0, "Changed in the Edit form")]
    # saving again without changing it adds nothing
    assert tenant.put("/api/employees/%d" % emp["id"], json={"salary": 44000, "job_title": "Clerk"}).status_code == 200
    assert len(tenant.get("/api/employees/%d/salary-history" % emp["id"]).json()["revisions"]) == 1


def test_the_office_alert_names_the_person_but_not_the_pay(tenant, hr, monkeypatch):
    emp = make_employee(tenant, first_name="Kiran", last_name="Rao", salary=50000.0, start_date="2020-01-01")
    assert tenant.post("/api/employees/%d/increment" % emp["id"], json={"mode": "percent", "value": 10, "effective_date": day(-400)}).status_code == 200
    _run_reminders(monkeypatch)
    alert = [a for a in tenant.get("/api/alerts").json()["alerts"] if a["title"] == "Increment due: Kiran Rao"][0]
    assert "Kiran Rao" in alert["body"] and "55000" not in alert["body"] and "50000" not in alert["body"]
    assert "55000.00" in _notes(hr)[0]["message"]
