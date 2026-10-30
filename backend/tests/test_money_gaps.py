"""Money that could go out twice, come in on paper only, or slip past the payment signature.

1. A supplier bill marked paid wrote no payment, so it could be paid again from Payments & Ledgers and then deleted.
2. A client's RA bill marked paid dropped off what the client owes with nothing received.
3. An invoice could be saved as "Paid", renumbered after it went out, and deleted with its receipts.
4. A refund from a supplier lowered what we owe them instead of raising it.
5. A payment over the limit went through as several under it, and a transfer moved money with nobody's say.
"""
from app import db as database
from app import models

from conftest import make_invoice
from test_finance_ledger import certified_ra, money_in, supplier_bill
from test_payment_approval import office  # noqa: F401  (the fixture)


# --- 1. supplier bills ----------------------------------------------------------------------------------------------------

def test_a_bill_marked_paid_is_paid_through_the_ledger_and_not_again(tenant):
    bill = supplier_bill(tenant, amount=100000, tax=18000)
    res = tenant.post("/api/bills/%d/pay" % bill["id"], json={})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Paid"
    entries = tenant.get("/api/money/outstanding/supplier_bill/%d" % bill["id"]).json()
    assert entries["outstanding"] == 0 and [e["amount"] for e in entries["entries"]] == [118000]
    # Not a second time, from either screen.
    again = money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=118000)
    assert again.status_code == 409, again.text
    assert tenant.post("/api/bills/%d/pay" % bill["id"], json={}).status_code == 409
    # And it is not deleted out from under the payment.
    assert tenant.delete("/api/bills/%d" % bill["id"]).status_code == 409


def test_a_bill_marked_paid_before_the_ledger_is_not_paid_twice(tenant):
    bill = supplier_bill(tenant, amount=50000, tax=0)
    with database.SessionLocal() as db:            # paid the old way: the flag, no entry
        b = db.query(models.DBBill).filter(models.DBBill.id == bill["id"]).first()
        b.amount_paid, b.status = 50000, "Paid"
        db.commit()
    assert money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=50000).status_code == 409
    assert tenant.delete("/api/bills/%d" % bill["id"]).status_code == 409


# --- 2. client RA bills ---------------------------------------------------------------------------------------------------

def test_an_ra_bill_marked_paid_is_received_in_the_bank_book(tenant):
    b = certified_ra(tenant)
    money_in(tenant, doc_type="ra_bill", doc_id=b["id"], amount=1000)
    res = tenant.post("/api/ra-bills/%d/pay" % b["id"], json={"reference": "UTR 55"})
    assert res.status_code == 200, res.text
    assert res.json()["bill"]["status"] == "PAID"
    assert res.json()["entry"]["amount"] == round(b["net_payable"] - 1000, 2)
    got = tenant.get("/api/money/outstanding/ra_bill/%d" % b["id"]).json()
    assert got["outstanding"] == 0 and len(got["entries"]) == 2
    assert tenant.post("/api/ra-bills/%d/pay" % b["id"], json={}).status_code == 409


# --- 3. invoices ----------------------------------------------------------------------------------------------------------

def test_an_invoice_is_not_paid_by_its_status(tenant):
    res = tenant.post("/api/invoices", json={
        "contact": "Customer Ltd", "issue_date": "2026-01-01", "due_date": "2026-01-31", "tax_type": "none",
        "status": "Paid", "line_items": [{"description": "Work", "qty": 1, "price": 400.0}]})
    assert res.status_code == 400
    inv = make_invoice(tenant)
    res = tenant.put("/api/invoices/%s" % inv["number"], json={
        "contact": "Customer Ltd", "issue_date": "2026-01-01", "due_date": "2026-01-31", "tax_type": "none",
        "status": "Paid", "line_items": [{"description": "Work", "qty": 1, "price": 400.0}]})
    assert res.status_code == 400


def test_an_invoice_with_money_received_is_not_deleted(tenant):
    inv = make_invoice(tenant)
    assert tenant.post("/api/invoices/%s/payments" % inv["number"], json={"amount": 50}).status_code == 200
    assert tenant.delete("/api/invoices/%s" % inv["number"]).status_code == 409


def test_a_sent_invoice_keeps_its_number(tenant):
    inv = make_invoice(tenant)
    with database.SessionLocal() as db:
        # Every test company numbers its invoices from INV-0001: the newest one with this number is this test's.
        row = db.query(models.DBInvoice).filter(models.DBInvoice.number == inv["number"]).order_by(
            models.DBInvoice.id.desc()).first()
        row.sent, row.status = "2026-01-02", "Sent"
        db.commit()
    res = tenant.put("/api/invoices/%s" % inv["number"], json={
        "invoice_number": "INV-9999", "contact": "Customer Ltd", "issue_date": "2026-01-01",
        "due_date": "2026-01-31", "tax_type": "none",
        "line_items": [{"description": "Work", "qty": 1, "price": 400.0}]})
    assert res.status_code == 409
    assert tenant.delete("/api/invoices/%s" % inv["number"]).status_code == 409


# --- 4. the party ledger --------------------------------------------------------------------------------------------------

def test_a_refund_from_a_supplier_raises_what_we_owe_them(tenant):
    supplier_bill(tenant, vendor="Ravi Traders", amount=50000, tax=0)
    assert money_in(tenant, doc_type="on_account", direction="IN", party_type="supplier",
                    party_name="Ravi Traders", amount=10000).status_code == 200
    ravi = [p for p in tenant.get("/api/ledger/parties?party_type=supplier").json()["parties"]
            if p["party"] == "Ravi Traders"][0]
    assert ravi["balance"] == 60000            # 50,000 billed, and their 10,000 refund is owed back in goods or money


# --- 5. the payment signature ---------------------------------------------------------------------------------------------

def test_a_payment_split_under_the_limit_still_needs_approval(tenant, office):  # noqa: F811
    clerk, _ = office
    bill = supplier_bill(tenant, amount=50000, tax=0)
    assert clerk.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": bill["id"],
                                                  "amount": 800}).status_code == 200
    res = clerk.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 800})
    assert res.status_code == 409 and "approv" in res.json()["detail"]
    # The same goes for one payee paid in pieces on one day, bill or no bill.
    body = {"doc_type": "expense", "head": "Machinery hire", "party_name": "Sai Earthmovers", "amount": 600}
    assert clerk.post("/api/money/entries", json=body).status_code == 200
    assert clerk.post("/api/money/entries", json=body).status_code == 409


def test_a_transfer_over_the_limit_is_moved_by_whoever_checks_payments(tenant, office):  # noqa: F811
    clerk, head = office
    bank = tenant.post("/api/bank-accounts", json={"name": "SBI current", "opening_balance": 500000}).json()
    box = tenant.post("/api/bank-accounts", json={"name": "Site cash", "kind": "Cash"}).json()
    move = {"from_account_id": bank["id"], "to_account_id": box["id"], "amount": 50000}
    res = clerk.post("/api/money/transfer", json=move)
    assert res.status_code == 409 and "approv" in res.json()["detail"]
    assert head.post("/api/money/transfer", json=move).status_code == 200


def test_a_cash_box_cannot_hand_over_more_than_it_holds(tenant):
    box = tenant.post("/api/bank-accounts", json={"name": "Site cash", "kind": "Cash", "opening_balance": 5000}).json()
    bank = tenant.post("/api/bank-accounts", json={"name": "SBI current"}).json()
    res = tenant.post("/api/money/transfer", json={"from_account_id": box["id"], "to_account_id": bank["id"],
                                                   "amount": 6000})
    assert res.status_code == 409
