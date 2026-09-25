"""E-way bills: goods over fifty thousand rupees do not go on the road
without one - a transfer of the contractor's own cement between sites as
much as a sale."""
from datetime import date, timedelta

from test_goods_receipt import order, receipt, set_lines, post


def setup_company(tenant):
    tenant.put("/api/gst/settings", json={"gstin": "36AABCY1234H1ZX"})
    tenant.post("/api/settings", json={"company_address": "Plot 12, Madhapur, Hyderabad 500081"})
    job = tenant.post("/api/jobs", json={"name": "Vanya City STP", "customer_name": "Arabtec",
                                         "site_address": "Kokapet, Hyderabad 500075"}).json()
    return job


def cement(tenant, hsn="25232930"):
    return tenant.post("/api/erp/items/bulk", json={"items": [
        {"kind": "RM", "item_name": "OPC 53 CEMENT", "units_of_measure": "Bags",
         "hsn_code": hsn}]}).json()["codes"][0]


def transfer(tenant, code, qty=200, price=400):
    po = order(tenant, lines=[{"description": "OPC 53", "item_code": code, "uom": "Bags",
                               "qty": 500, "price": price}])
    grn = receipt(tenant, po)
    set_lines(tenant, grn, [{"received_qty": 500, "rejected_qty": 0}])
    post(tenant, grn)
    store = tenant.get("/api/stock/stores").json()["stores"][0]["store"]
    res = tenant.post("/api/stock/transfers", json={"from_store": store, "to_store": "Vanya site store",
                                                   "lines": [{"item_code": code, "qty": qty}]})
    assert res.status_code == 200, res.text
    return res.json()["number"]


def from_transfer(tenant, ref, job, **over):
    body = {"source_type": "transfer", "source_ref": ref, "from_key": "company",
            "to_key": "job-%d" % job["id"], "distance_km": 18, "vehicle_no": "TS09UB1234"}
    body.update(over)
    res = tenant.post("/api/eway-bills", json=body)
    assert res.status_code == 200, res.text
    return res.json()["eway_bill"]


