"""Head office: HO QS and HO Coordinator.

Head office is two people who look after every site at once. They sign in at the same page as
everybody else and land on the HO portal. HO QS is the only one in the business - with the Master -
who opens a vendor code, a work order (the client's or a sub contractor's) or a BOQ. The coordinator
sees all of it, follows up what is waiting and keeps drafts up to date, but opens none of them. Three
sites each registering gangs and raising orders is how one gang ends up with two vendor codes.
"""
import uuid

from conftest import as_owner, make_employee


PASSWORD = "Head0ffice1"


def person(tenant, role, **over):
    emp = make_employee(tenant, permission_role=role, password=PASSWORD, **over)
    tenant.put("/api/employees/%d" % emp["id"], json={"status": "active"})
    return emp


def sign_in(client, emp):
    res = client.post("/api/employee/auth/login", json={"email": emp["email"], "password": PASSWORD})
    assert res.status_code == 200, res.text
    return client


def project(tenant, name="Kokapet Towers"):
    res = tenant.post("/api/jobs", json={"name": "%s %s" % (name, uuid.uuid4().hex[:4]), "customer_name": "L&T"})
    assert res.status_code == 200, res.text
    return res.json()


def vendor_body(**over):
    body = {"company_name": "Sri Balaji Civil Works %s" % uuid.uuid4().hex[:6],
            "pan": "AAAPB1234C", "gst_number": "36AAAPB1234C1Z5"}
    body.update(over)
    return body


def order_body(job, con, **over):
    body = {"contractor_id": con["id"], "job_id": job["id"], "department": "Civil",
            "work_type": "Civil", "subject": "Raft and columns, block A",
            "commencement_date": "2026-05-01", "completion_date": "2026-11-30",
            "gst_rate": 18, "tds_rate": 1}
    body.update(over)
    return body


def finished_good(tenant):
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "RCC M25 RAFT %s" % uuid.uuid4().hex[:4], "units_of_measure": "cum"}]})
    assert made.status_code == 200, made.text
    return made.json()["codes"][0]


def client_order_body(job, code):
    return {"job_id": job["id"], "reference": "LT/PO/7", "lines": [{"code": code, "qty": 250, "rate": 6800}]}


# --- The two people ------------------------------------------------------------

def test_both_are_access_levels_hr_can_give(tenant):
    roles = {r["code"]: r for r in tenant.get("/api/hr/levels").json()["permission_roles"]}
    assert roles["ho_qs"]["label"] == "HO QS"
    assert roles["ho_coordinator"]["label"] == "HO Coordinator"
    assert {"vendors.create", "workorders.create", "boq.create"} <= set(roles["ho_qs"]["permissions"])
    assert not {"vendors.create", "workorders.create", "boq.create"} & set(roles["ho_coordinator"]["permissions"])


def test_they_sign_in_at_the_same_door_and_are_told_they_are_head_office(tenant, portal):
    qs, co, site = person(tenant, "ho_qs"), person(tenant, "ho_coordinator"), person(tenant, "planning_billing")
    for emp, ho in ((qs, True), (co, True), (site, False)):
        me = sign_in(portal, emp).get("/api/employee/auth/me").json()
        assert me["head_office"] is ho, emp["permission_role"]
    assert sign_in(portal, qs).get("/api/employee/auth/me").json()["permission_role_label"] == "HO QS"


# --- Only HO QS opens them ---------------------------------------------------------

def test_ho_qs_opens_a_vendor_code_a_work_order_both_ways_and_a_boq(tenant, portal):
    job, code = project(tenant), finished_good(tenant)
    qs = sign_in(portal, person(tenant, "ho_qs"))

    con = qs.post("/api/wo/contractors", json=vendor_body())
    assert con.status_code == 200, con.text
    assert con.json()["vendor_code"].startswith("IV")

    wo = qs.post("/api/wo/orders", json=order_body(job, con.json()))
    assert wo.status_code == 200, wo.text
    assert wo.json()["order"]["status"] == "DRAFT"

    client_wo = qs.post("/api/erp/work-orders/build", json=client_order_body(job, code))
    assert client_wo.status_code == 200, client_wo.text

    boq = qs.post("/api/boqs", json={"job_id": job["id"]})
    assert boq.status_code == 200, boq.text


