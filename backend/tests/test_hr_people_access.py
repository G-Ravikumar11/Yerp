"""What a signed-in HR login can do in the People portal, and what stays the Master's."""
import uuid

import pytest
from fastapi.testclient import TestClient

import main
from conftest import make_employee

PASSWORD = "Crew1234"


@pytest.fixture
def logins(tenant):
    tag = uuid.uuid4().hex[:6]
    out = {}
    for role in ("hr", "staff"):
        email = "%s-%s@example.com" % (role, tag)
        emp = make_employee(tenant, email=email, password=PASSWORD, permission_role=role, status="active")
        c = TestClient(main.app)
        c.__enter__()
        assert c.post("/api/employee/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        out[role] = c
        out[role + "_id"] = emp["id"]
    out["target"] = make_employee(tenant, email="tg-%s@example.com" % tag, password=PASSWORD, status="active")
    yield out
    for role in ("hr", "staff"):
        out[role].__exit__(None, None, None)


def test_hr_reads_and_edits_people(logins):
    hr, target = logins["hr"], logins["target"]
    assert hr.get("/api/employees").status_code == 200
    assert hr.get("/api/employees/%d" % target["id"]).status_code == 200
    assert hr.put("/api/employees/%d" % target["id"], json={"job_title": "Clerk"}).status_code == 200
    assert hr.get("/api/payslips").status_code == 200
    assert hr.get("/api/attendance").status_code == 200
    assert hr.get("/api/leave/requests").status_code == 200
    assert hr.get("/api/departments").status_code == 200


def test_staff_without_the_rights_are_refused(logins):
    staff = logins["staff"]
    for url in ("/api/employees", "/api/payslips", "/api/attendance", "/api/leave/requests"):
        assert staff.get(url).status_code == 403, url


def test_hr_has_the_whole_people_portal(logins, tenant):
    hr, target = logins["hr"], logins["target"]
    uid = target["id"]
    # access, designation and the reporting line
    assert hr.put("/api/employees/%d/permissions" % uid, json={"permission_role": "accounts"}).status_code == 200
    assert hr.put("/api/employees/%d" % uid, json={"permission_role": "stores"}).status_code == 200
    assert hr.put("/api/employees/%d" % uid, json={"role": "hr"}).status_code == 200
    # departments
    dept = hr.post("/api/departments", json={"name": "Planning-" + uuid.uuid4().hex[:4]})
    assert dept.status_code == 200, dept.text
    did = dept.json()["id"]
    assert hr.post("/api/departments/%d/employees" % did, json={"employee_ids": [uid]}).status_code == 200
    assert hr.delete("/api/departments/%d" % did).status_code == 200
    # passwords, stages and delete
    assert hr.put("/api/employees/%d/set-password" % uid, json={"password": "Another1234"}).status_code == 200
    assert hr.post("/api/employees/%d/offboard" % uid).status_code == 200
    assert hr.delete("/api/employees/%d" % uid).status_code == 200


def test_hr_can_delete_leave_and_timesheets_but_not_other_records(logins):
    hr = logins["hr"]
    assert hr.delete("/api/master/leave/999999").status_code == 404           # allowed in, nothing there
    assert hr.delete("/api/master/attendance/999999").status_code == 404
    assert hr.delete("/api/master/supplier_bill/1").status_code in (401, 403)   # not a People record
    assert logins["staff"].delete("/api/master/leave/1").status_code == 403


def test_hr_cannot_reach_past_itself_to_the_master(logins, tenant):
    hr, target = logins["hr"], logins["target"]
    uid = target["id"]
    assert hr.put("/api/employees/%d/permissions" % uid, json={"permission_role": "owner"}).status_code == 403
    assert hr.put("/api/employees/%d" % uid, json={"permission_role": "owner"}).status_code == 403
    assert hr.put("/api/employees/%d" % uid, json={"extra_permissions": "store.admin"}).status_code == 403
    # the Master's own employee record is out of reach
    master = make_employee(tenant, email="m-%s@example.com" % uuid.uuid4().hex[:6], permission_role="owner")
    mid = master["id"]
    assert hr.put("/api/employees/%d" % mid, json={"job_title": "x"}).status_code == 403
    assert hr.put("/api/employees/%d/set-password" % mid, json={"password": "Another1234"}).status_code == 403
    assert hr.delete("/api/employees/%d" % mid).status_code == 403


def test_staff_without_people_manage_get_none_of_it(logins):
    staff, uid = logins["staff"], logins["target"]["id"]
    assert staff.put("/api/employees/%d/permissions" % uid, json={"permission_role": "accounts"}).status_code == 403
    assert staff.delete("/api/employees/%d" % uid).status_code == 403
    assert staff.post("/api/departments", json={"name": "X"}).status_code == 403


def test_a_staff_login_is_never_the_master(logins):
    from app.core.auth import require_owner
    from fastapi import HTTPException

    class Req:
        session = {"employee_id": 1}

    with pytest.raises(HTTPException) as err:
        require_owner(Req(), None)
    assert err.value.status_code == 403


# --- payroll and the people records are HR's and the Master's alone ---------------------------------------------

def test_no_other_role_holds_the_payroll_or_people_rights():
    from app.core.permissions import ROLE_PERMISSIONS, permissions_for

    class Person:
        def __init__(self, role, extra=""):
            self.permission_role, self.extra_permissions, self.denied_permissions = role, extra, ""

    both = {"payroll.manage", "people.manage"}
    assert {r for r, rights in ROLE_PERMISSIONS.items() if both & rights} == {"hr", "owner"}
    # Ticked by hand for somebody on any other level: not honoured.
    for role in ("staff", "accounts", "project_manager", "head_projects", "ho_qs", "store_incharge"):
        assert not both & permissions_for(Person(role, extra="payroll.manage,people.manage")), role
    assert both <= permissions_for(Person("hr")) and both <= permissions_for(Person("owner"))


def test_the_master_cannot_hand_payroll_to_anyone_but_hr(tenant):
    email = "pm-%s@example.com" % uuid.uuid4().hex[:6]
    emp = make_employee(tenant, email=email, password=PASSWORD, permission_role="accounts", status="active")
    assert tenant.put("/api/employees/%d" % emp["id"], json={"extra_permissions": "payroll.manage,people.manage"}).status_code == 200
    c = TestClient(main.app)
    c.__enter__()
    try:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
        assert c.get("/api/payslips").status_code == 403
        assert c.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-09-01", "period_end": "2026-09-30",
                                             "pay_date": "2026-09-30", "basic_salary": 1}).status_code == 403
        assert c.get("/api/employees").status_code == 403
        assert c.get("/api/payslips/register.xlsx").status_code == 403
    finally:
        c.__exit__(None, None, None)


def test_hr_and_the_master_change_payslips(logins, tenant):
    hr, target = logins["hr"], logins["target"]
    body = {"employee_id": target["id"], "period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30", "basic_salary": 1000}
    made = hr.post("/api/payslips", json=body)
    assert made.status_code == 200, made.text
    pid = made.json()["id"]
    assert hr.put("/api/payslips/%d" % pid, json={"bonus": 50}).status_code == 200
    assert tenant.put("/api/payslips/%d" % pid, json={"bonus": 75}).status_code == 200      # the Master
    assert hr.delete("/api/payslips/%d" % pid).status_code == 200
    assert logins["staff"].put("/api/payslips/%d" % pid, json={"bonus": 1}).status_code == 403
