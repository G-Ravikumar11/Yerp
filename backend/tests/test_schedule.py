"""The project schedule: planned against actual, with progress on measured
activities read from the book and slippage carried down the chain."""
from datetime import date, timedelta

from test_measurement_and_ra_bills import placed_order, book, measure


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vizag STP", "customer_name": "L&T"}).json()


def act(tenant, j, name, start, finish, **over):
    body = {"name": name, "planned_start": start, "planned_finish": finish}
    body.update(over)
    res = tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json=body)
    assert res.status_code == 200, res.text
    return res.json()["schedule"]


def test_an_activity_is_coded_in_tens(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-10), d(10))
    s = act(tenant, j, "Raft", d(11), d(30))
    assert [a["code"] for a in s["activities"]] == ["A10", "A20"]


def working(a, b):
    """Working days from a to b, both counted: Sundays are off unless the project says otherwise."""
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    return sum(1 for i in range((b - a).days + 1) if (a + timedelta(days=i)).isoweekday() != 7)


def snap(day):
    """A start that falls on a Sunday is moved to the Monday."""
    x = date.fromisoformat(day)
    return (x + timedelta(days=1)).isoformat() if x.isoweekday() == 7 else day


def last_working(day):
    """An end that falls on a Sunday comes back to the Saturday: its days are working days."""
    x = date.fromisoformat(day)
    return (x - timedelta(days=1)).isoformat() if x.isoweekday() == 7 else day


def test_planned_progress_runs_across_the_span(tenant):
    """A working day at a time: by the end of today, the share of its working days that have passed."""
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-10), d(10))
    expected = round(working(d(-10), d(0)) / working(d(-10), d(10)) * 100, 1)
    assert s["activities"][0]["planned_percent"] == expected
    assert s["activities"][0]["state"] == "behind"          # planned half, nothing done


def test_reported_progress_is_dated_and_starts_the_activity(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-10), d(10))
    aid = s["activities"][0]["id"]
    out = tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 55}).json()
    a = out["schedule"]["activities"][0]
    assert a["actual_percent"] == 55 and a["actual_start"] == d(0)
    assert a["state"] == "on track"


def test_a_measured_activity_reads_the_book(tenant):
    """Nobody types a percentage the book already knows."""
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    line = book(tenant, wo["id"])["lines"][0]["line_id"]
    s = tenant.post("/api/jobs/%d/schedule/activities" % job_id, json={
        "name": "Conduit", "planned_start": d(-5), "planned_finish": d(5),
        "work_order_line_id": line}).json()["schedule"]
    measure(tenant, wo["id"], line, 250)
    a = tenant.get("/api/jobs/%d/schedule" % job_id).json()["activities"][0]
    assert a["actual_percent"] == 25.0 and a["progress_from"] == "measurement book"
    res = tenant.post("/api/schedule/activities/%d/progress" % a["id"], json={"percent": 90})
    assert res.status_code == 409 and "measurement book" in res.json()["detail"]


def test_a_late_predecessor_pushes_its_successor(tenant):
    j = job(tenant)
    s = act(tenant, j, "Columns", d(-20), d(-1))
    col = s["activities"][0]["id"]
    tenant.post("/api/schedule/activities/%d/progress" % col, json={"percent": 50, "reported_on": d(-15)})
    s = act(tenant, j, "Slab", d(0), d(10), depends_on_id=col)
    cols, slab = s["activities"]
    assert cols["state"] == "late" and cols["slip_days"] > 0
    assert slab["slip_days"] > 0, "the slab cannot start until the columns are done"
    assert s["summary"]["slip_days"] > 0


def test_the_curve_is_what_was_true_each_week(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-21), d(7))
    aid = s["activities"][0]["id"]
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 20, "reported_on": d(-14)})
    tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 60, "reported_on": d(-1)})
    curve = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["curve"]
    assert curve[0]["actual"] == 0
    assert any(p["actual"] == 20 for p in curve)
    assert curve[-1]["actual"] is None or curve[-1]["actual"] == 60
    assert curve[-1]["planned"] == 100


def test_weights_decide_the_overall_percentage(tenant):
    j = job(tenant)
    s = act(tenant, j, "Big", d(-10), d(10), weight=900)
    s = act(tenant, j, "Small", d(-10), d(10), weight=100)
    big, small = s["activities"]
    tenant.post("/api/schedule/activities/%d/progress" % big["id"], json={"percent": 100})
    summary = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["summary"]
    assert summary["actual_percent"] == 90.0


