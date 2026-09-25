"""Stores: material between sites, and material charged to a gang.

Cement left at one site goes to the next as a transfer, at what it cost, and
is not consumption. Material handed to a gang whose rate includes it comes
off their next bill on its own, up to what that bill can bear; the project is
credited back so the same cement is not counted twice.
"""
from test_goods_receipt import order as po_order, receipt, post
from test_subcontractor_bills import live_order, book as sub_book, measure as sub_measure, raise_bill


def cement(tenant, bags=400, rate=390, store=None):
    item = tenant.post("/api/erp/items", json={
        "kind": "RM", "item_name": "Cement OPC 53", "units_of_measure": "Bags"}).json()
    po = po_order(tenant, lines=[{"description": "Cement", "item_code": item["item_code"],
                                  "uom": "Bags", "qty": bags, "price": rate}])
    g = receipt(tenant, po, **({"store_location": store} if store else {}))
    post(tenant, g)
    return item["item_code"]


def on_hand(tenant, code, store=None):
    q = "?store=" + store if store else ""
    rows = tenant.get("/api/stock" + q).json()["stock"]
    row = [r for r in rows if r["item_code"] == code]
    return row[0]["on_hand"] if row else 0


# --- Transfers --------------------------------------------------------------------

def test_a_transfer_moves_stock_between_stores(tenant):
    code = cement(tenant)
    res = tenant.post("/api/stock/transfers", json={
        "from_store": "Main store", "to_store": "Vizag site store",
        "lines": [{"item_code": code, "qty": 150}]})
    assert res.status_code == 200, res.text
    assert res.json()["number"] == "TRF-0001"
    assert res.json()["value"] == 150 * 390
    assert on_hand(tenant, code, "Main store") == 250
    assert on_hand(tenant, code, "Vizag site store") == 150
    assert on_hand(tenant, code) == 400            # the company still holds it all


def test_a_transfer_is_not_consumption(tenant):
    """Received and issued stay what the gate and the site saw."""
    code = cement(tenant)
    tenant.post("/api/stock/transfers", json={"from_store": "Main store", "to_store": "Site B",
                                              "lines": [{"item_code": code, "qty": 100}]})
    row = [r for r in tenant.get("/api/stock").json()["stock"] if r["item_code"] == code][0]
    assert row["received"] == 400 and row["issued"] == 0
    assert row["value"] == 400 * 390


def test_the_balance_still_agrees_with_the_ledger(tenant):
    code = cement(tenant)
    tenant.post("/api/stock/transfers", json={"from_store": "Main store", "to_store": "Site B",
                                              "lines": [{"item_code": code, "qty": 100}]})
    before = [r for r in tenant.get("/api/stock").json()["stock"] if r["item_code"] == code][0]
    tenant.post("/api/stock/rebuild")
    after = [r for r in tenant.get("/api/stock").json()["stock"] if r["item_code"] == code][0]
    for k in ("on_hand", "value", "received", "issued"):
        assert before[k] == after[k], k


def test_you_cannot_send_what_is_not_there(tenant):
    code = cement(tenant, bags=50)
    res = tenant.post("/api/stock/transfers", json={
        "from_store": "Main store", "to_store": "Site B", "lines": [{"item_code": code, "qty": 60}]})
    assert res.status_code == 409 and "Not enough" in res.json()["detail"]


def test_a_store_does_not_send_to_itself(tenant):
    code = cement(tenant)
    assert tenant.post("/api/stock/transfers", json={
        "from_store": "Main store", "to_store": "main store",
        "lines": [{"item_code": code, "qty": 1}]}).status_code == 400


def test_the_stores_and_the_transfers_are_listed(tenant):
    code = cement(tenant)
    tenant.post("/api/stock/transfers", json={"from_store": "Main store", "to_store": "Site B",
                                              "lines": [{"item_code": code, "qty": 40}]})
    stores = {s["store"]: s for s in tenant.get("/api/stock/stores").json()["stores"]}
    assert stores["Site B"]["value"] == 40 * 390
    t = tenant.get("/api/stock/transfers").json()["transfers"][0]
    assert t["from_store"] == "Main store" and t["to_store"] == "Site B"
    assert t["lines"][0]["qty"] == 40


# --- Material charged to a gang -------------------------------------------------------

def issue_to_gang(tenant, code, order, bags, **extra):
    iss = tenant.post("/api/stock-issues", json={"lines": [{"item_code": code, "qty": bags}]}).json()["issue"]
    body = {"recover_from_order_id": order["id"]}
    body.update(extra)
    res = tenant.post("/api/stock-issues/%d/post" % iss["id"], json=body)
    assert res.status_code == 200, res.text
    return iss


def test_material_issued_to_a_gang_comes_off_their_bill(tenant):
    code = cement(tenant)
    order = live_order(tenant)
    issue_to_gang(tenant, code, order, 20)
    waiting = tenant.get("/api/material-recoveries?order_id=%d" % order["id"]).json()
    assert waiting["summary"]["waiting"] == 20 * 390
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["other_deductions"] == 20 * 390
    assert "Material issued and recovered" in bill["deduction_notes"]
    after = tenant.get("/api/material-recoveries?order_id=%d" % order["id"]).json()
    assert after["summary"]["waiting"] == 0 and after["summary"]["recovered"] == 7800


