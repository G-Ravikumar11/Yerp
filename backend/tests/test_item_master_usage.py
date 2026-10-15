"""Where an item is used, and the warning before something still in use is switched off."""
from test_boq import contractor_order, make_boq, saved
from test_site_pricing import make_item, site_with


def groups(tenant, item_id):
    body = tenant.get("/api/items/%d/where-used" % item_id).json()
    return body, {g["key"]: g for g in body["groups"]}


def test_an_unused_item_is_used_nowhere_and_switches_off_without_fuss(tenant):
    item = make_item(tenant, "FREE-1", "Nobody uses me")
    body, by = groups(tenant, item["id"])
    assert body["total"] == 0 and by == {}
    off = tenant.patch("/api/items/%d/status" % item["id"], json={"is_active": False})
    assert off.status_code == 200 and off.json()["item"]["is_active"] is False


def test_where_used_lists_the_boq_the_client_order_and_the_contractor_order(tenant):
    _, boq = make_boq(tenant)
    lines = {l["group_code"]: l for l in saved(tenant, boq)["lines"]}
    tenant.post("/api/boqs/%d/client-order" % boq["id"], json={})
    contractor_order(tenant, lines, [(lines["EXC"], 300, 150)])
    item = next(i for i in tenant.get("/api/items", params={"q": "Excavation"}).json()["items"])
    body, by = groups(tenant, item["id"])
    assert set(by) == {"boq", "client_orders", "contractor_orders"} and body["total"] == 3
    assert by["boq"]["rows"][0]["path"] == "/projects/boq/%d" % boq["id"] and "quantity 500" in by["boq"]["rows"][0]["detail"]
    assert by["contractor_orders"]["rows"][0]["path"].startswith("/subcontractors/work-orders/")
    assert body["item"]["item_code"] == item["item_code"]


def test_the_rows_are_capped_but_the_count_is_the_whole_count(tenant):
    item = make_item(tenant, "BUSY-1", "On many sites")
    for n in range(12):
        site_with(tenant, "Site %d" % n, [("BUSY-1", 1, 1)])
    body, by = groups(tenant, item["id"])
    assert by["boq"]["count"] == 12 and len(by["boq"]["rows"]) == 10 and by["boq"]["more"] == 2
    assert body["total"] == 12


def test_switching_off_something_in_use_needs_the_person_to_say_so(tenant):
    item = make_item(tenant, "USED-1", "On a BOQ")
    site_with(tenant, "Site A", [("USED-1", 5, 10)])
    refused = tenant.patch("/api/items/%d/status" % item["id"], json={"is_active": False})
    assert refused.status_code == 409
    assert "'On a BOQ' is used in 1 place (BOQs 1)" in refused.json()["detail"] and "Confirm" in refused.json()["detail"]
    assert tenant.get("/api/items/%d" % item["id"]).json()["item"]["is_active"] is True
    done = tenant.patch("/api/items/%d/status" % item["id"], json={"is_active": False, "confirm": True})
    assert done.status_code == 200 and done.json()["item"]["is_active"] is False
    _, by = groups(tenant, item["id"])
    assert by["boq"]["count"] == 1, "the BOQ still carries it"
    assert tenant.patch("/api/items/%d/status" % item["id"], json={"is_active": True}).status_code == 200, "switching on never needs a warning"


def test_bulk_switching_off_counts_the_ones_in_use_and_changes_nothing_until_confirmed(tenant):
    used, free = make_item(tenant, "BLKU-1", "In use"), make_item(tenant, "BLKU-2", "Free")
    site_with(tenant, "Site A", [("BLKU-1", 1, 1)])
    ids = [used["id"], free["id"]]
    refused = tenant.post("/api/items/bulk-status", json={"ids": ids, "is_active": False})
    assert refused.status_code == 409 and refused.json()["detail"].startswith("1 of these 2 items is used")
    assert tenant.get("/api/items", params={"status": "inactive"}).json()["total"] == 0, "nothing was changed"
    assert tenant.post("/api/items/bulk-status", json={"ids": ids, "is_active": False, "confirm": True}).status_code == 200
    assert tenant.get("/api/items", params={"status": "inactive"}).json()["total"] == 2
    only_free = make_item(tenant, "BLKU-3", "Also free")
    assert tenant.post("/api/items/bulk-status", json={"ids": [only_free["id"]], "is_active": False}).status_code == 200


def test_where_used_is_only_for_your_own_items(tenant, second_tenant):
    item = make_item(tenant, "PRIV-1", "Private")
    assert second_tenant.get("/api/items/%d/where-used" % item["id"]).status_code == 404
