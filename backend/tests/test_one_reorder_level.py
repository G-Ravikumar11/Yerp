"""One reorder level per item: the Store Hub's. The Item Master, its import and the older store screens read and write that
one figure, and a level once kept only on the item master is carried into the Hub at start-up."""
import uuid
from decimal import Decimal

import main
from app import models
from app.core.lifecycle import carry_reorder_levels_into_hub
from test_item_master_import import preview, to_commit


def material(tenant, unit="Bags", **extra):
    res = tenant.post("/api/items", json={"item_name": "Cement %s" % uuid.uuid4().hex[:6], "kind": "RM", "units_of_measure": unit, **extra})
    assert res.status_code == 200, res.text
    return res.json()["item"]


def hub(item_id):
    with main.SessionLocal() as db:
        s = db.query(models.DBStoreItemSettings).filter(models.DBStoreItemSettings.item_id == item_id).first()
        return (float(s.reorder_level), s.base_uom) if s else None


def test_the_item_master_writes_the_store_hubs_level(tenant):
    item = material(tenant, reorder_level=200)
    assert hub(item["id"]) == (200.0, "Bags"), "an item with no store settings gets them, counted in its own unit"
    assert item["reorder_level"] == 200 and item["reorder_unit"] == "Bags"
    with main.SessionLocal() as db:
        assert not db.query(models.DBItem).get(item["id"]).reorder_level, "no second figure on the item itself"
    res = tenant.put("/api/items/%d" % item["id"], json={"item_name": item["item_name"], "units_of_measure": "Bags", "reorder_level": 150})
    assert res.status_code == 200 and res.json()["item"]["reorder_level"] == 150
    assert hub(item["id"])[0] == 150
    # An edit that does not send it leaves it alone.
    tenant.put("/api/items/%d" % item["id"], json={"item_name": "Cement OPC 53", "units_of_measure": "Bags"})
    assert hub(item["id"])[0] == 150


def test_a_level_set_in_the_store_hub_is_the_one_the_item_master_shows(tenant):
    item = material(tenant, unit="Kgs")
    with main.SessionLocal() as db:
        db.add(models.DBStoreItemSettings(item_id=item["id"], base_uom="Kgs", reorder_level=Decimal("750")))
        db.commit()
    shown = tenant.get("/api/items/%d" % item["id"]).json()["item"]
    assert shown["reorder_level"] == 750 and shown["reorder_unit"] == "Kgs"
    listed = [i for i in tenant.get("/api/items", params={"q": item["item_code"]}).json()["items"] if i["id"] == item["id"]][0]
    assert listed["reorder_level"] == 750
    picker = [i for i in tenant.get("/api/erp/items", params={"kind": "RM"}).json()["items"] if i["id"] == item["id"]][0]
    assert picker["reorder_level"] == 750


def test_a_work_item_has_no_reorder_level(tenant):
    res = tenant.post("/api/items", json={"item_name": "PCC M15", "kind": "FG", "units_of_measure": "cum", "reorder_level": 30})
    assert res.status_code == 200
    item = res.json()["item"]
    assert hub(item["id"]) is None and item["reorder_level"] == 0


def test_the_imports_minimum_stock_is_the_one_level(tenant):
    item = material(tenant, reorder_level=10)
    head = ["Item code", "Item name", "What is it?", "Unit", "Minimum stock"]
    body = preview(tenant, [[item["item_code"], item["item_name"], "Material", "Bags", 10]], head=head)
    assert "reorder_level" not in body["rows"][0]["changes"], "the same level as the Hub's is no change"
    body = preview(tenant, [[item["item_code"], item["item_name"], "Material", "Bags", 60]], head=head)
    assert body["rows"][0]["status"] == "Update" and "reorder_level" in body["rows"][0]["changes"]
    assert tenant.post("/api/items/import/commit", json=to_commit(body)).json()["updated"] == 1
    assert hub(item["id"])[0] == 60
    new_code = "IMP" + uuid.uuid4().hex[:5].upper()
    body = preview(tenant, [[new_code, "River sand %s" % new_code, "Material", "cum", 25]], head=head)
    assert tenant.post("/api/items/import/commit", json=to_commit(body)).json()["created"] == 1
    made = [i for i in tenant.get("/api/items", params={"q": new_code}).json()["items"]][0]
    assert hub(made["id"]) == (25.0, "cum")


def old_level(item_id, level):
    """A level kept the old way, on the item master only."""
    with main.SessionLocal() as db:
        db.query(models.DBItem).filter(models.DBItem.id == item_id).update({"reorder_level": level})
        db.commit()


def test_an_old_item_master_level_is_carried_into_the_hub_once(tenant):
    plain, has_hub, bagged, odd = material(tenant), material(tenant), material(tenant), material(tenant, unit="Bags")
    with main.SessionLocal() as db:
        db.add(models.DBStoreItemSettings(item_id=has_hub["id"], base_uom="Bags", reorder_level=Decimal("5")))
        # Counted in kg in the stores, with 1 bag = 50 kg: an old level of 4 bags is 200 kg.
        db.add(models.DBStoreItemSettings(item_id=bagged["id"], base_uom="kg", reorder_level=Decimal("0")))
        db.add(models.DBStoreUomConversion(item_id=bagged["id"], from_uom="Bags", to_base_factor=Decimal("50")))
        # Counted in kg with no way to turn bags into kg: left alone rather than guessed at.
        db.add(models.DBStoreItemSettings(item_id=odd["id"], base_uom="kg", reorder_level=Decimal("0")))
        db.commit()
    for i, level in ((plain, 40), (has_hub, 99), (bagged, 4), (odd, 7)):
        old_level(i["id"], level)
    carry_reorder_levels_into_hub()
    assert hub(plain["id"]) == (40.0, "Bags")
    assert hub(has_hub["id"])[0] == 5, "a level already set in the Hub stands"
    assert hub(bagged["id"]) == (200.0, "kg")
    assert hub(odd["id"])[0] == 0
    with main.SessionLocal() as db:
        left = {i["id"]: db.query(models.DBItem).get(i["id"]).reorder_level for i in (plain, has_hub, bagged, odd)}
    assert left == {plain["id"]: 0, has_hub["id"]: 0, bagged["id"]: 0, odd["id"]: 7}
    # Somebody now takes the level off in the Hub; the next start does not bring the old one back.
    with main.SessionLocal() as db:
        db.query(models.DBStoreItemSettings).filter(models.DBStoreItemSettings.item_id == plain["id"]).update({"reorder_level": 0})
        db.commit()
    carry_reorder_levels_into_hub()
    assert hub(plain["id"])[0] == 0
