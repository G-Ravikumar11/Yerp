"""Low stock that can be acted on: the alert keeps its figures and its history and resolves itself when the stock recovers, and many
low materials can be raised on an indent or an enquiry at once, each checked again against the stock as it is now."""
import json
import uuid
from datetime import date
from decimal import Decimal

from app import db as database, models
from app.models.store_core import DBStoreBatch
from app.models.store_extras import DBStoreReorderAlert
from app.models.store_outward import DBStoreIndent
from app.services.stock_ledger import available_map
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401
from store.test_f10_levels import _alerts, _issue, _receive

TODAY = date.today().isoformat()
LOW = "/api/store/levels/low-stock"


def setup(account, reorder="3000", max_qty=None):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    body = {"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": reorder}
    if max_qty:
        body["max_qty"] = max_qty
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json=body))
    return t, w, central, tag


def alert(w):
    with database.SessionLocal() as s:
        return s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.client_id == w["client_id"], DBStoreReorderAlert.item_id == w["item"]).one()


def low(t, **params):
    return ok(t.get(LOW, params=params))


def raise_(t, action, lines, key="", **extra):
    return t.post(LOW + "/raise", json={"action": action, "lines": lines, "request_key": key, **extra})


def line(central, w, qty, alert_id=None):
    return {"store_id": central["id"], "item_id": w["item"], "qty": str(qty), "alert_id": alert_id}


def drop_po(w):
    """The company's open order for 200 bags would cover any enquiry: cancelled, so the enquiry has something to ask for."""
    with database.SessionLocal() as s:
        for po_id, _l in w["pos"]:
            s.get(models.DBPurchaseOrder, po_id).status = "Cancelled"
        s.commit()


# --- the alert's life ----------------------------------------------------------------------------------------------------------

def test_an_alert_is_raised_with_its_figures_updated_not_duplicated_and_resolves_when_stock_recovers(account):
    t, w, central, _tag = setup(account, max_qty="8000")
    _receive(t, central, w, 100)                              # 5000 kg
    _issue(t, central, w, 50)                                 # 2500 kg: low
    a = alert(w)
    assert (a.status, a.available, a.reorder_level, a.target_level, a.suggested_qty) == ("OPEN", Decimal("2500"), Decimal("3000"), Decimal("8000"), Decimal("5500"))
    assert a.suggest_basis.startswith("Up to the maximum") and a.last_checked_at is not None and _alerts(w["client_id"]) == 1
    first_check = a.last_checked_at
    _issue(t, central, w, 10)                                 # 2000 kg: still low - brought up to date, not raised again
    assert ok(t.post("/api/store/levels/scan")) == {"raised": 0, "updated": 1, "resolved": 0}      # the morning check: no duplicate
    a = alert(w)
    assert a.available == Decimal("2000") and a.suggested_qty == Decimal("6000") and a.last_checked_at >= first_check
    assert _alerts(w["client_id"]) == 1
    with database.SessionLocal() as s:
        assert s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.item_id == w["item"]).count() == 1

    _receive(t, central, w, 100)                              # 7000 kg: a goods receipt brings it back above the level
    a = alert(w)
    assert (a.status, a.resolved_qty) == ("RESOLVED", Decimal("7000")) and a.cleared_at is not None
    assert low(t)["items"] == []                              # gone from the active list ...
    [past] = low(t, view="history")["items"]                  # ... and kept in the history
    assert past["status"] == "RESOLVED" and past["resolved_qty"] == "7000.000"

    _issue(t, central, w, 100)                                # 2000 kg: low again - raised afresh, the first episode kept
    a = alert(w)
    assert (a.status, a.times_raised, a.available) == ("OPEN", 2, Decimal("2000")) and _alerts(w["client_id"]) == 2
    [episode] = json.loads(a.history)
    assert episode["resolved_qty"] == "7000.000" and episode["alerted_at"]
    assert len(low(t, view="history")["items"]) == 1


def test_the_morning_check_resolves_what_recovered_without_a_posting(account):
    """Lowering the reorder level is not a posting: before, the alert stayed open for ever."""
    t, w, central, _tag = setup(account)
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)                                 # 2500 kg, level 3000: low
    assert alert(w).status == "OPEN"
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "1000"}))
    assert ok(t.post("/api/store/levels/scan"))["resolved"] == 1
    assert alert(w).status == "RESOLVED" and alert(w).resolved_qty == Decimal("2500")


