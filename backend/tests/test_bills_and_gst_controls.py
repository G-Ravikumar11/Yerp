"""Supplier bills and GST, held to what the books and the returns need.

A bill approved or paid against kept being editable - its amount, its supplier, its order - and its status and amount
paid could be typed in. The same supplier invoice could be entered twice and paid twice. A total that was not the
amount plus the tax was stored as given. Bills on one order were checked against it one at a time. The outward
register left the tax invoices out, the inward one guessed every split and counted bills still waiting on an
approver, a GSTIN was checked for its length only, and anyone in the company login could change ours. An e-way bill
was cancellable two days on and silently; an IRN's document number could be registered again after cancelling.
"""
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from app import models
from app.db.session import SessionLocal
from conftest import make_invoice
from test_finance_ledger import supplier_bill

OUR_GSTIN = "36AABCY1234H1ZI"


def set_bill(bill_id, **values):
    db = SessionLocal()
    try:
        db.query(models.DBBill).filter(models.DBBill.id == bill_id).update(values)
        db.commit()
    finally:
        db.close()


def new_bill(tenant, **body):
    payload = {"number": "NB-" + uuid.uuid4().hex[:6], "vendor_name": "Ramco Cements", "amount": 1000,
               "tax_amount": 180, "total": 1180, "status": "Awaiting Payment"}
    payload.update(body)
    return tenant.post("/api/bills", json=payload)


# --- 1. Approved or paid: what it says stays said -----------------------------------------------

def test_an_approved_bill_keeps_its_amount_supplier_and_order(tenant):
    b = supplier_bill(tenant)
    set_bill(b["id"], approval_status="approved", status="Approved for payment")
    for change in ({"amount": 1, "total": 18001}, {"vendor_name": "Someone Else"}, {"number": "X-1"},
                   {"issue_date": "2020-01-01"}, {"job_id": 999}):
        res = tenant.put("/api/bills/%d" % b["id"], json=change)
        assert res.status_code == 409, (change, res.text)
    # The harmless ones still change.
    res = tenant.put("/api/bills/%d" % b["id"], json={"notes": "checked", "due_date": "2030-01-01", "category": "materials"})
    assert res.status_code == 200, res.text
    got = tenant.get("/api/bills/%d" % b["id"]).json()
    assert got["notes"] == "checked" and got["vendor_name"] == "ACC Ltd" and got["amount"] == 100000


def test_a_bill_paid_against_is_locked_too(tenant):
    b = supplier_bill(tenant)
    paid = tenant.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": b["id"], "amount": 500, "mode": "Cash"})
    assert paid.status_code == 200, paid.text
    assert tenant.put("/api/bills/%d" % b["id"], json={"amount": 90000, "total": 108000}).status_code == 409


def test_status_and_amount_paid_are_never_typed_in(tenant):
    b = supplier_bill(tenant)
    assert tenant.put("/api/bills/%d" % b["id"], json={"status": "Paid"}).status_code == 409
    assert tenant.put("/api/bills/%d" % b["id"], json={"amount_paid": 118000}).status_code == 409
    got = tenant.get("/api/bills/%d" % b["id"]).json()
    assert got["status"] == "Awaiting Payment" and got["amount_paid"] == 0
    # The form sends the whole bill back unchanged: that is not a change.
    assert tenant.put("/api/bills/%d" % b["id"], json={**got, "notes": "ok"}).status_code == 200


def test_the_master_still_accepts_a_draft_and_edits_it_freely(tenant):
    d = new_bill(tenant, status="Draft").json()
    assert tenant.put("/api/bills/%d" % d["id"], json={"amount": 2000, "tax_amount": 360, "total": 2360}).status_code == 200
    assert tenant.put("/api/bills/%d" % d["id"], json={"status": "Awaiting Payment"}).status_code == 200
    assert tenant.get("/api/bills/%d" % d["id"]).json()["status"] == "Awaiting Payment"


# --- 2. The same supplier invoice once ----------------------------------------------------------

