"""The hard copy of an RA bill is attached as it came on paper before it is sent for approval, and the approvers read the two together."""
import pytest

import main
import models
from test_delete_work_order import book, live_order

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(autouse=True)
def rule_on(monkeypatch):
    monkeypatch.setenv("REQUIRE_BILL_SCAN", "1")


def a_draft(tenant, qty=10):
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": qty})
    return tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]


def attach(tenant, bill, name="their_bill.pdf", data=PDF, ctype="application/pdf", amount=""):
    return tenant.post("/api/sub-bills/%d/hardcopy" % bill["id"], files={"file": (name, data, ctype)}, data={"amount": amount})


def test_a_bill_cannot_be_sent_without_the_contractors_own_bill(tenant):
    bill = a_draft(tenant)
    assert bill["scan_required"] and bill["hardcopy"] is None
    refused = tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    assert refused.status_code == 409 and "hard copy" in refused.json()["detail"]
    assert attach(tenant, bill).status_code == 200
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200


def test_the_hard_copy_is_kept_with_the_amount_it_claims_and_can_be_read_back(tenant):
    bill = a_draft(tenant)
    res = attach(tenant, bill, amount="68,000")
    assert res.status_code == 200, res.text
    h = res.json()["bill"]["hardcopy"]
    assert h["name"] == "their_bill.pdf" and h["amount"] == 68000 and h["difference"] == bill["this_bill"] - 68000
    got = tenant.get("/api/sub-bills/%d/hardcopy" % bill["id"])
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"] == "application/pdf" and got.headers["content-disposition"].startswith("inline")


def test_a_photo_of_the_bill_will_do_and_anything_else_is_refused(tenant):
    bill = a_draft(tenant)
    assert attach(tenant, bill, "photo.jpg", b"\xff\xd8\xff" + b"0" * 50, "image/jpeg").status_code == 200
    assert attach(tenant, bill, "bill.html", b"<script>1</script>", "text/html").status_code == 400
    assert attach(tenant, bill, "bill.xlsx", b"PK", "application/vnd.ms-excel").status_code == 400
    assert attach(tenant, bill, "bill.pdf", PDF, "application/pdf", amount="-5").status_code == 400


def test_attaching_again_replaces_it_and_only_one_copy_is_kept(tenant):
    bill = a_draft(tenant)
    attach(tenant, bill, "first.pdf")
    second = attach(tenant, bill, "second.pdf", PDF + b"x")
    assert second.json()["bill"]["hardcopy"]["name"] == "second.pdf"
    with main.SessionLocal() as db:
        assert db.query(models.DBFile).filter(models.DBFile.attached_type == "sub_bill_scan", models.DBFile.attached_id == bill["id"]).count() == 1


def test_it_can_be_replaced_or_removed_until_the_bill_is_paid_and_stays_when_sent_back(tenant):
    bill = a_draft(tenant)
    attach(tenant, bill, amount="68000")
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    assert attach(tenant, bill, "other.pdf").status_code == 200
    assert attach(tenant, bill, "their_bill.pdf").status_code == 200
    gone = tenant.delete("/api/sub-bills/%d/hardcopy" % bill["id"])
    assert gone.status_code == 200
    assert tenant.get("/api/sub-bills/%d" % bill["id"]).json()["hardcopy"] is None
    assert tenant.delete("/api/sub-bills/%d/hardcopy" % bill["id"]).status_code == 404
    attach(tenant, bill, "their_bill.pdf")
    back = tenant.post("/api/sub-bills/%d/reject" % bill["id"], json={"comments": "Quantities differ"}).json()["bill"]
    assert back["status"] == "DRAFT" and back["hardcopy"]["name"] == "their_bill.pdf"
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 200


def test_the_approver_is_shown_the_paper_and_told_when_the_two_disagree(tenant):
    bill = a_draft(tenant)
    attach(tenant, bill, amount="1000")
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    item = [i for i in tenant.get("/api/approvals/inbox").json()["items"] if i["kind"] == "sub_bill"][0]
    assert item["scan"].endswith("/hardcopy") and tenant.get(item["scan"]).status_code == 200
    assert item["warnings"] and "The hard copy says" in item["warnings"][0]


def test_a_matching_amount_raises_no_warning(tenant):
    bill = a_draft(tenant)
    attach(tenant, bill, amount=str(bill["this_bill"]))
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    item = [i for i in tenant.get("/api/approvals/inbox").json()["items"] if i["kind"] == "sub_bill"][0]
    assert item["warnings"] == []


def test_the_file_goes_with_the_bill_and_is_not_another_companys_to_read(tenant, second_tenant):
    bill = a_draft(tenant)
    attach(tenant, bill)
    assert second_tenant.get("/api/sub-bills/%d/hardcopy" % bill["id"]).status_code == 404
    assert tenant.delete("/api/sub-bills/%d" % bill["id"]).status_code == 200
    with main.SessionLocal() as db:
        assert db.query(models.DBFile).filter(models.DBFile.attached_type == "sub_bill_scan", models.DBFile.attached_id == bill["id"]).count() == 0


def test_removing_the_hard_copy_from_a_draft_makes_the_bill_unsendable_again(tenant):
    bill = a_draft(tenant)
    attach(tenant, bill)
    assert tenant.delete("/api/sub-bills/%d/hardcopy" % bill["id"]).status_code == 200
    assert tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={}).status_code == 409
