"""The gaps in an item master: the make and segment the old ERP kept, an item's kind put right, the details still
missing found and filled in together, and the old ERP's own item list read as it is."""
import io

import openpyxl

from test_item_master_import import preview, to_commit
from test_site_pricing import make_item

OLD_ERP = ["Item Code", "Item Name", "Segment", "Description", "Category", "Sub Category", "HSN Code", "Item Tax Type", "Item Type",
           "Units Of Measure", "Make"]


def test_make_and_segment_are_kept_shown_and_searched(tenant):
    res = tenant.post("/api/items", json={"item_name": "Cement OPC 53 grade", "kind": "RM", "units_of_measure": "Bags",
                                          "make": "  UltraTech ", "segment": "YPPL"})
    assert res.status_code == 200, res.text
    item = res.json()["item"]
    assert item["make"] == "UltraTech" and item["segment"] == "YPPL"
    found = tenant.get("/api/items", params={"q": "ultratech"}).json()["items"]
    assert [i["id"] for i in found] == [item["id"]]
    wb = openpyxl.load_workbook(io.BytesIO(tenant.get("/api/items/export.xlsx").content))
    rows = [[c.value for c in r] for r in wb.active.iter_rows()]
    head = next(r for r in rows if r and r[0] == "Item Code")
    row = next(r for r in rows if r and r[0] == item["item_code"])
    assert row[head.index("Make")] == "UltraTech" and row[head.index("Segment")] == "YPPL"
    assert row[head.index("What is it?")] == "Material"


def test_an_item_can_be_put_right_as_a_material_or_a_work_item(tenant):
    item = make_item(tenant, "KND-1", "Binding wire 18 gauge", units_of_measure="Kgs")
    assert item["kind"] == "FG"
    res = tenant.put("/api/items/%d" % item["id"], json={"item_name": "Binding wire 18 gauge", "kind": "RM", "units_of_measure": "Kgs"})
    assert res.status_code == 200 and res.json()["item"]["kind"] == "RM"
    assert tenant.get("/api/items", params={"kind": "RM", "q": "KND-1"}).json()["total"] == 1


def test_what_an_item_is_stays_once_something_uses_it(tenant):
    """A BOQ was made with it as a work item: turning it into a material under that BOQ is refused, one item or many."""
    from test_site_pricing import site_with
    used = make_item(tenant, "USD-1", "PCC M15 in foundation")
    free = make_item(tenant, "USD-2", "PCC M20 in raft")
    site_with(tenant, "Kind site", [("USD-1", 10, 5000)])
    res = tenant.put("/api/items/%d" % used["id"], json={"item_name": used["item_name"], "units_of_measure": "cum", "kind": "RM"})
    assert res.status_code == 409 and "cannot change now" in res.json()["detail"]
    res = tenant.post("/api/items/bulk-update", json={"ids": [used["id"], free["id"]], "kind": "RM"})
    assert res.status_code == 409
    assert tenant.get("/api/items/%d" % free["id"]).json()["item"]["kind"] == "FG", "all or none"
    # Saying it is what it already is changes nothing and is not refused.
    assert tenant.put("/api/items/%d" % used["id"], json={"item_name": used["item_name"], "units_of_measure": "cum", "kind": "FG"}).status_code == 200


def test_the_list_counts_materials_and_work_items(tenant):
    make_item(tenant, "CNT-1", "PCC M15", units_of_measure="cum")
    tenant.post("/api/items", json={"item_name": "Sand", "kind": "RM", "units_of_measure": "cum", "item_code": "CNT-2"})
    body = tenant.get("/api/items", params={"q": "CNT-", "kind": "RM"}).json()
    assert body["total"] == 1 and body["counts"] == {"RM": 1, "FG": 1}


def test_what_is_missing_is_counted_and_found(tenant):
    a = tenant.post("/api/items", json={"item_name": "Sand", "kind": "RM", "units_of_measure": "cum", "item_code": "GAP-1"}).json()["item"]
    tenant.post("/api/items", json={"item_name": "Cement", "kind": "RM", "units_of_measure": "Bags", "item_code": "GAP-2",
                                    "item_category": "Cement", "gst_percent": 28, "hsn_code": "2523", "purchase_rate": 390, "make": "ACC"})
    make_item(tenant, "GAP-3", "PCC M15", units_of_measure="cum")          # filed under a category, no GST or HSN
    gaps = tenant.get("/api/items/gaps").json()
    # A work item is not bought: it is never short of a purchase rate or a make.
    assert gaps["total"] == 3 and gaps["rate"] == 1 and gaps["make"] == 1
    assert gaps["category"] == 1 and gaps["gst"] == 2 and gaps["hsn"] == 2
    missing = {i["item_code"] for i in tenant.get("/api/items", params={"missing": "make"}).json()["items"]}
    assert missing == {a["item_code"]}
    no_gst = {i["item_code"] for i in tenant.get("/api/items", params={"missing": "gst"}).json()["items"]}
    assert no_gst == {"GAP-1", "GAP-3"}
    assert tenant.get("/api/items", params={"missing": "colour"}).status_code == 422


