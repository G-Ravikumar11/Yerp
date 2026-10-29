"""Signing in with Yahoo, for everybody who has a login - and for nobody who has not. Sign in with Google has been
retired in its place; Google still connects Gmail for sending mail, and still opens the platform console.

Yahoo and Google themselves are stood in for: the token exchange returns the address they would have vouched for. The
rules under test are ours - who that address is here, and that an address nobody gave a login to gets nothing, not a
new account.
"""
import pytest
from fastapi.testclient import TestClient

import main
from app import models
from test_partner_portal import contractor_with_a_certified_bill, invite as portal_invite
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


@pytest.fixture
def yahoo(monkeypatch):
    """Yahoo configured, and answering with whatever address the test sets."""
    said = {"email": "", "verified": True}

    async def exchange(request):
        return {"userinfo": {"email": said["email"], "email_verified": said["verified"], "name": "Someone"}}

    async def redirect(request, redirect_uri, **kw):
        from starlette.responses import RedirectResponse
        return RedirectResponse("https://api.login.yahoo.com/oauth2/request_auth?fake=1")

    monkeypatch.setenv("YAHOO_CLIENT_ID", "yahoo-id")
    monkeypatch.setenv("YAHOO_CLIENT_SECRET", "secret")
    monkeypatch.setattr(main.oauth.yahoo, "authorize_access_token", exchange)
    monkeypatch.setattr(main.oauth.yahoo, "authorize_redirect", redirect)
    return said


def sign_in_with_yahoo(browser, yahoo, email, who=""):
    yahoo["email"] = email
    start = browser.get("/api/auth/yahoo/start", params={"who": who} if who else {}, follow_redirects=False)
    assert start.status_code in (302, 307), start.text
    assert "yahoo.com" in start.headers.get("location", ""), "the real Yahoo flow starts"
    return browser.get("/api/auth/yahoo/callback", follow_redirects=False)


def where(res):
    return res.headers.get("location", "")


def new_browser():
    return TestClient(main.app)


def clients():
    with main.SessionLocal() as db:
        return db.query(models.DBClient).count()


def test_the_master_signs_in_with_their_yahoo_address_whatever_its_capitals(account, yahoo):
    browser = new_browser()
    res = sign_in_with_yahoo(browser, yahoo, account["email"].upper())
    assert where(res).startswith("/next/") or where(res) == "/next/onboard", where(res)
    assert browser.get("/api/client/me").json()["email"] == account["email"]


def test_a_team_member_signs_in_as_themselves_on_the_masters_company(tenant, account, yahoo):
    member, email = team_invite(tenant, role="viewer")
    browser = new_browser()
    assert where(sign_in_with_yahoo(browser, yahoo, email)).startswith("/next/")
    assert browser.get("/api/client/me").json()["email"] == account["email"]
    # still a viewer: reading yes, changing no
    assert browser.post("/api/jobs", json={"name": "Should not be made"}).status_code == 403


def test_staff_sign_in_with_yahoo_by_their_work_email(tenant, yahoo):
    """Yahoo signs staff in by the organisation email HR gave them, never by their personal one."""
    import uuid
    emp = staff(tenant, "staff")
    work = "work-%s@yalavarti.com" % uuid.uuid4().hex[:6]
    assert tenant.put("/api/employees/%d" % emp["id"], json={"org_email": work}).status_code == 200
    browser = new_browser()
    assert "error" in where(sign_in_with_yahoo(browser, yahoo, emp["email"]))      # their personal address: no
    browser = new_browser()
    assert where(sign_in_with_yahoo(browser, yahoo, work)).startswith("/next/")
    assert browser.get("/api/employee/auth/me").status_code == 200
    assert browser.get("/api/client/me").status_code == 401


def test_an_address_nobody_gave_a_login_to_gets_nothing(tenant, yahoo):
    before = clients()
    browser = new_browser()
    res = sign_in_with_yahoo(browser, yahoo, "stranger@yahoo.com")
    assert where(res) == "/next/login?error=yahoo_unknown"
    assert browser.get("/api/client/me").status_code == 401
    assert clients() == before


