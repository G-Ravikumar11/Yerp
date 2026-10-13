"""Signing in never clocks anybody in; a shift starts when the person presses Clock in.

Opening the portal to read a payslip, or to check a document on a Sunday, is not
being at work - and with a shift started for them the time counted from the
moment they signed in rather than from when they arrived. So the button is the
only way a shift starts, for each employee separately, on any day.
"""
import pytest

import main
from conftest import make_employee, work_every_day


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert res.status_code == 200, res.text
    return res.json()


def test_signing_in_does_not_clock_you_in(client, tenant):
    work_every_day(tenant)     # a working day whenever the suite runs
    emp = make_employee(tenant, password="EmpPass123")
    body = sign_in(client, emp)
    assert not body["clock_in"]
    today = client.get("/api/employee/attendance/today").json()
    assert today["clocked_in"] is False


def test_signing_in_on_a_day_off_does_not_either(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    assert not sign_in(client, emp)["clock_in"]


def test_pressing_clock_in_starts_the_shift(client, tenant):
    work_every_day(tenant)
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    res = client.post("/api/employee/attendance/clock-in", json={})
    assert res.status_code == 200, res.text
    today = client.get("/api/employee/attendance/today").json()
    assert today["clocked_in"] is True and today["clock_in"] == res.json()["clock_in"]
    assert client.post("/api/employee/attendance/clock-in", json={}).status_code == 400, "once a day"


def test_they_can_clock_in_by_hand_on_a_day_off(client, tenant):
    """Coming in on a day off is allowed; it just is not automatic."""
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    assert client.post("/api/employee/attendance/clock-in", json={}).status_code == 200


def test_a_break_can_only_be_taken_once_clocked_in(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    assert client.post("/api/employee/attendance/break-start").status_code == 400, "not clocked in yet"
    client.post("/api/employee/attendance/clock-in", json={})
    assert client.post("/api/employee/attendance/break-start").status_code == 200
    today = client.get("/api/employee/attendance/today").json()
    assert today["is_on_break"] is True
    assert client.post("/api/employee/attendance/break-stop").status_code == 200
    assert client.get("/api/employee/attendance/today").json()["is_on_break"] is False


def test_each_employee_clocks_in_for_themselves(client, portal, tenant):
    a = make_employee(tenant, password="EmpPass123")
    b = make_employee(tenant, password="EmpPass123")
    sign_in(client, a)
    sign_in(portal, b)
    client.post("/api/employee/attendance/clock-in", json={})
    assert client.get("/api/employee/attendance/today").json()["clocked_in"] is True
    assert portal.get("/api/employee/attendance/today").json()["clocked_in"] is False, "one person's click is not everybody's"


def test_the_old_setting_is_gone_from_the_settings(tenant):
    assert "auto_clock_in" not in tenant.get("/api/attendance/settings").json()


def test_the_server_gives_the_second_the_counter_starts_from(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    client.post("/api/employee/attendance/clock-in", json={})
    body = client.get("/api/employee/attendance/today").json()
    assert isinstance(body["elapsed_seconds"], int) and 0 <= body["elapsed_seconds"] < 60
    assert body["break_elapsed_seconds"] == 0
    client.post("/api/employee/attendance/break-start")
    on_break = client.get("/api/employee/attendance/today").json()
    assert on_break["is_on_break"] and on_break["break_elapsed_seconds"] >= 0


def test_a_short_break_is_not_rounded_to_a_tenth_of_a_minute(client, tenant):
    """Rounded to 6 seconds, the counter on the clock jumped when a break ended."""
    import time
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    client.post("/api/employee/attendance/clock-in", json={})
    client.post("/api/employee/attendance/break-start")
    time.sleep(1.2)
    spent = client.post("/api/employee/attendance/break-stop").json()["break_minutes"]
    assert 0.015 <= spent < 0.1, "a second or two is kept as a second or two, not rounded to 0 or 0.1: %r" % spent


def test_the_clock_is_told_how_long_a_working_day_is(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    assert client.get("/api/employee/attendance/today").json()["target_hours"] == 8.0, "8 hours until HR sets the day"


def test_the_working_day_follows_the_start_and_end_hr_set(client, tenant):
    # set first: the owner and the member of staff share this browser, and signing in replaces the owner
    assert tenant.put("/api/attendance/settings", json={"work_start": "09:00", "work_end": "17:30"}).status_code == 200
    emp = make_employee(tenant, password="EmpPass123")
    sign_in(client, emp)
    assert client.get("/api/employee/attendance/today").json()["target_hours"] == 8.5
    client.post("/api/employee/attendance/clock-in", json={})
    assert client.get("/api/employee/attendance/today").json()["target_hours"] == 8.5, "and once they are working"
