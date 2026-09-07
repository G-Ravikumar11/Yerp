"""The handoffs between modules.

Every module knew its own job and none of them handed over. The BOM knew a
work order needed nine hundred bags of cement and nothing turned that into a
purchase order. A posted receipt knew exactly what arrived and at what rate,
and somebody still retyped it as a supplier bill - which is precisely where
the three figures quietly stop matching.

Both handoffs are the same idea: the next document already exists inside the
last one, so the app draws it up and a person corrects it.
"""
import uuid

from test_goods_receipt import order, receipt, set_lines, post
from test_stock_control import rm_item, receive, on_hand


def job(tenant):
    return tenant.post("/api/jobs", json={
        "name": "Vizag STP", "customer_name": "L&T"}).json()


def order_with_budget(tenant, rm_qty=1000, rm_rate=40):
    """A work order with a BOM behind it - what the job was costed on."""
    j = job(tenant)
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY %s" % uuid.uuid4().hex[:6],
         "units_of_measure": "Meters"},
        {"kind": "RM", "item_name": "CONDUIT %s" % uuid.uuid4().hex[:6],
         "units_of_measure": "Meters"}]}).json()
    fg, rm = made["codes"]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": j["id"], "lines": [{"code": fg, "qty": 1000, "rate": 100}]
    }).json()["work_order"]
    tenant.post("/api/erp/bom/build", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": fg, "rm_code": rm, "qty": rm_qty, "rate": rm_rate}]})
    return wo, rm, j


def req(tenant, wo_id):
    res = tenant.get("/api/erp/work-orders/%d/requisition" % wo_id)
    assert res.status_code == 200, res.text
    return res.json()


# --- What the budget says still has to be bought ------------------------------

def test_the_budget_becomes_a_shopping_list(tenant):
    wo, rm, _ = order_with_budget(tenant, rm_qty=1000, rm_rate=40)
    r = req(tenant, wo["id"])
    line = r["lines"][0]
    assert line["item_code"] == rm
    assert line["needed"] == 1000
    assert line["to_buy"] == 1000
    assert r["summary"]["value"] == 40000


def test_what_is_already_in_the_store_is_not_bought_again(tenant):
    wo, rm, _ = order_with_budget(tenant, rm_qty=1000, rm_rate=40)
    receive(tenant, rm, 300, 45)
    line = req(tenant, wo["id"])["lines"][0]
    assert line["in_store"] == 300
    assert line["to_buy"] == 700


def test_the_rate_the_store_actually_paid_beats_the_budget(tenant):
    """A budget rate is months old; what the last lorry cost is not."""
    wo, rm, _ = order_with_budget(tenant, rm_qty=1000, rm_rate=40)
    receive(tenant, rm, 100, 55)
    line = req(tenant, wo["id"])["lines"][0]
    assert line["budget_rate"] == 40
    assert line["rate"] == 55


def test_a_covered_line_asks_for_nothing(tenant):
    wo, rm, _ = order_with_budget(tenant, rm_qty=100, rm_rate=40)
    receive(tenant, rm, 500, 40)
    r = req(tenant, wo["id"])
    assert r["lines"][0]["covered"] is True
    assert r["lines"][0]["to_buy"] == 0
    assert r["summary"]["to_buy"] == 0


def test_an_order_with_no_budget_asks_for_nothing(tenant):
    j = job(tenant)
    fg = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "BARE %s" % uuid.uuid4().hex[:6],
         "units_of_measure": "Nos"}]}).json()["codes"][0]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": j["id"], "lines": [{"code": fg, "qty": 1, "rate": 100}]
    }).json()["work_order"]
    assert req(tenant, wo["id"])["lines"] == []


# --- Raising the order --------------------------------------------------------

def test_the_purchase_order_draws_itself_up(tenant):
    wo, rm, _ = order_with_budget(tenant, rm_qty=1000, rm_rate=40)
    res = tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                      json={"supplier_name": "Tata Steel Ltd"})
    assert res.status_code == 200, res.text
    po = res.json()["order"]
    assert po["supplier_name"] == "Tata Steel Ltd"
    assert po["total"] == 40000
    assert po["status"] == "Draft", "spending is still somebody's decision"


def test_it_lands_on_the_same_project(tenant):
    wo, rm, j = order_with_budget(tenant)
    tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                json={"supplier_name": "Steel Co"})
    row = tenant.get("/api/costs/by-project/%d" % j["id"]).json()
    assert row["committed"] == 40000


