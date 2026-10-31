"""The maintenance schedule: by the meter and the calendar, the meter only, or the calendar only - its thresholds,
early reminders and statuses, the service that resets it, its history, and the checks on every step."""
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import text

from app import db as database
from app.db.migrations import SCHEDULE_BACKFILL
from app.services.assets import service_schedule
from test_site_access import signed_in


def day(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


def machine(tenant, **over):
    body = {"name": "JCB 3DX", "category": "Earthmoving", "ownership": "Owned", "meter_unit": "Hours", "meter_reading": 1000}
    body.update(over)
    res = tenant.post("/api/assets", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def sched(tenant, m):
    return tenant.get("/api/assets/%d" % m["id"]).json()["service"]["schedule"]


def edit(tenant, m, **over):
    return tenant.put("/api/assets/%d" % m["id"], json=dict(m, **over))


def log_meter(tenant, m, reading, n=-1):
    """Run the meter on by a reading taken in the field."""
    j = tenant.post("/api/jobs", json={"name": "Site %s" % reading, "customer_name": "L&T"}).json()
    if not tenant.get("/api/assets/%d" % m["id"]).json()["current_job_id"]:
        assert tenant.post("/api/assets/%d/move" % m["id"], json={"to_job_id": j["id"]}).status_code == 200
    res = tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "filled_on": day(n), "litres": 10, "rate": 90, "meter_reading": reading})
    assert res.status_code == 200, res.text


# ---- the three schedule types and their thresholds ---------------------------------------------------

def test_meter_and_calendar_whichever_first(tenant):
    m = machine(tenant, service_interval_type="Both", service_every=250, service_every_days=90,
                last_service_on=day(-80), last_service_meter=900)
    s = sched(tenant, m)
    assert s["type"] == "Both" and s["next_meter"] == 1150 and s["next_on"] == day(10)
    assert s["meter_left"] == 150 and s["days_left"] == 10
    # Ten days to go is outside the default reminder (a tenth of 90 days, 9), so not yet due soon.
    assert s["status"] == "Upcoming" and s["reminder_days"] == 9 and s["reminder_meter"] == 25
    # The meter reaches its threshold first: it is that one that is reported.
    log_meter(tenant, m, 1150)
    s = sched(tenant, m)
    assert s["status"] == "Service due" and s["next_on"] == day(10)


def test_meter_only_ignores_the_calendar(tenant):
    m = machine(tenant, service_interval_type="Meter", service_every=500, service_every_days=30,
                last_service_on=day(-400), last_service_meter=800)
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    assert got["service_interval_type"] == "Meter" and got["service_every_days"] == 0
    s = got["service"]["schedule"]
    assert s["next_meter"] == 1300 and s["next_on"] is None and s["days_left"] is None and s["status"] == "Upcoming"


def test_calendar_only_ignores_the_meter(tenant):
    m = machine(tenant, service_interval_type="Days", service_every=250, service_every_days=180, last_service_on=day(-100))
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    assert got["service_every"] == 0
    s = got["service"]["schedule"]
    assert s["next_on"] == day(80) and s["next_meter"] is None and s["status"] == "Upcoming"


def test_kilometres_are_the_unit_for_a_vehicle(tenant):
    m = machine(tenant, name="Tipper", meter_unit="Km", meter_reading=42000, service_interval_type="Meter",
                service_every=10000, last_service_meter=40000)
    s = sched(tenant, m)
    assert s["unit"] == "km" and s["next_meter"] == 50000 and s["meter_left"] == 8000


# ---- statuses and early reminders --------------------------------------------------------------------

def test_meter_statuses_upcoming_due_soon_due_and_overdue(tenant):
    m = machine(tenant, service_interval_type="Meter", service_every=250, reminder_meter=50, last_service_meter=1000)
    assert sched(tenant, m)["status"] == "Upcoming"
    log_meter(tenant, m, 1210, -4)
    s = sched(tenant, m)
    assert s["status"] == "Due soon" and s["meter_left"] == 40
    log_meter(tenant, m, 1260, -3)                       # 10 past - inside a tenth of the interval
    assert sched(tenant, m)["status"] == "Service due"
    log_meter(tenant, m, 1290, -2)                       # 40 past - more than a tenth
    got = tenant.get("/api/assets/%d" % m["id"]).json()["service"]
    assert got["status"] == "Overdue" and got["due"] is True and "40 hours past its service" in got["reasons"][0]


