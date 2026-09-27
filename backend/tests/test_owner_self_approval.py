"""The owner's own work order is approved as it is issued; staff still send
theirs to somebody else. And the PDF can be shown inside the app's pages."""
from conftest import fund_order, make_employee
from test_letterhead_and_signing import an_order

PASSWORD = "Crew1234"


def test_the_owner_approves_and_issues_in_one_step(tenant):
    order, _, _ = an_order(tenant)
    res = tenant.post("/api/wo/orders/%d/self-approve" % order["id"], json={})
    assert res.status_code == 200, res.text
    assert res.json()["order"]["status"] == "APPROVED"
    moves = [h["action"] for h in tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"].get("history", [])]
    assert not moves or ("SUBMIT" in moves and "APPROVE" in moves)
    # Nothing was left waiting in anybody's queue.
    assert not [i for i in tenant.get("/api/approvals/inbox").json()["items"] if i["kind"] == "subcontract_order"]


def test_self_approval_still_needs_a_budget(tenant):
    order, _, _ = an_order(tenant)
    tenant.post("/api/wo/orders/%d/charge-budget" % order["id"], json={"budget_id": 0})
    job = tenant.post("/api/jobs", json={"name": "No budget here", "customer_name": "X"}).json()
    bare = tenant.post("/api/wo/orders", json={
        "business_unit_id": order["business_unit_id"], "contractor_id": order["contractor_id"], "job_id": job["id"],
        "department": "Civil", "subject": "Unbudgeted", "commencement_date": "2026-10-01",
        "completion_date": "2027-01-31"}).json()["order"]
    tenant.put("/api/wo/orders/%d/boq" % bare["id"], json={"lines": [
        {"item_description": "Plastering", "uom": "sqm", "quantity": 100, "unit_rate": 90}]})
    res = tenant.post("/api/wo/orders/%d/self-approve" % bare["id"], json={})
    assert res.status_code == 400 and "budget" in res.json()["detail"]
    assert tenant.get("/api/wo/orders/%d" % bare["id"]).json()["order"]["status"] == "DRAFT"


def test_an_overrun_is_approved_only_with_a_reason(tenant):
    order, _, _ = an_order(tenant)
    tight = tenant.post("/api/wo/projects/%d/budgets" % order["job_id"],
                        json={"name": "Tight", "allocated_amount": 100}).json()
    tenant.post("/api/wo/orders/%d/charge-budget" % order["id"], json={"budget_id": tight["id"], "only_blank": False})
    res = tenant.post("/api/wo/orders/%d/self-approve" % order["id"], json={})
    assert res.status_code == 409
    assert tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["status"] == "DRAFT"
    res = tenant.post("/api/wo/orders/%d/self-approve" % order["id"],
                      json={"comments": "Rates agreed with the client", "override": True})
    assert res.status_code == 200 and res.json()["order"]["status"] == "APPROVED"


def test_staff_cannot_approve_their_own(tenant, portal):
    order, _, _ = an_order(tenant)
    pm = make_employee(tenant, permission_role="project_manager", password=PASSWORD)
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "active"})
    portal.post("/api/employee/auth/login", json={"email": pm["email"], "password": PASSWORD})
    assert portal.post("/api/wo/orders/%d/self-approve" % order["id"], json={}).status_code in (401, 403)


def test_a_pdf_may_be_shown_inside_the_app_but_pages_may_not_be_framed(tenant):
    order, _, _ = an_order(tenant)
    pdf = tenant.get("/api/wo/orders/%d/document.pdf" % order["id"])
    assert pdf.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert tenant.get("/api/jobs").headers["X-Frame-Options"] == "DENY"
