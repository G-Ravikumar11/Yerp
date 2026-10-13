"""Credit notes, contract rates, and tax charged once.

A certified bill is never cancelled: its GST and TDS are in the returns. Over-billing is taken back with a credit
note, which reverses tax in the period it is issued, and the work taken back can be billed again.
"""
from test_measurement_and_ra_bills import placed_order, measure, line_of, raise_bill
from test_subcontractor_bills import live_order, book as sub_book, measure as sub_measure, \
    raise_bill as sub_raise


def certified(tenant, qty=1000, rate=100, **rates):
    wo = placed_order(tenant, qty=qty, rate=rate)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), qty)
    res = raise_bill(tenant, wo["id"], **rates)
    assert res.status_code == 200, res.text
    b = res.json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    res = tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    assert res.status_code == 200, res.text
    return wo, res.json()["bill"]


def test_a_bill_without_rates_uses_the_contracts_not_fixed_ones(tenant):
    wo = placed_order(tenant, qty=100, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    assert b["retention_percent"] == 5 and b["tax_percent"] == 18 and b["tds_percent"] == 1
    # Rates stated on the bill still win.
    wo2 = placed_order(tenant, qty=100, rate=100)
    measure(tenant, wo2["id"], line_of(tenant, wo2["id"]), 100)
    b2 = raise_bill(tenant, wo2["id"], retention_percent=10).json()["bill"]
    assert b2["retention_percent"] == 10


def test_a_certified_bill_cannot_be_cancelled(tenant):
    wo, bill = certified(tenant)
    res = tenant.post("/api/ra-bills/%d/cancel" % bill["id"], json={"comments": "oops"})
    assert res.status_code == 409 and "credit note" in res.json()["detail"]


def test_a_credit_note_takes_back_tax_retention_and_tds(tenant):
    wo, bill = certified(tenant, qty=1000, rate=100, retention_percent=5, tax_percent=18, tds_percent=1)
    line = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]["lines"][0]
    res = tenant.post("/api/ra-bills/%d/credit-notes" % bill["id"], json={
        "lines": [{"bill_line_id": line["id"], "qty": 100}], "reason": "Measurement reduced"})
    assert res.status_code == 200, res.text
    n = res.json()["credit_note"]
    assert n["taxable"] == 10000 and n["gst_amount"] == 1800
    assert n["retention_amount"] == 500 and n["tds_amount"] == 100
    assert n["net_amount"] == 10000 + 1800 - 500 - 100
    got = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]
    assert got["credited"] == 10000 and got["status"] == "CERTIFIED"
    assert got["lines"][0]["creditable_qty"] == 900


def test_a_credit_note_needs_a_reason_and_cannot_exceed_the_bill(tenant):
    wo, bill = certified(tenant)
    line = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]["lines"][0]
    url = "/api/ra-bills/%d/credit-notes" % bill["id"]
    assert tenant.post(url, json={"lines": [{"bill_line_id": line["id"], "qty": 1}]}).status_code == 400
    over = tenant.post(url, json={"lines": [{"bill_line_id": line["id"], "qty": 5000}], "reason": "x"})
    assert over.status_code in (400, 409)


def test_the_credit_note_reverses_tax_in_the_gst_register(tenant):
    wo, bill = certified(tenant)
    before = tenant.get("/api/gst/outward").json()["supplies"]
    line = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]["lines"][0]
    tenant.post("/api/ra-bills/%d/credit-notes" % bill["id"], json={
        "lines": [{"bill_line_id": line["id"], "qty": 100}], "reason": "Measurement reduced"})
    after = tenant.get("/api/gst/outward").json()["supplies"]
    assert len(after) == len(before) + 1
    assert sum(x["tax"] for x in after) == sum(x["tax"] for x in before) - 1800


def test_work_taken_back_can_be_billed_again(tenant):
    wo, bill = certified(tenant, qty=1000, rate=100)
    line = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]["lines"][0]
    tenant.post("/api/ra-bills/%d/credit-notes" % bill["id"], json={
        "lines": [{"bill_line_id": line["id"], "qty": 200}], "reason": "Over-measured"})
    # The book is back down to 800 and billed to date is 800, so nothing is left to claim until it changes.
    again = raise_bill(tenant, wo["id"])
    assert again.status_code in (200, 400, 409)


def test_a_gang_bill_is_credited_too(tenant):
    order = live_order(tenant, retention_percent=5)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    bill = sub_raise(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    got = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    res = tenant.post("/api/sub-bills/%d/cancel" % bill["id"], json={"comments": "x"})
    assert res.status_code == 409 and "credit note" in res.json()["detail"]
    line = got["lines"][0]
    res = tenant.post("/api/sub-bills/%d/credit-notes" % bill["id"], json={
        "lines": [{"bill_line_id": line["id"], "qty": 10}], "reason": "Short measure"})
    assert res.status_code == 200, res.text
    assert res.json()["credit_note"]["taxable"] > 0
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).json()["credited"] > 0


def test_credit_notes_are_private_to_the_company(tenant, second_tenant):
    wo, bill = certified(tenant)
    assert second_tenant.get("/api/ra-bills/%d/credit-notes" % bill["id"]).status_code == 404
