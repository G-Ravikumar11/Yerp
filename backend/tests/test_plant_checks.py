"""What the plant module checks for itself: project costs counted once, one logbook, a meter that only runs forward, the
alerts, the fuel flags and rental bills against their agreements. Mail is stood in for; everything else is real."""
from datetime import date, datetime, timedelta

import pytest

import main
from app import models
from app.core import notifications
from app.core.scheduler import run_due_jobs
from app.services.plant_checks import expected_charge, run_unbilled_alerts, run_weekly_alerts
from tests.conftest import make_employee


def day(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def _fresh():
    main.rate_limiter._hits.clear()
    notifications.NOTIFY_SYNC = True
    yield
    notifications.NOTIFY_SYNC = False


def job(tenant, name="Vizag STP"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()


def machine(tenant, **over):
    body = {"name": "JCB 3DX", "category": "Earthmoving", "ownership": "Owned", "meter_unit": "Hours", "meter_reading": 0}
    body.update(over)
    res = tenant.post("/api/assets", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def deploy(tenant, m, j):
    assert tenant.post("/api/assets/%d/move" % m["id"], json={"to_job_id": j["id"]}).status_code == 200


def person(tenant):
    return make_employee(tenant, job_title="Operator", salary=20800)


def log(tenant, m, e, opening, closing, on, **over):
    body = {"asset_id": m["id"], "employee_id": e["id"], "log_date": on, "shift": "Day", "start_time": "07:00", "end_time": "19:00",
            "break_minutes": 60, "opening_meter": opening, "closing_meter": closing}
    body.update(over)
    return tenant.post("/api/plant/logs", json=body)


def fuel(tenant, m, on, litres=100, rate=90, **over):
    res = tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "filled_on": on, "litres": litres, "rate": rate, **over})
    assert res.status_code == 200, res.text
    return res.json()


def hired_machine(tenant, j=None, **rental):
    m = machine(tenant, name="Hydra crane", ownership="Hired", hire_rate=1000, hire_basis="Hour")
    if j:
        deploy(tenant, m, j)
    p = tenant.post("/api/plant/rental-providers", json={"name": "Sai Cranes %s" % m["id"]}).json()["provider"]
    terms = {"asset_id": m["id"], "provider_id": p["id"], "agreement_no": "AG-%s" % m["id"], "start_date": "2026-09-01", "expected_return": "2026-12-31",
             "rate": 90000, "billing": "Monthly", "min_billable_hours": 200, "overtime_rate": 1500}
    terms.update(rental)
    res = tenant.post("/api/plant/rentals", json=terms)
    assert res.status_code == 200, res.text
    return m, res.json()["id"]


def pnl(tenant, j):
    return tenant.get("/api/jobs/%d/pnl" % j["id"]).json()["cost"]


# ---- 1. what the machines cost a project ---------------------------------------------------------

def test_every_plant_cost_lands_on_its_project_once(tenant):
    j, other = job(tenant), job(tenant, "Other")
    e = person(tenant)
    m = machine(tenant, name="Excavator")
    deploy(tenant, m, j)
    assert log(tenant, m, e, 100, 108, day(-3)).status_code == 200
    fuel(tenant, m, day(-3), litres=50, rate=100)                                    # 5,000 from the fuel register
    res = tenant.post("/api/plant/expenses", json={"asset_id": m["id"], "category": "Spare parts", "spent_on": day(-3), "description": "Filters", "amount": 700})
    assert res.status_code == 200, res.text
    rejected = tenant.post("/api/plant/expenses", json={"asset_id": m["id"], "category": "Other", "spent_on": day(-3), "description": "Doubtful", "amount": 999}).json()
    assert tenant.post("/api/plant/expenses/%d/decision" % rejected["id"], json={"decision": "reject", "remarks": "No voucher"}).status_code == 200
    raised = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Corrective", "description": "Hose"}).json()
    done = tenant.post("/api/plant/maintenance/%d/complete" % raised["id"], json={"work_performed": "Hose replaced", "parts_cost": 1200, "labour_cost": 300})
    assert done.status_code == 200, done.text
    cost = pnl(tenant, j)
    assert cost["equipment"] == 5000 + 700 + 1500
    assert cost["equipment_breakdown"] == {"fuel": 5000, "rental": 0, "hire": 0, "maintenance": 1500, "expenses": 700}
    assert cost["incurred"] >= cost["equipment"]
    assert pnl(tenant, other)["equipment"] == 0


def test_a_rental_invoice_is_counted_once_and_shared_by_hours(tenant):
    j1, j2 = job(tenant, "A"), job(tenant, "B")
    m, rid = hired_machine(tenant, j1)
    e, e2 = person(tenant), person(tenant)
    assert log(tenant, m, e, 0, 6, "2026-09-10").status_code == 200                  # the log works out hire of its own
    deploy(tenant, m, j2)
    assert log(tenant, m, e2, 6, 8, "2026-09-11").status_code == 200
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "H-1", "invoice_date": "2026-09-30", "period_from": "2026-09-01",
                                                                     "period_to": "2026-09-30", "amount": 80000}).status_code == 200
    a, b = pnl(tenant, j1), pnl(tenant, j2)
    assert a["equipment"] == 60000 and b["equipment"] == 20000                       # 6 hours and 2, of the bill only
    assert a["equipment_breakdown"]["hire"] == 0
    lines = tenant.get("/api/plant/project-costs?job_id=%d" % j1["id"]).json()["projects"][0]
    assert lines["duplicates_excluded"] > 0
    assert [x["source"] for x in lines["lines"]] == ["Rental invoice"] and lines["lines"][0]["ref"] == "H-1"


