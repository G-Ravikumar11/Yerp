"""Journal vouchers - balanced, a project on each line, counted only once the Master approves them - and debit notes to
suppliers, which come off the bill they name, the supplier's account and the project's cost, and both go to Tally."""
import xml.etree.ElementTree as ET
from datetime import date

from app import db as database
from app.services.projects import site_expenses_by_job

from test_finance_ledger import money_in, supplier_bill
from test_payment_approval import person

TODAY = date.today().isoformat()


def job(tenant, name="Vizag Bypass"):
    res = tenant.post("/api/jobs", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()


def balance(tenant, party_type, party):
    got = tenant.get("/api/ledger/parties", params={"party_type": party_type}).json()["parties"]
    return next((p["balance"] for p in got if p["party"] == party), 0.0)


def write_off(tenant, j, amount=5000):
    """We owe the supplier 5,000 less: a short supply written off against the site's material cost."""
    return tenant.post("/api/journals", json={"voucher_date": TODAY, "narration": "Short supply written off", "lines": [
        {"kind": "party", "party_type": "supplier", "party_name": "ACC Ltd", "debit": amount, "job_id": j["id"]},
        {"kind": "head", "head": "Site expenses", "credit": amount, "job_id": j["id"]}]})


def cost(j):
    with database.SessionLocal() as db:
        return round(site_expenses_by_job(db, _client_of(db, j), [j["id"]]).get(j["id"], 0.0), 2)


def _client_of(db, j):
    from app import models
    return db.get(models.DBJob, j["id"]).client_id


def test_a_journal_must_balance_and_say_what_it_is_for(tenant):
    j = job(tenant)
    unequal = tenant.post("/api/journals", json={"narration": "Wrong", "lines": [
        {"kind": "party", "party_type": "supplier", "party_name": "ACC Ltd", "debit": 100},
        {"kind": "head", "head": "Site expenses", "credit": 90, "job_id": j["id"]}]})
    assert unequal.status_code == 400 and "equal" in unequal.json()["detail"]
    one = tenant.post("/api/journals", json={"narration": "One line", "lines": [{"kind": "head", "head": "Site expenses", "debit": 5}]})
    assert one.status_code == 400
    both = tenant.post("/api/journals", json={"narration": "Both", "lines": [
        {"kind": "head", "head": "Site expenses", "debit": 5, "credit": 5}, {"kind": "head", "head": "Site expenses", "credit": 5}]})
    assert both.status_code == 400
    assert tenant.post("/api/journals", json={"narration": "", "lines": []}).status_code == 400


def test_a_journal_counts_only_once_the_master_approves_it(tenant):
    supplier_bill(tenant, vendor="ACC Ltd", amount=10000, tax=0)
    j = job(tenant)
    made = write_off(tenant, j)
    assert made.status_code == 200, made.text
    jid = made.json()["id"]
    assert made.json()["status"] == "PENDING" and made.json()["number"].startswith("JV-") and made.json()["total"] == 5000
    assert balance(tenant, "supplier", "ACC Ltd") == 10000            # nothing moves while it waits
    inbox = tenant.get("/api/approvals/inbox").json()
    items = inbox["items"] if isinstance(inbox, dict) else inbox
    assert any(i["kind"] == "journal" and i["id"] == jid and i["amount"] == 5000 for i in items)
    res = tenant.post("/api/approvals/decide", json={"kind": "journal", "id": jid, "decision": "approve"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "APPROVED"
    assert balance(tenant, "supplier", "ACC Ltd") == 5000
    assert cost(j) == -5000
    pdf = tenant.get("/api/journals/%d/voucher.pdf" % jid)
    assert pdf.status_code in (200, 503)


def test_accounts_raise_journals_but_only_the_master_approves_them(tenant):
    j = job(tenant)
    clerk = person(tenant, extra="accounts.manage,money.view")
    try:
        made = write_off(clerk, j)
        assert made.status_code == 200, made.text
        jid = made.json()["id"]
        assert clerk.post("/api/journals/%d/approve" % jid, json={}).status_code == 403
        assert clerk.post("/api/approvals/decide", json={"kind": "journal", "id": jid, "decision": "approve"}).status_code == 403
    finally:
        clerk.__exit__(None, None, None)
    assert tenant.post("/api/journals/%d/reject" % jid, json={}).status_code == 400       # a reason to send it back
    assert tenant.post("/api/journals/%d/reject" % jid, json={"note": "Wrong head"}).json()["status"] == "REJECTED"
    assert tenant.post("/api/journals/%d/approve" % jid, json={}).status_code == 409


def test_an_approved_journal_cancelled_stops_counting(tenant):
    supplier_bill(tenant, vendor="ACC Ltd", amount=10000, tax=0)
    j = job(tenant)
    jid = write_off(tenant, j).json()["id"]
    tenant.post("/api/journals/%d/approve" % jid, json={})
    assert tenant.post("/api/journals/%d/cancel" % jid, json={"reason": "Raised twice"}).json()["status"] == "CANCELLED"
    assert balance(tenant, "supplier", "ACC Ltd") == 10000 and cost(j) == 0


def test_a_debit_note_comes_off_the_bill_the_supplier_and_the_project(tenant):
    j = job(tenant)
    bill = tenant.post("/api/bills", json={"number": "SB-DN1", "vendor_name": "Ramco Steel", "amount": 100000, "tax_amount": 18000,
                                          "total": 118000, "status": "Awaiting Payment", "job_id": j["id"]}).json()
    too_much = tenant.post("/api/supplier-debit-notes", json={"bill_id": bill["id"], "reason": "Short supply", "taxable": 200000, "tax": 0})
    assert too_much.status_code == 409
    res = tenant.post("/api/supplier-debit-notes", json={"bill_id": bill["id"], "reason": "2 MT short", "taxable": 10000, "tax": 1800})
    assert res.status_code == 200, res.text
    n = res.json()
    assert n["number"].startswith("DN-") and n["total"] == 11800 and n["supplier_name"] == "Ramco Steel"
    pay = tenant.get("/api/money/payables").json()
    row = next(r for r in pay["bills"] if r["id"] == bill["id"])
    assert row["outstanding"] == 106200
    assert balance(tenant, "supplier", "Ramco Steel") == 106200
    assert cost(j) == -11800
    # The payment box will not take more than is left, and paying that settles the bill.
    assert money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=118000).status_code == 400
    paid = money_in(tenant, doc_type="supplier_bill", doc_id=bill["id"], amount=106200)
    assert paid.status_code == 200, paid.text
    assert tenant.get("/api/bills/%d" % bill["id"]).json()["status"] == "Paid"
    # The bill is not deleted from under it.
    assert tenant.delete("/api/bills/%d" % bill["id"]).status_code == 409


def test_a_cancelled_debit_note_puts_the_bill_back(tenant):
    bill = supplier_bill(tenant, vendor="Ramco Steel", amount=50000, tax=0)
    n = tenant.post("/api/supplier-debit-notes", json={"bill_id": bill["id"], "reason": "Rate above order", "taxable": 50000}).json()
    assert tenant.get("/api/bills/%d" % bill["id"]).json()["status"] == "Paid"          # nothing left to pay
    assert tenant.post("/api/supplier-debit-notes/%d/cancel" % n["id"], json={"reason": "Supplier agreed rate"}).json()["status"] == "CANCELLED"
    assert tenant.get("/api/bills/%d" % bill["id"]).json()["status"] != "Paid"
    assert balance(tenant, "supplier", "Ramco Steel") == 50000


def test_a_debit_note_with_no_bill_comes_off_the_supplier_s_account(tenant):
    supplier_bill(tenant, vendor="Ramco Steel", amount=50000, tax=0)
    assert tenant.post("/api/supplier-debit-notes", json={"reason": "Late delivery penalty", "taxable": 2000}).status_code == 400
    res = tenant.post("/api/supplier-debit-notes", json={"supplier_name": "Ramco Steel", "reason": "Late delivery penalty", "taxable": 2000})
    assert res.status_code == 200, res.text
    assert balance(tenant, "supplier", "Ramco Steel") == 48000


def test_journals_and_debit_notes_go_to_tally_balanced(tenant):
    a, b = job(tenant, "Site A"), job(tenant, "Site B")
    bill = supplier_bill(tenant, vendor="ACC Ltd", amount=10000, tax=1800)
    tenant.post("/api/supplier-debit-notes", json={"bill_id": bill["id"], "reason": "Returned", "taxable": 1000, "tax": 180})
    jid = tenant.post("/api/journals", json={"narration": "Shuttering hire moved to Site B", "lines": [
        {"kind": "head", "head": "Machinery hire", "debit": 3000, "job_id": b["id"]},
        {"kind": "head", "head": "Machinery hire", "credit": 3000, "job_id": a["id"]}]}).json()["id"]
    pending = tenant.get("/api/tally/summary").json()
    assert any(x["what"] == "Journal vouchers" for x in pending["left_out"])
    tenant.post("/api/journals/%d/approve" % jid, json={})
    res = tenant.get("/api/tally/vouchers.xml")
    assert res.status_code == 200, res.text
    root = ET.fromstring(res.content)
    vs = {v.findtext("VOUCHERNUMBER"): v for v in root.iter("VOUCHER")}
    jv = next(v for n, v in vs.items() if n.startswith("JV-"))
    dn = next(v for n, v in vs.items() if n.startswith("DN-"))
    for v in (jv, dn):
        assert abs(sum(float(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST"))) < 0.01
    assert dn.findtext("VOUCHERTYPENAME") == "Debit Note" and jv.findtext("VOUCHERTYPENAME") == "Journal"
    centres = {c.findtext("NAME") for c in jv.iter("COSTCENTREALLOCATIONS.LIST")}
    assert len(centres) == 2 and any("Site A" in c for c in centres) and any("Site B" in c for c in centres)
