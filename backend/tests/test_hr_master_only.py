"""Payroll, the salary structure, the ID numbers and the documents kept on somebody are for HR and the Master only.
A team member the Master has invited - even an admin - is neither, and gets none of it."""
import base64
import uuid

import pytest
from fastapi.testclient import TestClient

import main
from conftest import make_employee

PASSWORD = "Crew1234"
UAN, ESI = "101185316896", "3100123456"
SEP = {"period_start": "2026-09-01", "period_end": "2026-09-30", "pay_date": "2026-09-30"}


@pytest.fixture
def member(tenant):
    """A team member (an admin) signed in on their own."""
    main.rate_limiter._hits.clear()
    email = "mate-%s@example.com" % uuid.uuid4().hex[:8]
    res = tenant.post("/api/team/invite", json={"email": email, "role": "admin", "name": "Colleague", "password": "Colleague123"})
    assert res.status_code == 200, res.text
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/client/login", json={"email": email, "password": "Colleague123"}).status_code == 200
    yield c
    c.__exit__(None, None, None)


@pytest.fixture
def hr(tenant):
    email = "hr-%s@example.com" % uuid.uuid4().hex[:6]
    make_employee(tenant, email=email, password=PASSWORD, permission_role="hr", status="active")
    c = TestClient(main.app)
    c.__enter__()
    assert c.post("/api/employee/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    yield c
    c.__exit__(None, None, None)


def doc():
    return {"title": "PAN card", "doc_type": "identity", "file_name": "p.pdf", "file_type": "application/pdf",
            "file_data": base64.b64encode(b"%PDF-1.4 x").decode()}


def test_a_team_member_gets_no_payroll_at_all(tenant, member):
    emp = make_employee(tenant, salary=65000.0)
    pid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **SEP}).json()["id"]
    for url in ("/api/payslips", "/api/payslips/%d" % pid, "/api/payslips/%d/pdf" % pid, "/api/payslips/%d/xlsx" % pid,
                "/api/payslips/register.xlsx", "/api/salary-structure", "/api/payroll/auto"):
        assert member.get(url).status_code == 403, url
    assert member.post("/api/payslips", json={"employee_id": emp["id"], **SEP}).status_code == 403
    assert member.post("/api/salary-structure", json={"name": "X"}).status_code == 403
    assert member.put("/api/payslips/%d" % pid, json={"bonus": 1}).status_code == 403
    assert member.delete("/api/payslips/%d" % pid).status_code == 403


def test_hr_and_the_master_get_all_of_it(tenant, hr):
    emp = make_employee(tenant, salary=65000.0)
    pid = tenant.post("/api/payslips", json={"employee_id": emp["id"], **SEP}).json()["id"]
    for who in (tenant, hr):
        for url in ("/api/payslips", "/api/payslips/%d" % pid, "/api/payslips/%d/pdf" % pid, "/api/payslips/%d/xlsx" % pid,
                    "/api/payslips/register.xlsx", "/api/salary-structure"):
            assert who.get(url).status_code == 200, url


def test_the_documents_kept_on_somebody_are_for_hr_and_the_master(tenant, member, hr):
    emp = make_employee(tenant)
    base = "/api/employees/%d/documents" % emp["id"]
    assert hr.post(base, json=doc()).status_code == 200
    made = tenant.get(base).json()
    assert len(made) == 1 and len(hr.get(base).json()) == 1
    did = made[0]["id"]
    assert member.get(base).status_code == 403
    assert member.post(base, json=doc()).status_code == 403
    assert member.get("%s/%d/download" % (base, did)).status_code == 403
    assert member.delete("%s/%d" % (base, did)).status_code == 403
    # the whole-person view does not list them either
    assert len(tenant.get("/api/employees/%d" % emp["id"]).json()["documents"]) == 1
    assert member.get("/api/employees/%d" % emp["id"]).json()["documents"] == []


def test_the_id_numbers_are_hidden_from_and_not_saved_by_anybody_else(tenant, member, hr):
    emp = make_employee(tenant, uan_no=UAN, esi_no=ESI, pan_no="ABCDE1234F", aadhaar_no="801874264479")
    url = "/api/employees/%d?view=profile" % emp["id"]
    for who in (tenant, hr):
        got = who.get(url).json()
        assert (got["uan_no"], got["esi_no"], got["pan_no"], got["aadhaar_masked"]) == (UAN, ESI, "ABCDE1234F", "XXXX XXXX 4479")
    seen = member.get(url).json()
    assert (seen["uan_no"], seen["esi_no"], seen["pan_no"], seen["aadhaar_masked"]) == ("", "", "", "")
    # a team member's save does not touch them, nor can they enter them
    assert member.put("/api/employees/%d" % emp["id"], json={"job_title": "Clerk", "uan_no": "999999999999", "esi_no": ""}).status_code == 200
    kept = tenant.get(url).json()
    assert kept["job_title"] == "Clerk" and kept["uan_no"] == UAN and kept["esi_no"] == ESI
    made = member.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": "m-%s@example.com" % uuid.uuid4().hex[:6],
                                                "uan_no": UAN, "esi_no": ESI, "gender": "Male"})
    assert made.status_code == 200, made.text
    assert tenant.get("/api/employees/%d?view=profile" % made.json()["id"]).json()["uan_no"] == ""
    # while HR enters them
    hr_made = hr.post("/api/employees", json={"first_name": "C", "last_name": "D", "email": "h-%s@example.com" % uuid.uuid4().hex[:6],
                                              "uan_no": UAN, "esi_no": ESI, "gender": "Male"})
    assert hr_made.status_code == 200, hr_made.text
    assert tenant.get("/api/employees/%d?view=profile" % hr_made.json()["id"]).json()["uan_no"] == UAN


def test_the_salary_structure_preview_is_not_shown_to_a_team_member(tenant, member):
    emp = make_employee(tenant, salary=65000.0)
    url = "/api/employees/%d/pay-details?period_start=2026-09-01&period_end=2026-09-30" % emp["id"]
    assert tenant.get(url).json()["structure"]
    assert member.get(url).json()["structure"] is None
