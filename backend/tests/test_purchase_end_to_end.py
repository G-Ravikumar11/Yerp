"""Purchase, end to end, as the buyer and the suppliers do it: an enquiry, suppliers invited to the portal who quote through
their own links, the comparison, the award, and the purchase orders it makes - checked against the rate contracts in
force."""
import json

import pytest
from fastapi.testclient import TestClient

import main

CEMENT, STEEL = "RM-CEM", "RM-STL"


def ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def portal_quote(token, rates, **extra):
    """A supplier answering through his link: no sign-in, his own browser."""
    with TestClient(main.app) as supplier:
        page = ok(supplier.get("/api/vendor-quote/%s" % token))
        lines = [{"rfq_line_id": l["rfq_line_id"], "rate": rates[l["item_code"]], "tax_percent": 18} for l in page["lines"]
                 if rates.get(l["item_code"])]
        body = dict({"lines": lines, "quote_ref": "Q-%s" % page["supplier_name"][:4], "delivery_days": 7,
                     "payment_terms": "30 days"}, **extra)
        return ok(supplier.post("/api/vendor-quote/%s" % token, data={"quote": json.dumps(body)})), page


@pytest.fixture
def enquiry(tenant):
    """An enquiry for cement and steel, three suppliers invited and all three quoted on the portal, and a rate contract
    with Sri Ram Cements for cement at 380 a bag."""
    ok(tenant.post("/api/rate-contracts", json={"supplier_name": "Sri Ram Cements", "items": [{"item_code": CEMENT, "rate": 380}]}))
    r = ok(tenant.post("/api/rfqs", json={"title": "Cement and steel for Block A", "lines": [
        {"item_code": CEMENT, "description": "Cement OPC 53", "uom": "Bags", "qty": 1000},
        {"item_code": STEEL, "description": "TMT Fe500D 12mm", "uom": "MT", "qty": 20}]}))["rfq"]
    quotes = {"Sri Ram Cements": {CEMENT: 385, STEEL: 62000},
              "Balaji Traders": {CEMENT: 395, STEEL: 61500},
              "Vijaya Steels": {CEMENT: 390, STEEL: 60800}}
    pages = {}
    for supplier, rates in quotes.items():
        inv = ok(tenant.post("/api/rfqs/%d/invites" % r["id"], json={"supplier_name": supplier}))["invite"]
        _, pages[supplier] = portal_quote(inv["link"].split("token=")[1], rates)
    return r, pages


def test_suppliers_see_the_enquiry_on_the_portal_and_their_quotes_reach_the_comparison(tenant, enquiry):
    r, pages = enquiry
    page = pages["Balaji Traders"]
    assert page["rfq"]["number"] == r["number"] and page["open"]
    assert [l["description"] for l in page["lines"]] == ["Cement OPC 53", "TMT Fe500D 12mm"]
    cmp_ = ok(tenant.get("/api/rfqs/%d" % r["id"]))
    assert sorted(s["supplier_name"] for s in cmp_["suppliers"]) == ["Balaji Traders", "Sri Ram Cements", "Vijaya Steels"]
    lowest = {row["item_code"]: (row["lowest"], row["lowest_rate"]) for row in cmp_["lines"]}
    assert lowest == {CEMENT: ("Sri Ram Cements", 385), STEEL: ("Vijaya Steels", 60800)}


def test_the_comparison_shows_the_rate_contract_in_force(tenant, enquiry):
    """A buyer comparing quotes is told the item is on a rate contract, and at what - before he awards above it."""
    r, _ = enquiry
    cement = next(row for row in ok(tenant.get("/api/rfqs/%d" % r["id"]))["lines"] if row["item_code"] == CEMENT)
    assert cement["contract"] == {"supplier_name": "Sri Ram Cements", "rate": 380, "contract_no": "RC-0001",
                                  "valid_to": cement["contract"]["valid_to"]}
    over = {o["supplier_name"]: o["over_contract"] for o in cement["offers"]}
    assert over == {"Sri Ram Cements": True, "Balaji Traders": True, "Vijaya Steels": True}


