"""A site diary's "work done" moves the plan; deleting the draft takes that back. And a lower report opens a finished activity again."""
from datetime import date, timedelta

from test_schedule import act, activity_row, d, day_of, job, start_diary


def activity(tenant, j, aid):
    return next(a for a in tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"] if a["id"] == aid)


def test_deleting_a_draft_diary_takes_back_the_progress_it_reported(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Raft", d(-4), d(5))["activities"][0]["id"]
    assert tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 20, "reported_on": d(-2)}).status_code == 200
    made = start_diary(tenant, j, [{"activity_id": aid, "percent": 70}])
    assert made.status_code == 200, made.text
    assert activity(tenant, j, aid)["actual_percent"] == 70

    gone = tenant.delete("/api/diary/%d" % made.json()["diary"]["id"])
    assert gone.status_code == 200, gone.text
    assert gone.json()["undone"] == {"reports": 1, "tasks": 0} and "Taken back from Planning & Progress" in gone.json()["message"]
    assert activity(tenant, j, aid)["actual_percent"] == 20                  # back to the earlier report, not left at the diary's 70


def test_a_diary_that_finished_an_activity_leaves_it_open_when_deleted(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Slab", d(-4), d(5))["activities"][0]["id"]
    made = start_diary(tenant, j, [{"activity_id": aid, "percent": 100}])
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 100 and row["actual_finish"] == d(0)
    tenant.delete("/api/diary/%d" % made.json()["diary"]["id"])
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 0 and row["actual_finish"] == "" and row["actual_start"] == ""
    assert row["status"] in ("", "Not Started")


def test_deleting_a_draft_puts_ticked_tasks_back_as_they_were(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    ids = [tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Task %d" % n, "date": d(0), "activity_id": aid}).json()["task"]["id"] for n in range(4)]
    tenant.put("/api/schedule/tasks/%d" % ids[0], json={"done": True})                          # one was ticked on the plan itself
    made = start_diary(tenant, j, [{"task_id": ids[1], "done": True}, {"task_id": ids[2], "percent": 40}])
    assert activity_row(tenant, j, aid)["tasks_done"] == 2
    gone = tenant.delete("/api/diary/%d" % made.json()["diary"]["id"])
    assert gone.json()["undone"]["tasks"] == 2
    row = activity_row(tenant, j, aid)
    assert row["tasks_done"] == 1 and row["actual_percent"] == 25                               # only the tick made on the plan stands


def test_a_task_changed_since_the_diary_is_left_as_it_is(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    ids = [tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Task %d" % n, "date": d(0), "activity_id": aid}).json()["task"]["id"] for n in range(2)]
    made = start_diary(tenant, j, [{"task_id": ids[0], "done": True}])
    tenant.put("/api/schedule/tasks/%d" % ids[0], json={"done": False})                         # someone put it back, then
    tenant.put("/api/schedule/tasks/%d" % ids[1], json={"done": True})                          # ticked another
    gone = tenant.delete("/api/diary/%d" % made.json()["diary"]["id"])
    assert gone.json()["undone"]["tasks"] == 0                                                  # nothing of the diary's left to put back
    assert activity_row(tenant, j, aid)["tasks_done"] == 1


def test_re_saving_a_draft_diary_and_then_deleting_it_leaves_nothing(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Raft", d(-4), d(5))["activities"][0]["id"]
    made = start_diary(tenant, j, [{"activity_id": aid, "percent": 30}])
    did = made.json()["diary"]["id"]
    tenant.put("/api/diary/%d" % did, json={"work_updates": [{"activity_id": aid, "percent": 60}]})
    tenant.put("/api/diary/%d" % did, json={"work_updates": [{"activity_id": aid, "percent": 80}]})
    gone = tenant.delete("/api/diary/%d" % did)
    assert gone.json()["undone"]["reports"] == 3
    assert activity(tenant, j, aid)["actual_percent"] == 0


def test_a_signed_off_diary_still_cannot_be_deleted_and_keeps_its_progress(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Raft", d(-4), d(5))["activities"][0]["id"]
    made = start_diary(tenant, j, [{"activity_id": aid, "percent": 50}])
    did = made.json()["diary"]["id"]
    assert tenant.post("/api/diary/%d/submit" % did).status_code == 200
    assert tenant.delete("/api/diary/%d" % did).status_code == 409
    assert activity(tenant, j, aid)["actual_percent"] == 50


# --- a lower report opens a finished activity -------------------------------------------------------------------------------------

def test_a_lower_report_reopens_a_finished_activity(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Slab", d(-6), d(5))["activities"][0]["id"]
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 100, "reported_on": d(-2)})
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 100 and row["actual_finish"] == d(-2) and row["status"] == "Completed"
    res = tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 85, "reported_on": d(0)})     # found 15% still to do
    assert res.status_code == 200, res.text
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 85 and row["actual_finish"] == "" and row["status"] == "In Progress"
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 100})                                # and finishing it again
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 100 and row["actual_finish"] == d(0) and row["status"] == "Completed"


def test_a_diary_report_below_100_also_reopens_it(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Slab", d(-6), d(5))["activities"][0]["id"]
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 100, "reported_on": d(-2)})
    start_diary(tenant, j, [{"activity_id": aid, "percent": 90}])
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 90 and row["actual_finish"] == "" and row["status"] == "In Progress"


def test_a_report_dated_before_the_finish_does_not_reopen_it(tenant):
    """The latest report decides, by its date: a lower figure reported for an earlier day is history, not news."""
    j = job(tenant)
    aid = act(tenant, j, "Slab", d(-8), d(5))["activities"][0]["id"]
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 100, "reported_on": d(-1)})
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 40, "reported_on": d(-5)})
    row = activity(tenant, j, aid)
    assert row["actual_percent"] == 100 and row["actual_finish"] == d(-1)
