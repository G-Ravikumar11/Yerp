"""Birthdays and special days: everybody sees them, reacts with an emoji and writes a message, is told on the day, and only
HR (and the Master) adds days of their own."""
from datetime import date, datetime

from conftest import as_owner, make_employee

from app import models
from app.core.scheduler import run_due_jobs
from app.db import SessionLocal

TODAY = date.today()
BORN = "%d-%02d-%02d" % (TODAY.year - 30, TODAY.month, TODAY.day if (TODAY.month, TODAY.day) != (2, 29) else 28)


def staff(tenant, portal, **extra):
    """An active employee signed in on the second browser."""
    emp = make_employee(tenant, password="EmpPass123", **extra)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(portal, emp):
    res = portal.post("/api/employee/auth/login", json={"email": emp["email"], "password": "EmpPass123"})
    assert res.status_code == 200, res.text
    return portal


def feed(c):
    res = c.get("/api/celebrations")
    assert res.status_code == 200, res.text
    return res.json()


def birthday_of(c, emp):
    return next(x for x in feed(c)["today"] if x.get("employee_id") == emp["id"])


# --- the birthday shows to everybody ----------------------------------------

def test_a_birthday_today_is_on_everybodys_feed_without_the_year(tenant, portal):
    star = make_employee(tenant, date_of_birth=BORN)
    other = staff(tenant, portal)
    sign_in(portal, other)
    b = birthday_of(portal, star)
    assert b["kind"] == "birthday" and b["key"].startswith("birthday:%d:" % star["id"])
    assert BORN not in str(b) and str(TODAY.year - 30) not in str(b)
    assert birthday_of(tenant, star)["key"] == b["key"]            # the Master sees it as well


def test_a_birthday_on_another_day_is_upcoming_not_today(tenant):
    other_day = date(2000, 1, 1) if (TODAY.month, TODAY.day) != (1, 1) else date(2000, 1, 2)
    soon = make_employee(tenant, date_of_birth=other_day.isoformat())
    assert not [x for x in feed(tenant)["today"] if x.get("employee_id") == soon["id"]]


def test_a_date_of_birth_must_be_a_real_day_in_the_past(tenant):
    assert tenant.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": "dob1@example.com",
                                               "date_of_birth": "next week"}).status_code == 400
    assert tenant.post("/api/employees", json={"first_name": "A", "last_name": "B", "email": "dob2@example.com",
                                               "date_of_birth": "2999-01-01"}).status_code == 400


def test_somebody_who_left_has_no_birthday(tenant):
    gone = make_employee(tenant, date_of_birth=BORN)
    tenant.put("/api/employees/%d" % gone["id"], json={"status": "terminated"})
    assert not [x for x in feed(tenant)["today"] if x.get("employee_id") == gone["id"]]


# --- reactions and messages --------------------------------------------------

def test_a_colleague_reacts_and_taking_it_back(tenant, portal):
    star = make_employee(tenant, date_of_birth=BORN)
    fan = staff(tenant, portal)
    sign_in(portal, fan)
    key = birthday_of(portal, star)["key"]
    assert portal.post("/api/celebrations/react", json={"celebration": key, "emoji": "🎉"}).json() == {"reacted": True}
    r = birthday_of(portal, star)["reactions"]
    assert r == [{"emoji": "🎉", "count": 1, "mine": True, "names": ["%s %s" % (fan["first_name"], fan["last_name"])]}]
    assert portal.post("/api/celebrations/react", json={"celebration": key, "emoji": "🎉"}).json() == {"reacted": False}
    assert birthday_of(portal, star)["reactions"] == []


def test_only_the_offered_emoji_are_accepted(tenant, portal):
    star = make_employee(tenant, date_of_birth=BORN)
    key = birthday_of(tenant, star)["key"]
    assert tenant.post("/api/celebrations/react", json={"celebration": key, "emoji": "<script>"}).status_code == 400


