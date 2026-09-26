"""The firm's departments as access levels, and approvals that reach somebody.

Each department opens its own work and no other's. Anything sent for approval
lands in front of a person who can decide it: the manager set for the raiser,
or when nobody is set - which is most people - the nearest rank above them
that holds the right, and from the top of the staff, the owner.
"""
import main
from conftest import make_employee


PASSWORD = "Crew1234"


def person(tenant, role, **over):
    emp = make_employee(tenant, permission_role=role, password=PASSWORD, **over)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login", json={"email": emp["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


def inbox(client):
    res = client.get("/api/approvals/inbox")
    assert res.status_code == 200, res.text
    return res.json()["items"]


def decide(client, item, decision="approve", note="Checked"):
    return client.post("/api/approvals/decide", json={"kind": item["kind"], "id": item["id"],
                                                      "decision": decision, "note": note})


ESTIMATE = {"title": "Vanya City STP"}
ADJUST = {"item_code": "RM0001", "counted": 10}
RFQ = {"title": "Cement for raft", "lines": [{"description": "OPC 53", "qty": 100}]}


# --- The departments ----------------------------------------------------------

def test_the_departments_are_the_access_levels_on_offer(tenant):
    roles = {r["code"]: r for r in tenant.get("/api/hr/levels").json()["permission_roles"]}
    for code, label in (("planning_billing", "Planning & Billing"), ("accounts", "Accounts"),
                        ("stores", "Stores"), ("purchase", "Purchase"), ("hr_admin", "HR admin"),
                        ("construction", "Construction management team"),
                        ("project_manager", "Project manager"), ("head_projects", "Head projects")):
        assert roles[code]["label"] == label
        assert not roles[code].get("retired")
    # The first presets are still honoured for whoever holds them.
    assert roles["manager"]["retired"] and roles["supervisor"]["retired"]


def test_each_department_holds_its_own_work_and_not_the_others():
    R = main.ROLE_PERMISSIONS
    assert "stores.manage" in R["stores"] and "billing.manage" not in R["stores"]
    assert "purchase.manage" in R["purchase"] and "subcontracts.approve" not in R["purchase"]
    assert "billing.manage" in R["planning_billing"] and "subcontracts.approve" not in R["planning_billing"]
    assert "bills.pay" in R["accounts"] and "bills.approve" not in R["accounts"]
    assert "subcontracts.approve" in R["project_manager"]
    assert R["project_manager"] < R["head_projects"]
    assert "workorders.approve" not in R["head_projects"]      # the MD's signature stays the owner's
    # Nobody on an older preset lost a screen when the work was split out.
    assert {"billing.manage", "purchase.manage", "stores.manage", "accounts.manage"} <= R["manager"]


def test_the_store_counts_stock_but_does_not_draw_up_tenders(tenant):
    sign_in(tenant, person(tenant, "stores"))
    assert tenant.post("/api/estimates", json=ESTIMATE).status_code == 403
    assert tenant.post("/api/stock/adjustments", json=ADJUST).status_code != 403


def test_billing_draws_up_tenders_but_does_not_touch_the_store_or_buy(tenant):
    sign_in(tenant, person(tenant, "planning_billing"))
    assert tenant.post("/api/stock/adjustments", json=ADJUST).status_code == 403
    assert tenant.post("/api/rfqs", json=RFQ).status_code == 403
    assert tenant.post("/api/estimates", json=ESTIMATE).status_code == 200


def test_purchase_keeps_the_orders_the_owner_used_to_keep_alone(tenant):
    sign_in(tenant, person(tenant, "purchase"))
    assert tenant.get("/api/purchase-orders").status_code == 200
    assert tenant.post("/api/rfqs", json=RFQ).status_code == 200
    assert tenant.post("/api/suppliers", json={"name": "Ramco Cements"}).status_code == 200
    made = tenant.post("/api/purchase-orders", json={"supplier_name": "UltraTech", "amount": 5000.0})
    assert made.status_code == 200, made.text
    # A buyer's order goes for approval the moment it exists.
    assert made.json()["order"]["approval_status"] == "pending"
    assert tenant.post("/api/estimates", json=ESTIMATE).status_code == 403


