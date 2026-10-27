"""Project budgeting: our own cost for each BOQ line, against the client's rate, and the profit between them."""
import io

import openpyxl

from test_boq import make_boq, saved
from test_subcontract_orders import sign_in, staff


def keyed(tenant):
    """A project with the client's BOQ saved, and its priced lines by group code."""
    jid, boq = make_boq(tenant)
    lines = saved(tenant, boq)["lines"]
    return jid, {l["group_code"]: l["key"] for l in lines if l["kind"] == "item"}


def put_line(tenant, jid, key, items):
    return tenant.put("/api/jobs/%d/budget/lines/%s" % (jid, key), json={"items": items})


def row_of(budget, key):
    return next(r for r in budget["rows"] if r["key"] == key)


RCC_ITEMS = [
    {"kind": "MATERIAL", "description": "Ready-mix M25", "uom": "cum", "coefficient": 1, "rate": 5000},
    {"kind": "LABOUR", "description": "Mason and helpers", "uom": "day", "coefficient": 4, "rate": 200},
]


# --- the numbers -----------------------------------------------------------------------------------------------------

def test_an_unbudgeted_boq_is_all_revenue_and_no_profit(tenant):
    jid, _ = keyed(tenant)
    b = tenant.get("/api/jobs/%d/budget" % jid).json()
    t = b["total"]
    assert t["boq_value"] == 1472800 and t["unbudgeted_value"] == 1472800 and t["budgeted_value"] == 0
    assert t["cost"] == 0 and t["lines"] == 4 and t["lines_budgeted"] == 0
    assert t["margin"] is None and t["projected_profit"] is None       # nothing priced yet, so no profit is claimed
    assert all(not r["budgeted"] and r["profit"] is None for r in b["rows"])


def test_a_lines_material_and_labour_make_its_cost_and_profit(tenant):
    jid, k = keyed(tenant)
    b = put_line(tenant, jid, k["RCC"], RCC_ITEMS).json()
    r = row_of(b, k["RCC"])
    assert r["revenue"] == 984000                                     # 120 cum at the client's 8,200
    assert (r["unit_material"], r["unit_labour"], r["unit_cost"]) == (5000, 800, 5800)
    assert (r["material"], r["labour"], r["other"], r["cost"]) == (600000, 96000, 0, 696000)
    assert r["profit"] == 288000 and r["margin"] == 29.3
    t = b["total"]
    assert t["lines_budgeted"] == 1 and t["budgeted_value"] == 984000 and t["unbudgeted_value"] == 1472800 - 984000
    assert (t["material"], t["labour"], t["cost"], t["profit"]) == (600000, 96000, 696000, 288000)


def test_a_loss_making_line_shows_as_a_loss(tenant):
    jid, k = keyed(tenant)
    b = put_line(tenant, jid, k["EXC"], [{"kind": "LABOUR", "description": "Excavator and crew", "coefficient": 1, "rate": 250}]).json()
    r = row_of(b, k["EXC"])
    assert r["revenue"] == 90000 and r["cost"] == 125000 and r["profit"] == -35000 and r["margin"] == -38.9
    assert b["total"]["losing"] == 1


def test_overheads_and_contingency_come_off_the_profit(tenant):
    jid, k = keyed(tenant)
    put_line(tenant, jid, k["RCC"], RCC_ITEMS)
    b = tenant.put("/api/jobs/%d/budget" % jid, json={"overhead_percent": 5, "contingency_percent": 2, "note": "Tower C"}).json()
    t = b["total"]
    assert (t["direct"], t["overheads"], t["contingency"]) == (696000, 34800, 13920)
    assert t["cost"] == 744720 and t["profit"] == 984000 - 744720
    assert b["overhead_percent"] == 5 and b["note"] == "Tower C"
    assert row_of(b, k["RCC"])["cost"] == 744720                      # the same share is taken line by line


def test_the_projected_profit_stretches_the_budgeted_margin_over_the_whole_boq(tenant):
    jid, k = keyed(tenant)
    b = put_line(tenant, jid, k["RCC"], RCC_ITEMS).json()
    # 288,000 on 984,000 of BOQ, applied to the whole 1,472,800.
    assert b["total"]["projected_profit"] == round(1472800 * 288000 / 984000, 2)


def test_a_rate_only_line_has_no_revenue_until_it_has_a_quantity(tenant):
    jid, boq = make_boq(tenant)
    lines = saved(tenant, boq)["lines"]
    item = next(l for l in lines if l["kind"] == "item")
    item.update({"quantity": 0, "rate_only": True, "amount": 0})
    assert tenant.put("/api/boqs/%d/lines" % boq["id"], json={"lines": lines}).status_code == 200
    b = tenant.get("/api/jobs/%d/budget" % jid).json()
    assert row_of(b, item["key"])["revenue"] == 0 and row_of(b, item["key"])["rate_only"]


# --- editing a line --------------------------------------------------------------------------------------------------

