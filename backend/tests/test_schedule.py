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


def test_planned_progress_runs_across_the_span(tenant):
    j = job(tenant)
    s = act(tenant, j, "Excavation", d(-10), d(10))
    assert s["activities"][0]["planned_percent"] == 50.0
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
    assert acts[0]["planned_start"] == d(0) and acts[0]["planned_finish"] == d(60)
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
