"""Cycle counting: items ranked A, B, C; what is due for counting at each class's interval; and a blind second count for a line whose first count was
far from the books - the second count is the one the books are adjusted to."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, MovementType
from app.services.stock_ledger import post_movement
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()
D = Decimal


def _receive(t, central, w, bags):
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "lines": [{"po_line_id": po_line, "qty": str(bags), "uom": "bag"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")


def _start(t, central, **body):
    c = ok(t.post("/api/store/control/count", json={"store_id": central["id"], "count_date": TODAY, **body}))
    ok(t.post("/api/store/control/count/%d/start" % c["id"]))
    return c


def _sheet(t, c, w, kg, reason=""):
    return t.put("/api/store/control/count/%d/sheet" % c["id"], json={"rows": [{"item_id": w["item"], "counted_qty": str(kg), "uom": "kg", "reason": reason}]})


def test_a_line_far_from_the_books_must_be_counted_again_and_the_second_count_stands(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)                                       # 5000 kg at 7.00
    c = _start(t, central)
    ok(_sheet(t, c, w, 3000, "Looks short"))                           # 2000 kg short: 40 percent, worth 14,000
    res = t.post("/api/store/control/count/%d/submit" % c["id"])
    assert res.status_code == 409 and "counted again" in res.json()["detail"]

    # The second count is blind: it names the item and nothing else.
    [again] = ok(t.get("/api/store/cycle/recount/%d" % c["id"]))["items"]
    assert again["item_id"] == w["item"] and set(again) == {"item_id", "item_code", "item_name", "base_uom"}
    assert t.post("/api/store/cycle/recount/%d" % c["id"], json={"rows": [{"item_id": w["item"], "qty": "-1", "uom": "kg"}]}).status_code == 400
    assert ok(t.post("/api/store/cycle/recount/%d" % c["id"], json={"rows": [{"item_id": w["item"], "qty": "4900", "uom": "kg"}]}))["still_to_recount"] == 0
    assert ok(t.get("/api/store/cycle/recount/%d" % c["id"]))["items"] == []

    # The line now carries the recount; it still needs the reason, and the adjustment is to 4900, not 3000.
    ok(t.put("/api/store/control/count/%d/sheet" % c["id"], json={"rows": [{"item_id": w["item"], "counted_qty": "4900", "uom": "kg", "reason": "Spillage"}]}))
    assert t.post("/api/store/cycle/recount/%d" % c["id"], json={"rows": [{"item_id": w["item"], "qty": "4900", "uom": "kg"}]}).status_code == 409     # 100 short is close to the books
    walk(t, "control", "count", c["id"], "submit", "approve", "post")
    [bal] = ok(t.get("/api/store/enquiry/balances", params={"store_id": central["id"]}))["items"]
    assert bal["qty"] == "4900.000"


def test_entering_the_first_count_again_asks_for_a_new_recount(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)
    c = _start(t, central)
    ok(_sheet(t, c, w, 3000, "Short"))
    ok(t.post("/api/store/cycle/recount/%d" % c["id"], json={"rows": [{"item_id": w["item"], "qty": "3050", "uom": "kg"}]}))
    ok(_sheet(t, c, w, 2000, "Counted wrongly"))                       # the first count is changed: the old recount no longer stands
    assert t.post("/api/store/control/count/%d/submit" % c["id"]).status_code == 409
    assert len(ok(t.get("/api/store/cycle/recount/%d" % c["id"]))["items"]) == 1


def test_a_small_difference_needs_no_recount(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    _receive(t, central, w, 100)
    c = _start(t, central)
    ok(_sheet(t, c, w, 4950, "Spillage"))
    assert ok(t.get("/api/store/cycle/recount/%d" % c["id"]))["items"] == []
    walk(t, "control", "count", c["id"], "submit")


def test_rules_can_be_changed_and_are_checked(account):
    t = account["client"]
    assert ok(t.get("/api/store/cycle/settings"))["days_a"] == 30
    assert t.put("/api/store/cycle/settings", json={"days_a": "100", "days_b": "50"}).status_code == 400          # A is not counted less often than B
    assert t.put("/api/store/cycle/settings", json={"days_a": "0"}).status_code == 400
    assert t.put("/api/store/cycle/settings", json={"recount_pct": "x"}).status_code == 400
    saved = ok(t.put("/api/store/cycle/settings", json={"days_a": "14", "recount_value": "0", "recount_pct": "0"}))
    assert saved["days_a"] == 14 and saved["recount_value"] == "0.00"


def test_abc_classes_and_what_is_due(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    with database.SessionLocal() as s:
        for key, value in (("X", 8000), ("Y", 1500), ("Z", 500)):
            it = models.DBItem(client_id=w["client_id"], kind="RM", item_code="AB-%s-%s" % (key, tag), item_name="Item " + key, units_of_measure="nos")
            s.add(it)
            s.flush()
            s.add(DBStoreItemSettings(item_id=it.id, category="CONSUMABLE", base_uom="nos"))
            post_movement(s, movement_type=MovementType.OPENING_IN, store_id=central["id"], item_id=it.id, qty=D(value), rate=D(1), txn_date=date.today() - timedelta(days=5), project_id=None,
                          ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
    classes = {r["item_name"]: r["class"] for r in ok(t.get("/api/store/cycle/abc"))["items"]}
    assert classes == {"Item X": "A", "Item Y": "B", "Item Z": "C"}

    due = ok(t.get("/api/store/cycle/due"))["items"]
    assert {r["item_name"] for r in due} == {"Item X", "Item Y", "Item Z"} and all(r["last_counted"] == "" for r in due)     # never counted
    c = ok(t.post("/api/store/control/count", json={"store_id": central["id"], "count_date": TODAY, "count_type": "PARTIAL", "item_ids": [r["item_id"] for r in due if r["class"] == "A"]}))
    ok(t.post("/api/store/control/count/%d/start" % c["id"]))
    [a] = [r for r in due if r["class"] == "A"]
    ok(t.put("/api/store/control/count/%d/sheet" % c["id"], json={"rows": [{"item_id": a["item_id"], "counted_qty": "8000", "uom": "nos"}]}))
    walk(t, "control", "count", c["id"], "submit", "approve", "post")
    due = ok(t.get("/api/store/cycle/due"))["items"]
    assert {r["item_name"] for r in due} == {"Item Y", "Item Z"}                                  # X was counted today; its class is counted monthly
    everything = ok(t.get("/api/store/cycle/due", params={"due_only": False}))["items"]
    x = next(r for r in everything if r["item_name"] == "Item X")
    assert x["due"] is False and x["last_counted"] == TODAY and x["every_days"] == 30
