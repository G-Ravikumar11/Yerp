"""HO QS budget control: every live project's BOQ budgeted before any work order on it goes out; what each line has
budgeted, given and left; the same figures on the dashboard, the Setup Check, the budget screen and the order's check."""
from conftest import budget_all
from test_boq import contractor_order, make_boq, saved
from test_budgeting import put_line
from test_subcontract_orders import PASSWORD, staff

# The sample BOQ: EXC 500 cum (90,000), RCC 120 cum (9,84,000), FWK 80 sqm (32,800), MAS 60 cum (3,66,000) - 14,72,800.
TOTAL = 1472800


def project(tenant, name="Kokapet Towers"):
    jid, boq = make_boq(tenant, name)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"] if l["kind"] == "item"}
    return jid, lines


def labour(tenant, jid, key, rate=100):
    res = put_line(tenant, jid, key, [{"kind": "LABOUR", "description": "Gang", "uom": "unit", "coefficient": 1, "rate": rate}])
    assert res.status_code == 200, res.text


def material_only(tenant, jid, key):
    res = put_line(tenant, jid, key, [{"kind": "MATERIAL", "description": "Cement", "uom": "bag", "coefficient": 1, "rate": 400}])
    assert res.status_code == 200, res.text


def submit(tenant, order, comments=""):
    return tenant.post("/api/wo/orders/%d/submit" % order["id"], json={"comments": comments})


def control(tenant, jid):
    res = tenant.get("/api/jobs/%d/budget-control" % jid)
    assert res.status_code == 200, res.text
    return res.json()


def line(c, key):
    return next(r for r in c["lines"] if r["key"] == key)


# ---- 1, 2, 3, 8: no work order goes out until the whole project is budgeted -----------------------

def test_a_project_with_no_budget_sends_no_work_order_and_says_which_lines(tenant):
    jid, lines = project(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    labour(tenant, jid, lines["EXC"]["key"], 200)                   # the order's own line is budgeted, the rest is not
    res = submit(tenant, order)                                     # straight at the API: the server decides
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "Kokapet Towers" in detail and "3 BOQ lines still to budget" in detail and "RCC" in detail or "M25" in detail
    assert tenant.get("/api/wo/orders/%d" % order["id"]).json()["order"]["status"] == "DRAFT"


def test_a_partly_budgeted_project_is_refused_too_and_material_alone_is_not_a_budget(tenant):
    jid, lines = project(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    budget_all(tenant, jid, skip={lines["MAS"]["key"]})
    material_only(tenant, jid, lines["MAS"]["key"])
    assert line(control(tenant, jid), lines["MAS"]["key"])["status"] == "Partially budgeted"
    res = submit(tenant, order)
    assert res.status_code == 409 and "1 BOQ line still to budget" in res.json()["detail"] and "partially budgeted" in res.json()["detail"]


def test_with_the_whole_project_budgeted_the_order_goes_and_is_approved(tenant):
    jid, lines = project(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    budget_all(tenant, jid)
    assert submit(tenant, order).status_code == 200
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 200, res.text
    assert res.json()["order"]["status"] == "APPROVED"


def test_approval_checks_again_a_budget_removed_after_sending(tenant):
    jid, lines = project(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    budget_all(tenant, jid)
    assert submit(tenant, order).status_code == 200
    assert put_line(tenant, jid, lines["FWK"]["key"], []).status_code == 200          # a budget taken off meanwhile
    res = tenant.post("/api/wo/orders/%d/approve" % order["id"], json={})
    assert res.status_code == 409 and "still to budget" in res.json()["detail"]


def test_a_project_that_is_not_live_or_has_no_boq_keeps_the_rules_it_had(tenant):
    jid, lines = project(tenant, "Old Finished Site")
    tenant.put("/api/jobs/%d" % jid, json={"name": "Old Finished Site", "customer_name": "Kokapet LLP", "status": "complete"})
    c = control(tenant, jid)
    assert c["live"] is False
    assert all(p["job_id"] != jid for p in tenant.get("/api/ho/budget-control").json()["projects"])


# ---- 4, 5: quantity and value past what is left keep their existing rules ----------------------------

def test_more_than_the_boq_quantity_left_is_shown_and_needs_the_master_at_approval(tenant):
    jid, lines = project(tenant)
    budget_all(tenant, jid)
    first, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 400, 150)])
    assert submit(tenant, first).status_code == 200
    second, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 200, 150)])
    check = tenant.get("/api/wo/orders/%d/budget-check" % second["id"]).json()
    over = check["over_quantity"]
    assert len(over) == 1 and over[0]["available_qty"] == 100 and over[0]["this_order_qty"] == 200 and over[0]["short_qty"] == 100
    assert check["can_send"] is True                                  # not a block: the existing BOQ override decides
    assert submit(tenant, second).status_code == 200
    res = tenant.post("/api/wo/orders/%d/approve" % second["id"], json={})
    assert res.status_code == 409 and "BOQ" in res.json()["detail"]   # the Master's override, as before
    res = tenant.post("/api/wo/orders/%d/approve" % second["id"], json={"override": True, "comments": "Extra excavation agreed"})
    assert res.status_code == 200, res.text


