"""A member of staff put on particular sites works on those sites only.

HR assigns people to projects; the Projects portal's screens used to look a record up by its number and the company, so a person
assigned to one project could read - workers' Aadhaar and PAN papers included - and change another's by asking for it. Now every
lookup of a project, or of a record that belongs to one, is narrowed to the person's sites (core/site_scope.py). Nobody who is
not limited notices: the owner, head office and the company-wide rights see every project, and a person assigned to nothing
sees every project (HR's "none ticked means every site").
"""
import uuid

from conftest import make_employee

PASSWORD = "Crew1234"
INCIDENT = {"kind": "Near miss", "happened_on": "2026-09-20", "happened_at": "10:00", "location": "Block A", "description": "Slipped",
            "injured_name": "", "injury": "", "treatment": "", "lost_days": 0, "immediate_action": "Cordoned off"}


def two_projects(tenant):
    a = tenant.post("/api/jobs", json={"name": "Alpha Towers", "customer_name": "A Ltd"}).json()
    b = tenant.post("/api/jobs", json={"name": "Bravo Plaza", "customer_name": "B Ltd"}).json()
    return a, b


def staff_on(tenant, browser, sites, role="staff"):
    """A signed-in member of staff assigned to `sites` (project ids; [] means assigned to nothing)."""
    e = make_employee(tenant, permission_role=role, password=PASSWORD, site_ids=sites, emergency_contact="Asha", emergency_phone="9999999999")
    tenant.put("/api/employees/%d" % e["id"], json={"status": "active"})
    res = browser.post("/api/employee/auth/login", json={"email": e["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text
    return e


def seed(tenant, job, name):
    """A diary, a worker, an incident and an activity on `job`, made by the owner."""
    tenant.post("/api/diary", json={"job_id": job["id"], "diary_date": "2026-09-20", "weather": "Clear", "working_hours": 8, "work_done": name})
    w = tenant.post("/api/workers", json={"job_id": job["id"], "name": name, "age": 30, "address": "Hyderabad", "trade": "Mason", "screened_on": "2026-09-20"})
    assert w.status_code == 200, w.text
    assert tenant.post("/api/safety/incidents", json={"job_id": job["id"], **INCIDENT}).status_code == 200
    act = tenant.post("/api/jobs/%d/schedule/activities" % job["id"], json={"name": name + " slab", "planned_start": "2026-10-01", "planned_finish": "2026-10-09"})
    assert act.status_code == 200, act.text
    return w.json()["worker"]["id"], act.json()["schedule"]["activities"][0]["id"]


def test_staff_on_one_project_see_and_change_only_that_project(tenant, portal):
    a, b = two_projects(tenant)
    wa, act_a = seed(tenant, a, "Alpha")
    wb, act_b = seed(tenant, b, "Bravo")
    staff_on(tenant, portal, [a["id"]])

    # What is theirs works as before ...
    assert [d["work_done"] for d in portal.get("/api/diary?job_id=%d" % a["id"]).json()["diaries"]] == ["Alpha"]
    assert portal.get("/api/jobs/%d/schedule" % a["id"]).status_code == 200
    assert portal.get("/api/workers/%d/document.pdf" % wa).status_code == 200
    assert portal.post("/api/schedule/activities/%d/progress" % act_a, json={"percent": 40}).status_code == 200
    assert portal.post("/api/safety/incidents", json={"job_id": a["id"], **INCIDENT}).status_code == 200

    # ... and the other project is not found: lists leave it out, and asking for it by number gets a 404.
    assert portal.get("/api/diary?job_id=%d" % b["id"]).json()["diaries"] == []
    assert [d["work_done"] for d in portal.get("/api/diary").json()["diaries"]] == ["Alpha"]
    assert [w["name"] for w in portal.get("/api/workers").json()["workers"]] == ["Alpha"]
    assert {i["job_id"] for i in portal.get("/api/safety").json()["incidents"]} == {a["id"]}      # theirs, seeded and reported just now
    assert portal.get("/api/jobs/%d/schedule" % b["id"]).status_code == 403          # "you are not assigned to that site"
    assert portal.get("/api/jobs/%d/drawings" % b["id"]).status_code == 403
    assert portal.get("/api/workers/%d/document.pdf" % wb).status_code == 404            # a stranger's papers are not served
    assert portal.post("/api/schedule/activities/%d/progress" % act_b, json={"percent": 99}).status_code == 404
    assert portal.post("/api/diary", json={"job_id": b["id"], "diary_date": "2026-09-21", "weather": "Clear", "working_hours": 8}).status_code == 404
    assert portal.post("/api/workers", json={"job_id": b["id"], "name": "Intruder", "age": 30, "address": "x", "trade": "Mason", "screened_on": "2026-09-20"}).status_code == 403
    assert portal.post("/api/safety/incidents", json={"job_id": b["id"], **INCIDENT}).status_code == 403
    assert portal.post("/api/safety/talks", json={"job_id": b["id"], "topic": "PPE", "attendees": 4, "attendee_names": ""}).status_code == 403
    # Nothing of Bravo's was touched.
    assert tenant.get("/api/jobs/%d/schedule" % b["id"]).json()["activities"][0]["actual_percent"] == 0


def test_staff_assigned_to_nothing_still_see_every_project(tenant, portal):
    a, b = two_projects(tenant)
    seed(tenant, a, "Alpha")
    seed(tenant, b, "Bravo")
    staff_on(tenant, portal, [])
    assert len(portal.get("/api/diary").json()["diaries"]) == 2
    assert portal.get("/api/jobs/%d/schedule" % b["id"]).status_code == 200


def test_company_wide_rights_are_not_limited_by_sites(tenant, portal):
    """A project manager (reports, billing, work orders) works across projects even when put on one."""
    a, b = two_projects(tenant)
    seed(tenant, a, "Alpha")
    seed(tenant, b, "Bravo")
    staff_on(tenant, portal, [a["id"]], role="project_manager")
    assert len(portal.get("/api/diary").json()["diaries"]) == 2
    assert portal.get("/api/jobs/%d/schedule" % b["id"]).status_code == 200


def test_the_owner_and_a_colleague_see_every_project(tenant):
    a, b = two_projects(tenant)
    seed(tenant, a, "Alpha")
    seed(tenant, b, "Bravo")
    assert len(tenant.get("/api/diary").json()["diaries"]) == 2
    assert len(tenant.get("/api/workers").json()["workers"]) == 2


def test_a_change_of_sites_takes_effect_at_once(tenant, portal):
    a, b = two_projects(tenant)
    seed(tenant, b, "Bravo")
    e = staff_on(tenant, portal, [a["id"]])
    assert portal.get("/api/jobs/%d/schedule" % b["id"]).status_code == 403
    res = tenant.put("/api/employees/%d/permissions" % e["id"], json={"permission_role": "staff", "site_ids": [a["id"], b["id"]]})
    assert res.status_code == 200, res.text
    assert portal.get("/api/jobs/%d/schedule" % b["id"]).status_code == 200