def test_the_coordinator_opens_none_of_them_and_is_told_who_does(tenant, portal):
    job, code = project(tenant), finished_good(tenant)
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    co = sign_in(portal, person(tenant, "ho_coordinator"))

    refusals = [
        (co.post("/api/wo/contractors", json=vendor_body()), "Vendor codes"),
        (co.post("/api/wo/orders", json=order_body(job, con)), "Work orders"),
        (co.post("/api/erp/work-orders/build", json=client_order_body(job, code)), "Work orders"),
        (co.post("/api/boqs", json={"job_id": job["id"]}), "BOQs"),
    ]
    for res, what in refusals:
        assert res.status_code == 403, res.text
        assert res.json()["detail"].startswith(what + " are opened by HO QS"), res.text


def test_nobody_on_a_site_opens_them_either(tenant, portal):
    """Whole-company, not just head office: the planner and the project manager used to."""
    job = project(tenant)
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    for role in ("planning_billing", "project_manager", "head_projects", "construction"):
        who = sign_in(portal, person(tenant, role))
        assert who.post("/api/wo/contractors", json=vendor_body()).status_code == 403, role
        assert who.post("/api/wo/orders", json=order_body(job, con)).status_code == 403, role
        assert who.post("/api/boqs", json={"job_id": job["id"]}).status_code == 403, role


def test_the_master_still_opens_all_three(tenant):
    job, code = project(tenant), finished_good(tenant)
    con = tenant.post("/api/wo/contractors", json=vendor_body())
    assert con.status_code == 200
    assert tenant.post("/api/wo/orders", json=order_body(job, con.json())).status_code == 200
    assert tenant.post("/api/erp/work-orders/build", json=client_order_body(job, code)).status_code == 200
    assert tenant.post("/api/boqs", json={"job_id": job["id"]}).status_code == 200


def test_ticking_the_box_by_hand_for_somebody_else_does_not_give_it(tenant, portal):
    """The way to give somebody these is to make them HO QS - never one box at a time."""
    emp = person(tenant, "planning_billing")
    res = tenant.put("/api/employees/%d/permissions" % emp["id"], json={
        "permission_role": "planning_billing",
        "permissions": ["self.service", "billing.manage", "workorders.manage", "vendors.create", "boq.create"]})
    assert res.status_code == 200, res.text
    assert "vendors.create" not in res.json()["permissions"]
    who = sign_in(portal, emp)
    assert "boq.create" not in who.get("/api/employee/auth/me").json()["permissions"]
    assert who.post("/api/wo/contractors", json=vendor_body()).status_code == 403


def test_a_copy_and_an_amendment_are_new_orders_so_ho_qs_makes_them(tenant, portal):
    job = project(tenant)
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    order = tenant.post("/api/wo/orders", json=order_body(job, con)).json()["order"]
    co = sign_in(portal, person(tenant, "ho_coordinator"))
    assert co.post("/api/wo/orders/%d/copy" % order["id"]).status_code == 403
    qs = sign_in(portal, person(tenant, "ho_qs"))
    assert qs.post("/api/wo/orders/%d/copy" % order["id"]).status_code == 200


