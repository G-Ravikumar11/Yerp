"""Only the Master changes what anybody may do."""
from app import models


def test_master_sees_every_permission_and_each_employee(tenant):
    r = tenant.post("/api/employees", json={"first_name": "Asha", "last_name": "Rao"})
    assert r.status_code == 200, r.text
    out = tenant.get("/api/master/access").json()
    from app.core.permissions import PERMISSION_KEYS
    assert {p["key"] for p in out["permissions"]} == PERMISSION_KEYS
    assert any(e["full_name"] == "Asha Rao" for e in out["employees"])


def test_master_can_change_a_role_any_time(tenant):
    emp = tenant.post("/api/employees", json={"first_name": "Asha", "last_name": "Rao"}).json()
    eid = emp.get("id") or emp.get("employee_pk")
    if eid is None:
        eid = tenant.get("/api/master/access").json()["employees"][0]["id"]
    for role in ("finance", "staff", "owner"):
        r = tenant.put("/api/employees/%d/permissions" % eid, json={"permission_role": role})
        assert r.status_code == 200, r.text
        assert r.json()["permission_role"] == role
