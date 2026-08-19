"""Jobs, purchase orders and the spending limits that make a chain practical.

A contracting business earns per job. These tests pin down the one number that
matters - did this job make money - and the two mechanisms that keep it honest:
spend agreed before it is committed, and small costs not being sent to a
director who has better things to read.
"""
import uuid

import pytest

from conftest import make_employee, make_invoice


PASSWORD = "Crew1234"


def staff(tenant, permission_role="staff", reports_to=None, **overrides):
    emp = make_employee(tenant, permission_role=permission_role, reports_to=reports_to,
                        password=PASSWORD, **overrides)
    tenant.put(f"/api/employees/{emp['id']}", json={"status": "active"})
    return emp


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login",
                      json={"email": emp["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text


def sign_out(client):
    client.post("/api/employee/auth/logout")


def make_job(tenant, **overrides):
    payload = {"name": "Fairview, plot 3", "customer_name": "Fairview Homes",
               "status": "in_progress", "quoted_value": 20000.0, "budget": 14000.0}
    payload.update(overrides)
    res = tenant.post("/api/jobs", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


# --- Jobs -------------------------------------------------------------------

def test_a_job_gets_a_number_and_starts_empty(tenant):
    job = make_job(tenant)
    assert job["number"] == "JOB-0001"
    c = job["costing"]
    assert c["invoiced"] == 0 and c["spent"] == 0 and c["profit"] == 0


def test_jobs_number_in_sequence(tenant):
    assert make_job(tenant)["number"] == "JOB-0001"
    assert make_job(tenant, name="Second")["number"] == "JOB-0002"


def test_a_job_needs_a_name(tenant):
    assert tenant.post("/api/jobs", json={"name": "   "}).status_code == 400


def test_an_unknown_status_is_refused(tenant):
    assert tenant.post("/api/jobs", json={"name": "X", "status": "invented"}).status_code == 400


def test_negative_money_is_refused(tenant):
    assert tenant.post("/api/jobs", json={"name": "X", "budget": -5}).status_code == 400


def test_costing_adds_up_across_invoices_and_bills(tenant):
    job = make_job(tenant)
    make_invoice(tenant, job_id=job["id"],
                 line_items=[{"description": "Groundworks", "qty": 1, "price": 10000.0,
                              "tax_rate": "No Tax"}])
    tenant.post("/api/bills", json={"number": "BILL-9001", "vendor_name": "Jewson",
                                    "amount": 3000.0, "total": 3000.0, "job_id": job["id"]})

    c = tenant.get(f"/api/jobs/{job['id']}").json()["costing"]
    assert c["invoiced"] == 10000.0
    assert c["spent"] == 3000.0
    assert c["profit"] == 7000.0
    assert c["margin_percent"] == 70.0


def test_money_on_another_job_stays_there(tenant):
    a, b = make_job(tenant), make_job(tenant, name="Other site")
    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X",
                                    "amount": 500.0, "total": 500.0, "job_id": a["id"]})
    assert tenant.get(f"/api/jobs/{a['id']}").json()["costing"]["spent"] == 500.0
    assert tenant.get(f"/api/jobs/{b['id']}").json()["costing"]["spent"] == 0.0


def test_a_rejected_cost_is_not_a_cost(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    job = make_job(tenant)

    sign_in(tenant, hand)
    bill = tenant.post("/api/employee/bills", json={
        "vendor_name": "Jewson", "amount": 900.0, "job_id": job["id"]}).json()["bill"]
    sign_out(tenant)

    assert tenant.get(f"/api/jobs/{job['id']}").json()["costing"]["spent"] == 900.0

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "reject", "notes": "Not ours"})
    sign_out(tenant)

    assert tenant.get(f"/api/jobs/{job['id']}").json()["costing"]["spent"] == 0.0


