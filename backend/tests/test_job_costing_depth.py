"""What a project actually costs.

Cost by Project used to total open purchase orders and subcontract orders and
call that the cost. Bills were not in it, so a project paying its suppliers
directly showed a cost of nothing; labour was not in it either; and a purchase
order stayed in the total after its bill arrived, counting the same spend
twice. Every one of those errors ran in the direction that flatters the job,
which is the direction nobody checks.

These fix the arithmetic in place so it cannot drift back.
"""
import pytest

from conftest import make_employee, make_invoice
from test_jobs_and_orders import staff, sign_in, sign_out


def make_job(tenant, **extra):
    body = {"name": "Fairview plot 3", "customer_name": "Fairview Homes",
            "status": "in_progress", "quoted_value": 1000000.0, "budget": 700000.0}
    body.update(extra)
    res = tenant.post("/api/jobs", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def costs_for(tenant, job_id):
    res = tenant.get("/api/costs/by-project/%d" % job_id)
    assert res.status_code == 200, res.text
    return res.json()


def add_bill(tenant, job_id, total, category="materials", **extra):
    body = {"number": "B-%d-%s" % (job_id, str(total).replace(".", "")),
            "vendor_name": "Travis Perkins", "amount": total, "total": total,
            "job_id": job_id, "category": category}
    body.update(extra)
    res = tenant.post("/api/bills", json=body)
    assert res.status_code == 200, res.text
    return res.json()


# --- the three things that were wrong --------------------------------------

def test_a_bill_is_a_cost(tenant):
    """The hole that mattered most: most jobs buy directly, and every one of
    them reported a cost of nothing and a margin of everything."""
    job = make_job(tenant)
    add_bill(tenant, job["id"], 250000.0)
    row = costs_for(tenant, job["id"])
    assert row["incurred"] == 250000.0
    assert row["cost"] == 250000.0


def test_hours_worked_on_site_are_a_cost(tenant, portal):
    """The hours are already recorded and already priced on the jobs board.
    Cost by Project was the one place that ignored them."""
    import database, models
    job = make_job(tenant)
    hand = staff(tenant, hourly_rate=400.0)

    # Written directly: the clock endpoints decide the date and hours for
    # themselves, and this is a test about what a recorded day costs.
    session = database.SessionLocal()
    try:
        emp = session.query(models.DBEmployee).filter(
            models.DBEmployee.id == hand["id"]).first()
        session.add(models.DBAttendance(
            client_id=emp.client_id, employee_id=emp.id, date="2026-08-03",
            status="present", total_hours=10.0, job_id=job["id"]))
        session.commit()
    finally:
        session.close()

    row = costs_for(tenant, job["id"])
    assert row["labour_hours"] == 10.0
    assert row["labour"] == 4000.0
    assert row["incurred"] == 4000.0


def test_an_order_stops_being_a_commitment_once_its_bill_arrives(tenant):
    """Otherwise the same spend is counted twice and the job looks worse the
    closer it gets to finishing."""
    job = make_job(tenant)
    po = tenant.post("/api/purchase-orders", json={
        "supplier_name": "Jewson", "job_id": job["id"], "amount": 100000.0,
        "line_items": [{"description": "Conduit", "qty": 1, "price": 100000.0}]}).json()

    # A bill may only be matched to an approved order, which is the situation
    # this is about: the order approved, the bill against it arrived.
    import database, models
    session = database.SessionLocal()
    try:
        row = session.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.id == po["id"]).first()
        row.approval_status = "approved"
        session.commit()
    finally:
        session.close()

    before = costs_for(tenant, job["id"])
    assert before["commitment"] == 100000.0
    assert before["incurred"] == 0.0

    add_bill(tenant, job["id"], 100000.0, purchase_order_id=po["id"])
    after = costs_for(tenant, job["id"])
    assert after["incurred"] == 100000.0
    assert after["commitment"] == 0.0, "the order is still being counted alongside its bill"
    assert after["cost"] == 100000.0, "the same spend has been counted twice"


def test_a_rejected_bill_is_not_a_cost(tenant, portal):
    job = make_job(tenant)
    boss = staff(tenant, permission_role="manager")
    hand = staff(tenant, reports_to=boss["id"])

    sign_in(portal, hand)
    portal.post("/api/employee/bills", json={
        "vendor_name": "Jewson", "amount": 50000.0, "job_id": job["id"]})
    sign_out(portal)
    assert costs_for(tenant, job["id"])["incurred"] == 50000.0

    sign_in(portal, boss)
    step = portal.get("/api/employee/approvals").json()["pending"][0]
    portal.post("/api/employee/approvals/%s/action" % step["step_id"],
                json={"action": "reject", "notes": "Wrong job"})
    sign_out(portal)
    assert costs_for(tenant, job["id"])["incurred"] == 0.0


# --- the measures a contractor actually reads ------------------------------

