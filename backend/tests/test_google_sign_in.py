"""Signing in with Google, for everybody who has a login - and for nobody who has not.

Google itself is stood in for: the token exchange returns the address Google would have vouched for. The
rules under test are ours - who that address is here, and that an address nobody gave a login to gets
nothing, not a new account.
"""
import pytest
from fastapi.testclient import TestClient

import main
from app import models
from test_partner_portal import gang_with_a_certified_bill, invite as portal_invite
from test_subcontract_orders import staff
from test_team import invite as team_invite


@pytest.fixture
def google(monkeypatch):
    """Google configured, and answering with whatever address the test sets."""
    said = {"email": "", "verified": True, "refresh": ""}

    async def exchange(request):
        return {"userinfo": {"email": said["email"], "email_verified": said["verified"], "name": "Someone"},
                "access_token": "at-secret", "refresh_token": said["refresh"]}

    async def redirect(request, redirect_uri, **kw):
        from starlette.responses import RedirectResponse
        return RedirectResponse("https://accounts.google.com/o/oauth2/auth?fake=1")

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(main.oauth.google, "authorize_access_token", exchange)
    monkeypatch.setattr(main.oauth.google, "authorize_redirect", redirect)
    return said


def sign_in_with_google(browser, google, email, who=""):
    google["email"] = email
    start = browser.get("/api/auth/google/start", params={"who": who} if who else {}, follow_redirects=False)
    assert start.status_code in (302, 307), start.text
    return browser.get("/api/auth/google/callback", follow_redirects=False)


def where(res):
    return res.headers.get("location", "")


def new_browser():
    return TestClient(main.app)


def clients():
    with main.SessionLocal() as db:
        return db.query(models.DBClient).count()


def test_the_master_signs_in_with_their_google_address_whatever_its_capitals(account, google):
    browser = new_browser()
    res = sign_in_with_google(browser, google, account["email"].upper())
    assert where(res).startswith("/next/") or where(res) == "/onboard.html", where(res)
    assert browser.get("/api/client/me").json()["email"] == account["email"]


def test_a_team_member_signs_in_as_themselves_on_the_masters_company(tenant, account, google):
    member, email = team_invite(tenant, role="viewer")
    browser = new_browser()
    assert where(sign_in_with_google(browser, google, email)).startswith("/next/")
    assert browser.get("/api/client/me").json()["email"] == account["email"]
    # still a viewer: reading yes, changing no
    assert browser.post("/api/jobs", json={"name": "Should not be made"}).status_code == 403
    members = tenant.get("/api/team").json()["members"]
    assert next(m for m in members if m["email"] == email)["accepted"]


def test_staff_sign_in_with_google_to_their_own_screens(tenant, google):
    emp = staff(tenant, "staff")
    browser = new_browser()
    assert where(sign_in_with_google(browser, google, emp["email"])).startswith("/next/")
    assert browser.get("/api/employee/auth/me").status_code == 200
    assert browser.get("/api/client/me").status_code == 401


def test_an_address_nobody_gave_a_login_to_gets_nothing(tenant, google):
    before = clients()
    browser = new_browser()
    res = sign_in_with_google(browser, google, "stranger@gmail.com")
    assert where(res) == "/login.html?error=google_unknown"
    assert browser.get("/api/client/me").status_code == 401
    assert clients() == before


def test_an_unverified_google_address_is_refused(account, google):
    google["verified"] = False
    browser = new_browser()
    assert where(sign_in_with_google(browser, google, account["email"])) == "/login.html?error=google_unverified"
    assert browser.get("/api/client/me").status_code == 401


def test_a_partner_signs_in_with_google_at_the_portal(tenant, google):
    order, _ = gang_with_a_certified_bill(tenant)
    import uuid
    email = "babu-%s@sribalaji.in" % uuid.uuid4().hex[:6]
    portal_invite(tenant, "contractor", order["contractor_id"], email)
    browser = new_browser()
    res = sign_in_with_google(browser, google, email.upper(), who="portal")
    assert where(res) == "/portal.html"
    assert browser.get("/api/portal/me").status_code == 200
    assert browser.get("/api/client/me").status_code == 401


def test_the_portal_door_only_opens_for_partners(account, google):
    browser = new_browser()
    res = sign_in_with_google(browser, google, account["email"], who="portal")
    assert where(res) == "/portal.html?error=google_unknown"
    assert browser.get("/api/client/me").status_code == 401


def test_connecting_gmail_never_creates_or_switches_an_account(tenant, account, google):
    before = clients()
    stranger = new_browser()
    google["email"], google["refresh"] = "stranger@gmail.com", "rt-stranger"
    res = stranger.get("/api/auth/callback", follow_redirects=False)
    assert where(res) == "/login.html?error=gmail_sign_in_first"
    assert stranger.get("/api/client/me").status_code == 401 and clients() == before

    # signed in, it attaches that Gmail to this company, and the cookie carries no Google keys
    google["email"], google["refresh"] = "accounts@gmail.com", "rt-company"
    res = tenant.get("/api/auth/callback", follow_redirects=False)
    assert where(res).startswith("/next/")
    assert tenant.get("/api/client/me").json()["email"] == account["email"]
    cid = tenant.get("/api/client/me").json()["id"]
    with main.SessionLocal() as db:
        assert main.get_stored_refresh_token(db, client_id=cid) == "rt-company"
    import base64
    cookie = tenant.cookies.get("session") or ""
    raw = base64.b64decode(cookie.split(".")[0] + "==").decode("utf8", "ignore")
    assert "client_id" in raw, "the session cookie was read"
    assert "rt-company" not in raw and "at-secret" not in raw


def test_the_platform_console_takes_only_addresses_named_for_it(google, monkeypatch):
    with main.SessionLocal() as db:
        if not db.query(models.DBSuperAdmin).filter(models.DBSuperAdmin.email == "hello@billing.com").first():
            db.add(models.DBSuperAdmin(username="superadmin", password_hash="", email="hello@billing.com"))
            db.commit()
    monkeypatch.setenv("SUPERADMIN_EMAILS", "")
    browser = new_browser()
    browser.get("/api/auth/login", params={"role": "superadmin"}, follow_redirects=False)
    google["email"] = "hello@billing.com"
    assert where(browser.get("/api/auth/callback", follow_redirects=False)) == "/superadmin-login.html?error=not_admin"
    monkeypatch.setenv("SUPERADMIN_EMAILS", "hello@billing.com")
    browser.get("/api/auth/login", params={"role": "superadmin"}, follow_redirects=False)
    assert where(browser.get("/api/auth/callback", follow_redirects=False)) == "/superadmin.html"


def test_which_gmail_the_company_sends_from_is_not_told_to_strangers():
    assert new_browser().get("/api/gmail/status").status_code == 401
