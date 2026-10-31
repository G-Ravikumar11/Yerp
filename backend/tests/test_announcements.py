"""The Feed's announcements: HR and the Master write them, everybody in the company reads them."""
from datetime import date, timedelta

import pytest

from app import db as database
from app import models
from conftest import make_employee


def staff(tenant, **extra):
    emp = make_employee(tenant, password="EmpPass123", **extra)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(portal, emp):
    res = portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert res.status_code == 200, res.text


def post(c, title="Site closed on Saturday", **kw):
    return c.post("/api/announcements", json={"title": title, **kw})


def titles(c):
    return [a["title"] for a in c.get("/api/announcements").json()["announcements"]]


def test_the_master_posts_and_it_appears_on_the_feed(tenant):
    res = post(tenant, body="Heavy rain: the Gachibowli site is shut.\nBack on Monday.", category="site")
    assert res.status_code == 200, res.text
    got = tenant.get("/api/announcements").json()
    assert got["can_post"] is True and got["categories"] == ["general", "site", "holiday", "important"]
    a = got["announcements"][0]
    assert (a["title"], a["category"], a["pinned"], a["expired"]) == ("Site closed on Saturday", "site", False, False)
    assert a["body"] == "Heavy rain: the Gachibowli site is shut.\nBack on Monday.", "line breaks are kept"
    assert a["posted_by"] and a["created_at"]


def test_hr_can_post_and_everybody_else_can_only_read(tenant, portal):
    hr, plain = staff(tenant, permission_role="hr"), staff(tenant)
    post(tenant, "Holiday on Friday", category="holiday")
    sign_in(portal, plain)
    seen = portal.get("/api/announcements").json()
    assert seen["can_post"] is False and [a["title"] for a in seen["announcements"]] == ["Holiday on Friday"]
    assert seen["announcements"][0]["can_edit"] is False
    assert post(portal, "Free pizza").status_code in (401, 403)
    sign_in(portal, hr)
    assert portal.get("/api/announcements").json()["can_post"] is True
    res = post(portal, "New safety rules", category="important")
    assert res.status_code == 200, res.text
    assert res.json()["posted_by"].startswith("Test Person")


def test_somebody_without_hr_cannot_change_pin_or_remove_one(tenant, portal):
    made = post(tenant).json()
    plain = staff(tenant)
    sign_in(portal, plain)
    assert portal.put("/api/announcements/%d" % made["id"], json={"title": "Mine now"}).status_code in (401, 403)
    assert portal.post("/api/announcements/%d/pin" % made["id"], json={}).status_code in (401, 403)
    assert portal.delete("/api/announcements/%d" % made["id"]).status_code in (401, 403)
    assert titles(tenant) == ["Site closed on Saturday"]


def test_not_signed_in_sees_nothing(client):
    client.post("/api/client/logout")
    assert client.get("/api/announcements").status_code == 401


@pytest.mark.parametrize("body,why", [
    ({"title": "   "}, "no title"),
    ({"title": "x" * 121}, "title too long"),
    ({"title": "Ok", "body": "y" * 2001}, "message too long"),
    ({"title": "Ok", "category": "gossip"}, "unknown kind"),
    ({"title": "Ok", "expires_on": "next week"}, "not a date"),
])
def test_a_bad_announcement_is_refused(tenant, body, why):
    assert tenant.post("/api/announcements", json=body).status_code == 400, why
    assert titles(tenant) == []


def test_pinned_first_then_newest(tenant):
    post(tenant, "Old news")
    post(tenant, "Fresh news")
    post(tenant, "Always on top", pinned=True)
    assert titles(tenant) == ["Always on top", "Fresh news", "Old news"]


def test_one_past_its_last_day_is_hidden_from_staff_but_marked_for_hr(tenant, portal):
    yesterday, tomorrow = (date.today() - timedelta(days=1)).isoformat(), (date.today() + timedelta(days=1)).isoformat()
    post(tenant, "Diwali holiday notice", expires_on=yesterday)
    post(tenant, "Safety week", expires_on=tomorrow)
    hr = {a["title"]: a["expired"] for a in tenant.get("/api/announcements").json()["announcements"]}
    assert hr == {"Diwali holiday notice": True, "Safety week": False}
    sign_in(portal, staff(tenant))
    assert [a["title"] for a in portal.get("/api/announcements").json()["announcements"]] == ["Safety week"]


def test_hr_edits_pins_and_removes(tenant):
    a = post(tenant, "Draft title", category="general").json()
    res = tenant.put("/api/announcements/%d" % a["id"], json={"title": "Final title", "body": "Details", "category": "important", "pinned": True})
    assert res.status_code == 200 and res.json()["title"] == "Final title" and res.json()["updated_at"]
    assert tenant.post("/api/announcements/%d/pin" % a["id"], json={"pinned": False}).json()["pinned"] is False
    assert tenant.post("/api/announcements/%d/pin" % a["id"], json={}).json()["pinned"] is True        # no answer toggles
    assert tenant.delete("/api/announcements/%d" % a["id"]).status_code == 200
    assert titles(tenant) == []
    assert tenant.delete("/api/announcements/%d" % a["id"]).status_code == 404


def test_each_company_has_its_own_feed(tenant, second_tenant):
    mine = post(tenant, "Ours").json()
    assert titles(second_tenant) == []
    assert second_tenant.delete("/api/announcements/%d" % mine["id"]).status_code == 404
    assert second_tenant.put("/api/announcements/%d" % mine["id"], json={"title": "Theirs"}).status_code == 404
    assert titles(tenant) == ["Ours"]


def notices_for(emp):
    with database.SessionLocal() as s:
        return [n.title for n in s.query(models.DBNotification).filter(models.DBNotification.employee_id == emp["id"])]


def test_employees_are_told_unless_the_post_says_not_to(tenant):
    a, b = staff(tenant), staff(tenant)
    gone = staff(tenant)
    tenant.put("/api/employees/%d" % gone["id"], json={"status": "terminated"})
    res = post(tenant, "Pay day moved", body="Salaries on the 3rd.")
    assert res.json()["told"] >= 2
    assert "Announcement: Pay day moved" in notices_for(a) and "Announcement: Pay day moved" in notices_for(b)
    assert notices_for(gone) == [], "somebody who has left is not told"
    quiet = post(tenant, "Minor change", notify=False).json()
    assert quiet["told"] == 0 and "Announcement: Minor change" not in notices_for(a)


def test_what_hr_does_is_in_the_audit_log(tenant):
    a = post(tenant, "Audited").json()
    tenant.put("/api/announcements/%d" % a["id"], json={"title": "Audited again"})
    tenant.delete("/api/announcements/%d" % a["id"])
    with database.SessionLocal() as s:
        actions = [r.action for r in s.query(models.DBAuditLog).filter(models.DBAuditLog.entity_type == "announcement",
                                                                         models.DBAuditLog.entity_id == a["id"]).order_by(models.DBAuditLog.id)]
    assert actions == ["announcement_posted", "announcement_changed", "announcement_removed"]
