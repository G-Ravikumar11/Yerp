"""GST the way the return needs it.

The bills carried a flat tax percentage. A return does not: it wants to know
whether the supply was inside our state - CGST and SGST, half each - or across
a border - all of it IGST - per rate, per month, with the SAC against every
line. For a works contract the place of supply is where the property is.
"""
from test_measurement_and_ra_bills import placed_order, book, measure
from test_subcontractor_bills import (live_order, book as sub_book,
                                      measure as sub_measure, raise_bill)


def registered(tenant, gstin="36AABCY1234H1ZX"):
    res = tenant.put("/api/gst/settings", json={"gstin": gstin})
    assert res.status_code == 200, res.text
    return res.json()


def site_in(tenant, job_id, state):
    res = tenant.put("/api/jobs/%d/place-of-supply" % job_id, json={"state_code": state})
    assert res.status_code == 200, res.text


def certified_client_bill(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    return wo, tenant.get("/api/ra-bills/%d" % b["id"]).json()["bill"]


# --- Who we are ---------------------------------------------------------------

def test_the_state_falls_out_of_the_gstin(tenant):
    out = registered(tenant, "36AABCY1234H1ZX")
    assert out["state_code"] == "36"
    assert out["state"] == "Telangana"


def test_a_malformed_gstin_is_refused(tenant):
    assert tenant.put("/api/gst/settings", json={"gstin": "ABC123"}).status_code == 400
    assert tenant.put("/api/gst/settings", json={"gstin": "99AABCY1234H1ZX"}).status_code == 400


def test_a_site_takes_a_state(tenant):
    wo = placed_order(tenant)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    site_in(tenant, job_id, "37")
    assert tenant.get("/api/jobs/%d" % job_id).json()["state_code"] == "37"
    assert tenant.put("/api/jobs/%d/place-of-supply" % job_id,
                      json={"state_code": "99"}).status_code == 400


# --- The split ------------------------------------------------------------------

def test_a_site_in_our_own_state_is_cgst_plus_sgst(tenant):
    """Telangana company, Telangana site: half and half."""
    registered(tenant, "36AABCY1234H1ZX")
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    site_in(tenant, job_id, "36")
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    # 10,000 of work, 5% retention -> 9,500 taxable at 18% = 1,710.
    assert b["tax_amount"] == 1710
    assert b["cgst_amount"] == 855
    assert b["sgst_amount"] == 855
    assert b["igst_amount"] == 0
    assert b["place_of_supply"] == "36"


def test_a_site_across_the_border_is_all_igst(tenant):
    """Telangana company, Andhra site: every rupee of tax is IGST."""
    registered(tenant, "36AABCY1234H1ZX")
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    site_in(tenant, job_id, "37")
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    assert b["tax_amount"] == 1710
    assert b["igst_amount"] == 1710
    assert b["cgst_amount"] == 0 and b["sgst_amount"] == 0


def test_an_unknown_place_of_supply_defaults_to_igst(tenant):
    """A wrong IGST is a reconciliation; a wrong CGST across a border is a
    penalty. When in doubt, the safer of the two."""
    registered(tenant, "36AABCY1234H1ZX")
    wo, b = certified_client_bill(tenant)          # site has no state set
    assert b["igst_amount"] == b["tax_amount"] > 0
    assert b["cgst_amount"] == 0


def test_the_split_always_adds_up_to_the_tax(tenant):
    registered(tenant, "36AABCY1234H1ZX")
    wo = placed_order(tenant, qty=1000, rate=33.33)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    site_in(tenant, job_id, "36")
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 7)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    assert round(b["cgst_amount"] + b["sgst_amount"] + b["igst_amount"], 2) == b["tax_amount"]


def test_the_net_payable_is_unchanged_by_the_split(tenant):
    """Splitting the tax must not change what the client owes."""
    registered(tenant, "36AABCY1234H1ZX")
    wo, b = certified_client_bill(tenant)
    taxable = (b["this_bill"] - b["retention_amount"] - b["advance_recovery"]
               - b["other_deductions"])
    assert b["net_payable"] == round(taxable + b["tax_amount"] - b["tds_amount"], 2)


def test_the_gangs_bill_is_split_the_same_way(tenant):
    registered(tenant, "36AABCY1234H1ZX")
    order = live_order(tenant, retention_percent=5)
    site_in(tenant, order["job_id"], "36")
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    b = raise_bill(tenant, order["id"]).json()["bill"]
    assert b["cgst_amount"] == b["sgst_amount"] > 0
    assert b["igst_amount"] == 0
    assert round(b["cgst_amount"] + b["sgst_amount"], 2) == b["gst_amount"]


# --- The summaries -------------------------------------------------------------

def test_outward_supplies_group_by_month_and_rate(tenant):
    registered(tenant, "36AABCY1234H1ZX")
    certified_client_bill(tenant)
    certified_client_bill(tenant)
    out = tenant.get("/api/gst/outward").json()
    assert out["summary"]["bills"] == 2
    assert len(out["by_month"]) == 1
    assert out["by_rate"][0]["rate"] == 18
    assert out["summary"]["tax"] == round(sum(r["tax"] for r in out["supplies"]), 2)
    assert out["supplies"][0]["sac"] == "9954"


def test_outward_flags_bills_with_no_place_of_supply(tenant):
    """A return cannot be filed against a blank."""
    registered(tenant, "36AABCY1234H1ZX")
    certified_client_bill(tenant)
    assert tenant.get("/api/gst/outward").json()["summary"]["missing_place_of_supply"] == 1


def test_a_draft_bill_is_not_an_outward_supply(tenant):
    registered(tenant, "36AABCY1234H1ZX")
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]})
    assert tenant.get("/api/gst/outward").json()["summary"]["bills"] == 0


def test_inward_lists_the_gangs_bills_with_their_gstin(tenant):
    registered(tenant, "36AABCY1234H1ZX")
    order = live_order(tenant)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    b = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % b["id"], json={})
    inw = tenant.get("/api/gst/inward").json()
    sub = [r for r in inw["supplies"] if r["kind"] == "Subcontractor bill"]
    assert len(sub) == 1
    assert sub[0]["party_gstin"].startswith("36")
    assert inw["summary"]["missing_party_gstin"] == 0


def test_outward_downloads(tenant):
    registered(tenant)
    certified_client_bill(tenant)
    res = tenant.get("/api/gst/outward.xlsx")
    assert res.status_code == 200 and res.content[:2] == b"PK"


def test_another_tenant_sees_none_of_it(tenant, second_tenant):
    registered(tenant)
    certified_client_bill(tenant)
    assert second_tenant.get("/api/gst/outward").json()["summary"]["bills"] == 0
    assert second_tenant.get("/api/gst/settings").json()["gstin"] == ""