def test_several_items_are_filled_in_together_and_nothing_else_moves(tenant):
    a = tenant.post("/api/items", json={"item_name": "Sand", "kind": "RM", "units_of_measure": "cum", "make": "Local",
                                        "hsn_code": "2505"}).json()["item"]
    b = make_item(tenant, "BLK-2", "Aggregate 20mm", units_of_measure="cum")
    res = tenant.post("/api/items/bulk-update", json={"ids": [a["id"], b["id"]], "item_category": "Sand & Aggregate",
                                                      "gst_percent": 5, "kind": "RM"})
    assert res.status_code == 200, res.text
    after = {i["id"]: tenant.get("/api/items/%d" % i["id"]).json()["item"] for i in (a, b)}
    for got in after.values():
        assert got["item_category"] == "Sand & Aggregate" and got["item_tax_type"] == "5%" and got["kind"] == "RM"
    assert after[a["id"]]["make"] == "Local" and after[a["id"]]["hsn_code"] == "2505", "what was not sent is left alone"


def test_a_bad_bulk_change_changes_nothing(tenant):
    a = tenant.post("/api/items", json={"item_name": "Sand", "kind": "RM", "units_of_measure": "cum"}).json()["item"]
    for body in ({"item_category": "No such category"}, {"gst_percent": 7}, {"units_of_measure": "furlong"}, {"kind": "XX"}):
        res = tenant.post("/api/items/bulk-update", json={"ids": [a["id"]], "make": "Changed", **body})
        assert res.status_code in (400, 422), body
    assert tenant.post("/api/items/bulk-update", json={"ids": [a["id"]]}).status_code == 422
    assert tenant.get("/api/items/%d" % a["id"]).json()["item"]["make"] == ""


def test_the_old_erps_item_list_comes_in_as_it_is(tenant):
    """Their list says RAW MATERIAL / RM where this master says Material, carries GST as 0.18 under Item Tax Type,
    leaves the Make column on its own prompt and spells units its own way. Every line of it comes in."""
    long_name = ("C1 - EI & FANS WIRING Installation of Wiring for light point/ fan point/ exhaust fan point/ call bell point with "
                 "1.5 sq.mm ZHFR insulated copper conductor single core cable in surface / recessed steel conduit, with modular "
                 "switch, modular plate, suitable GI box and earthing the point")
    prompt = "Please Select Option From Dropdown"
    body = preview(tenant, [
        ["", "", "", "", prompt, prompt, "", prompt, prompt, prompt, ""],
        ["RMRT27590", long_name, "YPPL", long_name, "RAW MATERIAL", "RM", "\xa0995461", 0.18, "Service", "EACH", "Make List"],
        ["RMRT27591", "Copper earth wire", "YPPL", "Copper earth wire", "RAW MATERIAL", "RM", "7408", 0.18, "Purchased", "kilograms", "Polycab"],
        ["RMRT27592", "Site watchman", "YPPL", "Site watchman", "RAW MATERIAL", "RM", "998525", 0.18, "Service", "Lump Sum per Month", ""],
    ], head=OLD_ERP)
    assert body["summary"] == {"total": 3, "new": 3, "update": 0, "duplicate": 0, "error": 0}, body["rows"]
    assert body["unused_columns"] == []
    v = {r["values"]["item_code"]: r["values"] for r in body["rows"]}
    assert v["RMRT27590"]["kind"] == "RM" and v["RMRT27590"]["item_category"] == "" and v["RMRT27590"]["gst_percent"] == "18"
    assert v["RMRT27590"]["hsn_code"] == "995461" and v["RMRT27590"]["make"] == "" and v["RMRT27590"]["segment"] == "YPPL"
    assert [v[c]["units_of_measure"] for c in ("RMRT27590", "RMRT27591", "RMRT27592")] == ["Nos", "Kgs", "Months"]
    done = tenant.post("/api/items/import/commit", json=to_commit(body)).json()
    assert done["created"] == 3, done
    items = {i["item_code"]: i for i in tenant.get("/api/items", params={"q": "RMRT", "kind": "RM"}).json()["items"]}
    assert items["RMRT27591"]["make"] == "Polycab" and items["RMRT27591"]["item_tax_type"] == "18%"
    long_item = items["RMRT27590"]
    assert len(long_item["item_name"]) <= 200 and long_name.startswith(long_item["item_name"])
    assert long_name[len(long_item["item_name"])] in " ,", "cut between words, not through one"
    assert long_item["description"] == long_name, "the whole text stays as the description"


def test_a_business_with_its_own_raw_material_category_keeps_it(tenant):
    tenant.post("/api/item-categories", json={"name": "Raw Material"})
    body = preview(tenant, [["RMX-1", "Sand", "", "", "Raw Material", "", "", "", "", "cum", ""]], head=OLD_ERP)
    assert body["rows"][0]["values"]["item_category"] == "Raw Material"
