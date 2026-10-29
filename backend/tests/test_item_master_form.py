"""Making an item: a suggested code, a warning before a repeat is saved, and refusals that say what to do."""
from test_site_pricing import make_item


def test_the_next_code_is_suggested_and_is_free(tenant):
    first = tenant.get("/api/items/next-code").json()["code"]
    assert first and len(first) == 6
    assert tenant.get("/api/items/next-code").json()["code"] == first, "asking does not use the code up"
    made = tenant.post("/api/items", json={"item_code": first, "item_name": "Takes the suggestion", "units_of_measure": "Nos"})
    assert made.status_code == 200 and made.json()["item"]["item_code"] == first
    assert tenant.get("/api/items/next-code").json()["code"] != first, "once it is taken the suggestion moves on"
    blank = tenant.post("/api/items", json={"item_name": "Takes the next one", "units_of_measure": "Nos"}).json()["item"]["item_code"]
    assert blank not in (first, "")


def test_a_repeat_is_noticed_by_code_by_name_and_by_a_close_name(tenant):
    make_item(tenant, "STL-TMT12", "Steel TMT bar 12mm", units_of_measure="Kgs")
    make_item(tenant, "CEM-OPC53", "Cement OPC 53 grade", units_of_measure="Bags")
    by_code = tenant.get("/api/items/similar", params={"code": "stl-tmt12"}).json()["similar"]
    assert [(i["item_code"], i["reason"]) for i in by_code] == [("STL-TMT12", "Same code")]
    same = tenant.get("/api/items/similar", params={"name": "steel  TMT bar 12MM"}).json()["similar"]
    assert same[0]["item_code"] == "STL-TMT12" and same[0]["reason"] == "Same name"
    close = tenant.get("/api/items/similar", params={"name": "Cement OPC 53"}).json()["similar"]
    assert close and close[0]["item_code"] == "CEM-OPC53" and close[0]["reason"] == "Looks similar"
    assert tenant.get("/api/items/similar", params={"name": "Plywood 19mm"}).json()["similar"] == []
    assert tenant.get("/api/items/similar").json()["similar"] == []


def test_an_item_being_edited_is_not_its_own_repeat(tenant):
    item = make_item(tenant, "EDT-1", "Brick masonry in CM 1:6")
    got = tenant.get("/api/items/similar", params={"name": "Brick masonry in CM 1:6", "code": "EDT-1", "exclude_id": item["id"]}).json()["similar"]
    assert got == []


def test_a_taken_code_is_refused_naming_the_item_that_has_it(tenant, second_tenant):
    make_item(tenant, "DUP-1", "Steel TMT 12mm")
    res = tenant.post("/api/items", json={"item_code": "dup-1", "item_name": "Something else", "units_of_measure": "Nos"})
    assert res.status_code == 409
    assert res.json()["detail"] == "This code is already used by 'Steel TMT 12mm'. Use a different code, or open that item."
    other = second_tenant.post("/api/items", json={"item_code": "DUP-1", "item_name": "Mine", "units_of_measure": "Nos"})
    assert other.status_code == 409 and "Steel TMT" not in other.json()["detail"], "another company's item is not named"
    assert second_tenant.get("/api/items/similar", params={"code": "DUP-1"}).json()["similar"] == []


def test_only_real_gst_rates_are_accepted(tenant):
    for good in (0, 5, 12, 18, 28):
        assert tenant.post("/api/items", json={"item_name": "Gst %d" % good, "units_of_measure": "Nos", "gst_percent": good}).status_code == 200
    for bad in (7, 18.5, 100, -1):
        res = tenant.post("/api/items", json={"item_name": "Bad gst", "units_of_measure": "Nos", "gst_percent": bad})
        assert res.status_code == 422 and "0, 5, 12, 18 or 28" in res.json()["detail"]


def test_a_material_and_a_work_item_are_both_made_from_the_same_form(tenant):
    material = tenant.post("/api/items", json={"item_name": "River sand", "units_of_measure": "cum", "kind": "RM", "item_type": "Purchased"}).json()["item"]
    work = tenant.post("/api/items", json={"item_name": "PCC M15", "units_of_measure": "cum", "kind": "FG", "item_type": "Work"}).json()["item"]
    assert (material["kind"], work["kind"]) == ("RM", "FG")
    assert tenant.post("/api/items", json={"item_name": "Odd", "units_of_measure": "cum", "kind": "XX"}).status_code == 400
    # An edit that does not say what the item is leaves it as it was.
    edited = tenant.put("/api/items/%d" % material["id"], json={"item_name": "River sand (Zone II)", "units_of_measure": "cum"}).json()["item"]
    assert edited["kind"] == "RM"
