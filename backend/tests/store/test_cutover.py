"""Moving the old store into the Store Hub, through the API: the old store's closing stock becomes Hub opening stock at
its own rate, the old store refuses new entries afterwards, and the screens written against the old store - purchase
orders, project costs, current stock - count the Hub and the old history together without counting anything twice."""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion
from app.services import store_integration

D = Decimal
TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


def ok(res):
    assert res.status_code == 200, (res.request.method, res.request.url, res.text)
    return res.json()


def walk(t, base, kind, doc_id, *steps):
    last = None
    for step in steps:
        last = ok(t.post("/api/store/%s/%s/%d/%s" % (base, kind, doc_id, step)))
    return last


def _company(account, tag, orders=1):
    """A project, cement in the Item Master (kept in kg in the Hub, bought in bags) and approved orders for 200 bags."""
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        job = models.DBJob(client_id=client.id, number="P-" + tag, name="Tower A")
        s.add(job)
        code = "CO-CEM-" + tag
        item = models.DBItem(client_id=client.id, kind="RM", item_code=code, item_name="Cement OPC", units_of_measure="kg")
        s.add(item)
        s.flush()
        pos = []
        for n in range(orders):
            po = models.DBPurchaseOrder(client_id=client.id, job_id=job.id, number="PO-%s-%d" % (tag, n), supplier_name="Shree Traders",
                                        status="Approved", issue_date=TODAY)
            s.add(po)
            s.flush()
            line = models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_code=code, uom="bag", qty=200, price=350.0)
            s.add(line)
            s.flush()
            pos.append((po.id, line.id))
        s.commit()
        return {"client_id": client.id, "job": job.id, "item": item.id, "code": code, "pos": pos}


def _hub(t, w, tag):
    central = ok(t.post("/api/store/masters/stores", json={"code": "CS" + tag[:3].upper(), "name": "Central", "type": "CENTRAL"}))
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg"}))
    ok(t.put("/api/store/masters/items/%d/conversions/bag" % w["item"], json={"to_base_factor": "50"}))
    return central


def _old_receipt(t, po_id):
    grn = ok(t.post("/api/grn", json={"purchase_order_id": po_id, "store_location": "Main store", "received_on": TODAY}))
    gid = (grn.get("goods_receipt") or grn)["id"]
    return ok(t.post("/api/grn/%d/post" % gid))


