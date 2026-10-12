"""Departments are the Master's to set up and staff: create one, put people in
it, move them to another, take them out. Nobody else may."""
import pytest

import main
from app import models
from test_team import invite, set_their_password, sign_in_as


def dept(tenant, name):
    res = tenant.post("/api/departments", json={"name": name, "description": "", "color": "#ff0000", "icon": "building"})
    assert res.status_code == 200, res.text
    return res.json()


def person(tenant, first):
    res = tenant.post("/api/employees", json={"first_name": first, "last_name": "Test"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def members(tenant, dept_id):
    return {e["id"] for e in tenant.get(f"/api/departments/{dept_id}").json()["employees"]}


def test_a_business_starts_with_no_departments(tenant):
    assert tenant.get("/api/departments").json() == []


def test_the_master_adds_people_to_a_department(tenant):
    civil = dept(tenant, "Civil")
    a, b = person(tenant, "Asha"), person(tenant, "Bala")
    res = tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a, b]})
    assert res.status_code == 200, res.text
    assert res.json()["employee_count"] == 2
    assert members(tenant, civil["id"]) == {a, b}


def test_adding_somebody_to_another_department_moves_them(tenant):
    civil, roads = dept(tenant, "Civil"), dept(tenant, "Roads")
    a, b = person(tenant, "Asha"), person(tenant, "Bala")
    tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a, b]})
    tenant.post(f"/api/departments/{roads['id']}/employees", json={"employee_ids": [a]})
    assert members(tenant, civil["id"]) == {b}
    assert members(tenant, roads["id"]) == {a}
    # ...and back again
    tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a]})
    assert members(tenant, civil["id"]) == {a, b}
    assert members(tenant, roads["id"]) == set()


def test_the_master_takes_somebody_out_of_a_department(tenant):
    civil = dept(tenant, "Civil")
    a = person(tenant, "Asha")
    tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a]})
    assert tenant.delete(f"/api/departments/{civil['id']}/employees/{a}").status_code == 200
    assert members(tenant, civil["id"]) == set()
    assert tenant.get(f"/api/employees/{a}").json()["department_id"] is None
    # not in it any more, so a second removal is a 404
    assert tenant.delete(f"/api/departments/{civil['id']}/employees/{a}").status_code == 404


def test_an_unknown_employee_or_department_is_refused(tenant):
    civil = dept(tenant, "Civil")
    assert tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [999999]}).status_code == 404
    assert tenant.post("/api/departments/999999/employees", json={"employee_ids": [person(tenant, "A")]}).status_code == 404
    assert tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": []}).status_code == 400


def test_a_move_is_in_the_audit_log(tenant):
    civil, roads = dept(tenant, "Civil"), dept(tenant, "Roads")
    a = person(tenant, "Asha")
    tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a]})
    tenant.post(f"/api/departments/{roads['id']}/employees", json={"employee_ids": [a]})
    logs = [l["details"] for l in tenant.get("/api/audit-logs").json() if l["action"] == "employee_department_changed"]
    assert "Moved from Civil to Roads" in logs


def test_the_profile_form_can_still_move_somebody_for_the_master(tenant):
    civil = dept(tenant, "Civil")
    a = person(tenant, "Asha")
    assert tenant.put(f"/api/employees/{a}", json={"department_id": civil["id"]}).status_code == 200
    assert members(tenant, civil["id"]) == {a}


@pytest.fixture
def admin_and_ids(client, tenant):
    """A department and an employee made by the Master, then the browser
    handed to a team admin."""
    civil = dept(tenant, "Civil")
    roads = dept(tenant, "Roads")
    a = person(tenant, "Asha")
    tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a]})
    member, email = invite(tenant, role="admin")
    raw = set_their_password(member["id"])
    client.post("/api/client/reset-password", json={"token": raw, "password": "Colleague123"})
    sign_in_as(client, email)
    return client, civil["id"], roads["id"], a


def test_nobody_but_the_master_runs_departments(admin_and_ids):
    c, civil, roads, a = admin_and_ids
    body = {"name": "X", "description": "", "color": "#ff0000", "icon": "building"}
    assert c.post("/api/departments", json=body).status_code == 403
    assert c.put(f"/api/departments/{civil}", json=body).status_code == 403
    assert c.delete(f"/api/departments/{civil}").status_code == 403
    assert c.post(f"/api/departments/{roads}/employees", json={"employee_ids": [a]}).status_code == 403
    assert c.delete(f"/api/departments/{civil}/employees/{a}").status_code == 403
    # the side doors: the employee edit, a new employee, and a hire
    assert c.put(f"/api/employees/{a}", json={"department_id": roads}).status_code == 403
    assert c.post("/api/employees", json={"first_name": "B", "last_name": "C", "department_id": roads}).status_code == 403
    # ...while they can still read them, and edit a profile without moving it
    assert c.get("/api/departments").status_code == 200
    assert c.put(f"/api/employees/{a}", json={"job_title": "Engineer", "department_id": civil}).status_code == 200
    with main.SessionLocal() as db:
        assert db.query(models.DBEmployee).get(a).department_id == civil


def test_another_companys_department_cannot_be_used(tenant):
    a = person(tenant, "Asha")
    with main.SessionLocal() as db:
        other = models.DBClient(email="other@example.com", company_name="Other", is_active=True)
        db.add(other)
        db.flush()
        theirs = models.DBDepartment(client_id=other.id, name="Theirs")
        db.add(theirs)
        db.commit()
        theirs_id = theirs.id
    assert tenant.put(f"/api/employees/{a}", json={"department_id": theirs_id}).status_code == 404
    assert tenant.post(f"/api/departments/{theirs_id}/employees", json={"employee_ids": [a]}).status_code == 404


# --- deleting an employee ------------------------------------------------------

def test_the_master_deletes_an_employee(tenant):
    a = person(tenant, "Asha")
    civil = dept(tenant, "Civil")
    tenant.post(f"/api/departments/{civil['id']}/employees", json={"employee_ids": [a]})
    assert tenant.delete(f"/api/employees/{a}").status_code == 200
    assert tenant.get(f"/api/employees/{a}").status_code == 404
    assert members(tenant, civil["id"]) == set(), "they leave their department with the record"
    assert tenant.delete(f"/api/employees/{a}").status_code == 404
    logs = [l["details"] for l in tenant.get("/api/audit-logs").json() if l["action"] == "employee_deleted"]
    assert logs, "and it is written down"


def test_nobody_but_the_master_deletes_an_employee(admin_and_ids):
    c, _civil, _roads, a = admin_and_ids
    assert c.delete(f"/api/employees/{a}").status_code == 403
    with main.SessionLocal() as db:
        assert db.query(models.DBEmployee).get(a) is not None
