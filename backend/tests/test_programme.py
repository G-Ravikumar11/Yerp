"""The programme as stored and read back worked out (GET /api/jobs/{id}/programme). The arithmetic itself is tested
in test_programme_engine.py; this is about what is kept and what the screen is given."""
from datetime import date, timedelta

import main
from app import models
from app.db.migrations import QUALITY_COLUMNS
from test_schedule import job


def _monday():
    """A Monday a few weeks out, so the dates are not near today."""
    t = date.today() + timedelta(days=21)
    return t - timedelta(days=t.weekday())


def _db():
    return main.SessionLocal()


def programme(tenant, j, **params):
    res = tenant.get("/api/jobs/%d/programme" % j["id"], params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _set(aid, **values):
    with _db() as db:
        db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.id == aid).update(values)
        db.commit()


def act(tenant, j, name, start, finish):
    """A row as the programme keeps it (the grid's own endpoints come in phase 2); returned the way the old helper was."""
    with _db() as db:
        client_id = db.query(models.DBJob).get(j["id"]).client_id
        row = models.DBScheduleActivity(client_id=client_id, job_id=j["id"], name=name, planned_start=start,
                                        planned_finish=finish)
        db.add(row)
        db.commit()
        ids = [a.id for a in db.query(models.DBScheduleActivity).filter(
            models.DBScheduleActivity.job_id == j["id"]).order_by(models.DBScheduleActivity.id).all()]
    return {"activities": [{"id": i} for i in ids]}


def test_rows_come_back_worked_out_numbered_and_rolled_up(tenant):
    mon = _monday()
    j = job(tenant)
    unit = act(tenant, j, "A-16", "", "")["activities"][0]["id"]
    putty = act(tenant, j, "Putty", mon.isoformat(), "")["activities"][-1]["id"]
    paint = act(tenant, j, "Paint", (mon + timedelta(days=7)).isoformat(), "")["activities"][-1]["id"]
    _set(putty, parent_id=unit, duration_days=7, display_order=1)                 # Mon..Sat, then Mon: 7 working days
    _set(paint, parent_id=unit, duration_days=2, display_order=2)
    p = programme(tenant, j)
    rows = {r["name"]: r for r in p["rows"]}
    assert [r["wbs"] for r in p["rows"]] == ["1", "1.1", "1.2"]
    assert rows["Putty"]["end"] == (mon + timedelta(days=7)).isoformat()           # Sunday skipped
    assert rows["A-16"]["summary"] and rows["A-16"]["start"] == mon.isoformat()
    assert rows["A-16"]["end"] == (mon + timedelta(days=8)).isoformat()
    assert p["start"] == mon.isoformat() and p["duration"] == 9 and p["errors"] == []


def test_an_old_single_depends_on_counts_as_finish_to_start(tenant):
    mon = _monday()
    j = job(tenant)
    a = act(tenant, j, "Reinforcement", mon.isoformat(), "")["activities"][0]["id"]
    b = act(tenant, j, "Shuttering", "", "")["activities"][-1]["id"]
    _set(a, duration_days=3)
    _set(b, duration_days=2, depends_on_id=a, display_order=2)
    rows = {r["name"]: r for r in programme(tenant, j)["rows"]}
    assert rows["Shuttering"]["start"] == (mon + timedelta(days=3)).isoformat()
    assert rows["Shuttering"]["predecessors"] == "1"


def test_links_holidays_and_the_working_week_are_kept_and_used(tenant):
    mon = _monday()
    j = job(tenant)
    a = act(tenant, j, "Wiring", mon.isoformat(), "")["activities"][0]["id"]
    b = act(tenant, j, "Switches", "", "")["activities"][-1]["id"]
    _set(a, duration_days=5)
    _set(b, duration_days=3, display_order=2)
    client_id = None
    with _db() as db:
        client_id = db.query(models.DBJob).get(j["id"]).client_id
        db.add(models.DBScheduleLink(client_id=client_id, job_id=j["id"], activity_id=b, predecessor_id=a, kind="SS", lag=2))
        db.add(models.DBScheduleHoliday(client_id=client_id, job_id=j["id"], holiday_on=(mon + timedelta(days=2)).isoformat(),
                                        name="Festival"))
        db.commit()
    p = programme(tenant, j)
    rows = {r["name"]: r for r in p["rows"]}
    # SS+2 from Monday, with Wednesday a holiday: Mon, Tue, (Wed off), Thu -> starts Thursday
    assert rows["Switches"]["start"] == (mon + timedelta(days=3)).isoformat()
    assert rows["Switches"]["predecessors"] == "1SS+2"
    assert p["calendar"]["weekly_off"] == [7] and p["calendar"]["holidays"][0]["name"] == "Festival"
    with _db() as db:
        db.add(models.DBScheduleCalendar(client_id=client_id, job_id=j["id"], calendar_days=True))
        db.commit()
    rows = {r["name"]: r for r in programme(tenant, j)["rows"]}
    assert rows["Wiring"]["end"] == (mon + timedelta(days=4)).isoformat()           # every day counts now


def test_another_company_cannot_read_it(tenant, second_tenant):
    j = job(tenant)
    assert second_tenant.get("/api/jobs/%d/programme" % j["id"]).status_code == 404


def test_deleting_a_row_takes_its_links_and_a_project_takes_its_calendar(tenant):
    mon = _monday()
    j = job(tenant)
    a = act(tenant, j, "Reinforcement", mon.isoformat(), "")["activities"][0]["id"]
    b = act(tenant, j, "Shuttering", mon.isoformat(), "")["activities"][-1]["id"]
    with _db() as db:
        client_id = db.query(models.DBJob).get(j["id"]).client_id
        db.add(models.DBScheduleLink(client_id=client_id, job_id=j["id"], activity_id=b, predecessor_id=a))
        db.add(models.DBScheduleCalendar(client_id=client_id, job_id=j["id"]))
        db.add(models.DBScheduleHoliday(client_id=client_id, job_id=j["id"], holiday_on=mon.isoformat()))
        base = models.DBScheduleBaseline(client_id=client_id, job_id=j["id"], label="Agreed")
        db.add(base)
        db.flush()
        db.add(models.DBScheduleBaselineRow(baseline_id=base.id, activity_id=a, start=mon.isoformat(), finish=mon.isoformat()))
        db.commit()
    assert tenant.delete("/api/master/activity/%d" % a).status_code == 200
    with _db() as db:
        assert db.query(models.DBScheduleLink).filter(models.DBScheduleLink.job_id == j["id"]).count() == 0
        assert db.query(models.DBScheduleBaselineRow).filter(models.DBScheduleBaselineRow.activity_id == a).count() == 0
    assert tenant.delete("/api/jobs/%d" % j["id"]).status_code == 200
    with _db() as db:
        for m in (models.DBScheduleCalendar, models.DBScheduleHoliday, models.DBScheduleBaseline):
            assert db.query(m).filter(m.job_id == j["id"]).count() == 0, m.__tablename__


def test_every_new_programme_column_reaches_an_older_database():
    """Adding a column is the model plus the start-up list (shared by Postgres and SQLite); miss the list and the tests
    pass while every older database answers 500."""
    listed = {(t, c) for t, c, _ in QUALITY_COLUMNS}
    for col in ("parent_id", "description", "boq_ref", "uom", "quantity", "rate", "amount", "labour_required",
                "duration_days", "not_before", "productivity", "output_per_day", "gangs", "qty_done"):
        assert ("schedule_activities", col) in listed, col
    assert ("schedule_progress", "qty_done") in listed
