"""Where the money is, per project.

Every figure already existed somewhere - a work order on one screen, a
purchase order on another, bills on a third. What nobody could do was see
them on one line and answer the only question a running job asks: are we
still making money on it.
"""


def project(tenant, name="Fairview plot 3"):
    return tenant.post("/api/jobs", json={
        "name": name, "customer_name": "L&T Construction"}).json()


def sold(tenant, job, value=100000):
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY", "units_of_measure": "Meters"},
        {"kind": "RM", "item_name": "CONDUIT", "units_of_measure": "Meters"},
    ]}).json()
    fg, rm = made["codes"]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": "PO-1",
        "lines": [{"code": fg, "qty": 1, "rate": value}]}).json()["work_order"]
    return wo, fg, rm


def costs(tenant):
    res = tenant.get("/api/costs/by-project")
    assert res.status_code == 200, res.text
    return res.json()


def one(tenant, job_id):
    res = tenant.get("/api/costs/by-project/%d" % job_id)
    assert res.status_code == 200, res.text
    return res.json()


# --- The figures ------------------------------------------------------------

def test_a_project_with_nothing_on_it_reads_as_zero(tenant):
    """Not an error, and not blank. A job that has sold nothing has sold nought."""
    job = project(tenant)
    row = [r for r in costs(tenant)["projects"] if r["job_id"] == job["id"]][0]
    assert row["sold"] == 0 and row["cost"] == 0 and row["margin"] == 0
    assert row["margin_percent"] == 0, "no division by a zero sale"


def test_what_the_work_orders_promise_is_the_sold_figure(tenant):
    job = project(tenant)
    sold(tenant, job, 250000)
    row = [r for r in costs(tenant)["projects"] if r["job_id"] == job["id"]][0]
    assert row["sold"] == 250000
    assert row["work_orders"] == 1


def test_a_purchase_order_is_a_cost_before_any_bill_arrives(tenant):
    """Money promised is money committed. Waiting for the bill to count it is
    how a job looks profitable right up until the post arrives."""
    job = project(tenant)
    sold(tenant, job, 100000)
    tenant.post("/api/purchase-orders", json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 30000,
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 30000}]})
    row = one(tenant, job["id"])
    assert row["committed"] == 30000
    assert row["cost"] == 30000, "committed counts as cost with no bill in sight"
    assert row["margin"] == 70000


def test_the_budget_is_the_estimate_and_the_commitments_are_the_promises(tenant):
    """They are different numbers and the screen keeps them apart."""
    job = project(tenant)
    wo, fg, rm = sold(tenant, job, 100000)
    tenant.post("/api/erp/bom/build", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": fg, "rm_code": rm, "qty": 1, "rate": 40000}]})
    row = one(tenant, job["id"])
    assert row["budgeted_cost"] == 40000, "what the budget said it would take"
    assert row["cost"] == 0, "nothing has actually been committed to anybody"


def test_committing_more_than_the_budget_is_called_out(tenant):
    """The number that starts an argument, so it is not left to be worked out."""
    job = project(tenant)
    wo, fg, rm = sold(tenant, job, 100000)
    tenant.post("/api/erp/bom/build", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": fg, "rm_code": rm, "qty": 1, "rate": 30000}]})
    tenant.post("/api/purchase-orders", json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 45000,
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 45000}]})
    row = one(tenant, job["id"])
    assert row["over_budget"] == 15000


def test_a_project_within_its_budget_is_not_flagged(tenant):
    job = project(tenant)
    wo, fg, rm = sold(tenant, job, 100000)
    tenant.post("/api/erp/bom/build", json={
        "work_order_id": wo["id"],
        "lines": [{"fg_code": fg, "rm_code": rm, "qty": 1, "rate": 50000}]})
    tenant.post("/api/purchase-orders", json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 20000,
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 20000}]})
    assert one(tenant, job["id"])["over_budget"] == 0


def test_a_cancelled_order_stops_being_a_commitment(tenant):
    """It was promised and then it was not. Counting it would overstate the cost."""
    job = project(tenant)
    sold(tenant, job, 100000)
    po = tenant.post("/api/purchase-orders", json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 30000,
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 30000}]}).json()
    assert one(tenant, job["id"])["committed"] == 30000
    # The update takes the whole order, not a lone field.
    tenant.put("/api/purchase-orders/%d" % po["id"], json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 30000,
        "status": "Cancelled"})
    assert one(tenant, job["id"])["committed"] == 0


def test_a_margin_can_go_negative(tenant):
    """The whole reason to look at this screen, so it must not be hidden."""
    job = project(tenant)
    sold(tenant, job, 50000)
    tenant.post("/api/purchase-orders", json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 80000,
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 80000}]})
    row = one(tenant, job["id"])
    assert row["margin"] == -30000
    assert row["margin_percent"] == -60.0


# --- Getting from a total back to the paper ---------------------------------

def test_every_total_lists_what_it_is_made_of(tenant):
    """A figure you cannot trace is a figure nobody trusts."""
    job = project(tenant)
    sold(tenant, job, 100000)
    tenant.post("/api/purchase-orders", json={
        "supplier_name": "Steel Co", "job_id": job["id"], "amount": 30000,
        "line_items": [{"description": "Fe500D", "qty": 1, "price": 30000}]})
    row = one(tenant, job["id"])
    assert len(row["work_order_list"]) == 1
    assert row["purchase_order_list"][0]["supplier"] == "Steel Co"
    assert "bill_list" in row and "subcontract_list" in row


def test_the_whole_business_totals_across_its_projects(tenant):
    a, b = project(tenant, "Plot 3"), project(tenant, "Sector 12")
    sold(tenant, a, 100000)
    sold(tenant, b, 60000)
    s = costs(tenant)["summary"]
    assert s["projects"] >= 2
    assert s["sold"] == 160000


# --- Who may look ------------------------------------------------------------

def test_it_takes_the_right_to_see_the_reports(tenant):
    """A project's margin is not something every member of staff should read."""
    from conftest import make_employee
    emp = make_employee(tenant, permission_role="staff", password="Crew1234")
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    tenant.post("/api/employee/auth/login",
                json={"email": emp["email"], "password": "Crew1234"})
    assert tenant.get("/api/costs/by-project").status_code == 403
    tenant.post("/api/employee/auth/logout")


def test_one_tenant_cannot_read_anothers_project(tenant, second_tenant):
    job = project(tenant)
    assert second_tenant.get("/api/costs/by-project/%d" % job["id"]).status_code == 404


def test_it_downloads(tenant):
    project(tenant)
    res = tenant.get("/api/costs/by-project.xlsx")
    assert res.status_code == 200
    assert "cost_by_project.xlsx" in res.headers.get("content-disposition", "")