def test_a_schedule_drawn_from_a_work_order(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    out = tenant.post("/api/jobs/%d/schedule/from-work-order/%d" % (job_id, wo["id"]),
                      json={"start": d(0), "finish": d(60)})
    assert out.status_code == 200, out.text
    acts = out.json()["schedule"]["activities"]
    assert len(acts) == 1 and acts[0]["work_order_line_id"]
    # the programme does not start on a Sunday
    assert acts[0]["planned_start"] == (d(1) if date.today().weekday() == 6 else d(0)) and acts[0]["planned_finish"] == d(60)
    again = tenant.post("/api/jobs/%d/schedule/from-work-order/%d" % (job_id, wo["id"]),
                        json={"start": d(0), "finish": d(60)})
    assert again.status_code == 409


def test_it_cannot_finish_before_it_starts(tenant):
    j = job(tenant)
    res = tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={
        "name": "X", "planned_start": d(5), "planned_finish": d(1)})
    assert res.status_code == 400


def test_activities_cannot_wait_on_each_other(tenant):
    j = job(tenant)
    s = act(tenant, j, "A", d(0), d(5))
    a = s["activities"][0]["id"]
    s = act(tenant, j, "B", d(6), d(9), depends_on_id=a)
    b = s["activities"][1]["id"]
    res = tenant.put("/api/schedule/activities/%d" % a, json={
        "name": "A", "planned_start": d(0), "planned_finish": d(5), "depends_on_id": b})
    assert res.status_code == 400 and "for ever" in res.json()["detail"]


def test_the_overview_lists_projects_worst_first(tenant):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-10), d(10))
    rows = tenant.get("/api/schedule-overview").json()["projects"]
    assert rows[0]["job_id"] == j["id"] and rows[0]["variance"] < 0


def test_another_tenant_cannot_see_it(tenant, second_tenant):
    j = job(tenant)
    act(tenant, j, "X", d(0), d(5))
    assert second_tenant.get("/api/jobs/%d/schedule" % j["id"]).status_code == 404


# --- the plan for one day ------------------------------------------------------------------------------------------

def test_the_day_plan_lists_what_is_due_overdue_and_next(tenant):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-4), d(5))       # running: nine days from start to finish, a ninth of it a day
    act(tenant, j, "Survey", d(-10), d(-3))         # past its finish and never reported
    act(tenant, j, "Raft", d(3), d(12))             # starts in three days
    act(tenant, j, "Handover", d(40), d(45))        # too far off to list
    day = tenant.get("/api/jobs/%d/schedule/day" % j["id"]).json()
    assert [a["name"] for a in day["today"]] == ["Excavation"]
    late = (date.today() - date.fromisoformat(last_working(d(-3)))).days
    assert [a["name"] for a in day["overdue"]] == ["Survey"] and day["overdue"][0]["days_late"] == late
    starts = (date.fromisoformat(snap(d(3))) - date.today()).days       # a Sunday start is the Monday
    assert [a["name"] for a in day["soon"]] == ["Raft"] and day["soon"][0]["starts_in"] == starts
    work = day["today"][0]
    # the day's share: a working day's worth of its working days (nothing on a Sunday)
    s0, n = snap(d(-4)), None
    n = working(s0, d(5))
    target = round(round(working(s0, d(0)) / n * 100, 1) - round(working(s0, d(-1)) / n * 100, 1), 1)
    assert work["target_today"] == target and work["actual_percent"] == 0 and work["to_catch_up"] == work["planned_percent"] > 0
    assert day["summary"]["working"] == 1 and day["summary"]["overdue"] == 1 and day["summary"]["starting_soon"] == 1


def test_the_day_plan_follows_the_date_asked_for(tenant):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-4), d(5))
    far = tenant.get("/api/jobs/%d/schedule/day" % j["id"], params={"on": d(20)}).json()
    assert far["date"] == d(20) and far["today"] == [] and [a["name"] for a in far["overdue"]] == ["Excavation"]
    assert tenant.get("/api/jobs/%d/schedule/day" % j["id"], params={"on": "tomorrow"}).status_code == 400


def test_finished_work_drops_off_the_day_plan(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-4), d(5))
    tenant.post("/api/schedule/activities/%d/progress" % s["activities"][0]["id"], json={"percent": 100})
    day = tenant.get("/api/jobs/%d/schedule/day" % j["id"]).json()
    assert day["today"] == [] and day["overdue"] == []


# --- what is to be done on the day, and progress as it is reported ---------------------------------------------------

def day_of(tenant, j, on=None):
    return tenant.get("/api/jobs/%d/schedule/day" % j["id"], params={"on": on or d(0)}).json()


