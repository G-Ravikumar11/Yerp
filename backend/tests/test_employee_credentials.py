"""The Master gives a member of staff a login; the member of staff signs in and chooses their own password.

Staff accounts are made only by the Master, with an initial password. That password is only good for the first sign-in:
until the person has changed it, the one thing their session can do is change it.
"""
import uuid

import pytest

import main
from app import models
from tests.conftest import as_owner, make_employee

INITIAL = "Initial1Pass"
NEW = "Chosen2Password"


@pytest.fixture(autouse=True)
def _limiter(monkeypatch):
    monkeypatch.setenv("FORCE_FIRST_PASSWORD_CHANGE", "1")
    main.rate_limiter._hits.clear()
    yield


def staff(tenant, **kw):
    return make_employee(tenant, password=INITIAL, **kw)


def sign_in(c, email, password):
    return c.post("/api/employee/auth/login", json={"email": email, "password": password})


def test_the_master_creates_an_employee_and_only_a_hash_is_kept(tenant):
    e = staff(tenant, employee_id="EMP-X1")
    assert INITIAL not in str(e) and "password" not in str(e).lower().replace("must_change_password", "")
    with main.SessionLocal() as db:
        row = db.query(models.DBEmployee).filter(models.DBEmployee.id == e["id"]).first()
        assert row.password_hash and INITIAL not in row.password_hash
        assert row.must_change_password is True and row.status == "onboarding"
    assert INITIAL not in tenant.get(f"/api/employees/{e['id']}").text
    assert INITIAL not in tenant.get("/api/employees").text


def test_a_duplicate_email_or_employee_id_is_refused(tenant):
    e = staff(tenant, employee_id="EMP-DUP")
    same_email = tenant.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": e["email"].upper(), "password": INITIAL})
    assert same_email.status_code == 400
    same_id = tenant.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": f"o-{uuid.uuid4().hex[:8]}@example.com", "password": INITIAL, "employee_id": "EMP-DUP"})
    assert same_id.status_code == 400


def test_a_weak_initial_password_is_refused(tenant):
    r = tenant.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": f"w-{uuid.uuid4().hex[:8]}@example.com", "password": "weak"})
    assert r.status_code == 400


def test_the_employee_signs_in_with_the_initial_password_and_nobody_with_a_wrong_one(tenant, portal):
    e = staff(tenant)
    assert sign_in(portal, e["email"], "Wrong9Password").status_code == 401
    assert sign_in(portal, e["email"].upper(), INITIAL).status_code == 200
    me = portal.get("/api/employee/auth/me")
    assert me.status_code == 200 and me.json()["must_change_password"] is True


def test_until_it_is_changed_the_first_password_only_opens_the_change_page(tenant, portal):
    e = staff(tenant)
    sign_in(portal, e["email"], INITIAL)
    blocked = portal.get("/api/employee/profile")
    assert blocked.status_code == 403 and "new password" in blocked.json()["detail"].lower()
    assert portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW, "confirm_password": NEW}).status_code == 200
    assert portal.get("/api/employee/profile").status_code == 200


def test_changing_the_password(tenant, portal):
    e = staff(tenant)
    sign_in(portal, e["email"], INITIAL)
    wrong = portal.post("/api/auth/change-password", json={"current_password": "Nope1234Pass", "new_password": NEW, "confirm_password": NEW})
    assert wrong.status_code == 400 and "current password" in wrong.json()["detail"].lower()
    for new, why in ((INITIAL, "different"), ("short", ""), ("alllowercase1", "")):
        assert portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": new, "confirm_password": new}).status_code == 400, why
    assert portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW, "confirm_password": "Other3Password"}).status_code == 400
    ok = portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW, "confirm_password": NEW})
    assert ok.status_code == 200 and NEW not in ok.text
    # Still signed in, and the flag is down.
    assert portal.get("/api/employee/auth/me").json()["must_change_password"] is False
    with TestClientFor() as fresh:
        assert sign_in(fresh, e["email"], INITIAL).status_code == 401      # the old one is dead
        assert sign_in(fresh, e["email"], NEW).status_code == 200          # the new one works


def TestClientFor():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def test_nobody_can_change_a_password_without_signing_in(client):
    r = client.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW})
    assert r.status_code == 401


def test_the_session_decides_whose_password_changes(tenant, portal):
    a, b = staff(tenant), staff(tenant)
    sign_in(portal, a["email"], INITIAL)
    # Naming somebody else in the request changes nothing about whose password this is.
    portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW, "confirm_password": NEW, "employee_id": b["id"], "email": b["email"]})
    with TestClientFor() as other:
        assert sign_in(other, b["email"], INITIAL).status_code == 200
    with TestClientFor() as other:
        assert sign_in(other, a["email"], NEW).status_code == 200


def test_an_employee_cannot_use_the_masters_pages(tenant, portal):
    e = staff(tenant)
    sign_in(portal, e["email"], INITIAL)
    portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW, "confirm_password": NEW})
    assert portal.get("/api/employees").status_code in (401, 403)
    assert portal.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": f"z-{uuid.uuid4().hex[:8]}@example.com", "password": INITIAL}).status_code in (401, 403)
    assert portal.put(f"/api/employees/{e['id']}/set-password", json={"password": "Hacked1Pass"}).status_code in (401, 403)


def test_the_masters_reset_asks_for_a_new_choice_again(tenant, portal):
    e = staff(tenant)
    sign_in(portal, e["email"], INITIAL)
    portal.post("/api/auth/change-password", json={"current_password": INITIAL, "new_password": NEW})
    as_owner(tenant)
    assert tenant.put(f"/api/employees/{e['id']}/set-password", json={"password": "Reset4Password"}).status_code == 200
    with TestClientFor() as fresh:
        sign_in(fresh, e["email"], "Reset4Password")
        assert fresh.get("/api/employee/auth/me").json()["must_change_password"] is True


def test_unauthenticated_requests_to_the_protected_apis_are_refused(client):
    for path in ("/api/employees", "/api/employee/profile"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/employees", json={"first_name": "A", "last_name": "B"}).status_code == 401
