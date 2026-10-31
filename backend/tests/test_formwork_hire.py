"""Shuttering and scaffolding hire: charged by the day, a return at a time, with a lost piece charged once at its replacement cost."""
from datetime import date, timedelta

import pytest

import main
from app import models
from app.routers.formwork_hire import billable_days, hire_state


def day(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def _fresh():
    main.rate_limiter._hits.clear()


def job(tenant, name="Tower A"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()


def supplier(tenant, name="Sri Formwork"):
    return tenant.post("/api/plant/rental-providers", json={"name": name}).json()["provider"]


def hire(tenant, j, p, **over):
    body = {"job_id": j["id"], "kind": "Shuttering", "provider_id": p["id"], "description": "Steel plates 600x1200", "quantity": 100, "uom": "Sqm",
            "start_date": day(-9), "expected_return": day(30), "daily_rate": 5, "replacement_cost": 400}
    body.update(over)
    res = tenant.post("/api/plant/formwork", json=body)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def give_back(tenant, hid, key="r1", **over):
    body = {"return_key": key, "returned_on": day(0), "returned_qty": 0, "damaged_qty": 0, "lost_qty": 0}
    body.update(over)
    return tenant.post("/api/plant/formwork/%d/returns" % hid, json=body)


def row(tenant, hid):
    return [h for h in tenant.get("/api/plant/formwork").json()["hires"] if h["id"] == hid][0]


def test_total_hire_is_quantity_by_rate_by_billable_days(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    res = give_back(tenant, h, returned_qty=100)
    assert res.status_code == 200, res.text
    assert res.json()["billable_days"] == 10 and res.json()["hire_charge"] == 100 * 5 * 10
    r = row(tenant, h)
    assert r["status"] == "Fully returned" and r["total_hire"] == 5000 and r["out"] == 0 and r["accrued"] == 0 and r["actual_return"] == day(0)


def test_the_billing_rule_is_the_company_s():
    assert billable_days("2026-10-01", "2026-10-10", "inclusive") == 10
    assert billable_days("2026-10-01", "2026-10-10", "exclusive") == 9
    assert billable_days("2026-10-01", "2026-10-01", "exclusive") == 1


def test_setting_the_rule_changes_the_days(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    with main.SessionLocal() as db:
        cid = db.query(models.DBFormworkHire).get(h).client_id
        db.add(models.DBSettings(client_id=cid, key="formwork_billing_days", value="exclusive"))
        db.commit()
    assert give_back(tenant, h, returned_qty=100).json()["billable_days"] == 9


def test_a_partial_return_charges_what_went_back_and_the_rest_keeps_running(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    assert give_back(tenant, h, "a", returned_qty=40, returned_on=day(-5)).json()["hire_charge"] == 40 * 5 * 5
    r = row(tenant, h)
    assert r["status"] == "Partially returned" and r["out"] == 60 and r["hire_charged"] == 1000
    assert r["accrued"] == 60 * 5 * 10 and r["total_hire"] == 4000
    assert give_back(tenant, h, "b", returned_qty=60).json()["hire_charge"] == 3000
    assert row(tenant, h)["total_hire"] == 4000


def test_more_than_is_out_and_the_same_form_twice_are_refused(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    assert give_back(tenant, h, "a", returned_qty=80).status_code == 200
    assert give_back(tenant, h, "a", returned_qty=10).status_code == 409                 # the same form again
    res = give_back(tenant, h, "b", returned_qty=21)
    assert res.status_code == 409 and "20" in res.json()["detail"]
    assert give_back(tenant, h, "c", returned_qty=0).status_code == 400
    assert give_back(tenant, h, "d", returned_qty=-1).status_code == 400
    assert give_back(tenant, h, "e", returned_qty=1, returned_on=day(-20)).status_code == 400
    assert give_back(tenant, h, "f", returned_qty=1, returned_on=day(1)).status_code == 400
    assert row(tenant, h)["out"] == 20


def test_a_lost_piece_is_charged_its_replacement_cost_once_not_the_day_rate(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    res = give_back(tenant, h, "a", returned_qty=90, lost_qty=10).json()
    assert res["loss_charge"] == 10 * 400 and res["hire_charge"] == 100 * 5 * 10
    r = row(tenant, h)
    assert r["lost"] == 10 and r["loss_charge"] == 4000 and r["payable"] == 9000
    assert give_back(tenant, h, "b", lost_qty=1).status_code == 409                      # nothing left to lose twice
    assert row(tenant, h)["loss_charge"] == 4000


def test_damage_is_kept_apart_from_loss(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    assert give_back(tenant, h, "a", returned_qty=95, damage_charge=50).status_code == 400
    r = give_back(tenant, h, "b", returned_qty=95, damaged_qty=5, damage_charge=750).json()
    assert r["damage_charge"] == 750 and r["loss_charge"] == 0
    s = row(tenant, h)
    assert s["damaged"] == 5 and s["payable"] == 5000 + 750


def test_overdue_on_hire_and_payments(tenant):
    j, p = job(tenant), supplier(tenant)
    late = hire(tenant, j, p, expected_return=day(-1))
    fresh = hire(tenant, j, p)
    data = tenant.get("/api/plant/formwork").json()
    assert data["counts"]["Overdue"] == 1 and data["counts"]["On hire"] == 1
    assert row(tenant, late)["status"] == "Overdue" and row(tenant, fresh)["status"] == "On hire"
    give_back(tenant, fresh, returned_qty=100)
    assert tenant.post("/api/plant/formwork/%d/payments" % fresh, json={"amount": 2000, "reference": "UTR1"}).status_code == 200
    r = row(tenant, fresh)
    assert r["paid"] == 2000 and r["balance"] == 3000 and r["payments"][0]["reference"] == "UTR1"


def test_terms_stop_changing_at_the_first_return(tenant):
    j, p = job(tenant), supplier(tenant)
    h = hire(tenant, j, p)
    body = {"job_id": j["id"], "kind": "Scaffolding", "provider_id": p["id"], "description": "Cuplock", "quantity": 50, "uom": "Nos", "start_date": day(-9), "daily_rate": 3}
    assert tenant.put("/api/plant/formwork/%d" % h, json=body).status_code == 200
    give_back(tenant, h, returned_qty=1)
    assert tenant.put("/api/plant/formwork/%d" % h, json=body).status_code == 409


def test_bad_hires_are_refused(tenant):
    j, p = job(tenant), supplier(tenant)
    base = {"job_id": j["id"], "kind": "Shuttering", "provider_id": p["id"], "description": "Plates", "quantity": 1, "uom": "Sqm", "start_date": day(-1), "daily_rate": 1}
    for bad in ({"kind": "Cranes"}, {"quantity": 0}, {"daily_rate": 0}, {"replacement_cost": -1}, {"description": " "}, {"job_id": 99999}, {"provider_id": 99999},
                {"expected_return": day(-5)}, {"start_date": "soon"}):
        assert tenant.post("/api/plant/formwork", json={**base, **bad}).status_code == 400, bad


def test_reports_are_by_project_and_vendor(tenant):
    a, b = job(tenant, "A"), job(tenant, "B")
    p, q = supplier(tenant), supplier(tenant, "Om Scaffolds")
    h1 = hire(tenant, a, p)
    hire(tenant, a, q, kind="Scaffolding", quantity=30, uom="Nos", daily_rate=2)
    h3 = hire(tenant, b, p, quantity=10)
    give_back(tenant, h1, "x", returned_qty=90, lost_qty=10)
    give_back(tenant, h3, "y", returned_qty=10)
    rep = tenant.get("/api/plant/formwork-report").json()
    by = {r["job_id"]: r for r in rep["projects"]}
    assert by[a["id"]]["shuttering_qty"] == 100 and by[a["id"]]["scaffolding_qty"] == 30 and by[a["id"]]["outstanding_qty"] == 30 and by[a["id"]]["daily_rental"] == 60
    assert by[a["id"]]["total_cost"] == 5000 + 4000 + 30 * 2 * 10 and by[b["id"]]["total_cost"] == 500
    assert {v["supplier"] for v in rep["vendors"]} == {"Sri Formwork", "Om Scaffolds"}
    assert rep["lost_damaged"][0]["loss_charge"] == 4000
    assert tenant.get("/api/plant/formwork-report.xlsx").status_code == 200


def test_the_project_pays_for_it_once(tenant):
    j = job(tenant)
    h = hire(tenant, j, supplier(tenant))
    give_back(tenant, h, "a", returned_qty=50, lost_qty=10, returned_on=day(-4))           # 60 x 5 x 6 = 1,800, loss 4,000
    cost = tenant.get("/api/jobs/%d/pnl" % j["id"]).json()["cost"]
    assert cost["equipment"] == 5800 and cost["equipment_breakdown"]["hire"] == 5800
    line = tenant.get("/api/plant/project-costs?job_id=%d" % j["id"]).json()["projects"][0]
    assert line["unbilled_hire_estimate"] == 40 * 5 * 10
    assert {x["source"] for x in line["lines"]} == {"Shuttering hire"}


def test_permissions_and_other_companies(tenant, second_tenant, portal):
    j, p = job(tenant), supplier(tenant)
    h = hire(tenant, j, p)
    assert portal.post("/api/plant/formwork/%d/returns" % h, json={"return_key": "z", "returned_qty": 1}).status_code in (401, 403)
    assert second_tenant.post("/api/plant/formwork/%d/returns" % h, json={"return_key": "z", "returned_qty": 1}).status_code == 404
    assert second_tenant.get("/api/plant/formwork").json()["hires"] == []


def test_state_needs_no_database():
    class H:
        quantity, daily_rate, start_date, expected_return = 10, 2, "2026-01-01", "2026-01-05"
    s = hire_state(H, [], [], "inclusive", on="2026-01-10")
    assert s["status"] == "Overdue" and s["accrued"] == 200


def test_the_charges_can_be_seen_first_and_nothing_is_saved(tenant):
    h = hire(tenant, job(tenant), supplier(tenant))
    res = give_back(tenant, h, "p", returned_qty=90, lost_qty=10, preview=True).json()
    assert res["payable"] == 5000 + 4000 and res["billable_days"] == 10
    assert row(tenant, h)["out"] == 100
    assert give_back(tenant, h, "p", returned_qty=90, lost_qty=10).json()["payable"] == 9000      # the same form, now saved
