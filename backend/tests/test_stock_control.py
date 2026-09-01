"""Stock: what is in the store, what went to site, and what it cost.

The item master said what may be bought and the goods receipt said what
arrived. Nothing said what was left, so material could be received, paid for
and quietly walk off without a figure changing anywhere in the app.

The rule underneath all of this is that stock only ever moves by a signed row
being written. There is no other door, which is what makes the balance
trustworthy and a miscount recoverable.
"""
import uuid

from test_goods_receipt import order, receipt, set_lines, post
from test_measurement_and_ra_bills import placed_order


def rm_item(tenant, name=None, uom="Nos"):
    res = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "RM", "item_name": name or ("RM %s" % uuid.uuid4().hex[:6]),
         "units_of_measure": uom}]})
    assert res.status_code == 200, res.text
    return res.json()["codes"][0]


def receive(tenant, code, qty, rate, rejected=0):
    """Book material in the way the app really does - through a receipt."""
    po = order(tenant, lines=[{"description": "material", "item_code": code,
                               "uom": "Nos", "qty": qty, "price": rate}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": qty, "rejected_qty": rejected}])
    post(tenant, grn)
    return grn


def on_hand(tenant, code):
    rows = tenant.get("/api/stock").json()["stock"]
    hit = [r for r in rows if r["item_code"] == code]
    return hit[0] if hit else None


# --- Receiving is what creates stock -----------------------------------------

def test_nothing_is_in_the_store_to_begin_with(tenant):
    assert tenant.get("/api/stock").json()["stock"] == []


def test_posting_a_receipt_books_the_material_in(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    s = on_hand(tenant, code)
    assert s["on_hand"] == 100
    assert s["rate"] == 50
    assert s["value"] == 5000


def test_rejected_material_never_enters_the_store(tenant):
    """It was never accepted, so it must not have to be found and removed."""
    code = rm_item(tenant)
    receive(tenant, code, 100, 50, rejected=30)
    assert on_hand(tenant, code)["on_hand"] == 70


def test_a_draft_receipt_is_not_stock_yet(tenant):
    code = rm_item(tenant)
    po = order(tenant, lines=[{"description": "m", "item_code": code,
                               "uom": "Nos", "qty": 10, "price": 5}])
    receipt(tenant, po)          # opened, never posted
    assert on_hand(tenant, code) is None


def test_cancelling_a_posted_receipt_takes_it_back_out(tenant):
    code = rm_item(tenant)
    grn = receive(tenant, code, 100, 50)
    tenant.post("/api/grn/%d/cancel" % grn["id"], json={"comments": "wrong order"})
    assert on_hand(tenant, code)["on_hand"] == 0


def test_two_deliveries_at_different_prices_average_out(tenant):
    """One heap in the yard has one rate, not whichever was paid last."""
    code = rm_item(tenant)
    receive(tenant, code, 100, 40)
    receive(tenant, code, 100, 60)
    s = on_hand(tenant, code)
    assert s["on_hand"] == 200
    assert s["rate"] == 50          # not 60
    assert s["value"] == 10000


# --- Issuing to site ----------------------------------------------------------

def test_issuing_takes_it_out_and_prices_it_from_the_store(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    wo = placed_order(tenant)
    made = tenant.post("/api/stock-issues", json={
        "work_order_id": wo["id"], "issued_to": "Ganger Raju",
        "lines": [{"item_code": code, "quantity": 30}]}).json()["issue"]
    # Rate is taken from the store, not typed in.
    assert made["lines"][0]["rate"] == 50
    assert made["total_value"] == 1500

    tenant.post("/api/stock-issues/%d/post" % made["id"], json={})
    assert on_hand(tenant, code)["on_hand"] == 70


def test_a_draft_issue_has_not_moved_anything(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    tenant.post("/api/stock-issues", json={
        "lines": [{"item_code": code, "quantity": 30}]})
    assert on_hand(tenant, code)["on_hand"] == 100


def test_issuing_more_than_is_there_is_refused(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 10, 50)
    issue = tenant.post("/api/stock-issues", json={
        "lines": [{"item_code": code, "quantity": 40}]}).json()["issue"]
    res = tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    assert res.status_code == 409
    assert "not enough in the store" in res.json()["detail"].lower()
    assert on_hand(tenant, code)["on_hand"] == 10


def test_a_store_that_is_behind_can_still_be_forced(tenant):
    """Material really has gone even when the paperwork has not caught up."""
    code = rm_item(tenant)
    receive(tenant, code, 10, 50)
    issue = tenant.post("/api/stock-issues", json={
        "lines": [{"item_code": code, "quantity": 40}]}).json()["issue"]
    res = tenant.post("/api/stock-issues/%d/post" % issue["id"],
                      json={"allow_negative": True})
    assert res.status_code == 200
    s = on_hand(tenant, code)
    assert s["on_hand"] == -30
    assert s["negative"] is True


def test_a_posted_issue_cannot_be_edited(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    issue = tenant.post("/api/stock-issues", json={
        "lines": [{"item_code": code, "quantity": 10}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    res = tenant.put("/api/stock-issues/%d" % issue["id"], json={
        "lines": [{"item_code": code, "quantity": 90}]})
    assert res.status_code == 409
    assert on_hand(tenant, code)["on_hand"] == 90


def test_cancelling_an_issue_puts_the_material_back(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    issue = tenant.post("/api/stock-issues", json={
        "lines": [{"item_code": code, "quantity": 30}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    tenant.post("/api/stock-issues/%d/cancel" % issue["id"], json={})
    assert on_hand(tenant, code)["on_hand"] == 100


# --- Counting and correcting --------------------------------------------------

def test_a_physical_count_posts_the_difference(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    out = tenant.post("/api/stock/adjustments", json={
        "item_code": code, "counted": 94, "remarks": "Month end count"}).json()
    assert out["difference"] == -6
    assert on_hand(tenant, code)["on_hand"] == 94


def test_a_count_that_agrees_posts_nothing(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    out = tenant.post("/api/stock/adjustments", json={
        "item_code": code, "counted": 100}).json()
    assert out["difference"] == 0
    assert len(tenant.get("/api/stock/%s/ledger" % code).json()["movements"]) == 1


def test_the_ledger_shows_every_movement_with_a_running_balance(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    issue = tenant.post("/api/stock-issues", json={
        "lines": [{"item_code": code, "quantity": 30}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    led = tenant.get("/api/stock/%s/ledger" % code).json()
    assert led["on_hand"] == 70
    # Newest first, so the balance column reads 70 then 100.
    assert [m["balance"] for m in led["movements"]] == [70, 100]
    assert [m["kind"] for m in led["movements"]] == ["ISSUE", "RECEIPT"]
    # Every row can be traced back to the document that caused it.
    assert led["movements"][0]["source_ref"].startswith("ISS-")
    assert led["movements"][1]["source_ref"].startswith("GRN-")


def test_reorder_levels_only_warn_when_somebody_set_one(tenant):
    quiet = rm_item(tenant)
    watched = rm_item(tenant)
    receive(tenant, quiet, 1, 10)
    receive(tenant, watched, 5, 10)
    item = [i for i in tenant.get("/api/erp/items").json()["items"]
            if i["item_code"] == watched][0]
    # The endpoint takes a whole item, not a patch, so the rest goes back
    # unchanged alongside the level being set.
    res = tenant.put("/api/erp/items/%d" % item["id"], json={
        "kind": "RM", "item_name": item["item_name"],
        "units_of_measure": item["units_of_measure"], "reorder_level": 20})
    assert res.status_code == 200, res.text

    rows = tenant.get("/api/stock?low_only=true").json()["stock"]
    codes = [r["item_code"] for r in rows]
    assert watched in codes
    assert quiet not in codes           # no level set, so it stays quiet


# --- What the job was costed on, against what it drew -------------------------

def test_consumption_compares_the_bom_with_what_was_issued(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    bom = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    rm = bom["bom"][0]["rm_code"] if bom.get("bom") else None
    assert rm, "the fixture builds a BOM"

    receive(tenant, rm, 1200, 40)
    issue = tenant.post("/api/stock-issues", json={
        "work_order_id": wo["id"],
        "lines": [{"item_code": rm, "quantity": 1150}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})

    c = tenant.get("/api/stock/consumption/%d" % wo["id"]).json()
    line = [l for l in c["lines"] if l["item_code"] == rm][0]
    assert line["planned_qty"] == 1000
    assert line["issued_qty"] == 1150
    assert line["variance_qty"] == 150          # 150 more than it was costed on
    assert line["over_consumed"] is True
    assert c["summary"]["lines_over_consumed"] == 1


def test_material_drawn_that_was_never_budgeted_is_flagged(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    stray = rm_item(tenant)
    receive(tenant, stray, 50, 100)
    issue = tenant.post("/api/stock-issues", json={
        "work_order_id": wo["id"],
        "lines": [{"item_code": stray, "quantity": 20}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})

    c = tenant.get("/api/stock/consumption/%d" % wo["id"]).json()
    line = [l for l in c["lines"] if l["item_code"] == stray][0]
    assert line["unplanned"] is True
    assert line["planned_qty"] == 0
    assert c["summary"]["unplanned_items"] == 1


def test_a_cancelled_issue_costs_the_job_nothing(tenant):
    wo = placed_order(tenant, qty=1000, rate=60)
    stray = rm_item(tenant)
    receive(tenant, stray, 50, 100)
    issue = tenant.post("/api/stock-issues", json={
        "work_order_id": wo["id"],
        "lines": [{"item_code": stray, "quantity": 20}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    tenant.post("/api/stock-issues/%d/cancel" % issue["id"], json={})

    c = tenant.get("/api/stock/consumption/%d" % wo["id"]).json()
    line = [l for l in c["lines"] if l["item_code"] == stray][0]
    assert line["issued_qty"] == 0
    assert line["issued_value"] == 0


# --- Boundaries ---------------------------------------------------------------

def test_stock_downloads_as_a_workbook(tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    res = tenant.get("/api/stock.xlsx")
    assert res.status_code == 200
    assert res.content[:2] == b"PK"


def test_another_tenant_sees_none_of_this_stock(tenant, second_tenant):
    code = rm_item(tenant)
    receive(tenant, code, 100, 50)
    assert second_tenant.get("/api/stock").json()["stock"] == []
    assert second_tenant.get("/api/stock/%s/ledger" % code).json()["movements"] == []
