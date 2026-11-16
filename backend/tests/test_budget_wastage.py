"""The wastage % a budget's material is costed at: the store's norm where one is set, else the budget's own.

Budgeting and the store each hold a wastage percentage for a material on a BOQ item, and they drifted apart. The store's norm
is now the one used whenever it exists (0% included); the budget's own figure is kept as typed, shown beside it, warned about
when it differs, and fallen back to when the norm is removed. Nothing is stored about the answer, so a norm changed in the
store shows in the budget on the next read."""
import io
import uuid

import openpyxl
import pytest

from app import db as database, models
from app.models.store_reports import DBStoreMaterialNorm
from app.services import budget_wastage

from test_budgeting import keyed, put_line, row_of

NORMS = "/api/store/reports/norms"


@pytest.fixture(autouse=True)
def _no_norms_left_behind():
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreMaterialNorm).delete(synchronize_session=False)
        s.commit()


def material(name="Cement OPC"):
    """A stock item in the master of the company signed in last: (id, code)."""
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).order_by(models.DBClient.id.desc()).first()
        it = models.DBItem(client_id=client.id, kind="RM", item_code="BW-%s" % uuid.uuid4().hex[:8].upper(), item_name=name, units_of_measure="kg")
        s.add(it)
        s.commit()
        return it.id, it.item_code


def line_id(jid, key):
    with database.SessionLocal() as s:
        boq = s.query(models.DBBoq).filter(models.DBBoq.job_id == jid).first()
        return (s.query(models.DBBoqLine).join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
                .filter(models.DBBoqLine.boq_id == boq.id, models.DBBoqLine.key == key, models.DBBoqRevision.rev_no == boq.current_rev).first().id)


def budget(tenant, jid, key, code, own, coefficient=2, rate=10):
    """Budget one material on a line: `coefficient` kg per unit at `rate`, with the budget's own wastage % of `own`."""
    res = put_line(tenant, jid, key, [{"kind": "MATERIAL", "description": "Cement OPC", "uom": "kg", "coefficient": coefficient, "rate": rate,
                                       "item_code": code, "wastage_percent": own}])
    assert res.status_code == 200, res.text
    return res.json()


def norm(tenant, jid, key, item_id, pct, qty="2"):
    res = tenant.post(NORMS, json={"boq_item_id": line_id(jid, key), "item_id": item_id, "qty_per_unit": qty, "wastage_pct": str(pct)})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def item_of(tenant, jid, key):
    return row_of(tenant.get("/api/jobs/%d/budget" % jid).json(), key)["items"][0]


def wastage(i):
    return (i["budgeting_wastage_percent"], i["store_norm_wastage_percent"], i["effective_wastage_percent"], i["wastage_source"], i["has_wastage_mismatch"])


# --- the rule itself -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("own,store,effective,source,mismatch", [
    (5, 8, 8, "STORE_NORM", True),
    (5, 5, 5, "STORE_NORM", False),
    (5, None, 5, "BUDGETING", False),
    (0, 8, 8, "STORE_NORM", True),
    (5, 0, 0, "STORE_NORM", True),         # a norm of 0% is a norm: it does not fall back to the budget's 5%
    (None, None, 0, "BUDGETING", False),
])
def test_the_norm_wins_whenever_there_is_one_and_the_budget_figure_is_the_fallback(own, store, effective, source, mismatch):
    got = budget_wastage.resolve(own, store)
    assert (got["effective_wastage_percent"], got["wastage_source"], got["has_wastage_mismatch"]) == (effective, source, mismatch)
    assert got["store_norm_wastage_percent"] == store and bool(got["mismatch_message"]) == mismatch


def test_the_mismatch_message_names_both_figures_and_which_is_used():
    assert budget_wastage.resolve(5, 8)["mismatch_message"] == ("Budgeting wastage is 5%, but Store Material Norm wastage is 8%. "
                                                                 "Store Norm percentage is being used.")


# --- in the budget -----------------------------------------------------------------------------------------------------------

def test_budget_5_norm_8_costs_at_8_once_and_warns(tenant):
    jid, k = keyed(tenant)
    item_id, code = material()
    budget(tenant, jid, k["RCC"], code, 5)                                         # 120 cum x 2 kg at 10
    norm(tenant, jid, k["RCC"], item_id, 8)
    b = tenant.get("/api/jobs/%d/budget" % jid).json()
    r = row_of(b, k["RCC"])
    i = r["items"][0]
    assert wastage(i) == (5, 8, 8, "STORE_NORM", True) and "Store Norm percentage is being used" in i["mismatch_message"]
    assert (i["base_quantity"], i["wastage_quantity"], i["final_quantity"]) == (240, 19.2, 259.2)
    # 2 kg x 1.08 x 10 = 21.60 a unit; x 120 = 2,592: the wastage is on once, not on top of the budget's own 5%.
    assert (i["per_unit"], r["unit_material"], r["material"], r["cost"]) == (21.6, 21.6, 2592, 2592)
    assert (r["wastage_mismatches"], b["total"]["wastage_mismatches"], b["total"]["material"]) == (1, 1, 2592)
    assert i["wastage_percent"] == 5                                               # the budget's own figure is still what was typed


