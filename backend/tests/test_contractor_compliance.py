"""A contractor is safe to pay only while their papers are in order; what is charged back comes off their next bill;
and a finished order says plainly whether anything is still owed."""
from datetime import date, timedelta

import main
from app import models
from test_delete_work_order import book, live_order


def a_draft(tenant, qty=10):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": qty})
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    return order, bill


def day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()


def doc(tenant, contractor_id, kind, valid_to):
    return tenant.post("/api/compliance/documents", json={"contractor_id": contractor_id, "kind": kind, "valid_to": valid_to})


def test_a_contractor_with_no_papers_is_flagged_and_complete_papers_clear_it(tenant):
    order, bill = a_draft(tenant)
    cid = bill["contractor_id"] if "contractor_id" in bill else order["contractor_id"]
    status = tenant.get("/api/compliance/contractors/%d" % cid).json()
    assert status["ok"] is False and len(status["warnings"]) == 4
    for kind in ("labour_licence", "pf", "esi", "insurance"):
        assert doc(tenant, cid, kind, day(400)).status_code == 200
    status = tenant.get("/api/compliance/contractors/%d" % cid).json()
    assert status["ok"] is True and status["warnings"] == []


def test_a_lapsed_licence_blocks_and_one_running_out_only_warns(tenant):
    order, bill = a_draft(tenant)
    cid = order["contractor_id"]
    for kind in ("pf", "esi", "insurance"):
        doc(tenant, cid, kind, day(400))
    doc(tenant, cid, "labour_licence", day(-3))
    status = tenant.get("/api/compliance/contractors/%d" % cid).json()
    assert status["ok"] is False and "ran out" in status["warnings"][0]
    doc(tenant, cid, "labour_licence", day(12))                  # renewed, but only just
    status = tenant.get("/api/compliance/contractors/%d" % cid).json()
    assert status["ok"] is True and "runs out in" in status["warnings"][0]


def test_the_bill_shows_the_contractors_warnings(tenant):
    order, bill = a_draft(tenant)
    detail = tenant.get("/api/sub-bills/%d" % bill["id"]).json()
    assert any("not on record" in w for w in detail["compliance_warnings"])


def test_a_back_charge_comes_off_the_bill_and_goes_back_when_taken_off(tenant):
    order, bill = a_draft(tenant)
    cid = order["contractor_id"]
    net_before = bill["net_payable"]
    made = tenant.post("/api/back-charges", json={"contractor_id": cid, "order_id": order["id"], "kind": "Wastage",
                                                   "reason": "Cement wasted beyond the allowance", "amount": 100})
    assert made.status_code == 200, made.text
    charge = made.json()["back_charge"]
    assert charge["status"] == "OPEN" and charge["number"].startswith("BC-")

    on = tenant.post("/api/sub-bills/%d/back-charges" % bill["id"], json={"ids": [charge["id"]]})
    assert on.status_code == 200, on.text
    billed = on.json()["bill"]
    assert billed["back_charges"] == 100 and billed["net_payable"] == net_before - 100
    assert billed["applied_back_charges"][0]["number"] == charge["number"]
    # taken twice, or taken by another bill, is refused
    assert tenant.post("/api/sub-bills/%d/back-charges" % bill["id"], json={"ids": [charge["id"]]}).status_code == 409

    off = tenant.delete("/api/sub-bills/%d/back-charges/%d" % (bill["id"], charge["id"]))
    assert off.status_code == 200
    assert off.json()["bill"]["back_charges"] == 0 and off.json()["bill"]["net_payable"] == net_before
    assert tenant.get("/api/back-charges?status=OPEN").json()["back_charges"][0]["status"] == "OPEN"


def test_a_back_charge_must_be_for_something_and_cannot_be_nothing(tenant):
    order, bill = a_draft(tenant)
    cid = order["contractor_id"]
    assert tenant.post("/api/back-charges", json={"contractor_id": cid, "reason": "x", "amount": 0}).status_code == 400
    assert tenant.post("/api/back-charges", json={"contractor_id": cid, "reason": " ", "amount": 5}).status_code == 400


def test_a_cancelled_bill_gives_its_back_charges_back(tenant):
    order, bill = a_draft(tenant)
    cid = order["contractor_id"]
    charge = tenant.post("/api/back-charges", json={"contractor_id": cid, "reason": "Damaged hoarding", "amount": 50}).json()["back_charge"]
    tenant.post("/api/sub-bills/%d/back-charges" % bill["id"], json={"ids": [charge["id"]]})
    assert tenant.post("/api/sub-bills/%d/cancel" % bill["id"], json={"comments": "redo"}).status_code == 200
    assert tenant.get("/api/back-charges?status=OPEN").json()["back_charges"][0]["number"] == charge["number"]


def test_another_contractors_back_charge_cannot_go_on_this_bill(tenant):
    order, bill = a_draft(tenant)
    other = tenant.post("/api/wo/contractors", json={"company_name": "Somebody Else", "pan": "AAAPB1234C",
                                                     "gst_number": "36AAAPB1234C1Z5"}).json()
    charge = tenant.post("/api/back-charges", json={"contractor_id": other["id"], "reason": "Not theirs", "amount": 10}).json()["back_charge"]
    refused = tenant.post("/api/sub-bills/%d/back-charges" % bill["id"], json={"ids": [charge["id"]]})
    assert refused.status_code == 400 and "another contractor" in refused.json()["detail"]


def test_ratings_average_and_stay_between_one_and_five(tenant):
    order, bill = a_draft(tenant)
    cid = order["contractor_id"]
    assert tenant.post("/api/compliance/ratings", json={"contractor_id": cid, "quality": 6}).status_code == 400
    tenant.post("/api/compliance/ratings", json={"contractor_id": cid, "bill_id": bill["id"], "quality": 5, "speed": 3, "safety": 4, "discipline": 4})
    tenant.post("/api/compliance/ratings", json={"contractor_id": cid, "quality": 3, "speed": 3, "safety": 4, "discipline": 2})
    score = tenant.get("/api/compliance/contractors/%d" % cid).json()["score"]
    assert score["count"] == 2 and score["quality"] == 4.0 and score["overall"] == 3.5


def test_an_order_with_open_bills_or_open_charges_cannot_be_closed(tenant):
    order, bill = a_draft(tenant)
    s = tenant.get("/api/subcontract-orders/%d/settlement" % order["id"]).json()
    assert s["can_close"] is False and s["open_bills"] == 1
    tenant.post("/api/sub-bills/%d/cancel" % bill["id"], json={"comments": "none"})
    assert tenant.get("/api/subcontract-orders/%d/settlement" % order["id"]).json()["can_close"] is True
    tenant.post("/api/back-charges", json={"contractor_id": order["contractor_id"], "order_id": order["id"], "reason": "Clean-up", "amount": 20})
    assert tenant.get("/api/subcontract-orders/%d/settlement" % order["id"]).json()["can_close"] is False


def test_one_company_cannot_see_anothers_contractors(tenant, second_tenant):
    order, bill = a_draft(tenant)
    assert second_tenant.get("/api/compliance/contractors/%d" % order["contractor_id"]).status_code == 404
    assert second_tenant.post("/api/back-charges", json={"contractor_id": order["contractor_id"], "reason": "x", "amount": 5}).status_code == 404
