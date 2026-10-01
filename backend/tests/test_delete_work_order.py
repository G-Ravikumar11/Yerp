"""Deleting a work order: the owner's alone, and complete - the order and everything
that hangs off it go from every screen. Money behind it is the one thing that stops it."""
from conftest import make_employee
from test_subcontractor_bills import live_order, measure, book, pay_the_advance

PASSWORD = "Crew1234"


def raise_a_bill(tenant, order):
    item = book(tenant, order["id"])["lines"][0]
    measure(tenant, order["id"], item["item_id"], 10)
    res = tenant.post("/api/sub-bills", json={"order_id": order["id"]})
    assert res.status_code == 200, res.text
    return res.json()["bill"] if "bill" in res.json() else res.json()


def test_a_draft_is_deleted_and_is_gone_from_the_list(tenant):
    from test_subcontract_orders import priced
    order = priced(tenant)
    assert tenant.get("/api/wo/orders/%d/delete-preview" % order["id"]).json()["can_delete"] is True
    res = tenant.delete("/api/wo/orders/%d" % order["id"])
    assert res.status_code == 200, res.text
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404
    assert order["id"] not in [o["id"] for o in tenant.get("/api/wo/orders").json()["orders"]]


def test_an_approved_order_goes_with_its_measurements_and_bills(tenant):
    order = live_order(tenant, pay_advance=False)
    bill = raise_a_bill(tenant, order)
    prev = tenant.get("/api/wo/orders/%d/delete-preview" % order["id"]).json()
    assert prev["can_delete"] and prev["counts"]["measurements"] >= 1 and prev["counts"]["bills"] == 1
    assert tenant.delete("/api/wo/orders/%d" % order["id"]).status_code == 200
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404
    assert tenant.get("/api/sub-mb/%d" % order["id"]).status_code == 404
    assert bill["id"] not in [b["id"] for b in tenant.get("/api/sub-bills").json().get("bills", [])]


def test_a_revision_takes_the_whole_chain_with_it(tenant):
    order = live_order(tenant, pay_advance=False)
    rev = tenant.post("/api/wo/orders/%d/amend" % order["id"], json={}).json()["order"]
    prev = tenant.get("/api/wo/orders/%d/delete-preview" % rev["id"]).json()
    assert prev["counts"]["versions"] == 2
    assert tenant.delete("/api/wo/orders/%d" % rev["id"]).status_code == 200
    ids = [o["id"] for o in tenant.get("/api/wo/orders").json()["orders"]]
    assert order["id"] not in ids and rev["id"] not in ids


def test_money_paid_against_it_is_deleted_with_it(tenant):
    order = live_order(tenant, mobilization_advance_percent=10)
    assert order["mobilization_advance_amount"] > 0
    prev = tenant.get("/api/wo/orders/%d/delete-preview" % order["id"]).json()
    assert prev["can_delete"] is True and "advance" in prev["warnings"][0]
    assert tenant.delete("/api/wo/orders/%d" % order["id"]).status_code == 200
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 404
    entries = tenant.get("/api/money/entries").json()
    rows = entries.get("entries", entries) if isinstance(entries, dict) else entries
    assert not [e for e in rows if e.get("doc_type") == "sub_advance" and e.get("doc_id") == order["id"]]


def test_staff_cannot_delete_a_work_order(tenant, portal):
    order = live_order(tenant, pay_advance=False)
    pm = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": pm["email"], "password": PASSWORD})
    assert portal.delete("/api/wo/orders/%d" % order["id"]).status_code in (401, 403)
    assert portal.get("/api/wo/orders/%d/delete-preview" % order["id"]).status_code in (401, 403)
    assert tenant.get("/api/wo/orders/%d" % order["id"]).status_code == 200


def test_a_client_work_order_goes_with_everything_on_it(tenant):
    from test_work_order_pricing import fg, job
    code = fg(tenant)
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job(tenant)["id"], "reference": "PO/DEL/1",
        "lines": [{"code": code, "qty": 10, "rate": 500}]}).json()["work_order"]
    assert wo["id"]
    prev = tenant.get("/api/erp/work-orders/%d/delete-preview" % wo["id"])
    assert prev.status_code == 200 and prev.json()["can_delete"] is True
    assert tenant.delete("/api/erp/work-orders/%d" % wo["id"]).status_code == 200
    assert tenant.get("/api/erp/work-orders/%d" % wo["id"]).status_code == 404
