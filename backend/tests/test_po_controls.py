"""A purchase order checked before it is placed: each line charged to a BOQ item is set against that item's budget
(Raju's budget against actual: spent, plus other orders still to deliver, plus this one). Going over needs a reason and
goes to the higher approver. And prices: the last price per item per supplier, a rate contract, an alert past a set %."""
from test_earned_value import issue, project
from test_jobs_and_orders import approved_order, set_rules, sign_in, sign_out, staff


def po(tenant, jid, lines, supplier="ACC Cement", **extra):
    total = sum(l["qty"] * l["price"] for l in lines)
    return tenant.post("/api/purchase-orders", json={"supplier_name": supplier, "job_id": jid, "amount": total, "total": total,
                                                     "line_items": lines, **extra})


def approve(tenant, order):
    body = dict(order)
    body["status"] = "Approved"
    res = tenant.put("/api/purchase-orders/%d" % order["id"], json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_the_check_reads_the_budget_less_what_is_spent_and_committed(tenant):
    jid, boq_id, exc, rcc, acts = project(tenant)                     # RCC budget 8,40,000
    issue(jid, boq_id, rcc, 100000)                                   # 1,00,000 already spent on it
    first = po(tenant, jid, [{"description": "Cement", "qty": 1000, "price": 400, "boq_key": rcc}])   # 4,00,000 on order
    assert first.status_code == 200, first.text
    out = tenant.post("/api/purchase-orders/check", json={"job_id": jid, "supplier_name": "ACC Cement",
                                                         "line_items": [{"qty": 1000, "price": 400, "boq_key": rcc}]}).json()
    [row] = out["budget"]
    assert (row["budget"], row["spent"], row["committed"], row["this"]) == (840000, 100000, 400000, 400000)
    assert out["over_budget"] is True and row["over_by"] == 60000
    heads = {h["key"]: h for h in tenant.get("/api/jobs/%d/budget-heads" % jid).json()["heads"]}
    assert heads[rcc]["budget"] == 840000 and any(h["heading"] for h in heads.values())


def test_going_over_the_budget_needs_a_reason_and_is_kept(tenant):
    jid, boq_id, exc, rcc, acts = project(tenant)
    lines = [{"description": "Cement", "qty": 3000, "price": 300, "boq_key": rcc}]              # 9,00,000 against 8,40,000
    refused = po(tenant, jid, lines)
    assert refused.status_code == 409 and "budget_reason" in refused.json()["detail"]
    kept = po(tenant, jid, lines, budget_reason="Raft thickened by the structural consultant (VO-3 to follow)")
    assert kept.status_code == 200, kept.text
    assert kept.json()["over_budget"] is True and kept.json()["budget_reason"].startswith("Raft thickened")
    within = po(tenant, jid, [{"description": "Cement", "qty": 100, "price": 300, "boq_key": exc}])
    assert within.status_code == 200 and within.json()["over_budget"] is False


def test_an_order_over_budget_goes_to_the_master_and_is_never_auto_approved(portal, tenant):
    jid, boq_id, exc, rcc, acts = project(tenant)
    set_rules(tenant, auto_below=10_000_000.0)
    boss = staff(tenant, permission_role="manager")
    buyer = staff(tenant, permission_role="manager", reports_to=boss["id"])
    sign_in(portal, buyer)
    res = portal.post("/api/employee/purchase-orders", json={"supplier_name": "ACC", "job_id": jid, "amount": 900000,
                                                             "line_items": [{"description": "Cement", "qty": 3000, "price": 300, "boq_key": rcc}],
                                                             "budget_reason": "Raft thickened by the consultant"})
    sign_out(portal)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == "pending"                                 # not waved through under the limit
    history = tenant.get("/api/approvals/history/purchase_order/%d" % out["order"]["id"]).json()["history"]
    # The manager first, then the higher approver: the Master.
    assert [(h["approver_name"], h["approver_level"]) for h in history][-1] == ("Master", "owner") and len(history) == 2
    [item] = [i for i in tenant.get("/api/approvals/inbox").json()["items"] if i.get("number") == out["order"]["number"]]
    assert item["warnings"] == ["Over the project budget: Raft thickened by the consultant"]


def test_a_rate_over_the_last_price_or_a_rate_contract_is_flagged(tenant):
    first = po(tenant, None, [{"description": "OPC 53", "item_code": "CEM53", "qty": 10, "price": 400}])
    approve(tenant, first.json())
    hist = tenant.get("/api/items/price-history", params={"item_code": "CEM53"}).json()
    assert [(p["rate"], p["supplier"]) for p in hist["points"]] == [(400, "ACC Cement")]
    assert hist["last_by_supplier"][0]["rate"] == 400
    # 10% is the alert by default: 430 is within it, 450 is past it.
    assert po(tenant, None, [{"description": "OPC 53", "item_code": "CEM53", "qty": 1, "price": 430}]).json()["rate_flags"] == []
    flagged = po(tenant, None, [{"description": "OPC 53", "item_code": "CEM53", "qty": 1, "price": 450}]).json()
    assert flagged["rate_flags"] and "above the last price 400" in flagged["rate_flags"][0]["why"]
    # A tighter alert, and a rate contract below the price, both flag.
    assert tenant.put("/api/purchase-controls", json={"rate_alert_pct": 5}).json()["rate_alert_pct"] == 5
    assert po(tenant, None, [{"description": "OPC 53", "item_code": "CEM53", "qty": 1, "price": 430}]).json()["rate_flags"]
    assert tenant.post("/api/rate-contracts", json={"supplier_name": "ACC Cement", "item_code": "CEM53", "rate": 390}).status_code == 200
    why = po(tenant, None, [{"description": "OPC 53", "item_code": "CEM53", "qty": 1, "price": 400}]).json()["rate_flags"][0]["why"]
    assert "rate contract 390" in why


def test_the_last_price_is_kept_per_supplier(tenant):
    approve(tenant, po(tenant, None, [{"description": "Sand", "item_code": "SAND", "qty": 1, "price": 50}], supplier="Ravi Sand").json())
    approve(tenant, po(tenant, None, [{"description": "Sand", "item_code": "SAND", "qty": 1, "price": 60}], supplier="Krishna Sand").json())
    last = {p["supplier"]: p["rate"] for p in tenant.get("/api/items/price-history", params={"item_code": "SAND"}).json()["last_by_supplier"]}
    assert last == {"Ravi Sand": 50, "Krishna Sand": 60}
    # Ravi's own last price is what his next order is set against: 56 is 12% over his 50.
    assert po(tenant, None, [{"description": "Sand", "item_code": "SAND", "qty": 1, "price": 56}], supplier="Ravi Sand").json()["rate_flags"]
    assert po(tenant, None, [{"description": "Sand", "item_code": "SAND", "qty": 1, "price": 64}], supplier="Krishna Sand").json()["rate_flags"] == []
