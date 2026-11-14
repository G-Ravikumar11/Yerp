"""The payroll month: Draft, Approved, Paid, Locked; a locked month is frozen; only the Master reopens it, with a reason."""
import pytest

from app import db as database
from app import models
from conftest import make_employee

MONTH = "2026-09"
SLIP = {"period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}


def slip(tenant, emp, **extra):
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], **SLIP, **extra})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def month(tenant, action, **body):
    return tenant.post("/api/payroll/month/" + action, json={"month": MONTH, **body})


def statuses(tenant):
    return {m["month"]: m["status"] for m in tenant.get("/api/payroll/months").json()}


@pytest.fixture
def locked(tenant):
    emp = make_employee(tenant)
    sid = slip(tenant, emp)
    for action in ("approve", "pay", "lock"):
        assert month(tenant, action).status_code == 200
    return emp, sid


def test_a_month_walks_draft_approved_paid_locked(tenant):
    emp = make_employee(tenant)
    sid = slip(tenant, emp)
    assert statuses(tenant)[MONTH] == "Draft"
    for action, expected in (("approve", "Approved"), ("pay", "Paid"), ("lock", "Locked")):
        res = month(tenant, action)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == expected and statuses(tenant)[MONTH] == expected
    assert tenant.get("/api/payslips/%d" % sid).json()["status"] == "Paid", "paying the month pays its payslips"
    assert tenant.get("/api/payroll/month", params={"month": MONTH}).json()["payslips"] == 1


def test_a_step_cannot_be_skipped_or_repeated(tenant):
    slip(tenant, make_employee(tenant))
    assert month(tenant, "pay").status_code == 409, "not approved yet"
    assert month(tenant, "lock").status_code == 409, "not paid yet"
    assert month(tenant, "approve").status_code == 200
    assert month(tenant, "approve").status_code == 409, "already approved"
    assert month(tenant, "lock").status_code == 409


def test_an_empty_month_cannot_be_approved_and_the_month_must_be_a_month(tenant):
    assert month(tenant, "approve").status_code == 400
    for bad in ("", "2026-13", "October", "2026-9"):
        assert tenant.post("/api/payroll/month/approve", json={"month": bad}).status_code == 400, bad


def test_a_locked_month_refuses_every_change(tenant, locked):
    emp, sid = locked
    other = make_employee(tenant)
    refused = [
        tenant.post("/api/payslips", json={"employee_id": other["id"], **SLIP}),
        tenant.put("/api/payslips/%d" % sid, json={"bonus": 100}),
        tenant.delete("/api/payslips/%d?force=true" % sid),
        tenant.post("/api/payroll/run", json={**SLIP}),
        tenant.post("/api/payslips/%d/unmark-paid" % sid),
        tenant.post("/api/payslips/%d/mark-paid" % sid),
    ]
    assert [r.status_code for r in refused] == [409] * 6, [r.text for r in refused]
    assert "locked" in refused[0].json()["detail"].lower()
    assert tenant.get("/api/payslips/%d" % sid).json()["status"] == "Paid", "nothing changed"


def test_moving_a_payslip_into_a_locked_month_is_refused(tenant, locked):
    other = make_employee(tenant)
    oct_id = tenant.post("/api/payslips", json={"employee_id": other["id"], "period_start": "2026-10-01",
                                                "period_end": "2026-10-31", "pay_date": "2026-10-31"}).json()["id"]
    res = tenant.put("/api/payslips/%d" % oct_id, json={"period_start": "2026-09-01", "period_end": "2026-09-30"})
    assert res.status_code == 409


def test_other_months_are_not_affected_by_a_lock(tenant, locked):
    other = make_employee(tenant)
    res = tenant.post("/api/payslips", json={"employee_id": other["id"], "period_start": "2026-10-01",
                                             "period_end": "2026-10-31", "pay_date": "2026-10-31"})
    assert res.status_code == 200


def test_the_automatic_run_leaves_a_locked_month_alone(tenant, locked):
    from app.services.payroll import generate_payroll
    s = database.SessionLocal()
    try:
        client_id = s.query(models.DBPayrollMonth).order_by(models.DBPayrollMonth.id.desc()).first().client_id   # this test's company, the newest
        with pytest.raises(Exception) as caught:
            generate_payroll(s, client_id, SLIP["period_start"], SLIP["period_end"], SLIP["pay_date"])
        assert getattr(caught.value, "status_code", None) == 409
    finally:
        s.rollback()
        s.close()


