"""Signing out signs out of everything this browser holds, and every page shows the Y."""
from conftest import make_employee

PASSWORD = "Crew1234"


def staff_signed_in(tenant):
    emp = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    assert tenant.post("/api/employee/auth/login", json={"email": emp["email"], "password": PASSWORD}).status_code == 200
    assert tenant.get("/api/employee/auth/me").status_code == 200


def test_signing_out_as_staff_leaves_nothing_signed_in(tenant):
    staff_signed_in(tenant)
    assert tenant.post("/api/employee/auth/logout").status_code == 200
    assert tenant.get("/api/client/me").status_code == 401
    assert tenant.get("/api/employee/auth/me").status_code == 401


def test_signing_out_as_owner_leaves_nothing_signed_in(tenant):
    assert tenant.get("/api/client/me").status_code == 200
    assert tenant.post("/api/client/logout").status_code == 200
    assert tenant.get("/api/client/me").status_code == 401
    assert tenant.get("/api/employee/auth/me").status_code == 401


def test_the_staff_logout_clears_even_when_the_staff_session_is_gone(tenant):
    assert tenant.post("/api/employee/auth/logout").status_code == 200
    assert tenant.get("/api/client/me").status_code == 401


def test_the_y_icon_is_served_for_every_page(tenant):
    for path, kind in (("/favicon.svg", "svg"), ("/favicon.ico", "icon"), ("/favicon-32.png", "png"), ("/icons/apple-touch-icon.png", "png")):
        res = tenant.get(path)
        assert res.status_code == 200, path
        assert kind in res.headers.get("content-type", "") or kind == "icon", (path, res.headers.get("content-type"))
    for page in ("/login.html", "/employee-login.html", "/portal.html"):
        assert "/favicon.svg" in tenant.get(page).text, page


def test_no_page_prints_leftover_icon_markup(tenant):
    """The old inline icons were once cut in half, leaving a lightning bolt and a stray '">' on the page."""
    import glob
    import os
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "*.html")
    for path in glob.glob(here):
        body = open(path, encoding="utf8").read()
        assert "</text></svg>" not in body, path
        assert "⚡" not in body.split("<body", 1)[-1], path