def test_the_same_supplier_invoice_is_not_entered_twice(tenant):
    assert new_bill(tenant, reference="INV/2291").status_code == 200
    again = new_bill(tenant, vendor_name="RAMCO  CEMENTS.", reference="inv/2291")
    assert again.status_code == 409 and "paid twice" in again.json()["detail"]
    # Another supplier's invoice of that number is theirs.
    assert new_bill(tenant, vendor_name="Birla", reference="INV/2291").status_code == 200


def test_a_rejected_copy_does_not_block_the_real_one(tenant):
    first = new_bill(tenant, reference="R-7").json()
    set_bill(first["id"], status="Rejected")
    assert new_bill(tenant, reference="R-7").status_code == 200


def test_renaming_to_a_number_in_use_is_a_conflict_not_a_crash(tenant):
    a = new_bill(tenant, number="DUP-A", status="Draft").json()
    new_bill(tenant, number="DUP-B", status="Draft")
    res = tenant.put("/api/bills/%d" % a["id"], json={"number": "DUP-B"})
    assert res.status_code == 409


# --- 3. Figures that add up ---------------------------------------------------------------------

def test_the_total_is_the_amount_plus_the_tax(tenant):
    assert new_bill(tenant, total=5000).status_code == 400
    assert new_bill(tenant, amount=-10, total=170).status_code == 400
    assert new_bill(tenant, tax_amount=-1, total=999).status_code == 400
    assert new_bill(tenant, total=1180.6).status_code == 200            # rounding is allowed for


def test_the_lines_come_to_the_amount(tenant):
    bad = new_bill(tenant, line_items=[{"description": "OPC 53", "qty": 2, "price": 400}])
    assert bad.status_code == 400 and "lines come to" in bad.json()["detail"]
    ok = new_bill(tenant, line_items=[{"description": "OPC 53", "qty": 2, "price": 500}])
    assert ok.status_code == 200
    line = tenant.get("/api/bills/%d" % ok.json()["id"]).json()["line_items"][0]
    assert "20" not in line["tax_rate"] and "18" in line["tax_rate"]


# --- 4. The order, all its bills together -------------------------------------------------------

def test_bills_on_one_order_are_added_up(tenant):
    from test_goods_receipt import order
    po = order(tenant)                                     # 6,00,000
    first = new_bill(tenant, vendor_name="Steel Co", amount=400000, tax_amount=0, total=400000, purchase_order_id=po["id"])
    assert first.status_code == 200 and not first.json()["warnings"]
    second = new_bill(tenant, vendor_name="Steel Co", amount=300000, tax_amount=0, total=300000, purchase_order_id=po["id"])
    assert second.status_code == 200
    assert any("more than the order" in w for w in second.json()["warnings"])
    db = SessionLocal()
    try:
        from app.services.approvals import bill_exceeds_its_order
        b = db.query(models.DBBill).filter(models.DBBill.id == second.json()["id"]).first()
        assert bill_exceeds_its_order(db, b, "bill") is True
    finally:
        db.close()


def test_billing_past_what_was_received_is_said(tenant):
    from test_goods_receipt import order, post, receipt, set_lines
    po = order(tenant)
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 6, "accepted_qty": 6}])
    post(tenant, grn)                                       # 3,60,000 received
    res = new_bill(tenant, vendor_name="Steel Co", amount=600000, tax_amount=0, total=600000, purchase_order_id=po["id"])
    assert res.status_code == 200
    assert any("received" in w for w in res.json()["warnings"])


# --- 5. Outward: the tax invoices, and who they went to ------------------------------------------

