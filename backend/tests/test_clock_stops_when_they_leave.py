"""A shift stops counting the moment the person is signed out - by any route.

Signing out is the obvious one. But the login page ends sessions through the
company logout, which wipes the staff session before the staff logout runs, and
somebody else signing in on the same browser replaces the first person's
session without ever signing them out. In both the clock kept running.
"""
import pytest

import main
from conftest import make_employee


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert res.status_code == 200, res.text


def working(client, emp):
    sign_in(client, emp)
    assert client.post("/api/employee/attendance/clock-in", json={}).status_code == 200


def record_of(emp_id):
    from datetime import datetime
    from app import models
    with main.SessionLocal() as db:
        return db.query(models.DBAttendance).filter(
            models.DBAttendance.employee_id == emp_id,
            models.DBAttendance.date == datetime.now().strftime("%Y-%m-%d")).first()


def test_signing_out_stops_the_clock(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    working(client, emp)
    res = client.post("/api/employee/auth/logout")
    assert res.status_code == 200 and res.json()["total_hours"] >= 0
    row = record_of(emp["id"])
    assert row.clock_out and row.status == "completed"


def test_signing_out_on_a_break_ends_the_break_and_the_shift(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    working(client, emp)
    client.post("/api/employee/attendance/break-start")
    client.post("/api/employee/auth/logout")
    row = record_of(emp["id"])
    assert row.clock_out and row.is_on_break is False and row.break_start == ""


def test_the_company_logout_stops_a_staff_clock_too(client, tenant):
    """The route the login page's clean-up uses; it used to wipe the session first."""
    emp = make_employee(tenant, password="EmpPass123")
    working(client, emp)
    assert client.post("/api/client/logout").status_code == 200
    assert record_of(emp["id"]).clock_out


def test_the_redirecting_logout_stops_it_as_well(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    working(client, emp)
    client.get("/api/auth/logout", follow_redirects=False)
    assert record_of(emp["id"]).clock_out


def test_somebody_else_signing_in_on_the_same_browser_stops_the_first_clock(client, tenant):
    first = make_employee(tenant, password="EmpPass123")
    second = make_employee(tenant, password="EmpPass123")
    working(client, first)
    sign_in(client, second)          # the first was never signed out
    assert record_of(first["id"]).clock_out, "the first person's shift ended when they were replaced"
    assert record_of(second["id"]) is None, "and the second person has not been clocked in by it"


def test_signing_in_again_as_the_same_person_does_not_stop_it(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    working(client, emp)
    sign_in(client, emp)
    assert not record_of(emp["id"]).clock_out


def test_signing_out_without_ever_clocking_in_leaves_no_record(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    assert client.post("/api/employee/auth/logout").status_code == 200
    assert record_of(emp["id"]) is None


def test_signing_out_books_overtime_the_way_clocking_out_does(client, tenant):
    """The sign-out used to compute hours by itself and skip the overtime rule."""
    from datetime import datetime, timedelta
    from app import models
    emp = make_employee(tenant, password="EmpPass123")
    working(client, emp)
    with main.SessionLocal() as db:
        row = db.query(models.DBAttendance).filter(models.DBAttendance.employee_id == emp["id"]).first()
        row.clock_in = (datetime.now() - timedelta(hours=1)).strftime("%H:%M:%S")
        # a one-hour working day, so the hour just worked is not overtime but 30 minutes beyond it would be
        settings = models.DBAttendanceSettings(client_id=row.client_id, work_start="09:00", work_end="09:30",
                                               max_overtime_hours=4)
        db.add(settings)
        db.commit()
    client.post("/api/employee/auth/logout")
    assert record_of(emp["id"]).overtime_hours > 0
