"""Measurement, and the bills that follow from it.

The stretch the contracts deck never covered, because it stops at approval -
and approval is where the money starts moving. Work is measured on site, the
measurements accumulate, and each bill claims the difference between what has
been measured to date and what earlier bills already claimed. That subtraction
is the arithmetic a site office gets wrong by hand every month.
"""
from conftest import make_employee


PASSWORD = "Crew1234"


def placed_order(tenant, qty=1000, rate=60):
    """An order with one line on it, placed and ready to be measured."""
    job = tenant.post("/api/jobs", json={
        "name": "Fairview plot 3", "customer_name": "L&T"}).json()
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY OF CONDUIT", "units_of_measure": "Meters"},
        {"kind": "RM", "item_name": "20MM CONDUIT", "units_of_measure": "Meters"},
    ]}).json()
    fg, rm = made["codes"]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": "PO-1",
        "lines": [{"code": fg, "qty": qty, "rate": rate}]}).json()["work_order"]
    tenant.post("/api/erp/bom/build", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": fg, "rm_code": rm, "qty": qty, "rate": 40}]})
    tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"])
    return wo


def book(tenant, wo_id):
    res = tenant.get("/api/mb/%d" % wo_id)
    assert res.status_code == 200, res.text
    return res.json()


def measure(tenant, wo_id, line_id, qty, **extra):
    body = {"line_id": line_id, "quantity": qty}
    body.update(extra)
    return tenant.post("/api/mb/%d/entries" % wo_id, json=body)


def line_of(tenant, wo_id):
    return book(tenant, wo_id)["lines"][0]["line_id"]


def raise_bill(tenant, wo_id, **extra):
    body = {"work_order_id": wo_id}
    body.update(extra)
    return tenant.post("/api/ra-bills", json=body)


# --- The measurement book ---------------------------------------------------

def test_the_book_opens_on_an_order_with_nothing_measured(tenant):
    wo = placed_order(tenant)
    row = book(tenant, wo["id"])["lines"][0]
    assert row["ordered_qty"] == 1000
    assert row["measured_to_date"] == 0
    assert row["balance_to_measure"] == 1000, "all of it still to do"


def test_measurements_accumulate_rather_than_replace(tenant):
    """The book is a history of what was found on site, not a running total
    somebody overwrites."""
    wo = placed_order(tenant)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 300)
    measure(tenant, wo["id"], line, 250)
    row = book(tenant, wo["id"])["lines"][0]
    assert row["measured_to_date"] == 550
    assert row["balance_to_measure"] == 450
    assert row["percent_measured"] == 55.0


def test_a_correction_is_an_entry_not_an_edit(tenant):
    """A ledger is not rubbed out."""
    wo = placed_order(tenant)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 400)
    measure(tenant, wo["id"], line, -100, remarks="Re-measured, over-recorded")
    assert book(tenant, wo["id"])["lines"][0]["measured_to_date"] == 300
    assert len(book(tenant, wo["id"])["entries"]) == 2, "both entries stand"


def test_measuring_past_the_order_is_allowed_but_said_plainly(tenant):
    """Site conditions differ from the schedule and a variation follows. It
    must not be silent, or somebody bills past the order without knowing."""
    wo = placed_order(tenant)
    line = line_of(tenant, wo["id"])
    res = measure(tenant, wo["id"], line, 1200)
    assert res.status_code == 200
    assert res.json()["over_measured"] == 200
    assert book(tenant, wo["id"])["summary"]["lines_over_measured"] == 1


def test_nothing_is_measured_against_an_order_not_yet_placed(tenant):
    job = tenant.post("/api/jobs", json={"name": "P", "customer_name": "C"}).json()
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY", "units_of_measure": "Meters"}]}).json()
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "lines": [{"code": made["codes"][0], "qty": 10, "rate": 5}]
    }).json()["work_order"]
    line = book(tenant, wo["id"])["lines"][0]["line_id"]
    assert measure(tenant, wo["id"], line, 5).status_code == 409


def test_a_measurement_of_nothing_is_refused(tenant):
    wo = placed_order(tenant)
    assert measure(tenant, wo["id"], line_of(tenant, wo["id"]), 0).status_code == 400


# --- Raising a bill ---------------------------------------------------------

def test_a_bill_claims_what_has_been_measured(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 400)
    res = raise_bill(tenant, wo["id"])
    assert res.status_code == 200, res.text
    b = res.json()["bill"]
    assert b["number"].endswith("/RA-01")
    assert b["this_bill"] == 24000, "400 metres at 60"
    assert b["previously_billed"] == 0