def test_outward_carries_the_tax_invoices_with_the_recipient(tenant):
    assert tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN}).status_code == 200
    tenant.post("/api/contacts", json={"name": "Customer Ltd", "gstin": "36AAACL1234H1ZW"})
    make_invoice(tenant, status="Awaiting Payment", issue_date=date.today().isoformat(),
                 line_items=[{"description": "Shuttering hire", "qty": 1, "price": 1000.0, "tax_rate": "18% GST"}])
    make_invoice(tenant, issue_date=date.today().isoformat())                     # a draft is not a supply
    out = tenant.get("/api/gst/outward").json()
    rows = [r for r in out["supplies"] if r["kind"] == "Tax invoice"]
    assert len(rows) == 1
    r = rows[0]
    assert r["taxable"] == 1000 and r["tax"] == 180 and r["cgst"] == 90 and r["sgst"] == 90 and r["igst"] == 0
    assert r["party_gstin"] == "36AAACL1234H1ZW" and r["b2b"] is True
    assert out["summary"]["b2b"] == 1
    assert tenant.get("/api/gst/outward.xlsx").status_code == 200


# --- 6. Inward: the stored split, approved bills, credit and reverse charge -----------------------

def test_the_split_is_stored_on_the_bill(tenant):
    tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN})
    tenant.post("/api/suppliers", json={"name": "Jindal Steel", "gstin": "27AAACJ1234H1ZX"})
    b = new_bill(tenant, vendor_name="Jindal Steel").json()
    got = tenant.get("/api/bills/%d" % b["id"]).json()
    assert got["igst"] == 180 and got["cgst"] == 0
    # Typed in, it must be a split of the tax.
    assert new_bill(tenant, vendor_name="Local Co", cgst=50, sgst=50).status_code == 400
    assert new_bill(tenant, vendor_name="Local Co", cgst=90, sgst=90, igst=0).status_code == 200


def test_inward_leaves_out_bills_waiting_on_an_approver(tenant):
    tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN})
    waiting = new_bill(tenant, reference="W-1").json()
    set_bill(waiting["id"], approval_status="pending", status="Awaiting Approval")
    ok = new_bill(tenant, reference="OK-1").json()
    numbers = {r["number"] for r in tenant.get("/api/gst/inward").json()["supplies"]}
    assert ok["number"] in numbers and waiting["number"] not in numbers


def test_blocked_credit_and_reverse_charge_are_kept_apart(tenant):
    tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN})
    new_bill(tenant, reference="E-1")
    new_bill(tenant, reference="E-2", itc_eligible=False)
    new_bill(tenant, reference="E-3", reverse_charge=True)
    s = tenant.get("/api/gst/inward").json()["summary"]
    assert s["tax"] == 360 and s["ineligible_tax"] == 180 and s["reverse_charge_tax"] == 180


def test_an_old_bill_with_no_split_is_still_worked_out(tenant):
    tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN})
    b = new_bill(tenant).json()
    set_bill(b["id"], cgst=None, sgst=None, igst=None)
    row = [r for r in tenant.get("/api/gst/inward").json()["supplies"] if r["number"] == b["number"]][0]
    assert row["igst"] == 180                                # supplier's state unknown: IGST


# --- 7. GSTINs that pass the check, set by those who may ------------------------------------------

def test_a_gstin_with_a_wrong_check_character_is_refused(tenant):
    assert tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"}).status_code == 400
    assert tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN}).status_code == 200
    bad = tenant.post("/api/customers", json={"name": "Typo Ltd", "gstin": "36AAACL1234H1ZQ"})
    assert bad.status_code == 400 and "check" in bad.json()["detail"]


def test_the_check_character_is_the_portals(tenant):
    from app.core.gst import gstin_check_char, gstin_valid
    assert gstin_check_char("27AAPFU0939F1Z") == "V"           # a GSTIN published in the GST portal's own examples
    assert gstin_valid("27AAPFU0939F1ZV") and not gstin_valid("27AAPFU0939F1ZW")


@pytest.fixture
def colleague(tenant):
    main.rate_limiter._hits.clear()
    email = "mate-%s@example.com" % uuid.uuid4().hex[:8]
    assert tenant.post("/api/team/invite", json={"email": email, "role": "admin", "name": "Colleague",
                                                 "password": "Colleague123"}).status_code == 200
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/client/login", json={"email": email, "password": "Colleague123"}).status_code == 200
    yield c
    c.__exit__(None, None, None)