def test_reopen_needs_a_reason_and_records_it(tenant, locked):
    emp, sid = locked
    assert month(tenant, "reopen").status_code == 400, "no reason"
    assert month(tenant, "reopen", reopen_reason="  ").status_code == 400
    assert month(tenant, "reopen", reopen_reason="no").status_code == 400, "too short to be a reason"
    res = month(tenant, "reopen", reopen_reason="Wrong PF on two payslips")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Paid" and body["reopen_reason"] == "Wrong PF on two payslips" and body["reopened_by"] == "Master"
    # open again: a change goes through, and it can be locked once more
    assert tenant.post("/api/payslips/%d/unmark-paid" % sid).status_code == 200
    assert month(tenant, "reopen", reopen_reason="again please").status_code == 409, "not locked any more"


def test_reopen_is_in_the_audit_log(tenant, locked):
    s = database.SessionLocal()
    try:
        before = s.query(models.DBAuditLog).count()
    finally:
        s.close()
    month(tenant, "reopen", reopen_reason="Bank returned two transfers")
    s = database.SessionLocal()
    try:
        rows = s.query(models.DBAuditLog).order_by(models.DBAuditLog.id).offset(before).all()
        assert [r.action for r in rows] == ["payroll_month_reopened"]
        assert rows[0].entity_name == MONTH and rows[0].user_name == "Master"
        assert "Bank returned two transfers" in rows[0].details and "Master" in rows[0].details
    finally:
        s.close()


def test_only_the_master_reopens(tenant, portal, locked):
    hr = make_employee(tenant, password="EmpPass123", permission_role="hr")
    tenant.put("/api/employees/%d" % hr["id"], json={"status": "active"})
    assert portal.post("/api/employee/auth/login", json={"email": hr["email"], "password": "EmpPass123"}).status_code == 200
    # HR may read the month and move it forward ...
    assert portal.get("/api/payroll/months").status_code == 200
    # ... but not unlock it.
    res = portal.post("/api/payroll/month/reopen", json={"month": MONTH, "reopen_reason": "I would like to"})
    assert res.status_code == 403
    assert statuses(tenant)[MONTH] == "Locked"


def test_people_without_payroll_rights_cannot_touch_the_month(tenant, portal, locked):
    plain = make_employee(tenant, password="EmpPass123")
    tenant.put("/api/employees/%d" % plain["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": plain["email"], "password": "EmpPass123"})
    for path, body in (("approve", {}), ("pay", {}), ("lock", {}), ("reopen", {"reopen_reason": "because"})):
        assert portal.post("/api/payroll/month/" + path, json={"month": MONTH, **body}).status_code in (401, 403)
    assert portal.get("/api/payroll/months").status_code in (401, 403)


def test_one_company_cannot_move_anothers_month(tenant, second_tenant):
    slip(tenant, make_employee(tenant))
    assert second_tenant.post("/api/payroll/month/approve", json={"month": MONTH}).status_code == 400, "they have no payslips for it"
    assert statuses(tenant)[MONTH] == "Draft"


def test_a_payslip_says_which_month_it_is_in_and_the_list_says_whether_that_is_locked(tenant, locked):
    emp, sid = locked
    assert tenant.get("/api/payslips/%d" % sid).json()["month"] == MONTH
    row = [p for p in tenant.get("/api/payslips").json() if p["id"] == sid][0]
    assert (row["month"], row["month_status"]) == (MONTH, "Locked")


def test_an_employee_with_payslips_in_a_locked_month_cannot_be_deleted(tenant, locked):
    emp, sid = locked
    res = tenant.delete("/api/employees/%d" % emp["id"])
    assert res.status_code == 409 and "locked" in res.json()["detail"].lower()
    assert tenant.get("/api/payslips/%d" % sid).status_code == 200
    month(tenant, "reopen", reopen_reason="Removing a duplicate person")
    assert tenant.delete("/api/employees/%d" % emp["id"]).status_code == 200


def test_the_payslip_list_carries_the_statutory_breakdown(tenant):
    emp = make_employee(tenant, salary=18000.0, tax_rate=0.0)
    sid = slip(tenant, emp)
    row = [p for p in tenant.get("/api/payslips").json() if p["id"] == sid][0]
    full = tenant.get("/api/payslips/%d" % sid).json()
    assert row["employee_pf"] == full["retirement"] == 864.0
    assert row["employer_pf"] == round(row["employer_epf"] + row["employer_eps"], 2) == 864.0
    assert row["employee_esi"] == full["insurance"] and row["employer_esi"] == full["employer_esi"]
    assert row["professional_tax"] == full["professional_tax"]
    assert row["working_days"] == 22 and row["paid_days"] == 22 and row["lop_days"] == 0
