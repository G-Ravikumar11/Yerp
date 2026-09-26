"""Fixed assets: what each owned machine is worth on the books, year by year,
and the income-tax blocks the return is filed on."""
from datetime import date

import main


def asset(tenant, **over):
    body = {"name": "JCB 3DX backhoe", "category": "Earthmoving", "ownership": "Owned",
            "purchase_date": "2024-10-01", "purchase_value": 4000000}
    body.update(over)
    res = tenant.post("/api/assets", json=body)
    assert res.status_code == 200, res.text
    return res.json().get("asset") or res.json()


def book(tenant, a, **over):
    body = {"method": "WDV", "life_years": 9, "residual_percent": 5,
            "put_to_use_on": "2024-10-01", "cost": 4000000}
    body.update(over)
    return tenant.put("/api/fixed-assets/%d/book" % a["id"], json=body)


def test_an_owned_asset_with_no_book_is_listed_with_its_suggestion(tenant):
    a = asset(tenant)
    reg = tenant.get("/api/fixed-assets?fy=2025-26").json()
    bare = [x for x in reg["not_set_up"] if x["asset_id"] == a["id"]][0]
    assert bare["suggest"]["life_years"] == 9 and bare["suggest"]["tax_block"] == "Plant & machinery"
    assert bare["ready"]
    assert "assets_unbooked" in {i["kind"] for i in tenant.get("/api/attention").json()["items"]}


def test_wdv_is_pro_rata_in_the_first_year(tenant):
    a = asset(tenant)
    res = book(tenant, a)
    assert res.status_code == 200, res.text
    reg = tenant.get("/api/fixed-assets?fy=2024-25").json()
    row = reg["assets"][0]
    assert row["rate_percent"] == 28.31
    y = row["year"]
    assert y["added"] == 4000000 and y["days"] == 182
    # 40 lakh at 28.31% for 182 of 365 days.
    assert abs(y["depreciation"] - 4000000 * main.wdv_rate(type("B", (), {"cost": 4000000, "residual_percent": 5, "life_years": 9})()) * 182 / 365) < 1
    nxt = tenant.get("/api/fixed-assets?fy=2025-26").json()["assets"][0]["year"]
    assert nxt["opening"] == y["closing"] and nxt["added"] == 0


def test_slm_stops_at_the_residual(tenant):
    a = asset(tenant, purchase_date="2015-04-01", purchase_value=900000)
    book(tenant, a, method="SLM", put_to_use_on="2015-04-01", cost=900000)
    rows = tenant.get("/api/fixed-assets/%d/schedule" % a["id"]).json()["rows"]
    assert rows[0]["depreciation"] == 95000
    assert rows[-1]["closing"] == 45000 and rows[-1]["depreciation"] == 0


def test_an_old_asset_opens_on_its_audited_book_value(tenant):
    a = asset(tenant, purchase_date="2019-06-01", purchase_value=2500000)
    assert book(tenant, a, put_to_use_on="2019-06-01", cost=2500000,
                opening_fy="2025-26").status_code == 400          # needs the value
    assert book(tenant, a, put_to_use_on="2019-06-01", cost=2500000,
                opening_fy="2025-26", opening_book_value=3000000).status_code == 400
    res = book(tenant, a, put_to_use_on="2019-06-01", cost=2500000,
               opening_fy="2025-26", opening_book_value=900000)
    assert res.status_code == 200, res.text
    y = tenant.get("/api/fixed-assets?fy=2025-26").json()["assets"][0]["year"]
    assert y["opening"] == 900000 and y["added"] == 0 and y["days"] == 365
    assert tenant.get("/api/fixed-assets?fy=2024-25").json()["assets"] == []


