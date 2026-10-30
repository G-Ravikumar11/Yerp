"""Payments approved before they are made.

Accounts raise a payment request; the accounts head checks it; over the MD's limit the MD releases it too; only then is
it paid - and the voucher says who checked and who approved. Nobody approves their own request, and the Master pays
without asking. Off until the company turns it on.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import main
from conftest import make_employee
from test_finance_ledger import money_in, supplier_bill

PASSWORD = "Crew1234"


def person(tenant, role="accounts", extra=""):
    email = "acc-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(tenant, email=email, password=PASSWORD, permission_role=role, status="active")
    if extra:
        tenant.put("/api/employees/%d" % emp["id"], json={"extra_permissions": extra})
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/employee/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def office(tenant):
    """The accounts clerk who pays, the accounts head who checks, with payment approval on and the MD's limit at 1 lakh."""
    res = tenant.put("/api/payment-requests/rules", json={"on": True, "free_below": 1000, "md_above": 100000})
    assert res.status_code == 200, res.text
    clerk, head = person(tenant), person(tenant, extra="payments.approve")
    yield clerk, head
    for c in (clerk, head):
        c.__exit__(None, None, None)


def test_off_by_default_and_set_by_the_master_alone(tenant):
    rules = tenant.get("/api/payment-requests/rules").json()
    assert rules["on"] is False and rules["master"] is True
    clerk = person(tenant)
    try:
        assert clerk.put("/api/payment-requests/rules", json={"on": True}).status_code == 403
    finally:
        clerk.__exit__(None, None, None)


def test_with_approval_on_a_clerk_cannot_just_pay(tenant, office):
    clerk, _ = office
    bill = supplier_bill(tenant, amount=50000, tax=9000)
    res = clerk.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 59000})
    assert res.status_code == 409 and "approv" in res.json()["detail"]
    # Up to the amount that needs no approval, they can.
    assert clerk.post("/api/money/entries", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 800}).status_code == 200
    # Money coming in never waits.
    assert clerk.post("/api/money/entries", json={"doc_type": "income", "head": "Scrap sale", "party_name": "Scrap dealer",
                                                  "amount": 9000}).status_code == 200
    # The Master pays without asking.
    assert money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=10000).status_code == 200


def test_a_request_is_checked_then_paid_and_the_voucher_names_who(tenant, office):
    clerk, head = office
    bill = supplier_bill(tenant, amount=50000, tax=9000)
    res = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 59000,
                                                    "note": "Cement, October"})
    assert res.status_code == 200, res.text
    r = res.json()["request"]
    assert r["number"] == "PRQ-0001" and r["status"] == "PENDING" and r["party_name"] == "ACC Ltd"
    # The clerk cannot approve their own request, nor pay it before it is approved.
    assert clerk.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 403
    assert clerk.post("/api/payment-requests/%d/pay" % r["id"], json={}).status_code == 409
    # It waits in the accounts head's inbox, and is approved from there.
    inbox = head.get("/api/approvals/inbox").json()["items"]
    row = next(i for i in inbox if i["kind"] == "payment_request")
    assert row["number"] == "PRQ-0001" and row["amount"] == 59000
    done = head.post("/api/approvals/decide", json={"kind": "payment_request", "id": r["id"], "decision": "approve"})
    assert done.status_code == 200, done.text
    assert done.json()["request"]["status"] == "APPROVED"           # under the MD's limit: one signature
    # Paid, as approved.
    paid = clerk.post("/api/payment-requests/%d/pay" % r["id"], json={"mode": "Bank transfer", "reference": "UTR1"})
    assert paid.status_code == 200, paid.text
    entry = paid.json()["entry"]
    assert entry["amount"] == 59000 and entry["doc_number"] == bill["number"]
    listed = tenant.get("/api/payment-requests").json()["requests"][0]
    assert listed["status"] == "PAID" and listed["entry_id"] == entry["id"] and listed["checked_by_name"]
    assert tenant.get("/api/money/entries/%d/voucher.pdf" % entry["id"]).status_code == 200
    # Voided, the request is approved again, to be paid properly.
    tenant.post("/api/money/entries/%d/void" % entry["id"], json={"reason": "wrong account"})
    assert tenant.get("/api/payment-requests").json()["requests"][0]["status"] == "APPROVED"


def test_over_the_limit_the_md_releases_it_too(tenant, office):
    clerk, head = office
    bill = supplier_bill(tenant, amount=200000, tax=36000)
    r = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 236000}).json()["request"]
    checked = head.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).json()
    assert checked["request"]["status"] == "AWAITING_MD" and "MD" in checked["message"]
    # The accounts head cannot release it as well; the MD (here the Master) does.
    assert head.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 403
    md_inbox = tenant.get("/api/approvals/inbox").json()["items"]
    assert any(i["kind"] == "payment_request" and i["kind_label"] == "Payment (MD)" for i in md_inbox)
    released = tenant.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).json()
    assert released["request"]["status"] == "APPROVED" and released["request"]["approved_by_name"]


def test_somebody_who_may_release_large_payments_approves_in_one_go(tenant, office):
    clerk, _ = office
    md = person(tenant, extra="payments.approve_high")
    try:
        bill = supplier_bill(tenant, amount=200000, tax=36000)
        r = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 236000}).json()["request"]
        assert md.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).json()["request"]["status"] == "APPROVED"
    finally:
        md.__exit__(None, None, None)


