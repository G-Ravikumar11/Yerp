"""What actually arrived at the gate.

A purchase order says what was agreed and a bill says what is being charged.
Until now nothing recorded what came off the lorry, so the two could disagree
by any amount and nobody would know. These tests pin down the third number and
the report that puts all three side by side.
"""

import pytest

from conftest import make_employee


def project(tenant, name="Fairview plot 3"):
    return tenant.post("/api/jobs", json={
        "name": name, "customer_name": "L&T Construction"}).json()


def order(tenant, job=None, lines=None, approve=True, supplier="Steel Co"):
    """A purchase order, approved by default so it can be received against."""
    lines = lines or [{"description": "Fe500D 12mm", "item_code": "RM-STEEL",
                       "uom": "MT", "qty": 10, "price": 60000}]
    total = sum(l["qty"] * l["price"] for l in lines)
    body = {"supplier_name": supplier, "amount": total, "total": total,
            "line_items": lines}
    if job:
        body["job_id"] = job["id"]
    po = tenant.post("/api/purchase-orders", json=body).json()
    if approve:
        approved = dict(body)
        approved["status"] = "Approved"
        res = tenant.put("/api/purchase-orders/%d" % po["id"], json=approved)
        assert res.status_code == 200, res.text
    return tenant.get("/api/purchase-orders/%d" % po["id"]).json()


