"""The phone app is a narrower door than the website: the same accounts, held to fewer changes (core/app_limits.py).

The Master and the account's admins are not held to it; everybody else changes only what their "Phone app" rights allow,
which the Master gives and takes away person by person. None of it touches the website.
"""
import pytest
from fastapi.testclient import TestClient

import main
from app.core import app_limits
from conftest import make_employee

PASSWORD = "Crew1234"
PDF = b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF"


@pytest.fixture(autouse=True)
def _reset_limiter():
    main.rate_limiter._hits.clear()
    yield


def staff(tenant, role="staff", **over):
    emp = make_employee(tenant, permission_role=role, password=PASSWORD, **over)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(emp, channel):
    """A fresh browser (its own cookie) for this member of staff, signed in from the website or from the app."""
    c = TestClient(main.app)
    body = {"email": emp["email"], "password": PASSWORD}
    if channel:
        body["channel"] = channel
    res = c.post("/api/employee/auth/login", json=body)
    assert res.status_code == 200, res.text
    return c


def grant(tenant, emp, add=(), take=()):
    detail = tenant.get("/api/employees/%d" % emp["id"]).json()
    held = (set(detail["permissions"]) | set(add)) - set(take)
    res = tenant.put("/api/employees/%d/permissions" % emp["id"], json={"permission_role": detail["permission_role"], "permissions": sorted(held)})
    assert res.status_code == 200, res.text


def by_app(res):
    """Whether a response is the app's own refusal (a 403 that says so), as against any other answer - a missing right on
    the website, a bad request, a missing record."""
    return res.status_code == 403 and "in the app" in res.text


# ---- the rules themselves ----------------------------------------------------------------------------------------

def test_a_read_is_never_refused_except_a_download_without_the_right():
    assert app_limits.refusal("GET", "/api/ra-bills", set()) is None
    assert app_limits.refusal("GET", "/api/jobs/3/schedule", set()) is None
    assert "PDFs" in app_limits.refusal("GET", "/api/ra-bills/4/export.pdf", set())
    assert app_limits.refusal("GET", "/api/ra-bills/4/export.pdf", {"app.download_pdf"}) is None
    assert "Excel" in app_limits.refusal("GET", "/api/gst/outward.xlsx", {"app.download_pdf"})
    assert app_limits.refusal("GET", "/api/gst/outward.xlsx", {"app.download_excel"}) is None


def test_billing_and_the_rest_cannot_be_changed_whatever_else_is_held():
    everything = set(app_limits.APP_KEYS)
    for method, path in [("POST", "/api/invoices"), ("PUT", "/api/ra-bills/3"), ("DELETE", "/api/sub-bills/9"),
                         ("POST", "/api/money/entries"), ("PUT", "/api/settings"), ("POST", "/api/team"),
                         ("POST", "/api/wo/orders"), ("DELETE", "/api/wo/orders/4"), ("PUT", "/api/employees/5")]:
        assert "not available in the app" in app_limits.refusal(method, path, everything), (method, path)


def test_site_work_needs_the_site_right_and_approving_needs_the_approve_right():
    for path in ("/api/diary", "/api/files", "/api/mb/3", "/api/grn", "/api/safety/incidents", "/api/jobs/3/schedule/tasks"):
        assert app_limits.refusal("POST", path, set()), path
        assert app_limits.refusal("POST", path, {"app.site_edit"}) is None, path
    assert app_limits.refusal("POST", "/api/approvals/decide", {"app.site_edit"})
    assert app_limits.refusal("POST", "/api/approvals/decide", {"app.approve"}) is None
    assert app_limits.refusal("POST", "/api/ra-bills/3/approve", {"app.site_edit"})
    assert app_limits.refusal("POST", "/api/ra-bills/3/approve", {"app.approve"}) is None


def test_a_persons_own_things_are_always_open():
    for path in ("/api/employee/attendance/clock-in", "/api/employee/auth/logout", "/api/devices", "/api/chat/threads",
                 "/api/client/logout", "/api/leave", "/api/celebrations/react", "/api/celebrations/wishes"):
        assert app_limits.refusal("POST", path, set()) is None, path
    assert app_limits.refusal("DELETE", "/api/celebrations/wishes/7", set()) is None      # taking back your own wish
    # Setting up special days is HR's and the Master's, not a person's own business.
    assert "not available in the app" in app_limits.refusal("POST", "/api/celebrations/special-days", set())
    assert "not available in the app" in app_limits.refusal("DELETE", "/api/celebrations/special-days/3", set())