def test_a_colleague_does_not_change_the_company_gstin(tenant, colleague):
    assert colleague.put("/api/gst/settings", json={"gstin": OUR_GSTIN}).status_code == 403
    assert tenant.put("/api/gst/settings", json={"gstin": OUR_GSTIN}).status_code == 200


# --- 8. E-way bills: the 24 hours, and a trail -----------------------------------------------------

def _generated(tenant):
    from test_eway_bills import cement, from_transfer, setup_company, transfer
    job = setup_company(tenant)
    e = from_transfer(tenant, transfer(tenant, cement(tenant)), job)
    res = tenant.post("/api/eway-bills/%d/generated" % e["id"], json={"ewb_no": "341012345678"})
    assert res.status_code == 200, res.text
    return e


def test_a_generated_e_way_bill_is_not_generated_again(tenant):
    e = _generated(tenant)
    assert tenant.post("/api/eway-bills/%d/generated" % e["id"], json={"ewb_no": "341012345679"}).status_code == 409


def test_valid_upto_has_to_be_a_date(tenant):
    from test_eway_bills import cement, from_transfer, setup_company, transfer
    job = setup_company(tenant)
    e = from_transfer(tenant, transfer(tenant, cement(tenant)), job)
    res = tenant.post("/api/eway-bills/%d/generated" % e["id"], json={"ewb_no": "341012345678", "valid_upto": "next week"})
    assert res.status_code == 400


def test_cancelling_after_24_hours_is_refused_and_a_cancel_is_logged(tenant):
    e = _generated(tenant)
    db = SessionLocal()
    try:
        db.query(models.DBEwayBill).filter(models.DBEwayBill.id == e["id"]).update(
            {"ewb_generated_at": (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")})
        db.commit()
    finally:
        db.close()
    assert tenant.post("/api/eway-bills/%d/cancel" % e["id"], json={"reason": "late"}).status_code == 409

    db = SessionLocal()
    try:
        db.query(models.DBEwayBill).filter(models.DBEwayBill.id == e["id"]).update(
            {"ewb_generated_at": (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")})
        db.commit()
        assert tenant.post("/api/eway-bills/%d/cancel" % e["id"], json={"reason": "Lorry did not come"}).status_code == 200
        logged = db.query(models.DBAuditLog).filter(models.DBAuditLog.action == "eway_bill_cancelled",
                                                    models.DBAuditLog.entity_id == e["id"]).count()
        assert logged == 1
    finally:
        db.close()
    assert tenant.post("/api/eway-bills/%d/generated" % e["id"], json={"ewb_no": "341012345670"}).status_code == 409


# --- 9. A cancelled IRN's number is not registered again ------------------------------------------

def test_a_cancelled_irns_document_number_is_not_registered_again(tenant):
    from test_einvoice import ready_bill
    from test_einvoice_irn import portal_response, status
    bill = ready_bill(tenant)
    p = status(tenant, bill)["payload"]
    url = "/api/einvoice/ra_bill/%d/irn" % bill["id"]
    irn = tenant.post(url, json={"response": portal_response(p)}).json()["irn"]
    assert tenant.post("/api/einvoice/irns/%d/cancel" % irn["id"], json={"reason": "Data entry mistake"}).status_code == 200
    again = tenant.post(url, json={"response": portal_response(p)})
    assert again.status_code == 409 and "new number" in again.json()["detail"]
    st = status(tenant, bill)
    assert st["irn_cancelled"] is True and st["action_needed"]


# --- 10. Numbering --------------------------------------------------------------------------------

def test_the_next_bill_number_follows_the_highest(tenant):
    new_bill(tenant, number="BILL-0041", status="Draft")
    new_bill(tenant, number="INV/77", status="Draft")                     # a supplier's own number entered last
    assert tenant.get("/api/next-bill-number").json()["number"] == "BILL-0042"
