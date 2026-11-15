"""Quantities are kept to three decimals and money to the paisa: a measured 12.346 is not booked as 12.35, a bill line is
quantity x rate to the paisa, and a bill's total is the sum of its lines as shown."""
from app.core.currency import money, qty3

from test_measurement_dimensions import book, measure, placed_order  # noqa: F401


def test_a_quantity_keeps_three_decimals_with_a_half_rounded_up():
    assert qty3(12.3456) == 12.346 and qty3(12.3454) == 12.345
    assert qty3(1.0005) == 1.001              # float round() gives 1.0
    assert qty3(2.6745) == 2.675 and qty3(None) == 0.0 and qty3("x") == 0.0
    assert money(2.675) == 2.68               # and money a half up to the paisa


def test_a_measurement_is_booked_at_three_decimals_and_billed_on_them(tenant):
    wo = placed_order(tenant, qty=1000, rate=137.55)
    line = book(tenant, wo["id"])["lines"][0]["line_id"]
    assert measure(tenant, wo["id"], line, 12.346).status_code == 200
    assert measure(tenant, wo["id"], line, 0.004).status_code == 200
    b = book(tenant, wo["id"])
    assert [e["quantity"] for e in b["entries"]] in ([12.346, 0.004], [0.004, 12.346])
    row = b["lines"][0]
    assert row["measured_to_date"] == 12.35                     # 12.346 + 0.004, not 12.35 + 0.00
    bill = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    got = tenant.get("/api/ra-bills/%d" % bill["id"]).json()["bill"]
    lines = got["lines"]
    assert lines[0]["this_bill_qty"] == 12.35 and lines[0]["amount"] == round(12.35 * 137.55, 2)
    assert got["this_bill"] == round(sum(l["amount"] for l in lines), 2)
