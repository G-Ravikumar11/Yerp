"""A salary advance is taken back through the payroll: the payslip shows what the person holds, HR types the month's
recovery, and marking the payslip (or its month) paid writes the adjustment receipt that brings the advance down."""
from conftest import make_employee

PERIOD = {"period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}
MONTH = "2026-09"


def advance(tenant, name, amount, direction="OUT", mode="Bank transfer"):
    res = tenant.post("/api/money/entries", json={
        "doc_type": "on_account", "doc_id": None, "direction": direction, "party_type": "staff", "party_name": name,
        "amount": amount, "paid_on": "2026-08-15", "mode": mode})
    assert res.status_code == 200, res.text
    return res.json()["entry"]


def staff_balance(tenant, name):
    rows = tenant.get("/api/advances").json()["staff"]
    return next((r["outstanding"] for r in rows if r["party"] == name), 0)


def person(tenant, **kw):
    emp = make_employee(tenant, **kw)
    return emp, "%s %s" % (emp["first_name"], emp["last_name"])


def receipts(tenant, name):
    rows = tenant.get("/api/money/entries", params={"party_type": "staff"}).json()
    rows = rows.get("entries", rows) if isinstance(rows, dict) else rows
    return [r for r in rows if r["party_name"] == name and r["direction"] == "IN"]


def test_the_preview_shows_the_advance_held_and_the_run_takes_back_what_hr_typed(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 10000)
    row = tenant.post("/api/payroll/preview", json={**PERIOD, "employee_ids": [emp["id"]]}).json()["rows"][0]
    assert row["advance_balance"] == 10000 and row["advance_recovery"] == 0

    plain = row["net_pay"]
    row = tenant.post("/api/payroll/preview", json={**PERIOD, "employee_ids": [emp["id"]],
                                                     "overrides": {str(emp["id"]): {"advance_recovery": 4000}}}).json()["rows"][0]
    assert row["advance_recovery"] == 4000 and row["net_pay"] == plain - 4000

    res = tenant.post("/api/payroll/run", json={**PERIOD, "employee_ids": [emp["id"]],
                                                 "overrides": {str(emp["id"]): {"advance_recovery": 4000}}})
    assert res.status_code == 200, res.text
    slips = tenant.get("/api/payslips").json()
    assert slips[0]["advance_recovery"] == 4000 and slips[0]["net_pay"] == plain - 4000
    detail = tenant.get("/api/payslips/%d" % slips[0]["id"]).json()
    assert detail["advance_recovery"] == 4000 and detail["advance_entry_id"] is None
    assert detail["standing_deduction"] == 0, "the recovery is its own line, not folded into the standing deduction"
    # Nothing has moved yet: the advance comes down only when the payslip is released.
    assert staff_balance(tenant, name) == 10000


def test_releasing_the_month_writes_one_adjustment_receipt_per_payslip(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 10000)
    tenant.post("/api/payroll/run", json={**PERIOD, "employee_ids": [emp["id"]],
                                           "overrides": {str(emp["id"]): {"advance_recovery": 4000}}})
    assert tenant.post("/api/payroll/month/approve", json={"month": MONTH}).status_code == 200
    res = tenant.post("/api/payroll/month/pay", json={"month": MONTH})
    assert res.status_code == 200, res.text
    assert res.json()["advances_recovered"] == 1 and "advance" in res.json()["message"]

    assert staff_balance(tenant, name) == 6000
    got = receipts(tenant, name)
    assert len(got) == 1
    e = got[0]
    assert e["mode"] == "Adjustment" and e["amount"] == 4000 and e["doc_type"] == "on_account"
    assert e["number"].startswith("RCT-") and "PS-" in e["note"]
    slip = tenant.get("/api/payslips").json()[0]
    assert tenant.get("/api/payslips/%d" % slip["id"]).json()["advance_entry_id"] == e["id"]


def test_marking_one_payslip_paid_releases_it_and_reopening_voids_the_receipt(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 10000)
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD, "advance_recovery": 2500})
    assert res.status_code == 200, res.text
    sid = res.json()["id"]
    assert tenant.post("/api/payslips/%d/mark-paid" % sid).status_code == 200
    assert staff_balance(tenant, name) == 7500
    # Marking the month paid afterwards does not write it twice.
    tenant.post("/api/payroll/month/approve", json={"month": MONTH})
    assert tenant.post("/api/payroll/month/pay", json={"month": MONTH}).json()["advances_recovered"] == 0
    assert staff_balance(tenant, name) == 7500 and len(receipts(tenant, name)) == 1

    # Reopened: the receipt is voided and the advance is owed again; released once more, a fresh receipt is written.
    assert tenant.post("/api/payslips/%d/unmark-paid" % sid).status_code == 200
    assert staff_balance(tenant, name) == 10000
    assert tenant.get("/api/payslips/%d" % sid).json()["advance_entry_id"] is None
    assert tenant.post("/api/payslips/%d/mark-paid" % sid).status_code == 200
    assert staff_balance(tenant, name) == 7500
    live = [r for r in receipts(tenant, name) if not r["voided"]]
    assert len(live) == 1 and live[0]["amount"] == 2500


