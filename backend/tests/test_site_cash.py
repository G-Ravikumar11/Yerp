"""A site's cash box: topped up by head office, spent on site with a photo of each bill, checked by accounts.

Only a checked expense is booked - as an expense voucher out of the box, charged to the site. Until then the cash has
gone from the box but not from the books, and the box says so: what it should hold is its balance less what is waiting.
"""
import uuid

from fastapi.testclient import TestClient

import main
from conftest import make_employee
from test_payment_approval import person

PASSWORD = "Crew1234"


def site_engineer(tenant):
    email = "se-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(tenant, email=email, password=PASSWORD, permission_role="staff", status="active")
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/employee/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    return emp, c


def setup(tenant):
    """A bank, a Vizag site with its cash box held by the site engineer, a float of 50,000, topped up."""
    bank = tenant.post("/api/bank-accounts", json={"name": "SBI current", "kind": "Bank", "opening_balance": 500000}).json()
    box = tenant.post("/api/bank-accounts", json={"name": "Site cash - Vizag", "kind": "Cash"}).json()
    job = tenant.post("/api/jobs", json={"name": "Vizag site"}).json()
    emp, se = site_engineer(tenant)
    res = tenant.put("/api/site-cash/boxes/%d" % box["id"], json={"job_id": job["id"], "custodian_id": emp["id"],
                                                                  "imprest_amount": 50000})
    assert res.status_code == 200, res.text
    assert tenant.post("/api/money/transfer", json={"from_account_id": bank["id"], "to_account_id": box["id"],
                                                    "amount": 50000}).status_code == 200
    return box, job, se


def photo(client, x):
    return client.post("/api/site-cash/expenses/%d/photo" % x["id"],
                       files={"file": ("bill.jpg", b"\xff\xd8\xff\xe0" + b"0" * 200, "image/jpeg")})


def spend(client, box, amount=4500, head="Diesel & fuel", paid_to="HP pump, Gajuwaka", **more):
    return client.post("/api/site-cash/expenses", json={"account_id": box["id"], "amount": amount, "head": head,
                                                        "paid_to": paid_to, **more})


def test_the_site_spends_and_accounts_book_it(tenant):
    box, job, se = setup(tenant)
    try:
        res = spend(se, box, note="JCB, 50 litres", bill_no="HP/4471")
        assert res.status_code == 200, res.text
        x = res.json()["expense"]
        assert x["number"] == "SCE-0001" and x["status"] == "SUBMITTED" and x["job_id"] == job["id"]
        # The bill, photographed on site.
        photo = se.post("/api/site-cash/expenses/%d/photo" % x["id"],
                        files={"file": ("bill.jpg", b"\xff\xd8\xff\xe0" + b"0" * 200, "image/jpeg")})
        assert photo.status_code == 200, photo.text
        # The engineer sees their own box: 50,000 in the books, 45,500 that should be in hand.
        mine = se.get("/api/site-cash").json()
        assert mine["manage"] is False and len(mine["boxes"]) == 1
        b = mine["boxes"][0]
        assert (b["balance"], b["pending"], b["in_hand"]) == (50000, 4500, 45500)
        assert mine["expenses"][0]["photo"]["id"] == photo.json()["photo"]["id"]
        # They cannot check it themselves.
        assert se.post("/api/site-cash/expenses/%d/decide" % x["id"], json={"decision": "approve"}).status_code == 403
        # Accounts accept it, from the inbox: booked as an expense voucher out of the box, charged to the site.
        inbox = tenant.get("/api/approvals/inbox").json()["items"]
        assert any(i["kind"] == "site_cash" and i["number"] == "SCE-0001" for i in inbox)
        done = tenant.post("/api/approvals/decide", json={"kind": "site_cash", "id": x["id"], "decision": "approve"})
        assert done.status_code == 200, done.text
        entry_id = done.json()["expense"]["entry_id"]
        e = next(e for e in tenant.get("/api/money/entries").json()["entries"] if e["id"] == entry_id)
        assert e["doc_type"] == "expense" and e["head"] == "Diesel & fuel" and e["mode"] == "Cash" and e["account"] == "Site cash - Vizag"
        assert tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]["site_expenses"] == 4500
        b = se.get("/api/site-cash").json()["boxes"][0]
        assert (b["balance"], b["pending"], b["in_hand"], b["top_up"]) == (45500, 0, 45500, 4500)
        # The cash book prints for the custodian to sign.
        pdf = se.get("/api/site-cash/boxes/%d/statement.pdf" % box["id"])
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        # Voided by accounts, the expense goes back to be checked again.
        tenant.post("/api/money/entries/%d/void" % entry_id, json={"reason": "wrong site"})
        assert se.get("/api/site-cash").json()["expenses"][0]["status"] == "SUBMITTED"
    finally:
        se.__exit__(None, None, None)


