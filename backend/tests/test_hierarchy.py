"""Employee seniority levels, reporting roles and reporting-line integrity."""
import pytest

from conftest import make_employee


def test_level_catalogue_is_served(tenant):
    data = tenant.get("/api/hr/levels").json()
    codes = [l["code"] for l in data["levels"]]
    assert codes == ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
    roles = {r["code"]: r for r in data["roles"]}
    assert roles["project_manager"]["level"] == "L4"
    assert roles["store_assistant"]["reports_to"] == "store_executive"


def test_every_role_has_a_real_level_parent_and_access_level(tenant):
    from app.core.permissions import EMPLOYEE_ROLES, LEVEL_RANK, ROLE_PERMISSIONS
    by_code = {r["code"]: r for r in EMPLOYEE_ROLES}
    for r in EMPLOYEE_ROLES:
        assert r["level"] in LEVEL_RANK and r["access"] in ROLE_PERMISSIONS
        if r["reports_to"]:
            assert LEVEL_RANK[by_code[r["reports_to"]]["level"]] >= LEVEL_RANK[r["level"]]
        else:
            assert r["code"] == "hod"


def test_level_and_role_round_trip(tenant):
    emp = make_employee(tenant, level="L4", role="project_manager")
    assert emp["level"] == "L4"
    assert emp["role"] == "project_manager"
    fetched = tenant.get(f"/api/employees/{emp['id']}").json()
    assert fetched["level"] == "L4"
    assert fetched["role"] == "project_manager"


def test_level_is_normalised_to_upper_case(tenant):
    emp = make_employee(tenant, level="l6")
    assert emp["level"] == "L6"


@pytest.mark.parametrize("bad", ["L0", "L99", "Senior", "42"])
def test_unknown_level_rejected(tenant, bad):
    res = tenant.post("/api/employees", json={
        "first_name": "A", "last_name": "B", "email": f"lvl-{bad}@example.com", "level": bad,
    })
    assert res.status_code == 400
    assert "Unknown level" in res.json()["detail"]


def test_unknown_role_rejected(tenant):
    res = tenant.post("/api/employees", json={
        "first_name": "A", "last_name": "B", "email": "role@example.com", "role": "supreme_leader",
    })
    assert res.status_code == 400
    assert "Unknown role" in res.json()["detail"]


def test_level_can_be_changed_and_validated_on_update(tenant):
    emp = make_employee(tenant, level="L2")
    assert tenant.put(f"/api/employees/{emp['id']}", json={"level": "L5"}).status_code == 200
    assert tenant.get(f"/api/employees/{emp['id']}").json()["level"] == "L5"
    # The update path used to accept anything via a blind setattr.
    assert tenant.put(f"/api/employees/{emp['id']}", json={"level": "L42"}).status_code == 400


# --- reporting line integrity ----------------------------------------------

def test_reporting_line_builds_a_tree(tenant):
    boss = make_employee(tenant, level="L1")
    lead = make_employee(tenant, level="L4", role="project_manager", reports_to=boss["id"])
    junior = make_employee(tenant, level="L6", reports_to=lead["id"])

    chart = tenant.get("/api/org-chart").json()
    roots = {r["id"]: r for r in chart["roots"]}
    assert boss["id"] in roots
    lead_node = roots[boss["id"]]["children"][0]
    assert lead_node["id"] == lead["id"]
    assert lead_node["level"] == "L4"
    assert lead_node["children"][0]["id"] == junior["id"]


def test_role_fills_in_its_level_when_none_is_given(tenant):
    assert make_employee(tenant, role="site_engineer")["level"] == "L6"


def test_manager_cannot_sit_below_the_employee(tenant):
    junior = make_employee(tenant, level="L7")
    res = tenant.post("/api/employees", json={
        "first_name": "A", "last_name": "B", "email": "senior@example.com",
        "level": "L4", "reports_to": junior["id"],
    })
    assert res.status_code == 400
    assert "same level or higher" in res.json()["detail"]


def test_employee_cannot_report_to_themselves(tenant):
    emp = make_employee(tenant)
    res = tenant.put(f"/api/employees/{emp['id']}", json={"reports_to": emp["id"]})
    assert res.status_code == 400
    assert "themselves" in res.json()["detail"]


def test_direct_reporting_loop_is_rejected(tenant):
    """A -> B and B -> A would make the org chart renderer recurse forever."""
    boss = make_employee(tenant)
    report = make_employee(tenant, reports_to=boss["id"])
    res = tenant.put(f"/api/employees/{boss['id']}", json={"reports_to": report["id"]})
    assert res.status_code == 400
    assert "loop" in res.json()["detail"]


