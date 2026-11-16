"""An approved expense claim can be paid with the salary: the next payslip adds it as a non-taxable reimbursement and
releasing the payslip settles the claim."""
from conftest import make_employee

PERIOD = {"period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}
MONTH = "2026-09"


def claim(tenant, emp, amount=850, approve=True):
    res = tenant.post("/api/expense-claims", json={"spent_on": "2026-09-05", "head": "Travel & conveyance", "amount": amount,
                                                  "description": "Bus to site and back", "employee_id": emp["id"]})
    assert res.status_code == 200, res.text
    c = res.json()
    if approve:
        assert tenant.post("/api/expense-claims/%d/decide" % c["id"], json={"decision": "approve"}).status_code == 200
    return c


def row(tenant, cid):
    return next(c for c in tenant.get("/api/expense-claims").json()["claims"] if c["id"] == cid)


def staff_balance(tenant, name):
    rows = tenant.get("/api/ledger/parties", params={"party_type": "staff"}).json()
    rows = rows.get("parties", rows) if isinstance(rows, dict) else rows
    return next((r.get("balance", r.get("net", 0)) for r in rows if r.get("party") == name), 0)


def test_a_claim_on_the_salary_is_added_untaxed_and_settled_on_release(tenant):
    emp = make_employee(tenant, salary=30000.0, tax_rate=10.0)
    plain = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD}).json()
    base = tenant.get("/api/payslips/%d" % plain["id"]).json()
    tenant.delete("/api/payslips/%d" % plain["id"])

    c = claim(tenant, emp, 850)
    res = tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    assert res.status_code == 200 and res.json()["pay_with_salary"] is True, res.text

    preview = tenant.post("/api/payroll/preview", json={**PERIOD, "employee_ids": [emp["id"]]}).json()["rows"][0]
    assert preview["reimbursement"] == 850 and preview["net_pay"] == base["net_pay"] + 850
    assert row(tenant, c["id"])["payslip_id"] is None, "a preview picks nothing up"

    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD}).json()["id"]
    p = tenant.get("/api/payslips/%d" % sid).json()
    assert p["reimbursement"] == 850 and [x["number"] for x in p["reimbursed_claims"]] == [c["number"]]
    # Untaxed: gross, tax, PF and the deductions are what they were without the claim.
    assert (p["gross_pay"], p["tax_amount"], p["total_deductions"]) == (base["gross_pay"], base["tax_amount"], base["total_deductions"])
    assert p["net_pay"] == base["net_pay"] + 850 and p["standing_deduction"] == base["standing_deduction"]
    assert row(tenant, c["id"])["status"] == "APPROVED" and row(tenant, c["id"])["payslip_id"] == sid

    assert tenant.post("/api/payslips/%d/mark-paid" % sid).status_code == 200
    got = row(tenant, c["id"])
    assert got["status"] == "SETTLED" and got["left"] == 0
    entries = [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "expense_claim"]
    assert len(entries) == 1 and entries[0]["mode"] == "Adjustment" and entries[0]["amount"] == 850 and entries[0]["direction"] == "OUT"

    # Reopened: the claim is owed again; released once more it is settled by a fresh entry.
    assert tenant.post("/api/payslips/%d/unmark-paid" % sid).status_code == 200
    assert row(tenant, c["id"])["status"] == "APPROVED"
    assert tenant.post("/api/payslips/%d/mark-paid" % sid).status_code == 200
    assert row(tenant, c["id"])["status"] == "SETTLED"
    live = [e for e in tenant.get("/api/money/entries").json()["entries"] if e["doc_type"] == "expense_claim" and not e["voided"]]
    assert len(live) == 1


def test_releasing_the_month_settles_the_claim_and_a_claim_is_taken_once(tenant):
    emp = make_employee(tenant, salary=30000.0, tax_rate=0.0)
    c = claim(tenant, emp, 400)
    tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    assert tenant.post("/api/payroll/run", json={**PERIOD, "employee_ids": [emp["id"]]}).status_code == 200
    again = {"period_start": "2026-10-01", "period_end": "2026-10-31", "pay_date": "2026-10-31"}
    nxt = tenant.post("/api/payslips", json={"employee_id": emp["id"], **again}).json()["id"]
    assert tenant.get("/api/payslips/%d" % nxt).json()["reimbursement"] == 0, "already on September's payslip"
    assert tenant.post("/api/payroll/month/approve", json={"month": MONTH}).status_code == 200
    res = tenant.post("/api/payroll/month/pay", json={"month": MONTH})
    assert res.status_code == 200 and res.json()["claims_settled"] == 1, res.text
    assert row(tenant, c["id"])["status"] == "SETTLED"


def test_only_an_approved_claim_goes_on_the_salary_and_it_can_come_off_again(tenant):
    emp = make_employee(tenant)
    waiting = claim(tenant, emp, 300, approve=False)
    assert tenant.post("/api/expense-claims/%d/pay-with-salary" % waiting["id"], json={}).status_code == 409
    c = claim(tenant, emp, 300)
    tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    off = tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={"on": False})
    assert off.status_code == 200 and off.json()["pay_with_salary"] is False
    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD}).json()["id"]
    assert tenant.get("/api/payslips/%d" % sid).json()["reimbursement"] == 0
    tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    sid2 = tenant.post("/api/payslips", json={"employee_id": emp["id"], "period_start": "2026-10-01", "period_end": "2026-10-31",
                                              "pay_date": "2026-10-31"}).json()["id"]
    assert tenant.get("/api/payslips/%d" % sid2).json()["reimbursement"] == 300
    assert tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={"on": False}).status_code == 409


def test_deleting_the_payslip_puts_the_claim_back_in_the_queue(tenant):
    emp = make_employee(tenant, salary=30000.0, tax_rate=0.0)
    c = claim(tenant, emp, 500)
    tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD}).json()["id"]
    tenant.post("/api/payslips/%d/mark-paid" % sid)
    assert row(tenant, c["id"])["status"] == "SETTLED"
    assert tenant.delete("/api/payslips/%d?force=true" % sid).status_code == 200
    got = row(tenant, c["id"])
    assert got["status"] == "APPROVED" and got["payslip_id"] is None and got["pay_with_salary"] is True
    sid2 = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD}).json()["id"]
    assert tenant.get("/api/payslips/%d" % sid2).json()["reimbursement"] == 500


def test_the_payslip_sheet_shows_the_reimbursement_and_still_adds_up(tenant):
    emp = make_employee(tenant, salary=30000.0, tax_rate=0.0)
    c = claim(tenant, emp, 700)
    tenant.post("/api/expense-claims/%d/pay-with-salary" % c["id"], json={})
    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD}).json()["id"]
    from app.documents import payslip as sheet
    p = tenant.get("/api/payslips/%d" % sid).json()
    lay = sheet.layout(p)
    assert ("Expense Reimbursement (non-taxable)", 700.0) in [(l, v) for l, v in lay["earnings"]]
    cols = sheet.register_columns([p])
    cells = dict(zip(cols, sheet.register_row(p, cols)))
    assert cells["Reimbursement"] == 700.0 and cells["Total Earnings"] - cells["Total Deductions"] == cells["Net Pay"]