def test_a_rejected_expense_says_why_and_books_nothing(tenant):
    box, job, se = setup(tenant)
    try:
        x = spend(se, box, amount=1200, head="Staff welfare & food", paid_to="Hotel").json()["expense"]
        assert tenant.post("/api/site-cash/expenses/%d/decide" % x["id"], json={"decision": "reject"}).status_code == 400
        no = tenant.post("/api/site-cash/expenses/%d/decide" % x["id"], json={"decision": "reject", "note": "No bill"}).json()
        assert no["expense"]["status"] == "REJECTED" and no["expense"]["reject_reason"] == "No bill"
        assert tenant.get("/api/jobs/%d" % job["id"]).json()["costing"]["site_expenses"] == 0
        b = se.get("/api/site-cash").json()["boxes"][0]
        assert (b["balance"], b["pending"]) == (50000, 0)
    finally:
        se.__exit__(None, None, None)


def test_a_site_engineer_sees_and_spends_only_their_own_box(tenant):
    box, _, se = setup(tenant)
    other = tenant.post("/api/bank-accounts", json={"name": "Site cash - Kakinada", "kind": "Cash"}).json()
    bank = next(a for a in tenant.get("/api/bank-accounts").json()["accounts"] if a["kind"] == "Bank")
    try:
        assert [b["name"] for b in se.get("/api/site-cash").json()["boxes"]] == ["Site cash - Vizag"]
        assert spend(se, other).status_code == 403
        assert spend(se, bank).status_code == 404                       # a bank account is not a cash box
        assert se.get("/api/site-cash/boxes/%d/statement.pdf" % other["id"]).status_code == 403
        assert se.put("/api/site-cash/boxes/%d" % box["id"], json={"imprest_amount": 999999}).status_code == 403
        # Accounts see every box.
        assert len(tenant.get("/api/site-cash").json()["boxes"]) == 2
    finally:
        se.__exit__(None, None, None)


def test_what_is_spent_is_entered_as_it_was(tenant):
    box, _, se = setup(tenant)
    try:
        assert spend(se, box, head="Party").status_code == 400
        assert spend(se, box, paid_to=" ").status_code == 400
        assert spend(se, box, amount=0).status_code == 400
        assert spend(se, box, spent_on="2999-01-01").status_code == 400
    finally:
        se.__exit__(None, None, None)


def test_accounts_staff_check_site_cash_but_not_their_own(tenant):
    box, _, se = setup(tenant)
    clerk = person(tenant)                                            # accounts: pays bills, so manages cash boxes
    try:
        x = spend(se, box).json()["expense"]
        assert photo(se, x).status_code == 200                       # over 500: approved only with its bill
        assert clerk.post("/api/site-cash/expenses/%d/decide" % x["id"], json={"decision": "approve"}).status_code == 200
        own = spend(clerk, box, amount=300, head="Site expenses", paid_to="Tea stall").json()["expense"]
        assert clerk.post("/api/site-cash/expenses/%d/decide" % own["id"], json={"decision": "approve"}).status_code == 403
    finally:
        se.__exit__(None, None, None)
        clerk.__exit__(None, None, None)


