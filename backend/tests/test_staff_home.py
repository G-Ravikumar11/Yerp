"""The site engineer's day: clocked in or not, each site as it stands today,
and - for a supervisor - what is waiting to be signed off."""
from datetime import date, timedelta

from conftest import make_employee

PASSWORD = "Crew1234"


def staff(tenant, browser, role="staff"):
    e = make_employee(tenant, permission_role=role, password=PASSWORD)
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    assert browser.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD}).status_code == 200
    return e


def test_the_day_shows_each_site_and_whether_its_diary_is_written(tenant, portal):
    a = tenant.post("/api/jobs", json={"name": "Site A", "customer_name": "X", "status": "in_progress"}).json()
    tenant.post("/api/jobs", json={"name": "Site B", "customer_name": "X", "status": "in_progress"})
    staff(tenant, portal)
    day = portal.get("/api/employee/today").json()
    names = [s["name"] for s in day["sites"]]
    assert "Site A" in names and "Site B" in names
    assert all(s["diary"] is None for s in day["sites"])
    portal.post("/api/diary", json={"job_id": a["id"], "diary_date": date.today().isoformat(), "labour": [], "plant": []})
    site_a = [s for s in portal.get("/api/employee/today").json()["sites"] if s["name"] == "Site A"][0]
    assert site_a["diary"]["status"] == "DRAFT"


def test_clocking_in_shows_on_the_day(tenant, portal):
    staff(tenant, portal)
    portal.post("/api/employee/attendance/clock-in", json={})
    assert portal.get("/api/employee/today").json()["clock"]["in"]


def test_a_supervisor_sees_the_days_waiting_to_be_signed_off(tenant, portal):
    job = tenant.post("/api/jobs", json={"name": "Site C", "customer_name": "X", "status": "in_progress"}).json()
    tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": (date.today() - timedelta(days=2)).isoformat(),
                                    "labour": [], "plant": []})
    staff(tenant, portal, "supervisor")
    waiting = portal.get("/api/employee/today").json()["waiting"]
    assert any(w["kind"] == "diary" and "Site C" in w["text"] for w in waiting)


def test_plain_staff_are_not_asked_to_sign_off(tenant, portal):
    job = tenant.post("/api/jobs", json={"name": "Site D", "customer_name": "X", "status": "in_progress"}).json()
    tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": (date.today() - timedelta(days=2)).isoformat(),
                                    "labour": [], "plant": []})
    staff(tenant, portal, "staff")
    assert portal.get("/api/employee/today").json()["waiting"] == []


def test_the_day_is_only_for_staff(tenant, client):
    assert client.get("/api/employee/today").status_code == 401