def test_a_rejected_log_costs_nothing_and_an_older_day_still_counts(tenant):
    j = job(tenant)
    m = machine(tenant)
    deploy(tenant, m, j)
    with main.SessionLocal() as db:
        cid = db.query(models.DBAsset).filter(models.DBAsset.id == m["id"]).first().client_id
        db.add(models.DBAssetLog(client_id=cid, asset_id=m["id"], job_id=j["id"], log_date=day(-9), hours_worked=8, fuel_litres=10, fuel_rate=100, fuel_cost=1000))
        db.add(models.DBAssetLog(client_id=cid, asset_id=m["id"], job_id=j["id"], log_date=day(-8), hours_worked=8, fuel_litres=20, fuel_rate=100, fuel_cost=2000, approval_status="Rejected"))
        db.add(models.DBAssetLog(client_id=cid, asset_id=m["id"], job_id=j["id"], log_date=day(-7), hours_worked=8, fuel_litres=30, fuel_rate=100, fuel_cost=3000))
        db.commit()
    fuel(tenant, m, day(-7), litres=30, rate=100)                                    # the same diesel in the register
    cost = pnl(tenant, j)
    assert cost["equipment"] == 1000 + 3000
    assert tenant.get("/api/plant/costs?asset_id=%d" % m["id"]).json()["machines"][0]["fuel"] == 4000   # the machine's view agrees


def test_an_approval_decision_or_a_new_bill_changes_the_project_at_once(tenant):
    j = job(tenant)
    m, rid = hired_machine(tenant, j)
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "H-2", "invoice_date": "2026-09-30", "amount": 45000}).status_code == 200
    assert pnl(tenant, j)["equipment"] == 45000
    spent = tenant.post("/api/plant/expenses", json={"asset_id": m["id"], "category": "Other", "spent_on": day(-1), "description": "Crane permit", "amount": 5000}).json()
    assert pnl(tenant, j)["equipment"] == 50000
    assert tenant.post("/api/plant/expenses/%d/decision" % spent["id"], json={"decision": "reject", "remarks": "Not ours"}).status_code == 200
    assert pnl(tenant, j)["equipment"] == 45000


# ---- 2. one logbook ------------------------------------------------------------------------------

def test_the_old_log_day_cannot_write(tenant):
    m = machine(tenant)
    deploy(tenant, m, job(tenant))
    assert tenant.post("/api/assets/%d/logs" % m["id"], json={"hours_worked": 8}).status_code == 410
    assert tenant.get("/api/plant/logs").json()["logs"] == []


def test_the_same_line_twice_is_refused_but_a_night_shift_is_not(tenant):
    m, e = machine(tenant), person(tenant)
    assert log(tenant, m, e, 100, 108, day(-2)).status_code == 200
    again = log(tenant, m, e, 100, 108, day(-2))
    assert again.status_code == 409
    other = person(tenant)
    night = log(tenant, m, other, 108, 111, day(-2), shift="Night", start_time="20:00", end_time="23:00", break_minutes=0)
    assert night.status_code == 200, night.text


