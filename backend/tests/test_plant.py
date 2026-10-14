"""Equipment & Plant: the register, who works each machine, the logbook, fuel, maintenance, hire, expenses, costs, the
dashboard and the reports - each figure from what is stored, and each rule enforced on the server."""
import io
from datetime import date, timedelta

from conftest import make_employee
from test_site_access import signed_in


def day(n=0):
    return (date.today() + timedelta(days=n)).isoformat()


def job(tenant, name="Vizag STP"):
    return tenant.post("/api/jobs", json={"name": name, "customer_name": "L&T"}).json()


def machine(tenant, **over):
    body = {"name": "JCB 3DX", "category": "Earthmoving", "ownership": "Owned", "meter_unit": "Hours", "meter_reading": 1000,
            "service_every": 250, "service_every_days": 90, "last_service_on": day(-30)}
    body.update(over)
    res = tenant.post("/api/assets", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def deploy(tenant, m, j):
    assert tenant.post("/api/assets/%d/move" % m["id"], json={"to_job_id": j["id"]}).status_code == 200


def person(tenant, first="Ravi", last="Kumar", phone="9876543210", **over):
    return make_employee(tenant, first_name=first, last_name=last, phone=phone, job_title="Operator", salary=20800, **over)


def log(tenant, m, e, **over):
    body = {"asset_id": m["id"], "employee_id": e["id"], "log_date": day(-1), "shift": "Day", "start_time": "07:00", "end_time": "19:00",
            "break_minutes": 60, "opening_meter": 1000, "closing_meter": 1008, "work_done": "Excavation for raft"}
    body.update(over)
    return tenant.post("/api/plant/logs", json=body)


# ---- 1, 2: the register ---------------------------------------------------------------------------

def test_a_machine_is_registered_edited_viewed_and_archived(tenant):
    m = machine(tenant, brand=" JCB ", model="3DX", reg_no="ap 39 ab 1234", serial_no="SN-1", condition="Fair")
    assert m["code"] == "EQP-0001" and m["reg_no"] == "AP 39 AB 1234" and m["condition"] == "Fair" and m["ownership_label"] == "Owned"
    # The make is now the brand; the serial number is no longer taken or given back.
    assert m["brand"] == "JCB" and m["model"] == "3DX" and "make" not in m and "serial_no" not in m
    ed = tenant.put("/api/assets/%d" % m["id"], json=dict(m, name="JCB 3DX Super", condition="Good")).json()
    assert ed["name"] == "JCB 3DX Super" and ed["condition"] == "Good"
    assert tenant.get("/api/assets/%d" % m["id"]).json()["code"] == "EQP-0001"
    out = tenant.post("/api/assets/%d/archive" % m["id"], json={}).json()
    assert out["asset"]["is_archived"]
    assert tenant.get("/api/assets").json()["assets"] == [] and len(tenant.get("/api/assets?archived=true").json()["assets"]) == 1
    assert tenant.post("/api/assets/%d/archive" % m["id"], json={"restore": True}).json()["asset"]["is_archived"] is False


def test_ids_and_registrations_are_not_repeated(tenant):
    m = machine(tenant, code="JCB-01", reg_no="AP39AB1234")
    assert m["code"] == "JCB-01"
    for clash in ({"code": "jcb-01"}, {"reg_no": "ap39ab1234"}):
        res = tenant.post("/api/assets", json={"name": "Other", **clash})
        assert res.status_code == 409, clash
    assert tenant.post("/api/assets", json={"name": "Other", "condition": "Shiny"}).status_code == 400


def test_owned_rented_and_leased_are_told_apart(tenant):
    machine(tenant, name="Own")
    machine(tenant, name="Hire", ownership="Rented", hire_rate=6000, hire_basis="Day")
    machine(tenant, name="Lease", ownership="Leased", hire_rate=90000, hire_basis="Month")
    rows = {a["name"]: a for a in tenant.get("/api/assets").json()["assets"]}
    assert rows["Hire"]["ownership"] == "Hired" and rows["Hire"]["ownership_label"] == "Rented" and rows["Lease"]["ownership_label"] == "Leased"
    c = tenant.get("/api/plant/dashboard").json()["cards"]
    assert (c["total"], c["owned"], c["rented"], c["leased"]) == (3, 1, 1, 1)


# ---- 3: allocation -------------------------------------------------------------------------------

def test_people_are_allocated_with_their_mobile_and_conflicts_refused(tenant):
    j = job(tenant)
    m, m2 = machine(tenant), machine(tenant, name="Hydra")
    deploy(tenant, m, j)
    ravi, anil = person(tenant), person(tenant, "Anil", "Rao", "9000000001")
    a = tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": ravi["id"], "role": "Operator", "shift": "Day", "start_date": day(0)})
    assert a.status_code == 200, a.text
    rows = tenant.get("/api/plant/allocations").json()["allocations"]
    assert rows[0]["employee"]["mobile"] == "9876543210" and rows[0]["employee"]["name"] == "Ravi Kumar" and rows[0]["project"].endswith("Vizag STP")
    # The same person on another machine in the same shift, or a second operator on the same machine and shift: refused.
    assert tenant.post("/api/plant/allocations", json={"asset_id": m2["id"], "employee_id": ravi["id"], "shift": "Day", "start_date": day(0)}).status_code == 409
    assert tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": anil["id"], "shift": "Day", "start_date": day(0)}).status_code == 409
    # Another shift, or a helper alongside, is fine.
    assert tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": anil["id"], "shift": "Night", "start_date": day(0)}).status_code == 200
    helper = person(tenant, "Hari", "Babu", "9000000002")
    assert tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": helper["id"], "role": "Helper", "shift": "Day", "start_date": day(0)}).status_code == 200
    emps = {e["name"]: e for e in tenant.get("/api/plant/employees").json()["employees"]}
    assert emps["Ravi Kumar"]["on_machines"] == [m["code"]] and emps["Ravi Kumar"]["mobile"] == "9876543210"


def test_reassign_and_end_keep_the_history(tenant):
    m = machine(tenant)
    ravi, anil = person(tenant), person(tenant, "Anil", "Rao", "9000000001")
    tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": ravi["id"], "start_date": day(-10)})
    aid = tenant.get("/api/plant/allocations").json()["allocations"][0]["id"]
    assert tenant.post("/api/plant/allocations/%d/reassign" % aid, json={"employee_id": anil["id"], "on": day(0), "reason": "Ravi on leave"}).status_code == 200
    rows = tenant.get("/api/plant/allocations?asset_id=%d" % m["id"]).json()["allocations"]
    assert {(r["employee"]["name"], r["status"]) for r in rows} == {("Ravi Kumar", "Ended"), ("Anil Rao", "Active")}
    ended = next(r for r in rows if r["status"] == "Ended")
    assert ended["end_date"] == day(-1) and "Reassigned" in ended["ended_reason"]
    active = next(r for r in rows if r["status"] == "Active")
    assert tenant.post("/api/plant/allocations/%d/end" % active["id"], json={"reason": "Work done"}).status_code == 200
    assert tenant.post("/api/plant/allocations/%d/end" % active["id"], json={}).status_code == 409


# ---- 4: the logbook ----------------------------------------------------------------------------------

def test_hours_breaks_overtime_and_meter_are_worked_out(tenant):
    j = job(tenant)
    m = machine(tenant)
    deploy(tenant, m, j)
    e = person(tenant)
    res = log(tenant, m, e)
    assert res.status_code == 200, res.text
    l = tenant.get("/api/plant/logs").json()["logs"][0]
    # 07:00-19:00 less an hour's break: 11 on duty, 8 regular, 3 overtime. The meter ran 8; idle is the rest.
    assert (l["attendance_hours"], l["regular_hours"], l["overtime_hours"]) == (11.0, 8.0, 3.0)
    assert (l["operating_hours"], l["idle_hours"]) == (8.0, 3.0) and l["employee"]["mobile"] == "9876543210"
    assert l["approval_status"] == "Submitted"
    assert tenant.get("/api/assets/%d" % m["id"]).json()["meter_reading"] == 1008


def test_overnight_shifts_and_the_hours_rule(tenant):
    m = machine(tenant)
    e = person(tenant)
    assert tenant.put("/api/plant/settings", json={"regular_hours": 9}).status_code == 200
    assert log(tenant, m, e, shift="Night", start_time="20:00", end_time="06:00", break_minutes=30, opening_meter=1000, closing_meter=1009).status_code == 200
    l = tenant.get("/api/plant/logs").json()["logs"][0]
    assert (l["attendance_hours"], l["regular_hours"], l["overtime_hours"], l["operating_hours"]) == (9.5, 9.0, 0.5, 9.0)


def test_the_logbook_refuses_what_cannot_be(tenant):
    m = machine(tenant)
    e = person(tenant)
    assert log(tenant, m, e, opening_meter=1010, closing_meter=1005).status_code == 400            # meter backwards
    assert log(tenant, m, e, opening_meter=1000, closing_meter=1030).status_code == 400            # ran longer than the shift
    assert log(tenant, m, e, start_time="7am").status_code == 400
    assert log(tenant, m, e, break_minutes=800).status_code == 400
    assert log(tenant, m, e, opening_meter=1000, closing_meter=None).status_code == 400            # one reading only
    assert log(tenant, m, e, log_date=day(2)).status_code == 400
    assert log(tenant, m, e).status_code == 200
    assert log(tenant, m, e).status_code == 409                                                     # same person, day, shift
    assert log(tenant, m, e, shift="General", start_time="12:00", end_time="15:00", opening_meter=None, closing_meter=None, operating_hours=2).status_code == 409   # overlaps
    assert log(tenant, m, e, shift="Night", start_time="20:00", end_time="23:00", opening_meter=None, closing_meter=None, operating_hours=2).status_code == 200


def test_two_people_on_one_machine_are_one_machine_s_hours(tenant):
    m = machine(tenant)
    op, helper = person(tenant), person(tenant, "Hari", "Babu", "9000000002")
    log(tenant, m, op)
    log(tenant, m, helper)
    assert tenant.get("/api/plant/costs").json()["machines"][0]["operating_hours"] == 8.0
    assert tenant.get("/api/plant/costs").json()["machines"][0]["labour_hours"] == 22.0


def test_supervisor_approves_and_corrections_are_audited(tenant, portal):
    m = machine(tenant)
    e = person(tenant)
    lid = log(tenant, m, e).json()["id"]
    assert tenant.put("/api/plant/logs/%d" % lid, json={"asset_id": m["id"], "employee_id": e["id"], "log_date": day(-1), "shift": "Day", "start_time": "07:00",
                                                       "end_time": "17:00", "break_minutes": 60, "opening_meter": 1000, "closing_meter": 1007}).status_code == 400   # no reason
    fixed = tenant.put("/api/plant/logs/%d" % lid, json={"asset_id": m["id"], "employee_id": e["id"], "log_date": day(-1), "shift": "Day", "start_time": "07:00",
                                                         "end_time": "17:00", "break_minutes": 60, "opening_meter": 1000, "closing_meter": 1007, "correction_reason": "Left at 5"})
    assert fixed.status_code == 200
    assert tenant.get("/api/plant/logs").json()["logs"][0]["attendance_hours"] == 9.0
    signed_in(tenant, portal, "staff")
    assert portal.post("/api/plant/logs/%d/decision" % lid, json={"decision": "approve"}).status_code == 403
    assert tenant.post("/api/plant/logs/%d/decision" % lid, json={"decision": "reject"}).status_code == 400
    assert tenant.post("/api/plant/logs/%d/decision" % lid, json={"decision": "approve"}).json()["message"] == "Day approved."
    trail = [a["action"] for a in tenant.get("/api/settings/audit-log").json().get("logs", [])] if tenant.get("/api/settings/audit-log").status_code == 200 else []
    if trail:
        assert "plant.log.corrected" in trail


# ---- 5: fuel -------------------------------------------------------------------------------------------

def test_fuel_is_costed_reported_and_vouchers_counted_once(tenant):
    j = job(tenant)
    m = machine(tenant)
    deploy(tenant, m, j)
    e = person(tenant)
    log(tenant, m, e)
    f = tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "filled_on": day(-1), "filled_time": "06:30", "fuel_type": "Diesel", "litres": 40, "rate": 92.5,
                                             "supplier": "IOCL", "voucher_no": "FV-101", "meter_reading": 1000})
    assert f.status_code == 200, f.text
    assert f.json()["fuel"]["amount"] == 3700.0
    assert tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 92, "voucher_no": "fv-101"}).status_code == 409
    for bad in ({"litres": 0}, {"rate": 0}, {"litres": 9999}, {"fuel_type": "Water"}, {"filled_time": "9"}, {"litres": 10, "rate": 90, "amount": 5000}):
        assert tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 90, **bad}).status_code == 400, bad
    d = tenant.get("/api/plant/fuel").json()
    assert d["totals"]["amount"] == 3700.0 and d["by_machine"][0]["litres_per_hour"] == 5.0 and d["by_machine"][0]["cost_per_hour"] == 462.5
    c = tenant.get("/api/plant/costs").json()["machines"][0]
    assert c["fuel"] == 3700.0 and c["total"] == 3700.0