def test_held_stock_is_not_available(account):
    t, w, central, _tag = setup(account)
    po_id, po_line = w["pos"][0]
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id,
                                                  "lines": [{"po_line_id": po_line, "qty": "100", "uom": "bag", "batch_no": "B-1"}]}))
    walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")     # 5000 kg in batch B-1: above the level
    assert alert_or_none(w) is None
    with database.SessionLocal() as s:                       # the batch goes on hold
        batch = s.query(DBStoreBatch).filter(DBStoreBatch.item_id == w["item"], DBStoreBatch.batch_no == "B-1").one()
        batch.on_hold = True
        s.commit()
        f = available_map(s, [central["id"]], [w["item"]])[(central["id"], w["item"])]
        assert (f["on_hand"], f["unusable"], f["available"]) == (Decimal("5000"), Decimal("5000"), Decimal("0"))
    [row] = low(t)["items"]                                    # 5000 on hand but none of it can be issued: low
    assert (row["on_hand"], row["available"], row["unusable"]) == ("5000.000", "0.000", "5000.000")
    assert ok(t.post("/api/store/levels/scan"))["raised"] == 1 and alert(w).available == Decimal("0")


def alert_or_none(w):
    with database.SessionLocal() as s:
        return s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.item_id == w["item"]).first()


# --- raising for low items -----------------------------------------------------------------------------------------------------

def test_one_low_item_raises_an_indent_for_approval_at_the_suggested_quantity_and_the_alert_stays_open(account):
    t, w, central, _tag = setup(account, max_qty="8000")
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)                                  # 2500 kg
    [row] = low(t)["items"]
    assert (row["status"], row["suggested_qty"], row["base_uom"]) == ("LOW_STOCK", "5500.000", "kg")
    res = raise_(t, "INDENT", [line(central, w, row["to_order"], row["alert_id"])], key="k1", project_id=w["job"])
    body = ok(res)
    assert body["ok"] and body["raised"] == 1 and body["created"][0]["type"] == "INDENT"
    with database.SessionLocal() as s:
        indent = s.get(DBStoreIndent, body["created"][0]["id"])
        assert indent.status == "SUBMITTED" and indent.project_id == w["job"]          # waits for the project manager, as any indent
    [row] = low(t)["items"]
    assert (row["status"], row["action_ref"]) == ("INDENT_RAISED", body["created"][0]["number"])
    assert alert(w).status == "OPEN"                           # raising never resolves it: the stock is still low
    # The same press again raises nothing new.
    again = ok(raise_(t, "INDENT", [line(central, w, row["to_order"], row["alert_id"])], key="k1", project_id=w["job"]))
    assert again["created"] == [] and again["results"][0]["repeat"] is True
    # A new press while that indent is open is refused for this item.
    third = ok(raise_(t, "INDENT", [line(central, w, 100, row["alert_id"])], key="k2", project_id=w["job"]))
    assert third["created"] == [] and "Already raised on" in third["results"][0]["message"] and third["ok"] is False
    with database.SessionLocal() as s:
        assert s.query(DBStoreIndent).filter(DBStoreIndent.client_id == w["client_id"]).count() == 1


