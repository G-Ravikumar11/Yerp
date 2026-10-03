"""Holding part of the measured work back from billing, and releasing it."""
from test_delete_work_order import book, live_order, measure


def line(tenant, order, item):
    return next(l for l in book(tenant, order["id"])["lines"] if l["item_id"] == item)


def setup(tenant, qty=100):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    measure(tenant, order["id"], item, qty)
    return order, item


def test_a_percent_of_the_work_can_be_held_and_is_left_off_the_bill(tenant):
    order, item = setup(tenant)
    res = tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "percent": 5, "reason": "Finishes and handing over"})
    assert res.status_code == 200, res.text
    assert res.json()["held"] == 5
    l = line(tenant, order, item)
    assert l["measured_to_date"] == 100 and l["held"] == 5 and l["unbilled"] == 95
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    got = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    assert [x["this_bill_qty"] for x in (got.get("bill") or got)["lines"]] == [95]


def test_the_owner_releases_it_and_the_next_bill_picks_it_up(tenant):
    order, item = setup(tenant)
    hold = tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 20, "reason": "Defects"}).json()["id"]
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    assert tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={}).status_code == 200
    rel = tenant.post("/api/sub-mb/holds/%d/release" % hold, json={"quantity": 8})
    assert rel.status_code == 200, rel.text
    l = line(tenant, order, item)
    assert l["held"] == 12 and l["unbilled"] == 8
    tenant.post("/api/sub-mb/holds/%d/release" % hold, json={})
    assert tenant.post("/api/sub-mb/holds/%d/release" % hold, json={}).status_code == 409   # nothing left
    l = line(tenant, order, item)
    assert l["held"] == 0 and l["unbilled"] == 20
    nxt = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    got = tenant.get("/api/sub-bills/%d" % nxt["id"]).json()
    assert [x["this_bill_qty"] for x in (got.get("bill") or got)["lines"]] == [20]


def test_only_unbilled_work_can_be_held_and_a_reason_is_needed(tenant):
    order, item = setup(tenant, 50)
    assert tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 5}).status_code == 400
    assert tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 60, "reason": "x"}).status_code == 409
    assert tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "percent": 150, "reason": "x"}).status_code == 400
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    assert bill
    assert tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 1, "reason": "late"}).status_code == 409


def test_holding_does_not_let_more_be_measured_than_ordered(tenant):
    order, item = setup(tenant, 100)
    ordered = line(tenant, order, item)["max_quantity"]
    tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 30, "reason": "x"})
    over = tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": ordered - 100 + 1, "measured_on": "2026-11-20"})
    assert over.status_code == 409, over.text


def test_a_hold_with_work_behind_it_cannot_be_pulled_out_from_under_it(tenant):
    order, item = setup(tenant, 100)
    hold = tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 30, "reason": "x"}).json()["id"]
    entries = book(tenant, order["id"])["entries"]
    base = next(e for e in entries if not e["kind"])
    assert tenant.delete("/api/sub-mb/entries/%d" % base["id"]).status_code == 409
    assert tenant.put("/api/sub-mb/entries/%d" % hold, json={"item_id": item, "quantity": 5}).status_code == 409
    assert tenant.delete("/api/sub-mb/entries/%d" % hold).status_code == 200            # cancelling the hold is allowed
    assert line(tenant, order, item)["held"] == 0


def test_staff_who_bill_can_hold_but_only_the_owner_releases(tenant, portal):
    from test_sub_contractor_certificate import share, staff, sign_in
    order, item = setup(tenant, 100)
    qs = staff(tenant, "planning_billing")
    share(tenant, order, qs)
    sign_in(portal, qs)
    res = portal.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "percent": 10, "reason": "Handover"})
    assert res.status_code == 200, res.text
    assert portal.post("/api/sub-mb/holds/%d/release" % res.json()["id"], json={}).status_code in (401, 403)
