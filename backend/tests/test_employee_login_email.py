"""The login email: to the organisation's address only, with the password that was typed, and the password kept nowhere.

Mail itself is stood in for; what is under test is what goes out, to whom, and what is left behind.
"""
import email
import uuid
from email import policy

import pytest

import main
from app import models
from app.core import notifications
from app.services.login_email import login_email
from tests._patching import patch_app
from tests.conftest import make_employee

PASSWORD = "Given1Pass<&"


@pytest.fixture(autouse=True)
def _fresh():
    main.rate_limiter._hits.clear()


@pytest.fixture
def mail(monkeypatch):
    sent = []
    patch_app(monkeypatch, "send_email_background",
              lambda to, subject, body, sender, html, *a, **k: sent.append(dict(to=to, subject=subject, body=body, html=html)) or (True, "Email sent via Gmail API"))
    return sent


def org():
    return "org-%s@acme.example" % uuid.uuid4().hex[:8]


def status_of(tenant, emp_id):
    return tenant.get(f"/api/employees/{emp_id}").json()["credentials_email_status"]


def test_adding_an_employee_emails_nobody_until_send_is_clicked(tenant, portal, mail):
    work = org()
    e = make_employee(tenant, password=PASSWORD, org_email=work, first_name="Asha", last_name="Rao")
    assert PASSWORD not in str(e)
    assert mail == [] and status_of(tenant, e["id"]) == ""          # an email goes out only when somebody clicks send
    assert portal.post("/api/employee/auth/login", json={"email": work, "password": PASSWORD}).status_code == 200

    r = tenant.post(f"/api/employees/{e['id']}/login-email")         # Send login email, on their page
    assert r.status_code == 200 and r.json()["ok"] is True
    assert [m["to"] for m in mail] == [work] and e["email"] != work
    assert "Employee ID: %s" % e["employee_id"] in mail[0]["body"] and PASSWORD not in mail[0]["body"]
    assert status_of(tenant, e["id"]) == "sent"


def test_the_password_is_left_nowhere_but_the_hash(tenant, mail):
    e = make_employee(tenant, password=PASSWORD, org_email=org())
    detail = tenant.get(f"/api/employees/{e['id']}").text
    assert PASSWORD not in detail and "password_hash" not in detail
    with main.SessionLocal() as db:
        row = db.query(models.DBEmployee).filter(models.DBEmployee.id == e["id"]).first()
        assert PASSWORD not in " ".join(str(v) for v in vars(row).values())


def test_nothing_goes_out_without_a_password_or_without_an_organisation_address(tenant, mail):
    no_login = make_employee(tenant, org_email=org())
    no_org = make_employee(tenant, password=PASSWORD)
    assert mail == []
    assert status_of(tenant, no_login["id"]) == "" and status_of(tenant, no_org["id"]) == ""


def test_a_resend_makes_no_new_employee_and_carries_a_one_time_link_not_a_password(tenant, portal, mail):
    work = org()
    e = make_employee(tenant, password=PASSWORD, org_email=work)
    before = len(tenant.get("/api/employees").json())
    del mail[:]

    r = tenant.post(f"/api/employees/{e['id']}/login-email")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["credentials_email_status"] == "sent"
    assert len(tenant.get("/api/employees").json()) == before
    assert [m["to"] for m in mail] == [work]
    body = mail[0]["body"]
    assert "Password:" not in body and PASSWORD not in body and "Employee ID: %s" % e["employee_id"] in body
    assert portal.post("/api/employee/auth/login", json={"email": work, "password": PASSWORD}).status_code == 200    # theirs still stands

    token = body.split("token=")[1].split("&")[0]
    assert portal.post("/api/client/reset-password", json={"token": token, "password": "Chosen2Pass"}).status_code == 200
    assert portal.post("/api/client/reset-password", json={"token": token, "password": "Other3Pass"}).status_code == 400   # once only
    assert portal.post("/api/employee/auth/login", json={"email": work, "password": "Chosen2Pass"}).status_code == 200


def test_a_resend_that_fails_is_recorded(tenant, monkeypatch, mail):
    e = make_employee(tenant, password=PASSWORD, org_email=org())
    patch_app(monkeypatch, "send_email_background", lambda *a, **k: (False, "Gmail API error: invalid_grant token=secret"))
    r = tenant.post(f"/api/employees/{e['id']}/login-email")
    assert r.status_code == 200 and r.json()["ok"] is False and "secret" not in r.text
    assert status_of(tenant, e["id"]) == "failed"


def test_a_resend_needs_an_organisation_address_and_somebody_still_here(tenant, mail):
    e = make_employee(tenant)
    assert tenant.post(f"/api/employees/{e['id']}/login-email").status_code == 400
    assert tenant.post("/api/employees/99999999/login-email").status_code == 404
    assert mail == []


def test_resends_are_limited(tenant, mail):
    e = make_employee(tenant, org_email=org())
    codes = [tenant.post(f"/api/employees/{e['id']}/login-email").status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


def test_a_blank_address_never_matches_somebody_with_no_organisation_email(tenant, portal, mail):
    make_employee(tenant, password=PASSWORD)
    assert portal.post("/api/employee/auth/login", json={"email": "   ", "password": PASSWORD}).status_code == 401


def test_the_message_goes_out_whole_with_its_dash_and_password_intact():
    subject, text_body, html_body = login_email("Acme Infra", "Asha Rao", "EMP-0007", "asha@acme.example", "https://x/next/login", password="Given1Pass")
    raw = notifications.prepare_email_message("asha@acme.example", subject, text_body, html_body, "Acme Infra <a@b.c>")
    parsed = email.message_from_string(raw, policy=policy.default)
    assert parsed["Subject"] == "Welcome to Acme Infra – Your Login Credentials"
    assert "Password: Given1Pass" in parsed.get_body(preferencelist=("plain",)).get_content()
    assert "Given1Pass" in parsed.get_body(preferencelist=("html",)).get_content()


def test_a_message_has_a_date_with_its_timezone_and_no_empty_html_part():
    parsed = email.message_from_string(notifications.prepare_email_message("a@b.c", "Hi", "plain words", "", "Co <a@b.c>"), policy=policy.default)
    assert parsed["Date"].datetime.tzinfo is not None
    assert [p.get_content_type() for p in parsed.walk() if not p.is_multipart()] == ["text/plain"]


def test_a_message_to_one_person_does_not_dress_as_a_mailing_list():
    raw = notifications.prepare_email_message("a@b.c", "Hi", "plain words", "<p>hi</p>", "Co <a@b.c>")
    assert "List-Unsubscribe" not in raw