def test_a_task_belongs_to_its_day_and_can_be_ticked_off(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-4), d(5))
    aid = s["activities"][0]["id"]
    made = tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Pour the slab, 8 labourers", "date": d(0), "activity_id": aid})
    assert made.status_code == 200, made.text
    tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Order cement", "date": d(1)})
    today = day_of(tenant, j)["tasks"]
    assert [t["text"] for t in today] == ["Pour the slab, 8 labourers"] and today[0]["activity"].endswith("Excavation")
    assert [t["text"] for t in day_of(tenant, j, d(1))["tasks"]] == ["Order cement"]
    tid = made.json()["task"]["id"]
    done = tenant.put("/api/schedule/tasks/%d" % tid, json={"done": True}).json()["task"]
    assert done["done"] is True and done["done_by_name"] and done["done_at"]
    undone = tenant.put("/api/schedule/tasks/%d" % tid, json={"done": False}).json()["task"]
    assert undone["done"] is False and undone["done_by_name"] == ""


def test_a_task_is_checked_before_it_is_kept(tenant):
    j = job(tenant)
    other = job(tenant)
    s = act(tenant, other, "Elsewhere", d(0), d(5))
    post = lambda body: tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json=body)
    assert post({"text": "  ", "date": d(0)}).status_code == 400
    assert post({"text": "x", "date": "soon"}).status_code == 400
    assert post({"text": "x", "date": d(0), "activity_id": s["activities"][0]["id"]}).status_code == 400   # another project's


def test_a_task_can_be_reworded_moved_and_removed(tenant):
    j = job(tenant)
    tid = tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Shuttering", "date": d(0)}).json()["task"]["id"]
    moved = tenant.put("/api/schedule/tasks/%d" % tid, json={"text": "Shuttering, level 2", "date": d(2)}).json()["task"]
    assert moved["text"] == "Shuttering, level 2" and moved["date"] == d(2)
    assert day_of(tenant, j)["tasks"] == []
    assert tenant.delete("/api/schedule/tasks/%d" % tid).status_code == 200
    assert day_of(tenant, j, d(2))["tasks"] == []
    assert tenant.delete("/api/schedule/tasks/%d" % tid).status_code == 404


def test_deleting_an_activity_keeps_its_tasks_on_the_project(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-4), d(5))
    aid = s["activities"][0]["id"]
    tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Clear the site", "date": d(0), "activity_id": aid})
    assert tenant.delete("/api/schedule/activities/%d" % aid).status_code == 200
    kept = day_of(tenant, j)["tasks"]
    assert [t["text"] for t in kept] == ["Clear the site"] and kept[0]["activity_id"] is None


def test_the_day_plan_says_who_last_reported_progress_and_whether_it_can_be_reported(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-4), d(5))
    tenant.post("/api/schedule/activities/%d/progress" % s["activities"][0]["id"], json={"percent": 40})
    row = day_of(tenant, j)["today"][0]
    assert row["actual_percent"] == 40 and row["updated_on"] == d(0) and row["updated_by"] and row["editable"] is True


def test_a_project_with_tasks_can_still_be_deleted(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-4), d(5))
    tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Clear the site", "date": d(0), "activity_id": s["activities"][0]["id"]})
    assert tenant.delete("/api/jobs/%d" % j["id"]).status_code == 200


# --- an activity's progress follows its tasks --------------------------------------------------------------------------

def activity_row(tenant, j, aid):
    return [a for a in day_of(tenant, j)["today"] if a["id"] == aid][0]