def test_the_database_itself_refuses_a_repeat(tenant):
    m, e = machine(tenant), person(tenant)
    assert log(tenant, m, e, 100, 108, day(-2)).status_code == 200
    with main.SessionLocal() as db:
        row = db.query(models.DBAssetLog).filter(models.DBAssetLog.asset_id == m["id"]).first()
        db.add(models.DBAssetLog(client_id=row.client_id, asset_id=m["id"], log_date=row.log_date, shift="Day", employee_id=row.employee_id, day_key=row.day_key))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()


def test_a_rejected_day_can_be_entered_again(tenant):
    m, e = machine(tenant), person(tenant)
    lid = log(tenant, m, e, 100, 108, day(-2)).json()["id"]
    assert tenant.post("/api/plant/logs/%d/decision" % lid, json={"decision": "reject", "remarks": "Wrong machine"}).status_code == 200
    assert log(tenant, m, e, 100, 108, day(-2)).status_code == 200


def test_a_logbook_line_beside_an_older_log_day_is_refused_and_reported_not_removed(tenant):
    m, e = machine(tenant), person(tenant)
    with main.SessionLocal() as db:
        cid = db.query(models.DBAsset).filter(models.DBAsset.id == m["id"]).first().client_id
        db.add(models.DBAssetLog(client_id=cid, asset_id=m["id"], log_date=day(-5), hours_worked=8, operator="Old"))
        db.add(models.DBAssetLog(client_id=cid, asset_id=m["id"], log_date=day(-5), hours_worked=8, shift="Day", employee_id=e["id"], operator="New"))
        db.commit()
    assert log(tenant, m, e, 100, 108, day(-5)).status_code == 409
    days = tenant.get("/api/plant/logs/duplicates").json()["days"]
    assert len(days) == 1 and len(days[0]["entries"]) == 2
    assert len(tenant.get("/api/plant/logs?asset_id=%d" % m["id"]).json()["logs"]) == 2       # both still there


# ---- 3. the meter --------------------------------------------------------------------------------

def test_a_lower_reading_is_refused_without_a_replaced_meter(tenant):
    m, e = machine(tenant), person(tenant)
    assert log(tenant, m, e, 100, 108, day(-3)).status_code == 200
    res = log(tenant, m, e, 90, 95, day(-2))
    assert res.status_code == 400 and "108" in res.json()["detail"] and "Meter Replaced" in res.json()["detail"]
    assert tenant.get("/api/assets/%d" % m["id"]).json()["meter_reading"] == 108


def test_a_replaced_meter_needs_its_date_and_reason_and_is_on_the_record(tenant):
    m = machine(tenant, service_every=250, service_interval_type="Meter", last_service_meter=50, meter_reading=50)
    e = person(tenant)
    assert log(tenant, m, e, 100, 108, day(-3)).status_code == 200
    before = tenant.get("/api/assets/%d" % m["id"]).json()["service"]["schedule"]["next_meter"]
    assert log(tenant, m, e, 5, 13, day(-2), meter_replaced=True).status_code == 400
    assert log(tenant, m, e, 5, 13, day(-2), meter_replaced=True, replacement_date=day(-2)).status_code == 400
    res = log(tenant, m, e, 5, 13, day(-2), meter_replaced=True, replacement_date=day(-2), replacement_reason="Cluster failed")
    assert res.status_code == 200, res.text
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    assert got["meter_reading"] == 13
    assert got["service"]["schedule"]["next_meter"] == before - 103                # still as far off as it was
    hist = tenant.get("/api/plant/machines/%d/meter-history" % m["id"]).json()["history"]
    swap = [h for h in hist if h["type"] == "Meter replaced"][0]
    assert swap["opening"] == 108 and swap["closing"] == 5 and "Cluster failed" in swap["note"] and swap["by"]
    assert log(tenant, m, e, 13, 20, day(-1)).status_code == 200                   # and it carries on from the new meter