def test_more_than_the_contractor_budget_left_needs_a_reason_and_the_master(tenant):
    jid, lines = project(tenant)
    budget_all(tenant, jid, skip={lines["EXC"]["key"]})
    labour(tenant, jid, lines["EXC"]["key"], 160)                    # 500 x 160 = 80,000 for contractors on EXC
    first, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 300, 160)])     # 48,000
    assert submit(tenant, first).status_code == 200
    # Within the rate, but the BOQ line's budget left is 32,000 and this order is 32,000 + 160 x 50 = 40,000? No - 250 x 160.
    second, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 250, 160)])    # 40,000 against 32,000 left
    check = tenant.get("/api/wo/orders/%d/budget-check" % second["id"]).json()
    assert check["over_value"][0]["available_value"] == 32000 and check["over_value"][0]["short_value"] == 8000
    refused = submit(tenant, second)
    assert refused.status_code == 409 and "budget left" in refused.json()["detail"]
    assert submit(tenant, second, "Extra depth on grid C").status_code == 200


# ---- 6, 7: allocations and orders given back are counted at once ---------------------------------

def test_a_cancelled_order_gives_its_quantity_and_value_back(tenant):
    jid, lines = project(tenant)
    budget_all(tenant, jid, skip={lines["EXC"]["key"]})
    labour(tenant, jid, lines["EXC"]["key"], 160)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 300, 160)])
    assert submit(tenant, order).status_code == 200
    row = line(control(tenant, jid), lines["EXC"]["key"])
    assert row["committed_qty"] == 300 and row["available_qty"] == 200 and row["available_value"] == 32000
    res = tenant.post("/api/wo/orders/%d/cancel" % order["id"], json={"comments": "Contractor withdrew"})
    assert res.status_code == 200, res.text
    row = line(control(tenant, jid), lines["EXC"]["key"])
    assert row["committed_qty"] == 0 and row["available_qty"] == 500 and row["available_value"] == 80000


def test_a_budget_removed_makes_the_line_unbudgeted_again(tenant):
    jid, lines = project(tenant)
    budget_all(tenant, jid)
    assert control(tenant, jid)["summary"]["status"] == "Complete"
    assert put_line(tenant, jid, lines["RCC"]["key"], []).status_code == 200
    c = control(tenant, jid)
    assert line(c, lines["RCC"]["key"])["status"] == "Not budgeted" and line(c, lines["RCC"]["key"])["remaining_value"] == 984000
    assert c["summary"]["unbudgeted"] == 1 and c["summary"]["remaining_value"] == 984000 and c["summary"]["status"] == "Incomplete"


