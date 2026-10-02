"""Every work order climbs the hierarchy: the manager set for the person who
raised it, then one approver at each rank above them, then the owner - each
in turn, and each seeing it only when it is their turn."""
from conftest import make_employee
from test_departments_and_approvals import person, sign_in, inbox, decide, priced_order


def route(client, order_id):
    return client.get("/api/wo/orders/%d" % order_id).json()["order"]["approval_route"]


def test_the_route_climbs_every_rank_to_the_owner(tenant, portal):
    pm = person(tenant, "project_manager")
    head = person(tenant, "head_projects")
    qs = person(tenant, "planning_billing")
    sign_in(portal, qs)
    order = priced_order(portal)          # raised by the planner, as it is on site
    assert portal.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    steps = route(tenant, order["id"])
    assert [s["name"].split()[0] for s in steps[:2]] == [pm["first_name"], head["first_name"]]
    assert steps[2]["owner"] is True and steps[0]["status"] == "waiting"

    # Out of turn is refused, and says whose desk it is on.
    sign_in(portal, head)
    res = portal.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 403 and pm["first_name"] in res.json()["detail"]
    assert "comes to you after" in res.json()["detail"]
    assert not [i for i in inbox(portal) if i["kind"] == "subcontract_order"]

    sign_in(portal, pm)
    res = portal.post("/api/wo/orders/%d/approve" % order["id"], json={"comments": "Rates fine"})
    assert res.json()["order"]["status"] == "PROVISIONAL" and "passed to" in res.json()["message"]
    sign_in(portal, head)
    notes = portal.get("/api/employee/notifications").json()["notifications"]
    assert any(order["wo_number"] in n["message"] for n in notes)
    item = [i for i in inbox(portal) if i["kind"] == "subcontract_order"][0]
    assert "Step 2 of 3" in item["what"]
    assert decide(portal, item, note="").json()["order"]["status"] == "PROVISIONAL"

    item = [i for i in inbox(tenant) if i["kind"] == "subcontract_order"][0]
    assert item["mine"] is True
    assert decide(tenant, item, note="Authorised").json()["order"]["status"] == "APPROVED"
    assert [s["status"] for s in route(tenant, order["id"])] == ["approved", "approved", "approved"]


def test_sent_back_midway_it_returns_to_draft_and_the_route_closes(tenant, portal):
    pm = person(tenant, "project_manager")
    person(tenant, "head_projects")
    qs = person(tenant, "planning_billing")
    sign_in(portal, qs)
    order = priced_order(portal)          # raised by the planner, as it is on site
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    sign_in(portal, pm)
    res = portal.post("/api/wo/orders/%d/reject" % order["id"], json={"comments": "Rate for shuttering too high"})
    assert res.status_code == 200 and res.json()["order"]["status"] == "DRAFT"
    assert [s["status"] for s in route(tenant, order["id"])] == ["rejected", "cancelled", "cancelled"]


def test_the_owner_may_sign_at_any_point_and_it_is_the_last_word(tenant, portal):
    person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    sign_in(portal, qs)
    order = priced_order(portal)          # raised by the planner, as it is on site
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.json()["order"]["status"] == "APPROVED"
    assert [s["status"] for s in route(tenant, order["id"])] == ["skipped", "approved"]


def test_somebody_who_has_left_is_passed_over(tenant, portal):
    pm = person(tenant, "project_manager")
    head = person(tenant, "head_projects")
    qs = person(tenant, "planning_billing")
    sign_in(portal, qs)
    order = priced_order(portal)          # raised by the planner, as it is on site
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "terminated"})
    pending = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["pending_with"]
    assert head["first_name"] in pending[0]


def test_the_owner_can_leave_the_last_signature_to_the_heads(tenant, portal):
    assert tenant.put("/api/approval-rules", json={"owner_signs_work_orders": False}).status_code == 200
    assert tenant.get("/api/approval-rules").json()["owner_signs_work_orders"] is False
    pm = person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    sign_in(portal, qs)
    order = priced_order(portal)          # raised by the planner, as it is on site
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert len(route(tenant, order["id"])) == 1
    sign_in(portal, pm)
    assert portal.post("/api/wo/orders/%d/approve" % order["id"], json={}).json()["order"]["status"] == "APPROVED"


def test_a_client_work_order_climbs_the_same_way(tenant, portal):
    from test_erp_contracts import order_with_budget
    pm = person(tenant, "project_manager")
    head = person(tenant, "head_projects")
    qs = person(tenant, "planning_billing")
    job, wo = order_with_budget(tenant)
    sign_in(portal, qs)
    res = portal.post("/api/erp/work-orders/%d/submit" % wo["id"])
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending" and res.json()["chain_length"] == 3
    assert res.json()["next_approver"].startswith(pm["first_name"])
    sign_in(portal, pm)
    item = [i for i in inbox(portal) if i["kind"] == "step"][0]
    assert decide(portal, item).json()["status"] == "pending"
    sign_in(portal, head)
    item = [i for i in inbox(portal) if i["kind"] == "step"][0]
    assert decide(portal, item).json()["status"] == "pending"
    item = [i for i in inbox(tenant) if i["kind"] == "step" and i["mine"]][0]
    assert decide(tenant, item).json()["status"] == "approved"