def test_a_message_reaches_the_birthday_person_and_can_be_taken_down(tenant, portal):
    star = staff(tenant, portal, date_of_birth=BORN)
    fan = staff(tenant, portal)
    sign_in(portal, fan)
    key = birthday_of(portal, star)["key"]
    made = portal.post("/api/celebrations/wishes", json={"celebration": key, "message": "  Many happy returns!  "})
    assert made.status_code == 200, made.text
    wish = birthday_of(portal, star)["wishes"][0]
    assert wish["message"] == "Many happy returns!" and wish["mine"] and wish["can_delete"]
    assert portal.delete("/api/celebrations/wishes/%d" % wish["id"]).status_code == 200
    assert birthday_of(portal, star)["wishes"] == []


def test_a_message_needs_words_and_a_sane_length(tenant):
    star = make_employee(tenant, date_of_birth=BORN)
    key = birthday_of(tenant, star)["key"]
    assert tenant.post("/api/celebrations/wishes", json={"celebration": key, "message": "   "}).status_code == 400
    assert tenant.post("/api/celebrations/wishes", json={"celebration": key, "message": "x" * 301}).status_code == 400


def test_nobody_removes_somebody_elses_message_unless_they_are_hr_or_the_master(tenant, portal):
    star = make_employee(tenant, date_of_birth=BORN)
    a, b = staff(tenant, portal), staff(tenant, portal)
    sign_in(portal, a)
    key = birthday_of(portal, star)["key"]
    wid = portal.post("/api/celebrations/wishes", json={"celebration": key, "message": "Hello"}).json()["id"]
    sign_in(portal, b)
    assert portal.delete("/api/celebrations/wishes/%d" % wid).status_code == 403
    assert tenant.delete("/api/celebrations/wishes/%d" % wid).status_code == 200      # the Master may


def test_one_company_cannot_react_to_anothers_celebration(tenant, second_tenant):
    star = make_employee(tenant, date_of_birth=BORN)
    key = birthday_of(tenant, star)["key"]
    assert second_tenant.post("/api/celebrations/react", json={"celebration": key, "emoji": "🎉"}).status_code == 404
    assert not feed(second_tenant)["today"] or all(x.get("employee_id") != star["id"] for x in feed(second_tenant)["today"])


# --- special days, HR only ----------------------------------------------------

def test_the_master_adds_a_special_day_and_it_is_announced_when_it_is_today(tenant, portal):
    fan = staff(tenant, portal)
    res = tenant.post("/api/celebrations/special-days", json={"date": TODAY.isoformat(), "name": "Foundation Day",
                                                              "message": "Thank you all.", "emoji": "🏗️", "yearly": True})
    assert res.status_code == 200, res.text
    assert res.json()["announced"] >= 1
    sign_in(portal, fan)
    today = [x for x in feed(portal)["today"] if x["kind"] == "special"]
    assert [x["title"] for x in today] == ["Foundation Day"] and today[0]["message"] == "Thank you all."
    notes = portal.get("/api/employee/notifications").json()["notifications"]
    assert any("Foundation Day" in n["title"] for n in notes)


def test_a_yearly_day_comes_round_again_and_a_one_off_does_not(tenant):
    tenant.post("/api/celebrations/special-days", json={"date": "2001-%02d-%02d" % (TODAY.month, min(TODAY.day, 28)),
                                                        "name": "Yearly", "yearly": True})
    tenant.post("/api/celebrations/special-days", json={"date": "2001-%02d-%02d" % (TODAY.month, min(TODAY.day, 28)),
                                                        "name": "Once"})
    titles = [x["title"] for x in feed(tenant)["today"]]
    if TODAY.day <= 28:
        assert "Yearly" in titles and "Once" not in titles