def test_calendar_statuses_with_a_configured_reminder(tenant):
    m = machine(tenant, service_interval_type="Days", service_every_days=30, reminder_days=7, last_service_on=day(-20))
    assert sched(tenant, m)["status"] == "Upcoming"
    assert edit(tenant, m, service_interval_type="Days", service_every_days=30, reminder_days=7, last_service_on=day(-25)).status_code == 200
    assert sched(tenant, m)["status"] == "Due soon"
    assert edit(tenant, m, service_interval_type="Days", service_every_days=30, reminder_days=7, last_service_on=day(-30)).status_code == 200
    assert sched(tenant, m)["status"] == "Service due"
    assert edit(tenant, m, service_interval_type="Days", service_every_days=30, reminder_days=7, last_service_on=day(-31)).status_code == 200
    assert sched(tenant, m)["status"] == "Overdue"


def test_a_missing_meter_reading_is_not_counted_as_nought():
    """A record whose last-service reading was never taken: no meter status at all, not one counted from zero."""
    a = SimpleNamespace(service_interval_type="Meter", service_every=250, service_every_days=0, meter_reading=5000, meter_unit="Hours",
                        last_service_meter=None, last_service_on="", next_service_meter=None, next_service_on="",
                        reminder_meter=None, reminder_days=None)
    s = service_schedule(a)
    assert s["status"] == "Incomplete" and s["next_meter"] is None and s["meter_left"] is None
    # Combined, the calendar half still works on its own.
    a.service_interval_type, a.service_every_days, a.last_service_on = "Both", 30, day(-31)
    s = service_schedule(a)
    assert s["status"] == "Overdue" and s["next_meter"] is None and s["missing"] == ["the meter reading at the last service"]


def test_the_register_and_the_dashboard_agree(tenant):
    machine(tenant, name="A", service_interval_type="Days", service_every_days=30, last_service_on=day(-31))
    machine(tenant, name="B", service_interval_type="Days", service_every_days=30, last_service_on=day(-27))
    machine(tenant, name="C", service_interval_type="None")
    reg = tenant.get("/api/assets").json()
    assert reg["summary"]["service_status"]["Overdue"] == 1 and reg["summary"]["service_status"]["Due soon"] == 1
    assert reg["summary"]["service_status"]["Not scheduled"] == 1
    dash = tenant.get("/api/plant/dashboard").json()
    assert dash["cards"]["service"] == {"Due soon": 1, "Service due": 0, "Overdue": 1}
    names = {r["name"]: r["status"] for r in dash["maintenance_reminders"]}
    assert names == {"A": "Overdue", "B": "Due soon"}


# ---- validation ---------------------------------------------------------------------------------------

def test_the_schedule_is_checked(tenant):
    bad = [
        ({"service_interval_type": "Weekly"}, "meter and the calendar"),
        ({"service_interval_type": "Meter", "service_every": 0}, "How many hours"),
        ({"service_interval_type": "Meter", "service_every": -5}, "negative"),
        ({"service_interval_type": "Days", "service_every_days": 0, "last_service_on": day(-1)}, "How many days"),
        ({"service_interval_type": "Days", "service_every_days": 30}, "date of the last service"),
        ({"service_interval_type": "Days", "service_every_days": 30, "last_service_on": day(3)}, "future"),
        ({"service_interval_type": "Meter", "service_every": 250, "last_service_meter": 1200}, "cannot have been serviced at"),
        ({"service_interval_type": "Meter", "service_every": 250, "reminder_meter": 250}, "below the interval"),
        ({"service_interval_type": "Days", "service_every_days": 30, "last_service_on": day(-1), "reminder_days": 2.5}, "whole number"),
    ]
    for over, words in bad:
        res = tenant.post("/api/assets", json={"name": "X", "meter_reading": 1000, **over})
        assert res.status_code == 400 and words in res.json()["detail"], (over, res.text)
    assert tenant.get("/api/assets").json()["assets"] == []


def test_an_older_record_keeps_its_schedule(tenant):
    """Sent the way the old form sent it - two intervals, no type - the schedule is read from them."""
    m = machine(tenant, service_every=250, service_every_days=90, last_service_on=day(-10))
    assert tenant.get("/api/assets/%d" % m["id"]).json()["service_interval_type"] == "Both"