def test_days_without_a_reading_are_flagged_and_can_be_explained(tenant):
    m, e = machine(tenant), person(tenant)
    assert log(tenant, m, e, 100, 108, day(-6)).status_code == 200
    assert log(tenant, m, e, 120, 128, day(-2)).status_code == 200
    gaps = tenant.get("/api/plant/meter-gaps?asset_id=%d" % m["id"]).json()["gaps"]
    assert len(gaps) == 1 and gaps[0]["days_without_reading"] == 3 and gaps[0]["unlogged_meter"] == 12 and not gaps[0]["resolved"]
    g = {"asset_id": m["id"], "from_date": gaps[0]["from"], "to_date": gaps[0]["to"]}
    assert tenant.post("/api/plant/meter-gaps/resolve", json=dict(g, note="")).status_code == 400
    assert tenant.post("/api/plant/meter-gaps/resolve", json=dict(g, note="Stood at the yard")).status_code == 200
    assert tenant.get("/api/plant/meter-gaps?asset_id=%d" % m["id"]).json()["gaps"][0]["resolved"] is True


def test_correcting_a_reading_carries_through_everything_that_hangs_on_it(tenant):
    m, e = machine(tenant, fuel_norm_lph=10), person(tenant)
    lid = log(tenant, m, e, 100, 108, day(-3)).json()["id"]
    assert log(tenant, m, e, 108, 116, day(-2)).status_code == 200
    body = {"asset_id": m["id"], "employee_id": e["id"], "log_date": day(-3), "shift": "Day", "start_time": "07:00", "end_time": "19:00", "break_minutes": 60,
            "opening_meter": 100, "closing_meter": 110, "correction_reason": "Misread"}
    assert tenant.put("/api/plant/logs/%d" % lid, json=body).status_code == 200
    logs = sorted(tenant.get("/api/plant/logs?asset_id=%d" % m["id"]).json()["logs"], key=lambda l: l["log_date"])
    assert logs[0]["operating_hours"] == 10 and logs[1]["opening_meter"] == 110 and logs[1]["operating_hours"] == 6     # 16 hours still
    hist = tenant.get("/api/plant/machines/%d/meter-history" % m["id"]).json()["history"]
    fixed = [h for h in hist if h["type"] == "Reading corrected"]
    assert {(h["opening"], h["closing"]) for h in fixed} == {(108, 110)} and len(fixed) == 2 and all(h["by"] for h in fixed)


def test_correcting_the_last_reading_moves_the_machine_and_its_service(tenant):
    m = machine(tenant, service_every=100, service_interval_type="Meter", last_service_meter=0)
    e = person(tenant)
    lid = log(tenant, m, e, 92, 100, day(-2)).json()["id"]
    assert tenant.get("/api/assets/%d" % m["id"]).json()["service"]["due"] is True
    body = {"asset_id": m["id"], "employee_id": e["id"], "log_date": day(-2), "shift": "Day", "start_time": "07:00", "end_time": "19:00", "break_minutes": 60,
            "opening_meter": 52, "closing_meter": 60, "correction_reason": "Read the wrong machine"}
    assert tenant.put("/api/plant/logs/%d" % lid, json=body).status_code == 200
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    assert got["meter_reading"] == 60 and got["service"]["due"] is False


def test_only_those_who_approve_change_an_approved_reading(tenant, portal):
    m, e = machine(tenant), person(tenant)
    lid = log(tenant, m, e, 100, 108, day(-2)).json()["id"]
    assert tenant.post("/api/plant/logs/%d/decision" % lid, json={"decision": "approve"}).status_code == 200
    body = {"asset_id": m["id"], "employee_id": e["id"], "log_date": day(-2), "shift": "Day", "start_time": "07:00", "end_time": "19:00", "break_minutes": 60,
            "opening_meter": 100, "closing_meter": 106, "correction_reason": "Misread"}
    assert portal.put("/api/plant/logs/%d" % lid, json=body).status_code in (401, 403)


# ---- 4. alerts -----------------------------------------------------------------------------------

def _client_id(m):
    with main.SessionLocal() as db:
        return db.query(models.DBAsset).filter(models.DBAsset.id == m["id"]).first().client_id


def _weekly(cid, on=None):
    on = on or date.today()
    with main.SessionLocal() as db:
        return run_weekly_alerts(db, cid, on, on.strftime("%G-W%V"))


