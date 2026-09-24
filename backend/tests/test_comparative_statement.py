"""Enquiry, quotes, the comparative statement, and the award that becomes
the purchase orders."""
from test_measurement_and_ra_bills import placed_order


def rfq(tenant, **over):
    body = {"title": "Cement and steel for Block A", "lines": [
        {"item_code": "RM-CEM", "description": "Cement OPC 53", "uom": "Bags", "qty": 1000},
        {"item_code": "RM-STL", "description": "TMT Fe500D 12mm", "uom": "MT", "qty": 20}]}
    body.update(over)
    res = tenant.post("/api/rfqs", json=body)
    assert res.status_code == 200, res.text
    return tenant.get("/api/rfqs/%d" % res.json()["rfq"]["id"]).json()


def quote(tenant, r, supplier, cem, stl, freight=0, tax=18, **extra):
    lines = []
    for row, rate in zip(r["lines"], (cem, stl)):
        if rate:
            lines.append({"rfq_line_id": row["rfq_line_id"], "rate": rate, "tax_percent": tax})
    body = {"supplier_name": supplier, "freight": freight, "lines": lines}
    body.update(extra)
    res = tenant.post("/api/rfqs/%d/quotes" % r["rfq"]["id"], json=body)
    assert res.status_code == 200, res.text
    return res.json()["comparison"]


def test_an_enquiry_is_numbered(tenant):
    r = rfq(tenant)
    assert r["rfq"]["number"] == "RFQ-0001" and r["rfq"]["status"] == "OPEN"
    assert len(r["lines"]) == 2


def test_the_statement_names_the_lowest_per_line(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    quote(tenant, r, "UltraTech", 380, 63500)
    c = quote(tenant, r, "Dalmia", 395, 61000)
    cem, stl = c["lines"]
    assert cem["lowest"] == "UltraTech" and cem["lowest_rate"] == 380
    assert stl["lowest"] == "Dalmia" and stl["lowest_rate"] == 61000
    assert cem["spread_percent"] == round((395 - 380) / 380 * 100, 1)


def test_the_l1_is_by_landed_cost_not_rate(tenant):
    """A cheaper rate with a lorry charge on top is not cheaper."""
    r = rfq(tenant)
    quote(tenant, r, "Cheap but far", 380, 61000, freight=60000)
    c = quote(tenant, r, "Near", 390, 61500, freight=0)
    cheap = [s for s in c["suppliers"] if s["supplier_name"] == "Cheap but far"][0]
    near = [s for s in c["suppliers"] if s["supplier_name"] == "Near"][0]
    assert cheap["basic"] < near["basic"]
    assert near["landed"] < cheap["landed"]
    assert c["l1"] == "Near" and near["rank"] == "L1"
    assert c["saving_vs_l2"] == round(cheap["landed"] - near["landed"], 2)


def test_a_supplier_who_skipped_a_line_is_not_l1(tenant):
    r = rfq(tenant)
    quote(tenant, r, "Half", 300, 0)
    c = quote(tenant, r, "Full", 390, 62000)
    assert c["l1"] == "Full"
    assert [s for s in c["suppliers"] if s["supplier_name"] == "Half"][0]["complete"] is False


def test_a_revised_quote_replaces_the_last(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    c = quote(tenant, r, "acc", 385, 62000)
    assert len(c["suppliers"]) == 1 and c["lines"][0]["lowest_rate"] == 385


def test_awarding_the_lowest_per_line_makes_one_order_per_supplier(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    quote(tenant, r, "UltraTech", 380, 63500)
    res = tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"], json={"mode": "lowest_per_line"})
    assert res.status_code == 200, res.text
    orders = {o["supplier"]: o for o in res.json()["orders"]}
    assert set(orders) == {"UltraTech", "ACC"}
    po = tenant.get("/api/purchase-orders/%d" % orders["UltraTech"]["id"]).json()
    assert po["line_items"][0]["price"] == 380 and po["line_items"][0]["qty"] == 1000
    assert po["amount"] == 380000 and po["tax_amount"] == 68400
    assert "RFQ-0001" in po["reference"]
    assert tenant.get("/api/rfqs/%d" % r["rfq"]["id"]).json()["rfq"]["status"] == "AWARDED"


def test_the_freight_travels_with_the_order(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000, freight=15000)
    out = tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"],
                      json={"mode": "one_supplier", "supplier_name": "ACC"}).json()
    po = tenant.get("/api/purchase-orders/%d" % out["orders"][0]["id"]).json()
    assert any(l["description"] == "Freight to site" and l["price"] == 15000 for l in po["line_items"])
    assert po["amount"] == 390000 + 1240000 + 15000


def test_not_the_lowest_has_to_say_why(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    quote(tenant, r, "UltraTech", 380, 61000)
    res = tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"],
                      json={"mode": "one_supplier", "supplier_name": "ACC"})
    assert res.status_code == 400 and "Say why" in res.json()["detail"]
    ok = tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"],
                     json={"mode": "one_supplier", "supplier_name": "ACC",
                           "reason": "UltraTech's last two deliveries failed the cube test"})
    assert ok.status_code == 200
    assert "cube test" in tenant.get("/api/rfqs/%d" % r["rfq"]["id"]).json()["rfq"]["award_reason"]


def test_an_awarded_enquiry_takes_no_more_quotes(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"], json={})
    res = tenant.post("/api/rfqs/%d/quotes" % r["rfq"]["id"], json={
        "supplier_name": "Late", "lines": [{"rfq_line_id": r["lines"][0]["rfq_line_id"], "rate": 1}]})
    assert res.status_code == 409


def test_nothing_to_award_without_quotes(tenant):
    r = rfq(tenant)
    assert tenant.post("/api/rfqs/%d/award" % r["rfq"]["id"], json={}).status_code == 409


def test_an_enquiry_straight_from_what_an_order_still_needs(tenant):
    """The budget says what it takes; the store and open orders say what is
    already covered; the enquiry asks for the rest."""
    wo = placed_order(tenant, qty=1000, rate=60)      # budget: 1000 of 20MM conduit
    res = tenant.post("/api/rfqs/from-work-order/%d" % wo["id"])
    assert res.status_code == 200, res.text
    r = tenant.get("/api/rfqs/%d" % res.json()["rfq"]["id"]).json()
    assert r["rfq"]["work_order_id"] == wo["id"]
    assert r["lines"][0]["qty"] == 1000


def test_another_tenant_cannot_see_or_quote(tenant, second_tenant):
    r = rfq(tenant)
    assert second_tenant.get("/api/rfqs/%d" % r["rfq"]["id"]).status_code == 404
    assert second_tenant.get("/api/rfqs").json()["rfqs"] == []
