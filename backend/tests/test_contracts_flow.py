"""The last three steps of the contracts flow.

The document the flow comes from ends at a screen where the managing director
signs off every project, and gets there by way of adding a customer and placing
the order. These cover that run, including the points where it must refuse.
"""


def make_customer(tenant, name="Fairview Homes", **extra):
    body = {"name": name, "contact_person": "R. Menon",
            "email": "accounts@fairview.in", "phone_number": "9876500000",
            "gstin": "36aabcf1234h1zx", "city": "Hyderabad", "state": "Telangana"}
    body.update(extra)
    return tenant.post("/api/customers", json=body)


def build_order(tenant, place=True, budget=True):
    job = tenant.post("/api/jobs", json={
        "name": "Fairview plot 3", "customer_name": "Fairview Homes"}).json()
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "SUPPLY OF CONDUIT", "units_of_measure": "Meters"},
        {"kind": "RM", "item_name": "20MM CONDUIT", "units_of_measure": "Meters"},
    ]}).json()
    fg, rm = made["codes"]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": "PO-1",
        "lines": [{"code": fg, "qty": 100, "rate": 60}]}).json()["work_order"]
    if budget:
        tenant.post("/api/erp/bom/build", json={
            "work_order_id": wo["id"],
            "lines": [{"fg_code": fg, "rm_code": rm, "qty": 105, "rate": 40}]})
    if place:
        tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"])
    return wo


# --- customers -------------------------------------------------------------

def test_a_customer_is_added_with_the_detail_a_contract_needs(tenant):
    res = make_customer(tenant)
    assert res.status_code == 200
    row = res.json()
    assert row["code"] == "CUST-0001"
    assert row["contact_person"] == "R. Menon"
    assert row["gstin"] == "36AABCF1234H1ZX", "a GST number is stored as it is printed"
    assert row["city"] == "Hyderabad"


def test_customer_codes_run_in_sequence(tenant):
    assert make_customer(tenant, name="One").json()["code"] == "CUST-0001"
    assert make_customer(tenant, name="Two").json()["code"] == "CUST-0002"


def test_the_same_customer_is_not_added_twice(tenant):
    make_customer(tenant, name="Fairview Homes")
    again = make_customer(tenant, name="FAIRVIEW HOMES")
    assert again.status_code == 409, (
        "two rows for one customer would split their projects between them")


def test_a_customer_needs_a_name(tenant):
    assert tenant.post("/api/customers", json={"name": "   "}).status_code == 400


def test_the_customer_list_searches_and_counts_projects(tenant):
    cust = make_customer(tenant).json()
    tenant.post("/api/jobs", json={"name": "Plot 3", "contact_id": cust["id"],
                                   "customer_name": "Fairview Homes"})
    rows = tenant.get("/api/customers?q=fairview").json()["customers"]
    assert len(rows) == 1 and rows[0]["projects"] == 1
    assert tenant.get("/api/customers?q=zzz").json()["customers"] == []


def test_a_customer_can_be_corrected(tenant):
    cust = make_customer(tenant).json()
    res = tenant.put("/api/customers/%d" % cust["id"],
                     json={"name": "Fairview Homes Ltd", "phone_number": "9000000001"})
    assert res.status_code == 200
    assert res.json()["name"] == "Fairview Homes Ltd"
    assert res.json()["code"] == cust["code"], "correcting a name keeps the code"


def test_one_tenant_cannot_edit_another_tenants_customer(tenant, second_tenant):
    cust = make_customer(tenant).json()
    assert second_tenant.put("/api/customers/%d" % cust["id"],
                             json={"name": "Mine now"}).status_code == 404


# --- placing the order -----------------------------------------------------

def test_placing_an_order_takes_it_out_of_draft(tenant):
    wo = build_order(tenant, place=False)
    assert wo["status"] == "Draft"
    res = tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"])
    assert res.status_code == 200
    assert res.json()["work_order"]["status"] == "Placed"


def test_an_order_is_not_placed_twice(tenant):
    wo = build_order(tenant)
    assert tenant.post("/api/erp/work-orders/%d/place-order" % wo["id"]).status_code == 409


