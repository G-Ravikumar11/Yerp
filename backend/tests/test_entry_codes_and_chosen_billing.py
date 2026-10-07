"""Every measurement entry has its own code, and a bill can be drawn for chosen entries only."""
import main
import models
from test_delete_work_order import book, live_order


def setup(tenant):
    order = live_order(tenant, pay_advance=False)
    return order, book(tenant, order["id"])["lines"][0]["item_id"]


def add(tenant, order, item, qty, **extra):
    res = tenant.post("/api/sub-mb/%d/entries" % order["id"], json=dict({"item_id": item, "quantity": qty}, **extra))
    assert res.status_code == 200, res.text
    return res.json()


def entries(tenant, order):
    return sorted(book(tenant, order["id"])["entries"], key=lambda e: e["id"])


def draw(tenant, order, ids=None):
    body = {"order_id": order["id"]}
    if ids is not None:
        body["entry_ids"] = ids
    return tenant.post("/api/sub-bills", json=body)


def qty_of(bill):
    return [l["this_bill_qty"] for l in bill["lines"]]


# --- codes ---------------------------------------------------------------------------------------------------------

def test_every_entry_has_its_own_code_in_order_and_a_deleted_one_is_never_reused(tenant):
    order, item = setup(tenant)
    for q in (1, 2, 3):
        add(tenant, order, item, q)
    first = entries(tenant, order)
    assert [e["code"] for e in first] == ["%s/MB-%03d" % (order["wo_number"], n) for n in (1, 2, 3)]
    assert tenant.delete("/api/sub-mb/entries/%d" % first[2]["id"]).status_code == 200
    add(tenant, order, item, 4)
    assert entries(tenant, order)[-1]["code"].endswith("MB-004")


def test_a_hold_has_a_code_too_and_codes_are_per_order(tenant):
    order, item = setup(tenant)
    other, other_item = setup(tenant)
    add(tenant, order, item, 10)
    add(tenant, other, other_item, 5)
    assert tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 2, "reason": "x"}).status_code == 200
    codes = [e["code"] for e in entries(tenant, order)]
    assert [c.rsplit("/", 1)[1] for c in codes] == ["MB-001", "MB-002"]
    assert entries(tenant, other)[0]["code"].endswith("MB-001")


def test_entries_recorded_before_codes_existed_are_numbered_oldest_first(tenant):
    order, item = setup(tenant)
    for q in (1, 2, 3):
        add(tenant, order, item, q)
    with main.SessionLocal() as db:
        for m in db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id == order["id"]).all():
            m.code, m.code_no = "", None
        db.commit()
    main.backfill_entry_codes()
    assert [e["code"].rsplit("/", 1)[1] for e in entries(tenant, order)] == ["MB-001", "MB-002", "MB-003"]


# --- billing chosen entries --------------------------------------------------------------------------------------------

def test_a_bill_can_be_drawn_for_one_entry_and_the_rest_waits(tenant):
    order, item = setup(tenant)
    add(tenant, order, item, 3)
    add(tenant, order, item, 5)
    a, b = entries(tenant, order)
    res = draw(tenant, order, [a["id"]])
    assert res.status_code == 200, res.text
    bill = res.json()["bill"]
    assert bill["entry_mode"] == "chosen" and qty_of(bill) == [3]
    assert [(e["code"], e["quantity"]) for e in bill["entries"]] == [(a["code"], 3)]
    on = {e["id"]: e["billed"] for e in entries(tenant, order)}
    assert on == {a["id"]: True, b["id"]: False}
    # the next bill, of everything left, takes only the other entry
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    rest = draw(tenant, order).json()["bill"]
    assert rest["entry_mode"] == "" and qty_of(rest) == [5] and rest["lines"][0]["previously_billed_qty"] == 3