def test_a_machine_gets_one_summary_a_week_with_every_reason_in_it(tenant):
    j = job(tenant)
    m = machine(tenant, insurance_until=day(10), fitness_until=day(-2), service_every=100, service_interval_type="Meter", last_service_meter=0, meter_reading=120)
    deploy(tenant, m, j)
    with main.SessionLocal() as db:
        db.query(models.DBAssetMove).filter(models.DBAssetMove.asset_id == m["id"]).update({"moved_on": day(-5)})
        db.commit()
    cid = _client_id(m)
    assert _weekly(cid) == 1
    assert _weekly(cid) == 0                                                         # the same week: nothing more
    alerts = [a for a in tenant.get("/api/plant/alerts").json()["alerts"] if a["asset_id"] == m["id"]]
    assert len(alerts) == 1
    body = alerts[0]["body"]
    assert "Insurance expires" in body and "Fitness certificate expired" in body and "Service" in body and "no logbook entry" in body
    assert alerts[0]["delivery_status"] == "Delivered" and alerts[0]["severity"] == "danger"
    with main.SessionLocal() as db:
        assert db.query(models.DBAlert).filter(models.DBAlert.kind == "plant_weekly", models.DBAlert.ref_id == alerts[0]["id"]).count() == 1      # on the bell


def test_a_logged_machine_broken_down_or_with_nothing_due_is_left_alone(tenant):
    j = job(tenant)
    quiet = machine(tenant, name="Quiet")
    deploy(tenant, quiet, j)
    e = person(tenant)
    with main.SessionLocal() as db:
        db.query(models.DBAssetMove).filter(models.DBAssetMove.asset_id == quiet["id"]).update({"moved_on": day(-5)})
        db.commit()
    assert log(tenant, quiet, e, 100, 108, day(-1)).status_code == 200
    assert _weekly(_client_id(quiet)) == 0


def test_a_hired_machine_is_called_back_before_and_after_its_date(tenant):
    j = job(tenant)
    soon, _ = hired_machine(tenant, j, start_date=day(-20), expected_return=day(2))
    late, _ = hired_machine(tenant, None, start_date=day(-20), expected_return=day(-1))
    assert _weekly(_client_id(soon)) >= 2
    alerts = {a["asset_id"]: a for a in tenant.get("/api/plant/alerts").json()["alerts"]}
    assert "is due back" in alerts[soon["id"]]["body"] and "has not been returned" in alerts[late["id"]]["body"]


def test_an_emergency_is_announced_at_once_with_what_is_needed(tenant):
    j = job(tenant)
    m = machine(tenant)
    deploy(tenant, m, j)
    res = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Emergency", "priority": "Urgent", "description": "Boom cracked", "out_of_service": True})
    assert res.status_code == 200 and res.json()["alert_id"]
    a = tenant.get("/api/plant/alerts?kind=emergency").json()["alerts"][0]
    for bit in (m["name"], m["code"], j["name"], day(0), "Urgent"):
        assert bit in a["body"]
    assert a["delivery_status"] == "Delivered"


def test_the_scheduler_runs_each_job_once_a_period_and_alerts_can_be_closed(tenant):
    m = machine(tenant, insurance_until=day(5))
    now = datetime.now()
    first = [r for r in run_due_jobs(now, only="plant_weekly_alerts")]
    assert first[0]["status"] == "done"
    assert run_due_jobs(now, only="plant_weekly_alerts")[0]["status"] == "already_done"
    a = [x for x in tenant.get("/api/plant/alerts?kind=weekly").json()["alerts"] if x["asset_id"] == m["id"]][0]
    assert tenant.post("/api/plant/alerts/%d/review" % a["id"], json={"status": "Nonsense"}).status_code == 400
    assert tenant.post("/api/plant/alerts/%d/review" % a["id"], json={"status": "Resolved", "note": "Renewed"}).status_code == 200
    assert tenant.get("/api/plant/alerts?status=Resolved").json()["alerts"][0]["review_note"] == "Renewed"


def test_settings_change_how_early_papers_are_warned_of(tenant):
    m = machine(tenant, insurance_until=day(50))
    assert _weekly(_client_id(m)) == 0
    assert tenant.put("/api/plant/settings", json={"document_alert_days": 60}).status_code == 200
    assert _weekly(_client_id(m)) == 1
    assert tenant.put("/api/plant/settings", json={"document_alert_days": 0}).status_code == 400
    assert tenant.get("/api/plant/settings").json()["document_alert_days"] == 60


# ---- 5. fuel -------------------------------------------------------------------------------------