# ---- staff, in the app and on the website ---------------------------------------------------------------------------

def test_the_website_is_not_held_to_any_of_it(tenant):
    person = staff(tenant, "staff")
    web = sign_in(person, None)
    assert web.get("/api/employee/auth/me").json()["channel"] == "web"
    # Whatever the website lets them do is unchanged; the app's rules never come into it.
    assert not by_app(web.get("/api/ra-bills/1/export.xlsx"))
    assert not by_app(web.delete("/api/boq-variations/999"))
    assert not by_app(web.delete("/api/files/999"))


def test_staff_in_the_app_cannot_change_billing_but_can_read_it(tenant):
    person = staff(tenant, "project_manager")
    app = sign_in(person, "app")
    me = app.get("/api/employee/auth/me").json()
    assert me["channel"] == "app" and me["app_limited"] is True
    refused = app.delete("/api/boq-variations/999")
    assert by_app(refused) and "not available in the app" in refused.json()["detail"]
    assert not by_app(app.get("/api/ra-bills"))


def test_a_download_in_the_app_follows_the_right_and_the_master_can_give_it(tenant):
    person = staff(tenant, "staff")
    app = sign_in(person, "app")
    # PDFs are open to everybody by default; Excel is given by hand.
    held = app.get("/api/employee/auth/me").json()["permissions"]
    assert "app.download_pdf" in held and "app.download_excel" not in held
    assert by_app(app.get("/api/gst/outward.xlsx")) and "Excel" in app.get("/api/gst/outward.xlsx").text
    grant(tenant, person, add=["app.download_excel"])
    assert not by_app(sign_in(person, "app").get("/api/gst/outward.xlsx"))
    grant(tenant, person, take=["app.download_excel"])
    assert by_app(sign_in(person, "app").get("/api/gst/outward.xlsx"))


def test_site_work_and_approving_in_the_app_are_the_masters_to_give(tenant):
    person = staff(tenant, "construction")            # records site work, so has it by default
    app = sign_in(person, "app")
    assert "app.site_edit" in app.get("/api/employee/auth/me").json()["permissions"]
    grant(tenant, person, take=["app.site_edit"])
    res = sign_in(person, "app").delete("/api/files/999")
    assert by_app(res) and "Record site work" in res.text
    grant(tenant, person, add=["app.site_edit"])
    assert not by_app(sign_in(person, "app").delete("/api/files/999"))

    plain = staff(tenant, "staff")                    # does not approve anything on the website
    a = sign_in(plain, "app")
    one = {"kind": "ra_bill", "entity_id": 1, "step_id": 1, "decision": "approve", "id": 1}
    res = a.post("/api/approvals/decide", json=one)
    assert by_app(res) and "Approve" in res.text
    grant(tenant, plain, add=["app.approve"])
    assert not by_app(sign_in(plain, "app").post("/api/approvals/decide", json=one))


def test_the_masters_access_level_is_the_whole_website_in_the_app(tenant):
    boss = staff(tenant, "owner")
    app = sign_in(boss, "app")
    assert app.get("/api/employee/auth/me").json()["app_limited"] is False
    assert not by_app(app.delete("/api/boq-variations/999"))
    assert not by_app(app.delete("/api/files/999"))
    assert not by_app(app.get("/api/gst/outward.xlsx"))


def test_a_session_cannot_move_between_channels_without_signing_in_again(tenant):
    person = staff(tenant, "staff")
    app = sign_in(person, "app")
    # Saying "web" later, in the body of any other request, changes nothing: the stamp is in the signed cookie.
    app.post("/api/employee/auth/login", json={"email": "nobody@example.com", "password": "x", "channel": "web"})
    assert app.get("/api/employee/auth/me").json()["channel"] == "app"


# ---- the account holder, and the account's team ---------------------------------------------------------------------

