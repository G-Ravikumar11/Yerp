"""An edit kept on a phone out of signal is not allowed to silently win over somebody else's save (core/versions.py).

The phone sends the version of the day it started from. If the day has been saved since, the edit is refused with the
words the app looks for, and the person chooses. A request with no version - the website, or a phone that was online - is
unchanged: the last save wins there, as it always has.
"""
from app.core.versions import CONFLICT_TEXT
from test_site_diary import diary, project


def edit(tenant, day, base=None, **fields):
    headers = {"X-Base-Version": base} if base is not None else {}
    return tenant.put("/api/diary/%d" % day["id"], json={"job_id": day["job_id"], "diary_date": day["diary_date"], **fields}, headers=headers)


def test_a_day_carries_a_version_that_moves_with_every_save(tenant):
    day = diary(tenant, project(tenant))
    assert day["updated_at"]
    import time
    time.sleep(1.1)
    saved = edit(tenant, day, work_done="Slab to Block B").json()["diary"]
    assert saved["updated_at"] > day["updated_at"]


def test_an_edit_from_the_copy_that_is_still_current_goes_through(tenant):
    day = diary(tenant, project(tenant))
    res = edit(tenant, day, base=day["updated_at"], work_done="Slab to Block B")
    assert res.status_code == 200, res.text
    assert res.json()["diary"]["work_done"] == "Slab to Block B"


def test_an_edit_from_a_copy_somebody_has_since_changed_is_refused_and_nothing_is_lost(tenant):
    import time
    day = diary(tenant, project(tenant))
    time.sleep(1.1)
    assert edit(tenant, day, work_done="Block B, by the site engineer who had signal").status_code == 200
    res = edit(tenant, day, base=day["updated_at"], work_done="Block C, written offline")
    assert res.status_code == 409 and CONFLICT_TEXT in res.json()["detail"]
    # The first save stands untouched until somebody chooses.
    assert tenant.get("/api/diary/%d" % day["id"]).json()["work_done"] == "Block B, by the site engineer who had signal"


def test_keep_mine_is_the_same_edit_sent_without_the_old_version(tenant):
    import time
    day = diary(tenant, project(tenant))
    time.sleep(1.1)
    edit(tenant, day, work_done="Theirs")
    assert edit(tenant, day, base=day["updated_at"], work_done="Mine").status_code == 409
    assert edit(tenant, day, work_done="Mine").status_code == 200
    assert tenant.get("/api/diary/%d" % day["id"]).json()["work_done"] == "Mine"


def test_the_website_with_no_version_is_never_checked(tenant):
    import time
    day = diary(tenant, project(tenant))
    time.sleep(1.1)
    edit(tenant, day, work_done="First")
    assert edit(tenant, day, work_done="Second").status_code == 200


def test_a_day_nobody_has_edited_since_it_was_made_has_a_version_to_send(tenant):
    # Days made before versions existed have none: "-" stands for it, and an edit that says so is current.
    from app import db as database, models
    day = diary(tenant, project(tenant))
    s = database.SessionLocal()
    try:
        s.query(models.DBSiteDiary).filter(models.DBSiteDiary.id == day["id"]).update({"updated_at": ""})
        s.commit()
    finally:
        s.close()
    assert edit(tenant, day, base="-", work_done="Old day, edited").status_code == 200
