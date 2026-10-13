"""An amended work order carries on the running account of the one it replaces.

The book says "amend the order to measure beyond it". The revision used to
start again at nothing - no measurements, no bills - so the gang's next bill
had nothing previously billed and work already paid for could be billed again.
"""
import copy

from conftest import fund_order
from test_subcontract_orders import BOQ
from test_subcontractor_bills import live_order, book, measure, raise_bill


def certified_bill(tenant, order_id, item_id, qty):
    measure(tenant, order_id, item_id, qty)
    bill = raise_bill(tenant, order_id).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    res = tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    assert res.status_code == 200, res.text
    return bill


def revise(tenant, order_id, boq):
    rev = tenant.post("/api/wo/orders/%d/amend" % order_id, json={})
    assert rev.status_code == 200, rev.text
    rev = rev.json()["order"]
    put = tenant.put("/api/wo/orders/%d/boq" % rev["id"], json=boq)
    assert put.status_code == 200, put.text
    fund_order(tenant, put.json()["order"])
    sent = tenant.post("/api/wo/orders/%d/submit" % rev["id"], json={})
    assert sent.status_code == 200, sent.text
    return rev


def approve(tenant, order_id):
    return tenant.post("/api/wo/orders/%d/approve" % order_id,
                       json={"override": True, "comments": "More slab than drawn"})


def test_the_revision_continues_the_book_and_the_bills(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    certified_bill(tenant, order["id"], item, 250)       # the whole ordered quantity
    more = copy.deepcopy(BOQ)
    more["lines"][0]["quantity"] = 300
    rev = revise(tenant, order["id"], more)
    inbox = tenant.get("/api/approvals/inbox").json()["items"]
    row = next(i for i in inbox if i["kind"] == "subcontract_order" and i["id"] == rev["id"])
    assert any("move to this order on approval" in w for w in row["warnings"]), row["warnings"]
    res = approve(tenant, rev["id"])
    assert res.status_code == 200, res.text

    b = book(tenant, rev["id"])
    line = next(l for l in b["lines"] if l["activity_no"] == "1.0")
    assert line["measured_to_date"] == 250, "the book came across"

    new_item = line["item_id"]
    measure(tenant, rev["id"], new_item, 30)
    nxt = raise_bill(tenant, rev["id"])
    assert nxt.status_code == 200, nxt.text
    nxt = nxt.json()["bill"]
    assert nxt["number"].endswith("/RA-02"), "the numbering carries on"
    first = next(l for l in nxt["lines"] if l["activity_no"] == "1.0")
    assert first["previously_billed_qty"] == 250
    assert first["this_bill_qty"] == 30, "only the new work is billed, not the 250 again"
    assert nxt["previously_billed"] == 250 * 6800

    original = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]
    assert original["status"] == "AMENDED"


def test_the_original_stays_open_until_the_revision_is_approved(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    revise(tenant, order["id"], BOQ)
    measure(tenant, order["id"], item, 10)      # would 409 if the original were frozen


def test_a_revision_cannot_drop_a_line_already_measured(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 50)
    only_steel = {"lines": [BOQ["lines"][1]]}
    rev = revise(tenant, order["id"], only_steel)
    res = approve(tenant, rev["id"])
    assert res.status_code == 409
    assert "not on the revision" in res.json()["detail"]


def test_a_revision_cannot_order_less_than_is_measured(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 200)
    less = copy.deepcopy(BOQ)
    less["lines"][0]["quantity"] = 150
    rev = revise(tenant, order["id"], less)
    res = approve(tenant, rev["id"])
    assert res.status_code == 409
    assert "less than is already measured" in res.json()["detail"]


def test_an_open_bill_on_the_original_holds_the_revision(tenant):
    order = live_order(tenant)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 20)
    raise_bill(tenant, order["id"])
    rev = revise(tenant, order["id"], BOQ)
    res = approve(tenant, rev["id"])
    assert res.status_code == 409
    assert "still open" in res.json()["detail"]


def test_an_order_with_bills_or_measurements_is_not_cancelled(tenant):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, 5)
    res = tenant.post("/api/wo/orders/%d/cancel" % order["id"], json={"comments": "Gang left"})
    assert res.status_code == 409
    assert "measured" in res.json()["detail"]

    certified_bill(tenant, order["id"], item, 5)
    res = tenant.post("/api/wo/orders/%d/cancel" % order["id"], json={"comments": "Gang left"})
    assert res.status_code == 409
    assert "RA bills" in res.json()["detail"]
