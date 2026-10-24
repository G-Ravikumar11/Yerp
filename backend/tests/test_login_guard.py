"""Sign-in pages that cannot be hammered: the visitor's real address, a CAPTCHA once there is reason to doubt them,
an account locked after ten wrong passwords, and a limit on how fast one address may ask the API anything.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import main
from app import db as database, models
from app.core import login_guard
from conftest import make_employee

PASSWORD = "Passw0rdTest"


@pytest.fixture
def captcha_on(monkeypatch):
    monkeypatch.setenv("CAPTCHA_MODE", "builtin")
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    # Every drawn CAPTCHA reads AAAAA, so the test can answer it.
    monkeypatch.setattr(login_guard.secrets, "choice", lambda alphabet: "A")


def login(c, email, password, **extra):
    return c.post("/api/client/login", json={"email": email, "password": password, **extra})


def calm():
    """The per-address limit (ten sign-ins a minute) forgotten, to count the per-account ones past it."""
    main.rate_limiter._hits.clear()


def solve(c):
    ch = c.get("/api/captcha").json()
    assert ch["provider"] == "builtin" and ch["image"].startswith("data:image/png;base64,")
    return {"captcha_token": ch["token"], "captcha_answer": "AAAAA"}


def test_the_captcha_answer_must_match_capital_and_small_letters(client, captcha_on, monkeypatch):
    letters = iter("AbAbA")
    monkeypatch.setattr(login_guard.secrets, "choice", lambda alphabet: next(letters))
    drawn = login_guard._signer().loads(client.get("/api/captcha").json()["token"])["d"]
    assert login_guard._digest("AbAbA") == drawn
    assert login_guard._digest("ababa") != drawn and login_guard._digest("ABABA") != drawn


# --- the address -----------------------------------------------------------------------------------------------------

def test_the_address_is_the_one_the_proxy_saw_not_the_one_the_visitor_wrote(monkeypatch):
    h = [(b"x-forwarded-for", b"1.2.3.4, 203.0.113.9")]
    assert login_guard.address_from(h, "10.0.0.1") == "203.0.113.9"        # Railway appends the real one
    assert login_guard.address_from([], "10.0.0.1") == "10.0.0.1"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")                          # a CDN in front of Railway as well
    assert login_guard.address_from(h, "10.0.0.1") == "1.2.3.4"


def test_writing_a_new_address_on_every_try_does_not_get_round_the_limit(account, monkeypatch):
    c = account["client"]
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    codes = [c.post("/api/client/login", json={"email": account["email"], "password": "wrong"},
                    headers={"X-Forwarded-For": "6.6.6.%d, 198.51.100.7" % i}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[-1] == 429


# --- the CAPTCHA -----------------------------------------------------------------------------------------------------

def test_nobody_is_asked_until_there_is_reason(account, captcha_on):
    c = account["client"]
    assert login(c, account["email"], PASSWORD).status_code == 200


def test_three_wrong_passwords_and_the_next_try_needs_the_captcha(account, captcha_on):
    c, email = account["client"], account["email"]
    for _ in range(3):
        assert login(c, email, "wrong").status_code == 401
    asked = login(c, email, PASSWORD)
    assert asked.status_code == 428 and asked.json()["code"] == "YE-AUTH-09"
    # A wrong answer is refused; the right one, with the right password, signs in.
    bad = login(c, email, PASSWORD, captcha_token=solve(c)["captcha_token"], captcha_answer="ZZZZZ")
    assert bad.status_code == 428
    ok = login(c, email, PASSWORD, **solve(c))
    assert ok.status_code == 200, ok.text


def test_a_solved_captcha_covers_one_sign_in_and_cannot_be_used_again(account, captcha_on):
    c, email = account["client"], account["email"]
    for _ in range(3):
        login(c, email, "wrong")
    answer = solve(c)
    assert login(c, email, "wrong", **answer).status_code == 401           # solved, wrong password
    # The same sign-in's second request (the staff door) needs nothing more...
    assert c.post("/api/employee/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    # ...but the next guess does, and the old answer is spent.
    assert login(c, email, "wrong").status_code == 428
    with TestClient(main.app) as other:                                    # even from a fresh browser
        assert login(other, email, PASSWORD, **answer).status_code == 428


def test_trying_address_after_address_needs_the_captcha_too(client, captcha_on):
    for i in range(3):
        assert client.post("/api/employee/auth/login",
                           json={"email": "nobody%d@example.com" % i, "password": "x"}).status_code == 401
    assert client.post("/api/employee/auth/login", json={"email": "nobody9@example.com", "password": "x"}).status_code == 428


def test_a_staff_member_signing_in_is_not_counted_at_the_owners_door(tenant, client, captcha_on):
    email = "se-%s@example.com" % uuid.uuid4().hex[:8]
    make_employee(tenant, email=email, password="Crew1234", status="active")
    for _ in range(4):                                                     # as the sign-in page does: owner, then staff
        assert login(client, email, "Crew1234").status_code == 401
        assert client.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200


def test_the_forgotten_password_form_always_asks(client, captcha_on):
    assert client.post("/api/client/forgot-password", json={"email": "a@example.com"}).status_code == 428
    answer = solve(client)
    assert client.post("/api/client/forgot-password", json={"email": "a@example.com", **answer}).status_code == 200
    # The page asks for the staff link next, with the same check.
    assert client.post("/api/employee/forgot-password", json={"email": "a@example.com"}).status_code == 200
    assert client.post("/api/client/forgot-password", json={"email": "a@example.com"}).status_code == 428


def test_turnstile_is_used_when_its_keys_are_set(client, monkeypatch):
    monkeypatch.setenv("CAPTCHA_MODE", "auto")
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "0x4AAAA-site")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "0x4AAAA-secret")
    assert client.get("/api/captcha").json() == {"provider": "turnstile", "site_key": "0x4AAAA-site"}
    monkeypatch.setattr(login_guard, "_turnstile_ok", lambda token, ip: token == "good")
    assert client.post("/api/client/forgot-password", json={"email": "a@example.com", "captcha_token": "bad"}).status_code == 428
    assert client.post("/api/client/forgot-password", json={"email": "a@example.com", "captcha_token": "good"}).status_code == 200


# --- the lock --------------------------------------------------------------------------------------------------------

def test_ten_wrong_passwords_lock_the_account_and_the_master_is_told(account):
    c, email = account["client"], account["email"]
    calm()
    for _ in range(10):
        assert login(c, email, "wrong").status_code == 401
    calm()
    locked = login(c, email, PASSWORD)                                     # even the right password
    assert locked.status_code == 429 and locked.json()["code"] == "YE-AUTH-10"
    with database.SessionLocal() as s:
        mine = lambda: s.query(models.DBAlert).filter(models.DBAlert.kind == "security_lock",
                                                      models.DBAlert.title.contains(email)).count()
        assert mine() == 1
    login(c, email, "wrong")                                               # told once, not at every try
    with database.SessionLocal() as s:
        assert s.query(models.DBAlert).filter(models.DBAlert.kind == "security_lock",
                                              models.DBAlert.title.contains(email)).count() == 1
    login_guard.failures.reset()                                           # fifteen minutes on
    assert login(c, email, PASSWORD).status_code == 200


def test_the_right_password_starts_the_count_again(account):
    c, email = account["client"], account["email"]
    calm()
    for _ in range(9):
        login(c, email, "wrong")
    calm()
    assert login(c, email, PASSWORD).status_code == 200
    for _ in range(9):
        login(c, email, "wrong")
    calm()
    assert login(c, email, PASSWORD).status_code == 200


# --- the flood and the headers --------------------------------------------------------------------------------------

def test_one_address_asking_too_fast_is_told_to_wait(client, monkeypatch):
    monkeypatch.setenv("API_FLOOD_PER_MINUTE", "20")
    codes = [client.get("/api/captcha").status_code for _ in range(25)]
    assert codes.count(429) >= 5
    assert client.get("/api/health").status_code == 200                    # the health check is never refused


def test_security_headers_are_sent(client):
    h = client.get("/api/health").headers
    assert h["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert "camera=(self)" in h["Permissions-Policy"] and h["X-Content-Type-Options"] == "nosniff"
