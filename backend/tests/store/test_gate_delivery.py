"""A gate delivery, through the API: a lorry unloaded before its purchase order was raised is received on its challan and
posted to stock at once, then linked to the order when purchasing raises it - checked against what was ordered like any
receipt, the order counting it received, and the difference from the order's rate kept as the receipt's price variance."""
import uuid
from datetime import date

from app import db as database
from app.models.store_core import DBStoreStockBalance
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()
CHALLAN = {"challan_no": "DC-881", "challan_date": TODAY, "vehicle_no": "AP39 TB 4411", "driver_remarks": "Driver Ramesh, came at 9 pm, 100 bags"}


def _gate(t, central, item, qty="100", rate="340", **over):
    body = dict(store_id=central["id"], grn_date=TODAY, supplier_name="Shree Traders", gate_delivery=True,
                lines=[{"item_id": item, "qty": qty, "uom": "bag", "rate": rate}], **CHALLAN)
    body.update(over)
    return t.post("/api/store/inward/grn", json=body)


def test_a_gate_delivery_is_stock_at_once_and_is_linked_to_its_order_later(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]                                              # 200 bags at 350

    # The challan, vehicle and the driver's word are what it is matched on later: none may be left out.
    res = _gate(t, central, w["item"], driver_remarks="", vehicle_no="")
    assert res.status_code == 400 and "vehicle number" in res.json()["detail"] and "driver" in res.json()["detail"]
    # It has no order: one named is a normal receipt, not a gate delivery.
    assert _gate(t, central, w["item"], po_id=po_id).status_code == 400

    grn = ok(_gate(t, central, w["item"]))
    assert grn["gate_delivery"] is True and grn["po_id"] is None and grn["driver_remarks"].startswith("Driver Ramesh")
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:                                        # 100 bags is 5000 kg, at 6.80 a kg
        bal = s.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == central["id"], DBStoreStockBalance.item_id == w["item"]).one()
        assert str(bal.qty) == "5000.000" and str(bal.value) == "34000.00"

    # Purchasing raises the order; the storekeeper links the delivery to it.
    linked = ok(t.post("/api/store/inward/grn/%d/link-po" % grn["id"], json={"po_id": po_id}))
    assert linked["po_id"] == po_id and linked["lines"][0]["po_line_id"] == po_line and linked["linked_by"]
    assert linked["price_variance"] == "1000.00"                              # 5000 kg x (7.00 ordered - 6.80 at the gate)
    po = ok(t.get("/api/purchase-orders/%d" % po_id))
    assert po["line_items"][0]["received_qty"] == 100.0 and po["store_receipt"][0]["accepted_qty"] == "5000.000"
    with database.SessionLocal() as s:                                        # the stock keeps the value it came in at
        bal = s.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == central["id"], DBStoreStockBalance.item_id == w["item"]).one()
        assert str(bal.value) == "34000.00"
    assert t.post("/api/store/inward/grn/%d/link-po" % grn["id"], json={"po_id": po_id}).status_code == 409

    # A second lorry with no rate known is valued at what the store already holds the item at.
    second = ok(_gate(t, central, w["item"], qty="50", rate=""))
    assert second["lines"][0]["rate"] == "6.8000"


def test_a_gate_delivery_is_not_linked_past_what_was_ordered_or_to_someone_else_s_order(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, _line = w["pos"][0]

    # No stock and no purchase rate: the gate must give an estimate.
    res = _gate(t, central, w["item"], rate="")
    assert res.status_code == 400 and "estimated rate" in res.json()["detail"]

    big = ok(_gate(t, central, w["item"], qty="300"))                         # 300 bags against an order for 200
    walk(t, "inward", "grn", big["id"], "submit", "approve", "post")
    res = t.post("/api/store/inward/grn/%d/link-po" % big["id"], json={"po_id": po_id})
    assert res.status_code == 409 and "ordered" in res.json()["detail"]

    other = ok(_gate(t, central, w["item"], qty="10", supplier_name="Balaji Cements"))
    walk(t, "inward", "grn", other["id"], "submit", "approve", "post")
    res = t.post("/api/store/inward/grn/%d/link-po" % other["id"], json={"po_id": po_id})
    assert res.status_code == 409 and "Shree Traders" in res.json()["detail"]

    # An ordinary receipt was never a gate delivery, and a draft gate delivery is simply edited.
    draft = ok(_gate(t, central, w["item"], qty="5"))
    assert t.post("/api/store/inward/grn/%d/link-po" % draft["id"], json={"po_id": po_id}).status_code == 409
