"""Reminders for probation ending, contracts ending and statutory documents expiring."""
from datetime import date

import pytest

from app import db as database
from app import models
from app.services import hr_reminders as hr
from conftest import make_employee

TODAY = date(2026, 11, 2)


@pytest.fixture
def s():
    session = database.SessionLocal()
    yield session
    session.close()


def row(s, emp):
    return s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()


def names(found, kind):
    return {x[0].id for x in found[kind]}


def test_probation_is_reminded_on_its_milestone_days_only(tenant, s):
    on_day, week, quiet = (make_employee(tenant) for _ in range(3))
    row(s, on_day).probation_end_date = "2026-11-02"
    row(s, week).probation_end_date = "2026-11-09"
    row(s, quiet).probation_end_date = "2026-11-05"           # three days: not a milestone
    s.commit()
    found = hr.due_today(s, row(s, on_day).client_id, TODAY)
    assert names(found, "probation") == {on_day["id"], week["id"]}


def test_contract_end_and_the_day_after(tenant, s):
    month, after, gone = (make_employee(tenant) for _ in range(3))
    row(s, month).contract_end_date = "2026-12-02"
    row(s, after).contract_end_date = "2026-11-01"
    row(s, gone).contract_end_date = "2026-11-01"
    row(s, gone).status = "terminated"                        # already let go: nothing to remind
    s.commit()
    found = hr.due_today(s, row(s, month).client_id, TODAY)
    assert names(found, "contract") == {month["id"], after["id"]}


@pytest.mark.parametrize("days,window,due", [(30, 30, True), (29, 30, False), (7, 30, True), (0, 30, True),
                                             (-7, 30, True), (-3, 30, False), (-56, 30, True), (-63, 30, False),
                                             (45, 45, True)])
def test_document_milestones(days, window, due):
    assert hr.doc_due(days, window) is due


def test_an_expiring_document_tells_the_employee_and_hr(tenant, s):
    e = make_employee(tenant)
    emp = row(s, e)
    req = models.DBDocumentRequirement(client_id=emp.client_id, name="Driving licence", requires_expiry=True, expiry_reminder_days=30)
    s.add(req)
    s.flush()
    s.add(models.DBDocumentRequest(client_id=emp.client_id, employee_id=emp.id, requirement_id=req.id,
                                   name="Driving licence", requires_expiry=True, expires_on="2026-11-09", status="approved"))
    s.commit()
    found = hr.due_today(s, emp.client_id, TODAY)
    assert [(x[0].id, x[2]) for x in found["documents"]] == [(emp.id, 7)]
    assert hr.send(s, emp.client_id, found) == 1
    mine = s.query(models.DBNotification).filter(models.DBNotification.employee_id == emp.id).all()
    assert any(n.title == "Driving licence expires in 7 days" for n in mine)
    bell = s.query(models.DBAlert).filter(models.DBAlert.client_id == emp.client_id, models.DBAlert.kind == "documents_expiring").all()
    assert bell and "Driving licence" in bell[-1].body


def test_the_manager_and_hr_hear_about_probation(tenant, s):
    boss, new = make_employee(tenant), make_employee(tenant)
    r = row(s, new)
    r.probation_end_date, r.reports_to = "2026-11-09", boss["id"]
    s.commit()
    hr.send(s, r.client_id, hr.due_today(s, r.client_id, TODAY))
    told = s.query(models.DBNotification).filter(models.DBNotification.employee_id == boss["id"]).all()
    assert any("Probation ending" in n.title and "in 7 days" in n.message for n in told)
    bell = s.query(models.DBAlert).filter(models.DBAlert.client_id == r.client_id, models.DBAlert.kind == "probation_ending").all()
    assert bell and "Confirm them" in bell[-1].body


def test_the_job_is_registered_daily():
    from app.core.scheduler import SCHEDULED_JOBS, daily_key
    assert {n: k for n, k, _ in SCHEDULED_JOBS}["hr_reminders"] is daily_key