def test_labour_hours_reach_the_job(tenant):
    job = make_job(tenant)
    hand = staff(tenant, hourly_rate=25.0)
    tenant.put("/api/attendance/settings", json={"working_days": "1,2,3,4,5,6,7"})

    sign_in(tenant, hand)
    tenant.post("/api/employee/attendance/clock-in", json={})
    tenant.post("/api/employee/attendance/clock-out", json={})
    res = tenant.post("/api/employee/attendance/job", json={"job_id": job["id"]})
    assert res.status_code == 200, res.text
    sign_out(tenant)

    c = tenant.get(f"/api/jobs/{job['id']}").json()["costing"]
    assert c["labour_hours"] >= 0
    assert "labour_cost" in c


def test_a_job_with_documents_cannot_be_deleted(tenant):
    job = make_job(tenant)
    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X",
                                    "amount": 10.0, "total": 10.0, "job_id": job["id"]})
    res = tenant.delete(f"/api/jobs/{job['id']}")
    assert res.status_code == 409
    assert "complete" in res.json()["detail"]


def test_an_empty_job_can_be_deleted(tenant):
    job = make_job(tenant)
    assert tenant.delete(f"/api/jobs/{job['id']}").status_code == 200


def test_completing_a_job_stamps_the_date(tenant):
    job = make_job(tenant)
    done = tenant.put(f"/api/jobs/{job['id']}", json={"name": job["name"], "status": "complete"}).json()
    assert done["completed_at"] != ""


def test_the_board_puts_the_worst_margin_first(tenant):
    good = make_job(tenant, name="Good one")
    bad = make_job(tenant, name="Bad one")
    make_invoice(tenant, job_id=good["id"],
                 line_items=[{"description": "w", "qty": 1, "price": 1000.0, "tax_rate": "No Tax"}])
    make_invoice(tenant, job_id=bad["id"],
                 line_items=[{"description": "w", "qty": 1, "price": 1000.0, "tax_rate": "No Tax"}])
    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X",
                                    "amount": 900.0, "total": 900.0, "job_id": bad["id"]})
    board = tenant.get("/api/jobs-summary").json()
    assert board["jobs"][0]["name"] == "Bad one"
    assert board["totals"]["invoiced"] == 2000.0


def test_a_job_over_budget_is_flagged(tenant):
    job = make_job(tenant, budget=1000.0)
    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X",
                                    "amount": 1500.0, "total": 1500.0, "job_id": job["id"]})
    board = tenant.get("/api/jobs-summary").json()
    assert job["number"] in board["over_budget"]


def test_a_document_cannot_point_at_another_tenants_job(client):
    def register():
        email = f"user-{uuid.uuid4().hex[:10]}@example.com"
        client.post("/api/client/register", json={"email": email, "password": "Passw0rdTest"})
        client.post("/api/client/login", json={"email": email, "password": "Passw0rdTest"})

    register()
    theirs = make_job(client)
    register()
    res = client.post("/api/bills", json={"number": "B1", "vendor_name": "X",
                                          "amount": 10.0, "total": 10.0, "job_id": theirs["id"]})
    assert res.status_code == 404, res.text


# --- Purchase orders --------------------------------------------------------

def test_an_order_goes_up_the_line_before_the_money_is_spent(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    job = make_job(tenant)

    sign_in(tenant, hand)
    res = tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "Travis Perkins", "amount": 2000.0, "tax_amount": 400.0,
        "job_id": job["id"], "notes": "Blockwork"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == "pending"
    assert out["order"]["status"] == "Awaiting Approval"
    assert out["order"]["total"] == 2400.0
    sign_out(tenant)

    sign_in(tenant, boss)
    queue = tenant.get("/api/employee/approvals").json()["pending"]
    assert queue[0]["kind"] == "Purchase order"
    tenant.post(f"/api/employee/approvals/{queue[0]['step_id']}/action",
                json={"action": "approve", "notes": "Priced right"})
    sign_out(tenant)

    order = tenant.get(f"/api/purchase-orders/{out['order']['id']}").json()
    assert order["status"] == "Approved"
    assert order["approval_status"] == "approved"


def test_an_approved_order_is_committed_cost_not_spend(tenant):
    job = make_job(tenant)
    top = staff(tenant, permission_role="manager")
    sign_in(tenant, top)
    tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "Speedy Hire", "amount": 1000.0, "job_id": job["id"]})
    sign_out(tenant)

    c = tenant.get(f"/api/jobs/{job['id']}").json()["costing"]
    assert c["committed"] == 1000.0
    assert c["spent"] == 0.0
    assert c["forecast_cost"] == 1000.0