def test_placing_a_client_order_on_site_waits_for_its_approvals(tenant, portal):
    """Placing is not a way round the route: the order is sent for approval,
    says whose desk it is on, and is not measured until the last signature."""
    from test_erp_contracts import order_with_budget
    pm = person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    job, wo = order_with_budget(tenant)
    sign_in(portal, qs)
    res = portal.post("/api/erp/work-orders/%d/place-order" % wo["id"])
    assert res.status_code == 200, res.text
    placed = res.json()["work_order"]
    assert placed["approval_status"] == "pending" and placed["status"] == "Awaiting Approval"
    assert placed["waiting_on"].startswith(pm["first_name"])
    assert "sent for approval" in res.json()["message"]
    listed = next(w for w in portal.get("/api/erp/work-orders").json()["work_orders"] if w["id"] == wo["id"])
    assert listed["waiting_on"].startswith(pm["first_name"])
    # Placing again while it waits is refused.
    assert portal.post("/api/erp/work-orders/%d/place-order" % wo["id"]).status_code == 409


# --- Who may see a draft -------------------------------------------------------------

def test_staff_see_only_the_orders_they_made_or_have_to_sign_or_were_shown(tenant, portal):
    pm = person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    site = person(tenant, "staff")
    # The owner's own draft is the owner's alone.
    owners = priced_order(tenant)
    sign_in(portal, qs)
    assert portal.get("/api/wo/orders/%d" % owners["id"]).status_code == 404
    assert owners["id"] not in [o["id"] for o in portal.get("/api/wo/orders").json()["orders"]]
    assert portal.get("/api/wo/orders/%d/document.pdf" % owners["id"]).status_code == 404
    # The planner's draft: theirs alone - not their senior's, not the site's.
    mine = priced_order(portal)
    assert portal.get("/api/wo/orders/%d" % mine["id"]).status_code == 200
    assert mine["id"] in [o["id"] for o in portal.get("/api/wo/orders").json()["orders"]]
    for other in (pm, site):
        sign_in(portal, other)
        assert portal.get("/api/wo/orders/%d" % mine["id"]).status_code == 404
        assert mine["id"] not in [o["id"] for o in portal.get("/api/wo/orders").json()["orders"]]
    assert tenant.get("/api/wo/orders/%d" % mine["id"]).status_code == 200      # the owner sees all
    # The maker can let someone in; nobody else but the owner can.
    sign_in(portal, qs)
    assert portal.put("/api/wo/orders/%d/access" % mine["id"], json={"employee_ids": [site["id"]]}).status_code == 200
    sign_in(portal, site)
    assert portal.get("/api/wo/orders/%d" % mine["id"]).status_code == 200
    assert portal.put("/api/wo/orders/%d/access" % mine["id"], json={"employee_ids": []}).status_code == 403
    # Sending the owner's order for approval shows it to whoever has to sign it, and to no one else.
    assert tenant.post("/api/wo/orders/%d/submit" % owners["id"], json={}).status_code == 200
    on_route = {r["name"] for r in tenant.get("/api/wo/orders/%d" % owners["id"]).json()["order"]["approval_route"]}
    for who in (qs, pm, site):
        sign_in(portal, who)
        name = "%s %s" % (who["first_name"], who["last_name"])
        seen = portal.get("/api/wo/orders/%d" % owners["id"]).status_code == 200
        assert seen == (name in on_route), name


def test_a_bill_climbs_every_rank_before_it_is_approved(tenant, portal):
    cm = person(tenant, "construction")
    pm = person(tenant, "project_manager")
    head = person(tenant, "head_projects")
    hand = person(tenant, "staff")
    sign_in(portal, hand)
    res = portal.post("/api/employee/bills", json={"vendor_name": "Hardware shop", "amount": 5000.0})
    assert res.json()["status"] == "pending" and res.json()["chain_length"] == 3
    for who in (cm, pm, head):
        sign_in(portal, who)
        item = [i for i in inbox(portal) if i["kind"] == "step"][0]
        out = decide(portal, item).json()
    assert out["status"] == "approved"


def test_the_manager_the_owner_set_is_asked_first_even_while_still_onboarding(tenant, portal):
    """People the owner adds with a login are 'onboarding' until somebody moves them on.
    The manager set for them is still their manager: the order goes to that person, not to
    whoever happens to hold the right first."""
    earlier = person(tenant, "project_manager")                  # created first, holds the right
    chosen = make_employee(tenant, permission_role="project_manager", password="Crew1234")
    tenant.put("/api/employees/%d" % chosen["id"], json={"status": "onboarding"})
    qs = make_employee(tenant, permission_role="planning_billing", password="Crew1234", reports_to=chosen["id"])
    tenant.put("/api/employees/%d" % qs["id"], json={"status": "onboarding"})
    sign_in(portal, qs)
    order = priced_order(portal)
    assert portal.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    first = route(tenant, order["id"])[0]
    assert chosen["last_name"] in first["name"] and first["status"] == "waiting"


def test_a_revision_goes_up_the_same_line_and_the_owner_may_decide_it(tenant, portal):
    """Amending is raising again: the revision is a draft that goes for approval like any order,
    the owner can approve it as raised, and approving it moves the old order to 'amended'."""
    person(tenant, "project_manager")
    base = priced_order(tenant)
    assert tenant.post("/api/wo/orders/%d/self-approve" % base["id"], json={}).json()["order"]["status"] == "APPROVED"
    rev = tenant.post("/api/wo/orders/%d/amend" % base["id"], json={}).json()["order"]
    assert rev["status"] == "DRAFT"
    assert "SUBMIT" in rev["actions"]
    sent = tenant.post("/api/wo/orders/%d/submit" % rev["id"], json={})
    assert sent.status_code == 200 and sent.json()["order"]["status"] == "PROVISIONAL"
    item = [i for i in inbox(tenant) if i["kind"] == "subcontract_order" and i["id"] == rev["id"]][0]
    assert item["mine"] is False and item["waiting_on"]            # with the manager, shown to the owner
    assert decide(tenant, item, note="").json()["order"]["status"] == "APPROVED"
    assert tenant.get("/api/wo/orders/%d" % base["id"]).json()["order"]["status"] == "AMENDED"
