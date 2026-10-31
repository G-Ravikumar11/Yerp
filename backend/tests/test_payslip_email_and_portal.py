"""The payslip email (rupees, no unsubscribe, a PDF made on the server) and what staff see of their payslips."""
import base64

import pytest

from conftest import make_employee

SLIP = {"period_start": "2026-07-01", "period_end": "2026-07-31", "pay_date": "2026-07-31"}


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.payroll.send_email_background", lambda *a, **k: sent.append(a))
    return sent


def make_slip(tenant, emp, **extra):
    res = tenant.post("/api/payslips", json={"employee_id": emp["id"], **SLIP, **extra})
    assert res.status_code == 200, res.text
    return res.json()["id"]


# --- A: the email ----------------------------------------------------------------------------------------------------

def test_the_email_is_in_rupees_with_no_pound_and_no_unsubscribe(tenant, outbox):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    sid = make_slip(tenant, emp)
    res = tenant.post("/api/payslips/%d/send" % sid, json={})
    assert res.status_code == 200, res.text
    to, subject, text, sender, html, pdf_b64, filename = outbox[0][:7]
    assert to == emp["email"]
    for body in (text, html):
        assert "£" not in body and "&pound;" not in body and "£" not in body
        assert "₹" in body
    assert "unsubscribe" not in html.lower()
    assert "Provident Fund (PF)" in html and ">ESI<" in html


def test_large_amounts_are_grouped_the_indian_way(tenant, outbox):
    emp = make_employee(tenant, salary=150000.0, tax_rate=0.0)
    sid = make_slip(tenant, emp, use_structure=False)
    tenant.post("/api/payslips/%d/send" % sid, json={})
    html = outbox[0][4]
    assert "₹1,50,000.00" in html, "1,50,000 rather than 150,000"


def test_the_pdf_is_made_on_the_server_and_what_the_browser_sends_is_ignored(tenant, outbox):
    emp = make_employee(tenant, salary=30000.0)
    sid = make_slip(tenant, emp)
    forged = base64.b64encode(b"%PDF-1.4 not the real payslip").decode()
    assert tenant.post("/api/payslips/%d/send" % sid, json={"pdf_data": forged}).status_code == 200
    pdf_b64, filename = outbox[0][5], outbox[0][6]
    pdf = base64.b64decode(pdf_b64)
    assert pdf.startswith(b"%PDF") and b"not the real payslip" not in pdf and len(pdf) > 1000
    assert filename.startswith("Payslip_PS-") and filename.endswith(".pdf")


# --- B: what staff see -----------------------------------------------------------------------------------------------

@pytest.fixture
def staffer(tenant):
    emp = make_employee(tenant, password="EmpPass123", salary=30000.0)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(portal, emp):
    assert portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"}).status_code == 200


def my_payslips(portal):
    res = portal.get("/api/employee/dashboard")
    assert res.status_code == 200, res.text
    return res.json()["payslips"]


def test_a_draft_is_not_shown_until_it_is_sent_or_its_month_approved(tenant, portal, staffer, outbox):
    sid = make_slip(tenant, staffer)
    sign_in(portal, staffer)
    assert my_payslips(portal) == []
    assert portal.get("/api/employee/payslips/%d/pdf" % sid).status_code == 404
    assert tenant.post("/api/payroll/month/approve", json={"month": "2026-07"}).status_code == 200
    shown = my_payslips(portal)
    assert [p["id"] for p in shown] == [sid] and shown[0]["status"] == "Draft"


def test_a_sent_payslip_is_shown_and_downloads_as_a_pdf(tenant, portal, staffer, outbox):
    sid = make_slip(tenant, staffer)
    tenant.post("/api/payslips/%d/send" % sid, json={})
    sign_in(portal, staffer)
    assert [p["id"] for p in my_payslips(portal)] == [sid]
    res = portal.get("/api/employee/payslips/%d/pdf" % sid)
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF") and "Payslip_PS-" in res.headers["content-disposition"]


def test_a_paid_payslip_is_shown(tenant, portal, staffer):
    sid = make_slip(tenant, staffer)
    tenant.post("/api/payslips/%d/mark-paid" % sid)
    sign_in(portal, staffer)
    assert [p["id"] for p in my_payslips(portal)] == [sid]
    assert portal.get("/api/employee/payslips/%d/pdf" % sid).status_code == 200


def test_nobody_downloads_someone_elses_payslip(tenant, portal, staffer):
    other = make_employee(tenant, salary=30000.0)
    theirs = make_slip(tenant, other)
    tenant.post("/api/payslips/%d/mark-paid" % theirs)
    sign_in(portal, staffer)
    assert portal.get("/api/employee/payslips/%d/pdf" % theirs).status_code == 404
    assert portal.get("/api/employee/payslips/999999/pdf").status_code == 404


def test_signed_out_cannot_download(client, tenant, staffer):
    sid = make_slip(tenant, staffer)
    tenant.post("/api/payslips/%d/mark-paid" % sid)
    with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(__import__("main").app) as fresh:
        assert fresh.get("/api/employee/payslips/%d/pdf" % sid).status_code in (401, 403)