def test_indirect_reporting_loop_is_rejected(tenant):
    a = make_employee(tenant)
    b = make_employee(tenant, reports_to=a["id"])
    c = make_employee(tenant, reports_to=b["id"])
    # a -> c would close the ring a -> c -> b -> a
    res = tenant.put(f"/api/employees/{a['id']}", json={"reports_to": c["id"]})
    assert res.status_code == 400
    assert "loop" in res.json()["detail"]


def test_manager_must_belong_to_the_same_tenant(client, tenant):
    outsider = make_employee(tenant)
    client.post("/api/client/logout")
    client.post("/api/client/register", json={"email": "other-org@example.com", "password": "Passw0rdTest"})
    client.post("/api/client/login", json={"email": "other-org@example.com", "password": "Passw0rdTest"})
    res = client.post("/api/employees", json={
        "first_name": "X", "last_name": "Y", "email": "x@other.com", "reports_to": outsider["id"],
    })
    assert res.status_code == 400
    assert "Manager not found" in res.json()["detail"]


def test_level_appears_on_the_payslip(tenant):
    emp = make_employee(tenant, level="L5", salary=1000.0)
    ps = tenant.post("/api/payslips", json={
        "employee_id": emp["id"], "period_start": "2026-01-01",
        "period_end": "2026-01-31", "pay_date": "2026-02-01",
    }).json()
    detail = tenant.get(f"/api/payslips/{ps['id']}").json()
    assert detail["employee"]["level"] == "L5"


FIXED = ["hod", "md", "coordinator", "ho_planning_head", "ho_qs", "store_coordinator"]


def test_fixed_roles_are_not_offered_in_the_picker(tenant):
    offered = {r["code"] for r in tenant.get("/api/hr/levels").json()["roles"]}
    assert not offered & set(FIXED)
    assert "project_manager" in offered


@pytest.mark.parametrize("role", FIXED)
def test_fixed_roles_cannot_be_given_to_anyone(tenant, role):
    res = tenant.post("/api/employees", json={
        "first_name": "A", "last_name": "B", "email": f"{role}@example.com", "role": role})
    assert res.status_code == 403
    emp = make_employee(tenant)
    res = tenant.put(f"/api/employees/{emp['id']}", json={"role": role})
    assert res.status_code == 403
    assert tenant.get(f"/api/employees/{emp['id']}").json()["role"] == ""


def test_the_master_can_set_and_resend_the_reporting_line(tenant):
    boss = make_employee(tenant, level="L4")
    emp = make_employee(tenant, level="L6", reports_to=boss["id"])
    assert tenant.get(f"/api/employees/{emp['id']}").json()["reports_to"] == boss["id"]
    # An unchanged line may be sent back untouched (the profile form does); moving it is the Master's.
    assert tenant.put(f"/api/employees/{emp['id']}", json={"reports_to": boss["id"]}).status_code == 200


def test_the_reporting_line_follows_the_role(tenant):
    # Holders of a fixed role cannot be created through the API, so the boss is made a Project Manager.
    pm = make_employee(tenant, role="project_manager")
    director = make_employee(tenant, role="site_director")
    assert director["reports_to"] == pm["id"]
    engineer = make_employee(tenant, role="site_engineer")      # the role above, Site Director, is held
    assert engineer["reports_to"] == director["id"]


def test_the_line_climbs_when_the_role_above_is_empty(tenant):
    pm = make_employee(tenant, role="project_manager")
    assistant = make_employee(tenant, role="store_assistant")   # Store Executive is empty, so Project Manager
    assert assistant["reports_to"] == pm["id"]


def test_a_new_role_moves_the_line_but_a_manual_one_wins(tenant):
    pm = make_employee(tenant, role="project_manager")
    director = make_employee(tenant, role="site_director")
    other = make_employee(tenant, level="L2")
    emp = make_employee(tenant, role="site_director")
    assert tenant.put(f"/api/employees/{emp['id']}", json={"role": "site_engineer"}).status_code == 200
    assert tenant.get(f"/api/employees/{emp['id']}").json()["reports_to"] == director["id"]
    assert tenant.put(f"/api/employees/{emp['id']}", json={"role": "engineer", "reports_to": other["id"]}).status_code == 200
    assert tenant.get(f"/api/employees/{emp['id']}").json()["reports_to"] == other["id"]
