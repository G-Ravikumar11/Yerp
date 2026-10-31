"""Paid days: joining and leaving part-way through a month, loss of pay, and the pay that follows."""
from datetime import date

import pytest

from app import db as database
from app import models
from app.services import lop
from conftest import make_employee

START, END = "2026-10-01", "2026-10-31"      # 22 working days, Monday to Friday
TODAY = date(2026, 10, 31)


def working_dates():
    out, d = [], date(2026, 10, 1)
    while d <= date(2026, 10, 31):
        if d.isoweekday() <= 5:
            out.append(d.isoformat())
        d = date.fromordinal(d.toordinal() + 1)
    return out


@pytest.fixture
def db():
    s = database.SessionLocal()
    yield s
    s.close()


def row_of(db, emp):
    return db.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()


def days_for(db, emp, **employee_changes):
    row = row_of(db, emp)
    for k, v in employee_changes.items():
        setattr(row, k, v)
    db.flush()
    return lop.pay_days(db, row.client_id, row, START, END, today=TODAY)


def leave(db, row, kind, start, end, status="approved"):
    db.add(models.DBLeaveRequest(client_id=row.client_id, employee_id=row.id, leave_type=kind, start_date=start,
                                 end_date=end, days=1, status=status))
    db.flush()


def clock(db, row, dates, status="present"):
    for d in dates:
        db.add(models.DBAttendance(client_id=row.client_id, employee_id=row.id, date=d, clock_in="09:00:00", status=status))
    db.flush()


def test_a_full_month_is_all_paid(tenant, db):
    d = days_for(db, make_employee(tenant))
    assert (d["working_days"], d["active_days"], d["lop_days"], d["paid_days"], d["factor"]) == (22, 22, 0, 22, 1.0)


def test_joining_part_way_pays_only_the_days_after(tenant, db):
    d = days_for(db, make_employee(tenant), start_date="2026-10-12")
    assert (d["working_days"], d["active_days"], d["paid_days"]) == (22, 15, 15)


def test_leaving_part_way_pays_only_the_days_before(tenant, db):
    d = days_for(db, make_employee(tenant), end_date="2026-10-09")
    assert d["active_days"] == 7 and d["paid_days"] == 7


def test_joining_and_leaving_in_the_same_month(tenant, db):
    d = days_for(db, make_employee(tenant), start_date="2026-10-12", end_date="2026-10-16")
    assert d["active_days"] == 5


def test_not_on_the_books_at_all_has_no_active_days(tenant, db):
    d = days_for(db, make_employee(tenant), start_date="2026-11-02")
    assert d["active_days"] == 0 and d["paid_days"] == 0


def test_unpaid_leave_is_loss_of_pay(tenant, db):
    emp = make_employee(tenant)
    leave(db, row_of(db, emp), "unpaid", "2026-10-05", "2026-10-06")
    d = days_for(db, emp)
    assert d["unpaid_leave"] == 2 and d["lop_days"] == 2 and d["paid_days"] == 20


def test_leave_beyond_the_entitlement_is_loss_of_pay(tenant, db):
    emp = make_employee(tenant)
    leave(db, row_of(db, emp), "annual", "2026-10-05", "2026-10-07")
    d = days_for(db, emp, annual_leave_entitlement=1.0)
    assert d["excess_leave"] == 2 and d["lop_days"] == 2


def test_leave_within_the_entitlement_is_paid_and_pending_leave_does_not_count(tenant, db):
    emp = make_employee(tenant)
    row = row_of(db, emp)
    leave(db, row, "sick", "2026-10-05", "2026-10-06")
    leave(db, row, "unpaid", "2026-10-12", "2026-10-13", status="pending")
    d = days_for(db, emp)
    assert d["lop_days"] == 0 and d["paid_days"] == 22


