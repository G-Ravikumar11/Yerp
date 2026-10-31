"""Reorder levels per store, and an alert that is raised once while the stock stays low: raised when an issue takes a store to its level (even
if it was already below), not again on the next issue, cleared when stock is back above the level, and raised again after that. A scan raises it
for stock that was low before."""
import uuid
from decimal import Decimal
from datetime import date

from app import db as database, models
from app.models.store_extras import DBStoreReorderAlert
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()


def _alerts(client_id):
    with database.SessionLocal() as s:
        return s.query(models.DBAlert).filter(models.DBAlert.client_id == client_id, models.DBAlert.kind == "store_reorder").count()


def _receive(t, central, w, bags):
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": str(bags), "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")


def _issue(t, central, w, bags):
    doc = ok(t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
                                                       "lines": [{"item_id": w["item"], "qty": str(bags), "uom": "bag", "cost_head": "OVERHEAD"}]}))
    walk(t, "outward", "issue", doc["id"], "submit", "approve", "post")


def test_alert_is_raised_once_until_stock_is_back_above_the_level(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "3000"}))
    _receive(t, central, w, 100)                       # 5000 kg
    _issue(t, central, w, 20)                          # 4000 kg: above the level
    assert _alerts(w["client_id"]) == 0
    _issue(t, central, w, 20)                          # 3000 kg: at the level
    assert _alerts(w["client_id"]) == 1
    _issue(t, central, w, 10)                          # 2500 kg: still low, already told
    assert _alerts(w["client_id"]) == 1
    [row] = ok(t.get("/api/store/reports/reorder"))["rows"]
    assert row["qty"] == "2500.000" and row["reorder_level"] == "3000.000"
    # 3500 brings it back up; what the company's open orders still have to deliver is already coming.
    assert Decimal(row["suggested_qty"]) == max(Decimal(0), Decimal("3500") - Decimal(row["on_order"]))

    _receive(t, central, w, 100)                       # 7500 kg: back above, the alert closes
    with database.SessionLocal() as s:
        assert s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.client_id == w["client_id"], DBStoreReorderAlert.cleared_at.is_(None)).count() == 0
    _issue(t, central, w, 100)                         # 2500 kg: told again
    assert _alerts(w["client_id"]) == 2


def test_a_store_can_have_levels_of_its_own(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "3000", "min_qty": "500", "max_qty": "9000"}))
    _receive(t, central, w, 100)                       # 5000 kg
    url = "/api/store/levels/%d/%d" % (central["id"], w["item"])
    assert t.put(url, json={}).status_code == 400
    assert t.put(url, json={"reorder_level": "-1"}).status_code == 400
    assert t.put(url, json={"min_qty": "9500"}).status_code == 400                       # more than the item's maximum
    saved = ok(t.put(url, json={"reorder_level": "6000", "max_qty": "12000"}))
    assert saved["reorder_level"] == "6000.000" and saved["min_qty"] is None and saved["default_reorder_level"] == "3000.000"
    [lvl] = ok(t.get("/api/store/levels/%d" % central["id"]))["items"]
    assert lvl["item_name"] == "Cement OPC"
    [pos] = ok(t.get("/api/store/enquiry/balances", params={"store_id": central["id"]}))["items"]
    assert pos["status"] == "REORDER" and pos["reorder_level"] == "6000.000" and pos["max_qty"] == "12000.000" and pos["min_qty"] == "500.000"
    # Up to the store's maximum (7000), less what the open orders still have to deliver.
    row = ok(t.get("/api/store/reports/reorder"))["rows"][0]
    assert Decimal(row["suggested_qty"]) + Decimal(row["on_order"]) == Decimal("7000")
    ok(t.delete(url))
    assert t.delete(url).status_code == 404
    assert ok(t.get("/api/store/reports/reorder"))["rows"] == []


def test_scan_raises_the_alert_for_stock_already_low(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)                       # 5000 kg, no level set
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "6000"}))
    assert _alerts(w["client_id"]) == 0
    assert ok(t.post("/api/store/levels/scan"))["raised"] == 1
    assert ok(t.post("/api/store/levels/scan"))["raised"] == 0
    assert _alerts(w["client_id"]) == 1


def test_cancelling_an_issue_or_a_receipt_moves_the_alert_too(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "3000"}))
    _receive(t, central, w, 100)                       # 5000 kg
    doc = ok(t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN", "received_by_name": "Suresh",
                                                       "lines": [{"item_id": w["item"], "qty": "60", "uom": "bag", "cost_head": "OVERHEAD"}]}))
    walk(t, "outward", "issue", doc["id"], "submit", "approve", "post")          # 2000 kg: told
    assert _alerts(w["client_id"]) == 1
    ok(t.post("/api/store/outward/issue/%d/cancel" % doc["id"], json={"reason": "Wrong project"}))      # back to 5000 kg: the alert closes
    with database.SessionLocal() as s:
        assert s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.client_id == w["client_id"], DBStoreReorderAlert.cleared_at.is_(None)).count() == 0
    _issue(t, central, w, 60)                          # low again: told again
    assert _alerts(w["client_id"]) == 2


def test_the_scan_covers_only_the_stores_the_person_works_in(account):
    from fastapi.testclient import TestClient
    import main
    from conftest import make_employee
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    other = ok(t.post("/api/store/masters/stores", json={"code": "OT" + tag[:3].upper(), "name": "Other", "type": "CENTRAL"}))
    _receive(t, central, w, 100)                       # 5000 kg in the central store only
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "6000"}))
    email = "incharge-%s@example.com" % tag
    emp = make_employee(t, email=email, password="Crew1234", permission_role="store_incharge", status="active")
    ok(t.post("/api/store/masters/stores/%d/assignments" % other["id"], json={"employee_id": emp["id"], "role": "STOREKEEPER"}))
    c = TestClient(main.app)
    c.__enter__()
    try:
        assert c.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
        assert ok(c.post("/api/store/levels/scan"))["raised"] == 0                     # the low stock is in a store not theirs
        assert _alerts(w["client_id"]) == 0
        assert ok(t.post("/api/store/levels/scan"))["raised"] == 1                     # the Master's scan covers every store
    finally:
        c.__exit__(None, None, None)
