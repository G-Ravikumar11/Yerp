"""What reaches Tally beyond the bills and the money: payroll, retention released, mobilisation advances - and the page
says what was left out of an export, and why."""
from conftest import make_employee

from app import models
from app.db import SessionLocal
from app.services import tally
from test_subcontractor_bills import live_order, measure, raise_bill

PERIOD = "date_from=2020-01-01&date_to=2030-12-31"


def _client_id(tenant):
    job = tenant.post("/api/jobs", json={"name": "Books site", "customer_name": "Kokapet LLP"}).json()
    jid = job.get("id") or job["job"]["id"]
    db = SessionLocal()
    try:
        return db.get(models.DBJob, jid).client_id
    finally:
        db.close()


def _payslip(db, client_id, emp_id, n):
    db.add(models.DBPayslip(client_id=client_id, employee_id=emp_id, number="PS-%d" % n, period_start="2026-09-01",
                            period_end="2026-09-30", pay_date="2026-09-30", basic_salary=40000, gross_pay=50000, tax_amount=2000,
                            insurance=375, retirement=1800, professional_tax=200, other_deductions=125, total_deductions=4500,
                            net_pay=45500, employer_pf=1800, employer_esi=1625, status="Issued"))


def _vouchers(tenant):
    return tenant.get("/api/tally/vouchers?" + PERIOD).json()["vouchers"]


def _lines(v):
    return {l["ledger"]: (l["debit"], l["credit"]) for l in v["lines"]}


def test_an_approved_payroll_month_goes_as_a_journal_and_its_payment(tenant):
    c = _client_id(tenant)
    e = make_employee(tenant)
    db = SessionLocal()
    try:
        _payslip(db, c, e["id"], 1)
        _payslip(db, c, e["id"], 2)
        db.add(models.DBPayrollMonth(client_id=c, month="2026-09", status="Paid", paid_at="2026-10-02 10:00:00"))
        db.commit()
    finally:
        db.close()
    got = _vouchers(tenant)
    j = next(v for v in got if v["number"] == "PAY/2026-09")
    assert j["type"] == "Journal" and j["date"] == "2026-09-30"
    ledger = _lines(j)
    assert ledger["Salaries & Wages"] == (100000, 0) and ledger["Employer PF & ESI"] == (6850, 0)
    assert ledger["Salaries Payable"] == (0, 91000) and ledger["TDS Payable - Salaries"] == (0, 4000)
    assert ledger["PF Payable"] == (0, 7200) and ledger["ESI Payable"] == (0, 4000)
    assert sum(l["debit"] for l in j["lines"]) == sum(l["credit"] for l in j["lines"])
    paid = next(v for v in got if v["number"] == "PAY/2026-09/PAID")
    assert paid["type"] == "Payment" and paid["date"] == "2026-10-02" and paid["amount"] == 91000


def test_a_month_not_approved_stays_out_and_the_page_says_so(tenant):
    c = _client_id(tenant)
    e = make_employee(tenant)
    db = SessionLocal()
    try:
        _payslip(db, c, e["id"], 3)
        db.commit()
    finally:
        db.close()
    assert not [v for v in _vouchers(tenant) if v["number"].startswith("PAY/")]
    out = tenant.get("/api/tally/summary?" + PERIOD).json()["left_out"]
    row = next(r for r in out if r["what"] == "Payslips")
    assert row["count"] == 1 and row["amount"] == 50000 and "approved" in row["why"]


def test_a_bill_not_certified_is_named_as_left_out(tenant):
    o = live_order(tenant, pay_advance=False)
    item = tenant.get("/api/sub-mb/%d" % o["id"]).json()["lines"][0]["item_id"]
    measure(tenant, o["id"], item, 1)
    bill = raise_bill(tenant, o["id"]).json()["bill"]
    out = tenant.get("/api/tally/summary?" + PERIOD).json()["left_out"]
    row = next(r for r in out if r["what"] == "Contractor RA bills")
    assert row["count"] == 1 and row["amount"] == bill["this_bill"] and "certified" in row["why"]


def test_a_mobilisation_advance_is_paid_to_the_ledger_the_bills_recover_it_from(tenant):
    live_order(tenant, mobilization_advance_percent=10)
    paid = [v for v in _vouchers(tenant) if v["type"] == "Payment"]
    assert paid, "the advance was not paid"
    assert "Mobilisation Advance to Contractors" in _lines(paid[0])


def test_the_vouchers_download_as_a_workbook_to_read(tenant):
    res = tenant.get("/api/tally/vouchers.xlsx?" + PERIOD)
    assert res.status_code == 200 and res.content[:2] == b"PK"


def test_every_ledger_can_be_named_on_the_settings_page(tenant):
    assert set(tally.LEDGERS) <= set(tally.LABELS)
    assert tenant.get("/api/tally/settings").status_code == 200
