"""One company must not reach another's order through an id.

Ids run in sequence across every company, so anything taking a bare id has to
check whose it is: a variation naming a line, and an approval history asked for
by document id.
"""
from test_measurement_and_ra_bills import placed_order, book


def test_a_variation_cannot_name_another_companys_line(tenant, second_tenant):
    victim = placed_order(tenant, qty=100, rate=10)
    victim_line = book(tenant, victim["id"])["lines"][0]["line_id"]
    mine = placed_order(second_tenant, qty=5, rate=10)

    res = second_tenant.post("/api/variations", json={"work_order_id": mine["id"], "lines": [
        {"line_id": victim_line, "extra_qty": 900, "rate": 10, "description": "x", "uom": "Nos"}]})
    assert res.status_code == 404, res.text

    # Nothing was drafted, and the victim's quantity is untouched.
    assert second_tenant.get("/api/variations").json()["variations"] == []
    after = book(tenant, victim["id"])["lines"][0]
    assert after["line_id"] == victim_line and after["ordered_qty"] == 100


def test_a_variation_cannot_name_a_line_of_another_order_of_the_same_company(tenant):
    a = placed_order(tenant, qty=100, rate=10)
    b = placed_order(tenant, qty=100, rate=10)
    line_of_b = book(tenant, b["id"])["lines"][0]["line_id"]
    res = tenant.post("/api/variations", json={"work_order_id": a["id"], "lines": [
        {"line_id": line_of_b, "extra_qty": 5, "rate": 10, "description": "x", "uom": "Nos"}]})
    assert res.status_code == 404, res.text


def test_a_variation_on_its_own_line_still_works(tenant):
    wo = placed_order(tenant, qty=100, rate=10)
    line = book(tenant, wo["id"])["lines"][0]["line_id"]
    res = tenant.post("/api/variations", json={"work_order_id": wo["id"], "lines": [
        {"line_id": line, "extra_qty": 5, "rate": 10, "description": "x", "uom": "Nos"}]})
    assert res.status_code == 200, res.text


def test_approval_history_of_another_company_is_not_readable(tenant, second_tenant):
    wo = placed_order(tenant, qty=100, rate=10)
    assert tenant.get("/api/approvals/history/work_order/%d" % wo["id"]).status_code == 200
    res = second_tenant.get("/api/approvals/history/work_order/%d" % wo["id"])
    assert res.status_code == 404, res.text
    assert second_tenant.get("/api/approvals/history/nonsense/1").status_code == 404