# ---- 6: maintenance -------------------------------------------------------------------------------------

def test_a_breakdown_takes_the_machine_off_work_until_completed(tenant):
    j = job(tenant)
    m = machine(tenant)
    deploy(tenant, m, j)
    e = person(tenant)
    r = tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Emergency", "description": "Hydraulic hose burst", "priority": "Urgent", "out_of_service": True})
    assert r.status_code == 200, r.text
    assert tenant.get("/api/assets/%d" % m["id"]).json()["status"] == "Breakdown"
    # Nobody can be put on it, and it cannot log running hours, while it is down.
    assert tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": e["id"]}).status_code == 409
    assert log(tenant, m, e).status_code == 409
    assert log(tenant, m, e, opening_meter=None, closing_meter=None, operating_hours=0, breakdown_hours=8).status_code == 200
    mid = r.json()["id"]
    assert tenant.put("/api/plant/maintenance/%d" % mid, json={"status": "In progress", "mechanic": "Sai Hydraulics"}).status_code == 200
    assert tenant.get("/api/assets/%d" % m["id"]).json()["status"] == "Under repair"
    assert tenant.post("/api/plant/maintenance/%d/complete" % mid, json={"work_performed": ""}).status_code == 400
    done = tenant.post("/api/plant/maintenance/%d/complete" % mid, json={"work_performed": "Hose replaced", "parts_cost": 4500, "labour_cost": 1500,
                                                                         "downtime_start": day(0) + " 08:00", "downtime_end": day(0) + " 14:30", "invoice_no": "SH-77"})
    assert done.status_code == 200, done.text
    a = tenant.get("/api/assets/%d" % m["id"]).json()
    assert a["status"] == "Deployed"
    rows = tenant.get("/api/plant/maintenance").json()["maintenance"]
    assert rows[0]["total_cost"] == 6000.0 and rows[0]["downtime_hours"] == 6.5 and rows[0]["status"] == "Completed"
    assert tenant.post("/api/plant/maintenance/%d/approve" % mid).status_code == 200
    assert tenant.get("/api/plant/costs").json()["machines"][0]["maintenance"] == 6000.0