def test_approval_is_not_given_by_changing_the_status(tenant):
    sign_in(tenant, person(tenant, "purchase"))
    order = tenant.post("/api/purchase-orders", json={"supplier_name": "UltraTech", "amount": 5000.0}).json()["order"]
    res = tenant.put("/api/purchase-orders/%d" % order["id"],
                     json={"supplier_name": "UltraTech", "amount": 5000.0, "status": "Approved"})
    assert res.status_code in (403, 409)


def test_accounts_pays_but_does_not_draw_up_client_bills(tenant):
    sign_in(tenant, person(tenant, "accounts"))
    assert tenant.post("/api/ra-bills", json={"work_order_id": 1}).status_code == 403
    assert tenant.post("/api/estimates", json=ESTIMATE).status_code == 403


# --- Where a submission goes ---------------------------------------------------

def test_an_order_with_no_manager_set_goes_to_the_project_manager(tenant, portal):
    pm = person(tenant, "project_manager")
    person(tenant, "construction")          # level with purchase, so not them
    person(tenant, "accounts")              # pays, does not approve
    buyer = person(tenant, "purchase")
    sign_in(portal, buyer)
    res = portal.post("/api/employee/purchase-orders", json={"supplier_name": "Jindal", "amount": 90000.0})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending"
    assert res.json()["next_approver"].startswith(pm["first_name"])

    sent = portal.get("/api/approvals/sent").json()["items"]
    assert sent[0]["status"] == "pending" and sent[0]["waiting_on"].startswith(pm["first_name"])

    sign_in(portal, pm)
    items = [i for i in inbox(portal) if i["kind"] == "step"]
    assert len(items) == 1 and items[0]["kind_label"] == "Purchase order"
    assert decide(portal, items[0]).json()["status"] == "approved"


def test_the_manager_set_for_somebody_still_comes_first(tenant, portal):
    person(tenant, "project_manager")
    boss = person(tenant, "construction")
    hand = person(tenant, "staff", reports_to=boss["id"])
    sign_in(portal, hand)
    res = portal.post("/api/employee/bills", json={"vendor_name": "Hardware shop", "amount": 800.0})
    assert res.json()["next_approver"].startswith(boss["first_name"])


def test_a_site_cost_goes_to_the_engineer_on_that_site(tenant, portal):
    near = tenant.post("/api/jobs", json={"name": "Kokapet towers", "customer_name": "X"}).json()
    far = tenant.post("/api/jobs", json={"name": "Vanya City", "customer_name": "Y"}).json()
    elsewhere = person(tenant, "construction")
    here = person(tenant, "construction")
    hand = person(tenant, "staff")
    for emp, job in ((elsewhere, far), (here, near), (hand, near)):
        res = tenant.put("/api/employees/%d" % emp["id"], json={"site_ids": [job["id"]]})
        assert res.status_code == 200, res.text
    sign_in(portal, hand)
    res = portal.post("/api/employee/bills", json={"vendor_name": "Diesel", "amount": 1200.0,
                                                   "job_id": near["id"]})
    assert res.json()["next_approver"].startswith(here["first_name"])


def test_the_head_of_projects_goes_to_the_owner(tenant, portal):
    head = person(tenant, "head_projects")
    person(tenant, "project_manager")
    sign_in(portal, head)
    res = portal.post("/api/employee/purchase-orders", json={"supplier_name": "Tata", "amount": 400000.0})
    assert res.json()["status"] == "pending"
    assert "owner" in res.json()["next_approver"]
    items = inbox(tenant)
    assert [i for i in items if i["kind"] == "step" and i["mine"]]
    # The owner's own queue reads it as an order, not as a bill.
    pending = tenant.get("/api/approvals/pending").json()["pending"]
    assert pending and pending[0]["entity_type"] == "purchase_order"