def test_old_store_moves_into_the_hub_and_is_kept_as_a_record(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]

    # The old store: 200 bags in at 350, 40 issued to the project.
    _old_receipt(t, po_id)
    issue = ok(t.post("/api/stock-issues", json={"job_id": w["job"], "store": "Main store", "issued_on": TODAY,
                                                  "lines": [{"item_code": w["code"], "quantity": 40}]}))
    ok(t.post("/api/stock-issues/%d/post" % issue["issue"]["id"], json={}))
    material_before = ok(t.get("/api/jobs/%d/pnl" % w["job"]))["cost"]["material_from_store"]
    assert material_before == 14000.0                                       # 40 bags at 350

    # What moving would carry: 160 bags of cement from the Main store, nothing in the way.
    preview = ok(t.get("/api/stock/cutover"))
    assert preview["done"] is None and preview["problems"] == []
    [main] = preview["stores"]
    assert main["name"] == "Main store" and main["items"][0]["on_hand"] == 160.0 and main["items"][0]["rate"] == 350.0

    # It needs a Hub store for each old store that holds anything.
    assert t.post("/api/stock/cutover", json={"cutover_date": TODAY, "stores": {}}).status_code == 400
    done = ok(t.post("/api/stock/cutover", json={"cutover_date": TODAY, "stores": {"Main store": central["id"]}}))
    assert done["done"]["cutover_date"] == TODAY and done["done"]["carried"][0]["value"] == 56000.0

    # The Hub now holds it: 160 bags is 8000 kg, at 7 a kg - the same 56,000.
    with database.SessionLocal() as s:
        bal = s.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == central["id"], DBStoreStockBalance.item_id == w["item"]).one()
        assert bal.qty == D("8000.000") and bal.value == D("56000.00")
        assert store_integration.current_stock(s, w["client_id"], {w["code"]})[w["code"]]["on_hand"] == 8000.0

    # Once only, and the old store takes nothing more.
    assert t.post("/api/stock/cutover", json={"cutover_date": TODAY, "stores": {"Main store": central["id"]}}).status_code == 409
    assert t.post("/api/stock-issues", json={"job_id": w["job"], "store": "Main store", "lines": [{"item_code": w["code"], "quantity": 1}]}).status_code == 409
    assert t.post("/api/grn", json={"purchase_order_id": po_id}).status_code == 409
    assert t.post("/api/stock/adjustments", json={"item_code": w["code"], "counted": 1, "remarks": "count"}).status_code == 409
    assert ok(t.get("/api/stock/cutover", params={"brief": True}))["done"]["cutover_date"] == TODAY
    assert ok(t.get("/api/stock"))["stock"]                                  # its history is still there to read

    # An issue from the Hub adds to the project's material; the old issue still counts, and nothing is counted twice.
    hub_issue = ok(t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN",
                                                              "received_by_name": "Suresh", "lines": [{"item_id": w["item"], "qty": "20", "uom": "bag", "cost_head": "OVERHEAD"}]}))
    walk(t, "outward", "issue", hub_issue["id"], "submit", "approve", "post")
    assert ok(t.get("/api/jobs/%d/pnl" % w["job"]))["cost"]["material_from_store"] == 21000.0     # 14,000 + 1,000 kg at 7

    # The order was wholly received in the old store: the Hub does not show it as still to come.
    summary = ok(t.get("/api/purchase-orders/%d" % po_id))["store_receipt"][0]
    assert summary["accepted_qty"] == "10000.000" and summary["pending_qty"] == "0.000"


def test_hub_receipts_count_on_the_purchase_order_in_its_own_unit(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]

    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "challan_no": "CH-1",
                                                    "lines": [{"po_line_id": po_line, "qty": "100", "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")

    po = ok(t.get("/api/purchase-orders/%d" % po_id))
    assert po["line_items"][0]["received_qty"] == 100.0 and po["receipt_count"] == 1              # 5000 kg is 100 bags
    # An old receipt drawn up now is for what is still to come, not the whole order again.
    grn_old = ok(t.post("/api/grn", json={"purchase_order_id": po_id, "store_location": "Main store"}))
    lines = (grn_old.get("goods_receipt") or grn_old)["lines"]
    assert lines[0]["previously_received"] == 100.0

    # The invoice tracker sees the Hub's receipt, under an id that cannot meet an old receipt's.
    tracker = ok(t.get("/api/invoice-tracker"))
    hub_rows = [i for i in tracker["invoices"] if i["grn_id"] < 0]
    assert len(hub_rows) == 1 and hub_rows[0]["amount"] == 35000.0 and hub_rows[0]["invoice_number"] == "CH-1"
    ok(t.put("/api/invoice-tracker/invoices/%d" % hub_rows[0]["grn_id"], json={"invoice_amount": 41300}))
    assert [i for i in ok(t.get("/api/invoice-tracker"))["invoices"] if i["grn_id"] < 0][0]["invoice_amount"] == 41300.0


def test_cutover_refuses_what_the_hub_cannot_hold(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    # Counted into the old store under a code the Item Master does not have.
    ok(t.post("/api/stock/adjustments", json={"item_code": "NOT-A-CODE-" + tag, "counted": 5, "remarks": "found"}))
    preview = ok(t.get("/api/stock/cutover"))
    assert any("Not in the Item Master" in p for p in preview["problems"])
    res = t.post("/api/stock/cutover", json={"cutover_date": TODAY, "stores": {"Main store": central["id"]}})
    assert res.status_code == 409 and "Item Master" in res.json()["detail"]
    assert ok(t.get("/api/stock/cutover", params={"brief": True}))["done"] is None