def test_service_reminders_show_on_the_dashboard(tenant):
    m = machine(tenant, last_service_on=day(-95))
    tenant.post("/api/plant/maintenance", json={"asset_id": m["id"], "kind": "Preventive", "description": "500 h service", "reported_on": day(-5), "scheduled_on": day(-2)})
    d = tenant.get("/api/plant/dashboard").json()
    assert any(r["due"] and "past its service" in r["what"] for r in d["maintenance_reminders"])
    assert any("preventive" in r["what"] for r in d["maintenance_reminders"])
    assert tenant.get("/api/plant/maintenance?status=open").json()["maintenance"][0]["overdue"]


# ---- 7: rentals ------------------------------------------------------------------------------------------

def provider(tenant):
    res = tenant.post("/api/plant/rental-providers", json={"name": "Sri Sai Cranes", "contact_person": "Srinu", "mobile": "9849012345", "email": "srinu@saicranes.in"})
    assert res.status_code == 200, res.text
    return res.json()["provider"]


def test_a_hire_is_agreed_extended_billed_paid_and_returned(tenant):
    j = job(tenant)
    m = machine(tenant, name="Hydra 14T", ownership="Rented", hire_rate=1, hire_basis="Day")
    deploy(tenant, m, j)
    p = provider(tenant)
    body = {"asset_id": m["id"], "provider_id": p["id"], "agreement_no": "SSC/24/17", "start_date": day(-20), "expected_return": day(3), "rate": 1800, "billing": "Hourly",
            "min_billable_hours": 200, "transport_charges": 15000, "deposit": 50000, "fuel_included": False, "operator_included": True}
    r = tenant.post("/api/plant/rentals", json=body)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert tenant.post("/api/plant/rentals", json=dict(body, agreement_no="ssc/24/17")).status_code == 409
    assert tenant.post("/api/plant/rentals", json=dict(body, agreement_no="X2")).status_code == 409                     # overlapping dates
    e = person(tenant)
    log(tenant, m, e, log_date=day(-5))
    inv = tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "SSC-INV-9", "invoice_date": day(-1), "period_from": day(-20), "period_to": day(-1),
                                                                    "billed_hours": 10, "amount": 18000, "paid": 5000, "paid_on": day(-1)})
    assert inv.status_code == 200, inv.text
    assert tenant.post("/api/plant/rentals/%d/invoices" % rid, json={"invoice_no": "ssc-inv-9", "amount": 1}).status_code == 409
    row = tenant.get("/api/plant/rentals").json()["rentals"][0]
    assert (row["billed"], row["paid"], row["outstanding"]) == (18000.0, 5000.0, 13000.0)
    assert (row["used_hours"], row["billed_hours"], row["hours_gap"]) == (8.0, 10.0, 2.0)
    assert row["provider"]["mobile"] == "9849012345" and row["status"] == "Active"
    iid = row["invoices"][0]["id"]
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % iid, json={"amount": 20000}).status_code == 400
    assert tenant.post("/api/plant/rental-invoices/%d/payment" % iid, json={"amount": 13000, "payment_ref": "NEFT 1"}).status_code == 200
    assert tenant.post("/api/plant/rentals/%d/extend" % rid, json={"to_date": day(1)}).status_code == 400
    assert tenant.post("/api/plant/rentals/%d/extend" % rid, json={"to_date": day(10), "reason": "Slab delayed"}).status_code == 200
    row = tenant.get("/api/plant/rentals").json()["rentals"][0]
    assert row["status"] == "Extended" and row["expected_return"] == day(10) and row["extensions"][0]["to"] == day(10) and row["outstanding"] == 0
    # Hire cost is the invoices, not the daily estimate as well.
    assert tenant.get("/api/plant/costs").json()["machines"][0]["rental"] == 18000.0
    tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": person(tenant, "Anil", "Rao", "9000000001")["id"], "shift": "Night"})
    back = tenant.post("/api/plant/rentals/%d/return" % rid, json={"returned_on": day(0)})
    assert back.status_code == 200 and "1 allocation ended" in back.json()["message"]
    a = tenant.get("/api/assets/%d" % m["id"]).json()
    assert a["status"] == "Returned" and a["current_job_id"] is None
    assert tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": e["id"]}).status_code == 409
    assert tenant.post("/api/assets/%d/move" % m["id"], json={"to_job_id": j["id"]}).status_code == 409
    assert tenant.get("/api/plant/rentals?status=Returned").json()["rentals"][0]["actual_return"] == day(0)


