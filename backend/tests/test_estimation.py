"""Estimation - the front of the chain.

The chain used to start at a signed work order. Half of a contracting business
happens before that: a tender arrives, somebody builds a rate for every item
from material, labour, plant and overhead, adds a margin, and submits a price.
Win it and that priced schedule IS the work order.
"""


def tender(tenant, **over):
    body = {"title": "295 KLD STP, Vizag", "customer_name": "L&T Construction",
            "tender_reference": "LT/VZG/2026/041", "overhead_percent": 10,
            "profit_percent": 8}
    body.update(over)
    res = tenant.post("/api/estimates", json=body)
    assert res.status_code == 200, res.text
    return res.json()["estimate"]


def add_item(tenant, est_id, **over):
    body = {"item_no": "1.1", "description": "M25 RCC in raft foundation",
            "uom": "cum", "quantity": 250}
    body.update(over)
    res = tenant.post("/api/estimates/%d/items" % est_id, json=body)
    assert res.status_code == 200, res.text
    return res.json()["estimate"]


CONCRETE = [
    {"kind": "MATERIAL", "description": "Cement OPC 53", "uom": "bag",
     "quantity_per_unit": 8, "rate": 380, "wastage_percent": 2},
    {"kind": "MATERIAL", "description": "River sand", "uom": "cum",
     "quantity_per_unit": 0.45, "rate": 1800, "wastage_percent": 5},
    {"kind": "MATERIAL", "description": "20mm aggregate", "uom": "cum",
     "quantity_per_unit": 0.9, "rate": 1400, "wastage_percent": 5},
    {"kind": "LABOUR", "description": "Mason", "uom": "day",
     "quantity_per_unit": 0.35, "rate": 900},
    {"kind": "LABOUR", "description": "Helper", "uom": "day",
     "quantity_per_unit": 1.2, "rate": 600},
    {"kind": "PLANT", "description": "Mixer + vibrator", "uom": "hr",
     "quantity_per_unit": 0.5, "rate": 350},
]


def analysed(tenant):
    est = tender(tenant)
    est = add_item(tenant, est["id"])
    item = est["items"][0]
    res = tenant.put("/api/estimates/%d/items/%d/analysis" % (est["id"], item["id"]),
                     json={"lines": CONCRETE})
    assert res.status_code == 200, res.text
    return res.json()["estimate"]


# --- Building up a rate ------------------------------------------------------

def test_a_rate_is_the_sum_of_what_goes_into_one_unit(tenant):
    est = analysed(tenant)
    item = est["items"][0]
    # Cement 8 x 380 x 1.02 = 3100.8; sand 0.45 x 1800 x 1.05 = 850.5;
    # aggregate 0.9 x 1400 x 1.05 = 1323; mason 315; helper 720; plant 175.
    expected = 3100.8 + 850.5 + 1323 + 315 + 720 + 175
    assert item["cost_rate"] == round(expected, 4)
    assert len(item["analysis"]) == 6


def test_wastage_is_on_top_of_the_theoretical_quantity(tenant):
    est = analysed(tenant)
    cement = [a for a in est["items"][0]["analysis"] if a["description"] == "Cement OPC 53"][0]
    assert cement["amount_per_unit"] == round(8 * 380 * 1.02, 4)


def test_overhead_then_profit_in_that_order(tenant):
    """Overhead is a cost the business carries; profit is what is left after
    every cost. The other way round quietly understates the margin."""
    est = analysed(tenant)
    item = est["items"][0]
    cost = item["cost_rate"]
    assert item["quoted_rate"] == round(cost * 1.10 * 1.08, 4)
    assert est["quoted_total"] == round(250 * item["quoted_rate"], 2)
    assert est["margin_amount"] == round(est["quoted_total"] - est["cost_total"], 2)


def test_an_item_can_carry_its_own_margin(tenant):
    """A risky item is priced with more on top than the rest of the tender."""
    est = tender(tenant)
    est = add_item(tenant, est["id"], cost_rate=1000, profit_percent=25)
    item = est["items"][0]
    assert item["quoted_rate"] == round(1000 * 1.10 * 1.25, 4)


def test_a_typed_cost_rate_yields_to_an_analysis(tenant):
    """The build-up is the truth when it exists."""
    est = tender(tenant)
    est = add_item(tenant, est["id"], cost_rate=9999)
    item = est["items"][0]
    assert item["cost_rate"] == 9999
    res = tenant.put("/api/estimates/%d/items/%d/analysis" % (est["id"], item["id"]),
                     json={"lines": CONCRETE[:1]})
    assert res.json()["estimate"]["items"][0]["cost_rate"] == round(8 * 380 * 1.02, 4)


def test_the_tender_totals_across_its_items(tenant):
    est = tender(tenant, overhead_percent=0, profit_percent=0)
    add_item(tenant, est["id"], item_no="1.1", cost_rate=100, quantity=10)
    est = add_item(tenant, est["id"], item_no="1.2", cost_rate=50, quantity=20)
    assert est["cost_total"] == 2000
    assert est["quoted_total"] == 2000
    assert est["item_count"] == 2


# --- The lifecycle ------------------------------------------------------------