def test_saving_a_line_replaces_what_it_had_and_empty_removes_it(tenant):
    jid, k = keyed(tenant)
    put_line(tenant, jid, k["RCC"], RCC_ITEMS)
    b = put_line(tenant, jid, k["RCC"], [{"kind": "MATERIAL", "description": "Ready-mix M25", "coefficient": 1, "rate": 5200}]).json()
    r = row_of(b, k["RCC"])
    assert len(r["items"]) == 1 and r["cost"] == 624000
    b = put_line(tenant, jid, k["RCC"], []).json()
    assert not row_of(b, k["RCC"])["budgeted"] and b["total"]["cost"] == 0


def test_blank_rows_are_dropped_and_bad_rows_refused(tenant):
    jid, k = keyed(tenant)
    ok = put_line(tenant, jid, k["MAS"], [{"kind": "MATERIAL", "description": "", "coefficient": 0, "rate": 0},
                                          {"kind": "OTHER", "description": "Scaffold hire", "coefficient": 1, "rate": 100}])
    assert ok.status_code == 200 and len(row_of(ok.json(), k["MAS"])["items"]) == 1
    for bad in ({"kind": "MATERIAL", "description": "Sand", "coefficient": -1, "rate": 10},
                {"kind": "MATERIAL", "description": "Sand", "coefficient": 1, "rate": -10},
                {"kind": "FOOD", "description": "Lunch", "coefficient": 1, "rate": 10},
                {"kind": "LABOUR", "description": "", "coefficient": 2, "rate": 10}):
        assert put_line(tenant, jid, k["MAS"], [bad]).status_code == 400, bad
    assert len(row_of(tenant.get("/api/jobs/%d/budget" % jid).json(), k["MAS"])["items"]) == 1   # a refusal changed nothing


def test_a_line_that_is_not_in_the_boq_is_refused(tenant):
    jid, _ = keyed(tenant)
    assert put_line(tenant, jid, "no-such-line", RCC_ITEMS).status_code == 404


def test_overheads_are_a_percentage(tenant):
    jid, _ = keyed(tenant)
    for v in (-1, 101):
        assert tenant.put("/api/jobs/%d/budget" % jid, json={"overhead_percent": v}).status_code == 400


def test_a_new_boq_revision_keeps_the_budget(tenant):
    jid, boq = make_boq(tenant)
    lines = saved(tenant, boq)["lines"]
    key = next(l["key"] for l in lines if l["group_code"] == "RCC")
    put_line(tenant, jid, key, RCC_ITEMS)
    assert tenant.post("/api/boqs/%d/revisions" % boq["id"], json={}).status_code == 200
    b = tenant.get("/api/jobs/%d/budget" % jid).json()
    assert row_of(b, key)["budgeted"] and b["total"]["profit"] == 288000


# --- who may, and whose --------------------------------------------------------------------------------------------

def test_another_business_cannot_see_or_change_a_budget(tenant, second_tenant):
    jid, k = keyed(tenant)
    put_line(tenant, jid, k["RCC"], RCC_ITEMS)
    assert second_tenant.get("/api/jobs/%d/budget" % jid).status_code == 404
    assert put_line(second_tenant, jid, k["RCC"], []).status_code == 404
    assert second_tenant.put("/api/jobs/%d/budget" % jid, json={"overhead_percent": 1}).status_code == 404
    assert second_tenant.get("/api/jobs/%d/budget.xlsx" % jid).status_code == 404


def test_only_staff_with_the_reports_right_see_the_budget_and_only_managers_change_it(tenant):
    import main
    from fastapi.testclient import TestClient
    jid, k = keyed(tenant)
    manager, plain = staff(tenant, "manager"), staff(tenant, "staff")      # both made while the owner is still signed in
    with TestClient(main.app) as m, TestClient(main.app) as p:
        sign_in(m, manager)
        sign_in(p, plain)
        assert m.get("/api/jobs/%d/budget" % jid).status_code == 200
        assert put_line(m, jid, k["RCC"], RCC_ITEMS).status_code == 200
        assert p.get("/api/jobs/%d/budget" % jid).status_code == 403
        assert put_line(p, jid, k["RCC"], RCC_ITEMS).status_code == 403


# --- the item master and the export ----------------------------------------------------------------------------------

def test_materials_can_be_looked_up_with_the_rate_we_last_paid(tenant):
    res = tenant.post("/api/items", json={"kind": "RM", "item_name": "OPC 53 Cement", "units_of_measure": "Bag", "purchase_rate": 380})
    assert res.status_code == 200, res.text
    found = tenant.get("/api/budget/materials", params={"q": "cement"}).json()
    assert [m["name"] for m in found] == ["OPC 53 Cement"] and found[0]["rate"] == 380 and found[0]["uom"] == "Bags"
    assert tenant.get("/api/budget/materials", params={"q": "zzzz"}).json() == []


def test_the_budget_exports_to_a_workbook(tenant):
    jid, k = keyed(tenant)
    put_line(tenant, jid, k["RCC"], RCC_ITEMS)
    res = tenant.get("/api/jobs/%d/budget.xlsx" % jid)
    assert res.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(res.content)).active
    cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "PROJECT BUDGET AGAINST BOQ" in cells and "Ready-mix M25" not in cells   # one row per BOQ line, not per item
    assert "M25 grade RCC in raft" in cells and "288000.0" in cells or "288000" in cells