def test_an_unverified_yahoo_address_is_refused(account, yahoo):
    yahoo["verified"] = False
    browser = new_browser()
    assert where(sign_in_with_yahoo(browser, yahoo, account["email"])) == "/next/login?error=yahoo_unverified"
    assert browser.get("/api/client/me").status_code == 401


def test_a_partner_signs_in_with_yahoo_at_the_portal(tenant, yahoo):
    order, _ = contractor_with_a_certified_bill(tenant)
    import uuid
    email = "babu-%s@sribalaji.in" % uuid.uuid4().hex[:6]
    portal_invite(tenant, "contractor", order["contractor_id"], email)
    browser = new_browser()
    res = sign_in_with_yahoo(browser, yahoo, email.upper(), who="portal")
    assert where(res) == "/next/portal"
    assert browser.get("/api/portal/me").status_code == 200
    assert browser.get("/api/client/me").status_code == 401


def test_the_portal_door_only_opens_for_partners(account, yahoo):
    browser = new_browser()
    res = sign_in_with_yahoo(browser, yahoo, account["email"], who="portal")
    assert where(res) == "/next/portal?error=yahoo_unknown"
    assert browser.get("/api/client/me").status_code == 401


def test_yahoo_unconfigured_says_so(monkeypatch):
    monkeypatch.delenv("YAHOO_CLIENT_ID", raising=False)
    r = new_browser().get("/api/auth/yahoo/start", follow_redirects=False)
    assert where(r) == "/next/login?error=yahoo_unconfigured"


# --- Sign in with Google, retired -------------------------------------------------------------------------------

def test_google_sign_in_is_retired_and_signs_nobody_in(account, google):
    """Even with Google configured and Google vouching for the Master's own address."""
    google["email"] = account["email"]
    browser = new_browser()
    for path in ("/api/auth/google/start", "/api/auth/google/callback"):
        assert where(browser.get(path, follow_redirects=False)) == "/next/login?error=google_retired", path
    assert where(browser.get("/api/auth/google/start", params={"who": "portal"}, follow_redirects=False)) == "/next/portal?error=google_retired"
    assert browser.get("/api/client/me").status_code == 401
    assert browser.get("/api/auth/google/status").json() == {"configured": False}


def test_passwords_carry_on(account):
    with new_browser() as b:
        assert b.post("/api/client/login", json={"email": account["email"], "password": account["password"]}).status_code == 200


def test_connecting_gmail_never_creates_or_switches_an_account(tenant, account, google):
    before = clients()
    stranger = new_browser()
    google["email"], google["refresh"] = "stranger@gmail.com", "rt-stranger"
    res = stranger.get("/api/auth/callback", follow_redirects=False)
    assert where(res) == "/next/login?error=gmail_sign_in_first"
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
    assert where(browser.get("/api/auth/callback", follow_redirects=False)) == "/next/superadmin/login?error=not_admin"
    monkeypatch.setenv("SUPERADMIN_EMAILS", "hello@billing.com")
    browser.get("/api/auth/login", params={"role": "superadmin"}, follow_redirects=False)
    assert where(browser.get("/api/auth/callback", follow_redirects=False)) == "/next/superadmin"


def test_which_gmail_the_company_sends_from_is_not_told_to_strangers():
    assert new_browser().get("/api/gmail/status").status_code == 401


# --- Yahoo: what can go wrong, and the return address ------------------------------------------------------------

def test_yahoo_failures_are_told_apart(yahoo, monkeypatch):
    from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError

    def raising(exc):
        async def exchange(request):
            raise exc
        monkeypatch.setattr(main.oauth.yahoo, "authorize_access_token", exchange)

    b = new_browser()
    assert where(b.get("/api/auth/yahoo/callback?error=access_denied", follow_redirects=False)) == "/next/login?error=yahoo_denied"
    assert where(b.get("/api/auth/yahoo/callback?error=server_error", follow_redirects=False)) == "/next/login?error=yahoo_failed"
    raising(MismatchingStateError())
    assert where(b.get("/api/auth/yahoo/callback?code=x&state=forged", follow_redirects=False)) == "/next/login?error=yahoo_state"
    raising(OAuthError(error="invalid_grant", description="expired"))
    assert where(b.get("/api/auth/yahoo/callback?code=old&state=s", follow_redirects=False)) == "/next/login?error=yahoo_expired"
    raising(RuntimeError("boom"))
    assert where(b.get("/api/auth/yahoo/callback?code=x&state=s", follow_redirects=False)) == "/next/login?error=yahoo_failed"
    assert b.get("/api/client/me").status_code == 401