def test_the_example_of_1000_units_at_2_kg_comes_to_2160_kg(tenant):
    got = budget_wastage.resolve(5, 8)
    assert budget_wastage.quantities(1000, 2, got) == {"base_quantity": 2000, "wastage_quantity": 160, "final_quantity": 2160}


def test_matching_figures_use_the_norm_and_do_not_warn(tenant):
    jid, k = keyed(tenant)
    item_id, code = material()
    budget(tenant, jid, k["RCC"], code, 5)
    norm(tenant, jid, k["RCC"], item_id, 5)
    assert wastage(item_of(tenant, jid, k["RCC"])) == (5, 5, 5, "STORE_NORM", False)
    assert tenant.get("/api/jobs/%d/budget" % jid).json()["total"]["wastage_mismatches"] == 0


def test_no_norm_uses_the_budget_figure_and_says_so(tenant):
    jid, k = keyed(tenant)
    _item_id, code = material()
    b = budget(tenant, jid, k["RCC"], code, 5)
    i = row_of(b, k["RCC"])["items"][0]
    assert wastage(i) == (5, None, 5, "BUDGETING", False) and i["mismatch_message"] is None
    assert (i["final_quantity"], row_of(b, k["RCC"])["material"]) == (252, 2520)


def test_a_zero_on_either_side_is_a_figure_not_a_gap(tenant):
    jid, k = keyed(tenant)
    item_id, code = material()
    budget(tenant, jid, k["RCC"], code, 0)
    nid = norm(tenant, jid, k["RCC"], item_id, 8)
    assert wastage(item_of(tenant, jid, k["RCC"])) == (0, 8, 8, "STORE_NORM", True)
    budget(tenant, jid, k["RCC"], code, 5)
    assert tenant.put("%s/%d" % (NORMS, nid), json={"boq_item_id": line_id(jid, k["RCC"]), "item_id": item_id, "qty_per_unit": "2", "wastage_pct": "0"}).status_code == 200
    i = item_of(tenant, jid, k["RCC"])
    assert wastage(i) == (5, 0, 0, "STORE_NORM", True) and (i["wastage_quantity"], i["final_quantity"]) == (0, 240)


def test_a_norm_changed_or_removed_is_followed_at_once_and_the_budget_figure_is_never_overwritten(tenant):
    jid, k = keyed(tenant)
    item_id, code = material()
    budget(tenant, jid, k["RCC"], code, 5)
    nid = norm(tenant, jid, k["RCC"], item_id, 8)
    assert item_of(tenant, jid, k["RCC"])["effective_wastage_percent"] == 8
    tenant.put("%s/%d" % (NORMS, nid), json={"boq_item_id": line_id(jid, k["RCC"]), "item_id": item_id, "qty_per_unit": "2", "wastage_pct": "10"})
    i = item_of(tenant, jid, k["RCC"])
    assert (i["effective_wastage_percent"], i["final_quantity"]) == (10, 264)
    with database.SessionLocal() as s:                                             # what the budget itself holds did not move
        assert [x.wastage_percent for x in s.query(models.DBBoqBudgetItem).filter(models.DBBoqBudgetItem.job_id == jid).all()] == [5]
    assert tenant.delete("%s/%d" % (NORMS, nid)).status_code == 200
    assert wastage(item_of(tenant, jid, k["RCC"])) == (5, None, 5, "BUDGETING", False)


def test_the_same_material_takes_each_boq_items_own_norm_and_each_projects(tenant):
    jid, k = keyed(tenant)
    other, k2 = keyed(tenant)
    item_id, code = material()
    for j, keys in ((jid, k), (other, k2)):
        budget(tenant, j, keys["RCC"], code, 5)
        budget(tenant, j, keys["EXC"], code, 5)
    norm(tenant, jid, k["RCC"], item_id, 8)
    norm(tenant, jid, k["EXC"], item_id, 3)
    norm(tenant, other, k2["RCC"], item_id, 12)
    assert item_of(tenant, jid, k["RCC"])["effective_wastage_percent"] == 8
    assert item_of(tenant, jid, k["EXC"])["effective_wastage_percent"] == 3
    assert item_of(tenant, other, k2["RCC"])["effective_wastage_percent"] == 12
    assert wastage(item_of(tenant, other, k2["EXC"])) == (5, None, 5, "BUDGETING", False)     # no norm there: its own budget's figure


