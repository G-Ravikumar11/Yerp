"""Subcontractor bills - the money going out.

A work order is what the client buys from us and an RA bill against it is
money coming in. A subcontract order is what we buy from a gang, and until now
it could be signed but never measured or billed. The money going out to the
people actually doing the work was not in the app, and every project's profit
was flattered by exactly that amount.

Same shape as the client side on purpose. The difference is who holds the
retention: here it is us.
"""
from test_subcontract_orders import priced, BOQ


def live_order(tenant, pay_advance=True, **over):
    """A priced subcontract order, submitted and approved - ready to measure.

    Terms go on the draft: once approved the figures are what somebody signed
    for, and changing them afterwards is refused. Any mobilisation advance is
    paid, as it is on site before the first bill - only a paid advance is
    recovered."""
    order = priced(tenant, **over)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 200, res.text
    order = res.json()["order"]
    if pay_advance and order.get("mobilization_advance_amount"):
        paid = pay_the_advance(tenant, order["id"], order["mobilization_advance_amount"])
        assert paid.status_code == 200, paid.text
    return order


def pay_the_advance(tenant, order_id, amount):
    return tenant.post("/api/money/entries", json={
        "doc_type": "sub_advance", "doc_id": order_id, "amount": amount,
        "mode": "Bank transfer", "reference": "UTR-ADV-%d" % order_id})


def book(tenant, order_id):
    res = tenant.get("/api/sub-mb/%d" % order_id)
    assert res.status_code == 200, res.text
    return res.json()