def test_ticking_a_task_raises_its_activitys_progress(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    ids = [tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Task %d" % n, "date": d(0), "activity_id": aid}).json()["task"]["id"] for n in range(4)]
    assert activity_row(tenant, j, aid)["actual_percent"] == 0
    tenant.put("/api/schedule/tasks/%d" % ids[0], json={"done": True})
    row = activity_row(tenant, j, aid)
    assert row["actual_percent"] == 25 and row["tasks_done"] == 1 and row["tasks_total"] == 4
    assert [t["done"] for t in row["tasks"]] == [True, False, False, False]
    tenant.put("/api/schedule/tasks/%d" % ids[1], json={"done": True})
    assert activity_row(tenant, j, aid)["actual_percent"] == 50
    tenant.put("/api/schedule/tasks/%d" % ids[1], json={"done": False})
    assert activity_row(tenant, j, aid)["actual_percent"] == 25


def test_the_last_task_finishes_the_activity_and_unticking_reopens_it(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    tid = tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Only task", "date": d(0), "activity_id": aid}).json()["task"]["id"]
    tenant.put("/api/schedule/tasks/%d" % tid, json={"done": True})
    sch = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]
    assert sch["actual_percent"] == 100 and sch["state"] == "done"
    tenant.put("/api/schedule/tasks/%d" % tid, json={"done": False})
    again = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]
    assert again["actual_percent"] == 0 and again["state"] != "done"


def test_adding_or_removing_a_task_moves_the_share(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    new = lambda text: tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": text, "date": d(0), "activity_id": aid}).json()["task"]["id"]
    a, b = new("one"), new("two")
    tenant.put("/api/schedule/tasks/%d" % a, json={"done": True})
    assert activity_row(tenant, j, aid)["actual_percent"] == 50
    new("three")
    assert activity_row(tenant, j, aid)["actual_percent"] == 33.3        # a new task is more still to do
    tenant.delete("/api/schedule/tasks/%d" % b)
    assert activity_row(tenant, j, aid)["actual_percent"] == 50


# --- the site diary reports the planned work done -----------------------------------------------------------------------

def start_diary(tenant, j, updates, on=None):
    return tenant.post("/api/diary", json={"job_id": j["id"], "diary_date": on or d(0), "work_done": "Slab", "work_updates": updates})


def test_a_diary_ticks_planned_tasks_and_the_activitys_progress_follows(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    ids = [tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Task %d" % n, "date": d(0), "activity_id": aid}).json()["task"]["id"] for n in range(4)]
    res = start_diary(tenant, j, [{"task_id": ids[0], "done": True}, {"task_id": ids[1], "done": True}])
    assert res.status_code == 200, res.text
    assert res.json()["planning"] == {"tasks": 2, "activities": 0} and "Planning & Progress updated: 2 tasks" in res.json()["message"]
    row = day_of(tenant, j)["today"][0]
    assert row["actual_percent"] == 50 and row["tasks_done"] == 2
    done = [t for t in row["tasks"] if t["done"]]
    assert len(done) == 2 and all(t["done_by_name"] for t in done)


def test_a_diary_sets_progress_on_an_activity_without_tasks(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    res = start_diary(tenant, j, [{"activity_id": aid, "percent": 35}])
    assert res.status_code == 200, res.text
    assert res.json()["planning"] == {"tasks": 0, "activities": 1}
    assert day_of(tenant, j)["today"][0]["actual_percent"] == 35


def test_saving_the_diary_again_does_not_move_the_plan_twice(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    diary_id = start_diary(tenant, j, [{"activity_id": aid, "percent": 35}]).json()["diary"]["id"]
    again = tenant.put("/api/diary/%d" % diary_id, json={"work_updates": [{"activity_id": aid, "percent": 35}]})
    assert again.status_code == 200 and again.json()["planning"] == {"tasks": 0, "activities": 0}
    moved = tenant.put("/api/diary/%d" % diary_id, json={"work_updates": [{"activity_id": aid, "percent": 60}]})
    assert moved.json()["planning"]["activities"] == 1 and day_of(tenant, j)["today"][0]["actual_percent"] == 60


def test_a_diary_can_put_a_task_back(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    tid = tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Dig", "date": d(0), "activity_id": aid}).json()["task"]["id"]
    diary_id = start_diary(tenant, j, [{"task_id": tid, "done": True}]).json()["diary"]["id"]
    assert tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]["state"] == "done"
    tenant.put("/api/diary/%d" % diary_id, json={"work_updates": [{"task_id": tid, "done": False}]})
    assert tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]["actual_percent"] == 0


def test_a_diary_cannot_move_work_that_is_not_its_to_move(tenant, second_tenant):
    j, other = job(tenant), job(second_tenant)
    theirs = act(second_tenant, other, "Elsewhere", d(-4), d(5))["activities"][0]["id"]
    their_task = second_tenant.post("/api/jobs/%d/schedule/tasks" % other["id"], json={"text": "x", "date": d(0), "activity_id": theirs}).json()["task"]["id"]
    # another company's, and another project's, are refused
    assert start_diary(tenant, j, [{"task_id": their_task, "done": True}]).status_code == 400
    assert start_diary(tenant, j, [{"activity_id": theirs, "percent": 100}], on=d(-1)).status_code == 400
    mine = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    assert start_diary(tenant, j, [{"activity_id": mine, "percent": 120}], on=d(-2)).status_code == 400
    # an activity that follows its tasks is not set by a percentage
    tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "y", "date": d(0), "activity_id": mine})
    refused = start_diary(tenant, j, [{"activity_id": mine, "percent": 50}], on=d(-3))
    assert refused.status_code == 409 and "follows its tasks" in refused.json()["detail"]
    assert second_tenant.get("/api/jobs/%d/schedule/day" % other["id"]).json()["tasks"][0]["done"] is False


def test_a_diary_without_work_updates_still_saves_as_before(tenant):
    j = job(tenant)
    res = start_diary(tenant, j, None)
    assert res.status_code == 200 and res.json()["planning"] == {"tasks": 0, "activities": 0}
    assert res.json()["message"] == "Diary opened for %s." % d(0)


# ---- the project chart: who is responsible, what is late, how long it runs ----

def employee(tenant, first="Suresh", last="Babu"):
    from conftest import make_employee
    return make_employee(tenant, first_name=first, last_name=last)


def test_an_activity_is_given_to_an_employee_and_listed_under_their_name(tenant):
    from conftest import make_employee
    j = job(tenant)
    e = employee(tenant)
    s = act(tenant, j, "Excavation", d(-10), d(10), assigned_to_id=e["id"])
    a = s["activities"][0]
    assert a["assigned_to_id"] == e["id"] and a["assigned_to"] == "Suresh Babu"
    assert {"id": e["id"], "name": "Suresh Babu"} in s["employees"]
    # Changed, then taken off.
    other = make_employee(tenant, first_name="Anil", last_name="Rao")
    s = tenant.put("/api/schedule/activities/%d" % a["id"], json={"name": "Excavation", "planned_start": d(-10), "planned_finish": d(10), "assigned_to_id": other["id"]}).json()["schedule"]
    assert s["activities"][0]["assigned_to"] == "Anil Rao"
    s = tenant.put("/api/schedule/activities/%d" % a["id"], json={"name": "Excavation", "planned_start": d(-10), "planned_finish": d(10)}).json()["schedule"]
    assert s["activities"][0]["assigned_to_id"] is None


def test_only_an_employee_of_this_company_can_be_given_the_work(tenant, second_tenant):
    j = job(tenant)
    stranger = employee(second_tenant, "Other", "Firm")
    res = tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={"name": "Raft", "planned_start": d(0), "planned_finish": d(5), "assigned_to_id": stranger["id"]})
    assert res.status_code == 400
    res = tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={"name": "Raft", "planned_start": d(0), "planned_finish": d(5), "assigned_to_id": 99999})
    assert res.status_code == 400
    assert tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"] == []


def test_the_chart_reports_overdue_work_delays_and_the_timeline(tenant):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-20), d(-5))
    s = act(tenant, j, "Raft", d(-4), d(30), depends_on_id=tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]["id"])
    late, ok = s["activities"]
    # five days past its end - six when that end falls on a Sunday, which is no working day, so it ends the Saturday
    late_by = (date.today() - date.fromisoformat(last_working(d(-5)))).days
    assert late["overdue"] and late["days_late"] == late_by and late["delayed"]
    assert not ok["overdue"] and ok["delayed"]                  # it cannot start until the late one is done
    assert s["summary"]["overdue"] == 1
    first, last = snap(d(-20)), last_working(d(30))           # a Sunday start or end moves to the working day
    span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    assert s["summary"]["start"] == first and s["summary"]["end"] == last and s["summary"]["duration_days"] == span
    # Finished work is not overdue, and a milestone is counted and tracked.
    tenant.post("/api/schedule/activities/%d/progress" % late["id"], json={"percent": 100})
    s = act(tenant, j, "Handover", d(31), d(31), is_milestone=True)
    assert s["summary"]["overdue"] == 0 and s["summary"]["milestones"] == 1 and s["summary"]["milestones_done"] == 0
    assert [a["predecessor_code"] for a in s["activities"]][1] == "A10"


