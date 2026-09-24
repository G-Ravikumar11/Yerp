"""A civil contractor has to be able to name what it measures.

The app shipped with the six units an invoicing product carries - Meters,
Nos, Kgs, Litres, Sets, Lot - and refused everything else. Concrete is
measured in cubic metres, shuttering in square metres, steel in tonnes and
cement in bags, so not one item on a real site could be created in the unit
it is measured in. That single omission stopped the whole chain: no item,
so no work order, so nothing to measure and nothing to bill.
"""
import main


def test_a_site_can_name_what_it_measures(tenant):
    for unit in ("cum", "sqm", "rmt", "MT", "Bags", "Quintal", "Brass", "Days"):
        res = tenant.post("/api/erp/items", json={
            "kind": "RM", "item_name": "Thing in " + unit, "units_of_measure": unit})
        assert res.status_code == 200, "%s was refused: %s" % (unit, res.text)
        assert res.json()["units_of_measure"] == unit


def test_the_old_units_still_work(tenant):
    """Data named before this existed must stay valid."""
    for unit in ("Meters", "Nos", "Kgs", "Litres", "Sets", "Lot"):
        assert tenant.post("/api/erp/items", json={
            "kind": "RM", "item_name": "Old " + unit, "units_of_measure": unit}).status_code == 200


def test_how_somebody_elses_sheet_spells_it():
    """One unit, one spelling. Three spellings of cum is a stock balance in
    three pieces."""
    assert main.canonical_unit("Cu.M") == "cum"
    assert main.canonical_unit("CUM") == "cum"
    assert main.canonical_unit("cubic metre") == "cum"
    assert main.canonical_unit("R.Mt") == "rmt"
    assert main.canonical_unit("ton") == "MT"
    assert main.canonical_unit("kg") == "Kgs"
    assert main.canonical_unit("Each") == "Nos"
    assert main.canonical_unit("ltr") == "Litres"
    assert main.canonical_unit("") == "Nos"


def test_a_unit_nobody_uses_is_refused(tenant):
    res = tenant.post("/api/erp/items", json={
        "kind": "RM", "item_name": "Mystery", "units_of_measure": "furlong"})
    assert res.status_code == 400
    assert "furlong" in res.json()["detail"]


def test_the_spelling_is_settled_on_the_way_in(tenant):
    item = tenant.post("/api/erp/items", json={
        "kind": "RM", "item_name": "RMC M25", "units_of_measure": "Cu.M"}).json()
    assert item["units_of_measure"] == "cum"


def test_both_halves_of_the_app_agree_on_units(tenant):
    """The subcontract schedule used to keep its own list, spelled
    differently - kg against Kgs, nos against Nos - so the same material was
    two units depending on which screen named it."""
    items = tenant.get("/api/erp/vocabulary").json()["units"]
    boq = tenant.get("/api/wo/vocabulary").json()["uoms"]
    assert items == boq


def test_an_imported_boq_keeps_its_units(tenant):
    """The import had a third list with no cum and no sqm, so every concrete
    line on a real BOQ was quietly read as Nos."""
    assert "cum" in main.UOM_ALIASES and "sqm" in main.UOM_ALIASES
    assert "rmt" not in main.UOM_ALIASES["Meters"], "rmt is its own unit, not a metre"
    assert main.canonical_unit("rmt") == "rmt"
