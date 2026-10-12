"""The Master moves an employee between onboarding, offboarding and terminated; the status follows."""
from test_department_members import person


def status(tenant, emp_id):
    return tenant.get(f"/api/employees/{emp_id}").json()["status"]


def test_the_master_changes_the_status_each_way(tenant):
    emp = person(tenant, "Stage")
    assert tenant.post(f"/api/employees/{emp}/offboard").json()["status"] == "offboarding"
    assert status(tenant, emp) == "offboarding"
    assert tenant.post(f"/api/employees/{emp}/onboard").json()["status"] == "onboarding"
    assert status(tenant, emp) == "onboarding"
    assert tenant.post(f"/api/employees/{emp}/terminate").json()["status"] == "terminated"
    assert status(tenant, emp) == "terminated"


def test_an_unknown_employee_is_not_found(tenant):
    assert tenant.post("/api/employees/999999/terminate").status_code == 404