def test_machine_settings_are_kept_and_must_be_positive(tenant):
    m = machine(tenant, fuel_norm_lph=8.5, tank_capacity_l=120)
    got = tenant.get("/api/assets/%d" % m["id"]).json()
    assert got["fuel_norm_lph"] == 8.5 and got["tank_capacity_l"] == 120
    assert tenant.post("/api/assets", json={"name": "Bad", "fuel_norm_lph": -1}).status_code == 400
    assert tenant.post("/api/assets", json={"name": "Bad", "tank_capacity_l": -5}).status_code == 400


def _flags(tenant, m):
    return tenant.get("/api/plant/fuel-monitor?asset_id=%d" % m["id"]).json()


def test_fuel_above_the_norm_is_flagged_and_the_comparison_is_shown(tenant):
    m, e = machine(tenant, fuel_norm_lph=10, tank_capacity_l=500), person(tenant)
    assert log(tenant, m, e, 100, 108, day(-3)).status_code == 200
    fuel(tenant, m, day(-3), litres=40)
    fuel(tenant, m, day(-2), litres=150)                                             # 150 L on 8 hours: 18.75 L/h
    d = _flags(tenant, m)
    assert [f["reason"] for f in d["flags"]] == ["above_norm"] and d["flags"][0]["label"] == "Fuel Anomaly" and d["flags"][0]["status"] == "Open"
    row = d["machines"][0]
    assert row["operating_hours"] == 8 and row["litres"] == 190 and row["actual_lph"] == 23.75 and row["expected_litres"] == 80 and row["over_norm"] is True


def test_the_tolerance_is_adjustable(tenant):
    m, e = machine(tenant, fuel_norm_lph=10), person(tenant)
    assert log(tenant, m, e, 100, 108, day(-3)).status_code == 200
    fuel(tenant, m, day(-3), litres=40)
    fuel(tenant, m, day(-2), litres=100)                                             # 12.5 L/h is 25% over
    assert len(_flags(tenant, m)["flags"]) == 1
    assert tenant.put("/api/plant/settings", json={"fuel_tolerance_percent": 30}).status_code == 200
    assert _flags(tenant, m)["flags"] == []


def test_a_fill_bigger_than_the_tank_is_flagged_and_warned_of(tenant):
    m = machine(tenant, tank_capacity_l=100)
    res = fuel(tenant, m, day(-1), litres=130)
    assert "130" in res["warning"]
    f = _flags(tenant, m)["flags"]
    assert [x["reason"] for x in f] == ["over_tank"] and f[0]["label"] == "Requires Investigation"
    assert "theft" not in str(f).lower()


def test_a_fill_with_no_hours_since_the_last_is_flagged(tenant):
    m = machine(tenant, fuel_norm_lph=10)
    fuel(tenant, m, day(-5), litres=20)
    fuel(tenant, m, day(-2), litres=20)
    f = _flags(tenant, m)["flags"]
    assert [x["reason"] for x in f] == ["no_hours"] and f[0]["label"] == "Possible Fuel Misuse"


def test_a_rejected_log_gives_no_hours(tenant):
    m, e = machine(tenant), person(tenant)
    fuel(tenant, m, day(-5), litres=20)
    lid = log(tenant, m, e, 100, 108, day(-4)).json()["id"]
    fuel(tenant, m, day(-2), litres=20)
    assert _flags(tenant, m)["flags"] == []
    assert tenant.post("/api/plant/logs/%d/decision" % lid, json={"decision": "reject", "remarks": "No"}).status_code == 200
    assert len(_flags(tenant, m)["flags"]) == 1


def test_a_flag_is_reviewed_with_a_reason_and_it_stays_on_the_record(tenant, portal):
    m = machine(tenant, tank_capacity_l=100)
    fid = fuel(tenant, m, day(-1), litres=130)["fuel"]["id"]
    review = {"fuel_id": fid, "reason": "over_tank", "decision": "dismiss", "note": ""}
    assert tenant.post("/api/plant/fuel-flags/review", json=review).status_code == 400
    assert portal.post("/api/plant/fuel-flags/review", json=dict(review, note="x")).status_code in (401, 403)
    assert tenant.post("/api/plant/fuel-flags/review", json=dict(review, decision="investigate", note="Checking the voucher")).status_code == 200
    assert tenant.post("/api/plant/fuel-flags/review", json=dict(review, note="Two machines on one voucher")).status_code == 200
    f = _flags(tenant, m)["flags"][0]
    assert f["status"] == "Dismissed" and f["note"] == "Two machines on one voucher" and f["reviewed_by"]
    with main.SessionLocal() as db:
        assert db.query(models.DBAuditLog).filter(models.DBAuditLog.action == "plant.fuel.flag_reviewed", models.DBAuditLog.entity_id == fid).count() == 2


