"""Site stories: the site diary's photos in the phone app's row (services/stories.py).

A story does not go by itself. It stays until the Master, an account admin or staff at the Master's level has opened it,
leaves the row 24 hours after that, and until then only one of them can remove the photo. The photo stays in the diary.
"""
import io
from datetime import datetime, timedelta

import pytest

from app import db as database, models
from app.services import stories
from test_app_channel import by_app, sign_in, staff, team_member
from test_site_diary import diary, project

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2048 + b"\xff\xd9"
PDF = b"%PDF-1.4\n" + b"0" * 2048 + b"\n%%EOF"


def photo(client, day, name="slab.jpg", body=JPEG, kind="image/jpeg"):
    res = client.post("/api/files", files={"file": (name, io.BytesIO(body), kind)},
                      data={"attached_type": "diary", "attached_id": str(day["id"])})
    assert res.status_code == 200, res.text
    return res.json()["file"]


def row(client):
    res = client.get("/api/stories")
    assert res.status_code == 200, res.text
    return res.json()


def ids(client):
    return [s["id"] for site in row(client)["sites"] for s in site["stories"]]


def open_story(client, f):
    return client.post("/api/stories/%d/seen" % f["id"])


@pytest.fixture
def clock(monkeypatch):
    """Move the stories' clock on: clock(hours=25)."""
    at = {"now": datetime.now()}
    monkeypatch.setattr(stories, "_now", lambda: at["now"])

    def move(**by):
        at["now"] = at["now"] + timedelta(**by)
    return move


def site_engineer(tenant, job, role="construction"):
    emp = staff(tenant, role)
    assert tenant.put("/api/employees/%d" % emp["id"], json={"site_ids": [job["id"]]}).status_code == 200
    return emp


# ---- the row ----------------------------------------------------------------------------------------------------------

def test_a_diary_photo_is_a_story_on_its_site_and_a_document_is_not(tenant):
    job = project(tenant, "Vanya City STP")
    day = diary(tenant, job)
    f = photo(tenant, day)
    photo(tenant, day, "pour-card.pdf", PDF, "application/pdf")
    out = row(tenant)
    assert out["admin"] is True and out["hours"] == 24
    [site] = out["sites"]
    assert site["job_id"] == job["id"] and site["name"] == "Vanya City STP" and site["unseen"] == 1 and site["unopened"] == 1
    [s] = site["stories"]
    assert s["id"] == f["id"] and s["diary_id"] == day["id"] and s["diary_date"] == day["diary_date"]
    assert s["seen"] is False and s["opened_at"] == "" and s["leaves_in_s"] is None
    assert s["url"] == "/api/files/%d" % f["id"] and s["work_done"] == "Slab to Block A"


def test_a_story_never_goes_until_the_master_opens_it_however_long_that_is(tenant, clock):
    job = project(tenant)
    f = photo(tenant, diary(tenant, job))
    assert ids(tenant) == [f["id"]]                     # the row has been looked at: the company's stories have begun
    crew = sign_in(site_engineer(tenant, job), None)
    # The site looks at its own story: seen by them, and that starts nothing.
    assert open_story(crew, f).json()["opened_at"] == ""
    clock(days=40)
    assert ids(tenant) == [f["id"]] and ids(crew) == [f["id"]]
    mine = row(crew)["sites"][0]["stories"][0]
    assert mine["seen"] is True and mine["opened_at"] == "" and mine["leaves_in_s"] is None
    assert row(crew)["admin"] is False


def test_it_leaves_the_row_24_hours_after_the_master_opens_it_and_the_photo_stays_in_the_diary(tenant, clock):
    job = project(tenant)
    day = diary(tenant, job)
    f = photo(tenant, day)
    crew = sign_in(site_engineer(tenant, job), None)
    opened = open_story(tenant, f).json()
    assert opened["opened_at"] and 86390 <= opened["leaves_in_s"] <= 86400
    clock(hours=23)
    [s] = row(crew)["sites"][0]["stories"]
    assert s["opened_at"] == opened["opened_at"] and 3500 <= s["leaves_in_s"] <= 3600 and s["opened_by"]
    # Opening it again does not start the 24 hours over.
    assert open_story(tenant, f).json()["opened_at"] == opened["opened_at"]
    clock(hours=2)
    assert ids(tenant) == [] and ids(crew) == []
    # Only the row changed: the photo is still on its day.
    kept = tenant.get("/api/files?attached_type=diary&attached_id=%d" % day["id"]).json()["files"]
    assert [x["id"] for x in kept] == [f["id"]]
    assert tenant.get("/api/files/%d" % f["id"]).status_code == 200


def test_an_admin_and_staff_at_the_masters_level_open_it_too_but_nobody_else_does(tenant, clock):
    job = project(tenant)
    day = diary(tenant, job)
    a, b, c = photo(tenant, day, "a.jpg"), photo(tenant, day, "b.jpg", JPEG + b"b"), photo(tenant, day, "c.jpg", JPEG + b"c")
    admin = team_member(tenant, "admin")
    boss = sign_in(staff(tenant, "owner"), None)
    manager = sign_in(staff(tenant, "project_manager"), None)
    assert row(admin)["admin"] is True and row(boss)["admin"] is True and row(manager)["admin"] is False
    assert open_story(admin, a).json()["opened_at"]
    assert open_story(boss, b).json()["opened_at"]
    assert open_story(manager, c).json()["opened_at"] == ""
    clock(hours=25)
    assert ids(tenant) == [c["id"]]