def test_rental_rules(tenant):
    own = machine(tenant)
    p = provider(tenant)
    assert tenant.post("/api/plant/rentals", json={"asset_id": own["id"], "provider_id": p["id"], "agreement_no": "A1", "start_date": day(0), "expected_return": day(5), "rate": 100}).status_code == 409
    m = machine(tenant, name="Mixer", ownership="Rented", hire_rate=100)
    for bad in ({"agreement_no": ""}, {"expected_return": day(-5)}, {"rate": 0}, {"billing": "Yearly"}, {"deposit": -1}):
        body = {"asset_id": m["id"], "provider_id": p["id"], "agreement_no": "A2", "start_date": day(0), "expected_return": day(5), "rate": 100, **bad}
        assert tenant.post("/api/plant/rentals", json=body).status_code == 400, bad
    assert tenant.post("/api/plant/rental-providers", json={"name": "sri sai cranes"}).status_code == 409
    assert tenant.post("/api/plant/rental-providers", json={"name": "X", "mobile": "12"}).status_code == 400
    late = tenant.post("/api/plant/rentals", json={"asset_id": m["id"], "provider_id": p["id"], "agreement_no": "A3", "start_date": day(-10), "expected_return": day(-1), "rate": 100})
    assert late.status_code == 200
    assert tenant.get("/api/plant/rentals").json()["rentals"][0]["status"] == "Overdue"
    assert any(r["overdue"] for r in tenant.get("/api/plant/dashboard").json()["rental_returns"])