def measure(tenant, order_id, item_id, qty, **extra):
    body = {"item_id": item_id, "quantity": qty}
    body.update(extra)
    res = tenant.post("/api/sub-mb/%d/entries" % order_id, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def raise_bill(tenant, order_id, **extra):
    body = {"order_id": order_id}
    body.update(extra)
    return tenant.post("/api/sub-bills", json=body)


# --- Measuring the gang's work --------------------------------------------------

def test_the_book_opens_with_every_ordered_item(tenant):
    order = live_order(tenant)
    b = book(tenant, order["id"])
    assert len(b["lines"]) == len(BOQ["lines"])
    assert b["lines"][0]["activity_no"] == "1.0"
    assert b["lines"][0]["ordered_qty"] == 250
    assert b["summary"]["measured_value"] == 0


def test_a_draft_order_cannot_be_measured(tenant):
    order = priced(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"],
                      json={"item_id": item, "quantity": 10})
    assert res.status_code == 409
    assert "not been approved" in res.json()["detail"]


def test_measurements_accumulate(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    measure(tenant, order["id"], item, 60)
    line = book(tenant, order["id"])["lines"][0]
    assert line["measured_to_date"] == 160
    assert line["balance_to_measure"] == 90


def test_a_correction_is_a_negative_entry_not_an_edit(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    measure(tenant, order["id"], item, -15, remarks="Re-measured, cube failed")
    assert book(tenant, order["id"])["lines"][0]["measured_to_date"] == 85


# --- The bill -----------------------------------------------------------------

def test_the_bill_draws_itself_from_the_book(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    res = raise_bill(tenant, order["id"])
    assert res.status_code == 200, res.text
    bill = res.json()["bill"]
    assert bill["number"].endswith("/RA-01")
    assert bill["this_bill"] == 100 * 6800
    assert bill["lines"][0]["this_bill_qty"] == 100


def test_the_deductions_are_made_in_the_right_order(tenant):
    """Retention off the work, GST on the remainder, TDS off the lot.

    The order has 18% GST and 1% TDS from the fixture; retention is set here
    so the arithmetic is checkable by hand.
    """
    order = live_order(tenant, retention_percent=5)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)           # 6,80,000 of work
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    # 5% of 6,80,000 held back. 18% GST on the 6,46,000 that remains.
    # 1% TDS on the whole 6,80,000 claim.
    assert bill["retention_amount"] == 34000
    assert bill["gst_amount"] == round(646000 * 0.18, 2)
    assert bill["tds_amount"] == 6800
    assert bill["net_payable"] == round(646000 + 646000 * 0.18 - 6800, 2)


def test_the_second_bill_claims_only_what_is_new(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    first = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % first["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % first["id"], json={})
    measure(tenant, order["id"], item, 40)
    second = raise_bill(tenant, order["id"]).json()["bill"]
    assert second["number"].endswith("/RA-02")
    assert second["lines"][0]["previously_billed_qty"] == 100
    assert second["lines"][0]["this_bill_qty"] == 40
    assert second["previously_billed"] == 680000


def test_two_live_bills_cannot_claim_the_same_work(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    raise_bill(tenant, order["id"])
    again = raise_bill(tenant, order["id"])
    assert again.status_code == 409
    assert "still open" in again.json()["detail"]


def test_nothing_new_means_no_bill(tenant):
    order = live_order(tenant)
    res = raise_bill(tenant, order["id"])
    assert res.status_code == 409
    assert "nothing has been measured" in res.json()["detail"].lower()


def test_mobilisation_advance_is_recovered_pro_rata(tenant):
    order = live_order(tenant, mobilization_advance_percent=10,
                       advance_recovery_percent=10)
    advance = order["mobilization_advance_amount"]
    assert advance > 0, "the fixture order carries a mobilisation advance"
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["advance_recovery"] == round(advance * 0.10, 2)


def test_cancelling_a_bill_returns_the_work_to_be_claimed(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/cancel" % bill["id"], json={"comments": "wrong rate"})
    assert book(tenant, order["id"])["lines"][0]["unbilled"] == 100
    assert raise_bill(tenant, order["id"]).status_code == 200


def test_a_billed_measurement_cannot_be_deleted(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    entry = measure(tenant, order["id"], item, 100)
    raise_bill(tenant, order["id"])
    entries = book(tenant, order["id"])["entries"]
    assert entries[0]["billed"] is True
    assert tenant.delete("/api/sub-mb/entries/%d" % entries[0]["id"]).status_code == 409


def test_the_bill_downloads(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    res = tenant.get("/api/sub-bills/%d/export.xlsx" % bill["id"])
    assert res.status_code == 200 and res.content[:2] == b"PK"


# --- Where the money lands ----------------------------------------------------

def certified(tenant, qty=100):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, qty)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    return order, tenant.get("/api/sub-bills/%d" % bill["id"]).json()


def test_a_certified_subcontractor_bill_is_money_we_owe(tenant):
    order, bill = certified(tenant)
    p = tenant.get("/api/money/payables").json()
    sub = [r for r in p["bills"] if r["kind"] == "Subcontractor bill"]
    assert len(sub) == 1
    assert sub[0]["outstanding"] == bill["net_payable"]
    assert sub[0]["party"].startswith("Sri Balaji")


def test_paying_it_clears_the_debt_but_not_the_retention(tenant):
    order, bill = certified(tenant)
    tenant.post("/api/sub-bills/%d/pay" % bill["id"], json={"reference": "NEFT 88213"})
    assert tenant.get("/api/money/payables").json()["summary"]["owed"] == 0
    s = tenant.get("/api/sub-bills").json()["summary"]
    assert s["paid"] == bill["net_payable"]
    assert s["retention_held"] == bill["retention_amount"]


def test_it_is_a_cost_on_the_project(tenant):
    """The whole point. Every project was flattered by this before."""
    order, bill = certified(tenant)
    p = tenant.get("/api/jobs/%d/pnl" % order["job_id"]).json()
    assert p["cost"]["subcontractors"] == bill["this_bill"]
    assert p["cost"]["incurred"] >= bill["this_bill"]


def test_a_draft_bill_is_not_a_cost_yet(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    raise_bill(tenant, order["id"])
    p = tenant.get("/api/jobs/%d/pnl" % order["job_id"]).json()
    assert p["cost"]["subcontractors"] == 0


def test_certifying_is_the_approvers_right(tenant):
    from conftest import make_employee
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})

    eng = make_employee(tenant, permission_role="manager", password="Crew1234")
    tenant.put("/api/employees/%d" % eng["id"], json={
        "status": "active", "denied_permissions": "subcontracts.approve"})
    tenant.post("/api/employee/auth/login", json={"email": eng["email"], "password": "Crew1234"})
    assert tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={}).status_code == 403
    tenant.post("/api/employee/auth/logout")


def test_another_tenant_sees_none_of_it(tenant, second_tenant):
    order, bill = certified(tenant)
    assert second_tenant.get("/api/sub-bills/%d" % bill["id"]).status_code == 404
    assert second_tenant.get("/api/sub-mb/%d" % order["id"]).status_code == 404
    assert second_tenant.get("/api/money/payables").json()["summary"]["owed"] == 0


def test_a_small_first_bill_does_not_go_negative(tenant):
    """10% of a large advance against a small month's work: the recovery is
    what the bill can bear, and the rest waits. A bill for less than nothing
    was reaching the printer."""
    order = live_order(tenant, mobilization_advance_percent=10,
                       advance_recovery_percent=50, retention_percent=5)
    assert order["mobilization_advance_amount"] > 0
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 1)                    # one cum of work
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["net_payable"] >= 0
    assert bill["advance_recovery"] > 0
    assert bill["advance_recovery"] < bill["this_bill"] - bill["retention_amount"]


def test_the_advance_is_never_recovered_twice_over(tenant):
    """Bill after bill, the recovery stops when the advance is paid back."""
    order = live_order(tenant, mobilization_advance_percent=10,
                       advance_recovery_percent=60)
    advance = order["mobilization_advance_amount"]
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    recovered = 0.0
    for qty in (100, 100, 50):
        measure(tenant, order["id"], item, qty)
        bill = raise_bill(tenant, order["id"]).json()["bill"]
        tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
        tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
        recovered += bill["advance_recovery"]
    assert round(recovered, 2) == advance



def test_an_advance_never_paid_is_never_recovered(tenant):
    """The agreed advance used to come off the first bill whether or not the
    gang had ever been paid it."""
    order = live_order(tenant, pay_advance=False, mobilization_advance_percent=10,
                       advance_recovery_percent=10)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["advance_recovery"] == 0


def test_only_what_was_paid_comes_back(tenant):
    order = live_order(tenant, pay_advance=False, mobilization_advance_percent=10,
                       advance_recovery_percent=100)
    part = round(order["mobilization_advance_amount"] / 4, 2)
    assert pay_the_advance(tenant, order["id"], part).status_code == 200
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 250)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["advance_recovery"] == part


def test_the_advance_cannot_be_paid_twice_over(tenant):
    order = live_order(tenant, mobilization_advance_percent=10, advance_recovery_percent=10)
    again = pay_the_advance(tenant, order["id"], 1)
    assert again.status_code == 409 and "settled" in again.json()["detail"]
    assert tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["advance_paid"] ==         order["mobilization_advance_amount"]


def test_a_draft_order_takes_no_advance(tenant):
    order = priced(tenant, mobilization_advance_percent=10)
    res = pay_the_advance(tenant, order["id"], 100)
    assert res.status_code == 409


def test_the_gangs_ledger_shows_only_the_advance_still_owed(tenant):
    """Paid 10% advance, part of it taken back on a bill that was then paid
    in full: the gang owes exactly what has not come back yet."""
    order = live_order(tenant, mobilization_advance_percent=10, advance_recovery_percent=10)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    bill = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    bill = bill.get("bill", bill)
    paid = tenant.post("/api/money/entries", json={
        "doc_type": "sub_bill", "doc_id": bill["id"], "amount": bill["net_payable"],
        "mode": "Bank transfer", "reference": "UTR-BILL"})
    assert paid.status_code == 200, paid.text
    gang = [p for p in tenant.get("/api/ledger/parties").json()["parties"]
            if p["party_type"] == "contractor"][0]
    still_out = round(order["mobilization_advance_amount"] - bill["advance_recovery"], 2)
    assert bill["advance_recovery"] > 0
    assert gang["balance"] == -still_out