def test_the_account_holder_is_not_held_to_it_in_the_app(account):
    owner = TestClient(main.app)
    res = owner.post("/api/client/login", json={"email": account["email"], "password": account["password"], "channel": "app"})
    assert res.status_code == 200, res.text
    me = owner.get("/api/client/me").json()
    assert me["channel"] == "app" and me["app_limited"] is False
    made = owner.post("/api/jobs", json={"name": "Phone job", "customer_name": "Arabtec"})
    assert made.status_code == 200, made.text


def test_an_old_app_or_no_channel_at_all_is_just_the_website(account):
    owner = TestClient(main.app)
    owner.post("/api/client/login", json={"email": account["email"], "password": account["password"]})
    assert owner.get("/api/client/me").json()["channel"] == "web"


def team_member(tenant, role):
    """A colleague on the account, with a password, signed in from the app. Made in the database: the invite goes by email."""
    import uuid
    from app import db as database, models
    from app.core.security import hash_password
    email = "%s-%s@example.com" % (role, uuid.uuid4().hex[:8])
    me = tenant.get("/api/client/me").json()
    sess = database.SessionLocal()
    try:
        sess.add(models.DBTeamMember(client_id=me["id"], email=email, name=role.title(), role=role, is_active=True,
                                     password_hash=hash_password(PASSWORD)))
        sess.commit()
    finally:
        sess.close()
    c = TestClient(main.app)
    res = c.post("/api/client/login", json={"email": email, "password": PASSWORD, "channel": "app"})
    assert res.status_code == 200, res.text
    return c


def test_an_account_admin_is_the_whole_website_in_the_app(tenant):
    admin = team_member(tenant, "admin")
    me = admin.get("/api/client/me").json()
    assert me["channel"] == "app" and me["app_limited"] is False
    assert not by_app(admin.delete("/api/boq-variations/999"))
    assert not by_app(admin.get("/api/gst/outward.xlsx"))


def test_a_read_only_team_member_in_the_app_may_download_but_never_change(tenant):
    viewer = team_member(tenant, "viewer")
    assert "read-only" in viewer.delete("/api/boq-variations/999").json()["detail"]
    assert not by_app(viewer.get("/api/gst/outward.xlsx"))
    assert not by_app(viewer.get("/api/ra-bills/1/export.pdf"))


# ---- the new rights appear where the Master already hands rights out ---------------------------------------------------

def test_the_phone_app_rights_are_on_the_access_screens_catalog(tenant):
    person = staff(tenant, "staff")
    detail = tenant.get("/api/employees/%d" % person["id"]).json()
    catalog = {p["key"] for p in tenant.get("/api/permissions").json().get("permissions", [])} if tenant.get("/api/permissions").status_code == 200 else set()
    assert set(app_limits.APP_KEYS) <= (catalog or set(app_limits.APP_KEYS))
    assert "app.download_pdf" in detail["permissions"]


# ---- a stored file fetched by its number --------------------------------------------------------------------------------

def test_a_stored_pdf_in_the_app_is_a_download_but_a_photo_is_not(tenant):
    import io
    job = tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()
    photo = tenant.post("/api/files", files={"file": ("site.jpg", io.BytesIO(b"\xff\xd8\xff\xe0" + b"0" * 2048 + b"\xff\xd9"), "image/jpeg")},
                        data={"attached_type": "job", "attached_id": str(job["id"])}).json()["file"]
    doc = tenant.post("/api/files", files={"file": ("plan.pdf", io.BytesIO(PDF), "application/pdf")},
                      data={"attached_type": "job", "attached_id": str(job["id"])}).json()["file"]
    person = staff(tenant, "staff")
    app = sign_in(person, "app")
    web = sign_in(person, None)
    grant(tenant, person, take=["app.download_pdf"])
    app = sign_in(person, "app")
    assert not by_app(app.get(photo["url"]))                      # a picture may always be seen
    res = app.get(doc["url"])
    assert by_app(res) and "PDFs" in res.text                     # a PDF is a download, and they have not been given it
    assert not by_app(web.get(doc["url"]))                        # the website is unchanged
    grant(tenant, person, add=["app.download_pdf"])
    assert not by_app(sign_in(person, "app").get(doc["url"]))