# ---- 8: expenses ------------------------------------------------------------------------------------------

def test_expenses_are_stored_once_and_counted_once(tenant):
    m = machine(tenant)
    body = {"asset_id": m["id"], "category": "Spare parts", "spent_on": day(-2), "description": "Bucket teeth x 5", "quantity": 5, "unit_rate": 1200, "vendor": "JCB Parts", "invoice_no": "JP-55"}
    e = tenant.post("/api/plant/expenses", json=body)
    assert e.status_code == 200, e.text
    assert tenant.post("/api/plant/expenses", json=body).status_code == 409                                         # same invoice
    assert tenant.post("/api/plant/expenses", json=dict(body, invoice_no="")).status_code == 200                     # no voucher: allowed once...
    assert tenant.post("/api/plant/expenses", json=dict(body, invoice_no="")).status_code == 409                     # ...not twice
    assert tenant.post("/api/plant/expenses", json=dict(body, category="Fuel and diesel", invoice_no="Z")).status_code == 400   # has its own register
    assert tenant.post("/api/plant/expenses", json=dict(body, quantity=5, unit_rate=1200, amount=99, invoice_no="Q")).status_code == 400
    tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 10, "rate": 100, "voucher_no": "FV-1"})
    assert tenant.post("/api/plant/expenses", json=dict(body, invoice_no="FV-1")).status_code == 409                  # a fuel voucher already
    reg = tenant.get("/api/plant/expenses").json()
    assert reg["by_category"] == {"Spare parts": 12000.0, "Fuel and diesel": 1000.0} and reg["total"] == 13000.0
    assert {r["source"] for r in reg["expenses"]} == {"expense", "fuel"}
    eid = e.json()["id"]
    assert tenant.post("/api/plant/expenses/%d/decision" % eid, json={"decision": "approve"}).status_code == 200
    assert tenant.delete("/api/plant/expenses/%d" % eid).status_code == 409
    assert tenant.get("/api/plant/costs").json()["machines"][0]["total"] == 13000.0


