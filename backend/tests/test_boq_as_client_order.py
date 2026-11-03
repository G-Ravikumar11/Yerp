"""The BOQ is the client's order: the store's consumption report and the programme's measured progress read it."""
from datetime import date, timedelta

from test_boq import contractor_order, make_boq, saved
from test_budgeting import put_line
from test_stock_control import receive, rm_item
from test_subcontract_orders import fund_order


def d(n):
    return (date.today() + timedelta(days=n)).isoformat()


def boq_with_lines(tenant):
    jid, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"] if l["kind"] == "item"}
    return jid, boq, lines


def test_consumption_compares_the_boq_budget_with_what_went_to_the_project(tenant):
    jid, boq, lines = boq_with_lines(tenant)
    cement = rm_item(tenant, uom="bag")
    # 120 cum of RCC, 7 bags of cement each: 840 bags budgeted at 400.
    put_line(tenant, jid, lines["RCC"]["key"], [{"kind": "MATERIAL", "description": "Cement", "uom": "bag", "coefficient": 7, "rate": 400, "item_code": cement}])
    receive(tenant, cement, 1000, 400)
    issue = tenant.post("/api/stock-issues", json={"job_id": jid, "lines": [{"item_code": cement, "quantity": 900}]}).json()["issue"]
    assert tenant.post("/api/stock-issues/%d/post" % issue["id"], json={}).status_code == 200

    c = tenant.get("/api/stock/consumption/boq/%d" % boq["id"]).json()
    line = next(l for l in c["lines"] if l["item_code"] == cement)
    assert (line["planned_qty"], line["issued_qty"], line["variance_qty"]) == (840, 900, 60)
    assert line["over_consumed"] and c["summary"]["lines_over_consumed"] == 1
    assert c["summary"]["planned_value"] == 840 * 400


def test_a_material_drawn_that_the_boq_never_budgeted_is_flagged(tenant):
    jid, boq, _ = boq_with_lines(tenant)
    stray = rm_item(tenant)
    receive(tenant, stray, 50, 100)
    issue = tenant.post("/api/stock-issues", json={"job_id": jid, "lines": [{"item_code": stray, "quantity": 20}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    c = tenant.get("/api/stock/consumption/boq/%d" % boq["id"]).json()
    assert c["summary"]["unplanned_items"] == 1


def test_another_company_cannot_read_a_boqs_consumption(tenant, second_tenant):
    _, boq, _ = boq_with_lines(tenant)
    assert second_tenant.get("/api/stock/consumption/boq/%d" % boq["id"]).status_code == 404


def _activity(tenant, jid, **extra):
    res = tenant.post("/api/jobs/%d/schedule/activities" % jid, json={"name": "Excavation", "planned_start": d(-10), "planned_finish": d(10), **extra})
    assert res.status_code == 200, res.text
    return next(a for a in tenant.get("/api/jobs/%d/schedule" % jid).json()["activities"] if a["name"] == "Excavation")


def test_an_activity_tied_to_a_boq_line_moves_with_the_contractors_measurements(tenant):
    jid, _, lines = boq_with_lines(tenant)                      # EXC: 500 cum in the BOQ
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 500, 150)])
    fund_order(tenant, order)
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200
    item = tenant.get("/api/sub-mb/%d" % order["id"]).json()["lines"][0]["item_id"]
    assert tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": 125, "measured_on": d(-1)}).status_code == 200

    a = _activity(tenant, jid, measured_boq_key=lines["EXC"]["key"])
    assert a["measured_boq_key"] == lines["EXC"]["key"] and a["progress_from"] == "contractors' measurements"
    assert a["actual_percent"] == 25.0                          # 125 of 500
    # Measured, so nobody reports it by hand.
    assert tenant.post("/api/schedule/activities/%d/progress" % a["id"], json={"percent": 80}).status_code == 409


def test_a_boq_line_from_another_project_is_refused(tenant):
    jid, _, _ = boq_with_lines(tenant)
    _, _, other = boq_with_lines(tenant)
    res = tenant.post("/api/jobs/%d/schedule/activities" % jid, json={"name": "X", "planned_start": d(0), "planned_finish": d(5), "measured_boq_key": other["EXC"]["key"]})
    assert res.status_code == 400 and "not on this project's BOQ" in res.json()["detail"]


def _pnl_row(tenant, jid):
    return next(r for r in tenant.get("/api/jobs-pnl").json()["projects"] if r["job_id"] == jid)


def test_a_projects_order_value_and_budget_are_its_boqs(tenant):
    jid, boq, lines = boq_with_lines(tenant)
    cement = rm_item(tenant, uom="bag")
    put_line(tenant, jid, lines["RCC"]["key"], [{"kind": "MATERIAL", "description": "Cement", "uom": "bag", "coefficient": 7, "rate": 400, "item_code": cement}])
    total = tenant.get("/api/boqs/%d" % boq["id"]).json()["boq"]["total"]
    assert total > 0 and _pnl_row(tenant, jid)["order_value"] == total
    costs = next(r for r in tenant.get("/api/costs/by-project").json()["projects"] if r["job_id"] == jid)
    assert costs["contract_value"] == total and costs["budgeted_cost"] == 120 * 7 * 400
    assert tenant.get("/api/jobs/%d" % jid).json()["costing"]["budget"] == 120 * 7 * 400


def test_cost_with_nothing_billed_yet_is_not_losing_money_and_every_screen_counts_it(tenant):
    jid, _, _ = boq_with_lines(tenant)
    cement = rm_item(tenant, uom="bag")
    receive(tenant, cement, 10, 400)
    issue = tenant.post("/api/stock-issues", json={"job_id": jid, "lines": [{"item_code": cement, "quantity": 2}]}).json()["issue"]
    assert tenant.post("/api/stock-issues/%d/post" % issue["id"], json={}).status_code == 200
    row = _pnl_row(tenant, jid)
    assert row["incurred"] == 800 and not row["losing"] and row["not_billed"]
    summary = tenant.get("/api/jobs-pnl").json()["summary"]
    assert summary["losing_money"] == 0 and summary["cost_not_billed"] == 800
    # The project's own page counts the same cost: it read only the supplier bills before.
    assert tenant.get("/api/jobs/%d" % jid).json()["costing"]["total_cost"] == 800


def test_an_order_on_a_boq_project_needs_no_cost_centre(tenant):
    _, _, lines = boq_with_lines(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    got = tenant.get("/api/wo/orders/%d" % order["id"]).json()
    assert (got.get("order") or got).get("on_boq") is True
    res = tenant.post("/api/wo/orders/%d/submit" % order["id"], json={})
    assert res.status_code == 200, res.text


def test_the_tracker_shows_what_is_left_to_give_and_to_do(tenant):
    _, boq, lines = boq_with_lines(tenant)                      # EXC: 500 cum
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 300, 150)])
    assert tenant.post("/api/wo/orders/%d/submit" % order["id"], json={}).status_code == 200
    assert tenant.post("/api/wo/orders/%d/approve" % order["id"], json={}).status_code == 200
    item = tenant.get("/api/sub-mb/%d" % order["id"]).json()["lines"][0]["item_id"]
    assert tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": 120, "measured_on": d(-1)}).status_code == 200
    row = next(r for r in tenant.get("/api/boqs/%d/tracker" % boq["id"]).json()["rows"] if r.get("key") == lines["EXC"]["key"])
    assert (row["given"], row["left_to_give"], row["executed"], row["left_to_execute"]) == (300, 200, 120, 380)