def test_a_tender_with_nothing_priced_cannot_be_submitted(tenant):
    est = tender(tenant)
    res = tenant.post("/api/estimates/%d/submit" % est["id"])
    assert res.status_code == 409
    assert "nothing priced" in res.json()["detail"].lower()


def test_a_submitted_tender_is_frozen(tenant):
    """It is the price somebody was given."""
    est = analysed(tenant)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    res = tenant.put("/api/estimates/%d" % est["id"], json={"title": "Changed"})
    assert res.status_code == 409
    item = est["items"][0]
    assert tenant.put("/api/estimates/%d/items/%d/analysis" % (est["id"], item["id"]),
                      json={"lines": []}).status_code == 409


def test_losing_records_why(tenant):
    est = analysed(tenant)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    out = tenant.post("/api/estimates/%d/lose" % est["id"],
                      json={"reason": "L1 was 12% below us"}).json()["estimate"]
    assert out["status"] == "LOST"
    assert "12%" in out["lost_reason"]


def test_a_lost_tender_can_be_reopened_and_repriced(tenant):
    est = analysed(tenant)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    tenant.post("/api/estimates/%d/lose" % est["id"], json={"reason": "price"})
    out = tenant.post("/api/estimates/%d/reopen" % est["id"]).json()["estimate"]
    assert out["status"] == "DRAFT"
    assert out["lost_reason"] == ""


def test_the_strike_rate_is_by_count(tenant):
    for outcome in ("win", "lose", "lose", "win"):
        est = analysed(tenant)
        tenant.post("/api/estimates/%d/submit" % est["id"])
        tenant.post("/api/estimates/%d/%s" % (est["id"], outcome), json={"reason": "x"})
    assert tenant.get("/api/estimates").json()["summary"]["strike_rate"] == 50.0


# --- Winning is the handoff ----------------------------------------------------

def test_winning_makes_the_work_order_line_for_line(tenant):
    """The whole module exists for this. Nothing is retyped."""
    est = tender(tenant, overhead_percent=0, profit_percent=0)
    add_item(tenant, est["id"], item_no="1.1", description="M25 RCC raft",
             uom="cum", quantity=250, cost_rate=6800)
    est = add_item(tenant, est["id"], item_no="2.1", description="Fe500D steel",
                   uom="MT", quantity=18.5, cost_rate=68000)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    out = tenant.post("/api/estimates/%d/win" % est["id"]).json()
    assert out["estimate"]["status"] == "WON"
    wo = out["work_order"]
    assert wo["status"] == "Draft", "placing is still somebody's decision"
    assert wo["total_value"] == 250 * 6800 + 18.5 * 68000
    got = tenant.get("/api/erp/work-orders/%d" % wo["id"]).json()
    assert [l["description"] for l in got["lines"]] == ["M25 RCC raft", "Fe500D steel"]
    assert got["lines"][0]["rate"] == 6800


def test_winning_issues_codes_for_items_that_had_none(tenant):
    est = tender(tenant)
    est = add_item(tenant, est["id"], cost_rate=100)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    out = tenant.post("/api/estimates/%d/win" % est["id"]).json()
    got = tenant.get("/api/erp/work-orders/%d" % out["work_order"]["id"]).json()
    code = got["lines"][0]["fg_code"]
    assert code, "the line needs a code the measurement book can be kept against"
    items = tenant.get("/api/erp/items").json()["items"]
    assert any(i["item_code"] == code and i["kind"] == "FG" for i in items)


def test_winning_opens_the_project_if_there_was_none(tenant):
    est = tender(tenant, customer_name="NHAI")
    est = add_item(tenant, est["id"], cost_rate=100)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    out = tenant.post("/api/estimates/%d/win" % est["id"]).json()
    assert out["estimate"]["job_id"]
    job = tenant.get("/api/jobs/%d" % out["estimate"]["job_id"]).json()
    assert job["customer_name"] == "NHAI"
    assert job["status"] == "won"
    assert job["quoted_value"] == out["estimate"]["quoted_total"]


def test_the_estimate_remembers_its_order(tenant):
    """So the two can be laid side by side when the job is over."""
    est = tender(tenant)
    est = add_item(tenant, est["id"], cost_rate=100)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    out = tenant.post("/api/estimates/%d/win" % est["id"]).json()
    again = tenant.get("/api/estimates/%d" % est["id"]).json()
    assert again["work_order_id"] == out["work_order"]["id"]
    assert again["work_order"] == out["work_order"]["number"]


def test_a_won_tender_cannot_be_won_twice(tenant):
    est = tender(tenant)
    est = add_item(tenant, est["id"], cost_rate=100)
    tenant.post("/api/estimates/%d/submit" % est["id"])
    tenant.post("/api/estimates/%d/win" % est["id"])
    assert tenant.post("/api/estimates/%d/win" % est["id"]).status_code == 409
    assert len(tenant.get("/api/erp/work-orders").json()["work_orders"]) == 1


def test_it_downloads(tenant):
    est = analysed(tenant)
    res = tenant.get("/api/estimates/%d/export.xlsx" % est["id"])
    assert res.status_code == 200 and res.content[:2] == b"PK"


def test_another_tenant_cannot_see_it(tenant, second_tenant):
    est = analysed(tenant)
    assert second_tenant.get("/api/estimates/%d" % est["id"]).status_code == 404
    assert second_tenant.get("/api/estimates").json()["estimates"] == []