def test_awarded_lowest_per_line_makes_one_order_per_supplier_and_flags_the_rate_contract(tenant, enquiry):
    r, _ = enquiry
    res = ok(tenant.post("/api/rfqs/%d/award" % r["id"], json={"mode": "lowest_per_line"}))
    orders = {o["supplier"]: o for o in res["orders"]}
    assert set(orders) == {"Sri Ram Cements", "Vijaya Steels"}
    sriram = ok(tenant.get("/api/purchase-orders/%d" % orders["Sri Ram Cements"]["id"]))
    assert [(l["item_code"], l["price"]) for l in sriram["line_items"]] == [(CEMENT, 385)]
    flags = json.loads(sriram["rate_flags"]) if isinstance(sriram.get("rate_flags"), str) else sriram["rate_flags"]
    assert flags and "above the rate contract 380" in flags[0]["why"]
    steel = ok(tenant.get("/api/purchase-orders/%d" % orders["Vijaya Steels"]["id"]))
    assert [(l["item_code"], l["price"]) for l in steel["line_items"]] == [(STEEL, 60800)]
    assert not steel["rate_flags"]
    assert ok(tenant.get("/api/rfqs/%d" % r["id"]))["rfq"]["status"] == "AWARDED"


def test_buying_from_another_supplier_above_a_rate_contract_in_force_is_flagged(tenant, enquiry):
    """Cement is on contract with Sri Ram at 380. Awarding it to Vijaya at 390 pays more than the contract: flagged."""
    r, _ = enquiry
    res = ok(tenant.post("/api/rfqs/%d/award" % r["id"], json={"mode": "one_supplier", "supplier_name": "Vijaya Steels",
                                                               "reason": "One supplier for the whole lot"}))
    po = ok(tenant.get("/api/purchase-orders/%d" % res["orders"][0]["id"]))
    flags = json.loads(po["rate_flags"]) if isinstance(po.get("rate_flags"), str) else po["rate_flags"]
    cement = [f for f in flags if f["item_code"] == CEMENT]
    assert cement and "Sri Ram Cements" in cement[0]["why"] and "380" in cement[0]["why"], flags


def test_anything_but_the_lowest_needs_a_reason(tenant, enquiry):
    r, _ = enquiry
    res = tenant.post("/api/rfqs/%d/award" % r["id"], json={"mode": "one_supplier", "supplier_name": "Balaji Traders"})
    assert res.status_code == 400 and "Say why" in res.json()["detail"]


def test_a_quote_cannot_be_sent_once_the_enquiry_is_awarded(tenant, enquiry):
    r, _ = enquiry
    late = ok(tenant.post("/api/rfqs/%d/invites" % r["id"], json={"supplier_name": "Late Supplier"}))["invite"]
    ok(tenant.post("/api/rfqs/%d/award" % r["id"], json={"mode": "lowest_per_line"}))
    with TestClient(main.app) as supplier:
        token = late["link"].split("token=")[1]
        res = supplier.post("/api/vendor-quote/%s" % token, data={"quote": json.dumps({"lines": [{"rfq_line_id": 1, "rate": 1}]})})
        assert res.status_code in (409, 410), res.text


def test_an_order_raised_by_hand_to_the_contract_supplier_takes_the_contract_rate_and_one_above_it_is_flagged(tenant):
    ok(tenant.post("/api/rate-contracts", json={"supplier_name": "Sri Ram Cements", "items": [{"item_code": CEMENT, "rate": 380}]}))
    assert ok(tenant.get("/api/rate-contracts/active", params={"supplier": "Sri Ram Cements"}))["rates"] == {CEMENT: 380}
    check = ok(tenant.post("/api/purchase-orders/check", json={"supplier_name": "Sri Ram Cements", "line_items": [
        {"item_code": CEMENT, "description": "Cement OPC 53", "qty": 100, "price": 400}]}))
    assert check["rates"] and "above the rate contract 380" in check["rates"][0]["why"]
    po = ok(tenant.post("/api/purchase-orders", json={"supplier_name": "Sri Ram Cements", "line_items": [
        {"item_code": CEMENT, "description": "Cement OPC 53", "qty": 100, "price": 400}]}))
    assert po["rate_flags"]