# ---- 6. rental bills -----------------------------------------------------------------------------

class Terms:
    def __init__(self, **k):
        self.start_date, self.actual_return, self.rate, self.billing = k.get("start_date", "2026-09-01"), k.get("actual_return", ""), k.get("rate", 0), k.get("billing", "Monthly")
        self.min_billable_hours, self.overtime_rate, self.transport_charges = k.get("minh", 0), k.get("ot", 0), k.get("transport", 0)


def test_expected_hire_follows_each_agreement():
    sept = ("2026-09-01", "2026-09-30")
    hours = {"2026-09-%02d" % d: 10.0 for d in range(1, 26)}                         # 250 hours
    monthly = expected_charge(Terms(rate=90000, minh=200, ot=1500), *sept, hours)
    assert monthly["expected"] == 90000 + 50 * 1500 and monthly["overtime_hours"] == 50 and monthly["actual_hours"] == 250
    short = expected_charge(Terms(rate=90000, minh=300, ot=1500), *sept, hours)
    assert short["expected"] == 90000 and short["overtime_hours"] == 0               # the minimum is paid however little it worked
    hourly = expected_charge(Terms(rate=1000, billing="Hourly", minh=300), *sept, hours)
    assert hourly["expected"] == 300000                                              # 250 worked, the minimum billed
    hourly_ot = expected_charge(Terms(rate=1000, billing="Hourly", minh=200, ot=1500), *sept, hours)
    assert hourly_ot["expected"] == 200000 + 50 * 1500
    daily = expected_charge(Terms(rate=6000, billing="Daily", minh=8, ot=800), *sept, hours)
    assert daily["expected"] == 30 * 6000 + 25 * 2 * 800 and daily["days_on_hire"] == 30
    weekly = expected_charge(Terms(rate=35000, billing="Weekly"), *sept, hours)
    assert weekly["expected"] == 150000


def test_part_months_arrival_return_and_transport_are_handled():
    hours = {}
    arrived = expected_charge(Terms(start_date="2026-09-16", rate=90000, transport=5000), "2026-09-01", "2026-09-30", hours)
    assert arrived["days_on_hire"] == 15 and arrived["expected"] == 45000 + 5000
    back = expected_charge(Terms(start_date="2026-08-01", actual_return="2026-09-10", rate=90000), "2026-09-01", "2026-09-30", hours)
    assert back["days_on_hire"] == 10 and back["expected"] == 30000 and back["transport"] == 0
    gone = expected_charge(Terms(start_date="2026-08-01", actual_return="2026-08-20", rate=90000), "2026-09-01", "2026-09-30", hours)
    assert gone["expected"] == 0


def test_a_bill_is_set_beside_its_agreement_without_being_changed(tenant):
    j = job(tenant)
    m, rid = hired_machine(tenant, j, rate=90000, min_billable_hours=0, overtime_rate=0)
    inv = {"invoice_date": "2026-09-30", "period_from": "2026-09-01", "period_to": "2026-09-30"}
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json=dict(inv, invoice_no="OK-1", amount=90500)).status_code == 200
    rows = tenant.get("/api/plant/rental-verification?month=2026-09&rental_id=%d" % rid).json()["rows"]
    assert len(rows) == 1 and rows[0]["status"] == "Matched" and rows[0]["expected"] == 90000 and rows[0]["actual"] == 90500 and rows[0]["difference"] == 500
    for key in ("code", "supplier", "project", "month", "min_billable_hours", "actual_hours", "overtime_hours", "rate", "overtime_rate"):
        assert key in rows[0]