def test_a_markup_is_recovered_on_top_of_cost(tenant):
    code = cement(tenant)
    order = live_order(tenant)
    issue_to_gang(tenant, code, order, 10, markup_percent=10)
    got = tenant.get("/api/material-recoveries?order_id=%d" % order["id"]).json()["recoveries"][0]
    assert got["rate"] == 429 and got["amount"] == 4290


def test_a_small_bill_recovers_what_it_can_and_the_rest_waits(tenant):
    code = cement(tenant, bags=400)
    order = live_order(tenant)
    issue_to_gang(tenant, code, order, 300)                     # 1,17,000 of cement
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 10)                  # 68,000 of work
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    assert bill["net_payable"] >= 0
    rec = tenant.get("/api/material-recoveries?order_id=%d" % order["id"]).json()["summary"]
    assert rec["recovered"] == bill["other_deductions"] > 0
    assert round(rec["recovered"] + rec["waiting"], 2) == 300 * 390


def test_a_cancelled_bill_gives_the_material_back(tenant):
    code = cement(tenant)
    order = live_order(tenant)
    issue_to_gang(tenant, code, order, 20)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/cancel" % bill["id"], json={"comments": "wrong period"})
    rec = tenant.get("/api/material-recoveries?order_id=%d" % order["id"]).json()["summary"]
    assert rec["waiting"] == 7800 and rec["recovered"] == 0
    again = raise_bill(tenant, order["id"]).json()["bill"]
    assert again["other_deductions"] == 7800


def test_the_project_is_credited_so_nothing_is_counted_twice(tenant):
    """The cement's cost is in the store issue and again inside the gang's
    bill; the recovery takes one of them back out."""
    code = cement(tenant)
    order = live_order(tenant)
    issue_to_gang(tenant, code, order, 20)
    item = sub_book(tenant, order["id"])["lines"][0]["item_id"]
    sub_measure(tenant, order["id"], item, 100)
    bill = raise_bill(tenant, order["id"]).json()["bill"]
    tenant.post("/api/sub-bills/%d/submit" % bill["id"], json={})
    tenant.post("/api/sub-bills/%d/certify" % bill["id"], json={})
    cost = tenant.get("/api/jobs/%d/pnl" % order["job_id"]).json()["cost"]
    assert cost["material_from_store"] == 7800
    assert cost["material_recovered_from_gangs"] == 7800
    assert cost["incurred"] == round(cost["subcontractors"] + cost["supplier_bills"] + cost["labour"]
                                     + cost["plant"] + cost["equipment"], 2)


def test_material_is_charged_only_to_a_live_order(tenant):
    code = cement(tenant)
    from test_subcontract_orders import priced
    draft = priced(tenant)
    iss = tenant.post("/api/stock-issues", json={"lines": [{"item_code": code, "qty": 5}]}).json()["issue"]
    res = tenant.post("/api/stock-issues/%d/post" % iss["id"], json={"recover_from_order_id": draft["id"]})
    assert res.status_code == 409


def test_an_issue_comes_out_of_the_store_that_holds_it(tenant):
    """Material received into a site store was issued out of an empty main
    store: main went negative and the site store never went down."""
    from test_goods_receipt import order, receipt, set_lines, post
    from test_stock_control import rm_item
    code = rm_item(tenant, name="OPC 53 CEMENT", uom="Bags")
    po = order(tenant, lines=[{"description": "OPC 53", "item_code": code, "uom": "Bags",
                               "qty": 100, "price": 400}])
    grn = receipt(tenant, po, store_location="Vanya site store")
    set_lines(tenant, grn, [{"received_qty": 100, "rejected_qty": 0}])
    post(tenant, grn)
    issue = tenant.post("/api/stock-issues", json={"issued_to": "Site",
                                                  "lines": [{"item_code": code, "quantity": 10}]}).json()["issue"]
    assert issue["store"] == "Vanya site store"
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    stores = {s["store"]: s for s in tenant.get("/api/stock/stores").json()["stores"]}
    assert stores["Vanya site store"]["value"] == 90 * 400
    assert "Main store" not in stores or stores["Main store"]["value"] >= 0


def test_an_issue_not_against_an_order_can_still_name_its_project(tenant):
    from test_stock_control import rm_item, receive
    job = tenant.post("/api/jobs", json={"name": "Mobilisation", "customer_name": "Arabtec"}).json()
    code = rm_item(tenant)
    receive(tenant, code, 50, 100)
    issue = tenant.post("/api/stock-issues", json={"job_id": job["id"], "issued_to": "Site",
                                                  "lines": [{"item_code": code, "quantity": 5}]}).json()["issue"]
    tenant.post("/api/stock-issues/%d/post" % issue["id"], json={})
    cost = tenant.get("/api/jobs/%d/pnl" % job["id"]).json()["cost"]
    assert cost["material_from_store"] == 500