# ---- status, notes, codes, dependencies and the project team ----

def put_act(tenant, a, **over):
    body = {"name": a["name"], "planned_start": a["planned_start"], "planned_finish": a["planned_finish"], "code": a["code"]}
    body.update(over)
    return tenant.put("/api/schedule/activities/%d" % a["id"], json=body)


def test_status_and_notes_are_saved_and_shown(tenant):
    j = job(tenant)
    s = act(tenant, j, "Raft", d(0), d(20), notes="Needs the pump booked", status="In Progress")
    a = s["activities"][0]
    assert a["status"] == "In Progress" and a["stored_status"] == "In Progress" and a["notes"] == "Needs the pump booked"
    assert a["actual_percent"] == 0
    assert act(tenant, j, "Walls", d(30), d(40))["activities"][1]["status"] == "Not Started"
    assert tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={"name": "X", "planned_start": d(0), "planned_finish": d(1), "status": "Whenever"}).status_code == 400


def test_completed_reports_one_hundred_percent_and_late_work_shows_as_delayed(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-20), d(-5))
    a = s["activities"][0]
    assert a["status"] == "Delayed" and a["overdue"]
    done = put_act(tenant, a, status="Completed").json()["schedule"]["activities"][0]
    assert done["status"] == "Completed" and done["actual_percent"] == 100 and not done["overdue"]
    # It cannot be called In Progress while it is reported complete: the work is reported lower first.
    refused = put_act(tenant, done, status="In Progress")
    assert refused.status_code == 409 and "100% complete" in refused.json()["detail"]
    tenant.post("/api/schedule/activities/%d/progress" % done["id"], json={"percent": 70})
    reopened = put_act(tenant, done, status="In Progress").json()["schedule"]["activities"][0]
    assert reopened["status"] == "In Progress" and reopened["actual_percent"] == 70