def test_staff_without_hr_cannot_add_or_remove_special_days(tenant, portal):
    plain = staff(tenant, portal)
    made = tenant.post("/api/celebrations/special-days", json={"date": "2030-03-03", "name": "Mine"}).json()
    sign_in(portal, plain)
    assert portal.post("/api/celebrations/special-days", json={"date": "2030-03-04", "name": "Nope"}).status_code in (401, 403)
    assert portal.delete("/api/celebrations/special-days/%d" % made["id"]).status_code in (401, 403)
    assert portal.get("/api/celebrations/special-days").status_code in (401, 403)
    assert feed(portal)["can_manage"] is False


def test_hr_adds_a_special_day(tenant, portal):
    hr = staff(tenant, portal, permission_role="hr")
    sign_in(portal, hr)
    assert feed(portal)["can_manage"] is True
    res = portal.post("/api/celebrations/special-days", json={"date": "2030-03-03", "name": "Safety Week"})
    assert res.status_code == 200, res.text
    assert [d["name"] for d in portal.get("/api/celebrations/special-days").json()] == ["Safety Week"]
    assert portal.delete("/api/celebrations/special-days/%d" % res.json()["id"]).status_code == 200
    assert portal.get("/api/celebrations/special-days").json() == []


def test_a_special_day_needs_a_date_and_a_name(tenant):
    assert tenant.post("/api/celebrations/special-days", json={"date": "soon", "name": "X"}).status_code == 400
    assert tenant.post("/api/celebrations/special-days", json={"date": "2030-03-03", "name": "  "}).status_code == 400


def test_removing_a_special_day_clears_its_reactions(tenant):
    made = tenant.post("/api/celebrations/special-days", json={"date": TODAY.isoformat(), "name": "Gone soon"}).json()
    key = next(x for x in feed(tenant)["today"] if x.get("special_id") == made["id"])["key"]
    tenant.post("/api/celebrations/react", json={"celebration": key, "emoji": "🎉"})
    tenant.delete("/api/celebrations/special-days/%d" % made["id"])
    with SessionLocal() as db:
        assert db.query(models.DBCelebrationReaction).filter(models.DBCelebrationReaction.celebration == key).count() == 0


# --- told on the day ------------------------------------------------------------

def test_the_morning_job_wishes_the_birthday_person_and_tells_everybody_else(tenant, portal):
    star = staff(tenant, portal, date_of_birth=BORN)
    fan = staff(tenant, portal)
    out = run_due_jobs(only="celebrations")
    assert out[0]["status"] == "done", out
    sign_in(portal, star)
    mine = portal.get("/api/employee/notifications").json()["notifications"]
    assert any(n["title"].startswith("Happy Birthday") for n in mine)
    sign_in(portal, fan)
    theirs = portal.get("/api/employee/notifications").json()["notifications"]
    assert any(star["first_name"] in n["title"] and "birthday" in n["title"] for n in theirs)
    assert not any(n["title"].startswith("Happy Birthday") for n in theirs)
    # The Master's bell has it too, and running the job again the same day sends nothing more.
    as_owner(tenant)
    with SessionLocal() as db:
        assert db.query(models.DBAlert).filter(models.DBAlert.kind == "celebration").count() >= 1
    assert run_due_jobs(only="celebrations")[0]["status"] == "already_done"


def test_a_special_day_added_for_today_is_not_announced_twice(tenant, portal):
    fan = staff(tenant, portal)
    tenant.post("/api/celebrations/special-days", json={"date": TODAY.isoformat(), "name": "Open House"})
    run_due_jobs(only="celebrations")
    sign_in(portal, fan)
    notes = [n for n in portal.get("/api/employee/notifications").json()["notifications"] if "Open House" in n["title"]]
    assert len(notes) == 1


def test_an_employee_gives_their_own_date_of_birth(tenant, portal):
    me = staff(tenant, portal)
    sign_in(portal, me)
    assert portal.put("/api/employee/profile/details", json={"date_of_birth": BORN}).status_code == 200
    assert portal.put("/api/employee/profile/details", json={"date_of_birth": "tomorrow"}).status_code == 400
    assert birthday_of(portal, me)["kind"] == "birthday"