def test_many_items_go_on_one_enquiry_and_each_bad_line_is_answered_on_its_own(account):
    t, w, central, tag = setup(account, max_qty="8000")
    with database.SessionLocal() as s:                         # a second material in the same store
        sand = models.DBItem(client_id=w["client_id"], kind="RM", item_code="CO-SND-" + tag, item_name="River sand", units_of_measure="kg")
        s.add(sand)
        s.commit()
        sand_id = sand.id
    ok(t.put("/api/store/masters/items/%d/settings" % sand_id, json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "500"}))
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)                                  # cement 2500 kg: low
    drop_po(w)
    ok(t.post("/api/store/levels/scan"))
    assert [r["item_id"] for r in low(t)["items"]] == [w["item"]]
    res = ok(raise_(t, "ENQUIRY", [line(central, w, "4000"), {"store_id": central["id"], "item_id": w["item"], "qty": "1"},
                                   {"store_id": central["id"], "item_id": sand_id, "qty": "100"}], key="e1"))
    assert [c["type"] for c in res["created"]] == ["ENQUIRY"] and res["raised"] == 1 and res["failed"] == 2 and res["ok"] is False
    msgs = [r["message"] for r in res["results"] if not r["ok"]]
    assert any("chosen twice" in m for m in msgs) and any("holds no record of River sand" in m for m in msgs)
    assert "1 could not" not in res["message"] and "2 could not be raised" in res["message"]
    with database.SessionLocal() as s:
        rfq = s.get(models.DBRfq, res["created"][0]["id"])
        [rl] = s.query(models.DBRfqLine).filter(models.DBRfqLine.rfq_id == rfq.id).all()
        assert (rl.item_code, rl.qty, rl.uom.lower().rstrip("s")) == (w["code"], 4000, "kg")      # units are kept in the enquiry's canonical form
    assert alert(w).action == "ENQUIRY" and alert(w).status == "OPEN"
    assert low(t)["items"][0]["status"] == "ENQUIRY_RAISED"


def test_quantities_are_checked_against_the_stores_maximum_and_what_is_already_coming(account):
    t, w, central, _tag = setup(account, max_qty="8000")
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)                                  # 2500 kg available, 8000 max: 5500 needed
    # The order's other 100 bags (5000 kg) are still to come, so only 500 kg more fits under the maximum.
    [row] = low(t)["items"]
    assert (row["suggested_qty"], row["on_order"], row["to_order"]) == ("5500.000", "5000.000", "500.000")
    too_much = ok(raise_(t, "ENQUIRY", [line(central, w, "600")], key="q2"))
    assert too_much["created"] == [] and "past its maximum of 8000.000: at most 500.000" in too_much["results"][0]["message"]
    bad = ok(raise_(t, "ENQUIRY", [line(central, w, "-5")], key="q3"))
    assert "more than zero" in bad["results"][0]["message"]
    fine = ok(raise_(t, "ENQUIRY", [line(central, w, "500")], key="q4"))
    assert fine["ok"] and fine["created"][0]["type"] == "ENQUIRY"


def test_an_enquiry_is_not_raised_for_what_open_orders_already_cover(account):
    t, w, central, _tag = setup(account)                       # no maximum: up to twice the level, 6000
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)                                  # 2500 kg: 3500 needed, and the order still has 5000 kg to deliver
    [row] = low(t)["items"]
    assert row["to_order"] == "0.000"
    res = ok(raise_(t, "ENQUIRY", [line(central, w, "100")], key="c1"))
    assert res["created"] == [] and "Already being bought" in res["results"][0]["message"] and alert(w).action == ""


def test_a_resolved_alert_raises_nothing_and_says_why(account):
    t, w, central, _tag = setup(account)
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)                                  # low
    stale = low(t)["items"][0]
    _receive(t, central, w, 100)                               # recovered before the button was pressed
    res = ok(raise_(t, "INDENT", [line(central, w, stale["to_order"], stale["alert_id"])], key="r1", project_id=w["job"]))
    assert res["created"] == [] and res["results"][0]["status"] == "RESOLVED" and "No longer low" in res["results"][0]["message"]
    with database.SessionLocal() as s:
        assert s.query(DBStoreIndent).filter(DBStoreIndent.client_id == w["client_id"]).count() == 0


def test_an_indent_from_a_store_with_no_project_needs_one_and_the_rights_are_kept(account, portal):
    from conftest import make_employee
    t, w, central, tag = setup(account)
    _receive(t, central, w, 100)
    _issue(t, central, w, 50)
    res = ok(raise_(t, "INDENT", [line(central, w, "100")], key="p1"))                 # the central store is no project's
    assert res["created"] == [] and "belongs to no project" in res["results"][0]["message"]
    assert raise_(t, "SOMETHING", [line(central, w, "1")]).status_code == 400
    email = "ls-%s@example.com" % tag
    emp = make_employee(t, email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        s.get(models.DBEmployee, emp["id"]).extra_permissions = "store.enquiry.view"
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    assert raise_(portal, "INDENT", [line(central, w, "100")], project_id=w["job"]).status_code == 403
    assert raise_(portal, "ENQUIRY", [line(central, w, "100")]).status_code == 403