def test_only_ho_qs_changes_a_vendor_code_but_the_coordinator_keeps_the_form_up_to_date(tenant, portal):
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    body = vendor_body(company_name=con["company_name"], phone_number="9849012345")
    co = sign_in(portal, person(tenant, "ho_coordinator"))
    assert co.put("/api/wo/contractors/%d" % con["id"], json=body).status_code == 200
    moved = co.put("/api/wo/contractors/%d" % con["id"], json=dict(body, vendor_code="IV9999"))
    assert moved.status_code == 403
    assert "HO QS" in moved.json()["detail"]
    qs = sign_in(portal, person(tenant, "ho_qs"))
    assert qs.put("/api/wo/contractors/%d" % con["id"], json=dict(body, vendor_code="IV9999")).status_code == 200


# --- Head office sees every site ------------------------------------------------------

def test_head_office_sees_every_order_and_a_site_sees_only_its_own(tenant, portal):
    job = project(tenant)
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    order = tenant.post("/api/wo/orders", json=order_body(job, con)).json()["order"]

    co = sign_in(portal, person(tenant, "ho_coordinator"))
    assert order["id"] in [o["id"] for o in co.get("/api/wo/orders").json()["orders"]]
    assert co.get("/api/wo/orders/%d" % order["id"]).status_code == 200
    # Keeping a draft up to date is the coordinator's job.
    edited = co.put("/api/wo/orders/%d" % order["id"], json={"subject": "Raft, columns and slab, block A",
                                                              "department": "Civil"})
    assert edited.status_code == 200, edited.text

    site = sign_in(portal, person(tenant, "planning_billing"))
    assert order["id"] not in [o["id"] for o in site.get("/api/wo/orders").json()["orders"]]


def test_the_coordinator_cannot_decide_who_else_sees_an_order_ho_qs_made(tenant, portal):
    job = project(tenant)
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    qs_emp = person(tenant, "ho_qs")
    order = sign_in(portal, qs_emp).post("/api/wo/orders", json=order_body(job, con)).json()["order"]
    assert portal.get("/api/wo/orders/%d/access" % order["id"]).status_code == 200
    co = sign_in(portal, person(tenant, "ho_coordinator"))
    assert co.get("/api/wo/orders/%d/access" % order["id"]).status_code == 403


# --- The HO portal --------------------------------------------------------------------

def test_the_portal_counts_what_head_office_looks_after(tenant, portal):
    job, other = project(tenant), project(tenant, "Narsingi Villas")
    con = tenant.post("/api/wo/contractors", json=vendor_body()).json()
    tenant.post("/api/wo/orders", json=order_body(job, con))
    tenant.post("/api/boqs", json={"job_id": job["id"]})

    co = sign_in(portal, person(tenant, "ho_coordinator"))
    view = co.get("/api/ho/overview")
    assert view.status_code == 200, view.text
    data = view.json()
    assert data["person"]["role"] == "ho_coordinator"
    assert data["person"]["may_create"] == {"vendors": False, "work_orders": False, "boq": False}
    assert data["vendors"]["registered"] >= 1
    assert data["subcontract_orders"]["draft"] >= 1
    assert data["boqs"]["count"] >= 1
    assert other["id"] in [j["id"] for j in data["projects_without_boq"]]
    assert job["id"] not in [j["id"] for j in data["projects_without_boq"]]
    assert any(d["kind"] == "subcontract_order" for d in data["drafts"])

    qs = sign_in(portal, person(tenant, "ho_qs")).get("/api/ho/overview").json()
    assert qs["person"]["may_create"] == {"vendors": True, "work_orders": True, "boq": True}

    as_owner(tenant)
    assert tenant.get("/api/ho/overview").json()["person"]["role"] == "owner"


def test_the_portal_is_head_offices_not_a_sites(tenant, portal):
    site = sign_in(portal, person(tenant, "project_manager"))
    assert site.get("/api/ho/overview").status_code == 403


def test_the_follow_up_list_says_on_whom_each_thing_waits(tenant, portal):
    """A registration made by HO QS waits for somebody who approves - the coordinator chases it."""
    qs = sign_in(portal, person(tenant, "ho_qs"))
    made = qs.post("/api/wo/contractors", json=vendor_body()).json()
    assert made["registration_status"] == "PENDING"
    co = sign_in(portal, person(tenant, "ho_coordinator"))
    waiting = co.get("/api/ho/overview").json()["waiting"]
    assert any(w["kind"] == "contractor" and w["id"] == made["id"] for w in waiting)
    assert all(w["kind"] != "leave" for w in waiting)


