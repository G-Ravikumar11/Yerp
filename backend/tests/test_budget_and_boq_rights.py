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