def test_a_bill_off_the_agreement_is_flagged_and_finance_decides(tenant, portal):
    m, rid = hired_machine(tenant, job(tenant), rate=90000, min_billable_hours=0, overtime_rate=0)
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "BAD-1", "invoice_date": "2026-09-30", "period_from": "2026-09-01", "period_to": "2026-09-30", "amount": 120000}).status_code == 200
    row = tenant.get("/api/plant/rental-verification?month=2026-09&rental_id=%d" % rid).json()["rows"][0]
    assert row["status"] == "Mismatch" and row["difference"] == 30000
    url = "/api/plant/rental-invoices/%d/verify" % row["invoice_id"]
    assert portal.post(url, json={"decision": "approve"}).status_code in (401, 403)
    assert tenant.post(url, json={"decision": "dispute"}).status_code == 400
    assert tenant.post(url, json={"decision": "dispute", "note": "Rate is 90,000"}).status_code == 200
    row = tenant.get("/api/plant/rental-verification?month=2026-09&rental_id=%d" % rid).json()["rows"][0]
    assert row["verification_status"] == "Disputed" and row["actual"] == 120000 and row["expected_at_review"] == 90000


def test_a_second_bill_for_the_same_days_is_called_a_duplicate(tenant):
    m, rid = hired_machine(tenant, job(tenant), rate=90000, min_billable_hours=0, overtime_rate=0)
    for no in ("D-1", "D-2"):
        assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": no, "invoice_date": "2026-09-30", "period_from": "2026-09-01", "period_to": "2026-09-30", "amount": 90000}).status_code == 200
    rows = tenant.get("/api/plant/rental-verification?month=2026-09&rental_id=%d" % rid).json()["rows"]
    assert sorted(r["status"] for r in rows) == ["Duplicate", "Matched"]


# ---- 7. months with no bill ----------------------------------------------------------------------

def test_a_month_with_no_bill_is_alerted_once_and_a_part_billed_month_too(tenant):
    j = job(tenant)
    m, rid = hired_machine(tenant, j, rate=90000, min_billable_hours=0, overtime_rate=0, start_date="2026-08-01", expected_return="2026-09-30")
    assert tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": "2026-09-30"}).status_code == 200
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "PART", "invoice_date": "2026-09-15", "period_from": "2026-09-01", "period_to": "2026-09-15", "amount": 45000}).status_code == 200
    cid = _client_id(m)
    on = date(2026, 10, 2)
    with main.SessionLocal() as db:
        assert run_unbilled_alerts(db, cid, on) == 2
        assert run_unbilled_alerts(db, cid, on) == 0
    alerts = {a["period"]: a for a in tenant.get("/api/plant/alerts?kind=unbilled").json()["alerts"]}
    assert set(alerts) == {"2026-08", "2026-09"}
    assert "Expected rental: 90000" in alerts["2026-08"]["body"] and m["code"] in alerts["2026-08"]["body"] and "Sai Cranes" in alerts["2026-08"]["body"]
    status = {r["month"]: r["status"] for r in tenant.get("/api/plant/rental-verification?rental_id=%d" % rid).json()["rows"] if r["kind"] == "missing"}
    assert status == {"2026-08": "Missing", "2026-09": "Incomplete"}


def test_a_month_still_running_is_not_called_unbilled(tenant):
    m, rid = hired_machine(tenant, job(tenant), start_date=day(0)[:8] + "01", expected_return=day(60))
    with main.SessionLocal() as db:
        assert run_unbilled_alerts(db, _client_id(m), date.today()) == 0


def test_the_monthly_job_runs_once_a_month(tenant):
    now = datetime.now()
    assert run_due_jobs(now, only="plant_unbilled_rentals")[0]["status"] == "done"
    assert run_due_jobs(now, only="plant_unbilled_rentals")[0]["status"] == "already_done"


def test_the_project_view_and_the_machine_view_come_to_the_same_money(tenant):
    j = job(tenant)
    e = person(tenant)
    m, rid = hired_machine(tenant, j)
    owned = machine(tenant, name="Owned")
    deploy(tenant, owned, j)
    assert log(tenant, m, e, 0, 6, "2026-09-10").status_code == 200
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "R-1", "invoice_date": "2026-09-30", "amount": 80000}).status_code == 200
    fuel(tenant, owned, day(-2), litres=50)
    assert tenant.post("/api/plant/expenses", json={"asset_id": owned["id"], "category": "Other", "spent_on": day(-1), "description": "Permit", "amount": 700}).status_code == 200
    by_project = sum(p["total"] for p in tenant.get("/api/plant/project-costs").json()["projects"])
    by_machine = tenant.get("/api/plant/costs").json()["totals"]["operating_hours"] and sum(x["total"] for x in tenant.get("/api/plant/costs").json()["machines"])
    assert by_project == by_machine == 80000 + 4500 + 700
