"""Sign-in pages that cannot be hammered: the visitor's real address, a CAPTCHA once there is reason to doubt them,
ten wrong passwords shutting out the address they came from (never the Master), and a limit on how fast one address may ask the API anything.
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


def test_an_old_cookie_cannot_bring_a_spent_captcha_back(account, captcha_on):
    c, email = account["client"], account["email"]
    for _ in range(3):
        login(c, email, "wrong")
    answer = solve(c)
    first = login(c, email, "wrong", **answer)                             # solved: this try, and the staff door's
    assert first.status_code == 401
    kept = first.headers["set-cookie"].split(";")[0]                       # the cookie as it was handed back
    assert c.post("/api/employee/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    # Whoever kept that cookie and sends it again, over and over, is not let through without a new CAPTCHA.
    with TestClient(main.app) as replay:
        replay.headers["cookie"] = kept
        codes = [login(replay, email, "wrong").status_code for _ in range(4)]
    assert codes[-1] == 428 and codes.count(401) <= 1


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

def colleague(account, password="Colleague123"):
    """A colleague the Master has given a password: an account that can be locked, unlike the Master's own."""
    email = f"mate-{uuid.uuid4().hex[:8]}@example.com"
    r = account["client"].post("/api/team/invite", json={"email": email, "name": "Mate", "role": "admin", "password": password})
    assert r.status_code == 200, r.text
    return email


def from_address(monkeypatch, c, address):
    """Requests from `c` as if they came from `address` (the proxy's right-most X-Forwarded-For entry)."""
    monkeypatch.setenv("TRUST_PROXY", "1")
    c.headers["X-Forwarded-For"] = address


def security_alerts(email):
    with database.SessionLocal() as s:
        return s.query(models.DBAlert).filter(models.DBAlert.kind == "security_lock", models.DBAlert.title.contains(email)).count()


def test_nobody_can_lock_the_master_out(account, monkeypatch):
    c, email = account["client"], account["email"]
    with TestClient(main.app) as attacker:
        from_address(monkeypatch, attacker, "203.0.113.9")
        for _ in range(25):
            calm()
            assert login(attacker, email, "wrong").status_code == 401        # refused, never locked
    calm()
    assert login(c, email, PASSWORD).status_code == 200                  # the Master signs straight in
    assert security_alerts(email) == 1, "and is told, once, that somebody has been guessing"


def test_ten_wrong_passwords_shut_out_the_guesser_not_the_person(account, monkeypatch):
    email = colleague(account)
    with TestClient(main.app) as attacker:
        from_address(monkeypatch, attacker, "203.0.113.9")
        for _ in range(10):
            calm()
            assert login(attacker, email, "wrong").status_code == 401
        calm()
        locked = login(attacker, email, "Colleague123")                  # even the right password, from there
        assert locked.status_code == 429 and locked.json()["code"] == "YE-AUTH-10"
    with TestClient(main.app) as person:
        from_address(monkeypatch, person, "198.51.100.4")
        calm()
        assert login(person, email, "Colleague123").status_code == 200   # the colleague, from anywhere else
    assert security_alerts(email) == 1
    with TestClient(main.app) as attacker:
        from_address(monkeypatch, attacker, "203.0.113.9")
        login(attacker, email, "wrong")
    assert security_alerts(email) == 1, "told once, not at every try"
    login_guard.failures.reset()                                           # fifteen minutes on
    with TestClient(main.app) as attacker:
        from_address(monkeypatch, attacker, "203.0.113.9")
        calm()
        assert login(attacker, email, "Colleague123").status_code == 200


def test_a_new_password_clears_the_lock(account, monkeypatch):
    email = colleague(account)
    with TestClient(main.app) as here:
        from_address(monkeypatch, here, "203.0.113.9")
        for _ in range(10):
            calm()
            login(here, email, "wrong")
        calm()
        assert login(here, email, "Colleague123").status_code == 429
        # The Master gives them a new password: nothing counted against the account stands any more.
        member = next(m for m in account["client"].get("/api/team").json()["members"] if m["email"] == email)
        assert account["client"].put(f"/api/team/{member['id']}", json={"password": "Fresh456Pass"}).status_code == 200
        calm()
        assert login(here, email, "Fresh456Pass").status_code == 200


def test_a_reset_link_clears_the_lock(account, monkeypatch):
    from datetime import datetime, timedelta
    email = colleague(account)
    with TestClient(main.app) as here:
        from_address(monkeypatch, here, "203.0.113.9")
        for _ in range(10):
            calm()
            login(here, email, "wrong")
        calm()
        assert login(here, email, "Colleague123").status_code == 429
        raw = uuid.uuid4().hex                                             # the link the email would carry
        with database.SessionLocal() as s:
            m = s.query(models.DBTeamMember).filter(models.DBTeamMember.email == email).first()
            s.add(models.DBPasswordReset(user_type="member", member_id=m.id, token_hash=main.hash_reset_token(raw),
                                         expires_at=(datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
            s.commit()
        assert here.post("/api/client/reset-password", json={"token": raw, "password": "Fresh456Pass"}).status_code == 200
        calm()
        assert login(here, email, "Fresh456Pass").status_code == 200


def test_a_staff_member_is_locked_only_from_where_the_guessing_came(tenant, monkeypatch):
    e = make_employee(tenant, password="Staff123Pass")
    with TestClient(main.app) as attacker:
        from_address(monkeypatch, attacker, "203.0.113.9")
        for _ in range(10):
            calm()
            attacker.post("/api/employee/auth/login", json={"email": e["email"], "password": "wrong"})
        calm()
        assert attacker.post("/api/employee/auth/login", json={"email": e["email"], "password": "Staff123Pass"}).status_code == 429
    with TestClient(main.app) as person:
        from_address(monkeypatch, person, "198.51.100.4")
        calm()
        assert person.post("/api/employee/auth/login", json={"email": e["email"], "password": "Staff123Pass"}).status_code == 200


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
