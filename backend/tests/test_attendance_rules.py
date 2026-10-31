"""Overtime rate and duplicates, clock-out through midnight, location rules on clock-in, leave counted on the company's week."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import db as database
from app import models
from app.services.payroll import OVERTIME_MULTIPLIER, compute_payslip_figures, default_overtime_rate
from conftest import make_employee, work_every_day

OFFICE = {"office_lat": 17.4000, "office_lng": 78.4800, "geofence_radius": 200}
AT_OFFICE = {"latitude": 17.4001, "longitude": 78.4801}
FAR_AWAY = {"latitude": 17.5000, "longitude": 78.6000}


def settings(tenant, **kw):
    kw = {"working_days": "1,2,3,4,5,6,7", **kw}
    assert tenant.put("/api/attendance/settings", json=kw).status_code == 200


# --- A: overtime ----------------------------------------------------------------------------------------------------

def test_overtime_without_a_rate_is_twice_the_ordinary_hourly_wage():
    assert OVERTIME_MULTIPLIER == 2.0
    emp = SimpleNamespace(hourly_rate=0, salary=16000, pay_frequency="monthly", tax_rate=0, deductions=0)
    assert default_overtime_rate(emp) == 200.0                      # 16,000 / 160 = 100 an hour, doubled
    assert compute_payslip_figures(emp, {"overtime_hours": 3, "basic_salary": 16000})["overtime_pay"] == 600.0


def test_an_hourly_workers_own_rate_is_kept():
    assert default_overtime_rate(SimpleNamespace(hourly_rate=75.0, salary=0)) == 75.0


def test_announcing_overtime_twice_for_a_day_updates_the_one_record(tenant):
    emp = make_employee(tenant)
    for hours in (2, 3.5):
        res = tenant.post("/api/attendance/overtime/announce", json={"employee_id": emp["id"], "hours": hours, "date": "2026-10-05"})
        assert res.status_code == 200, res.text
    logs = [l for l in tenant.get("/api/attendance/overtime/logs").json() if l["employee_id"] == emp["id"]]
    assert len(logs) == 1 and logs[0]["hours"] == 3.5


# --- B: clock-out ---------------------------------------------------------------------------------------------------

def open_shift(tenant, emp, day, clock_in, **extra):
    s = database.SessionLocal()
    try:
        client_id = s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one().client_id
        s.add(models.DBAttendance(client_id=client_id, employee_id=emp["id"], date=day, clock_in=clock_in, status="present", **extra))
        s.commit()
    finally:
        s.close()


def test_clock_out_takes_the_break_off_the_hours(tenant):
    emp = make_employee(tenant)
    now = datetime.now()
    if now.hour < 3:
        pytest.skip("needs a clock-in earlier the same day")
    start = (now - timedelta(hours=2)).strftime("%H:%M:%S")
    open_shift(tenant, emp, now.strftime("%Y-%m-%d"), start, break_minutes=30.0)
    out = tenant.post("/api/attendance/clock-out", json={"employee_id": emp["id"]})
    assert out.status_code == 200, out.text
    assert 1.4 <= out.json()["total_hours"] <= 1.6, "about two hours, less the half hour break"


def test_a_shift_that_ran_past_midnight_is_closed_the_next_day_with_positive_hours(tenant):
    emp = make_employee(tenant)
    now = datetime.now()
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    # Started late yesterday evening, later than the time it is now: the clock-out is earlier on the dial than the clock-in.
    start = "23:59:00" if now.strftime("%H:%M:%S") < "23:59:00" else "23:58:00"
    open_shift(tenant, emp, yesterday, start)
    out = tenant.post("/api/attendance/clock-out", json={"employee_id": emp["id"]})
    assert out.status_code == 200, out.text
    assert out.json()["total_hours"] > 0


def test_clock_out_without_a_shift_or_twice_is_refused(tenant):
    emp = make_employee(tenant)
    assert tenant.post("/api/attendance/clock-out", json={"employee_id": emp["id"]}).status_code == 400
    settings(tenant, require_location=False)
    assert tenant.post("/api/attendance/clock-in", json={"employee_id": emp["id"]}).status_code == 200
    assert tenant.post("/api/attendance/clock-out", json={"employee_id": emp["id"]}).status_code == 200
    assert tenant.post("/api/attendance/clock-out", json={"employee_id": emp["id"]}).status_code == 400


# --- C: location ----------------------------------------------------------------------------------------------------

def test_location_is_required_when_the_company_says_so(tenant):
    emp = make_employee(tenant)
    settings(tenant, require_location=True, allow_remote=True)
    res = tenant.post("/api/attendance/clock-in", json={"employee_id": emp["id"]})
    assert res.status_code == 400 and "location" in res.json()["detail"].lower()
    assert tenant.post("/api/attendance/clock-in", json={"employee_id": emp["id"], **FAR_AWAY}).status_code == 200


def test_no_location_needed_when_it_is_off_and_remote_is_allowed(tenant):
    emp = make_employee(tenant)
    settings(tenant, require_location=False, allow_remote=True)
    assert tenant.post("/api/attendance/clock-in", json={"employee_id": emp["id"]}).status_code == 200


def test_with_remote_off_only_the_office_will_do(tenant):
    inside, outside = make_employee(tenant), make_employee(tenant)
    settings(tenant, require_location=True, allow_remote=False, **OFFICE)
    assert tenant.post("/api/attendance/clock-in", json={"employee_id": outside["id"], **FAR_AWAY}).status_code == 400
    assert tenant.post("/api/attendance/clock-in", json={"employee_id": inside["id"], **AT_OFFICE}).status_code == 200


def test_with_remote_off_and_nowhere_to_check_against_it_says_so(tenant):
    emp = make_employee(tenant)
    settings(tenant, require_location=True, allow_remote=False)
    res = tenant.post("/api/attendance/clock-in", json={"employee_id": emp["id"], **AT_OFFICE})
    assert res.status_code == 400 and "ask hr" in res.json()["detail"].lower()


def test_remote_off_also_needs_a_location_even_if_not_required(tenant):
    emp = make_employee(tenant)
    settings(tenant, require_location=False, allow_remote=False, **OFFICE)
    assert tenant.post("/api/attendance/clock-in", json={"employee_id": emp["id"]}).status_code == 400


def test_a_project_site_counts_as_a_place_to_clock_in_from(client, tenant):
    job = tenant.post("/api/jobs", json={"name": "Remote site"}).json()
    emp = make_employee(tenant, password="EmpPass123")
    settings(tenant, require_location=True, allow_remote=False, **OFFICE)
    put = tenant.put("/api/jobs/%d/site-location" % job["id"], json={"lat": FAR_AWAY["latitude"], "lng": FAR_AWAY["longitude"], "radius_m": 300})
    assert put.status_code == 200, put.text
    client.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert client.post("/api/employee/attendance/clock-in", json=FAR_AWAY).status_code == 200


def test_the_staff_portal_follows_the_same_rules(client, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    settings(tenant, require_location=True, allow_remote=False, **OFFICE)
    client.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert client.post("/api/employee/attendance/clock-in", json={}).status_code == 400
    assert client.post("/api/employee/attendance/clock-in", json=FAR_AWAY).status_code == 400
    assert client.post("/api/employee/attendance/clock-in", json=AT_OFFICE).status_code == 200


# --- D: leave days --------------------------------------------------------------------------------------------------

def test_leave_days_follow_the_companys_working_week(portal, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    settings(tenant, working_days="1,2,3,4,5,6", require_location=False)          # Monday to Saturday
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-10-05", "end_date": "2026-10-10", "days": 1})
    assert res.status_code == 200, res.text
    mine = portal.get("/api/employee/leave").json()["requests"]
    assert mine[0]["days"] == 6, "Monday to Saturday is six working days, whatever the request claims"


def test_a_range_with_no_working_days_is_refused(portal, tenant):
    emp = make_employee(tenant, password="EmpPass123")
    settings(tenant, working_days="1,2,3,4,5", require_location=False)
    portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-10-10", "end_date": "2026-10-11"})
    assert res.status_code == 400