# --- the managing director's approval --------------------------------------

def test_the_inquiry_screen_shows_where_every_order_stands(tenant):
    build_order(tenant)
    body = tenant.get("/api/erp/inquiry").json()
    row = body["rows"][0]
    assert row["bom_status"] == "Allocated"
    assert row["md_approval"] == "Not sent"
    assert row["can_approve"] is True
    assert row["can_place"] is False
    assert body["summary"]["orders"] == 1
    assert body["summary"]["total_value"] == 6000.0


def test_the_md_approves_and_it_shows_on_the_order(tenant):
    wo = build_order(tenant)
    res = tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"],
                      json={"approve": True, "notes": "Go ahead"})
    assert res.status_code == 200
    assert res.json()["work_order"]["approval_status"] == "approved"
    assert tenant.get("/api/erp/inquiry").json()["rows"][0]["md_approval"] == "Approved"


def test_a_rejection_carries_its_reason_back(tenant):
    wo = build_order(tenant)
    tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"],
                json={"approve": False, "notes": "Rate is too high"})
    detail = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert detail["approval_status"] == "rejected"
    assert detail["rejection_reason"] == "Rate is too high"


def test_the_decision_is_written_to_the_same_history_as_the_staff_route(tenant):
    wo = build_order(tenant)
    tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"], json={"approve": True})
    history = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["approval_history"]
    assert any(h["approver_level"] == "MD" and h["status"] == "approved" for h in history)


def test_nothing_is_approved_before_it_is_placed(tenant):
    wo = build_order(tenant, place=False)
    res = tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"], json={"approve": True})
    assert res.status_code == 409


def test_nothing_is_approved_before_its_budget_is_allocated(tenant):
    """There is no point approving a price with no cost behind it."""
    wo = build_order(tenant, budget=False)
    res = tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"], json={"approve": True})
    assert res.status_code == 409
    assert "budget" in res.json()["detail"].lower()


def test_a_rejection_does_not_wait_for_a_budget(tenant):
    wo = build_order(tenant, budget=False)
    assert tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"],
                       json={"approve": False, "notes": "Wrong scope"}).status_code == 200


# --- Customers a business already had ---------------------------------------

def test_a_contact_from_before_gets_a_code(tenant):
    """The contacts billing already had are the same customers.

    They were names and phone numbers, from before a customer needed
    identifying on a contract. Left blank in the code column they read as
    half-migrated records rather than as customers.
    """
    tenant.post("/api/contacts", json={"name": "Old Billing Contact",
                                       "email": "ap@old.in"})
    rows = tenant.get("/api/customers").json()["customers"]
    older = [r for r in rows if r["name"] == "Old Billing Contact"][0]
    assert older["code"] == "CUST-0001"


def test_backfilled_codes_do_not_collide_with_new_ones(tenant):
    tenant.post("/api/contacts", json={"name": "Old One"})
    tenant.post("/api/contacts", json={"name": "Old Two"})
    tenant.get("/api/customers")                       # backfills both
    fresh = make_customer(tenant, name="Added Later").json()
    codes = [r["code"] for r in tenant.get("/api/customers").json()["customers"]]
    assert fresh["code"] == "CUST-0003"
    assert len(set(codes)) == len(codes), "every customer has its own code"


def test_a_code_once_given_does_not_move(tenant):
    first = tenant.get("/api/customers")
    tenant.post("/api/contacts", json={"name": "Steady Ltd"})
    before = [r for r in tenant.get("/api/customers").json()["customers"]
              if r["name"] == "Steady Ltd"][0]["code"]
    after = [r for r in tenant.get("/api/customers").json()["customers"]
             if r["name"] == "Steady Ltd"][0]["code"]
    assert before == after and first.status_code == 200


# --- A project finding its customer -----------------------------------------

def test_a_project_raised_by_name_belongs_to_that_customer(tenant):
    """The jobs screen only asks for a name, and that has to be enough.

    Without this the same business sits on both sides of the system with
    nothing joining them, and the customer shows no projects while plainly
    having several.
    """
    cust = make_customer(tenant, name="Fairview Homes").json()
    tenant.post("/api/jobs", json={"name": "Plot 3", "customer_name": "fairview homes"})
    rows = tenant.get("/api/customers?q=fairview").json()["customers"]
    assert rows[0]["id"] == cust["id"]
    assert rows[0]["projects"] == 1


