"""The people on site can record the site; supervisors sign it off; the money
is for those who hold the money rights."""
from conftest import make_employee

PASSWORD = "Crew1234"


def signed_in(tenant, browser, role):
    e = make_employee(tenant, permission_role=role, password=PASSWORD)
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    res = browser.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text
    return e


def site(tenant):
    return tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec"}).json()


def diary(browser, job, day="2026-09-20"):
    return browser.post("/api/diary", json={"job_id": job["id"], "diary_date": day, "work_done": "Raft shuttering",
                                            "labour": [], "plant": []})


def test_a_site_engineer_records_the_site_but_does_not_sign_it_off(tenant, portal):
    job = site(tenant)
    signed_in(tenant, portal, "staff")
    d = diary(portal, job)
    assert d.status_code == 200, d.text
    assert portal.post("/api/safety/incidents", json={"job_id": job["id"], "kind": "Near miss",
                                                      "description": "Loose clamp"}).status_code == 200
    up = portal.post("/api/files", data={"attached_type": "job", "attached_id": str(job["id"])},
                     files={"file": ("site.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")})
    assert up.status_code == 200, up.text
    off = portal.post("/api/diary/%d/submit" % d.json()["diary"]["id"])
    assert off.status_code == 403 and "Sign off site work" in off.json()["detail"]


def test_a_supervisor_signs_the_day_off(tenant, portal):
    job = site(tenant)
    signed_in(tenant, portal, "supervisor")
    d = diary(portal, job).json()["diary"]
    assert portal.post("/api/diary/%d/submit" % d["id"]).status_code == 200


def test_site_staff_cannot_read_the_money(tenant, portal):
    signed_in(tenant, portal, "supervisor")
    for path in ("/api/money/receivables", "/api/money/payables", "/api/ledger/parties", "/api/bank-accounts",
                 "/api/gst/outward", "/api/fixed-assets", "/api/registers/tds", "/api/jobs-pnl", "/api/retention"):
        assert portal.get(path).status_code == 403, path


def test_a_manager_reads_the_money(tenant, portal):
    signed_in(tenant, portal, "manager")
    for path in ("/api/money/receivables", "/api/ledger/parties", "/api/gst/outward", "/api/jobs-pnl"):
        assert portal.get(path).status_code == 200, path


def test_staff_get_their_own_projects_not_the_contract_list(tenant, portal):
    site(tenant)
    signed_in(tenant, portal, "staff")
    assert portal.get("/api/jobs").status_code in (401, 403)
    assert portal.get("/api/employee/jobs").status_code == 200


def test_the_new_rights_are_in_the_roles():
    import main
    assert "site.record" in main.ROLE_PERMISSIONS["staff"]
    assert {"site.record", "site.signoff"} <= main.ROLE_PERMISSIONS["supervisor"]
    assert {"site.record", "site.signoff"} <= main.ROLE_PERMISSIONS["manager"]
    assert "site.signoff" not in main.ROLE_PERMISSIONS["staff"]