def test_a_transfer_over_the_threshold_is_flagged_until_it_has_one(tenant):
    job = setup_company(tenant)
    ref = transfer(tenant, cement(tenant))          # 200 bags x 400 = 80,000
    listing = tenant.get("/api/eway-bills").json()
    assert [t["number"] for t in listing["uncovered_transfers"]] == [ref]
    kinds = {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    assert "eway" in kinds
    from_transfer(tenant, ref, job)
    assert tenant.get("/api/eway-bills").json()["uncovered_transfers"] == []
    kinds = {i["kind"] for i in tenant.get("/api/attention").json()["items"]}
    assert "eway" not in kinds


def test_it_is_drawn_from_the_transfer_on_a_challan_for_own_use(tenant):
    job = setup_company(tenant)
    ref = transfer(tenant, cement(tenant))
    e = from_transfer(tenant, ref, job)
    assert e["doc_type"] == "CHL" and e["sub_type"] == "5" and e["doc_no"] == ref
    assert e["from"]["pincode"] == "500081" and e["to"]["pincode"] == "500075"
    assert e["from"]["state"] == e["to"]["state"] == "36"
    assert e["lines"][0]["hsn"] == "25232930" and e["lines"][0]["qty"] == 200
    assert e["total_value"] == 80000 and e["problems"] == []
    assert e["job_id"] == job["id"]


def test_the_portal_file_is_in_the_nic_format(tenant):
    job = setup_company(tenant)
    e = from_transfer(tenant, transfer(tenant, cement(tenant)), job)
    res = tenant.get("/api/eway-bills/%d/json" % e["id"])
    assert res.status_code == 200
    bill = res.json()["billLists"][0]
    assert bill["userGstin"] == "36AABCY1234H1ZX" and bill["supplyType"] == "O"
    assert bill["subSupplyType"] == 5 and bill["docType"] == "CHL"
    assert bill["fromPincode"] == 500081 and bill["toPincode"] == 500075
    assert bill["transDistance"] == 18 and bill["vehicleNo"] == "TS09UB1234"
    assert bill["itemList"][0]["qtyUnit"] == "BAG" and bill["itemList"][0]["hsnCode"] == 25232930
    assert bill["totInvValue"] == 80000


def test_what_the_portal_would_refuse_is_named_first(tenant):
    job = setup_company(tenant)
    ref = transfer(tenant, cement(tenant, hsn=""))
    e = from_transfer(tenant, ref, job, vehicle_no="TS 09 UB")
    assert any("HSN" in p for p in e["problems"])
    assert any("vehicle number" in p for p in e["problems"])
    res = tenant.get("/api/eway-bills/%d/json" % e["id"])
    assert res.status_code == 409 and "HSN" in res.json()["detail"]


def test_the_number_and_validity_come_back_from_the_portal(tenant):
    job = setup_company(tenant)
    e = from_transfer(tenant, transfer(tenant, cement(tenant)), job, distance_km=450)
    today = date.today().isoformat()
    assert tenant.post("/api/eway-bills/%d/generated" % e["id"], json={"ewb_no": "1234"}).status_code == 400
    out = tenant.post("/api/eway-bills/%d/generated" % e["id"],
                      json={"ewb_no": "3410 1234 5678", "ewb_date": today}).json()["eway_bill"]
    assert out["status"] == "GENERATED" and out["ewb_no"] == "341012345678"
    assert out["valid_upto"].startswith((date.today() + timedelta(days=3)).isoformat())
    # Generated: the portal is the place to change it now.
    assert tenant.put("/api/eway-bills/%d" % e["id"], json={"doc_no": "X"}).status_code == 409


def test_a_changed_lorry_is_recorded_as_part_b(tenant):
    job = setup_company(tenant)
    e = from_transfer(tenant, transfer(tenant, cement(tenant)), job)
    tenant.post("/api/eway-bills/%d/generated" % e["id"], json={"ewb_no": "341012345678"})
    assert tenant.post("/api/eway-bills/%d/vehicle" % e["id"], json={"vehicle_no": "bad"}).status_code == 400
    out = tenant.post("/api/eway-bills/%d/vehicle" % e["id"],
                      json={"vehicle_no": "AP16TG4471", "reason": "Breakdown"}).json()["eway_bill"]
    assert out["vehicle_no"] == "AP16TG4471" and "Breakdown" in out["vehicle_history"][0]


def test_cancelling_needs_a_reason_and_frees_the_transfer(tenant):
    job = setup_company(tenant)
    ref = transfer(tenant, cement(tenant))
    e = from_transfer(tenant, ref, job)
    assert tenant.post("/api/eway-bills/%d/cancel" % e["id"], json={"reason": ""}).status_code == 400
    tenant.post("/api/eway-bills/%d/cancel" % e["id"], json={"reason": "Lorry did not come"})
    again = tenant.post("/api/eway-bills", json={"source_type": "transfer", "source_ref": ref,
                                                 "from_key": "company", "to_key": "job-%d" % job["id"]})
    assert again.status_code == 200


def test_one_transfer_one_live_e_way_bill(tenant):
    job = setup_company(tenant)
    ref = transfer(tenant, cement(tenant))
    from_transfer(tenant, ref, job)
    res = tenant.post("/api/eway-bills", json={"source_type": "transfer", "source_ref": ref})
    assert res.status_code == 409


def test_a_manual_one_for_plant_moved_between_sites(tenant):
    job = setup_company(tenant)
    res = tenant.post("/api/eway-bills", json={
        "from_key": "company", "to_key": "job-%d" % job["id"], "doc_no": "DC-JCB-01",
        "distance_km": 22, "vehicle_no": "TS07EA5566",
        "lines": [{"product_name": "JCB 3DX backhoe loader", "hsn": "8429", "qty": 1, "unit": "Nos",
                   "taxable": 2500000}]})
    e = res.json()["eway_bill"]
    assert e["problems"] == [] and e["total_value"] == 2500000


def test_another_tenant_cannot_see_it(tenant, second_tenant):
    job = setup_company(tenant)
    e = from_transfer(tenant, transfer(tenant, cement(tenant)), job)
    assert second_tenant.get("/api/eway-bills/%d" % e["id"]).status_code == 404