def test_a_material_is_matched_by_the_item_itself_never_by_its_name(tenant):
    jid, k = keyed(tenant)
    item_id, _code = material("Cement OPC")
    _twin_id, twin_code = material("Cement OPC")                                   # another item of the same name
    norm(tenant, jid, k["RCC"], item_id, 8)
    budget(tenant, jid, k["RCC"], twin_code, 5)
    assert item_of(tenant, jid, k["RCC"])["wastage_source"] == "BUDGETING"
    budget(tenant, jid, k["RCC"], "", 5)                                           # typed in, not picked from the master
    assert item_of(tenant, jid, k["RCC"])["wastage_source"] == "BUDGETING"


def test_labour_and_plant_carry_no_wastage(tenant):
    jid, k = keyed(tenant)
    b = put_line(tenant, jid, k["RCC"], [{"kind": "LABOUR", "description": "Mason", "uom": "day", "coefficient": 4, "rate": 200, "wastage_percent": 50}]).json()
    i = row_of(b, k["RCC"])["items"][0]
    assert (i["effective_wastage_percent"], i["per_unit"], row_of(b, k["RCC"])["labour"]) == (0, 800, 96000)
    assert put_line(tenant, jid, k["RCC"], [{"kind": "MATERIAL", "description": "x", "coefficient": 1, "rate": 1, "wastage_percent": 140}]).status_code == 400


# --- everywhere the budget is read -----------------------------------------------------------------------------------------

def test_every_reading_of_the_budget_uses_the_same_percentage(tenant):
    jid, k = keyed(tenant)
    item_id, code = material()
    budget(tenant, jid, k["RCC"], code, 5)
    norm(tenant, jid, k["RCC"], item_id, 8)
    from app.services.budgeting import boq_money_by_job, unit_costs
    from app.services.stores import boq_material_budget
    with database.SessionLocal() as s:
        client_id = s.get(models.DBJob, jid).client_id
        assert unit_costs(s, client_id, jid)[k["RCC"]]["MATERIAL"] == pytest.approx(21.6)     # contractor-rate suggestions
        assert boq_money_by_job(s, client_id, [jid])[jid]["budget"] == 2592                   # the projects board and profit
        need = boq_material_budget(s, client_id, jid)[code]                                   # what to buy, and BOQ consumption
        assert (need["needed"], need["value"]) == (259.2, 2592)
    ev = tenant.get("/api/jobs/%d/budget/earned-value" % jid).json()                          # budget against actual
    assert ev["total"]["budget"] == 2592
    wb = openpyxl.load_workbook(io.BytesIO(tenant.get("/api/jobs/%d/budget.xlsx" % jid).content))
    cells = [list(r) for r in wb.active.iter_rows(values_only=True)]
    used = next(r for r in cells if r[1] == "Cement OPC" and r[7] == "Store Norm")
    assert (used[4], used[5], used[6], used[8], used[9], used[10]) == (5, 8, 8, 240, 19.2, 259.2) and "Store Norm percentage" in used[11]


def test_the_editor_is_told_the_answer_before_it_saves(tenant):
    jid, k = keyed(tenant)
    item_id, code = material()
    norm(tenant, jid, k["RCC"], item_id, 8)
    ask = lambda items: tenant.post("/api/jobs/%d/budget/lines/%s/wastage" % (jid, k["RCC"]), json={"items": items})
    got = ask([{"kind": "MATERIAL", "item_code": code, "wastage_percent": 5}, {"kind": "MATERIAL", "item_code": "", "wastage_percent": 4},
               {"kind": "LABOUR", "item_code": "", "wastage_percent": 9}]).json()["items"]
    assert [wastage(g) for g in got] == [(5, 8, 8, "STORE_NORM", True), (4, None, 4, "BUDGETING", False), (0, None, 0, "BUDGETING", False)]
    assert tenant.get("/api/jobs/%d/budget" % jid).json()["total"]["lines_budgeted"] == 0      # asking saved nothing
    assert tenant.post("/api/jobs/%d/budget/lines/%s/wastage" % (jid, "no-such-line"), json={"items": []}).status_code == 404


def test_a_budget_made_before_this_reads_as_it_did(tenant):
    """No wastage figure and no norm: the cost is coefficient x rate, exactly as before."""
    jid, k = keyed(tenant)
    b = put_line(tenant, jid, k["RCC"], [{"kind": "MATERIAL", "description": "Ready-mix M25", "uom": "cum", "coefficient": 1, "rate": 5000}]).json()
    r = row_of(b, k["RCC"])
    assert (r["unit_material"], r["material"], r["items"][0]["effective_wastage_percent"], r["items"][0]["wastage_source"]) == (5000, 600000, 0, "BUDGETING")