def test_the_migration_reads_the_type_from_the_intervals(tenant):
    a = machine(tenant, name="Old both", service_every=250, service_every_days=90, last_service_on=day(-10))
    b = machine(tenant, name="Old meter", service_every=250)
    c = machine(tenant, name="Old days", service_every_days=60, last_service_on=day(-10))
    d = machine(tenant, name="Old none")
    with database.engine.begin() as conn:
        conn.execute(text("UPDATE assets SET service_interval_type = '' WHERE id IN (%d, %d, %d, %d)" % (a["id"], b["id"], c["id"], d["id"])))
        conn.execute(text(SCHEDULE_BACKFILL))
        got = dict(conn.execute(text("SELECT id, service_interval_type FROM assets WHERE id IN (%d, %d, %d, %d)" % (a["id"], b["id"], c["id"], d["id"]))).fetchall())
        conn.execute(text(SCHEDULE_BACKFILL))           # again: nothing changes
        again = dict(conn.execute(text("SELECT id, service_interval_type FROM assets WHERE id IN (%d, %d, %d, %d)" % (a["id"], b["id"], c["id"], d["id"]))).fetchall())
    assert got == {a["id"]: "Both", b["id"]: "Meter", c["id"]: "Days", d["id"]: "None"} == again
    assert sched(tenant, a)["next_meter"] == 1250 and sched(tenant, a)["next_on"] == day(80)


# ---- service completion, history and audit ---------------------------------------------------------

def test_completing_a_service_resets_the_thresholds(tenant):
    m = machine(tenant, service_interval_type="Both", service_every=250, service_every_days=90, last_service_on=day(-95), last_service_meter=700)
    assert sched(tenant, m)["status"] == "Overdue"
    res = tenant.post("/api/assets/%d/service-complete" % m["id"], json={
        "completed_on": day(), "meter_at_service": 1000, "work_performed": "250 h service: oil, filters, greasing",
        "parts_used": "Engine oil 15 L, oil filter, fuel filter", "parts_cost": 8500, "labour_cost": 1500, "vendor": "JCB dealer"})
    assert res.status_code == 200, res.text
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    s = got["service"]["schedule"]
    assert got["last_service_on"] == day() and got["last_service_meter"] == 1000
    assert s["next_meter"] == 1250 and s["next_on"] == day(90) and s["status"] == "Upcoming"
    h = got["services"][0]
    assert h["work_performed"].startswith("250 h") and h["parts_used"].startswith("Engine oil") and h["total_cost"] == 10000
    assert h["meter_at_service"] == 1000 and h["next_service_meter"] == 1250 and h["next_service_on"] == day(90)
    trail = got["schedule_history"]
    assert trail[0]["action"] == "plant.service.completed" and "next meter 950.0 -> 1250.0" in trail[0]["details"]


def test_a_completion_can_set_its_own_next_thresholds_and_an_edit_keeps_them(tenant):
    m = machine(tenant, service_interval_type="Both", service_every=250, service_every_days=90, last_service_on=day(-10))
    tenant.post("/api/assets/%d/service-complete" % m["id"], json={"meter_at_service": 1000, "work_performed": "Service",
                                                                    "next_service_meter": 1200, "next_service_on": day(60)})
    s = sched(tenant, m)
    assert s["next_meter"] == 1200 and s["next_on"] == day(60)
    cur = tenant.get("/api/assets/%d" % m["id"]).json()
    assert edit(tenant, cur, notes="Painted").status_code == 200          # nothing about the schedule changed
    assert sched(tenant, m)["next_meter"] == 1200
    assert edit(tenant, cur, service_every=300).status_code == 200      # the schedule changed: worked out again
    assert sched(tenant, m)["next_meter"] == 1300