def test_drafts_reserve_nothing_and_each_sent_order_is_weighed_against_the_others(tenant):
    jid, lines = project(tenant)
    budget_all(tenant, jid)
    a, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 300, 150)])
    b, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 300, 150)])
    # Two drafts: neither is a commitment, so each sees the whole 500 left.
    for o in (a, b):
        assert tenant.get("/api/wo/orders/%d/budget-check" % o["id"]).json()["over_quantity"] == []
    assert submit(tenant, a).status_code == 200
    over = tenant.get("/api/wo/orders/%d/budget-check" % b["id"]).json()["over_quantity"]
    assert over and over[0]["available_qty"] == 200                     # what a left


# ---- 9: who sees what -----------------------------------------------------------------------------

def test_budget_figures_are_for_those_who_see_budgets(tenant, portal):
    jid, lines = project(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    clerk = staff(tenant, "staff")
    assert portal.post("/api/employee/auth/login", json={"email": clerk["email"], "password": PASSWORD}).status_code == 200
    assert portal.get("/api/ho/budget-control").status_code == 403
    assert portal.get("/api/jobs/%d/budget-control" % jid).status_code == 403


def test_the_orders_check_hides_the_boqs_own_values_from_those_who_do_not_see_budgets(tenant, monkeypatch):
    """Only HO QS (who sees budgets) opens work orders; anybody else reaches one as an approver on its route. Whoever
    does not see budgets gets the check without the BOQ's own values - the client's prices."""
    jid, lines = project(tenant)
    order, _, _ = contractor_order(tenant, lines, [(lines["EXC"], 100, 150)])
    full = tenant.get("/api/wo/orders/%d/budget-check" % order["id"]).json()
    assert full["missing"] and all(m["value"] is not None for m in full["missing"])
    import app.core.auth as auth
    monkeypatch.setattr(auth, "session_can", lambda request, db, perm: False)
    hidden = tenant.get("/api/wo/orders/%d/budget-check" % order["id"]).json()
    assert [m["key"] for m in hidden["missing"]] == [m["key"] for m in full["missing"]]
    assert all(m["value"] is None for m in hidden["missing"]) and hidden["can_send"] is False


# ---- 11, 12: the dashboard, the Setup Check and the screens add up the same ------------------------

def test_the_dashboard_setup_check_and_budget_screen_agree(tenant):
    jid, lines = project(tenant, "Vizag High Rise")
    labour(tenant, jid, lines["EXC"]["key"])
    labour(tenant, jid, lines["RCC"]["key"])
    material_only(tenant, jid, lines["FWK"]["key"])                  # MAS left alone
    c = control(tenant, jid)
    s = c["summary"]
    assert (s["lines"], s["budgeted"], s["partial"], s["unbudgeted"]) == (4, 2, 1, 1)
    assert s["approved_value"] == TOTAL and s["budgeted_value"] == 90000 + 984000 and s["remaining_value"] == 32800 + 366000
    assert s["completion_percent"] == 50.0 and s["status"] == "Incomplete"
    exc = line(c, lines["EXC"]["key"])
    assert (exc["approved_qty"], exc["budgeted_qty"], exc["remaining_qty"], exc["unit"]) == (500, 500, 0, "cum")
    mas = line(c, lines["MAS"]["key"])
    assert (mas["status"], mas["budgeted_value"], mas["remaining_qty"]) == ("Not budgeted", 0, 60)
    dash = next(p for p in tenant.get("/api/ho/budget-control").json()["projects"] if p["job_id"] == jid)
    assert dash["summary"] == s
    item = next(i for i in tenant.get("/api/setup-check").json()["items"] if i["key"] == "budgets")
    mine = next(p for p in item["budget"]["projects"] if p["job_id"] == jid)
    assert {l["key"] for l in mine["lines"]} == {lines["FWK"]["key"], lines["MAS"]["key"]}
    assert item["ok"] is False and item["count"] >= 2
    budget_all(tenant, jid)
    item = next(i for i in tenant.get("/api/setup-check").json()["items"] if i["key"] == "budgets")
    assert all(p["job_id"] != jid for p in item["budget"]["projects"])