# --- A won tender ----------------------------------------------------------------------

def _won_tender(who):
    est = who.post("/api/estimates", json={"title": "295 KLD STP %s" % uuid.uuid4().hex[:4],
                                           "customer_name": "L&T", "overhead_percent": 0, "profit_percent": 0})
    assert est.status_code == 200, est.text
    est = est.json()["estimate"]
    who.post("/api/estimates/%d/items" % est["id"], json={"item_no": "1.1", "description": "M25 RCC raft",
                                                         "uom": "cum", "quantity": 250, "cost_rate": 6800})
    assert who.post("/api/estimates/%d/submit" % est["id"]).status_code == 200
    out = who.post("/api/estimates/%d/win" % est["id"])
    assert out.status_code == 200, out.text
    return out.json()


def test_a_tender_won_by_the_planner_leaves_the_work_order_to_ho_qs(tenant, portal):
    planner = sign_in(portal, person(tenant, "planning_billing"))
    out = _won_tender(planner)
    assert out["estimate"]["status"] == "WON"
    assert "work_order" not in out and not out["estimate"]["work_order_id"]
    assert "HO QS" in out["message"]
    est_id = out["estimate"]["id"]
    assert planner.post("/api/estimates/%d/work-order" % est_id).status_code == 403

    qs = sign_in(portal, person(tenant, "ho_qs"))
    made = qs.post("/api/estimates/%d/work-order" % est_id)
    assert made.status_code == 200, made.text
    assert made.json()["work_order"]["total_value"] == 250 * 6800
    assert made.json()["estimate"]["work_order_id"] == made.json()["work_order"]["id"]
    assert qs.post("/api/estimates/%d/work-order" % est_id).status_code == 409


def test_a_tender_won_by_the_master_still_draws_up_its_order(tenant):
    out = _won_tender(tenant)
    assert out["work_order"]["status"] == "Draft"


# --- Where HO QS sits on the approval ladder ----------------------------------------------

def _route(tenant, raiser):
    """The people a paper from `raiser` passes, lowest first, as the approval chain builds it."""
    import main
    from app.services.approvals import hierarchy_chain
    db = main.database.SessionLocal()
    try:
        emp = db.query(main.models.DBEmployee).filter(main.models.DBEmployee.id == raiser["id"]).first()
        rungs = hierarchy_chain(db, emp.client_id, emp.id, "subcontracts.approve")
        return [r["name"] for r in rungs]
    finally:
        db.close()


def test_what_a_site_raises_goes_project_manager_then_ho_qs_then_head_projects_then_the_master(tenant):
    site = person(tenant, "construction")
    pm = person(tenant, "project_manager")
    qs = person(tenant, "ho_qs")
    head = person(tenant, "head_projects")
    person(tenant, "ho_coordinator")
    names = _route(tenant, site)
    first = lambda e: "%s %s" % (e["first_name"], e["last_name"])
    assert names[:4] == [first(pm), first(qs), first(head), names[3]]
    assert names[3].endswith("(Master)") or names[3] == "the Master"
    assert len(names) == 4


def test_the_coordinator_is_never_on_the_route(tenant):
    site = person(tenant, "construction")
    co = person(tenant, "ho_coordinator")
    assert "%s %s" % (co["first_name"], co["last_name"]) not in _route(tenant, site)


def test_the_order_ho_qs_raises_still_goes_to_the_project_manager_first(tenant):
    qs = person(tenant, "ho_qs")
    pm = person(tenant, "project_manager")
    assert _route(tenant, qs)[0] == "%s %s" % (pm["first_name"], pm["last_name"])
