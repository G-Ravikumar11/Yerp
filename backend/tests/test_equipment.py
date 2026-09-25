"""Equipment: where each machine is, what it did, what it burned, when it is
due - and what it cost the project it worked for."""
from datetime import date, timedelta


def job(tenant, name="Vizag STP"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()


def machine(tenant, **over):
    body = {"name": "JCB 3DX backhoe", "category": "Earthmoving", "ownership": "Owned",
            "meter_unit": "Hours", "meter_reading": 1200, "service_every": 250}
    body.update(over)
    res = tenant.post("/api/assets", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def deploy(tenant, asset, j):
    res = tenant.post("/api/assets/%d/move" % asset["id"], json={"to_job_id": j["id"]})
    assert res.status_code == 200, res.text
    return res.json()["asset"]


def log(tenant, asset, **body):
    return tenant.post("/api/assets/%d/logs" % asset["id"], json=body)


def test_a_machine_is_numbered_and_starts_in_the_yard(tenant):
    a = machine(tenant)
    assert a["code"] == "EQP-0001" and a["status"] == "Available"
    assert a["current_job"] == ""


def test_a_hired_machine_needs_its_rate(tenant):
    res = tenant.post("/api/assets", json={"name": "Tower crane", "ownership": "Hired"})
    assert res.status_code == 400 and "hire rate" in res.json()["detail"]


def test_deploying_puts_it_on_the_site(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    assert a["status"] == "Deployed" and a["current_job_id"] == j["id"]


def test_it_moves_between_sites_and_back(tenant):
    a = machine(tenant)
    j1, j2 = job(tenant, "Site A"), job(tenant, "Site B")
    deploy(tenant, a, j1)
    deploy(tenant, a, j2)
    back = tenant.post("/api/assets/%d/move" % a["id"], json={}).json()["asset"]
    assert back["status"] == "Available"
    moves = tenant.get("/api/assets/%d" % a["id"]).json()["moves"]
    assert [m["to"] for m in moves][::-1] == ["%s %s" % (j1["number"], j1["name"]),
                                              "%s %s" % (j2["number"], j2["name"]), "Yard"]


def test_a_machine_in_the_yard_cannot_log_a_day(tenant):
    res = log(tenant, machine(tenant), hours_worked=8)
    assert res.status_code == 409 and "Deploy it" in res.json()["detail"]


def test_a_day_costs_its_diesel(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    res = log(tenant, a, hours_worked=8, idle_hours=1, fuel_litres=60, fuel_rate=92.5,
              operator="Ramesh", work_done="Excavation, zone B")
    assert res.status_code == 200, res.text
    assert res.json()["cost"] == 60 * 92.5
    got = tenant.get("/api/assets/%d" % a["id"]).json()
    assert got["meter_reading"] == 1208           # the meter moves with the hours
    assert got["litres_per_hour"] == 7.5
    assert got["utilisation_percent"] == round(8 / 9 * 100, 1)


def test_a_hired_machine_costs_its_hire_on_its_terms(tenant):
    j = job(tenant)
    by_hour = deploy(tenant, machine(tenant, name="Hydra", ownership="Hired", hire_rate=1500,
                                     hire_basis="Hour"), j)
    by_day = deploy(tenant, machine(tenant, name="Mixer", ownership="Hired", hire_rate=6000,
                                    hire_basis="Day"), j)
    by_month = deploy(tenant, machine(tenant, name="Crane", ownership="Hired", hire_rate=260000,
                                      hire_basis="Month"), j)
    assert log(tenant, by_hour, hours_worked=6).json()["cost"] == 9000
    assert log(tenant, by_day, hours_worked=3).json()["cost"] == 6000
    assert log(tenant, by_month, hours_worked=8).json()["cost"] == 10000   # 2,60,000 / 26


def test_one_log_per_machine_per_day(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    log(tenant, a, hours_worked=8, log_date="2026-09-01")
    assert log(tenant, a, hours_worked=2, log_date="2026-09-01").status_code == 409


def test_the_meter_does_not_run_backwards(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    res = log(tenant, a, hours_worked=8, meter_reading=1100)
    assert res.status_code == 400 and "backwards" in res.json()["detail"]


def test_more_than_a_day_is_refused(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    assert log(tenant, a, hours_worked=20, idle_hours=6).status_code == 400


# --- Maintenance --------------------------------------------------------------------

def test_a_service_falls_due_on_the_meter(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant, meter_reading=1200, service_every=250), j)
    log(tenant, a, hours_worked=10, meter_reading=1440, log_date="2026-09-01")
    soon = tenant.get("/api/assets/%d" % a["id"]).json()["service"]
    assert soon["soon"] is True
    log(tenant, a, hours_worked=10, meter_reading=1460, log_date="2026-09-02")
    due = tenant.get("/api/assets/%d" % a["id"]).json()["service"]
    assert due["due"] is True and "past its service" in due["reasons"][0]
    assert tenant.get("/api/assets").json()["summary"]["service_due"] == 1


def test_a_service_resets_the_clock(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant, meter_reading=1500, service_every=250,
                               last_service_meter=1200), j)
    assert tenant.get("/api/assets/%d" % a["id"]).json()["service"]["due"] is True
    res = tenant.post("/api/assets/%d/services" % a["id"], json={
        "kind": "Preventive", "description": "250-hour service", "parts_cost": 8500,
        "labour_cost": 1500})
    assert res.status_code == 200
    got = tenant.get("/api/assets/%d" % a["id"]).json()
    assert got["service"]["due"] is False and got["last_service_meter"] == 1500
    assert got["services"][0]["total_cost"] == 10000


def test_a_service_falls_due_on_the_calendar(tenant):
    old = (date.today() - timedelta(days=100)).isoformat()
    a = machine(tenant, service_every=0, service_every_days=90, last_service_on=old)
    assert tenant.get("/api/assets/%d" % a["id"]).json()["service"]["due"] is True


def test_lapsed_insurance_is_called_out(tenant):
    a = machine(tenant, insurance_until=(date.today() - timedelta(days=3)).isoformat())
    s = tenant.get("/api/assets/%d" % a["id"]).json()["service"]
    assert s["due"] is True and "insurance lapsed" in s["reasons"][0]


def test_a_breakdown_takes_it_off_work_until_it_is_back(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    tenant.post("/api/assets/%d/services" % a["id"], json={
        "kind": "Breakdown", "description": "Hydraulic hose burst", "parts_cost": 4200,
        "out_of_service": True})
    assert tenant.get("/api/assets/%d" % a["id"]).json()["status"] == "Under repair"
    assert log(tenant, a, hours_worked=4).status_code == 409
    tenant.post("/api/assets/%d/back-in-service" % a["id"])
    assert tenant.get("/api/assets/%d" % a["id"]).json()["status"] == "Deployed"


# --- Where the money goes ----------------------------------------------------------

def test_what_a_machine_costs_lands_on_the_project(tenant):
    """Diesel, hire and repairs are a project cost, and the P&L said nothing
    about them."""
    j = job(tenant)
    owned = deploy(tenant, machine(tenant), j)
    hired = deploy(tenant, machine(tenant, name="Transit mixer", ownership="Hired",
                                   hire_rate=6000, hire_basis="Day"), j)
    log(tenant, owned, hours_worked=8, fuel_litres=60, fuel_rate=90)        # 5,400
    log(tenant, hired, hours_worked=6, fuel_litres=40, fuel_rate=90)        # 3,600 + 6,000
    tenant.post("/api/assets/%d/services" % owned["id"], json={
        "kind": "Repair", "parts_cost": 2000})                                # 2,000
    pnl = tenant.get("/api/jobs/%d/pnl" % j["id"]).json()
    assert pnl["cost"]["equipment"] == 5400 + 3600 + 6000 + 2000
    assert pnl["cost"]["incurred"] >= pnl["cost"]["equipment"]
    site = tenant.get("/api/jobs/%d/equipment" % j["id"]).json()
    assert site["total"] == 17000


def test_the_portfolio_counts_it_too(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    log(tenant, a, hours_worked=8, fuel_litres=10, fuel_rate=100)
    rows = tenant.get("/api/jobs-pnl").json()["projects"]
    row = [r for r in rows if r["job_id"] == j["id"]][0]
    assert row["incurred"] >= 1000


def test_cost_follows_the_site_it_was_earned_on(tenant):
    """A machine moved between sites charges each for its own days."""
    a = machine(tenant)
    j1, j2 = job(tenant, "A"), job(tenant, "B")
    deploy(tenant, a, j1)
    log(tenant, a, hours_worked=8, fuel_litres=10, fuel_rate=100, log_date="2026-09-01")
    deploy(tenant, a, j2)
    log(tenant, a, hours_worked=8, fuel_litres=20, fuel_rate=100, log_date="2026-09-02")
    assert tenant.get("/api/jobs/%d/pnl" % j1["id"]).json()["cost"]["equipment"] == 1000
    assert tenant.get("/api/jobs/%d/pnl" % j2["id"]).json()["cost"]["equipment"] == 2000


def test_a_machine_on_site_cannot_be_disposed(tenant):
    j = job(tenant)
    a = deploy(tenant, machine(tenant), j)
    assert tenant.post("/api/assets/%d/dispose" % a["id"], json={"reason": "sold"}).status_code == 409


def test_another_tenant_sees_none_of_it(tenant, second_tenant):
    a = machine(tenant)
    assert second_tenant.get("/api/assets").json()["assets"] == []
    assert second_tenant.get("/api/assets/%d" % a["id"]).status_code == 404


def test_a_machine_brought_in_overdue_shows_as_overdue(tenant):
    a = machine(tenant, meter_reading=1200, service_every=250, last_service_meter=900)
    assert a["service"]["due"] is True


def test_correcting_the_last_service_is_kept(tenant):
    a = machine(tenant)
    body = {"name": a["name"], "ownership": "Owned", "meter_unit": "Hours",
            "service_every": 250, "last_service_on": "2026-08-01", "last_service_meter": 1100}
    res = tenant.put("/api/assets/%d" % a["id"], json=body)
    assert res.status_code == 200, res.text
    got = tenant.get("/api/assets/%d" % a["id"]).json()
    got = got.get("asset", got)
    assert got["last_service_on"] == "2026-08-01" and got["last_service_meter"] == 1100
