"""Paying out: the bank's bulk payment file, MSME suppliers' 45 days, cheque books and post-dated cheques, and staff
expense claims - each settling through the bank book like a payment typed by hand."""
import csv
import io
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from app import db as database
from app import models
from app.services.projects import site_expenses_by_job

from test_finance_ledger import money_in, supplier_bill
from test_payment_approval import person

TODAY = date.today().isoformat()


def day(n):
    return (date.today() - timedelta(days=n)).isoformat()


def bank(tenant, name="HDFC current", ifsc="HDFC0001234"):
    res = tenant.post("/api/bank-accounts", json={"name": name, "kind": "Bank", "opening_balance": 1000000, "opening_date": day(90),
                                                  "account_no": "50200012345678", "ifsc": ifsc, "bank_name": "HDFC Bank"})
    assert res.status_code == 200, res.text
    return res.json()


def supplier(tenant, name="Ramco Steel", ifsc="ICIC0004321", **kw):
    body = {"name": name, "bank_account": "001105012345", "bank_ifsc": ifsc, "bank_name": "ICICI Bank", "payment_days": 30}
    body.update(kw)
    res = tenant.post("/api/suppliers", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def balance(tenant, party_type, party):
    got = tenant.get("/api/ledger/parties", params={"party_type": party_type}).json()["parties"]
    return next((p["balance"] for p in got if p["party"] == party), 0.0)


# --- MSME -------------------------------------------------------------------------------------------------------------------

def test_an_msme_supplier_s_bill_is_due_in_45_days_at_most(tenant):
    bad = tenant.post("/api/suppliers", json={"name": "X", "msme_type": "tiny"})
    assert bad.status_code == 400
    assert tenant.post("/api/suppliers", json={"name": "X", "msme_type": "micro", "udyam_no": "12345"}).status_code == 400
    s = supplier(tenant, msme_type="micro", udyam_no="UDYAM-TS-02-0012345", payment_days=60)
    assert s["msme_type"] == "micro" and s["udyam_no"] == "UDYAM-TS-02-0012345"
    old = tenant.post("/api/bills", json={"number": "MS-1", "vendor_name": "Ramco Steel", "amount": 10000, "tax_amount": 0, "total": 10000,
                                          "issue_date": day(50), "status": "Awaiting Payment"}).json()
    fresh = tenant.post("/api/bills", json={"number": "MS-2", "vendor_name": "Ramco Steel", "amount": 5000, "tax_amount": 0, "total": 5000,
                                            "issue_date": day(40), "status": "Awaiting Payment"}).json()
    pay = tenant.get("/api/money/payables").json()
    rows = {r["id"]: r for r in pay["bills"] if r["doc_type"] == "supplier_bill"}
    assert rows[old["id"]]["msme"]["due"] == (date.today() - timedelta(days=5)).isoformat()         # 45 days, not the 60 agreed
    assert rows[old["id"]]["msme"]["days_left"] == -5 and rows[fresh["id"]]["msme"]["days_left"] == 5
    assert pay["summary"]["msme_overdue"] == 10000 and pay["summary"]["msme_due_soon"] == 5000
    supplier(tenant, name="Big Cement", msme_type="medium", udyam_no="UDYAM-AP-01-0000001")
    b = supplier_bill(tenant, vendor="Big Cement", amount=1000, tax=0)
    assert next(r for r in tenant.get("/api/money/payables").json()["bills"] if r["id"] == b["id"])["msme"] is None


# --- the bank's file ----------------------------------------------------------------------------------------------------------

def test_a_payment_file_is_written_in_the_bank_s_layout_and_paid_into_the_bank_book(tenant):
    acc = bank(tenant)
    supplier(tenant)
    big = supplier_bill(tenant, vendor="Ramco Steel", amount=250000, tax=0)
    small = supplier_bill(tenant, vendor="Ramco Steel", amount=10000, tax=1800)
    supplier_bill(tenant, vendor="Nobody Bank Details", amount=5000, tax=0)
    cands = tenant.get("/api/payment-batches/candidates").json()["items"]
    nobody = next(c for c in cands if c["party_name"] == "Nobody Bank Details")
    assert nobody["problem"]
    refused = tenant.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "icici", "items": [nobody]})
    assert refused.status_code == 400 and "bank details" in refused.json()["detail"]
    pick = [c for c in cands if c["doc_id"] in (big["id"], small["id"])]
    res = tenant.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "icici", "pay_on": TODAY, "items": pick})
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["number"].startswith("PB-") and b["count"] == 2 and b["total"] == 261800
    assert {l["mode"] for l in b["lines"]} == {"RTGS", "NEFT"}
    again = tenant.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "csv", "items": pick[:1]})
    assert again.status_code == 409                                          # already in a file not yet paid
    f = tenant.get("/api/payment-batches/%d/file" % b["id"])
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(f.text)))
    assert rows[0][0] == "Debit Ac No" and rows[1][0] == "50200012345678" and rows[1][1] == "001105012345" and rows[1][6] == "ICIC0004321"
    hdfc = tenant.post("/api/payment-batches/%d/cancel" % b["id"]).json()
    assert hdfc["status"] == "CANCELLED"
    b = tenant.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "hdfc", "items": pick}).json()
    line = list(csv.reader(io.StringIO(tenant.get("/api/payment-batches/%d/file" % b["id"]).text)))[0]
    assert len(line) == 28 and line[0] in ("N", "R") and line[2] == "001105012345"
    paid = tenant.post("/api/payment-batches/%d/paid" % b["id"], json={"paid_on": TODAY, "reference": "BATCH UTR 99"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "PAID" and all(l["status"] == "PAID" and l["entry_id"] for l in paid.json()["lines"])
    assert balance(tenant, "supplier", "Ramco Steel") == 0
    assert tenant.get("/api/bills/%d" % big["id"]).json()["status"] == "Paid"


def test_a_line_the_rules_refuse_is_kept_as_failed_and_the_rest_are_paid(tenant):
    acc = bank(tenant)
    supplier(tenant)
    a = supplier_bill(tenant, vendor="Ramco Steel", amount=1000, tax=0)
    c = supplier_bill(tenant, vendor="Ramco Steel", amount=2000, tax=0)
    pick = [x for x in tenant.get("/api/payment-batches/candidates").json()["items"] if x["doc_id"] in (a["id"], c["id"])]
    b = tenant.post("/api/payment-batches", json={"account_id": acc["id"], "bank_format": "csv", "items": pick}).json()
    money_in(tenant, doc_type="supplier_bill", doc_id=a["id"], amount=1000, account_id=acc["id"])          # paid by hand meanwhile
    res = tenant.post("/api/payment-batches/%d/paid" % b["id"], json={}).json()
    st = {l["doc_id"]: l for l in res["lines"]}
    assert st[a["id"]]["status"] == "FAILED" and "settled" in st[a["id"]]["error"] and st[c["id"]]["status"] == "PAID"
    assert res["status"] == "DRAFT"
    assert tenant.post("/api/payment-batches/%d/cancel" % b["id"]).json()["status"] == "PAID"


# --- cheques ----------------------------------------------------------------------------------------------------------------

def test_a_cheque_book_accounts_for_every_leaf(tenant):
    acc = bank(tenant)
    assert tenant.post("/api/cheque-books", json={"account_id": acc["id"], "first_no": 100, "last_no": 90}).status_code == 400
    book = tenant.post("/api/cheque-books", json={"account_id": acc["id"], "first_no": 451, "last_no": 475}).json()
    assert book["leaves"] == 25 and book["next_leaf"] == 451
    assert tenant.post("/api/cheque-books", json={"account_id": acc["id"], "first_no": 470, "last_no": 480}).status_code == 409
    supplier(tenant)
    bill = supplier_bill(tenant, vendor="Ramco Steel", amount=1000, tax=0)
    assert money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=1000, account_id=acc["id"], mode="Cheque",
                    reference="000451").status_code == 200
    assert tenant.post("/api/cheque-books/%d/spoil" % book["id"], json={"number": 452, "reason": "Written wrong"}).status_code == 200
    assert tenant.post("/api/cheque-books/%d/spoil" % book["id"], json={"number": 451, "reason": "x x x"}).status_code == 409
    leaves = {l["number"]: l for l in tenant.get("/api/cheque-books/%d/leaves" % book["id"]).json()["leaves"]}
    assert leaves[451]["status"] == "ISSUED" and leaves[451]["party"] == "Ramco Steel" and leaves[452]["status"] == "SPOILT"
    assert tenant.get("/api/cheque-books").json()["books"][0]["next_leaf"] == 453


def test_a_post_dated_cheque_is_not_money_until_its_day(tenant):
    acc = bank(tenant)
    supplier(tenant)
    bill = supplier_bill(tenant, vendor="Ramco Steel", amount=50000, tax=0)
    ahead = (date.today() + timedelta(days=10)).isoformat()
    p = tenant.post("/api/pdcs", json={"direction": "OUT", "cheque_no": "000460", "cheque_date": ahead, "account_id": acc["id"],
                                       "doc_type": "supplier_bill", "doc_id": bill["id"], "amount": 50000})
    assert p.status_code == 200, p.text
    p = p.json()
    assert p["party_name"] == "Ramco Steel" and p["status"] == "HELD"
    assert balance(tenant, "supplier", "Ramco Steel") == 50000                       # not paid yet
    early = tenant.post("/api/pdcs/%d/bank" % p["id"], json={"on": TODAY})
    assert early.status_code == 409
    with database.SessionLocal() as db:                                         # ten days on: its date has come
        db.get(models.DBPostDatedCheque, p["id"]).cheque_date = TODAY
        db.commit()
    done = tenant.post("/api/pdcs/%d/bank" % p["id"], json={"on": TODAY})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "BANKED" and balance(tenant, "supplier", "Ramco Steel") == 0
    held = tenant.post("/api/pdcs", json={"direction": "IN", "cheque_no": "778899", "cheque_date": ahead, "drawn_on": "SBI",
                                          "party_type": "client", "party_name": "Vizag Port", "amount": 100000}).json()
    assert tenant.get("/api/pdcs").json()["summary"]["held"] == 100000
    closed = tenant.post("/api/pdcs/%d/close" % held["id"], json={"status": "RETURNED", "reason": "Client replaced it with NEFT"})
    assert closed.json()["status"] == "RETURNED"


# --- staff expense claims -----------------------------------------------------------------------------------------------------

def _job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vizag Bypass"}).json()


def test_a_claim_is_approved_by_accounts_and_reimbursed(tenant):
    acc = bank(tenant)
    j = _job(tenant)
    staff = person(tenant, role="staff")
    try:
        me = staff.get("/api/employee/me").json()
        res = staff.post("/api/expense-claims", json={"spent_on": TODAY, "head": "Travel & conveyance", "job_id": j["id"], "amount": 850,
                                                     "description": "Bus to site and back", "bill_no": "T-1"})
        assert res.status_code == 200, res.text
        c = res.json()
        assert c["number"].startswith("EC-") and c["status"] == "SUBMITTED"
        assert staff.post("/api/expense-claims", json={"spent_on": TODAY, "head": "Travel & conveyance", "amount": 850,
                                                      "description": "Same bus", "bill_no": "T-1"}).status_code == 409
        assert staff.post("/api/expense-claims/%d/decide" % c["id"], json={"decision": "approve"}).status_code == 403
        assert [x["id"] for x in staff.get("/api/expense-claims").json()["claims"]] == [c["id"]]
    finally:
        staff.__exit__(None, None, None)
    name = c["employee_name"]
    items = tenant.get("/api/approvals/inbox").json()
    items = items["items"] if isinstance(items, dict) else items
    assert any(i["kind"] == "expense_claim" and i["id"] == c["id"] for i in items)
    assert tenant.post("/api/approvals/decide", json={"kind": "expense_claim", "id": c["id"], "decision": "approve"}).status_code == 200
    assert balance(tenant, "staff", name) == 850
    with database.SessionLocal() as db:
        assert round(site_expenses_by_job(db, db.get(models.DBJob, j["id"]).client_id, [j["id"]])[j["id"]], 2) == 850
    owed = next(r for r in tenant.get("/api/money/payables").json()["bills"] if r["doc_type"] == "expense_claim")
    assert owed["outstanding"] == 850 and owed["party"] == name
    paid = money_in(tenant, doc_type="expense_claim", doc_id=c["id"], amount=850, account_id=acc["id"])
    assert paid.status_code == 200, paid.text
    assert balance(tenant, "staff", name) == 0
    claims = {x["id"]: x for x in tenant.get("/api/expense-claims").json()["claims"]}
    assert claims[c["id"]]["status"] == "SETTLED"
    assert me


def test_a_claim_can_be_set_against_an_advance_the_person_holds(tenant):
    acc = bank(tenant)
    from conftest import make_employee
    emp = make_employee(tenant, first_name="Ravi", last_name="Kumar")
    name = "Ravi Kumar"
    c = tenant.post("/api/expense-claims", json={"employee_id": emp["id"], "spent_on": TODAY, "head": "Site expenses", "amount": 1200,
                                                 "description": "Cement bags bought in town"}).json()
    tenant.post("/api/expense-claims/%d/decide" % c["id"], json={"decision": "approve"})
    none = tenant.post("/api/expense-claims/%d/against-advance" % c["id"])
    assert none.status_code == 409                                             # no advance held
    assert money_in(tenant, doc_type="on_account", direction="OUT", party_type="staff", party_name=name, amount=5000,
                    account_id=acc["id"]).status_code == 200
    res = tenant.post("/api/expense-claims/%d/against-advance" % c["id"])
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "SETTLED" and res.json()["against_advance"] == 1200
    assert balance(tenant, "staff", name) == -3800                             # still holds 3,800 of ours
    assert not [r for r in tenant.get("/api/money/payables").json()["bills"] if r["doc_type"] == "expense_claim"]


def test_claims_go_to_tally_as_journals(tenant):
    from conftest import make_employee
    emp = make_employee(tenant, first_name="Sita", last_name="Rao")
    c = tenant.post("/api/expense-claims", json={"employee_id": emp["id"], "spent_on": TODAY, "head": "Staff welfare & food",
                                                 "amount": 640, "description": "Lunch for the inspection team"}).json()
    assert any(x["what"] == "Staff expense claims" for x in tenant.get("/api/tally/summary").json()["left_out"])
    tenant.post("/api/expense-claims/%d/decide" % c["id"], json={"decision": "approve"})
    root = ET.fromstring(tenant.get("/api/tally/vouchers.xml").content)
    v = next(v for v in root.iter("VOUCHER") if v.findtext("VOUCHERNUMBER") == c["number"])
    amts = sorted(float(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST"))
    assert amts == [-640.0, 640.0]