# --- the controls on the box ---------------------------------------------------------------------------------------

def test_the_box_cannot_pay_out_more_than_it_holds(tenant):
    box, _, se = setup(tenant)
    try:
        res = spend(se, box, amount=50001)
        assert res.status_code == 409, res.text
        assert spend(se, box, amount=30000, bill_no="A1").status_code == 200
        # 50,000 in the books, 30,000 already waiting: 25,000 more is more than is left.
        assert spend(se, box, amount=25000, bill_no="A2").status_code == 409
        assert spend(se, box, amount=20000, bill_no="A3").status_code == 200
    finally:
        se.__exit__(None, None, None)


def test_the_same_bill_is_not_entered_twice(tenant):
    box, _, se = setup(tenant)
    try:
        assert spend(se, box, bill_no="HP/1").status_code == 200
        assert spend(se, box, bill_no="hp/1", amount=100).status_code == 409
        # No bill number: the same payee, amount and day is the same payment.
        first = spend(se, box, amount=250, paid_to="Tea stall").json()["expense"]
        assert spend(se, box, amount=250, paid_to="tea stall").status_code == 409
        # Once rejected, it may be entered again properly.
        tenant.post("/api/site-cash/expenses/%d/decide" % first["id"], json={"decision": "reject", "note": "No details"})
        assert spend(se, box, amount=250, paid_to="Tea stall").status_code == 200
    finally:
        se.__exit__(None, None, None)


def test_an_expense_over_500_is_approved_only_with_its_bill(tenant):
    box, _, se = setup(tenant)
    try:
        x = spend(se, box, amount=600).json()["expense"]
        assert x["bill_needed"] is True
        res = tenant.post("/api/site-cash/expenses/%d/decide" % x["id"], json={"decision": "approve"})
        assert res.status_code == 409 and "bill" in res.json()["detail"]
        assert photo(se, x).status_code == 200
        assert tenant.post("/api/site-cash/expenses/%d/decide" % x["id"], json={"decision": "approve"}).status_code == 200
        small = spend(se, box, amount=200, paid_to="Tea stall").json()["expense"]
        assert tenant.post("/api/site-cash/expenses/%d/decide" % small["id"], json={"decision": "approve"}).status_code == 200
    finally:
        se.__exit__(None, None, None)


def test_the_master_does_not_approve_their_own_expense(tenant):
    box, _, se = setup(tenant)
    clerk = person(tenant)
    try:
        own = spend(tenant, box, amount=300, paid_to="Tea stall").json()["expense"]
        assert own["submitted_by_master"] is True
        assert tenant.post("/api/site-cash/expenses/%d/decide" % own["id"], json={"decision": "approve"}).status_code == 403
        assert clerk.post("/api/site-cash/expenses/%d/decide" % own["id"], json={"decision": "approve"}).status_code == 200
    finally:
        se.__exit__(None, None, None)
        clerk.__exit__(None, None, None)


def test_cash_over_10000_to_one_payee_in_a_day_is_warned(tenant):
    box, _, se = setup(tenant)
    try:
        a = spend(se, box, amount=8000, paid_to="Ravi Transport", bill_no="RT-1", spent_on="2026-01-10").json()
        assert not a["warning"]
        b = spend(se, box, amount=3000, paid_to="ravi transport", bill_no="RT-2", spent_on="2026-01-10").json()
        assert "40A(3)" in b["warning"]
    finally:
        se.__exit__(None, None, None)


def test_an_expense_belongs_to_the_box_s_own_site(tenant):
    box, job, se = setup(tenant)
    other = tenant.post("/api/jobs", json={"name": "Kakinada site"}).json()
    try:
        assert spend(se, box, job_id=other["id"]).status_code == 400
        assert spend(se, box, job_id=job["id"]).status_code == 200
    finally:
        se.__exit__(None, None, None)
