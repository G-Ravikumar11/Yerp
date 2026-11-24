"""A work order's department - and so its number series - is decided, not chosen: the department of whoever raises it.
An order the Master raises takes its kind of work's department, and with neither it is a general order (GEN)."""
from test_subcontract_orders import dept_work_type, draft, masters, sign_in, staff


def order_body(tenant, **over):
    unit, con, job = masters(tenant)
    body = {"business_unit_id": unit["id"], "contractor_id": con["id"], "job_id": job["id"], "subject": "Shuttering",
            "commencement_date": "2026-05-01", "completion_date": "2026-11-30"}
    body.update(over)
    return body


def test_ho_qs_raises_it_in_their_own_department_whatever_is_asked(tenant, portal):
    dept = tenant.post("/api/departments", json={"name": "Site QS", "description": "", "color": "#2255aa", "icon": "building"}).json()
    qs = staff(tenant, "ho_qs")
    assert tenant.put("/api/employees/%d" % qs["id"], json={"department_id": dept["id"]}).status_code == 200
    body = order_body(tenant, department="Electrical")          # asked for another: not taken
    sign_in(portal, qs)
    res = portal.post("/api/wo/orders", json=body)
    assert res.status_code == 200, res.text
    order = res.json()["order"]
    assert order["department"] == "Site QS" and order["wo_number"].split("/")[2] == "SITEQS"


def test_the_masters_order_takes_its_kind_of_works_department_else_general(tenant):
    with_type = tenant.post("/api/wo/orders", json=order_body(tenant, work_type=dept_work_type(tenant, "Roads"))).json()["order"]
    assert with_type["department"] == "Roads"
    plain = tenant.post("/api/wo/orders", json=order_body(tenant, department="Roads")).json()["order"]
    assert plain["department"] == "" and plain["wo_number"].split("/")[2] == "GEN"


def test_a_copy_is_raised_by_whoever_copies_it(tenant, portal):
    original = draft(tenant, department="Roads")
    dept = tenant.post("/api/departments", json={"name": "Site QS", "description": "", "color": "#2255aa", "icon": "building"}).json()
    qs = staff(tenant, "ho_qs")
    tenant.put("/api/employees/%d" % qs["id"], json={"department_id": dept["id"]})
    sign_in(portal, qs)
    copy = portal.post("/api/wo/orders/%d/copy" % original["id"], json={})
    assert copy.status_code == 200, copy.text
    assert (copy.json().get("order") or copy.json())["department"] == "Site QS"