def test_the_owner_raising_their_own_paper_needs_nobody(tenant):
    res = tenant.post("/api/purchase-orders", json={"supplier_name": "Self", "amount": 10.0})
    assert res.status_code == 200
    assert res.json().get("approval_status") in ("none", None, "")


# --- Work orders to subcontractors ---------------------------------------------

def priced_order(client):
    unit = client.post("/api/wo/business-units", json={"name": "Yalavarti Projects", "code": "YP",
                                                       "gstin": "36AABCY1234H1ZX"}).json()
    con = client.post("/api/wo/contractors", json={"company_name": "Rani Labour %s" % id(client),
                                                   "pan": "AAAPR1234C"}).json()
    job = client.post("/api/jobs", json={"name": "295 KLD STP", "customer_name": "L&T"}).json()
    order = client.post("/api/wo/orders", json={
        "business_unit_id": unit["id"], "contractor_id": con["id"], "job_id": job["id"],
        "department": "Civil", "work_type": "Civil", "subject": "Shuttering and concreting",
        "commencement_date": "2026-10-01", "completion_date": "2027-03-31"}).json()["order"]
    res = client.put("/api/wo/orders/%d/boq" % order["id"], json={"lines": [
        {"item_description": "Shuttering", "uom": "sqm", "quantity": 1000, "unit_rate": 180}]})
    assert res.status_code == 200, res.text
    return res.json()["order"]


def test_a_work_order_reaches_the_project_manager_and_is_approved_from_the_inbox(tenant, portal):
    order = priced_order(tenant)
    pm = person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    sign_in(portal, qs)
    res = portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert res.status_code == 200, res.text
    assert pm["first_name"] in " ".join(res.json()["order"]["pending_with"])
    # Billing drafts; billing does not approve.
    assert portal.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 403
    assert not [i for i in inbox(portal) if i["kind"] == "subcontract_order"]

    sign_in(portal, pm)
    notes = portal.get("/api/employee/notifications").json()
    notes = notes.get("notifications", notes) if isinstance(notes, dict) else notes
    assert any(order["wo_number"] in (n.get("message") or "") for n in notes)
    item = [i for i in inbox(portal) if i["kind"] == "subcontract_order"][0]
    assert item["number"] == order["wo_number"] and item["pdf"].endswith("document.pdf")
    res = decide(portal, item, note="")
    assert res.status_code == 200, res.text
    assert res.json()["order"]["status"] == "APPROVED"


def test_nobody_approves_the_work_order_they_raised(tenant, portal):
    order = priced_order(tenant)
    pm = person(tenant, "project_manager")
    sign_in(portal, pm)
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = portal.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 403
    assert "somebody else" in res.json()["detail"]
    # The owner can.
    item = [i for i in inbox(tenant) if i["kind"] == "subcontract_order"][0]
    assert decide(tenant, item, note="").status_code == 200