def test_yahoo_uses_pkce_and_the_return_address_can_be_pinned(yahoo, monkeypatch):
    assert main.oauth.yahoo.client_kwargs.get("code_challenge_method") == "S256"
    sent = {}

    async def redirect(request, redirect_uri, **kw):
        from starlette.responses import RedirectResponse
        sent["uri"] = redirect_uri
        return RedirectResponse("https://api.login.yahoo.com/oauth2/request_auth?fake=1")
    monkeypatch.setattr(main.oauth.yahoo, "authorize_redirect", redirect)
    new_browser().get("/api/auth/yahoo/start", follow_redirects=False)
    assert sent["uri"].endswith("/api/auth/yahoo/callback")
    monkeypatch.setenv("YAHOO_REDIRECT_URI", "https://tunnel.example.com/api/auth/yahoo/callback")
    new_browser().get("/api/auth/yahoo/start", follow_redirects=False)
    assert sent["uri"] == "https://tunnel.example.com/api/auth/yahoo/callback"


# --- Gmail for sending: the Master's alone ---------------------------------------------------------------------

def test_only_the_master_connects_or_disconnects_the_company_gmail(tenant, google):
    from test_team import sign_in_as
    member, email = team_invite(tenant, role="admin")
    with new_browser() as colleague:
        assert sign_in_as(colleague, email).status_code == 200
        google["email"], google["refresh"] = "accounts@gmail.com", "rt-colleague"
        assert where(colleague.get("/api/auth/callback", follow_redirects=False)) == "/next/settings?gmail=master_only"
        assert colleague.post("/api/gmail/disconnect").status_code == 403
        assert colleague.post("/api/gmail/test", json={"to": "someone@yahoo.com"}).status_code == 403
    cid = tenant.get("/api/client/me").json()["id"]
    with main.SessionLocal() as db:
        assert main.get_stored_refresh_token(db, client_id=cid) != "rt-colleague"


def test_the_master_connects_gmail_from_settings_and_sends_a_test_to_a_yahoo_address(tenant, google, monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.email.send_email_background", lambda to, subject, body, sender, *a, **k: sent.append((to, subject, sender)) or (True, "Email sent via Gmail API"))
    assert tenant.post("/api/gmail/test", json={"to": "someone@yahoo.com"}).status_code == 409          # not connected yet
    tenant.get("/api/auth/login", params={"portal": "settings"}, follow_redirects=False)
    google["email"], google["refresh"] = "accounts@gmail.com", "rt-company"
    assert where(tenant.get("/api/auth/callback", follow_redirects=False)) == "/next/settings?gmail=connected"
    assert tenant.post("/api/gmail/test", json={"to": "not-an-address"}).status_code == 400
    r = tenant.post("/api/gmail/test", json={"to": "someone@yahoo.com"})
    assert r.status_code == 200 and sent and sent[-1][0] == "someone@yahoo.com"
    assert "rt-company" not in r.text and "at-secret" not in r.text
    monkeypatch.setattr("app.routers.email.send_email_background", lambda *a, **k: (False, "Gmail API error: invalid_grant token=rt-company"))
    r = tenant.post("/api/gmail/test", json={"to": "someone@yahoo.com"})
    assert r.status_code == 502 and "rt-company" not in r.text                                          # the provider's words stay off the screen
    assert tenant.post("/api/gmail/disconnect").status_code == 200
    assert tenant.post("/api/gmail/test", json={"to": "someone@yahoo.com"}).status_code == 409
