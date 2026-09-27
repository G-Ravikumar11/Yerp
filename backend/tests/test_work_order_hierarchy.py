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
    order = priced_order(tenant)
    sign_in(portal, qs)
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
    order = priced_order(tenant)
    sign_in(portal, qs)
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    sign_in(portal, pm)
    res = portal.post("/api/wo/orders/%d/reject" % order["id"], json={"comments": "Rate for shuttering too high"})
    assert res.status_code == 200 and res.json()["order"]["status"] == "DRAFT"
    assert [s["status"] for s in route(tenant, order["id"])] == ["rejected", "cancelled", "cancelled"]


def test_the_owner_may_sign_at_any_point_and_it_is_the_last_word(tenant, portal):
    person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    order = priced_order(tenant)
    sign_in(portal, qs)
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.json()["order"]["status"] == "APPROVED"
    assert [s["status"] for s in route(tenant, order["id"])] == ["skipped", "approved"]


def test_somebody_who_has_left_is_passed_over(tenant, portal):
    pm = person(tenant, "project_manager")
    head = person(tenant, "head_projects")
    qs = person(tenant, "planning_billing")
    order = priced_order(tenant)
    sign_in(portal, qs)
    portal.post("/api/wo/orders/%d/submit" % order["id"], json={})
    tenant.put("/api/employees/%d" % pm["id"], json={"status": "terminated"})
    pending = tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["pending_with"]
    assert head["first_name"] in pending[0]


def test_the_owner_can_leave_the_last_signature_to_the_heads(tenant, portal):
    assert tenant.put("/api/approval-rules", json={"owner_signs_work_orders": False}).status_code == 200
    assert tenant.get("/api/approval-rules").json()["owner_signs_work_orders"] is False
    pm = person(tenant, "project_manager")
    qs = person(tenant, "planning_billing")
    order = priced_order(tenant)
    sign_in(portal, qs)
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