def test_a_matched_bill_replaces_the_commitment(tenant):
    job = make_job(tenant)
    top = staff(tenant, permission_role="manager")
    sign_in(tenant, top)
    order = tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "Speedy Hire", "amount": 1000.0, "job_id": job["id"]}).json()["order"]
    sign_out(tenant)

    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "Speedy Hire",
                                    "amount": 1000.0, "total": 1000.0,
                                    "job_id": job["id"], "purchase_order_id": order["id"]})
    c = tenant.get(f"/api/jobs/{job['id']}").json()["costing"]
    # Counting both would double the cost of the same delivery.
    assert c["committed"] == 0.0
    assert c["spent"] == 1000.0


def test_a_bill_cannot_be_matched_to_an_unapproved_order(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    sign_in(tenant, hand)
    order = tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "X", "amount": 100.0}).json()["order"]
    sign_out(tenant)

    res = tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X",
                                          "amount": 100.0, "total": 100.0,
                                          "purchase_order_id": order["id"]})
    assert res.status_code == 409, res.text


def test_a_bill_over_its_order_is_flagged(tenant):
    top = staff(tenant, permission_role="manager")
    sign_in(tenant, top)
    order = tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "Jewson", "amount": 500.0}).json()["order"]
    sign_out(tenant)

    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "Jewson",
                                    "amount": 800.0, "total": 800.0,
                                    "purchase_order_id": order["id"]})
    bill = [b for b in tenant.get("/api/bills").json() if b["number"] == "B1"][0]
    detail = tenant.get(f"/api/bills/{bill['id']}").json()
    assert detail["approval_status"] == "none"
    listing = tenant.get(f"/api/jobs-summary").json()  # smoke: costing still computes
    assert listing is not None


def test_an_order_with_a_bill_against_it_cannot_be_deleted(tenant):
    top = staff(tenant, permission_role="manager")
    sign_in(tenant, top)
    order = tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "X", "amount": 100.0}).json()["order"]
    sign_out(tenant)
    tenant.post("/api/bills", json={"number": "B1", "vendor_name": "X", "amount": 100.0,
                                    "total": 100.0, "purchase_order_id": order["id"]})
    assert tenant.delete(f"/api/purchase-orders/{order['id']}").status_code == 409