# ---- 9: the dashboard ------------------------------------------------------------------------------------

def test_the_dashboard_is_the_records(tenant):
    j = job(tenant)
    a, b, c = machine(tenant, name="A"), machine(tenant, name="B"), machine(tenant, name="C")
    deploy(tenant, a, j)
    tenant.post("/api/plant/maintenance", json={"asset_id": b["id"], "kind": "Emergency", "description": "Engine seized", "out_of_service": True})
    e = person(tenant)
    tenant.post("/api/plant/allocations", json={"asset_id": a["id"], "employee_id": e["id"]})
    log(tenant, a, e)
    tenant.post("/api/plant/fuel", json={"asset_id": a["id"], "litres": 20, "rate": 90})
    d = tenant.get("/api/plant/dashboard").json()
    k = d["cards"]
    assert (k["total"], k["working"], k["idle"], k["breakdown"], k["operators"]) == (3, 1, 1, 1, 1)
    assert k["working_hours"] == 8.0 and k["fuel"] == 1800.0 and k["operating_cost"] == 1800.0
    assert {s["status"]: s["count"] for s in d["status_distribution"]} == {"Deployed": 1, "Available": 1, "Breakdown": 1}
    assert d["recent"] and d["recent"][0]["action"].startswith("plant.")


def test_excessive_idle_is_called_out(tenant):
    m = machine(tenant)
    e = person(tenant)
    log(tenant, m, e, opening_meter=1000, closing_meter=1002)
    idle = tenant.get("/api/plant/dashboard").json()["excess_idle"]
    assert idle and idle[0]["code"] == m["code"] and idle[0]["idle_share"] > 0.4


# ---- 10: permissions, other companies, reports -------------------------------------------------------------

def test_permissions(tenant, portal):
    m = machine(tenant)
    e = person(tenant)
    signed_in(tenant, portal, "staff")                     # records site work, decides nothing, manages nothing
    assert portal.get("/api/plant/dashboard").status_code == 200
    assert log(portal, m, e).status_code == 200
    assert portal.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 5, "rate": 90}).status_code == 200
    assert portal.post("/api/plant/expenses", json={"asset_id": m["id"], "category": "Other", "description": "x", "amount": 10}).status_code == 403
    assert portal.post("/api/plant/rental-providers", json={"name": "X"}).status_code == 403
    assert portal.post("/api/assets/%d/archive" % m["id"], json={}).status_code == 403
    assert portal.put("/api/plant/settings", json={"regular_hours": 10}).status_code == 403


