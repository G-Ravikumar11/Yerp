"""Material bought for a project, received into the store and issued to the
same project is one cost, not two."""
from test_goods_receipt import order, receipt, set_lines, post
from test_stock_control import rm_item
from test_measurement_and_ra_bills import placed_order


def test_material_bought_for_a_job_and_issued_to_it_is_counted_once(tenant):
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    code = rm_item(tenant, name="OPC 53 CEMENT", uom="Bags")
    po = order(tenant, job={"id": job_id}, lines=[{"description": "OPC 53", "item_code": code,
                                                   "uom": "Bags", "qty": 100, "price": 400}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 100, "rejected_qty": 0}])
    post(tenant, grn)
    tenant.post("/api/grn/%d/bill" % grn["id"], json={})
    issue = tenant.post("/api/stock-issues", json={"work_order_id": wo["id"], "issued_to": "Site",
                                                  "lines": [{"item_code": code, "quantity": 60}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    cost = tenant.get("/api/jobs/%d/pnl" % job_id).json()["cost"]
    print(cost)
    # 100 bags bought for 40,000; 60 of them used. Either the bill or the
    # issue carries the cost - never both.
    assert cost["incurred"] in (40000.0, 24000.0), cost


def test_cost_by_project_agrees_with_project_profit(tenant):
    """The two screens told two stories: a job with a gang bill, a signed
    diary and cement issued from the store showed nothing incurred."""
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    code = rm_item(tenant, name="OPC 53 CEMENT", uom="Bags")
    po = order(tenant, job={"id": job_id}, lines=[{"description": "OPC 53", "item_code": code,
                                                   "uom": "Bags", "qty": 100, "price": 400}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 100, "rejected_qty": 0}])
    post(tenant, grn)
    issue = tenant.post("/api/stock-issues", json={"work_order_id": wo["id"], "issued_to": "Site",
                                                  "lines": [{"item_code": code, "quantity": 60}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    pnl = tenant.get("/api/jobs/%d/pnl" % job_id).json()["cost"]
    row = [r for r in tenant.get("/api/costs/by-project").json()["projects"] if r["job_id"] == job_id][0]
    assert row["incurred"] == pnl["incurred"] == 24000


def test_owed_to_us_is_what_the_receivables_say(tenant):
    from test_measurement_and_ra_bills import book, measure
    wo = placed_order(tenant, qty=1000, rate=100)
    job_id = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()["job_id"]
    measure(tenant, wo["id"], book(tenant, wo["id"])["lines"][0]["line_id"], 100)
    b = tenant.post("/api/ra-bills", json={"work_order_id": wo["id"]}).json()["bill"]
    tenant.post("/api/ra-bills/%d/submit" % b["id"], json={})
    tenant.post("/api/ra-bills/%d/certify" % b["id"], json={})
    tenant.post("/api/money/entries", json={"doc_type": "ra_bill", "doc_id": b["id"],
                                            "amount": 3000, "mode": "Cash"})
    row = [r for r in tenant.get("/api/costs/by-project").json()["projects"] if r["job_id"] == job_id][0]
    rec = [r for r in tenant.get("/api/money/receivables").json()["invoices"] if r["job_id"] == job_id]
    assert row["outstanding"] == round(sum(r["outstanding"] for r in rec), 2) > 0