def receipt(tenant, po, **extra):
    body = {"purchase_order_id": po["id"]}
    body.update(extra)
    res = tenant.post("/api/grn", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def set_lines(tenant, grn, updates):
    """updates: list of dicts keyed by position in the receipt."""
    payload = []
    for i, u in enumerate(updates):
        row = dict(u)
        row["id"] = grn["lines"][i]["id"]
        payload.append(row)
    res = tenant.put("/api/grn/%d" % grn["id"], json={"lines": payload})
    assert res.status_code == 200, res.text
    return res.json()


def post(tenant, grn):
    res = tenant.post("/api/grn/%d/post" % grn["id"])
    assert res.status_code == 200, res.text
    return res.json()


def match(tenant, po):
    res = tenant.get("/api/match/three-way")
    assert res.status_code == 200, res.text
    return [r for r in res.json()["orders"]
            if r["purchase_order_id"] == po["id"]][0]


# --- Taking a delivery ------------------------------------------------------

def test_a_receipt_starts_pre_filled_with_what_is_still_to_come(tenant):
    """The storekeeper corrects the short lines; they do not retype the order."""
    grn = receipt(tenant, order(tenant))
    assert grn["status"] == "DRAFT"
    assert len(grn["lines"]) == 1
    line = grn["lines"][0]
    assert line["ordered_qty"] == 10
    assert line["previously_received"] == 0
    assert line["received_qty"] == 10, "a full delivery is the sensible default"
    assert line["accepted_qty"] == 10


def test_the_receipt_carries_the_orders_item_code_and_unit(tenant):
    """A line that is only free text cannot be counted off a lorry."""
    line = receipt(tenant, order(tenant))["lines"][0]
    assert line["item_code"] == "RM-STEEL"
    assert line["uom"] == "MT"


def test_receipts_are_numbered_in_their_own_sequence(tenant):
    po = order(tenant)
    assert receipt(tenant, po)["number"] == "GRN-0001"
    assert receipt(tenant, po)["number"] == "GRN-0002"


def test_the_supplier_and_project_come_from_the_order(tenant):
    job = project(tenant)
    grn = receipt(tenant, order(tenant, job, supplier="Tata Steel"))
    assert grn["supplier_name"] == "Tata Steel"
    assert job["name"] in grn["project"]


def test_the_suppliers_own_paperwork_is_kept(tenant):
    """Three months later a disputed bill is argued from the challan number."""
    grn = receipt(tenant, order(tenant), challan_number="DC-9912",
                  vehicle_number="AP16 TG 4471", store_location="Site store 2")
    assert grn["challan_number"] == "DC-9912"
    assert grn["vehicle_number"] == "AP16 TG 4471"
    assert grn["store_location"] == "Site store 2"


def test_nothing_may_be_received_against_an_order_nobody_approved(tenant):
    """Material arriving for a purchase that was never committed to is the
    problem the order exists to prevent."""
    po = order(tenant, approve=False)
    res = tenant.post("/api/grn", json={"purchase_order_id": po["id"]})
    assert res.status_code == 409
    assert "approved" in res.json()["detail"].lower()


def test_a_short_delivery_is_recorded_as_short(tenant):
    grn = receipt(tenant, order(tenant))
    grn = set_lines(tenant, grn, [{"received_qty": 6, "accepted_qty": 6}])
    assert grn["lines"][0]["received_qty"] == 6
    assert grn["accepted_value"] == 6 * 60000


def test_damaged_material_is_received_and_rejected_not_ignored(tenant):
    """It arrived. It has to be recorded, returned and credited, and a store
    that can only record good stock loses that argument."""
    grn = receipt(tenant, order(tenant))
    grn = set_lines(tenant, grn, [{
        "received_qty": 10, "rejected_qty": 2, "rejection_reason": "Rusted"}])
    line = grn["lines"][0]
    assert line["received_qty"] == 10
    assert line["accepted_qty"] == 8, "accepted is derived so the numbers add up"
    assert line["rejected_qty"] == 2
    assert grn["received_value"] == 600000
    assert grn["accepted_value"] == 480000
    assert grn["rejected_value"] == 120000


def test_the_figures_have_to_add_up(tenant):
    grn = receipt(tenant, order(tenant))
    res = tenant.put("/api/grn/%d" % grn["id"], json={"lines": [{
        "id": grn["lines"][0]["id"],
        "received_qty": 10, "accepted_qty": 8, "rejected_qty": 5}]})
    assert res.status_code == 400
    assert "more than arrived" in res.json()["detail"]


def test_a_receipt_of_nothing_cannot_be_posted(tenant):
    grn = receipt(tenant, order(tenant))
    set_lines(tenant, grn, [{"received_qty": 0, "accepted_qty": 0}])
    res = tenant.post("/api/grn/%d/post" % grn["id"])
    assert res.status_code == 400


# --- Posting locks it -------------------------------------------------------

def test_posting_records_who_and_when(tenant):
    out = post(tenant, receipt(tenant, order(tenant)))
    grn = out["goods_receipt"]
    assert grn["status"] == "POSTED"
    assert grn["posted_at"]
    assert grn["received_by_name"]


def test_a_posted_receipt_cannot_be_edited(tenant):
    """Somebody has asserted this is what arrived and a bill will be paid
    against it."""
    grn = post(tenant, receipt(tenant, order(tenant)))["goods_receipt"]
    res = tenant.put("/api/grn/%d" % grn["id"], json={"lines": [{
        "id": grn["lines"][0]["id"], "received_qty": 99}]})
    assert res.status_code == 409


def test_a_posted_receipt_cannot_be_deleted_only_cancelled(tenant):
    grn = post(tenant, receipt(tenant, order(tenant)))["goods_receipt"]
    res = tenant.delete("/api/grn/%d" % grn["id"])
    assert res.status_code == 409
    assert "cancel" in res.json()["detail"].lower()


def test_a_draft_may_be_discarded(tenant):
    grn = receipt(tenant, order(tenant))
    assert tenant.delete("/api/grn/%d" % grn["id"]).status_code == 200
    assert tenant.get("/api/grn/%d" % grn["id"]).status_code == 404


def test_cancelling_needs_a_reason(tenant):
    grn = post(tenant, receipt(tenant, order(tenant)))["goods_receipt"]
    assert tenant.post("/api/grn/%d/cancel" % grn["id"],
                       json={"comments": ""}).status_code == 400


def test_a_posted_receipt_cannot_be_posted_twice(tenant):
    grn = post(tenant, receipt(tenant, order(tenant)))["goods_receipt"]
    assert tenant.post("/api/grn/%d/post" % grn["id"]).status_code == 409


# --- Deliveries accumulate --------------------------------------------------

def test_the_second_delivery_only_offers_what_is_left(tenant):
    po = order(tenant)
    first = receipt(tenant, po)
    set_lines(tenant, first, [{"received_qty": 4, "accepted_qty": 4}])
    post(tenant, first)

    second = receipt(tenant, po)
    line = second["lines"][0]
    assert line["previously_received"] == 4
    assert line["received_qty"] == 6, "only the balance is still to come"


def test_a_fully_received_order_drops_off_the_open_list(tenant):
    """Offering it again invites somebody to receive the same delivery twice."""
    po = order(tenant)
    assert any(o["id"] == po["id"]
               for o in tenant.get("/api/grn/open-orders").json()["orders"])
    post(tenant, receipt(tenant, po))
    assert not any(o["id"] == po["id"]
                   for o in tenant.get("/api/grn/open-orders").json()["orders"])


def test_cancelling_a_receipt_gives_the_quantity_back(tenant):
    """The delivery did not happen, so the replacement one has to be recordable."""
    po = order(tenant)
    grn = post(tenant, receipt(tenant, po))["goods_receipt"]
    tenant.post("/api/grn/%d/cancel" % grn["id"], json={"comments": "Wrong order"})

    fresh = receipt(tenant, po)
    assert fresh["lines"][0]["previously_received"] == 0
    assert fresh["lines"][0]["received_qty"] == 10


def test_a_draft_receipt_does_not_hold_quantity_back_from_itself(tenant):
    """Its own lines must not count as already received when it is recosted."""
    po = order(tenant)
    grn = receipt(tenant, po)
    grn = set_lines(tenant, grn, [{"received_qty": 3, "accepted_qty": 3}])
    assert grn["lines"][0]["previously_received"] == 0


def test_over_receipt_is_reported_not_refused(tenant):
    """A lorry that brings more than the order is a real event, and the buyer
    needs to know before the bill turns up."""
    grn = receipt(tenant, order(tenant))
    set_lines(tenant, grn, [{"received_qty": 12, "accepted_qty": 12}])
    out = post(tenant, grn)
    assert out["goods_receipt"]["status"] == "POSTED"
    assert out["over_received"], "the excess is named"
    assert "over the order" in out["message"].lower()


# --- The order screen sees it ----------------------------------------------

def test_the_purchase_order_shows_what_has_arrived(tenant):
    po = order(tenant)
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 4, "accepted_qty": 4}])
    post(tenant, grn)
    fresh = tenant.get("/api/purchase-orders/%d" % po["id"]).json()
    assert fresh["received_total"] == 240000
    assert fresh["receipt_count"] == 1
    assert fresh["line_items"][0]["received_qty"] == 4


