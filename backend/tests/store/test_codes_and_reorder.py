"""Scanning on a construction store's floor, and the reorder alert, through the API.

A rack or yard-bay tag finds its bin and store, an item's rack label or the maker's barcode on a can of admixture finds the
item, and a store document's number (the gate pass at the gate) finds the document. Labels print as a sheet of QR codes.
Stock issued down to an item's reorder level raises one alert on the dashboard, as it crosses."""
import uuid
from datetime import date

from app import db as database, models
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _stock(t, central, w, bags="100"):
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "supplier_name": "Shree Traders",
                                                    "lines": [{"item_id": w["item"], "qty": bags, "uom": "bag", "rate": "350"}]}))
    return walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")


def _issue(t, central, w, bags):
    return ok(t.post("/api/store/outward/issue/direct", json={
        "store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
        "lines": [{"item_id": w["item"], "qty": bags, "uom": "bag", "cost_head": "OVERHEAD"}]}))


def test_scanning_finds_items_by_code_or_maker_barcode_bins_and_documents(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    ok(t.post("/api/store/masters/stores/%d/bins" % central["id"], json={"code": "R1-A", "description": "Rack 1, shelf A"}))

    # The item's own code - what its rack label carries, and what a handheld scanner types.
    found = ok(t.get("/api/store/lookup/scan", params={"code": w["code"].lower()}))
    assert found["kind"] == "item" and found["item"]["id"] == w["item"] and found["item"]["base_uom"] == "kg"

    # The maker's barcode on the bag, once linked to the item; one barcode names one item.
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "barcode": "8901234567890"}))
    assert ok(t.get("/api/store/lookup/scan", params={"code": "8901234567890"}))["item"]["id"] == w["item"]
    with database.SessionLocal() as s:
        other = models.DBItem(client_id=s.query(models.DBItem).get(w["item"]).client_id, kind="RM", item_code="CO-SAND-" + tag, item_name="River sand", units_of_measure="cum")
        s.add(other)
        s.commit()
        other_id = other.id
    res = t.put("/api/store/masters/items/%d/settings" % other_id, json={"category": "CONSUMABLE", "base_uom": "cum", "barcode": "8901234567890"})
    assert res.status_code == 409 and w["code"] in res.json()["detail"]

    # A rack or yard-bay tag.
    found = ok(t.get("/api/store/lookup/scan", params={"code": "BIN:%s:r1-a" % central["code"]}))
    assert found["kind"] == "bin" and found["store"]["id"] == central["id"] and found["bin"]["code"] == "R1-A"

    # A store document's number - a goods receipt here; a gate pass is found the same way at the gate.
    grn = _stock(t, central, w)
    found = ok(t.get("/api/store/lookup/scan", params={"code": grn["number"]}))
    assert found == {"kind": "document", "doc": "grn", "id": grn["id"], "number": grn["number"], "status": "POSTED", "path": "/store/hub/inward/grn/%d" % grn["id"]}

    res = t.get("/api/store/lookup/scan", params={"code": "NO-SUCH-CODE"})
    assert res.status_code == 404 and "maker's barcode" in res.json()["detail"]

    # The labels to stick up: bins of the store, and the items it holds.
    for kind in ("bins", "items"):
        res = t.get("/api/store/masters/labels.pdf", params={"store_id": central["id"], "kind": kind})
        assert res.status_code == 200 and res.headers["content-type"] == "application/pdf" and res.content.startswith(b"%PDF")


def test_issuing_down_to_the_reorder_level_raises_one_alert(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "4000"}))
    _stock(t, central, w)                                                       # 5000 kg

    def alerts():
        with database.SessionLocal() as s:
            return s.query(models.DBAlert).filter(models.DBAlert.kind == "store_reorder", models.DBAlert.ref_id == w["item"]).all()

    _issue(t, central, w, "10")                                                 # 4500 kg: still above
    assert alerts() == []
    _issue(t, central, w, "20")                                                 # 3500 kg: crosses
    [alert] = alerts()
    assert "reorder level" in alert.title and "3500 kg left" in alert.body and alert.view == "reorder-view"
    _issue(t, central, w, "10")                                                 # 3000 kg: already below, no second alert
    assert len(alerts()) == 1
