"""What accounts and the store owe the books, found without anybody opening the right screen: the dashboard's list carries
it, accounts are told each morning, the stores are checked against their reorder levels, and goods sent back come off the
supplier's only bill by themselves."""
import uuid
from datetime import date, datetime, timedelta

from app import db as database
from app import models
from app.core.scheduler import run_due_jobs

from test_finance_ledger import supplier_bill
from test_payouts import bank, supplier

TODAY = date.today().isoformat()


def kinds(tenant):
    return {i["kind"]: i for i in tenant.get("/api/attention").json()["items"]}


def test_the_dashboard_carries_what_accounts_have_waiting(tenant):
    assert not {"msme_overdue", "pdc_to_deposit", "journals_pending", "claims_waiting"} & set(kinds(tenant))
    acc = bank(tenant)
    supplier(tenant, msme_type="small", udyam_no="UDYAM-TS-02-0012345")
    old = (date.today() - timedelta(days=60)).isoformat()
    tenant.post("/api/bills", json={"number": "MS-9", "vendor_name": "Ramco Steel", "amount": 20000, "tax_amount": 0, "total": 20000,
                                    "issue_date": old, "status": "Awaiting Payment"})
    held = tenant.post("/api/pdcs", json={"direction": "IN", "cheque_no": "112233", "cheque_date": TODAY, "party_type": "client",
                                          "party_name": "Vizag Port", "amount": 75000, "account_id": acc["id"]})
    assert held.status_code == 200, held.text
    tenant.post("/api/journals", json={"narration": "Write off", "lines": [
        {"kind": "party", "party_type": "supplier", "party_name": "Ramco Steel", "debit": 500},
        {"kind": "head", "head": "Site expenses", "credit": 500}]})
    from conftest import make_employee
    emp = make_employee(tenant)
    tenant.post("/api/expense-claims", json={"employee_id": emp["id"], "spent_on": TODAY, "head": "Site expenses", "amount": 300,
                                             "description": "Nails and binding wire"})
    got = kinds(tenant)
    assert got["msme_overdue"]["value"] == 20000 and got["msme_overdue"]["severity"] == "wrong"
    assert got["pdc_to_deposit"]["value"] == 75000 and got["journals_pending"]["count"] == 1 and got["claims_waiting"]["count"] == 1


def test_accounts_are_told_each_morning_and_only_once(tenant):
    supplier(tenant, msme_type="micro", udyam_no="UDYAM-TS-02-0012345")
    tenant.post("/api/bills", json={"number": "MS-10", "vendor_name": "Ramco Steel", "amount": 1000, "tax_amount": 0, "total": 1000,
                                    "issue_date": (date.today() - timedelta(days=50)).isoformat(), "status": "Awaiting Payment"})
    at = datetime.now().replace(hour=9)
    early = run_due_jobs(at.replace(hour=5), only="accounts_store_watch")
    assert early[0]["detail"] == "too early"
    first = run_due_jobs(at, only="accounts_store_watch")
    assert first[0]["status"] == "done" and "office(s) told" in first[0]["detail"] and not first[0]["detail"].endswith(" 0 office(s) told")
    assert run_due_jobs(at, only="accounts_store_watch")[0]["status"] == "already_done"
    with database.SessionLocal() as db:                        # so the next test's morning is its own
        db.query(models.DBJobRun).filter(models.DBJobRun.job_name == "accounts_store_watch").delete()
        db.commit()
