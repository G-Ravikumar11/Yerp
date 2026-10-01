"""The member of staff's own portal: who they are, who they work with, what they have been set,
and what they have been told."""
from conftest import make_employee
from test_departments_and_approvals import PASSWORD, sign_in


def staff_in(tenant, department_id, **over):
    # make_employee leaves people "onboarding", which is how the owner's own additions arrive.
    return make_employee(tenant, permission_role="staff", password=PASSWORD, department_id=department_id, **over)


def test_the_profile_and_the_team_include_colleagues_still_onboarding(tenant, portal):
    dept = tenant.post("/api/departments", json={"name": "Survey", "description": "", "color": "#0f766e", "icon": "compass"}).json()
    boss = staff_in(tenant, dept["id"], first_name="Bela")
    me = staff_in(tenant, dept["id"], first_name="Mina", reports_to=boss["id"])
    mate = staff_in(tenant, dept["id"], first_name="Omar")
    sign_in(portal, me)
    profile = portal.get("/api/employee/profile").json()
    assert profile["department"] == "Survey" and boss["last_name"] in profile["manager"]
    assert {t["name"] for t in profile["team"]} == {"%s %s" % (boss["first_name"], boss["last_name"]), "%s %s" % (mate["first_name"], mate["last_name"])}
    presence = portal.get("/api/employee/team-presence").json()
    assert len(presence) == 3 and all(t["name"] for t in presence)


def test_a_goal_from_hr_reaches_the_person_and_they_can_move_it_on(tenant, portal):
    me = staff_in(tenant, None)
    made = tenant.post("/api/employees/%d/goals" % me["id"], json={"title": "Survey 10 sites", "target_value": 10, "current_value": 2, "unit": "sites", "priority": "high"})
    assert made.status_code == 200, made.text
    sign_in(portal, me)
    goals = portal.get("/api/employee/goals").json()
    assert [g["title"] for g in goals] == ["Survey 10 sites"] and goals[0]["current_value"] == 2
    notes = portal.get("/api/employee/notifications").json()
    assert notes["unread_count"] >= 1
    assert portal.post("/api/employee/goals/%d/update" % goals[0]["id"], json={"current_value": 10}).status_code == 200
    assert portal.get("/api/employee/goals").json()[0]["status"] == "completed"
    assert portal.post("/api/employee/notifications/read-all", json={}).status_code == 200
    assert portal.get("/api/employee/notifications").json()["unread_count"] == 0


def test_the_week_has_seven_days_and_marks_today(tenant, portal):
    me = staff_in(tenant, None)
    sign_in(portal, me)
    week = portal.get("/api/employee/weekly-chart").json()
    assert [d["day"] for d in week] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert sum(1 for d in week if d["is_today"]) == 1
