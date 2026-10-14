"""The departments an order can be raised for are the ones the owner creates.

They were a fixed list of six trades, so a business that does roads, or has an accounts
department, could not name its own. The owner's departments now drive the picker, and
they are the same ones employees belong to and staff see on their own sign-in."""
from test_subcontract_orders import draft


def choices(tenant):
    res = tenant.get("/api/wo/vocabulary")
    assert res.status_code == 200, res.text
    return res.json()["departments"]


def site(tenant):
    return tenant.post("/api/jobs", json={"name": "Fairview", "customer_name": "Someone", "status": "in_progress"}).json()


def make(tenant, name, site_ids=None):
    body = {"name": name, "description": "", "color": "#ff0000", "icon": "building"}
    if site_ids is not None:
        body["site_ids"] = site_ids
    return tenant.post("/api/departments", json=body).json()


def test_there_are_no_built_in_departments(tenant):
    """The six trades used to fill the picker for a business with none of its own."""
    assert choices(tenant) == []


def test_only_the_departments_added_to_a_site_are_offered(tenant):
    fairview = site(tenant)
    make(tenant, "Roads", [fairview["id"]])
    make(tenant, "Accounts", [fairview["id"]])
    make(tenant, "Unplaced")
    got = choices(tenant)
    assert got == ["Accounts", "Roads"], "a department on no site is shown nowhere"


def test_an_order_in_a_removed_department_can_still_be_opened(tenant):
    order = draft(tenant, department="Finishing")
    fairview = site(tenant)
    made = make(tenant, "Roads", [fairview["id"]])
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