def test_each_entry_can_be_billed_on_its_own_bill_once(tenant):
    order, item = setup(tenant)
    add(tenant, order, item, 3)
    add(tenant, order, item, 5)
    a, b = entries(tenant, order)
    one = draw(tenant, order, [a["id"]]).json()["bill"]
    assert draw(tenant, order, [b["id"]]).status_code == 409          # one bill is still open on the order
    tenant.post("/api/sub-bills/%d/submit" % one["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % one["id"], json={})
    two = draw(tenant, order, [b["id"]])
    assert two.status_code == 200 and qty_of(two.json()["bill"]) == [5]
    assert draw(tenant, order, [a["id"]]).status_code == 409            # a is on a bill already


def test_a_chosen_entry_that_is_not_there_or_is_already_billed_is_refused(tenant):
    order, item = setup(tenant)
    add(tenant, order, item, 3)
    a = entries(tenant, order)[0]
    assert draw(tenant, order, [987654]).status_code == 404
    assert draw(tenant, order, []).status_code == 400
    bill = draw(tenant, order, [a["id"]]).json()["bill"]
    tenant.post("/api/sub-bills/%d/cancel" % bill["id"], json={"comments": "x"})
    assert draw(tenant, order, [a["id"]]).status_code == 200           # cancelling freed it


def test_a_bill_of_chosen_entries_keeps_them_when_sent_and_does_not_pick_up_new_work(tenant):
    order, item = setup(tenant)
    add(tenant, order, item, 3)
    a = entries(tenant, order)[0]
    bill = draw(tenant, order, [a["id"]]).json()["bill"]
    add(tenant, order, item, 7)                                         # measured after the draft was drawn
    sent = tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).json()["bill"]
    assert qty_of(sent) == [3]
    back = tenant.post("/api/sub-bills/%d/reject" % bill["id"], json={"comments": "check"}).json()["bill"]
    assert back["status"] == "DRAFT" and [e["id"] for e in back["entries"]] == [a["id"]]
    again = tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).json()["bill"]
    assert qty_of(again) == [3]


def test_choosing_one_block_of_a_group_takes_the_whole_group_and_its_hold(tenant):
    order, item = setup(tenant)
    dims = lambda n: [{"particulars": "Wall", "nos": 1, "length": n, "breadth": 1}]
    res = tenant.post("/api/sub-mb/%d/entries/batch" % order["id"], json={
        "item_id": item, "entries": [{"location": "A", "dimensions": dims(50), "group": "g"},
                                     {"location": "B", "dimensions": dims(40), "group": "g"}],
        "holds": [{"group": "g", "quantity": 9, "reason": "held"}]})
    assert res.status_code == 200, res.text
    add(tenant, order, item, 6, location="elsewhere")
    mine = [e for e in entries(tenant, order) if e["location"] == "A"][0]
    bill = draw(tenant, order, [mine["id"]]).json()["bill"]
    assert qty_of(bill) == [81]                                          # 50 + 40 - 9
    assert sorted(e["location"] for e in bill["entries"]) == ["A", "B", "Held back"]
    assert not [e for e in entries(tenant, order) if e["location"] == "elsewhere"][0]["billed"]


def test_an_entry_cannot_be_billed_past_what_is_left_after_a_hold_elsewhere(tenant):
    order, item = setup(tenant)
    add(tenant, order, item, 10)
    assert tenant.post("/api/sub-mb/%d/holds" % order["id"], json={"item_id": item, "quantity": 4, "reason": "x"}).status_code == 200
    work = [e for e in entries(tenant, order) if not e["kind"]][0]
    res = draw(tenant, order, [work["id"]])
    assert res.status_code == 409 and "held back" in res.json()["detail"]
    hold = [e for e in entries(tenant, order) if e["kind"] == "hold"][0]
    ok = draw(tenant, order, [work["id"], hold["id"]])
    assert ok.status_code == 200 and qty_of(ok.json()["bill"]) == [6]


def test_billing_everything_still_works_as_before(tenant):
    order, item = setup(tenant)
    add(tenant, order, item, 3)
    add(tenant, order, item, 5)
    bill = draw(tenant, order).json()["bill"]
    assert bill["entry_mode"] == "" and qty_of(bill) == [8] and len(bill["entries"]) == 2