# --- The three-way match ----------------------------------------------------

def test_an_order_with_nothing_against_it_is_awaiting_delivery(tenant):
    assert match(tenant, order(tenant))["verdict"] == "AWAITING_DELIVERY"


def test_received_and_not_billed_is_an_accrual(tenant):
    """A cost already incurred. Left off the books it makes the month look
    cheaper than it was."""
    po = order(tenant)
    post(tenant, receipt(tenant, po))
    row = match(tenant, po)
    assert row["verdict"] == "AWAITING_BILL"
    assert row["received_value"] == 600000
    assert row["unbilled_receipts"] == 600000


def test_billed_with_nothing_received_is_flagged_before_payment(tenant):
    """The one that costs real money: an invoice for material that never came."""
    po = order(tenant)
    tenant.post("/api/bills", json={
        "number": "SUP-1", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": po["id"]})
    row = match(tenant, po)
    assert row["verdict"] == "AWAITING_RECEIPT"
    assert "check the gate" in row["note"].lower()


def test_billed_for_more_than_arrived_is_the_first_thing_reported(tenant):
    po = order(tenant)
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 6, "accepted_qty": 6}])
    post(tenant, grn)
    tenant.post("/api/bills", json={
        "number": "SUP-2", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": po["id"]})
    row = match(tenant, po)
    assert row["verdict"] == "OVER_BILLED"
    assert "do not pay" in row["note"].lower()


def test_the_three_agreeing_is_a_match(tenant):
    po = order(tenant)
    post(tenant, receipt(tenant, po))
    tenant.post("/api/bills", json={
        "number": "SUP-3", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": po["id"]})
    assert match(tenant, po)["verdict"] == "MATCHED"


def test_a_rejected_bill_is_not_a_claim_on_anything(tenant):
    """Counting it would make an order look billed when nobody has been paid."""
    po = order(tenant)
    post(tenant, receipt(tenant, po))
    bill = tenant.post("/api/bills", json={
        "number": "SUP-4", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": po["id"],
        "status": "Rejected"}).json()
    assert bill["id"]
    assert match(tenant, po)["verdict"] == "AWAITING_BILL"


def test_the_summary_totals_the_exceptions(tenant):
    po = order(tenant)
    tenant.post("/api/bills", json={
        "number": "SUP-5", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": po["id"]})
    summary = tenant.get("/api/match/three-way").json()["summary"]
    assert summary["exceptions"] >= 1
    assert summary["billed_value"] >= 600000


def test_only_exceptions_hides_the_orders_that_are_fine(tenant):
    good = order(tenant)
    post(tenant, receipt(tenant, good))
    tenant.post("/api/bills", json={
        "number": "SUP-6", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": good["id"]})
    rows = tenant.get("/api/match/three-way?only_exceptions=true").json()["orders"]
    assert not any(r["purchase_order_id"] == good["id"] for r in rows)


def test_the_match_can_be_read_line_by_line(tenant):
    po = order(tenant, lines=[
        {"description": "Fe500D 12mm", "item_code": "RM-STEEL", "uom": "MT",
         "qty": 10, "price": 60000},
        {"description": "Cement OPC53", "item_code": "RM-CEM", "uom": "Bags",
         "qty": 100, "price": 400}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 10, "accepted_qty": 10},
                            {"received_qty": 60, "accepted_qty": 60}])
    post(tenant, grn)
    d = tenant.get("/api/match/three-way/%d" % po["id"]).json()
    steel = [l for l in d["lines"] if l["item_code"] == "RM-STEEL"][0]
    cement = [l for l in d["lines"] if l["item_code"] == "RM-CEM"][0]
    assert steel["received_qty"] == 10
    assert cement["received_qty"] == 60
    assert cement["received_value"] == 24000
    assert d["goods_receipts"][0]["number"] == grn["number"]


def test_a_bill_line_can_name_the_order_line_it_settles(tenant):
    """Without it the totals still compare; the per line figures do not."""
    po = order(tenant)
    po_line = po["line_items"][0]["id"]
    post(tenant, receipt(tenant, po))
    tenant.post("/api/bills", json={
        "number": "SUP-7", "vendor_name": "Steel Co", "total": 600000,
        "amount": 600000, "purchase_order_id": po["id"],
        "line_items": [{"description": "Fe500D 12mm", "qty": 10,
                        "price": 60000, "po_line_id": po_line}]})
    d = tenant.get("/api/match/three-way/%d" % po["id"]).json()
    assert d["line_level_available"] is True
    assert d["lines"][0]["billed_qty"] == 10
    assert d["lines"][0]["verdict"] == "MATCHED"


def test_a_bill_line_cannot_claim_against_somebody_elses_order(tenant):
    """Exactly the mismatch the match report exists to catch."""
    mine = order(tenant)
    other = order(tenant, supplier="Rival Supplies")
    tenant.post("/api/bills", json={
        "number": "SUP-8", "vendor_name": "Steel Co", "total": 1000,
        "amount": 1000, "purchase_order_id": mine["id"],
        "line_items": [{"description": "x", "qty": 1, "price": 1000,
                        "po_line_id": other["line_items"][0]["id"]}]})
    d = tenant.get("/api/match/three-way/%d" % other["id"]).json()
    assert d["lines"][0]["billed_qty"] == 0, "the link was refused"


def test_bill_line_items_are_saved_at_all(tenant):
    """They were accepted and thrown away, so a saved bill came back blank."""
    bill = tenant.post("/api/bills", json={
        "number": "SUP-9", "vendor_name": "Steel Co", "total": 5000,
        "amount": 5000,
        "line_items": [{"description": "Sand", "qty": 5, "price": 1000}]}).json()
    fetched = tenant.get("/api/bills/%d" % bill["id"]).json()
    assert len(fetched["line_items"]) == 1
    assert fetched["line_items"][0]["description"] == "Sand"


# --- Who may do it ----------------------------------------------------------

def test_receiving_is_its_own_permission(tenant, portal):
    """Whoever is at the gate is not the person who raised the order and never
    the one who pays the bill. Three signatures, kept apart."""
    emp = make_employee(tenant, permission_role="staff", password="Crew1234")
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    po = order(tenant)

    assert portal.post("/api/employee/auth/login", json={
        "email": emp["email"], "password": "Crew1234"}).status_code == 200
    assert portal.post("/api/grn", json={
        "purchase_order_id": po["id"]}).status_code == 403

    # The owner grants it for this one person, and the same request goes through.
    tenant.put("/api/employees/%d/permissions" % emp["id"], json={
        "permission_role": "staff",
        "permissions": ["self.service", "bills.submit", "stores.receive"]})
    assert portal.post("/api/grn", json={
        "purchase_order_id": po["id"]}).status_code == 200


def test_another_business_cannot_see_the_receipt(tenant, second_tenant):
    grn = receipt(tenant, order(tenant))
    assert second_tenant.get("/api/grn/%d" % grn["id"]).status_code in (403, 404)


def test_the_receipt_downloads_as_a_spreadsheet(tenant):
    grn = post(tenant, receipt(tenant, order(tenant)))["goods_receipt"]
    res = tenant.get("/api/grn/%d/export.xlsx" % grn["id"])
    assert res.status_code == 200
    assert res.content[:2] == b"PK", "a real xlsx, not an error page"