def test_cost_is_split_by_heading(tenant):
    job = make_job(tenant)
    add_bill(tenant, job["id"], 200000.0, category="materials")
    add_bill(tenant, job["id"], 60000.0, category="plant")
    row = costs_for(tenant, job["id"])
    got = {c["key"]: c["amount"] for c in row["categories"]}
    assert got["materials"] == 200000.0
    assert got["plant"] == 60000.0


def test_the_old_office_headings_still_land_somewhere(tenant):
    """Bills raised before the contracting headings existed must still total."""
    job = make_job(tenant)
    add_bill(tenant, job["id"], 10000.0, category="general")
    got = {c["key"]: c["amount"] for c in costs_for(tenant, job["id"])["categories"]}
    assert got["other"] == 10000.0


def test_the_forecast_holds_the_budget_until_the_job_outgrows_it(tenant):
    """Work still to come has not been ordered yet, so early on the budget is
    the better forecast. Once known cost passes it, known cost is."""
    job = make_job(tenant, budget=700000.0)
    add_bill(tenant, job["id"], 100000.0)
    early = costs_for(tenant, job["id"])
    assert early["forecast_cost"] == 700000.0
    assert early["cost_to_complete"] == 600000.0

    add_bill(tenant, job["id"], 800000.0)
    late = costs_for(tenant, job["id"])
    assert late["forecast_cost"] == 900000.0
    assert late["over_budget"] == 200000.0
    assert late["budget_variance"] == -200000.0


def test_percent_complete_is_measured_by_cost(tenant):
    job = make_job(tenant, budget=400000.0)
    add_bill(tenant, job["id"], 100000.0)
    assert costs_for(tenant, job["id"])["percent_complete"] == 25.0


def test_billing_ahead_of_the_work_is_visible(tenant):
    """A job invoiced further than it has been built is borrowing from itself,
    and that has to show as a number rather than a surprise at the end."""
    job = make_job(tenant, budget=400000.0, quoted_value=1000000.0)
    add_bill(tenant, job["id"], 100000.0)          # a quarter of the way through
    make_invoice(tenant, job_id=job["id"],
                 line_items=[{"description": "Stage 1", "qty": 1, "price": 600000.0,
                              "tax_rate": "No Tax"}])
    row = costs_for(tenant, job["id"])
    assert row["percent_complete"] == 25.0
    assert row["earned"] == 250000.0
    assert row["over_billed"] == 350000.0


def test_retention_is_held_back_from_what_the_job_collects(tenant):
    job = make_job(tenant, retention_percent=5.0)
    make_invoice(tenant, job_id=job["id"],
                 line_items=[{"description": "Stage 1", "qty": 1, "price": 200000.0,
                              "tax_rate": "No Tax"}])
    row = costs_for(tenant, job["id"])
    assert row["retention_percent"] == 5.0
    assert row["retention_held"] == 10000.0


@pytest.mark.parametrize("given,expected", [(-5, 0.0), (0, 0.0), (5, 5.0), (150, 100.0)])
def test_retention_cannot_be_nonsense(tenant, given, expected):
    job = make_job(tenant, retention_percent=given)
    assert costs_for(tenant, job["id"])["retention_percent"] == expected


def test_cash_and_invoicing_are_kept_apart(tenant):
    job = make_job(tenant)
    inv = make_invoice(tenant, job_id=job["id"],
                       line_items=[{"description": "Stage 1", "qty": 1, "price": 300000.0,
                                    "tax_rate": "No Tax"}])
    row = costs_for(tenant, job["id"])
    assert row["invoiced"] == 300000.0
    assert row["received"] == 0.0
    assert row["outstanding"] == 300000.0

    tenant.post("/api/invoices/%s/mark-paid" % inv["number"])
    after = costs_for(tenant, job["id"])
    assert after["received"] == 300000.0
    assert after["outstanding"] == 0.0


def test_the_two_screens_agree_on_what_a_job_has_spent(tenant):
    """The jobs board and Cost by Project were computing different costs for
    the same job. Whatever they each add on top, the money actually spent has
    to be one number."""
    job = make_job(tenant)
    add_bill(tenant, job["id"], 120000.0)

    board = [j for j in tenant.get("/api/jobs-summary").json()["jobs"]
             if j["id"] == job["id"]][0]["costing"]
    costs = costs_for(tenant, job["id"])
    assert costs["incurred"] == board["total_cost"]
    assert costs["labour"] == board["labour_cost"]


def test_the_list_totals_what_the_rows_hold(tenant):
    a = make_job(tenant, name="A")
    b = make_job(tenant, name="B")
    add_bill(tenant, a["id"], 100000.0)
    add_bill(tenant, b["id"], 40000.0)
    body = tenant.get("/api/costs/by-project").json()
    assert body["summary"]["incurred"] == 140000.0
    totals = {c["key"]: c["amount"] for c in body["summary"]["categories"]}
    assert totals["materials"] == 140000.0