def test_codes_are_not_repeated_on_a_project(tenant):
    j = job(tenant)
    act(tenant, j, "Excavation", d(0), d(5), code="EX-1")
    clash = tenant.post("/api/jobs/%d/schedule/activities" % j["id"], json={"name": "Backfill", "planned_start": d(6), "planned_finish": d(9), "code": " ex-1 "})
    assert clash.status_code == 409 and "EX-1" in clash.json()["detail"]
    other = job(tenant)
    assert tenant.post("/api/jobs/%d/schedule/activities" % other["id"], json={"name": "Backfill", "planned_start": d(6), "planned_finish": d(9), "code": "EX-1"}).status_code == 200
    # An activity may keep its own code when it is saved again, and a generated code never collides with a typed one.
    s = act(tenant, j, "Piling", d(10), d(12), code="A20")
    s = act(tenant, j, "Capping", d(13), d(15))
    codes = [a["code"] for a in s["activities"]]
    assert len(set(codes)) == len(codes) == 3
    first = s["activities"][0]
    assert put_act(tenant, first, name="Excavation works").status_code == 200


def test_dates_and_dependencies_are_checked(tenant):
    j = job(tenant)
    s = act(tenant, j, "A", d(0), d(5))
    a = s["activities"][0]
    s = act(tenant, j, "B", d(6), d(9), depends_on_id=a["id"])
    b = s["activities"][1]
    s = act(tenant, j, "C", d(10), d(12), depends_on_id=b["id"])
    c = s["activities"][2]
    post = "/api/jobs/%d/schedule/activities" % j["id"]
    assert tenant.post(post, json={"name": "", "planned_start": d(0), "planned_finish": d(1)}).status_code == 400
    assert tenant.post(post, json={"name": "Z", "planned_start": "soon", "planned_finish": d(1)}).status_code == 400
    assert tenant.post(post, json={"name": "Z", "planned_start": d(5), "planned_finish": d(1)}).status_code == 400
    assert tenant.post(post, json={"name": "Z", "planned_start": d(0), "planned_finish": d(1), "actual_finish": "x"}).status_code == 400
    # No loops: itself, a straight pair, or round a chain.
    assert put_act(tenant, a, depends_on_id=a["id"]).status_code == 400
    assert put_act(tenant, a, depends_on_id=b["id"]).status_code == 400
    r = put_act(tenant, a, depends_on_id=c["id"])
    assert r.status_code == 400 and "wait on each other" in r.json()["detail"]
    # Nor on an activity of another project.
    k = job(tenant)
    foreign = act(tenant, k, "Elsewhere", d(0), d(3))["activities"][0]
    assert put_act(tenant, a, depends_on_id=foreign["id"]).status_code == 400
    assert put_act(tenant, a, depends_on_id=999999).status_code == 400


def test_the_assignee_list_is_the_projects_own_team(tenant):
    from conftest import make_employee
    from app import db as database, models
    j = job(tenant)
    on = make_employee(tenant, first_name="On", last_name="Site")
    off = make_employee(tenant, first_name="Not", last_name="Here")
    # Nobody placed yet: the whole company is offered.
    s = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()
    assert s["team_scope"] == "company" and {e["name"] for e in s["employees"]} >= {"On Site", "Not Here"}
    sess = database.SessionLocal()
    try:
        emp = sess.query(models.DBEmployee).filter(models.DBEmployee.id == on["id"]).first()
        sess.add(models.DBEmployeeSite(client_id=emp.client_id, employee_id=emp.id, job_id=j["id"]))
        sess.commit()
    finally:
        sess.close()
    s = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()
    assert s["team_scope"] == "project" and [e["name"] for e in s["employees"]] == ["On Site"]
    # Somebody already given work stays on the list.
    s = act(tenant, j, "Raft", d(0), d(5), assigned_to_id=off["id"])
    assert {e["name"] for e in s["employees"]} == {"On Site", "Not Here"}