def test_sending_one_back_needs_a_reason(tenant):
    order = priced_order(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    item = [i for i in inbox(tenant) if i["kind"] == "subcontract_order"][0]
    assert decide(tenant, item, "reject", "").status_code == 400
    res = decide(tenant, item, "reject", "Rate for shuttering too high")
    assert res.status_code == 200 and res.json()["order"]["status"] == "DRAFT"


def test_a_right_granted_on_top_of_a_department_counts(tenant, portal):
    order = priced_order(tenant)
    lead = person(tenant, "construction")
    res = tenant.put("/api/employees/%d/permissions" % lead["id"], json={
        "permission_role": "construction",
        "permissions": sorted(main.ROLE_PERMISSIONS["construction"] | {"subcontracts.approve"})})
    assert res.status_code == 200, res.text
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    sign_in(portal, lead)
    assert [i for i in inbox(portal) if i["kind"] == "subcontract_order"]


# --- RA bills and leave --------------------------------------------------------

def test_an_ra_bill_sent_for_certifying_reaches_the_certifier(tenant, portal):
    from test_measurement_and_ra_bills import placed_order, measure, line_of, raise_bill
    wo = placed_order(tenant)
    measure(tenant, wo["id"], line_of(tenant, wo["id"]), 100)
    bill = raise_bill(tenant, wo["id"]).json()["bill"]
    pm = person(tenant, "project_manager")
    assert tenant.post("/api/ra-bills/%d/submit" % bill["id"], json={}).status_code == 200
    sign_in(portal, pm)
    item = [i for i in inbox(portal) if i["kind"] == "ra_bill"][0]
    assert item["approve_label"] == "Certify"
    res = decide(portal, item, note="")
    assert res.status_code == 200, res.text
    assert res.json()["bill"]["status"] == "CERTIFIED"


def test_leave_is_decided_by_the_crews_own_manager_or_hr(tenant, portal):
    boss = person(tenant, "construction")
    other = person(tenant, "construction")
    hand = person(tenant, "staff", reports_to=boss["id"])
    sign_in(portal, hand)
    portal.post("/api/employee/leave", json={"leave_type": "annual", "start_date": "2026-10-05",
                                             "end_date": "2026-10-06", "reason": "Family function"})
    sign_in(portal, other)
    assert not [i for i in inbox(portal) if i["kind"] == "leave"]
    sign_in(portal, boss)
    item = [i for i in inbox(portal) if i["kind"] == "leave"][0]
    res = decide(portal, item, note="")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"


def test_a_stranger_sees_no_inbox(client):
    assert client.get("/api/approvals/inbox").status_code == 401
    assert client.post("/api/approvals/decide", json={"kind": "step", "id": 1,
                                                      "decision": "approve"}).status_code == 401


def test_another_company_cannot_decide_our_paper(tenant, second_tenant):
    order = priced_order(tenant)
    tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = second_tenant.post("/api/approvals/decide", json={"kind": "subcontract_order", "id": order["id"],
                                                            "decision": "approve", "note": "x"})
    assert res.status_code == 404


# --- The office screens a department opens ---------------------------------------

def test_accounts_works_the_supplier_bills_and_projects_screens(tenant, portal):
    pm = person(tenant, "project_manager")
    acc = person(tenant, "accounts")
    sign_in(portal, acc)
    assert portal.get("/api/bills").status_code == 200
    assert portal.get("/api/jobs").status_code == 200
    assert portal.get("/api/dashboard-summary").status_code == 200
    made = portal.post("/api/bills", json={"vendor_name": "Sri Sai Steel", "amount": 45000.0})
    assert made.status_code == 200, made.text
    # Entered by accounts, it goes to be approved like any other cost...
    assert made.json()["status"] == "pending"
    bill_id = made.json()["bill"]["id"]
    # ...and accounts cannot pay it, or mark it paid, until it is.
    assert portal.post("/api/bills/%d/pay" % bill_id).status_code == 403
    portal.put("/api/bills/%d" % bill_id, json={"status": "Paid", "amount_paid": 45000.0})
    assert tenant.get("/api/bills/%d" % bill_id).json()["status"] != "Paid"

    sign_in(portal, pm)
    item = [i for i in inbox(portal) if i["kind"] == "step"][0]
    assert decide(portal, item).json()["status"] == "approved"
    sign_in(portal, acc)
    assert portal.post("/api/bills/%d/pay" % bill_id).status_code == 200


def test_a_site_login_does_not_read_the_office_money(tenant):
    sign_in(tenant, person(tenant, "staff"))
    assert tenant.get("/api/jobs").status_code == 403
    assert tenant.get("/api/bills").status_code == 403
    assert tenant.get("/api/reports/profit-loss").status_code == 403