def test_the_second_bill_claims_only_what_is_new(tenant):
    """The subtraction that gets done wrong by hand."""
    wo = placed_order(tenant, qty=1000, rate=60)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 400)
    first = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % first["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % first["id"], json={})

    measure(tenant, wo["id"], line, 350)
    second = raise_bill(tenant, wo["id"]).json()["bill"]
    assert second["sequence"] == 2
    assert second["previously_billed"] == 24000
    assert second["this_bill"] == 21000, "only the 350 metres since"
    assert second["lines"][0]["measured_to_date"] == 750
    assert second["lines"][0]["previously_billed_qty"] == 400


def test_a_bill_cannot_be_raised_with_nothing_new_measured(tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    first = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % first["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % first["id"], json={})
    res = raise_bill(tenant, wo["id"])
    assert res.status_code == 409
    assert "measurement book" in res.json()["detail"]


def test_two_live_bills_cannot_claim_the_same_measurements(tenant):
    """How work gets paid for twice."""
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    raise_bill(tenant, wo["id"])
    again = raise_bill(tenant, wo["id"])
    assert again.status_code == 409
    assert "still open" in again.json()["detail"]


def test_billing_needs_the_order_placed(tenant):
    job = tenant.post("/api/jobs", json={"name": "P", "customer_name": "C"}).json()
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY", "units_of_measure": "Meters"}]}).json()
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "lines": [{"code": made["codes"][0], "qty": 10, "rate": 5}]
    }).json()["work_order"]
    assert raise_bill(tenant, wo["id"]).status_code == 409


# --- The deductions ---------------------------------------------------------

def test_retention_comes_off_the_work_and_tds_off_the_lot(tenant):
    """Retention comes off the work, tax goes on top of what is left, and TDS
    is withheld from the whole claim. The order is worth real money."""
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    b = raise_bill(tenant, wo["id"], retention_percent=5, tax_percent=18,
                   tds_percent=1).json()["bill"]
    assert b["this_bill"] == 100000
    assert b["retention_amount"] == 5000            # 5% of the work
    assert b["tax_amount"] == 17100                 # 18% of 95,000
    assert b["tds_amount"] == 1000                  # 1% of the whole claim
    assert b["net_payable"] == 111100               # 95,000 + 17,100 - 1,000


def test_an_advance_is_recovered_out_of_the_bill(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    b = raise_bill(tenant, wo["id"], retention_percent=0, tax_percent=0,
                   tds_percent=0, advance_recovery=20000).json()["bill"]
    assert b["this_bill"] == 100000
    assert b["net_payable"] == 80000


def test_the_deductions_can_be_corrected_while_it_is_a_draft(tenant):
    wo = placed_order(tenant, qty=100, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    b = raise_bill(tenant, wo["id"], retention_percent=5).json()["bill"]
    res = tenant.put("/api/ra-bills/%d" % b["id"], json={
        "work_order_id": wo["id"], "retention_percent": 10,
        "tax_percent": 0, "tds_percent": 0})
    assert res.json()["bill"]["retention_amount"] == 1000


# --- Certification ----------------------------------------------------------

def test_a_bill_walks_from_draft_to_paid(tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    assert b["status"] == "DRAFT"
    assert tenant.post("/api/ra-bills/%d/submit" % b["id"], json={}).json()["bill"]["status"] == "SUBMITTED"
    cert = tenant.post("/api/ra-bills/%d/certify" % b["id"], json={"comments": "Measured jointly"})
    assert cert.json()["bill"]["status"] == "CERTIFIED"
    assert cert.json()["bill"]["certified_at"]
    assert tenant.post("/api/ra-bills/%d/pay" % b["id"], json={}).json()["bill"]["status"] == "PAID"


def test_a_bill_cannot_skip_certification(tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    assert tenant.post("/api/ra-bills/%d/pay" % b["id"], json={}).status_code == 409


def test_a_submitted_bill_stops_being_editable(tenant):
    """The quantities are what somebody is being asked to certify."""
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    res = tenant.put("/api/ra-bills/%d" % b["id"],
                     json={"work_order_id": wo["id"], "retention_percent": 20})
    assert res.status_code == 409


def test_sending_a_bill_back_must_say_why(tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    assert tenant.post("/api/ra-bills/%d/reject" % b["id"],
                       json={"comments": " "}).status_code == 400
    back = tenant.post("/api/ra-bills/%d/reject" % b["id"],
                       json={"comments": "Quantities not jointly signed"})
    assert back.json()["bill"]["status"] == "DRAFT"
    assert back.json()["bill"]["editable"] is True


def test_the_person_who_measured_cannot_certify(tenant):
    """The whole point of certification being a separate step."""
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})

    engineer = make_employee(tenant, permission_role="supervisor", password=PASSWORD)
    tenant.put("/api/employees/%d" % engineer["id"], json={"status": "active"})
    tenant.post("/api/employee/auth/login",
                json={"email": engineer["email"], "password": PASSWORD})
    assert tenant.post("/api/ra-bills/%d/certify" % b["id"], json={}).status_code == 403
    tenant.post("/api/employee/auth/logout")


# --- Measurements and bills stay consistent ---------------------------------

def test_a_billed_measurement_cannot_be_deleted(tenant):
    wo = placed_order(tenant)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    entry = book(tenant, wo["id"])["entries"][0]
    res = tenant.delete("/api/mb/entries/%d" % entry["id"])
    assert res.status_code == 409
    assert "correcting entry" in res.json()["detail"]


def test_an_unbilled_measurement_can_be_removed(tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    entry = book(tenant, wo["id"])["entries"][0]
    assert tenant.delete("/api/mb/entries/%d" % entry["id"]).status_code == 200
    assert book(tenant, wo["id"])["lines"][0]["measured_to_date"] == 0


def test_cancelling_a_bill_returns_the_work_to_be_billed_again(tenant):
    """The work was still done. Holding it inside a cancelled bill is how it
    never gets paid for."""
    wo = placed_order(tenant, qty=1000, rate=60)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 400)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/cancel" % b["id"], json={"comments": "Raised in error"})

    again = raise_bill(tenant, wo["id"])
    assert again.status_code == 200, again.text
    assert again.json()["bill"]["this_bill"] == 24000, "the work is claimable again"


def test_the_unbilled_value_is_what_is_owed_but_unclaimed(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 400)
    assert book(tenant, wo["id"])["summary"]["unbilled_value"] == 24000
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    assert book(tenant, wo["id"])["summary"]["unbilled_value"] == 0


# --- The register -----------------------------------------------------------

def test_the_register_totals_what_is_claimed_held_and_owed(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 1000)
    b = raise_bill(tenant, wo["id"], retention_percent=5).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    s = tenant.get("/api/ra-bills").json()["summary"]
    assert s["claimed"] == 100000
    assert s["retention_held"] == 5000
    assert s["certified_unpaid"] == 111100


def test_one_tenant_cannot_read_anothers_bill(tenant, second_tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    assert second_tenant.get("/api/ra-bills/%d" % b["id"]).status_code == 404


def test_a_bill_downloads_as_it_is_presented(tenant):
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 500)
    b = raise_bill(tenant, wo["id"]).json()["bill"]
    res = tenant.get("/api/ra-bills/%d/export.xlsx" % b["id"])
    assert res.status_code == 200
    assert "ra_bill_" in res.headers.get("content-disposition", "")



# --- A draft that sat too long ---------------------------------------------

def test_a_draft_is_redrawn_from_the_book_when_it_is_submitted(tenant):
    """A draft can sit for days while the site corrects what it measured.

    Submitting the figures it was born with would send an approver a claim for
    work the book no longer says was done.
    """
    wo = placed_order(tenant)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 100)
    measure(tenant, wo["id"], line, 40)
    bill = raise_bill(tenant, wo["id"]).json()["bill"]
    assert bill["this_bill"] == 140 * 60

    # The 40 turns out to have been somebody else's block.
    newest = book(tenant, wo["id"])["entries"][0]
    assert newest["quantity"] == 40
    assert tenant.delete("/api/mb/entries/%d" % newest["id"]).status_code == 200

    res = tenant.post("/api/ra-bills/%d/submit" % bill["id"], json={})
    assert res.status_code == 200, res.text
    assert res.json()["bill"]["this_bill"] == 100 * 60, (
        "the claim follows the book, not the draft")


def test_a_draft_whose_measurements_all_went_away_cannot_be_submitted(tenant):
    wo = placed_order(tenant)
    line = line_of(tenant, wo["id"])
    measure(tenant, wo["id"], line, 50)
    bill = raise_bill(tenant, wo["id"]).json()["bill"]
    for e in book(tenant, wo["id"])["entries"]:
        assert tenant.delete("/api/mb/entries/%d" % e["id"]).status_code == 200
    res = tenant.post("/api/ra-bills/%d/submit" % bill["id"], json={})
    assert res.status_code == 400
    assert "withdrawn" in res.json()["detail"]
