"""The Budget Entry Report.

What the allocation gets read back as, and the last thing printed before a
project is signed off. Modelled on the report the business already prints:
grouped under the item that was sold, with the order it belongs to named at
the top, because the question asked of it is never "what did we buy" but
"what does this line cost against what we are charging for it".
"""
import io

import openpyxl

import main


def build(tenant, budget=True, reference="Yppl/Ord020"):
    job = tenant.post("/api/jobs", json={
        "name": "Common Central Secretariat, New Delhi",
        "customer_name": "L&T Construction"}).json()
    made = tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "FG", "item_name": "C1 WIRING SUPPLY", "units_of_measure": "Nos"},
        {"kind": "FG", "item_name": "C1 WIRING INSTALL", "units_of_measure": "Nos"},
        {"kind": "RM", "item_name": "1.5SQMM FRLS WIRE RED", "units_of_measure": "Meters"},
    ]}).json()
    supply, install, wire = made["codes"]
    wo = tenant.post("/api/erp/work-orders/build", json={
        "job_id": job["id"], "reference": reference,
        "lines": [{"code": supply, "qty": 7443, "rate": 765.75},
                  {"code": install, "qty": 7443, "rate": 153.15}]}).json()["work_order"]
    if budget:
        tenant.post("/api/erp/bom/build", json={
            "work_order_id": wo["id"],
            "lines": [{"fg_code": supply, "rm_code": wire, "qty": 12405, "rate": 12.222}]})
    return {"wo": wo, "supply": supply, "install": install, "wire": wire, "job": job}


def report(tenant, wo_id):
    res = tenant.get("/api/erp/work-orders/%d/budget-report" % wo_id)
    assert res.status_code == 200, res.text
    return res.json()


# --- What it is a report of -------------------------------------------------

def test_materials_sit_under_the_line_they_were_budgeted_against(tenant):
    made = build(tenant)
    body = report(tenant, made["wo"]["id"])
    supply = [g for g in body["groups"] if g["fg_code"] == made["supply"]][0]
    assert len(supply["lines"]) == 1
    material = supply["lines"][0]
    assert material["rm_code"] == made["wire"]
    assert material["description"] == "%s  -  1.5SQMM FRLS WIRE RED" % made["wire"]
    assert material["qty"] == 12405
    assert material["uom"] == "Meters"
    assert material["rate"] == 12.222
    assert material["wo_qty"] == 7443, "the quantity of the line being built"
    assert material["amount"] == 151613.91


def test_a_sold_line_nobody_costed_is_still_on_the_report(tenant):
    """The one thing the report exists to make visible.

    A line that was sold and never budgeted is the case somebody prints this
    to find. Listing only what was allocated would leave it off the page - it
    would look complete precisely when it is not.
    """
    made = build(tenant)
    body = report(tenant, made["wo"]["id"])
    install = [g for g in body["groups"] if g["fg_code"] == made["install"]][0]
    assert install["lines"] == []
    assert install["budgeted"] is False
    assert body["totals"]["unbudgeted_lines"] == 1


def test_each_line_carries_what_it_makes_against_what_it_costs(tenant):
    made = build(tenant)
    supply = [g for g in report(tenant, made["wo"]["id"])["groups"]
              if g["fg_code"] == made["supply"]][0]
    assert supply["value"] == 5699477.25
    assert supply["cost"] == 151613.91
    assert supply["margin"] == 5547863.34


def test_the_totals_are_the_order_against_its_budget(tenant):
    body = report(tenant, build(tenant)["wo"]["id"])
    totals = body["totals"]
    assert totals["ordered_lines"] == 2
    assert totals["material_lines"] == 1
    assert totals["value"] == 6839372.7
    assert totals["cost"] == 151613.91
    assert totals["margin"] == 6687758.79


# --- The block at the top ---------------------------------------------------

def test_the_report_names_the_order_it_covers(tenant):
    made = build(tenant)
    body = report(tenant, made["wo"]["id"])
    assert body["title"] == "Budget Entry Report"
    assert body["sale_order_no"] == "Yppl/Ord020", "their own order number, not ours"
    assert body["work_order_no"] == made["wo"]["number"]
    assert body["project"] == "Common Central Secretariat, New Delhi"
    assert body["customer"] == "L&T Construction"


def test_an_order_with_no_reference_of_its_own_is_named_by_ours(tenant):
    made = build(tenant, reference="")
    assert report(tenant, made["wo"]["id"])["sale_order_no"] == made["wo"]["number"]


def test_the_financial_year_runs_april_to_march(tenant):
    assert main.financial_year("2023-09-29") == "01/04/2023 - 31/03/2024"
    assert main.financial_year("2024-03-31") == "01/04/2023 - 31/03/2024"
    assert main.financial_year("2024-04-01") == "01/04/2024 - 31/03/2025"


def test_a_report_of_an_order_that_is_not_ours_is_not_a_report(tenant, second_tenant):
    made = build(tenant)
    assert second_tenant.get(
        "/api/erp/work-orders/%d/budget-report" % made["wo"]["id"]).status_code == 404


# --- The download -----------------------------------------------------------

def test_the_report_downloads_as_a_workbook(tenant):
    made = build(tenant)
    res = tenant.get("/api/erp/work-orders/%d/budget-report.xlsx" % made["wo"]["id"])
    assert res.status_code == 200, res.text
    assert ("budget_entry_report_%s.xlsx" % made["wo"]["number"]
            in res.headers.get("content-disposition", ""))

    sheet = openpyxl.load_workbook(io.BytesIO(res.content)).active
    grid = [[c if c is not None else "" for c in row]
            for row in sheet.iter_rows(values_only=True)]

    assert grid[0][0] == "Budget Entry Report"
    assert any(str(r[0]).startswith("Sale order No: Yppl/Ord020") for r in grid[:6])
    assert any(str(r[0]).startswith("Project: Common Central") for r in grid[:6])

    head = [r for r in grid if r[0] == "Ordered Items"][0]
    assert list(head)[:7] == main.BUDGET_REPORT_HEADERS

    body = grid[grid.index(head) + 1:]
    priced = [r for r in body if r[0] == made["supply"]][0]
    assert priced[2] == 12405 and priced[4] == 12.222 and priced[6] == 151613.91
    assert any(r[0] == made["install"] and "not budgeted" in str(r[1]) for r in body)
