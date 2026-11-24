"""A work order and a bill walked through their whole route, person by person, with the HO Coordinator in the
reporting line: site -> project manager -> HO Coordinator, and HO QS -> HO Coordinator. The coordinator signs where
somebody reports to them - and being there does not push the project manager or HO QS off the route."""
from app import db as database
from app import models
from conftest import budget_all
from test_boq import contractor_order, make_boq, saved
from test_budgeting import put_line
from test_subcontract_orders import sign_in, staff


def name(e):
    return "%s %s" % (e["first_name"], e["last_name"])


def line_up(tenant):
    p = {k: staff(tenant, role) for k, role in (("co", "ho_coordinator"), ("pm", "project_manager"), ("qs", "ho_qs"),
                                                 ("head", "head_projects"), ("site", "construction"))}
    for who, boss in (("pm", "co"), ("site", "pm"), ("qs", "co")):
        res = tenant.put("/api/employees/%d" % p[who]["id"], json={"reports_to": p[boss]["id"]})
        assert res.status_code == 200, res.text
    return p


def as_(portal, emp):
    portal.cookies.clear()
    sign_in(portal, emp)
    return portal


def test_a_work_order_from_ho_qs_goes_coordinator_project_manager_head_projects_master(tenant, portal):
    p = line_up(tenant)
    jid, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"] if l["kind"] == "item"}
    put_line(tenant, jid, lines["EXC"]["key"], [{"kind": "LABOUR", "description": "Gang", "uom": "cum",
                                                 "coefficient": 1, "rate": 200}])
    budget_all(tenant, jid, skip={lines["EXC"]["key"]})       # an order is sent only once the whole BOQ is budgeted (HO QS control)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    res = as_(portal, p["qs"]).post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert res.status_code == 200, res.text

    signed = []
    for _ in range(8):
        o = tenant.get("/api/wo/orders/%d" % order["id"]).json()
        o = o.get("order") or o
        waiting = [s for s in o["approval_route"] if s["status"] == "waiting"]
        if not waiting:
            break
        step = waiting[0]
        signed.append("Master" if step["owner"] else step["name"])
        if step["owner"]:
            r = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
        else:
            who = next(v for v in p.values() if name(v) == step["name"])
            r = as_(portal, who).post("/api/wo/orders/%d/approve" % order["id"], json={})
        assert r.status_code == 200, (step, r.text)
    assert signed == [name(p["co"]), name(p["pm"]), name(p["head"]), "Master"]
    assert o["status"] == "APPROVED"


def test_a_bill_from_site_goes_project_manager_coordinator_ho_qs_head_projects_master(tenant, portal):
    p = line_up(tenant)
    job = tenant.post("/api/jobs", json={"name": "Walk Towers"}).json()
    b = tenant.post("/api/bills", json={"number": "WALK-1", "vendor_name": "ACC Ltd", "amount": 40000, "tax_amount": 0,
                                        "total": 40000, "status": "Awaiting Payment", "job_id": job["id"]})
    assert b.status_code == 200, b.text
    b = b.json()
    res = tenant.post("/api/approvals/submit", json={"entity_type": "bill", "entity_id": b["id"],
                                                     "submitted_by": p["site"]["id"]})
    assert res.status_code == 200, res.text

    with database.SessionLocal() as db:
        steps = db.query(models.DBApprovalChain).filter(models.DBApprovalChain.entity_type == "bill",
                                                        models.DBApprovalChain.entity_id == b["id"]) \
            .order_by(models.DBApprovalChain.step).all()
        route = [(s.id, s.approver_id) for s in steps]
    by_id = {v["id"]: v for v in p.values()}
    assert [a for _, a in route if a] == [p["pm"]["id"], p["co"]["id"], p["qs"]["id"], p["head"]["id"]]

    for step_id, approver in route:
        if approver is None:
            continue
        r = as_(portal, by_id[approver]).post("/api/employee/approvals/%d/action" % step_id,
                                              json={"action": "approve", "notes": "Checked"})
        assert r.status_code == 200, (approver, r.text)