def test_a_project_for_somebody_not_on_the_customer_list_is_still_allowed(tenant):
    """A name nobody has set up yet is a job to be done, not an error."""
    res = tenant.post("/api/jobs", json={"name": "One-off", "customer_name": "Passing Trade"})
    assert res.status_code == 200
    assert res.json()["customer_name"] == "Passing Trade"


def test_projects_counted_before_the_customer_existed_still_count(tenant):
    """The job came first, which is the ordinary way round.

    Somebody raises the job the day the call comes in and sets the customer
    up properly afterwards. Counting only jobs linked at the moment they were
    created would leave those out for ever.
    """
    tenant.post("/api/jobs", json={"name": "Plot 9", "customer_name": "Latecomer Ltd"})
    make_customer(tenant, name="Latecomer Ltd")
    rows = tenant.get("/api/customers?q=latecomer").json()["customers"]
    assert rows[0]["projects"] == 1


# --- who may do what -------------------------------------------------------
#
# The contracts screens were reachable only by the account holder, and the
# sign-off was gated on the same right that lets somebody build the order.
# These pin both down.

from conftest import make_employee


def staff_session(tenant, portal, role):
    """An employee of this tenancy, signed in on their own browser."""
    import uuid
    email = "crew-%s@example.com" % uuid.uuid4().hex[:8]
    make_employee(tenant, email=email, password="Crew1234",
                  permission_role=role, status="active")
    res = portal.post("/api/employee/auth/login",
                      json={"email": email, "password": "Crew1234"})
    assert res.status_code == 200, res.text
    return portal


def test_a_manager_can_add_a_customer(tenant, portal):
    crew = staff_session(tenant, portal, "manager")
    res = crew.post("/api/customers", json={"name": "Bridgeworks Ltd"})
    assert res.status_code == 200, res.text
    assert res.json()["code"] == "CUST-0001"


def test_staff_cannot_add_a_customer(tenant, portal):
    crew = staff_session(tenant, portal, "staff")
    assert crew.post("/api/customers", json={"name": "Sneaky Ltd"}).status_code == 403


def test_anyone_signed_in_can_read_the_customer_list(tenant, portal):
    """Picking the customer a project is for needs the list; hiding it would
    only mean the name gets retyped, and retyped differently."""
    make_customer(tenant)
    crew = staff_session(tenant, portal, "staff")
    res = crew.get("/api/customers")
    assert res.status_code == 200
    assert [c["name"] for c in res.json()["customers"]] == ["Fairview Homes"]


def test_building_a_work_order_does_not_carry_the_right_to_approve_it(tenant, portal):
    """The whole point of the step. A manager raises and budgets the order;
    signing it off is somebody else's decision."""
    wo = build_order(tenant)
    crew = staff_session(tenant, portal, "manager")
    res = crew.post("/api/erp/inquiry/%d/md-approval" % wo["id"], json={"approve": True})
    assert res.status_code == 403
    assert "MD sign-off" in res.json()["detail"]


def test_the_right_can_be_granted_to_one_person(tenant, portal):
    wo = build_order(tenant)
    import uuid
    email = "md-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(tenant, email=email, password="Crew1234",
                        permission_role="manager", status="active")
    tenant.put("/api/employees/%d" % emp["id"],
               json={"extra_permissions": "workorders.approve"})
    assert portal.post("/api/employee/auth/login",
                       json={"email": email, "password": "Crew1234"}).status_code == 200
    res = portal.post("/api/erp/inquiry/%d/md-approval" % wo["id"], json={"approve": True})
    assert res.status_code == 200, res.text
    assert res.json()["work_order"]["approval_status"] == "approved"


def test_the_owner_needs_no_grant(tenant):
    wo = build_order(tenant)
    assert tenant.post("/api/erp/inquiry/%d/md-approval" % wo["id"],
                       json={"approve": True}).status_code == 200
