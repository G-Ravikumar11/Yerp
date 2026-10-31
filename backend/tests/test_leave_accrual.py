"""Leave accrued month by month, carried forward to a limit, the rest lapsing."""
from datetime import date

import pytest

from app import db as database
from app import models
from app.services import leave_accrual as la
from app.services.employee_portal import leave_balance_for
from conftest import make_employee


@pytest.fixture
def s():
    session = database.SessionLocal()
    yield session
    session.close()


def row(s, emp):
    return s.query(models.DBEmployee).filter(models.DBEmployee.id == emp["id"]).one()


def test_off_by_default_everybody_has_the_whole_year(tenant, s):
    emp = row(s, make_employee(tenant))
    assert not la.enabled(s, emp.client_id)
    assert leave_balance_for(s, emp, for_year=2026)["annual_total"] == 25.0


def test_switching_on_credits_the_months_already_begun(tenant, s):
    e = make_employee(tenant)
    emp = row(s, e)
    emp.annual_leave_entitlement, emp.sick_leave_entitlement = 24.0, 12.0
    s.commit()
    assert la.set_accrual(s, emp.client_id, True, today=date(2026, 4, 15)) > 0
    s.commit()
    bal = leave_balance_for(s, emp, for_year=2026)
    assert (bal["annual_total"], bal["sick_total"]) == (8.0, 4.0), "January to April: four twelfths"


def test_accrual_is_credited_once_however_often_it_runs(tenant, s):
    emp = row(s, make_employee(tenant))
    emp.annual_leave_entitlement = 12.0
    s.commit()
    la.set_accrual(s, emp.client_id, True, today=date(2026, 3, 1))
    for _ in range(3):
        la.run_month(s, emp.client_id, date(2026, 3, 1))
    s.commit()
    assert la.credited(s, emp, "annual", 2026) == 3.0


def test_nothing_accrues_before_joining(tenant, s):
    emp = row(s, make_employee(tenant))
    emp.start_date, emp.annual_leave_entitlement = "2026-03-10", 12.0
    s.commit()
    la.set_accrual(s, emp.client_id, True, today=date(2026, 5, 1))
    s.commit()
    assert la.credited(s, emp, "annual", 2026) == 3.0, "March, April and May"


def test_the_year_end_carries_over_to_the_limit_and_lapses_the_rest(tenant, s):
    emp = row(s, make_employee(tenant))
    emp.annual_leave_entitlement, emp.sick_leave_entitlement = 24.0, 12.0
    s.commit()
    la.set_accrual(s, emp.client_id, True, carry_annual=10, carry_sick=0, today=date(2026, 12, 1))
    s.add(models.DBLeaveRequest(client_id=emp.client_id, employee_id=emp.id, leave_type="annual",
                                start_date="2026-06-01", end_date="2026-06-04", days=4, status="approved"))
    s.commit()
    la.run_month(s, emp.client_id, date(2027, 1, 1))
    s.commit()
    # 24 earned, 4 taken: 20 left; 10 carry over, 10 lapse. Sick: 12 left, none carries.
    assert la.credited(s, emp, "annual", 2026) == 14.0, "24 credited less the 10 lapsed"
    ledger = {(r.leave_type, r.kind, r.period): r.days for r in s.query(models.DBLeaveLedger).filter(
        models.DBLeaveLedger.employee_id == emp.id, models.DBLeaveLedger.kind.in_(("lapse", "carry_forward")))}
    assert ledger == {("annual", "lapse", "2026"): -10.0, ("annual", "carry_forward", "2027"): 10.0, ("sick", "lapse", "2026"): -12.0}
    bal = leave_balance_for(s, emp, for_year=2027)
    assert bal["annual_total"] == 12.0, "10 carried over plus January's 2"


def test_leave_requests_are_checked_against_what_has_accrued(tenant, portal, s):
    e = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert tenant.put("/api/leave/accrual", json={"enabled": True}).status_code == 200
    assert tenant.put("/api/attendance/settings", json={"working_days": "1,2,3,4,5,6,7", "require_location": False}).status_code == 200
    portal.post("/api/employee/auth/login", json={"email": e["email"], "password": "EmpPass123"})
    have = portal.get("/api/employee/leave").json()["balance"]["annual_remaining"]
    assert 0 < have < 25, "less than the whole year's entitlement"
    res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-12-01", "end_date": "2026-12-25"})
    assert res.status_code == 400 and "remaining" in res.json()["detail"]


def test_settings_and_adjustments_through_the_api(tenant):
    e = make_employee(tenant)
    res = tenant.put("/api/leave/accrual", json={"enabled": True, "carry_max": {"annual": 15, "sick": 5}})
    assert res.status_code == 200 and res.json()["carry_max"] == {"annual": 15.0, "sick": 5.0}
    assert tenant.put("/api/leave/accrual", json={"carry_max": {"annual": -1}}).status_code == 400
    before = tenant.get("/api/employees/%d/leave-ledger" % e["id"]).json()["balance"]["annual_total"]
    assert tenant.post("/api/employees/%d/leave-ledger" % e["id"], json={"leave_type": "annual", "days": 2}).status_code == 400, "no reason"
    res = tenant.post("/api/employees/%d/leave-ledger" % e["id"], json={"leave_type": "annual", "days": 2, "note": "Worked a holiday"})
    assert res.status_code == 200
    ledger = tenant.get("/api/employees/%d/leave-ledger" % e["id"]).json()
    assert ledger["balance"]["annual_total"] == before + 2
    assert any(x["kind"] == "adjustment" and x["note"] == "Worked a holiday" for x in ledger["entries"])


def test_staff_cannot_change_accrual(tenant, portal):
    e = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": e["email"], "password": "EmpPass123"})
    assert portal.put("/api/leave/accrual", json={"enabled": True}).status_code in (401, 403)
    assert portal.post("/api/employees/%d/leave-ledger" % e["id"], json={"leave_type": "annual", "days": 30, "note": "mine"}).status_code in (401, 403)
