"""An order's schedule and its total must say the same thing.

A purchase order took a total off the header and its lines separately, and
never compared them: a printed order could show "No items." directly above
a value of goods. The lines are what the storekeeper counts off the lorry
and what a bill is matched against, so where there are lines they are the
order.
"""
from test_goods_receipt import order as po_order


def po(tenant, **body):
    body.setdefault("supplier_name", "Steel Co")
    return tenant.post("/api/purchase-orders", json=body)


def test_the_schedule_is_the_total(tenant):
    """A header that disagrees with the lines is ignored, not believed."""
    res = po(tenant, amount=999999, tax_amount=1,
             line_items=[{"description": "Fe500D 12mm", "qty": 10, "price": 60000, "tax_rate": "18%"},
                         {"description": "Cement OPC 53", "qty": 100, "price": 380, "tax_rate": "18%"}])
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["amount"] == 10 * 60000 + 100 * 380
    assert d["tax_amount"] == round(d["amount"] * 0.18, 2)
    assert d["total"] == round(d["amount"] + d["tax_amount"], 2)


def test_each_line_carries_its_own_rate(tenant):
    d = po(tenant, amount=1, line_items=[
        {"description": "Steel", "qty": 1, "price": 1000, "tax_rate": "18%"},
        {"description": "Sand, exempt", "qty": 1, "price": 500, "tax_rate": "0%"},
    ]).json()
    assert d["amount"] == 1500
    assert d["tax_amount"] == 180


def test_an_order_with_no_schedule_still_carries_a_value(tenant):
    """A committed cost nobody has itemised is a real order, not an error."""
    d = po(tenant, amount=654, tax_amount=22).json()
    assert d["amount"] == 654 and d["total"] == 676
    assert d["line_items"] == []


def test_a_negative_line_is_refused(tenant):
    res = po(tenant, amount=1, line_items=[{"description": "X", "qty": -5, "price": 10}])
    assert res.status_code == 400
    assert "negative" in res.json()["detail"]


def test_editing_the_schedule_moves_the_total(tenant):
    d = po(tenant, amount=1, line_items=[
        {"description": "Steel", "qty": 10, "price": 60000, "tax_rate": "18%"}]).json()
    assert d["amount"] == 600000
    out = tenant.put("/api/purchase-orders/%d" % d["id"], json={
        "supplier_name": "Steel Co", "amount": d["amount"],
        "line_items": [{"description": "Steel", "qty": 4, "price": 60000, "tax_rate": "18%"}]}).json()
    assert out["amount"] == 240000
    assert out["total"] == round(240000 * 1.18, 2)


def test_the_printed_order_has_what_it_needs(tenant):
    d = tenant.get("/api/purchase-orders/%d" % po_order(tenant)["id"]).json()
    assert d["line_items"], "the page prints the schedule, so it has to be there"
    assert d["our"]["name"] and d["amount_in_words"].startswith("Rupees")
