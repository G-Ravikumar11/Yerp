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


def _compared(tenant):
    r = rfq(tenant)
    quote(tenant, r, "ACC", 390, 62000)
    quote(tenant, r, "UltraTech", 380, 63500, freight=1000)
    quote(tenant, r, "Dalmia", 395, 61000)
    return r["rfq"]["id"]


def test_the_comparison_pdf_is_a_landscape_pdf(tenant):
    res = tenant.get("/api/rfqs/%d/comparison.pdf" % _compared(tenant))
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")


def test_the_comparison_can_be_narrowed_to_the_suppliers_chosen(tenant):
    from app.services.procurement import narrow_statement
    rid = _compared(tenant)
    d = tenant.get("/api/rfqs/%d" % rid).json()
    n = narrow_statement(d, ["ACC", "Dalmia"])
    assert [s["supplier_name"] for s in n["suppliers"]] == ["ACC", "Dalmia"]
    # UltraTech is out, so ACC is the lowest cement rate and L1 is worked out between the two left.
    assert n["lines"][0]["lowest"] == "ACC" and n["lines"][0]["lowest_rate"] == 390
    assert {s["supplier_name"]: s["rank"] for s in n["suppliers"]} == {"ACC": "L2", "Dalmia": "L1"}
    assert n["l1"] == "Dalmia" and n["saving_vs_l2"] == round(1630000 * 1.18 - 1615000 * 1.18, 2)
    assert narrow_statement(d, []) is d and narrow_statement(d, ["Nobody"]) is d


def test_a_narrowed_comparison_still_downloads(tenant):
    rid = _compared(tenant)
    for ext in ("xlsx", "pdf"):
        res = tenant.get("/api/rfqs/%d/comparison.%s?supplier=ACC&supplier=Dalmia" % (rid, ext))
        assert res.status_code == 200, res.text


def test_the_list_says_how_far_each_enquiry_has_got(tenant):
    """Asked, answered, and the best full quote landed at site - the same figure the statement gives as L1."""
    rid = _compared(tenant)
    tenant.post("/api/rfqs/%d/invites" % rid, json={"supplier_name": "Shree Cement"})
    row = tenant.get("/api/rfqs").json()["rfqs"][0]
    d = tenant.get("/api/rfqs/%d" % rid).json()
    assert row["quotes"] == 3 and row["lines"] == 2 and row["asked"] == 1 and row["waiting"] == 1
    assert row["best"] == {"supplier_name": d["l1"], "landed": d["l1_landed"]}
    assert row["awarded_to"] == [] and row["orders"] == 0


def test_a_part_quote_is_never_the_best_in_the_list(tenant):
    r = rfq(tenant)
    quote(tenant, r, "Half", 1, 0)
    assert tenant.get("/api/rfqs").json()["rfqs"][0]["best"] is None


def test_an_award_names_its_orders_on_the_enquiry(tenant):
    rid = _compared(tenant)
    out = tenant.post("/api/rfqs/%d/award" % rid, json={"mode": "lowest_per_line"}).json()
    st = tenant.get("/api/rfqs/%d/statement" % rid).json()
    numbers = {o["number"] for o in out["orders"]}
    assert {o["number"] for o in st["orders"]} == numbers
    assert all(l["po_number"] in numbers for l in st["lines"])
    row = tenant.get("/api/rfqs").json()["rfqs"][0]
    assert row["orders"] == len(numbers) and set(row["awarded_to"]) == {o["supplier"] for o in out["orders"]}


def test_an_enquiry_can_be_corrected_until_the_first_quote(tenant):
    r = rfq(tenant)
    rid = r["rfq"]["id"]
    body = {"title": "Cement only", "needed_by": "2026-11-01", "lines": [
        {"item_code": "RM-CEM", "description": "Cement OPC 53", "uom": "bags", "qty": 1200}]}
    res = tenant.put("/api/rfqs/%d" % rid, json=body)
    assert res.status_code == 200, res.text
    d = tenant.get("/api/rfqs/%d" % rid).json()
    assert d["rfq"]["title"] == "Cement only" and d["rfq"]["needed_by"] == "2026-11-01"
    assert [(l["description"], l["uom"], l["qty"]) for l in d["lines"]] == [("Cement OPC 53", "Bags", 1200)]
    quote(tenant, d, "ACC", 390, 0)
    # Once a supplier has priced these lines, the title may still change, the items may not.
    same = {**body, "title": "Cement for the raft"}
    assert tenant.put("/api/rfqs/%d" % rid, json=same).status_code == 200
    changed = {**body, "lines": [{**body["lines"][0], "qty": 1500}]}
    res = tenant.put("/api/rfqs/%d" % rid, json=changed)
    assert res.status_code == 409 and "Quotes are already in" in res.json()["detail"]
    assert tenant.get("/api/rfqs/%d" % rid).json()["lines"][0]["qty"] == 1200


def test_a_cancelled_enquiry_cannot_be_changed(tenant):
    r = rfq(tenant)
    rid = r["rfq"]["id"]
    assert tenant.post("/api/rfqs/%d/cancel" % rid, json={"reason": "bought locally"}).status_code == 200
    res = tenant.put("/api/rfqs/%d" % rid, json={"title": "x", "lines": [{"description": "y", "qty": 1}]})
    assert res.status_code == 409
    assert tenant.get("/api/rfqs").json()["summary"]["cancelled"] == 1