def test_more_than_the_advance_held_is_refused(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    nobody, _ = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 5000)
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD, "advance_recovery": 5001})
    assert res.status_code == 400 and "5,000" in res.json()["detail"], res.text
    res = tenant.post("/api/payslips", json={"employee_id": nobody["id"], **PERIOD, "advance_recovery": 1})
    assert res.status_code == 400 and "holds no advance" in res.json()["detail"], res.text
    res = tenant.post("/api/payroll/preview", json={**PERIOD, "employee_ids": [emp["id"]],
                                                     "overrides": {str(emp["id"]): {"advance_recovery": 9000}}})
    assert res.status_code == 400
    # Up to the balance is fine, and a second unreleased payslip may only take what the first left.
    assert tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD, "advance_recovery": 5000}).status_code == 200
    later = {"period_start": "2026-10-01", "period_end": "2026-10-31", "pay_date": "2026-10-31"}
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], **later, "advance_recovery": 1})
    assert res.status_code == 400 and "another payslip" in res.json()["detail"], res.text
    assert tenant.get("/api/employees/%d/pay-details" % emp["id"], params=later).json()["advance_balance"] == 0


def test_the_recovery_can_be_changed_on_a_draft_but_not_once_released(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 10000)
    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD, "advance_recovery": 1000}).json()["id"]
    before = tenant.get("/api/payslips/%d" % sid).json()["net_pay"]
    assert tenant.put("/api/payslips/%d" % sid, json={"advance_recovery": 3000}).status_code == 200
    after = tenant.get("/api/payslips/%d" % sid).json()
    assert after["advance_recovery"] == 3000 and after["net_pay"] == before - 2000
    assert tenant.put("/api/payslips/%d" % sid, json={"advance_recovery": 30000}).status_code == 400
    tenant.post("/api/payslips/%d/mark-paid" % sid)
    assert tenant.put("/api/payslips/%d" % sid, json={"advance_recovery": 500}).status_code == 409, "a paid payslip cannot be edited"
    assert staff_balance(tenant, name) == 7000


def test_the_payslip_sheet_prints_the_salary_advance_line(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 10000)
    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD, "advance_recovery": 1500}).json()["id"]
    from app.documents import payslip as sheet
    p = tenant.get("/api/payslips/%d" % sid).json()
    lay = sheet.layout(p)
    assert ("Salary Advance", 1500.0) in [(l, float(v or 0)) for l, v in lay["deductions"]]
    cols = sheet.register_columns([p])
    assert dict(zip(cols, sheet.register_row(p, cols)))["Salary Advance"] == 1500.0


def test_deleting_a_released_payslip_gives_the_advance_back(tenant):
    emp, name = person(tenant, salary=30000.0, tax_rate=0.0)
    advance(tenant, name, 10000)
    sid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **PERIOD, "advance_recovery": 4000}).json()["id"]
    tenant.post("/api/payslips/%d/mark-paid" % sid)
    assert staff_balance(tenant, name) == 6000
    assert tenant.delete("/api/payslips/%d?force=true" % sid).status_code == 200
    assert staff_balance(tenant, name) == 10000
