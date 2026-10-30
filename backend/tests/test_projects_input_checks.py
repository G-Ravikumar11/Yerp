"""The Projects forms refuse values that cannot be true: a date that is not a date, an end before the start, hours past 24,
a negative count, an incident that has not happened yet. (A wrong value used to be stored as typed and then flow into the
labour cost, the schedule and the safety record.)"""
from datetime import date, timedelta

import pytest

from test_boq import make_boq

TODAY = date.today()
FUTURE = (TODAY + timedelta(days=40)).isoformat()
INCIDENT = {"kind": "Near miss", "happened_on": TODAY.isoformat(), "happened_at": "10:00", "location": "Block A", "description": "Slipped",
            "injured_name": "", "injury": "", "treatment": "", "lost_days": 0, "immediate_action": "Cordoned off"}
WORKER = {"name": "Ravi", "age": 30, "address": "Hyderabad", "trade": "Mason", "screened_on": TODAY.isoformat()}


@pytest.fixture
def site(tenant):
    return tenant.post("/api/jobs", json={"name": "Checks Towers", "customer_name": "C Ltd"}).json()["id"]


def refused(res, *words):
    assert res.status_code == 400, res.text
    text = res.json()["detail"].lower()
    assert all(w.lower() in text for w in words), text


# --- projects (a retention outside 0-100 is clamped, not refused: see test_job_costing_depth) --------------------------------------------------------------------------------------------------------------

def test_a_project_needs_real_dates_in_order_and_a_retention_that_is_a_percentage(tenant):
    base = {"name": "P", "customer_name": "X"}
    refused(tenant.post("/api/jobs", json={**base, "start_date": "2026-12-01", "target_end_date": "2026-06-01"}), "before the start")
    refused(tenant.post("/api/jobs", json={**base, "start_date": "31/02/2026"}), "not a date")
    refused(tenant.post("/api/jobs", json={**base, "target_end_date": "next year"}), "not a date")
    ok = tenant.post("/api/jobs", json={**base, "start_date": "2026-06-01", "target_end_date": "2026-12-01", "retention_percent": 5})
    assert ok.status_code == 200 and ok.json()["retention_percent"] == 5
    assert tenant.post("/api/jobs", json={**base, "name": "No dates"}).status_code == 200            # dates may be left blank


def test_editing_a_project_is_checked_the_same_way(tenant, site):
    refused(tenant.put("/api/jobs/%d" % site, json={"name": "Checks Towers", "start_date": "2026-12-01", "target_end_date": "2026-01-01"}), "before the start")


# --- the site diary -----------------------------------------------------------------------------------------------------------

def diary(tenant, site, **over):
    return tenant.post("/api/diary", json={"job_id": site, "diary_date": TODAY.isoformat(), "weather": "Clear", "working_hours": 8, **over})


def test_a_diary_is_a_real_day_that_has_come_with_hours_inside_a_day(tenant, site):
    refused(diary(tenant, site, diary_date=FUTURE), "ahead")
    assert diary(tenant, site, diary_date=(TODAY + timedelta(days=1)).isoformat()).status_code == 200          # tomorrow is allowed
    refused(diary(tenant, site, diary_date="yesterday"), "not a date")
    refused(diary(tenant, site, working_hours=30), "working hours")
    refused(diary(tenant, site, rain_hours=-3), "rain")
    refused(diary(tenant, site, rain_hours=40), "rain")
    refused(diary(tenant, site, labour=[{"trade": "Mason", "headcount": -5, "hours": 8}]), "workers")
    refused(diary(tenant, site, labour=[{"trade": "Mason", "headcount": 5, "hours": 30}]), "hours")
    refused(diary(tenant, site, plant=[{"plant": "JCB", "worked_hours": 25}]), "machine")
    good = diary(tenant, site, labour=[{"trade": "Mason", "headcount": 5, "hours": 8, "rate": 700}], plant=[{"plant": "JCB", "worked_hours": 6}])
    assert good.status_code == 200, good.text
    refused(tenant.put("/api/diary/%d" % good.json()["diary"]["id"], json={"working_hours": 50}), "working hours")


# --- planning -----------------------------------------------------------------------------------------------------------------

def test_an_activity_has_no_negative_weight_and_progress_is_not_reported_for_a_day_to_come(tenant, site):
    act = {"name": "Slab", "planned_start": "2026-11-01", "planned_finish": "2026-11-09"}
    refused(tenant.post("/api/jobs/%d/schedule/activities" % site, json={**act, "weight": -10}), "weight")
    made = tenant.post("/api/jobs/%d/schedule/activities" % site, json={**act, "weight": 10})
    assert made.status_code == 200, made.text
    aid = made.json()["schedule"]["activities"][0]["id"]
    refused(tenant.put("/api/schedule/activities/%d" % aid, json={**act, "weight": -1}), "weight")
    refused(tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 10, "reported_on": FUTURE}), "future")
    assert tenant.post("/api/schedule/activities/%d/progress" % aid, json={"percent": 10}).status_code == 200


# --- workers and safety -------------------------------------------------------------------------------------------------------

def test_a_worker_is_not_screened_on_a_day_to_come_and_has_a_possible_build(tenant, site):
    refused(tenant.post("/api/workers", json={"job_id": site, **WORKER, "screened_on": FUTURE}), "future")
    refused(tenant.post("/api/workers", json={"job_id": site, **WORKER, "weight_kg": 900}), "weight")
    refused(tenant.post("/api/workers", json={"job_id": site, **WORKER, "height_cm": 20}), "height")
    assert tenant.post("/api/workers", json={"job_id": site, **WORKER}).status_code == 200                 # weight and height left out
    assert tenant.post("/api/workers", json={"job_id": site, **WORKER, "name": "Sita", "weight_kg": 62, "height_cm": 160}).status_code == 200


def test_an_incident_and_a_talk_are_real(tenant, site):
    inc = lambda **o: tenant.post("/api/safety/incidents", json={"job_id": site, **INCIDENT, **o})
    refused(inc(happened_on=FUTURE), "future")
    refused(inc(happened_at="99:99"), "time")
    refused(inc(lost_days=-4), "days lost")
    refused(inc(lost_days=5000), "days lost")
    assert inc().status_code == 200 and inc(happened_at="").status_code == 200
    talk = lambda **o: tenant.post("/api/safety/talks", json={"job_id": site, "topic": "PPE", "attendees": 8, "attendee_names": "", **o})
    refused(talk(attendees=5000), "attended")
    refused(talk(attendees=-3), "attended")
    refused(talk(held_on=FUTURE), "future")
    assert talk().status_code == 200
