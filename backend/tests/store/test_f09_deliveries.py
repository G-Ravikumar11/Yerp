"""What suppliers still owe: the pending-deliveries list, short-closing an order so nothing more is received against it (and reopening it), and
the supplier scorecard."""
import uuid
from datetime import date, timedelta

from app import db as database, models
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _grn(t, central, po_id, po_line, qty="50"):
    return ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "supplier_name": "Shree Traders",
                                                     "lines": [{"po_line_id": po_line, "qty": qty, "uom": "bag"}]}))


def test_pending_list_follows_what_has_been_received(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    [po] = ok(t.get("/api/store/deliveries/pending"))["items"]
    assert po["number"] == "PO-%s-0" % tag and po["lines"][0]["pending"] == "10000.000" and po["days_late"] == 0
    walk(t, "inward", "grn", _grn(t, central, po_id, po_line)["id"], "submit", "approve", "post")
    [po] = ok(t.get("/api/store/deliveries/pending"))["items"]
    assert po["lines"][0]["accepted"] == "2500.000" and po["lines"][0]["pending"] == "7500.000"
    assert ok(t.get("/api/store/deliveries/pending", params={"supplier": "nobody"}))["items"] == []


def test_a_late_order_shows_how_late(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    _hub(t, w, tag)
    with database.SessionLocal() as s:
        s.get(models.DBPurchaseOrder, w["pos"][0][0]).needed_by = (date.today() - timedelta(days=4)).isoformat()
        s.commit()
    assert ok(t.get("/api/store/deliveries/pending"))["items"][0]["days_late"] == 4


def test_short_closing_stops_receiving_and_can_be_undone(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    walk(t, "inward", "grn", _grn(t, central, po_id, po_line)["id"], "submit", "approve", "post")
    open_draft = _grn(t, central, po_id, po_line, "10")
    url = "/api/store/deliveries/%d/short-close" % po_id
    assert t.post(url, json={"reason": ""}).status_code == 400
    assert t.post(url, json={"reason": "Supplier cannot supply the rest"}).status_code == 409        # a receipt is still open
    ok(t.post("/api/store/inward/grn/%d/cancel" % open_draft["id"], json={"reason": "not needed"}))
    assert ok(t.post(url, json={"reason": "Supplier cannot supply the rest"}))["po_id"] == po_id
    assert t.post(url, json={"reason": "again"}).status_code == 409

    assert ok(t.get("/api/store/deliveries/pending"))["items"] == []
    assert ok(t.get("/api/store/inward/po-options"))["items"] == []
    assert [r["number"] for r in ok(t.get("/api/store/deliveries/short-closed"))["items"]] == ["PO-%s-0" % tag]
    refused = t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": "5", "uom": "bag"}]})
    assert refused.status_code == 409 and "short-closed" in refused.json()["detail"]

    ok(t.post("/api/store/deliveries/%d/reopen" % po_id))
    assert t.post("/api/store/deliveries/%d/reopen" % po_id).status_code == 404
    assert len(ok(t.get("/api/store/deliveries/pending"))["items"]) == 1
    _grn(t, central, po_id, po_line, "5")


def test_supplier_scorecard(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    po_id, po_line = w["pos"][0]
    with database.SessionLocal() as s:
        s.get(models.DBPurchaseOrder, po_id).needed_by = (date.today() + timedelta(days=2)).isoformat()
        s.commit()
    walk(t, "inward", "grn", _grn(t, central, po_id, po_line, "100")["id"], "submit", "approve", "post")      # half of the 200 bags
    [card] = ok(t.get("/api/store/deliveries/suppliers"))["items"]
    assert card["supplier_name"] == "Shree Traders" and card["orders"] == 1
    assert card["ordered_value"] == "70000.00" and card["accepted_value"] == "35000.00" and card["fill_pct"] == "50.0"
    assert card["rejection_pct"] == "0.0" and card["on_time_pct"] == "100.0"
