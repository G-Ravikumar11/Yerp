"""Signing in is not the same as starting a shift.

Someone opening the portal on a Sunday to read a payslip or upload a document
was being marked present for the day. Attendance should only start when the
person says it does, or when it is a working day and the tenant wants sign-in
to count.
"""
from datetime import date

import pytest

import main
from conftest import make_employee


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


@pytest.fixture
def staffer(tenant):
    return make_employee(tenant, password="EmpPass123")


def login(client, emp):
    return client.post("/api/employee/auth/login",
                       json={"email": emp["email"], "password": "EmpPass123"})


# --- the rule itself ---------------------------------------------------------

def test_monday_to_friday_is_the_default():
    assert main.parse_working_days(None) == {1, 2, 3, 4, 5}
    assert main.clean_working_days(None) == "1,2,3,4,5"


def test_a_saturday_and_sunday_are_not_working_days():
    class S:
        working_days = "1,2,3,4,5"
    assert main.is_working_day(S(), date(2026, 8, 7)) is True    # Friday
    assert main.is_working_day(S(), date(2026, 8, 8)) is False   # Saturday
    assert main.is_working_day(S(), date(2026, 8, 9)) is False   # Sunday


def test_a_tenant_that_works_weekends_can_say_so():
    class S:
        working_days = "6,7"
    assert main.is_working_day(S(), date(2026, 8, 9)) is True    # Sunday
    assert main.is_working_day(S(), date(2026, 8, 10)) is False  # Monday


def test_rubbish_falls_back_to_a_normal_week():
    """An empty set would make every day a day off and nobody could ever be
    marked present."""
    for junk in ("", "   ", "abc", "0,9,99", None, ","):
        assert main.parse_working_days(junk) == {1, 2, 3, 4, 5}


def test_days_are_stored_tidily():
    assert main.clean_working_days("3,1,2") == "1,2,3"
    assert main.clean_working_days([7, 6]) == "6,7"
    assert main.clean_working_days("1, 2 ,3") == "1,2,3"


def test_switching_auto_clock_in_off_stops_it_on_a_working_day_too():
    class S:
        working_days = "1,2,3,4,5"
        auto_clock_in = False
    assert main.should_auto_clock_in(S(), date(2026, 8, 10)) is False

    class T:
        working_days = "1,2,3,4,5"
        auto_clock_in = True
    assert main.should_auto_clock_in(T(), date(2026, 8, 10)) is True
    assert main.should_auto_clock_in(T(), date(2026, 8, 9)) is False


# --- settings ----------------------------------------------------------------

def test_settings_expose_the_new_fields(tenant):
    body = tenant.get("/api/attendance/settings").json()
    assert body["working_days"] == "1,2,3,4,5"
    assert body["auto_clock_in"] is True


def test_hr_can_change_them(tenant):
    tenant.put("/api/attendance/settings",
               json={"working_days": "1,2,3,4,5,6", "auto_clock_in": False})
    body = tenant.get("/api/attendance/settings").json()
    assert body["working_days"] == "1,2,3,4,5,6"
    assert body["auto_clock_in"] is False


def test_saving_nonsense_days_cannot_empty_the_week(tenant):
    tenant.put("/api/attendance/settings", json={"working_days": "banana"})
    assert tenant.get("/api/attendance/settings").json()["working_days"] == "1,2,3,4,5"


# --- signing in --------------------------------------------------------------

def test_sign_in_does_not_clock_in_when_auto_is_off(portal, tenant, staffer):
    tenant.put("/api/attendance/settings", json={"auto_clock_in": False})

    res = login(portal, staffer)
    assert res.status_code == 200, res.text
    assert res.json()["clock_in"] == ""
    assert res.json()["auto_clock_in"] is False

    today = portal.get("/api/employee/attendance/today").json()
    assert today["clocked_in"] is False


def test_they_can_still_clock_in_by_hand(portal, tenant, staffer):
    """A day off is not a lock-out; people do work weekends."""
    tenant.put("/api/attendance/settings", json={"auto_clock_in": False})
    login(portal, staffer)

    res = portal.post("/api/employee/attendance/clock-in", json={})
    assert res.status_code == 200, res.text
    assert portal.get("/api/employee/attendance/today").json()["clocked_in"] is True


def test_hr_sees_no_attendance_for_a_sign_in_that_was_not_a_shift(portal, tenant, staffer):
    tenant.put("/api/attendance/settings", json={"auto_clock_in": False})
    login(portal, staffer)

    rows = tenant.get("/api/attendance").json()
    mine = [r for r in rows if r.get("employee_id") == staffer["id"]]
    assert mine == []


def test_sign_in_still_clocks_in_when_the_tenant_wants_it(portal, tenant, staffer):
    """Unchanged for anyone happy with the old behaviour, on a working day."""
    tenant.put("/api/attendance/settings",
               json={"auto_clock_in": True, "working_days": "1,2,3,4,5,6,7"})
    res = login(portal, staffer)
    assert res.json()["clock_in"]
    assert portal.get("/api/employee/attendance/today").json()["clocked_in"] is True


def test_a_second_sign_in_does_not_start_a_second_shift(portal, tenant, staffer):
    tenant.put("/api/attendance/settings",
               json={"auto_clock_in": True, "working_days": "1,2,3,4,5,6,7"})
    first = login(portal, staffer).json()["clock_in"]
    again = login(portal, staffer).json()
    assert again["clock_in"] == first


def test_the_portal_is_told_whether_today_is_a_working_day(portal, tenant, staffer):
    tenant.put("/api/attendance/settings",
               json={"auto_clock_in": False, "working_days": "1,2,3,4,5,6,7"})
    login(portal, staffer)
    assert portal.get("/api/employee/attendance/today").json()["is_working_day"] is True

    tenant.put("/api/attendance/settings", json={"working_days": "1"})
    body = portal.get("/api/employee/attendance/today").json()
    assert body["is_working_day"] == (date.today().isoweekday() == 1)