def test_a_rejection_says_why_and_a_bill_is_not_asked_for_twice(tenant, office):
    clerk, head = office
    bill = supplier_bill(tenant, amount=50000, tax=9000)
    r = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 40000}).json()["request"]
    # Only what is left, less what is already asked for.
    over = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 20000})
    assert over.status_code == 400 and "asked for" in over.json()["detail"]
    assert head.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "reject"}).status_code == 400
    no = head.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "reject", "note": "Short supply, hold"})
    assert no.json()["request"]["status"] == "REJECTED" and no.json()["request"]["reject_reason"] == "Short supply, hold"
    # Refused, it no longer holds the bill: the whole of it can be asked for again.
    assert clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 59000}).status_code == 200


def test_an_expense_goes_through_a_request_too(tenant, office):
    clerk, head = office
    job = tenant.post("/api/jobs", json={"name": "Vizag site"}).json()
    res = clerk.post("/api/payment-requests", json={"doc_type": "expense", "head": "Machinery hire", "party_name": "Sai Earthmovers",
                                                    "amount": 45000, "job_id": job["id"]})
    assert res.status_code == 200, res.text
    r = res.json()["request"]
    head.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"})
    entry = clerk.post("/api/payment-requests/%d/pay" % r["id"], json={"mode": "Cheque", "reference": "004512"}).json()["entry"]
    assert entry["head"] == "Machinery hire" and entry["job_id"] == job["id"]
    assert tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]["site_expenses"] == 45000


def test_a_request_is_withdrawn_by_whoever_asked(tenant, office):
    clerk, _ = office
    bill = supplier_bill(tenant)
    r = clerk.post("/api/payment-requests", json={"doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 1000}).json()["request"]
    assert clerk.post("/api/payment-requests/%d/cancel" % r["id"]).status_code == 200
    assert tenant.get("/api/payment-requests?status=open").json()["summary"]["open"] == 0


# --- what was approved is what is paid --------------------------------------------------------------------------------
# The payer chooses how and when; the payee, the project and the head are the approver's, whichever way it is paid.

def _approved(clerk, approver, **body):
    res = clerk.post("/api/payment-requests", json=body)
    assert res.status_code == 200, res.text
    r = res.json()["request"]
    assert approver.post("/api/payment-requests/%d/decide" % r["id"], json={"decision": "approve"}).status_code == 200
    return r


def test_an_approved_expense_cannot_be_paid_to_someone_else_or_another_project(tenant, office):
    clerk, head = office
    job = tenant.post("/api/jobs", json={"name": "Vizag site"}).json()
    other = tenant.post("/api/jobs", json={"name": "Hyderabad site"}).json()
    r = _approved(clerk, head, doc_type="expense", head="Machinery hire", party_name="Sai Earthmovers", amount=45000, job_id=job["id"])
    pay = {"doc_type": "expense", "head": "Machinery hire", "party_name": "Sai Earthmovers", "amount": 45000, "job_id": job["id"], "request_id": r["id"]}

    res = clerk.post("/api/money/entries", json=dict(pay, party_name="Ravi Traders"))
    assert res.status_code == 409 and "payee cannot be changed" in res.json()["detail"]
    res = clerk.post("/api/money/entries", json=dict(pay, job_id=other["id"]))
    assert res.status_code == 409 and "project cannot be changed" in res.json()["detail"]
    res = clerk.post("/api/money/entries", json=dict(pay, head="Diesel & fuel"))
    assert res.status_code == 409 and "head cannot be changed" in res.json()["detail"]
    assert clerk.post("/api/money/entries", json=dict(pay, amount=50000)).status_code == 400                 # nor more than approved
    assert tenant.get("/api/payment-requests?status=APPROVED").json()["requests"][0]["status"] == "APPROVED"  # nothing was paid

    # The same payee written differently is the same payee; what is recorded is what was approved.
    res = clerk.post("/api/money/entries", json=dict(pay, party_name="  sai   earthmovers "))
    assert res.status_code == 200, res.text
    entry = res.json()["entry"]
    assert entry["party_name"] == "Sai Earthmovers" and entry["job_id"] == job["id"] and entry["head"] == "Machinery hire"


def test_an_approved_advance_is_paid_to_the_approved_party_only(tenant, office):
    clerk, head = office
    job = tenant.post("/api/jobs", json={"name": "Vizag site"}).json()
    r = _approved(clerk, head, doc_type="on_account", party_type="supplier", party_name="ACC Ltd", amount=20000, job_id=job["id"])
    res = clerk.post("/api/money/entries", json={"doc_type": "on_account", "direction": "OUT", "party_type": "contractor", "party_name": "ACC Ltd",
                                                 "amount": 20000, "request_id": r["id"]})
    assert res.status_code == 409 and "payee" in res.json()["detail"]
    res = clerk.post("/api/money/entries", json={"doc_type": "on_account", "direction": "IN", "amount": 20000, "request_id": r["id"]})
    assert res.status_code == 409                                                                             # it was approved as money going out
    # Left out, the approved payee and project are filled in.
    res = clerk.post("/api/money/entries", json={"doc_type": "on_account", "amount": 20000, "request_id": r["id"]})
    assert res.status_code == 200, res.text
    entry = res.json()["entry"]
    assert entry["party_name"] == "ACC Ltd" and entry["party_type"] == "supplier" and entry["job_id"] == job["id"] and entry["direction"] == "OUT"


def test_a_bill_whose_payee_changed_after_approval_is_not_paid(tenant, office):
    from app import db as database, models
    clerk, head = office
    bill = supplier_bill(tenant, amount=50000, tax=9000)
    r = _approved(clerk, head, doc_type="supplier_bill", doc_id=bill["id"], amount=59000)
    with database.SessionLocal() as s:
        s.get(models.DBBill, bill["id"]).vendor_name = "Someone Else Pvt Ltd"
        s.commit()
    res = clerk.post("/api/payment-requests/%d/pay" % r["id"], json={"mode": "Bank transfer"})
    assert res.status_code == 409 and "Raise a new request" in res.json()["detail"]