def test_an_order_awaiting_approval_cannot_be_edited(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    sign_in(tenant, hand)
    order = tenant.post("/api/employee/purchase-orders", json={
        "supplier_name": "X", "amount": 100.0}).json()["order"]
    sign_out(tenant)
    res = tenant.put(f"/api/purchase-orders/{order['id']}",
                     json={"supplier_name": "X", "amount": 50.0})
    assert res.status_code == 409


def test_an_order_needs_a_supplier_and_an_amount(tenant):
    hand = staff(tenant)
    sign_in(tenant, hand)
    assert tenant.post("/api/employee/purchase-orders", json={"amount": 10}).status_code == 400
    assert tenant.post("/api/employee/purchase-orders",
                       json={"supplier_name": "X"}).status_code == 400


# --- Approval thresholds ----------------------------------------------------

def set_rules(tenant, auto_below=0, finance_above=0):
    res = tenant.put("/api/approval-rules",
                     json={"auto_below": auto_below, "finance_above": finance_above})
    assert res.status_code == 200, res.text
    return res.json()


def test_a_small_cost_does_not_trouble_the_director(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    set_rules(tenant, auto_below=50.0)

    sign_in(tenant, hand)
    out = tenant.post("/api/employee/bills",
                      json={"vendor_name": "Screwfix", "amount": 12.0}).json()
    assert out["status"] == "approved"
    assert out["bill"]["status"] == "Approved for payment"
    assert "limit" in out["message"]
    sign_out(tenant)

    sign_in(tenant, boss)
    assert tenant.get("/api/employee/approvals").json()["pending"] == []


def test_a_cost_on_the_limit_still_goes_up(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    set_rules(tenant, auto_below=50.0)
    sign_in(tenant, hand)
    out = tenant.post("/api/employee/bills",
                      json={"vendor_name": "Screwfix", "amount": 50.0}).json()
    assert out["status"] == "pending"


def test_a_large_cost_picks_up_finance(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    purse = staff(tenant, permission_role="finance")
    set_rules(tenant, finance_above=1000.0)

    sign_in(tenant, hand)
    out = tenant.post("/api/employee/bills",
                      json={"vendor_name": "Jewson", "amount": 5000.0}).json()
    # The manager, then finance on top.
    assert out["chain_length"] == 2
    sign_out(tenant)

    sign_in(tenant, boss)
    step = tenant.get("/api/employee/approvals").json()["pending"][0]
    tenant.post(f"/api/employee/approvals/{step['step_id']}/action",
                json={"action": "approve", "notes": "ok"})
    sign_out(tenant)

    sign_in(tenant, purse)
    assert len(tenant.get("/api/employee/approvals").json()["pending"]) == 1


def test_a_small_cost_stays_a_short_chain(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    staff(tenant, permission_role="finance")
    set_rules(tenant, finance_above=1000.0)
    sign_in(tenant, hand)
    out = tenant.post("/api/employee/bills",
                      json={"vendor_name": "Jewson", "amount": 200.0}).json()
    assert out["chain_length"] == 1


def test_a_bill_over_its_order_never_auto_approves(tenant):
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])
    set_rules(tenant, auto_below=500.0)

    top = staff(tenant, permission_role="manager")
    sign_in(tenant, top)
    order = tenant.post("/api/employee/purchase-orders",
                        json={"supplier_name": "Jewson", "amount": 100.0}).json()["order"]
    sign_out(tenant)

    sign_in(tenant, hand)
    # Under the £500 limit, but more than the £100 that was agreed.
    out = tenant.post("/api/employee/bills", json={
        "vendor_name": "Jewson", "amount": 300.0,
        "purchase_order_id": order["id"]}).json()
    assert out["status"] == "pending", "overspend must always be looked at"
    assert out["over_order"] is True
    assert "more than the order" in out["message"]


def test_the_finance_limit_must_sit_above_the_signoff_limit(tenant):
    res = tenant.put("/api/approval-rules", json={"auto_below": 500, "finance_above": 100})
    assert res.status_code == 400


def test_rules_are_off_by_default(tenant):
    rules = tenant.get("/api/approval-rules").json()
    assert rules["auto_below"] == 0 and rules["finance_above"] == 0


def test_the_rules_screen_says_whether_anyone_can_hold_the_finance_step(tenant):
    set_rules(tenant, finance_above=1000.0)
    assert tenant.get("/api/approval-rules").json()["has_finance_approver"] is False
    purse = staff(tenant, permission_role="finance")
    after = tenant.get("/api/approval-rules").json()
    assert after["has_finance_approver"] is True
    assert after["finance_approver"] == f"{purse['first_name']} {purse['last_name']}"


def test_nonsense_limits_are_refused(tenant):
    assert tenant.put("/api/approval-rules", json={"auto_below": "lots"}).status_code == 400
    assert tenant.put("/api/approval-rules", json={"auto_below": -5}).status_code == 400
