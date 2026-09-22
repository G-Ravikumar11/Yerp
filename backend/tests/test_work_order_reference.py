"""The client's own order number, carried through to the bill.

A work order is filed by the client under their number, not ours. It was
typed into a box labelled only "Reference", never shown again, and accepted
at any length. Now it is named for what it is, capped to what fits on a
printed line, and appears on every bill raised against the order.
"""
from test_measurement_and_ra_bills import placed_order, book, measure


def built(tenant, reference):
    job = tenant.post("/api/jobs", json={"name": "Site", "customer_name": "ACME"}).json()
    item = tenant.post("/api/erp/items", json={
        "kind": "FG", "item_name": "Conduit", "units_of_measure": "Nos"}).json()
    return tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": reference,
        "lines": [{"code": item["item_code"], "qty": 1, "rate": 10}]})


def test_the_reference_is_kept_and_trimmed(tenant):
    res = built(tenant, "  PO/2026/ACME/0042  ")
    assert res.status_code == 200, res.text
    assert res.json()["work_order"]["reference"] == "PO/2026/ACME/0042"


def test_a_reference_longer_than_a_printed_line_is_refused(tenant):
    """It prints on a bill, so it has to fit on one."""
    assert built(tenant, "X" * 61).status_code == 422


def test_the_bill_carries_the_clients_reference(tenant):
    """It is what they will look for when the bill lands on their desk."""
    wo = placed_order(tenant, qty=1000, rate=100)          # the fixture uses PO-1
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    bill = tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]
    assert bill["work_order_detail"]["reference"] == "PO-1"
