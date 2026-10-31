"""Shifts and breaks that cross midnight: the portal finds last night's shift, the nightly check leaves it alone until it
has run its length, and minutes are measured round the clock."""
from datetime import datetime

import pytest

from app import db as database
from app import models
from app.services import attendance_job
from app.services import employee_portal as svc
from conftest import make_employee

YESTERDAY, TODAY = "2026-10-14", "2026-10-15"


class Clock:
    """A settable 'now' for the two modules that read the time of day."""
    value = datetime(2026, 10, 15, 1, 30, 0)


@pytest.fixture
def clock(monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return Clock.value
    monkeypatch.setattr("app.services.employee_portal.datetime", Frozen)
    monkeypatch.setattr("app.routers.employee_portal.datetime", Frozen)
    Clock.value = datetime(2026, 10, 15, 1, 30, 0)
    return Clock


def at(h, m=0):
    Clock.value = datetime(2026, 10, 15, h, m, 0)


# --- minutes round the clock -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("start,now,expected", [
    ("23:50:00", datetime(2026, 10, 15, 0, 20), 30),        # begun before midnight, ended after
    ("00:30:00", datetime(2026, 10, 15, 1, 0), 30),         # begun after midnight, in a shift dated the day before
    ("09:00:00", datetime(2026, 10, 14, 9, 45), 45),        # an ordinary break
])
def test_minutes_since_wraps_past_midnight(start, now, expected):
    assert svc.minutes_since(start, now) == expected


def person(tenant, **kw):
    emp = make_employee(tenant, password="EmpPass123", **kw)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    assert tenant.put("/api/attendance/settings", json={"working_days": "1,2,3,4,5,6,7", "require_location": False}).status_code == 200
    return emp


def open_shift_yesterday(emp, clock_in="22:00:00", **extra):
    s = database.SessionLocal()
    try:
        cid = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one().client_id
        s.add(models.DBAttendance(client_id=cid, employee_id=emp["id"], date=YESTERDAY, clock_in=clock_in, status="present", **extra))
        s.commit()
    finally:
        s.close()


def stored(emp, day=YESTERDAY):
    s = database.SessionLocal()
    try:
        a = s.query(models.DBAttendance).filter(models.DBAttendance.employee_id == emp["id"], models.DBAttendance.date == day).first()
        return a and {c.name: getattr(a, c.name) for c in a.__table__.columns}
    finally:
        s.close()


def sign_in(portal, emp):
    assert portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"}).status_code == 200


# --- the portal ------------------------------------------------------------------------------------------------------

def test_last_nights_shift_is_the_current_one_and_clocks_out_with_the_hours(tenant, portal, clock):
    emp = person(tenant)
    open_shift_yesterday(emp)                                     # 22:00 yesterday; it is 01:30
    sign_in(portal, emp)
    now = portal.get("/api/employee/attendance/today").json()
    assert now["clocked_in"] is True and now["clock_in"] == "22:00:00"
    assert now["elapsed_seconds"] == int(3.5 * 3600), "counted from last night, not from a clock-in 'today' that never was"
    at(2, 0)
    out = portal.post("/api/employee/attendance/clock-out")
    assert out.status_code == 200, out.text
    assert out.json()["total_hours"] == 4.0
    done = stored(emp)
    assert done["clock_out"] == "02:00:00" and done["status"] == "completed", "the record stays on the day it began"
    assert stored(emp, TODAY) is None


def test_a_break_across_midnight_comes_off_the_hours(tenant, portal, clock):
    emp = person(tenant)
    open_shift_yesterday(emp)
    sign_in(portal, emp)
    Clock.value = datetime(2026, 10, 14, 23, 50)                  # the break starts before midnight ...
    assert portal.post("/api/employee/attendance/break-start").status_code == 200
    Clock.value = datetime(2026, 10, 15, 0, 20)                   # ... and ends after it
    ended = portal.post("/api/employee/attendance/break-stop")
    assert ended.status_code == 200 and ended.json()["break_minutes"] == 30
    at(2, 0)
    assert portal.post("/api/employee/attendance/clock-out").json()["total_hours"] == 3.5     # 4 hours less the half hour


def test_a_break_still_on_when_the_clock_out_comes_is_closed_round_midnight(tenant, portal, clock):
    emp = person(tenant)
    open_shift_yesterday(emp, is_on_break=True, break_start="23:40:00")
    sign_in(portal, emp)
    at(0, 40)
    out = portal.post("/api/employee/attendance/clock-out").json()
    assert out["break_minutes"] == 60 and out["total_hours"] == round(2.67 - 1.0, 2)         # 22:00 to 00:40, less the hour


def test_clocking_in_over_a_running_shift_is_refused(tenant, portal, clock):
    emp = person(tenant)
    open_shift_yesterday(emp)
    sign_in(portal, emp)
    res = portal.post("/api/employee/attendance/clock-in", json={})
    assert res.status_code == 400 and "still clocked in from last night" in res.json()["detail"]
    portal.post("/api/employee/attendance/clock-out")
    assert portal.post("/api/employee/attendance/clock-in", json={}).status_code == 200


def test_a_forgotten_shift_from_yesterday_does_not_block_todays(tenant, portal, clock):
    emp = person(tenant)
    open_shift_yesterday(emp, clock_in="09:00:00")                # more than ten hours ago by 09:00 today
    sign_in(portal, emp)
    at(9, 0)
    assert portal.get("/api/employee/attendance/today").json()["clocked_in"] is False
    assert portal.post("/api/employee/attendance/clock-in", json={}).status_code == 200


def test_signing_out_stops_last_nights_shift_too(tenant, portal, clock):
    emp = person(tenant)
    open_shift_yesterday(emp)
    sign_in(portal, emp)
    at(2, 30)
    assert portal.post("/api/employee/auth/logout").status_code in (200, 204)
    assert stored(emp)["clock_out"] == "02:30:00"


# --- the nightly check -----------------------------------------------------------------------------------------------

def run_check(emp, now):
    s = database.SessionLocal()
    try:
        row = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()
        client = s.query(models.DBClient).filter(models.DBClient.id == row.client_id).one()
        return attendance_job.nightly_for_client(s, client, datetime(2026, 10, 14).date(), now)
    finally:
        s.close()


def test_the_nightly_check_leaves_a_shift_that_is_still_within_its_length(tenant):
    emp = person(tenant)
    open_shift_yesterday(emp)                                     # 22:00; ten hours run to 08:00
    assert run_check(emp, datetime(2026, 10, 15, 0, 10))["closed"] == 0
    assert stored(emp)["clock_out"] in ("", None)


def test_the_nightly_check_closes_it_once_it_has_run_its_length(tenant):
    emp = person(tenant)
    open_shift_yesterday(emp)
    assert run_check(emp, datetime(2026, 10, 15, 8, 30))["closed"] == 1
    done = stored(emp)
    assert done["clock_out"] == "08:00:00" and done["total_hours"] == 10.0 and done["overtime_hours"] == 0