def test_days_with_no_attendance_and_no_leave_are_absences(tenant, db):
    emp = make_employee(tenant)
    row = row_of(db, emp)
    dates = working_dates()
    clock(db, row, dates[:-5])                          # the last five working days: nothing
    leave(db, row, "annual", dates[-5], dates[-4])      # two of them on approved leave
    d = days_for(db, emp)
    assert d["tracked"] and d["absent"] == 3 and d["lop_days"] == 3 and d["paid_days"] == 19


def test_somebody_who_never_clocks_in_is_not_marked_absent(tenant, db):
    d = days_for(db, make_employee(tenant))
    assert not d["tracked"] and d["absent"] == 0 and d["paid_days"] == 22


def test_too_many_lates_cost_half_days(tenant, db):
    dates = working_dates()
    emp, few = make_employee(tenant), make_employee(tenant)       # both made before the session holds a write lock
    clock(db, row_of(db, emp), dates[:6], status="late")
    clock(db, row_of(db, emp), dates[6:])
    d = days_for(db, emp)
    assert d["late_count"] == 6 and d["late_penalty"] == 1.0 and d["lop_days"] == 1.0 and d["paid_days"] == 21
    clock(db, row_of(db, few), dates[:2], status="late")
    clock(db, row_of(db, few), dates[2:])
    assert days_for(db, few)["late_penalty"] == 0       # two lates: under the threshold of three


def test_the_tenants_own_late_rule_is_used(tenant, db):
    assert tenant.put("/api/attendance/settings", json={"late_threshold": 2, "late_penalty_lop": 1}).status_code == 200
    emp = make_employee(tenant)
    dates = working_dates()
    clock(db, row_of(db, emp), dates[:2], status="late")
    clock(db, row_of(db, emp), dates[2:])
    assert days_for(db, emp)["late_penalty"] == 1.0


def test_bad_late_settings_are_refused(tenant):
    assert tenant.put("/api/attendance/settings", json={"late_threshold": 0}).status_code == 400
    assert tenant.put("/api/attendance/settings", json={"late_penalty_lop": 2}).status_code == 400
    got = tenant.get("/api/attendance/settings").json()
    assert (got["late_threshold"], got["late_penalty_lop"]) == (3, 0.5)


def test_a_payslip_pays_the_prorated_amount(tenant):
    emp = make_employee(tenant, salary=22000.0, tax_rate=0.0, start_date="2026-10-12")
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": START, "period_end": END,
                                             "pay_date": END, "use_structure": False})
    slip = tenant.get("/api/payslips/%d" % res.json()["id"]).json()
    assert slip["basic_salary"] == 15000.0          # 22,000 / 22 x 15
    assert (slip["working_days"], slip["paid_days"], slip["lop_days"]) == (22, 15, 0)


def test_a_structured_payslip_prorates_each_component_and_the_statutory_lines_follow(tenant):
    emp = make_employee(tenant, salary=22000.0, tax_rate=0.0, start_date="2026-10-12")
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": START, "period_end": END, "pay_date": END})
    slip = tenant.get("/api/payslips/%d" % res.json()["id"]).json()
    by = {l["name"]: l["amount"] for l in slip["lines"]}
    assert by["Basic"] == 6000.0 and by["Conveyance"] == 1500.0     # 8,800 and 2,200 over 15 of 22 days
    assert by["PF"] == 720.0                                          # 12% of the prorated basic
    assert slip["paid_days"] == 15 and slip["working_days"] == 22


def test_a_payroll_run_skips_somebody_not_yet_employed(tenant):
    late = make_employee(tenant, start_date="2026-11-02")
    res = tenant.post("/api/payroll/run", json={"period_start": START, "period_end": END, "pay_date": END,
                                                "employee_ids": [late["id"]]})
    assert res.status_code == 400 or res.json()["skipped"]


def test_hourly_pay_is_not_prorated(tenant):
    emp = make_employee(tenant, salary=0.0, hourly_rate=25.0, start_date="2026-10-12")
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": START, "period_end": END,
                                             "pay_date": END, "hours_worked": 10})
    slip = tenant.get("/api/payslips/%d" % res.json()["id"]).json()
    assert slip["basic_salary"] == 250.0 and slip["paid_days"] == 0