def test_the_status_set_in_the_edit_form_is_the_status_shown(tenant):
    j = job(tenant)
    a = act(tenant, j, "Raft", d(-10), d(-2))["activities"][0]            # past its deadline: worked out, it is Delayed
    assert a["status"] == "Delayed" and a["overdue"]
    for want in ("In Progress", "Not Started", "Delayed", "Completed"):
        got = put_act(tenant, a, status=want).json()["schedule"]["activities"][0]
        assert got["status"] == want and got["stored_status"] == want, want
        a = got
    # Overdue is still said beside it: the status is what was set, the lateness is a fact.
    back = put_act(tenant, dict(a, name="Raft"), status="In Progress")
    assert back.status_code == 409          # reported complete by the step above
    a2 = act(tenant, j, "Walls", d(-10), d(-2))["activities"][1]
    got = put_act(tenant, a2, status="In Progress").json()["schedule"]["activities"][1]
    assert got["status"] == "In Progress" and got["overdue"] and got["days_late"] == 2


def test_reporting_progress_moves_the_status_with_it(tenant):
    j = job(tenant)
    a = act(tenant, j, "Raft", d(0), d(20), status="Not Started")["activities"][0]
    assert a["status"] == "Not Started"
    s = tenant.post("/api/schedule/activities/%d/progress" % a["id"], json={"percent": 30}).json()["schedule"]
    assert s["activities"][0]["status"] == "In Progress"
    s = tenant.post("/api/schedule/activities/%d/progress" % a["id"], json={"percent": 100}).json()["schedule"]
    assert s["activities"][0]["status"] == "Completed" and s["activities"][0]["stored_status"] == "Completed"
    # Not Started is refused once work is reported on it.
    b = act(tenant, j, "Walls", d(0), d(9))["activities"][1]
    tenant.post("/api/schedule/activities/%d/progress" % b["id"], json={"percent": 25})
    assert put_act(tenant, b, status="Not Started").status_code == 409

# --- one activity on a page of its own ------------------------------------------------------------------------------------

