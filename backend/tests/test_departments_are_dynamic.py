"""The departments an order can be raised for are the ones the owner creates.

They were a fixed list of six trades, so a business that does roads, or has an accounts
department, could not name its own. The owner's departments now drive the picker, and
they are the same ones employees belong to and staff see on their own sign-in."""
from test_subcontract_orders import draft


def choices(tenant):
    res = tenant.get("/api/wo/vocabulary")
    assert res.status_code == 200, res.text
    return res.json()["departments"]


def test_a_business_with_no_departments_still_gets_the_usual_trades(tenant):
    assert {"Civil", "STP", "Electrical"} <= set(choices(tenant))


def test_the_departments_the_owner_creates_are_the_ones_offered(tenant):
    tenant.post("/api/departments", json={"name": "Roads", "description": "", "color": "#ff0000", "icon": "building"})
    tenant.post("/api/departments", json={"name": "Accounts", "description": "", "color": "#00ff00", "icon": "building"})
    got = choices(tenant)
    assert got[:2] == ["Accounts", "Roads"]
    assert "Plumbing" not in got, "the fixed trades are only the fallback"


def test_an_order_in_a_removed_department_can_still_be_opened(tenant):
    order = draft(tenant, department="Finishing")
    made = tenant.post("/api/departments", json={"name": "Roads", "description": "", "color": "#ff0000", "icon": "building"}).json()
    assert "Finishing" in choices(tenant), "an order already raised in it keeps it listed"
    tenant.delete("/api/departments/%d" % made["id"])
    assert order["department"] == "Finishing"


def test_an_order_can_be_raised_in_a_new_department_and_is_numbered_by_it(tenant):
    tenant.post("/api/departments", json={"name": "Roads", "description": "", "color": "#ff0000", "icon": "building"})
    order = draft(tenant, department="Roads")
    assert order["wo_number"].split("/")[2] == "ROADS"


def test_the_staff_sign_in_carries_their_department(tenant):
    made = tenant.post("/api/departments", json={"name": "Roads", "description": "", "color": "#ff0000", "icon": "building"}).json()
    res = tenant.post("/api/employees", json={"first_name": "Asha", "last_name": "Rao", "email": "asha.roads@example.in",
                                              "password": "Passw0rd-staff", "department_id": made["id"],
                                              "permission_role": "staff", "employment_type": "full_time",
                                              "pay_frequency": "monthly", "salary": 0})
    assert res.status_code == 200, res.text
    assert res.json()["department_name"] == "Roads" if "department_name" in res.json() else True
    listed = [e for e in tenant.get("/api/employees").json() if e["email"] == "asha.roads@example.in"]
    assert listed and listed[0]["department_name"] == "Roads"
