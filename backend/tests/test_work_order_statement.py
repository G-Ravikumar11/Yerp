"""One page that answers "where are we on this order".

Every figure here already existed, on a different screen. The statement is
the reconciliation nobody could do without opening four of them and
subtracting by hand - which is the arithmetic this app exists to stop.
"""
from test_measurement_and_ra_bills import placed_order, book, measure


def statement(tenant, wo_id):
    res = tenant.get("/api/erp/work-orders/%d/statement" % wo_id)
    assert res.status_code == 200, res.text
    return res.json()


def test_a_fresh_order_reads_as_all_still_to_build(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    s = statement(tenant, wo["id"])
    assert s["order"]["original_value"] == 60000
    assert s["order"]["revised_value"] == 60000
    assert s["progress"]["measured_value"] == 0
    assert s["progress"]["left_to_build"] == 60000
    assert s["progress"]["percent_complete"] == 0
    assert s["money"]["claimed"] == 0


def test_measuring_moves_work_out_of_left_to_build(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    s = statement(tenant, wo["id"])
    assert s["progress"]["measured_value"] == 24000
    assert s["progress"]["left_to_build"] == 36000
    assert s["progress"]["percent_complete"] == 40.0
    # Built but not claimed - the number worth chasing.
    assert s["money"]["measured_not_billed"] == 24000


def test_billing_moves_it_from_unbilled_to_claimed(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]})
    s = statement(tenant, wo["id"])
    assert s["money"]["claimed"] == 24000
    assert s["money"]["measured_not_billed"] == 0
    assert s["money"]["certified"] == 0        # drawn up is not agreed


def test_certifying_and_paying_separate_the_three_stages(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})

    s = statement(tenant, wo["id"])
    assert s["money"]["certified"] == 24000
    assert s["money"]["paid"] == 0
    assert s["money"]["awaiting_payment"] > 0
    assert s["money"]["retention_held"] > 0

    tenant.post("/api/ra-bills/%d/pay" % b["id"], json={})
    s = statement(tenant, wo["id"])
    assert s["money"]["paid"] > 0
    assert s["money"]["awaiting_payment"] == 0


def test_a_cancelled_bill_leaves_the_work_to_be_claimed_again(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    # Cancelling asks for a reason, the same as sending one back.
    tenant.post("/api/ra-bills/%d/cancel" % b["id"],
                json={"comments": "Client disputed the levels"})
    s = statement(tenant, wo["id"])
    assert s["money"]["claimed"] == 0
    assert s["money"]["measured_not_billed"] == 24000


# --- Variations, without double counting -------------------------------------

def test_an_agreed_variation_is_not_counted_twice(tenant):
    """Approving raises the lines, so the order's own value already holds it."""
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 1200)
    vo = tenant.post("/api/variations", json={"work_order_id": wo["id"]}).json()["variation"]
    tenant.post("/api/variations/%d/submit" % vo["id"])
    tenant.post("/api/variations/%d/approve" % vo["id"])

    s = statement(tenant, wo["id"])
    assert s["order"]["original_value"] == 60000
    assert s["order"]["variations_agreed"] == 12000
    assert s["order"]["revised_value"] == 72000     # not 84000
    assert s["progress"]["percent_complete"] == 100.0
    assert s["progress"]["over_run_not_yet_varied"] == 0


def test_an_unagreed_variation_is_shown_but_not_added_to_the_order(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 1200)
    tenant.post("/api/variations", json={"work_order_id": wo["id"]})
    s = statement(tenant, wo["id"])
    assert s["order"]["variations_pending"] == 12000
    assert s["order"]["variations_agreed"] == 0
    assert s["order"]["revised_value"] == 60000
    # Still over-run until somebody agrees it.
    assert s["progress"]["over_run_not_yet_varied"] == 12000


def test_over_run_is_flagged_before_any_variation_exists(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 1100)
    s = statement(tenant, wo["id"])
    assert s["progress"]["over_run_not_yet_varied"] == 6000
    assert s["progress"]["left_to_build"] == -6000


# --- The lines and the export -------------------------------------------------

def test_each_line_carries_its_own_reconciliation(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    line = statement(tenant, wo["id"])["lines"][0]
    assert line["ordered_qty"] == 1000 and line["ordered_value"] == 60000
    assert line["measured_qty"] == 400 and line["measured_value"] == 24000
    assert line["unbilled_qty"] == 400
    assert line["percent_measured"] == 40.0


def test_bills_and_variations_are_listed_in_order(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    line = book(tenant, wo["id"])["lines"][0]["line_id"]
    measure(tenant, wo["id"], line, 400)
    first = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    # A second bill is refused while the first is still open - two live bills
    # claiming the same measurements is how work gets paid for twice - so the
    # first has to be seen through before the next one exists.
    tenant.post("/api/ra-bills/%d/submit" % first["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % first["id"], json={})
    measure(tenant, wo["id"], line, 300)
    tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]})
    s = statement(tenant, wo["id"])
    assert [b["number"][-2:] for b in s["bills"]] == ["01", "02"]
    assert s["money"]["claimed"] == 42000


def test_the_statement_downloads_as_a_workbook(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 400)
    res = tenant.get("/api/erp/work-orders/%d/statement.xlsx" % wo["id"])
    assert res.status_code == 200
    assert res.content[:2] == b"PK"           # a real xlsx, not an error page
    assert len(res.content) > 3000


def test_another_tenant_cannot_read_the_statement(tenant, second_tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    assert second_tenant.get(
        "/api/erp/work-orders/%d/statement" % wo["id"]).status_code == 404
