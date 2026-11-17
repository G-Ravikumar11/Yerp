"""Staff sign in with an employee ID (EMP-0002) and their password as well as with their email. An ID signs in only when
exactly one person has it, the wrong-password rules count its tries like an email's, and the Master still signs in by email."""
import uuid

from fastapi.testclient import TestClient

import main
from app import db as database, models
from conftest import make_employee

PASSWORD = "Crew1234x"


def staff(tenant, **kw):
    """An employee with an ID of their own. IDs count up from EMP-0001 in every company, and the suite keeps every test's
    companies in one database, so the generated one would be shared - and a shared ID signs nobody in."""
    emp = make_employee(tenant, password=PASSWORD, status="active", **kw)
    with database.SessionLocal() as s:
        s.get(models.DBEmployee, emp["id"]).employee_id = "T-%s" % uuid.uuid4().hex[:8].upper()
        s.commit()
    return emp


def code_of(emp):
    with database.SessionLocal() as s:
        return s.get(models.DBEmployee, emp["id"]).employee_id


def login(who, password=PASSWORD):
    with TestClient(main.app) as c:
        return c.post("/api/employee/auth/login", json={"email": who, "password": password})


def test_an_employee_signs_in_with_their_id_and_password(tenant):
    emp = staff(tenant)
    code = code_of(emp)
    res = login(code)
    assert res.status_code == 200, res.text
    assert res.json()["employee"]["id"] == emp["id"]
    assert login(code.lower()).status_code == 200                 # capitals and stray spaces do not matter
    assert login("  %s " % code).status_code == 200
    assert login(emp["email"]).status_code == 200                 # and the email still works


def test_a_wrong_password_or_an_unknown_id_is_refused_alike(tenant):
    emp = staff(tenant)
    code = code_of(emp)
    bad = login(code, "not-the-password")
    unknown = login("EMP-99999")
    assert bad.status_code == 401 and unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]       # nothing says which IDs exist
    assert login("").status_code == 400 and login("@").status_code == 401


def test_an_id_two_people_share_signs_nobody_in(tenant):
    a, b = staff(tenant), staff(tenant)
    with database.SessionLocal() as s:                           # an old duplicate, from before IDs were checked
        s.get(models.DBEmployee, b["id"]).employee_id = code_of(a).lower()
        s.commit()
    assert login(code_of(a)).status_code == 401
    assert login(a["email"]).status_code == 200 and login(b["email"]).status_code == 200


def test_an_id_cannot_be_given_twice_whatever_its_capitals(tenant):
    a = staff(tenant)
    res = tenant.post("/api/employees", json={"first_name": "Dup", "last_name": "Licate", "email": "dup-%s@example.com" % uuid.uuid4().hex[:8],
                                              "employee_id": " " + code_of(a).lower(), "salary": 1000, "status": "active"})
    assert res.status_code == 400 and "already in use" in res.json()["detail"], res.text


def test_a_left_employee_cannot_sign_in_by_id(tenant):
    emp = staff(tenant)
    with database.SessionLocal() as s:
        s.get(models.DBEmployee, emp["id"]).status = "terminated"
        s.commit()
    assert login(code_of(emp)).status_code == 403


def test_trying_an_id_with_wrong_passwords_locks_it_like_an_email(tenant, monkeypatch):
    from app.core import login_guard
    monkeypatch.setattr(login_guard, "LOCK_AFTER", 3)
    emp = staff(tenant)
    code = code_of(emp)
    with TestClient(main.app) as c:                               # one browser, one address
        for _ in range(3):
            assert c.post("/api/employee/auth/login", json={"email": code, "password": "wrong"}).status_code == 401
        locked = c.post("/api/employee/auth/login", json={"email": code, "password": PASSWORD})
    assert locked.status_code == 429


def test_the_master_is_not_signed_in_by_an_id(tenant, account):
    with TestClient(main.app) as c:
        res = c.post("/api/client/login", json={"email": "EMP-0001", "password": account["password"]})
    assert res.status_code == 401