def test_sites_with_something_new_come_first_and_each_persons_seen_is_their_own(tenant):
    one, two = project(tenant, "Kokapet towers"), project(tenant, "Vanya City")
    f1 = photo(tenant, diary(tenant, one))
    photo(tenant, diary(tenant, two), "two.jpg", JPEG + b"2")
    pm = sign_in(staff(tenant, "project_manager"), None)
    assert row(pm)["unseen"] == 2
    # Looked at one site's story: the other site is in front for this person, and only for them.
    first = row(pm)["sites"][0]
    assert open_story(pm, first["stories"][0]).status_code == 200
    after = row(pm)
    assert after["unseen"] == 1 and after["sites"][0]["unseen"] == 1 and after["sites"][1]["unseen"] == 0
    assert after["sites"][1]["job_id"] == first["job_id"]
    assert row(tenant)["unseen"] == 2
    assert f1["id"] in ids(pm)


def test_site_staff_see_the_stories_of_their_own_sites_only(tenant):
    here, there = project(tenant, "Kokapet towers"), project(tenant, "Vanya City")
    mine, theirs = photo(tenant, diary(tenant, here)), photo(tenant, diary(tenant, there), "there.jpg", JPEG + b"t")
    crew = sign_in(site_engineer(tenant, here), None)
    assert ids(crew) == [mine["id"]]
    assert open_story(crew, theirs).status_code == 404


def test_photos_from_before_a_company_used_stories_are_not_all_brought_up(tenant):
    job = project(tenant)
    old = photo(tenant, diary(tenant, job, on="2026-08-01"))
    recent = photo(tenant, diary(tenant, job, on="2026-09-01"), "recent.jpg", JPEG + b"r")
    s = database.SessionLocal()
    try:
        s.query(models.DBFile).filter(models.DBFile.id == old["id"]).update({"created_at": "2026-01-05 10:00:00"})
        s.commit()
    finally:
        s.close()
    # The row reaches a week back from its first opening; what is older stays in the diary and is nobody's story.
    assert ids(tenant) == [recent["id"]]
    manager = sign_in(site_engineer(tenant, job, "project_manager"), None)
    assert manager.delete("/api/files/%d" % old["id"]).status_code == 200


# ---- a story cannot be taken away before it is seen -------------------------------------------------------------------

def test_nobody_but_the_master_or_an_admin_removes_a_story_before_it_is_opened(tenant):
    job = project(tenant)
    day = diary(tenant, job)
    row(tenant)
    f = photo(tenant, day)
    # A project manager may remove files and draft days, and is not the Master or an admin.
    manager = sign_in(site_engineer(tenant, job, "project_manager"), None)
    refused = manager.delete("/api/files/%d" % f["id"])
    assert refused.status_code == 409 and "not opened yet" in refused.json()["detail"]
    assert manager.delete("/api/diary/%d" % day["id"]).status_code == 409        # nor by throwing the day away
    assert ids(tenant) == [f["id"]]
    # Once the Master has opened it, it is an ordinary photo on a draft day again.
    assert open_story(tenant, f).status_code == 200
    assert manager.delete("/api/files/%d" % f["id"]).status_code == 200
    assert ids(tenant) == []


def test_the_master_may_remove_one_unopened(tenant):
    job = project(tenant)
    row(tenant)
    f = photo(tenant, diary(tenant, job))
    assert tenant.delete("/api/files/%d" % f["id"]).status_code == 200


def test_a_company_that_never_opened_stories_is_held_to_nothing(tenant):
    job = project(tenant)
    f = photo(tenant, diary(tenant, job))
    manager = sign_in(site_engineer(tenant, job, "project_manager"), None)
    assert manager.delete("/api/files/%d" % f["id"]).status_code == 200


# ---- the phone app, and other companies -------------------------------------------------------------------------------

def test_opening_a_story_is_open_to_everybody_in_the_app(tenant):
    job = project(tenant)
    f = photo(tenant, diary(tenant, job))
    person = site_engineer(tenant, job, "staff")           # holds none of the app's rights to change anything
    app = sign_in(person, "app")
    assert app.get("/api/employee/auth/me").json()["app_limited"] is True
    res = open_story(app, f)
    assert res.status_code == 200 and not by_app(res)
    assert row(app)["sites"][0]["stories"][0]["seen"] is True


def test_the_same_opening_sent_twice_is_one_opening(tenant):
    f = photo(tenant, diary(tenant, project(tenant)))
    first, second = open_story(tenant, f).json(), open_story(tenant, f).json()
    assert first["opened_at"] == second["opened_at"]
    s = database.SessionLocal()
    try:
        assert s.query(models.DBStoryView).filter(models.DBStoryView.file_id == f["id"]).count() == 1
    finally:
        s.close()


def test_another_company_neither_sees_nor_opens_our_stories(tenant, second_tenant):
    f = photo(tenant, diary(tenant, project(tenant)))
    assert ids(second_tenant) == []
    assert open_story(second_tenant, f).status_code == 404
    assert ids(tenant) == [f["id"]]


def test_a_stranger_gets_nothing(client):
    assert client.get("/api/stories").status_code == 401
    assert client.post("/api/stories/1/seen").status_code == 401
