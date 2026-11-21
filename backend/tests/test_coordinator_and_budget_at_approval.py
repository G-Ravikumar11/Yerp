"""The HO Coordinator is a step on the way up when somebody reports to them; and a work order is held against the budget
again when it is approved, and shown against it on the Budgeting page."""
from app import db as database
from app import models
from app.services.approvals import hierarchy_chain
from test_boq import contractor_order, make_boq, saved
from test_budgeting import put_line
from test_subcontract_orders import staff


def test_a_coordinator_somebody_reports_to_signs_on_the_way_up(tenant):
    coordinator = staff(tenant, "ho_coordinator")
    pm = staff(tenant, "project_manager")
    assert tenant.put("/api/employees/%d" % pm["id"], json={"reports_to": coordinator["id"]}).status_code == 200
    with database.SessionLocal() as db:
        client_id = db.get(models.DBEmployee, pm["id"]).client_id
        for right in ("subcontracts.approve", "bills.approve"):
            route = [r["employee_id"] for r in hierarchy_chain(db, client_id, pm["id"], right)]
            assert route and route[0] == coordinator["id"], (right, route)


def over_after_sending(tenant):
    jid, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"] if l["kind"] == "item"}
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    labour = lambda rate: put_line(tenant, jid, lines["EXC"]["key"], [{"kind": "LABOUR", "description": "Gang", "uom": "cum", "coefficient": 1, "rate": rate}])
    assert labour(200).status_code == 200
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    assert labour(100).status_code == 200                       # lowered after it was sent
    return jid, order


def test_a_budget_lowered_after_sending_stops_staff_approving_it(tenant):
    import pytest
    from fastapi import HTTPException
    from app.services.subcontract_orders import wo_apply
    _, order = over_after_sending(tenant)
    approver = staff(tenant, "head_projects")
    with database.SessionLocal() as db:
        row = db.get(models.DBSubcontractOrder, order["id"])
        client = db.get(models.DBClient, row.client_id)
        with pytest.raises(HTTPException) as refused:
            wo_apply(db, client, row, "APPROVE", approver["id"], "Head of projects")
        assert refused.value.status_code == 409 and "budget has changed" in refused.value.detail
        db.rollback()


def test_the_master_approves_it_only_with_a_reason(tenant):
    _, order = over_after_sending(tenant)
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409 and "budget has changed" in res.json()["detail"]
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={"comments": "Rates went up this season"})
    assert res.status_code == 200, res.text
    got = tenant.get("/api/wo/orders/%d" % order["id"]).json()
    assert "Rates went up this season" in (got.get("order") or got)["over_budget_reason"]


def test_the_budget_page_shows_what_was_given_on_work_orders(tenant):
    jid, order = over_after_sending(tenant)
    budget = tenant.get("/api/jobs/%d/budget" % jid).json()
    row = next(r for r in budget["rows"] if r.get("given_out"))
    # 100 cum at 150 given, against 500 cum x 100 budgeted for contractors on the line: within it.
    assert row["given_out"] == 15000 and row["given_over"] is False
