"""The staff portal walked as three people would: a November payroll run, then each signs in and sees their payslip
(and only theirs), books leave that HR approves, and uploads the documents HR asked for."""
import base64

import pytest

import main
from conftest import make_employee
from test_subcontract_orders import PASSWORD, sign_in


@pytest.fixture(autouse=True)
def _clear_limits():
    main.rate_limiter._hits.clear()
    yield


def three(tenant):
    tenant.get("/api/onboarding/requirements")     # the default documents asked of everybody
    people = []
    for salary in (30000.0, 45000.0, 60000.0):
        e = make_employee(tenant, salary=salary, password=PASSWORD, start_date="2026-01-01")
        assert tenant.put("/api/employees/%d" % e["id"], json={"status": "active"}).status_code == 200
        people.append(e)
    return people


def run_november(tenant, people):
    body = {"period_start": "2026-11-01", "period_end": "2026-11-30", "pay_date": "2026-11-30",
            "employee_ids": [p["id"] for p in people]}
    preview = tenant.post("/api/payroll/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["rows"]) == 3
    run = tenant.post("/api/payroll/run", json=body)
    assert run.status_code == 200, run.text
    # A draft month is HR's: staff see their payslip once the month is approved.
    ok = tenant.post("/api/payroll/month/approve", json={"month": "2026-11"})
    assert ok.status_code == 200, ok.text
    return preview.json()


def test_each_sees_their_own_payslip_and_can_download_it(tenant, portal):
    people = three(tenant)
    preview = run_november(tenant, people)
    nets = {r["employee_id"]: r["net_pay"] for r in preview["rows"]}
    slips = {}
    for p in people:
        portal.cookies.clear()
        sign_in(portal, p)
        dash = portal.get("/api/employee/dashboard")
        assert dash.status_code == 200, dash.text
        mine = dash.json()["payslips"]
        assert len(mine) == 1, mine
        assert abs(mine[0]["net_pay"] - nets[p["id"]]) < 0.01
        slips[p["id"]] = mine[0]["id"]
        pdf = portal.get("/api/employee/payslips/%d/pdf" % mine[0]["id"])
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF", pdf.status_code
    # Nobody opens somebody else's.
    portal.cookies.clear()
    sign_in(portal, people[0])
    assert portal.get("/api/employee/payslips/%d/pdf" % slips[people[1]["id"]]).status_code in (403, 404)


def test_leave_is_booked_and_approved(tenant, portal):
    people = three(tenant)
    for i, p in enumerate(people):
        portal.cookies.clear()
        sign_in(portal, p)
        day = "2026-12-%02d" % (7 + i)          # a Monday to Wednesday, one each
        res = portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": day, "end_date": day,
                                                       "reason": "Family function"})
        assert res.status_code == 200, res.text
        mine = portal.get("/api/employee/leave").json()
        assert any(l.get("start_date") == day for l in (mine.get("requests") or mine.get("leave") or mine)), mine
    pending = tenant.get("/api/leave/requests").json()
    rows = pending.get("requests", pending) if isinstance(pending, dict) else pending
    ours = [r for r in rows if r["employee_id"] in {p["id"] for p in people}]
    assert len(ours) == 3
    for r in ours:
        res = tenant.post("/api/leave/requests/%d/action" % r["id"], json={"action": "approve", "notes": "OK"})
        assert res.status_code == 200, res.text


def test_documents_asked_for_are_uploaded_and_listed(tenant, portal):
    people = three(tenant)
    data = base64.b64encode(b"%PDF-1.4 test document").decode()
    for p in people:
        portal.cookies.clear()
        sign_in(portal, p)
        asked = portal.get("/api/employee/document-requests")
        assert asked.status_code == 200, asked.text
        reqs = asked.json().get("requests", asked.json())
        assert reqs, "nothing asked of a new employee"
        res = portal.post("/api/employee/document-requests/%d/upload" % reqs[0]["id"],
                          json={"file_name": "id.pdf", "file_type": "application/pdf", "file_data": data})
        assert res.status_code == 200, res.text
        docs = portal.get("/api/employee/documents")
        assert docs.status_code == 200, docs.text


def test_tds_owed_from_earlier_months_never_makes_the_net_negative():
    from types import SimpleNamespace
    from app.services.payroll import compute_payslip_figures
    emp = SimpleNamespace(salary=0, pay_frequency="monthly", tax_rate=0, deductions=0, overtime_rate=0,
                          state="", pf_applicable=False, esi_applicable=False, pt_applicable=False,
                          first_name="A", last_name="B", hourly_rate=0, employment_type="full_time")
    worked = compute_payslip_figures(emp, {"allowances": 1000}, tax_fn=lambda gross, one_off=0.0: 197911.0)
    assert worked["net_pay"] >= 0 and worked["tax_amount"] <= worked["gross_pay"]
    typed = compute_payslip_figures(emp, {"allowances": 1000, "tax_amount": 5000})   # HR's own figure still stands
    assert typed["tax_amount"] == 5000


def test_a_month_already_run_can_still_be_previewed_to_check_it(tenant):
    people = three(tenant)
    run_november(tenant, people)
    body = {"period_start": "2026-11-01", "period_end": "2026-11-30", "pay_date": "2026-11-30",
            "employee_ids": [p["id"] for p in people], "skip_existing": False}
    res = tenant.post("/api/payroll/preview", json=body)
    assert res.status_code == 200, res.text
    assert all(r["existing_payslip"] for r in res.json()["rows"])
