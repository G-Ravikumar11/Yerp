"""An issue note that opens empty and says nothing is found at the store.

Creating an issue note answered "opened" whatever it was sent: a line whose
quantity was called qty - which is what every other document in this app
calls it - was dropped, the note was saved with nothing on it, and the
mistake surfaced later, when the note refused to be posted, by which time
somebody is standing at the store with a lorry.
"""
from test_goods_receipt import order as po_order, receipt, post


def stocked(tenant):
    """Some cement in the store to issue."""
    item = tenant.post("/api/erp/items", json={
        "kind": "RM", "item_name": "Cement OPC 53", "units_of_measure": "Bags"}).json()
    po = po_order(tenant, lines=[{"description": "Cement OPC 53",
                                  "item_code": item["item_code"], "uom": "Bags",
                                  "qty": 400, "price": 390}])
    post(tenant, receipt(tenant, po))
    return item["item_code"]


def test_qty_is_accepted_like_everywhere_else(tenant):
    code = stocked(tenant)
    res = tenant.post("/api/stock-issues", json={"lines": [{"item_code": code, "qty": 50}]})
    assert res.status_code == 200, res.text
    assert len(res.json()["issue"]["lines"]) == 1
    assert res.json()["issue"]["lines"][0]["quantity"] == 50


def test_quantity_still_works(tenant):
    code = stocked(tenant)
    res = tenant.post("/api/stock-issues", json={"lines": [{"item_code": code, "quantity": 20}]})
    assert res.json()["issue"]["lines"][0]["quantity"] == 20


def test_a_note_that_would_open_empty_is_refused(tenant):
    """It must not answer "opened" and save nothing."""
    stocked(tenant)
    res = tenant.post("/api/stock-issues", json={"lines": [{"item_code": "NOPE", "qty": 5}]})
    assert res.status_code == 400
    assert "not in the item master" in res.json()["detail"]


def test_a_line_with_no_quantity_is_named(tenant):
    code = stocked(tenant)
    res = tenant.post("/api/stock-issues", json={"lines": [{"item_code": code}]})
    assert res.status_code == 400
    assert code in res.json()["detail"]


def test_a_note_may_still_be_opened_with_nothing_on_it(tenant):
    """Opening a blank note and filling it in later is ordinary."""
    assert tenant.post("/api/stock-issues", json={}).status_code == 200
