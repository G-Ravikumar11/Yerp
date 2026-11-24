"""The budget's figures and margins are seen by those given "See project budgets and margins" - not everybody who reads
reports - and the client's BOQ lines are changed by HO QS and the Master only."""
from test_boq import make_boq, saved
from test_subcontract_orders import sign_in, staff


def test_accounts_reads_reports_but_not_the_budget_a_project_manager_sees_it(tenant, portal):
    jid, _ = make_boq(tenant)
    accounts = staff(tenant, "accounts")
    sign_in(portal, accounts)
    assert portal.get("/api/jobs/%d/budget" % jid).status_code == 403
    pm = staff(tenant, "project_manager")
    sign_in(portal, pm)
    assert portal.get("/api/jobs/%d/budget" % jid).status_code == 200


def test_only_ho_qs_and_the_master_change_the_boq_lines(tenant, portal):
    _, boq = make_boq(tenant)
    lines = saved(tenant, boq)["lines"]
    body = {"lines": [{k: l.get(k) for k in ("kind", "description", "uom", "quantity", "rate", "group_code", "item_no", "key")} for l in lines]}
    pm = staff(tenant, "project_manager")
    sign_in(portal, pm)
    refused = portal.put("/api/boqs/%d/lines" % boq["id"], json=body)
    assert refused.status_code == 403 and "HO QS" in refused.json()["detail"]
    qs = staff(tenant, "ho_qs")
    sign_in(portal, qs)
    assert portal.put("/api/boqs/%d/lines" % boq["id"], json=body).status_code == 200


def test_the_order_builder_hides_the_clients_rate_from_those_who_do_not_see_budgets(tenant, portal):
    from test_budgeting import put_line
    jid, boq = make_boq(tenant)
    key = next(l["key"] for l in saved(tenant, boq)["lines"] if l["kind"] == "item")
    put_line(tenant, jid, key, [{"kind": "LABOUR", "description": "Gang", "uom": "cum", "coefficient": 1, "rate": 160}])
    mine = tenant.get("/api/boqs/%d/available" % boq["id"]).json()
    line = next(l for l in mine["lines"] if l.get("key") == key)
    assert line["rate"] and line["budgeted"] and line["budget_rate"] == 160 and not mine["rates_hidden"]
    planner = staff(tenant, "planning_billing")                 # builds work orders, does not see budgets
    sign_in(portal, planner)
    theirs = portal.get("/api/boqs/%d/available" % boq["id"]).json()
    seen = {l["key"]: l for l in theirs["lines"] if l.get("key") and l["kind"] != "section"}
    assert theirs["rates_hidden"] and all(l["rate"] is None for l in seen.values())
    assert seen[key]["budget_rate"] == 160 and any(not l["budgeted"] for l in seen.values())