def test_service_completion_is_checked(tenant):
    m = machine(tenant, service_interval_type="Meter", service_every=250, last_service_on=day(-10), last_service_meter=900)
    url = "/api/assets/%d/service-complete" % m["id"]
    for body, words in (({"meter_at_service": 1000}, "Say what was done"),
                        ({"work_performed": "x"}, "meter reading at this service"),
                        ({"work_performed": "x", "meter_at_service": 800}, "cannot read less"),
                        ({"work_performed": "x", "meter_at_service": 1000, "completed_on": day(2)}, "before it is done"),
                        ({"work_performed": "x", "meter_at_service": 1000, "completed_on": day(-20)}, "cannot be before that"),
                        ({"work_performed": "x", "meter_at_service": 1000, "next_service_meter": 950}, "above this one"),
                        ({"work_performed": "x", "meter_at_service": 1000, "parts_cost": -1}, "negative")):
        res = tenant.post(url, json=body)
        assert res.status_code == 400 and words in res.json()["detail"], (body, res.text)
    none = machine(tenant, name="No schedule", service_interval_type="None")
    assert tenant.post("/api/assets/%d/service-complete" % none["id"], json={"work_performed": "x"}).status_code == 409


def test_an_open_preventive_job_is_completed_not_duplicated(tenant):
    m = machine(tenant, service_interval_type="Days", service_every_days=30, last_service_on=day(-29))
    raised = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Preventive", "description": "30-day service"})
    assert raised.status_code == 200
    # One reminder for the machine - on the job - not the job and the schedule side by side.
    rem = [r for r in tenant.get("/api/plant/dashboard").json()["maintenance_reminders"] if r["asset_id"] == m["id"]]
    assert len(rem) == 1 and "30-day service" in rem[0]["what"] and "service in 1 days" in rem[0]["what"]
    again = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Preventive", "description": "Again"})
    assert again.status_code == 409 and "already has a preventive service open" in again.json()["detail"]
    tenant.post("/api/assets/%d/service-complete" % m["id"], json={"work_performed": "Done"})
    jobs = tenant.get("/api/plant/maintenance?asset_id=%d" % m["id"]).json()["maintenance"]
    assert len(jobs) == 1 and jobs[0]["id"] == raised.json()["id"] and jobs[0]["status"] == "Completed"
    assert [r for r in tenant.get("/api/plant/dashboard").json()["maintenance_reminders"] if r["asset_id"] == m["id"]] == []


def test_a_completed_preventive_job_keeps_the_interval(tenant):
    """Completing from Maintenance resets the clock the same way, and no longer rewrites the interval."""
    m = machine(tenant, service_interval_type="Both", service_every=250, service_every_days=90, last_service_on=day(-30))
    mid = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Preventive", "description": "Service"}).json()["id"]
    res = tenant.post("/api/plant/maintenance/%d/complete" % mid, json={"work_performed": "Oil and filters", "next_service_meter": 1100})
    assert res.status_code == 200, res.text
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    assert got["service_every"] == 250 and got["service_every_days"] == 90
    assert got["service"]["schedule"]["next_meter"] == 1100 and got["service"]["schedule"]["next_on"] == day(90)


def test_schedule_changes_are_kept_in_the_history(tenant):
    m = machine(tenant, service_interval_type="Meter", service_every=250)
    assert edit(tenant, m, service_interval_type="Meter", service_every=500, reminder_meter=40).status_code == 200
    trail = tenant.get("/api/assets/%d" % m["id"]).json()["schedule_history"]
    assert [t["action"] for t in trail] == ["plant.schedule.changed", "plant.schedule.set"]
    assert "every meter 250.0 -> 500.0" in trail[0]["details"] and "reminder meter - -> 40.0" in trail[0]["details"]


def test_who_may_do_what(tenant, portal):
    m = machine(tenant, service_interval_type="Meter", service_every=250)
    signed_in(tenant, portal, "staff")            # records site work: completes a service, does not set the schedule
    assert portal.put("/api/assets/%d" % m["id"], json=dict(m, service_every=100)).status_code == 403
    assert portal.post("/api/assets/%d/service-complete" % m["id"], json={"work_performed": "Greased", "meter_at_service": 1000}).status_code == 200
    other = machine(tenant, name="Other", service_interval_type="Meter", service_every=250)
    signed_in(tenant, portal, "purchase")         # nothing to do with the site
    assert portal.post("/api/assets/%d/service-complete" % other["id"], json={"work_performed": "x", "meter_at_service": 1000}).status_code == 403


def test_another_company_cannot_touch_it(tenant, second_tenant):
    m = machine(tenant, service_interval_type="Meter", service_every=250)
    assert second_tenant.post("/api/assets/%d/service-complete" % m["id"], json={"work_performed": "x", "meter_at_service": 1000}).status_code == 404