def test_an_activity_comes_with_its_tasks_on_every_day_and_its_history(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    for n, day in enumerate((d(-1), d(0), d(2))):
        tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Task %d" % n, "date": day, "activity_id": aid})
    first = tenant.get("/api/jobs/%d/schedule/day" % j["id"]).json()["today"][0]["tasks"][0]["id"]
    tenant.put("/api/schedule/tasks/%d" % first, json={"done": True})
    out = tenant.get("/api/schedule/activities/%d" % aid).json()
    a = out["activity"]
    assert out["job"]["id"] == j["id"] and a["name"] == "Excavation" and a["code"]
    assert [t["date"] for t in a["tasks"]] == [d(-1), d(0), d(2)], "every day, in date order"
    assert a["tasks_total"] == 3 and a["tasks_done"] == 1 and round(a["actual_percent"]) == 33
    assert a["editable"] is True and a["planned_start"] == snap(d(-4)) and a["state"]
    assert out["history"][0]["percent"] == 33.3 and out["history"][0]["note"] == "From its tasks"


def test_an_activity_that_is_not_yours_or_not_there_is_not_found(tenant, second_tenant):
    j = job(second_tenant)
    aid = act(second_tenant, j, "Elsewhere", d(-4), d(5))["activities"][0]["id"]
    assert tenant.get("/api/schedule/activities/%d" % aid).status_code == 404
    assert tenant.get("/api/schedule/activities/999999").status_code == 404
    assert second_tenant.get("/api/schedule/activities/%d" % aid).status_code == 200


# --- a task that is only part done ------------------------------------------------------------------------------------

def two_tasks(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    ids = [tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": t, "date": d(0), "activity_id": aid}).json()["task"]["id"] for t in ("Dig", "Haul")]
    return j, aid, ids


def test_a_task_part_done_moves_the_activity_by_that_share(tenant):
    j, aid, (dig, haul) = two_tasks(tenant)
    part = tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": 40}).json()["task"]
    assert part["percent"] == 40 and part["done"] is False
    row = activity_row(tenant, j, aid)
    assert row["actual_percent"] == 20 and row["tasks_done"] == 0, "40% of one of two tasks is a fifth of the activity"
    tenant.put("/api/schedule/tasks/%d" % haul, json={"done": True})
    assert activity_row(tenant, j, aid)["actual_percent"] == 70      # (40 + 100) / 2


def test_part_done_then_done_finishes_the_task_and_going_back_clears_it(tenant):
    j, aid, (dig, haul) = two_tasks(tenant)
    tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": 40})
    done = tenant.put("/api/schedule/tasks/%d" % dig, json={"done": True}).json()["task"]
    assert done["done"] is True and done["percent"] == 100
    assert activity_row(tenant, j, aid)["actual_percent"] == 50
    reset = tenant.put("/api/schedule/tasks/%d" % dig, json={"done": False}).json()["task"]
    assert reset["done"] is False and reset["percent"] == 0
    assert activity_row(tenant, j, aid)["actual_percent"] == 0


def test_a_task_reported_at_a_hundred_per_cent_is_done_and_can_be_lowered(tenant):
    j, aid, (dig, haul) = two_tasks(tenant)
    full = tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": 100}).json()["task"]
    assert full["done"] is True and full["done_by_name"]
    lower = tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": 30}).json()["task"]
    assert lower["done"] is False and lower["percent"] == 30
    assert activity_row(tenant, j, aid)["actual_percent"] == 15


def test_part_done_must_be_a_real_percentage(tenant):
    j, aid, (dig, haul) = two_tasks(tenant)
    assert tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": 120}).status_code == 400
    assert tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": -5}).status_code == 400
    assert activity_row(tenant, j, aid)["actual_percent"] == 0


def test_putting_a_part_done_task_back_clears_the_part(tenant):
    j, aid, (dig, haul) = two_tasks(tenant)
    tenant.put("/api/schedule/tasks/%d" % dig, json={"percent": 40})
    back = tenant.put("/api/schedule/tasks/%d" % dig, json={"done": False}).json()["task"]
    assert back["percent"] == 0 and back["done"] is False and back["done_by_name"] == ""
    assert activity_row(tenant, j, aid)["actual_percent"] == 0


def test_a_diary_can_report_a_task_part_done(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(5))["activities"][0]["id"]
    ids = [tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": t, "date": d(0), "activity_id": aid}).json()["task"]["id"] for t in ("Dig", "Haul")]
    res = start_diary(tenant, j, [{"task_id": ids[0], "percent": 40}, {"task_id": ids[1], "done": True}])
    assert res.status_code == 200, res.text
    assert res.json()["planning"]["tasks"] == 2
    row = day_of(tenant, j)["today"][0]
    assert row["actual_percent"] == 70 and row["tasks_done"] == 1
    assert [t["percent"] for t in row["tasks"]] == [40, 100]
    again = tenant.put("/api/diary/%d" % res.json()["diary"]["id"], json={"work_updates": [{"task_id": ids[0], "percent": 40}]})
    assert again.json()["planning"]["tasks"] == 0, "the same state again moves nothing"
    assert start_diary(tenant, j, [{"task_id": ids[0], "percent": 130}], on=d(-1)).status_code == 400


def test_a_diary_dated_in_the_future_still_moves_the_plan_from_today(tenant):
    j = job(tenant)
    aid = act(tenant, j, "Excavation", d(-4), d(9))["activities"][0]["id"]
    tid = tenant.post("/api/jobs/%d/schedule/tasks" % j["id"], json={"text": "Dig", "date": d(0), "activity_id": aid}).json()["task"]["id"]
    assert start_diary(tenant, j, [{"task_id": tid, "done": True}], on=d(1)).status_code == 200
    now = tenant.get("/api/jobs/%d/schedule" % j["id"]).json()["activities"][0]
    assert now["actual_percent"] == 100 and now["state"] == "done"


def test_the_day_plan_also_lists_every_other_activity_on_the_site(tenant):
    j = job(tenant)
    act(tenant, j, "Excavation", d(-4), d(5))        # running
    s = act(tenant, j, "Finished work", d(-20), d(-10))
    act(tenant, j, "Handover", d(40), d(45))         # too far off for "coming up"
    tenant.post("/api/schedule/activities/%d/progress" % [a for a in s["activities"] if a["name"] == "Finished work"][0]["id"], json={"percent": 100})
    day = day_of(tenant, j)
    assert [a["name"] for a in day["today"]] == ["Excavation"]
    names = {a["name"]: a["bucket"] for a in day["others"]}
    assert names == {"Finished work": "done", "Handover": "later"}, "nothing on the site goes missing"
    everything = [a["name"] for k in ("today", "overdue", "soon", "others") for a in day[k]]
    assert sorted(everything) == ["Excavation", "Finished work", "Handover"]
    assert all("tasks" in a and "editable" in a for a in day["others"])