def test_raising_it_twice_does_not_buy_it_twice(tenant):
    """The second click has nothing left to ask for."""
    wo, rm, _ = order_with_budget(tenant)
    tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                json={"supplier_name": "Steel Co"})
    again = tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                        json={"supplier_name": "Steel Co"})
    assert again.status_code == 409
    assert "still needs buying" in again.json()["detail"].lower()


def test_a_covered_budget_refuses_to_raise_one(tenant):
    wo, rm, _ = order_with_budget(tenant, rm_qty=100, rm_rate=40)
    receive(tenant, rm, 500, 40)
    res = tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                      json={"supplier_name": "Steel Co"})
    assert res.status_code == 409


def test_a_supplier_is_required(tenant):
    wo, rm, _ = order_with_budget(tenant)
    assert tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                       json={"supplier_name": "  "}).status_code == 400


def test_only_the_items_asked_for_are_ordered(tenant):
    """A yard buys steel from one supplier and cement from another."""
    wo, rm, _ = order_with_budget(tenant)
    other = rm_item(tenant)
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    fg = got["lines"][0]["fg_code"]
    tenant.post("/api/erp/bom/build", json={
        "work_order_id": wo["id"], "lines": [
            {"fg_code": fg, "rm_code": rm, "qty": 1000, "rate": 40},
            {"fg_code": fg, "rm_code": other, "qty": 50, "rate": 200}]})
    po = tenant.post("/api/erp/work-orders/%d/raise-po" % wo["id"],
                     json={"supplier_name": "Steel Co",
                           "item_codes": [rm]}).json()["order"]
    assert po["total"] == 40000, "the other item was not on this order"


# --- The bill for what actually arrived ---------------------------------------

def delivered(tenant, qty=100, rate=50, received_qty=None, rejected=0):
    code = rm_item(tenant)
    po = order(tenant, lines=[{"description": "cement", "item_code": code,
                               "uom": "Nos", "qty": qty, "price": rate}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": received_qty or qty,
                             "rejected_qty": rejected}])
    post(tenant, grn)
    return grn, code


def test_the_bill_is_for_what_arrived_not_what_was_ordered(tenant):
    """Ordered 100, 80 turned up and 5 of those were broken."""
    grn, code = delivered(tenant, qty=100, rate=50, received_qty=80, rejected=5)
    res = tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    assert res.status_code == 200, res.text
    bill = res.json()["bill"]
    assert bill["total"] == 75 * 50, "accepted quantity, not ordered"
    assert bill["reference"] == grn["number"]


def test_the_bill_is_tied_to_the_order_it_settles(tenant):
    grn, code = delivered(tenant)
    bill = tenant.post("/api/grn/%d/bill" % grn["id"], json={}).json()["bill"]
    assert bill["purchase_order_id"] == grn["purchase_order_id"]


def test_a_draft_receipt_cannot_be_billed(tenant):
    """A bill for material nobody has confirmed arrived."""
    code = rm_item(tenant)
    po = order(tenant, lines=[{"description": "c", "item_code": code,
                               "uom": "Nos", "qty": 10, "price": 5}])
    grn = receipt(tenant, po)
    res = tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    assert res.status_code == 409
    assert "post the receipt first" in res.json()["detail"].lower()


def test_one_delivery_cannot_be_billed_twice(tenant):
    """How a supplier gets paid twice."""
    grn, code = delivered(tenant)
    tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    again = tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    assert again.status_code == 409
    assert "already has a bill" in again.json()["detail"].lower()


def test_a_delivery_rejected_in_full_is_not_billed(tenant):
    grn, code = delivered(tenant, qty=100, rate=50, received_qty=100,
                          rejected=100)
    res = tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    assert res.status_code == 400
    assert "nothing to pay for" in res.json()["detail"].lower()


def test_the_bill_closes_the_three_way_match(tenant):
    """Ordered, received and billed all agree because none was retyped."""
    grn, code = delivered(tenant, qty=100, rate=50)
    tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    rows = tenant.get("/api/match/three-way").json()["orders"]
    row = [r for r in rows if r["number"] == grn["purchase_order"]][0]
    assert row["ordered_value"] == row["received_value"] == row["billed_value"] == 5000
    assert row["verdict"] == "MATCHED"


def test_another_tenant_cannot_reach_either_handoff(tenant, second_tenant):
    wo, rm, _ = order_with_budget(tenant)
    grn, code = delivered(tenant)
    assert second_tenant.get(
        "/api/erp/work-orders/%d/requisition" % wo["id"]).status_code == 404
    assert second_tenant.post(
        "/api/grn/%d/bill" % grn["id"], json={}).status_code == 404