def test_a_sale_stops_depreciation_and_says_the_profit_or_loss(tenant):
    a = asset(tenant)
    book(tenant, a)
    res = tenant.post("/api/fixed-assets/%d/dispose" % a["id"],
                      json={"disposed_on": "2025-09-30", "disposal_value": 3500000, "note": "Sold to Rao"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["gain"] == round(3500000 - out["book_value"], 2)
    y = tenant.get("/api/fixed-assets?fy=2025-26").json()["assets"][0]["year"]
    assert y["disposed"] and y["closing"] == 0 and y["days"] == 183
    assert tenant.get("/api/fixed-assets?fy=2026-27").json()["assets"] == []
    assert tenant.get("/api/assets/%d" % a["id"]).json()["status"] == "Disposed"
    # Its book is closed.
    assert book(tenant, a).status_code == 409


def test_wdv_needs_a_residual_and_hired_machines_have_no_book(tenant):
    a = asset(tenant)
    assert book(tenant, a, residual_percent=0).status_code == 400
    assert book(tenant, a, method="SLM", residual_percent=0).status_code == 200
    hired = asset(tenant, name="Hired crane", ownership="Hired", hired_from="Sri Ram Cranes", hire_rate=9000)
    assert book(tenant, hired).status_code == 409


def test_set_up_all_uses_each_categorys_life(tenant):
    asset(tenant)
    asset(tenant, name="Office laptop", category="Computers", purchase_date="2025-05-10", purchase_value=85000)
    asset(tenant, name="Old mixer", category="Concrete", purchase_date="", purchase_value=0)
    out = tenant.post("/api/fixed-assets/set-up-all").json()
    assert len(out["made"]) == 2 and len(out["skipped"]) == 1
    reg = tenant.get("/api/fixed-assets?fy=2025-26").json()
    laptop = [r for r in reg["assets"] if r["category"] == "Computers"][0]
    assert laptop["life_years"] == 3 and laptop["tax_block"] == "Computers"


def test_tax_blocks_take_half_the_rate_on_less_than_180_days(tenant):
    # Plant bought 1 Oct: used 182 days in the year - full rate.
    a = asset(tenant)
    book(tenant, a)
    # Plant bought 1 Jan: used 90 days - half rate.
    b = asset(tenant, name="Plate compactor", category="Compaction", purchase_date="2025-01-01", purchase_value=200000)
    book(tenant, b, put_to_use_on="2025-01-01", cost=200000, life_years=12)
    blocks = {r["block"]: r for r in tenant.get("/api/fixed-assets/tax-blocks?fy=2024-25").json()["blocks"]}
    pm = blocks["Plant & machinery"]
    assert pm["added_full"] == 4000000 and pm["added_half"] == 200000
    assert pm["depreciation"] == 4000000 * 0.15 + 200000 * 0.075
    nxt = {r["block"]: r for r in tenant.get("/api/fixed-assets/tax-blocks?fy=2025-26").json()["blocks"]}
    assert nxt["Plant & machinery"]["opening"] == pm["closing"]


def test_a_block_opens_on_its_last_filed_wdv(tenant):
    blocks = tenant.get("/api/fixed-assets/tax-blocks?fy=2025-26").json()["blocks"]
    veh = [b for b in blocks if b["block"] == "Motor vehicles"][0]
    res = tenant.put("/api/fixed-assets/tax-blocks/%d" % veh["block_id"],
                     json={"rate": 15, "opening_fy": "2025-26", "opening_wdv": 1000000})
    assert res.status_code == 200, res.text
    car = asset(tenant, name="Bolero", category="Vehicle", purchase_date="2025-12-15", purchase_value=900000)
    book(tenant, car, put_to_use_on="2025-12-15", cost=900000, life_years=8)
    row = [b for b in tenant.get("/api/fixed-assets/tax-blocks?fy=2025-26").json()["blocks"]
           if b["block"] == "Motor vehicles"][0]
    assert row["opening"] == 1000000 and row["added_half"] == 900000
    assert row["depreciation"] == 1000000 * 0.15 + 900000 * 0.075


def test_selling_for_more_than_the_block_is_a_short_term_gain(tenant):
    a = asset(tenant, name="Transit mixer", category="Transport", purchase_date="2024-04-01", purchase_value=1000000)
    book(tenant, a, put_to_use_on="2024-04-01", cost=1000000, life_years=8)
    tenant.post("/api/fixed-assets/%d/dispose" % a["id"], json={"disposed_on": "2025-06-01", "disposal_value": 1200000})
    row = [b for b in tenant.get("/api/fixed-assets/tax-blocks?fy=2025-26").json()["blocks"]
           if b["block"] == "Motor vehicles"][0]
    assert row["opening"] == 850000 and row["short_term_gain"] == 350000 and row["closing"] == 0


def test_the_registers_export(tenant):
    a = asset(tenant)
    book(tenant, a)
    assert tenant.get("/api/fixed-assets.xlsx?fy=2025-26").status_code == 200
    assert tenant.get("/api/fixed-assets/tax-blocks.xlsx?fy=2025-26").status_code == 200


def test_another_company_sees_none_of_it(tenant, second_tenant):
    a = asset(tenant)
    book(tenant, a)
    assert second_tenant.get("/api/fixed-assets?fy=2025-26").json()["assets"] == []
    assert second_tenant.put("/api/fixed-assets/%d/book" % a["id"], json={"cost": 1}).status_code == 404
    assert second_tenant.get("/api/fixed-assets/%d/schedule" % a["id"]).status_code == 404


def test_financial_years():
    assert main.fy_start_year("2026-27") == 2026
    assert main.fy_start_year("2026-03-31") == 2025
    assert main.fy_start_year(date(2026, 4, 1)) == 2026
    assert main.fy_start_year("2026-28") is None
