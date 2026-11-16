"""A department can be limited to the sites it operates on.

Same rule as staff and sites: a department with no sites chosen runs on every
site, so nothing changes until the owner narrows one.
"""


def make_job(tenant, name):
    return tenant.post("/api/jobs", json={
        "name": name, "customer_name": "Someone", "status": "in_progress"}).json()


def make_dept(tenant, name, site_ids=None):
    body = {"name": name, "description": "", "color": "#ff0000", "icon": "building"}
    if site_ids is not None:
        body["site_ids"] = site_ids
    res = tenant.post("/api/departments", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def names_on(tenant, site_id):
    res = tenant.get("/api/departments", params={"site_id": site_id})
    assert res.status_code == 200, res.text
    return {d["name"] for d in res.json()}


def test_a_department_on_no_site_is_on_none(tenant):
    dept = make_dept(tenant, "Roads")
    assert dept["site_ids"] == []
    site = make_job(tenant, "Fairview")
    assert names_on(tenant, site["id"]) == set()


def test_a_department_appears_only_on_the_sites_it_is_added_to(tenant):
    a, b = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    make_dept(tenant, "Roads", [a["id"]])
    make_dept(tenant, "Accounts", [a["id"], b["id"]])
    make_dept(tenant, "Unplaced")
    assert names_on(tenant, a["id"]) == {"Roads", "Accounts"}
    assert names_on(tenant, b["id"]) == {"Accounts"}


def test_the_sites_can_be_changed_and_cleared(tenant):
    a, b = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    dept = make_dept(tenant, "Roads", [a["id"]])
    body = {"name": "Roads", "description": "", "color": "#ff0000", "icon": "building"}
    moved = tenant.put("/api/departments/%d" % dept["id"], json={**body, "site_ids": [b["id"]]}).json()
    assert moved["site_ids"] == [b["id"]]
    # Leaving site_ids out is an edit to something else: the sites stay.
    kept = tenant.put("/api/departments/%d" % dept["id"], json=body).json()
    assert kept["site_ids"] == [b["id"]]
    cleared = tenant.put("/api/departments/%d" % dept["id"], json={**body, "site_ids": []}).json()
    assert cleared["site_ids"] == []
    assert names_on(tenant, a["id"]) == set() and names_on(tenant, b["id"]) == set()


def test_the_list_carries_each_departments_sites(tenant):
    a = make_job(tenant, "Fairview")
    make_dept(tenant, "Roads", [a["id"]])
    got = {d["name"]: d for d in tenant.get("/api/departments").json()}
    assert got["Roads"]["site_ids"] == [a["id"]]


def test_a_site_that_is_not_theirs_is_ignored(tenant):
    dept = make_dept(tenant, "Roads", [987654])
    assert dept["site_ids"] == []


def test_work_orders_are_told_which_sites_each_department_is_on(tenant):
    a = make_job(tenant, "Fairview")
    make_dept(tenant, "Roads", [a["id"]])
    make_dept(tenant, "Unplaced")
    vocab = tenant.get("/api/wo/vocabulary").json()
    assert vocab["department_sites"] == {"Roads": [a["id"]]}
    assert vocab["departments"] == ["Roads"]


def test_deleting_a_department_takes_its_sites_with_it(tenant):
    a = make_job(tenant, "Fairview")
    dept = make_dept(tenant, "Roads", [a["id"]])
    assert tenant.delete("/api/departments/%d" % dept["id"]).status_code == 200
    again = make_dept(tenant, "Roads")
    assert again["site_ids"] == []


def test_a_new_starter_puts_their_department_on_their_site(tenant):
    """HR types a department that already exists on another site and gives the person a different site: the department
    is then listed on the person's site too, and the list says which sites each person works on."""
    from conftest import make_employee
    iconica, arsha = make_job(tenant, "Iconica"), make_job(tenant, "Vision Arsha")
    civil = make_dept(tenant, "Civil", [arsha["id"]])
    emp = make_employee(tenant, department_id=civil["id"], site_ids=[iconica["id"]])
    assert names_on(tenant, iconica["id"]) == {"Civil"}
    assert names_on(tenant, arsha["id"]) == {"Civil"}       # kept where it was
    row = next(e for e in tenant.get("/api/employees").json() if e["id"] == emp["id"])
    assert row["site_ids"] == [iconica["id"]]


def test_changing_a_persons_site_brings_their_department_along(tenant):
    from conftest import make_employee
    a, b = make_job(tenant, "Fairview"), make_job(tenant, "Riverside")
    roads = make_dept(tenant, "Roads", [a["id"]])
    emp = make_employee(tenant, department_id=roads["id"])
    assert tenant.put("/api/employees/%d/permissions" % emp["id"],
                      json={"permission_role": "staff", "site_ids": [b["id"]]}).status_code == 200
    assert names_on(tenant, b["id"]) == {"Roads"}


def test_somebody_on_every_site_adds_no_site(tenant):
    from conftest import make_employee
    a = make_job(tenant, "Fairview")
    roads = make_dept(tenant, "Roads")
    make_employee(tenant, department_id=roads["id"])
    assert names_on(tenant, a["id"]) == set()
