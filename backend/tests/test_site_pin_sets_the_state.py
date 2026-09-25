"""A project raised without picking its state billed IGST even for a site in
the contractor's own city. The PIN in the site address settles it."""
from test_measurement_and_ra_bills import book, measure


def certified_bill(tenant, site):
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    job = tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec",
                                         "site_address": site}).json()
    fg = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "RCC M25", "units_of_measure": "cum"}]}).json()["codes"][0]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": "LOA-1",
        "lines": [{"code": fg, "qty": 100, "rate": 5000}]}).json()["work_order"]
    tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"])
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 10)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    return tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]


def test_a_hyderabad_site_is_billed_cgst_and_sgst(tenant):
    b = certified_bill(tenant, "Vanya City, Kokapet, Hyderabad 500075")
    assert b["place_of_supply"] == "36"
    assert b["cgst_amount"] > 0 and b["sgst_amount"] > 0 and b["igst_amount"] == 0


def test_a_site_across_the_border_is_igst(tenant):
    b = certified_bill(tenant, "Whitefield, Bengaluru 560066")
    assert b["place_of_supply"] == "29" and b["igst_amount"] > 0 and b["cgst_amount"] == 0


def test_no_pin_leaves_it_unknown(tenant):
    b = certified_bill(tenant, "Kokapet")
    assert b["place_of_supply"] == "" and b["igst_amount"] > 0


def test_a_pin_that_spans_two_states_is_not_guessed(tenant):
    b = certified_bill(tenant, "Villupuram 605602")
    assert b["place_of_supply"] == ""
