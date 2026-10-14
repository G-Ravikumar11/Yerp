"""Remember me: a persistent cookie and a long expiry when ticked, a browser-session cookie when not."""
import time

import main
from fastapi.testclient import TestClient

from app.core.config import REMEMBER_MAX_AGE, SESSION_MAX_AGE


def sign_in(account, **extra):
    with TestClient(main.app) as c:
        res = c.post("/api/client/login", json={"email": account["email"], "password": account["password"], **extra})
        assert res.status_code == 200, res.text
        cookie = next(v for k, v in res.headers.multi_items() if k == "set-cookie" and v.startswith("session="))
        return c, cookie


def test_ticked_gives_a_persistent_cookie(account):
    c, cookie = sign_in(account, rememberMe=True)
    assert f"Max-Age={REMEMBER_MAX_AGE}" in cookie
    assert c.get("/api/client/me").status_code == 200


def test_unticked_or_missing_gives_a_session_cookie(account):
    for extra in ({"rememberMe": False}, {}):
        c, cookie = sign_in(account, **extra)
        assert "max-age" not in cookie.lower() and "expires" not in cookie.lower()
        assert c.get("/api/client/me").status_code == 200


def test_the_server_enforces_the_shorter_lifetime(account, monkeypatch):
    c, _ = sign_in(account, rememberMe=False)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + SESSION_MAX_AGE + 60)
    assert c.get("/api/client/me").status_code == 401
    c2, _ = sign_in(account, rememberMe=True)
    monkeypatch.setattr(time, "time", lambda: real() + SESSION_MAX_AGE + 60)
    assert c2.get("/api/client/me").status_code == 200


def test_logout_ends_the_session(account):
    c, _ = sign_in(account, rememberMe=True)
    c.post("/api/client/logout")
    assert c.get("/api/client/me").status_code == 401
