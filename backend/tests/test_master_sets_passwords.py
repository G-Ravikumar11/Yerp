"""The Master gives staff their passwords; nothing is emailed.

There is no mail server to send set-your-password links, so the Master types the password when adding somebody (or
later, from their record) and hands it over. The person signs in with their email and that password.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import main
from app import models
from tests.conftest import make_employee


@pytest.fixture(autouse=True)
def _fresh():
    main.rate_limiter._hits.clear()


@pytest.fixture
def no_mail(monkeypatch):
    sent = []
    for target in ("app.core.notifications.send_email_background", "app.routers.employee_portal.send_email_background",
                   "app.routers.auth.send_email_background"):
        monkeypatch.setattr(target, lambda *a, **k: sent.append(a))
    return sent


def staff_sign_in(c, email, password):
    return c.post("/api/employee/auth/login", json={"email": email, "password": password})


def test_an_employee_made_with_a_password_signs_in_with_it(tenant, portal, no_mail):
    e = make_employee(tenant, password="Given1Pass")
    assert "Given1Pass" not in str(e)
    detail = tenant.get(f"/api/employees/{e['id']}").json()
    assert detail["has_password"] is True and "password_hash" not in detail and "Given1Pass" not in str(detail)
    assert staff_sign_in(portal, e["email"], "Wrong1Pass").status_code == 401
    assert staff_sign_in(portal, e["email"], "Given1Pass").status_code == 200
    assert no_mail == []


def test_the_master_gives_a_password_to_somebody_added_without_one(tenant, portal, no_mail):
    e = make_employee(tenant)
    assert tenant.get(f"/api/employees/{e['id']}").json()["has_password"] is False
    assert staff_sign_in(portal, e["email"], "Given1Pass").status_code == 401
    assert tenant.put(f"/api/employees/{e['id']}/set-password", json={"password": "weak"}).status_code == 400
    r = tenant.put(f"/api/employees/{e['id']}/set-password", json={"password": "Given1Pass"})
    assert r.status_code == 200 and "Given1Pass" not in r.text
    assert tenant.get(f"/api/employees/{e['id']}").json()["has_password"] is True
    assert staff_sign_in(portal, e["email"], "Given1Pass").status_code == 200
    with main.SessionLocal() as db:
        h = db.query(models.DBEmployee).filter(models.DBEmployee.id == e["id"]).first().password_hash
        assert h and "Given1Pass" not in h
    assert no_mail == []


def test_a_new_password_from_the_master_replaces_the_old_one(tenant, portal):
    e = make_employee(tenant, password="Given1Pass")
    tenant.put(f"/api/employees/{e['id']}/set-password", json={"password": "Second2Pass"})
    assert staff_sign_in(portal, e["email"], "Given1Pass").status_code == 401
    assert staff_sign_in(portal, e["email"], "Second2Pass").status_code == 200


def test_somebody_with_no_email_cannot_be_given_a_login(tenant):
    e = make_employee(tenant, email="")
    r = tenant.put(f"/api/employees/{e['id']}/set-password", json={"password": "Given1Pass"})
    assert r.status_code == 400 and "email" in r.json()["detail"].lower()


def test_staff_and_other_companies_cannot_set_passwords(tenant, portal):
    a = make_employee(tenant, password="Given1Pass")
    b = make_employee(tenant, password="Given1Pass")
    staff_sign_in(portal, a["email"], "Given1Pass")
    assert portal.put(f"/api/employees/{b['id']}/set-password", json={"password": "Hacked1Pass"}).status_code in (401, 403)
    with TestClient(main.app) as other:
        mail = f"o-{uuid.uuid4().hex[:8]}@example.com"
        other.post("/api/client/register", json={"email": mail, "password": "Passw0rdTest", "company_name": "Other"})
        other.post("/api/client/login", json={"email": mail, "password": "Passw0rdTest"})
        assert other.put(f"/api/employees/{b['id']}/set-password", json={"password": "Hacked1Pass"}).status_code == 404
    with TestClient(main.app) as nobody:
        assert nobody.put(f"/api/employees/{b['id']}/set-password", json={"password": "Hacked1Pass"}).status_code == 401
    with TestClient(main.app) as fresh:
        assert staff_sign_in(fresh, b["email"], "Given1Pass").status_code == 200