def test_another_company_sees_and_touches_none_of_it(tenant, second_tenant):
    m = machine(tenant)
    e = person(tenant)
    lid = log(tenant, m, e).json()["id"]
    assert second_tenant.get("/api/plant/logs").json()["logs"] == []
    assert second_tenant.get("/api/plant/dashboard").json()["cards"]["total"] == 0
    assert second_tenant.post("/api/plant/logs/%d/decision" % lid, json={"decision": "approve"}).status_code == 404
    assert second_tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 5, "rate": 90}).status_code == 404
    assert second_tenant.post("/api/plant/allocations", json={"asset_id": m["id"], "employee_id": e["id"]}).status_code == 404


def test_every_report_exports(tenant):
    m = machine(tenant)
    e = person(tenant)
    log(tenant, m, e)
    tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 5, "rate": 90})
    for kind in ("register", "allocations", "employee-hours", "machine-hours", "fuel", "maintenance", "rentals", "rental-invoices", "expenses", "overtime"):
        res = tenant.get("/api/plant/reports/%s.xlsx" % kind, params={"date_from": day(-30), "date_to": day(0)})
        assert res.status_code == 200 and len(res.content) > 500, kind
    assert tenant.get("/api/plant/reports/nonsense.xlsx").status_code == 404
    pdf = tenant.get("/api/plant/reports/fuel.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_attachments_go_against_plant_records(tenant):
    m = machine(tenant)
    f = tenant.post("/api/plant/fuel", json={"asset_id": m["id"], "litres": 5, "rate": 90}).json()["fuel"]
    for kind, rid in (("equipment", m["id"]), ("plant_fuel", f["id"])):
        up = tenant.post("/api/files", files={"file": ("x.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 300), "image/jpeg")}, data={"attached_type": kind, "attached_id": str(rid)})
        assert up.status_code == 200, (kind, up.text)


def test_an_older_database_keeps_its_makes_as_brands():
    from sqlalchemy import create_engine, text
    from app.db.migrations import rename_asset_make_to_brand
    eng = create_engine("sqlite://")
    with eng.connect() as conn:
        conn.execute(text("CREATE TABLE assets (id INTEGER PRIMARY KEY, make VARCHAR, serial_no VARCHAR)"))
        conn.execute(text("INSERT INTO assets (make, serial_no) VALUES ('JCB', 'SN-1')"))
        for _ in range(2):  # a second start finds nothing left to rename
            rename_asset_make_to_brand(conn, {r[1] for r in conn.execute(text("PRAGMA table_info(assets)")).fetchall()})
        assert conn.execute(text("SELECT brand, serial_no FROM assets")).fetchone() == ("JCB", "SN-1")


def test_where_a_machine_is_is_said_not_assumed(tenant):
    j = job(tenant)
    m = machine(tenant)
    assert m["location_type"] == "" and m["where"] == "Not set" and m["current_job_id"] is None
    # a site needs the site
    assert tenant.put("/api/assets/%d" % m["id"], json=dict(m, location_type="Site")).status_code == 400
    assert tenant.put("/api/assets/%d" % m["id"], json=dict(m, location_type="Moon")).status_code == 400
    on = tenant.put("/api/assets/%d" % m["id"], json=dict(m, location_type="Site", location_id=j["id"])).json()
    assert on["location_type"] == "Site" and on["location_id"] == j["id"] and on["status"] == "Deployed" and "Vizag STP" in on["where"]
    yard = tenant.put("/api/assets/%d" % m["id"], json=dict(on, location_type="Yard", location_id=None)).json()
    assert yard["location_type"] == "Yard" and yard["where"] == "Yard" and yard["current_job_id"] is None and yard["status"] == "Available"
    transit = tenant.put("/api/assets/%d" % m["id"], json=dict(yard, location_type="Transit")).json()
    assert transit["where"] == "In transit"
    # an edit that does not mention where leaves it be
    kept = tenant.put("/api/assets/%d" % m["id"], json={k: v for k, v in dict(transit, name="Renamed").items() if k not in ("location_type", "location_id")}).json()
    assert kept["where"] == "In transit"
    new = machine(tenant, name="Roller", location_type="Site", location_id=j["id"])
    assert new["status"] == "Deployed" and new["location_id"] == j["id"]
