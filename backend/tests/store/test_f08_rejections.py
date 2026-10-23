"""Goods turned away at the gate: a posted receipt leaves a HELD record per rejected line, closed by returning or disposing of the
goods; cancelling the receipt voids it. None of it touches stock."""
import uuid
from datetime import date

from app import db as database
from app.models.store_core import DBStoreStockBalance
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _grn(t, central, w, po_id, po_line):
    return ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "supplier_name": "Shree Traders",
                                                     "lines": [{"po_line_id": po_line, "qty": "100", "uom": "bag", "rejected_qty": "10", "reject_reason": "Lumps in the bags"}]}))


def test_rejected_goods_are_held_then_returned_or_disposed(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    grn = _grn(t, central, w, po_id, po_line)
    assert ok(t.get("/api/store/rejections"))["items"] == []                       # nothing until the receipt posts
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")

    [row] = ok(t.get("/api/store/rejections"))["items"]
    assert row["status"] == "HELD" and row["qty"] == "500.000" and row["reason"] == "Lumps in the bags" and row["grn_number"] == grn["number"]
    with database.SessionLocal() as s:                                              # only the accepted 90 bags (4500 kg) is stock
        bal = s.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == central["id"], DBStoreStockBalance.item_id == w["item"]).one()
        assert str(bal.qty) == "4500.000"

    url = "/api/store/rejections/%d/resolve" % row["id"]
    assert t.post(url, json={"outcome": "RETURNED"}).status_code == 400            # the vehicle it went on is needed
    assert t.post(url, json={"outcome": "SOLD"}).status_code == 400
    done = ok(t.post(url, json={"outcome": "RETURNED", "vehicle_no": "AP39 TB 4411"}))
    assert done["status"] == "RETURNED" and done["vehicle_no"] == "AP39 TB 4411" and done["resolved_on"] == TODAY
    assert t.post(url, json={"outcome": "DISPOSED", "note": "Dumped"}).status_code == 409
    assert ok(t.get("/api/store/rejections"))["items"] == []
    assert len(ok(t.get("/api/store/rejections", params={"status": "RETURNED"}))["items"]) == 1


def test_cancelling_the_receipt_voids_the_held_goods(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    grn = _grn(t, central, w, po_id, po_line)
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    assert len(ok(t.get("/api/store/rejections"))["items"]) == 1
    ok(t.post("/api/store/inward/grn/%d/cancel" % grn["id"], json={"reason": "Wrong supplier"}))
    assert ok(t.get("/api/store/rejections"))["items"] == []
    assert ok(t.get("/api/store/rejections", params={"status": ""}))["items"] == []     # voided ones are not listed at all


def test_disposal_needs_a_note(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    grn = _grn(t, central, w, po_id, po_line)
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    [row] = ok(t.get("/api/store/rejections"))["items"]
    url = "/api/store/rejections/%d/resolve" % row["id"]
    assert t.post(url, json={"outcome": "DISPOSED"}).status_code == 400
    assert ok(t.post(url, json={"outcome": "DISPOSED", "note": "Dumped at the yard"}))["status"] == "DISPOSED"
