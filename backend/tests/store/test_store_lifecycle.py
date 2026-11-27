"""The store's whole cycle, through the API: an approved order received in parts, checked, put into stock, issued to the
site; stock running low raises one alert, which an indent and an order move along but never resolve - only accepted
material posted into stock above the reorder level does. One ledger throughout; nothing posted twice."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app import db as database, models
from app.models.store_core import DBStoreBatch, DBStoreStockLedger
from app.models.store_extras import DBStoreReorderAlert
from app.services.stock_ledger import available_map
from store.test_cutover import _company, _hub, _leave_no_stock_behind, ok, walk  # noqa: F401

TODAY = date.today().isoformat()
D = Decimal


def grn(t, central, w, bags, po=0, post=True, **line):
    po_id, po_line = w["pos"][po]
    res = t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id,
                                                "lines": [dict({"po_line_id": po_line, "qty": str(bags), "uom": "bag"}, **line)]})
    if res.status_code != 200:
        return res
    doc = res.json()
    return walk(t, "inward", "grn", doc["id"], "submit", "approve", "post") if post else doc


def issue(t, central, w, bags, **line):
    """Issued and posted; or the first refusal, whether at the draft or at a later step."""
    res = t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN",
                                                    "received_by_name": "Suresh", "lines": [dict({"item_id": w["item"], "qty": str(bags), "uom": "bag", "cost_head": "OVERHEAD"}, **line)]})
    if res.status_code != 200:
        return res
    doc = res.json()
    for step in ("submit", "approve", "post"):
        res = t.post("/api/store/outward/issue/%d/%s" % (doc["id"], step))
        if res.status_code != 200:
            return res
    return res


def available(w, central):
    with database.SessionLocal() as s:
        row = available_map(s, [central["id"]], [w["item"]]).get((central["id"], w["item"]))
        return row or {"on_hand": D(0), "available": D(0), "unusable": D(0), "reserved": D(0)}


def po_row(t, w, n=0):
    return ok(t.get("/api/purchase-orders/%d" % w["pos"][n][0]))


def alert_row(t, w):
    return next((r for r in ok(t.get("/api/store/levels/low-stock"))["items"] if r["item_id"] == w["item"]), None)


def new_order(w, bags):
    """An approved order placed now, as purchase would place it against the indent."""
    with database.SessionLocal() as s:
        po = models.DBPurchaseOrder(client_id=w["client_id"], job_id=w["job"], number="PO-R-" + uuid.uuid4().hex[:5], supplier_name="Shree Traders",
                                    status="Approved", issue_date=TODAY)
        s.add(po)
        s.flush()
        line = models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_code=w["code"], uom="bag", qty=bags, price=350.0)
        s.add(line)
        s.commit()
        w["pos"].append((po.id, line.id))
    return len(w["pos"]) - 1


def cancel_order(w, n):
    with database.SessionLocal() as s:
        s.get(models.DBPurchaseOrder, w["pos"][n][0]).status = "Cancelled"
        s.commit()


def world(account, reorder=None, qc=False):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag, orders=2)
    central = _hub(t, w, tag)
    body = {"category": "CONSUMABLE", "base_uom": "kg", "qc_required": qc}
    if reorder:
        body["reorder_level"] = reorder
    ok(t.put("/api/store/masters/items/%d/settings" % w["item"], json=body))
    return t, w, central


# ---- 1. purchase order and goods receipt ----------------------------------------------------------

def test_an_order_is_received_in_parts_never_past_what_was_ordered_and_says_how_far_it_has_come(account):
    t, w, central = world(account)
    assert po_row(t, w)["receipt_status"] == "Not received"
    grn(t, central, w, 80)
    grn(t, central, w, 70)
    po = po_row(t, w)
    assert po["status"] == "Approved" and po["receipt_status"] == "Partially received"         # still approved: a third receipt can come
    assert po["line_items"][0]["received_qty"] == 150 and po["line_items"][0]["pending_qty"] == 50
    over = grn(t, central, w, 60, post=False)                                                    # 10 bags past the order
    refused = over if hasattr(over, "status_code") else t.post("/api/store/inward/grn/%d/submit" % over["id"])
    assert refused.status_code == 409 and "ordered" in refused.text
    if not hasattr(over, "status_code"):
        assert t.delete("/api/store/inward/grn/%d" % over["id"]).status_code == 200
    grn(t, central, w, 50)
    assert po_row(t, w)["receipt_status"] == "Fully received"
    assert available(w, central)["on_hand"] == D("10000")


def test_a_receipt_is_posted_once(account):
    t, w, central = world(account)
    doc = grn(t, central, w, 40)
    again = t.post("/api/store/inward/grn/%d/post" % doc["id"])
    assert again.status_code == 409
    with database.SessionLocal() as s:
        entries = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id == central["id"], DBStoreStockLedger.item_id == w["item"],
                                                     DBStoreStockLedger.qty_in > 0).count()
    assert entries == 1 and available(w, central)["on_hand"] == D("2000")


# ---- 2. quality check, holds and rejected goods -----------------------------------------------------

def test_accepted_goods_enter_stock_rejected_go_to_rejected_goods_and_never_into_stock(account):
    t, w, central = world(account, qc=True)
    doc = grn(t, central, w, 100, post=False)
    line_id = doc["lines"][0]["id"]
    assert t.post("/api/store/inward/grn/%d/submit" % doc["id"]).status_code == 409                       # QC first
    ok(t.post("/api/store/inward/grn/%d/qc/%d" % (doc["id"], line_id), json={"result": "PASSED", "rejected_qty": "10", "note": "Wet bags"}))
    walk(t, "inward", "grn", doc["id"], "submit", "approve", "post")
    assert available(w, central)["on_hand"] == D("4500")                                                  # 90 bags
    mine = [r for r in ok(t.get("/api/store/rejections"))["items"] if r.get("item_id") == w["item"]]
    assert len(mine) == 1 and D(str(mine[0]["qty"])) == D("500") and mine[0]["status"] == "HELD"


def test_a_held_lot_is_not_issued_moved_or_written_off_until_its_ncr_is_closed(account):
    t, w, central = world(account)
    grn(t, central, w, 100, batch_no="LOT-A")
    with database.SessionLocal() as s:
        bid = s.query(DBStoreBatch).filter(DBStoreBatch.item_id == w["item"], DBStoreBatch.batch_no == "LOT-A").one().id
    ncr = ok(t.post("/api/qc/ncrs", json={"store_batch_id": bid, "description": "Lumps in bags", "severity": "Minor"}))["ncr"]
    assert available(w, central)["available"] == D(0) and available(w, central)["unusable"] == D("5000")
    refused = issue(t, central, w, 10)
    assert refused.status_code == 409 and "held" in refused.text.lower()
    site = ok(t.post("/api/store/masters/stores", json={"code": "SX" + uuid.uuid4().hex[:3].upper(), "name": "Site", "type": "SITE", "project_id": w["job"]}))
    move = t.post("/api/store/control/transfer", json={"store_id": central["id"], "to_store_id": site["id"], "transfer_date": TODAY,
                                                      "lines": [{"item_id": w["item"], "qty": "10", "uom": "bag"}]})
    moved = move if move.status_code != 200 else t.post("/api/store/control/transfer/%d/submit" % move.json()["id"])
    assert moved.status_code == 409
    scrap = t.post("/api/store/control/scrap", json={"store_id": central["id"], "scrap_date": TODAY, "project_id": w["job"], "buyer": "X",
                                                    "lines": [{"item_id": w["item"], "qty": "10", "uom": "bag", "disposal": "WASTAGE", "reason": "Lumps"}]})
    scrapped = scrap if scrap.status_code != 200 else t.post("/api/store/control/scrap/%d/submit" % scrap.json()["id"])
    assert scrapped.status_code == 409
    assert available(w, central)["on_hand"] == D("5000")                                                  # nothing moved
    # Closed by the existing NCR steps, the hold lifts and the lot can be issued.
    nid = ncr["id"]
    n = ok(t.get("/api/qc/ncrs/%d" % nid))["ncr"]
    ok(t.post("/api/qc/ncrs/%d/assign" % nid, json={"responsible": "Stores", "target_date": TODAY, "corrective_action": "Sieve", "root_cause": "Damp", "severity": n["severity"]}))
    ok(t.post("/api/qc/ncrs/%d/work" % nid, json={"corrective_done": "Sieved", "root_cause": "Damp"}))
    ok(t.post("/api/qc/ncrs/%d/request-verification" % nid))
    ok(t.post("/api/qc/ncrs/%d/verify" % nid, json={"result": "verified", "note": "Seen"}))
    ok(t.post("/api/qc/ncrs/%d/close" % nid, json={"closure_note": "Fit to use"}))
    assert available(w, central)["available"] == D("5000")
    assert issue(t, central, w, 10).status_code == 200


# ---- 4, 7. issue to site, FEFO and expiry -----------------------------------------------------------

def test_an_issue_takes_only_what_is_there_once_earliest_expiry_first_and_never_expired_stock(account):
    t, w, central = world(account)
    grn(t, central, w, 20, batch_no="OLD", expiry_date=(date.today() + timedelta(days=20)).isoformat())
    grn(t, central, w, 20, batch_no="NEW", expiry_date=(date.today() + timedelta(days=80)).isoformat())
    too_much = issue(t, central, w, 41)
    assert too_much.status_code == 409 and available(w, central)["on_hand"] == D("2000")                  # never negative
    later = issue(t, central, w, 5, batch_no="NEW")                                                        # FEFO: an earlier lot is there
    assert later.status_code == 409 and "earlier-expiry" in later.text
    assert issue(t, central, w, 5, batch_no="NEW", fefo_reason="Old lot is at the far yard").status_code == 200
    with database.SessionLocal() as s:
        old = s.query(DBStoreBatch).filter(DBStoreBatch.item_id == w["item"], DBStoreBatch.batch_no == "OLD").one()
        old.expiry_date = date.today() - timedelta(days=1)                                                 # it has now run out
        s.commit()
    assert available(w, central)["available"] == D("750")                                                  # 15 bags of NEW only
    expired = issue(t, central, w, 5, batch_no="OLD")
    assert expired.status_code == 409 and "expired" in expired.text.lower()
    done = issue(t, central, w, 5)                                                                          # the expired lot is passed over
    assert done.status_code == 200
    assert t.post("/api/store/outward/issue/%d/post" % done.json()["id"]).status_code == 409               # posted once
    assert available(w, central)["on_hand"] == D("1500")


# ---- 5, 6. low stock, indent, order, receipt and resolution -------------------------------------------

def test_low_stock_goes_from_alert_to_indent_to_order_to_receipt_and_resolves_only_with_stock(account):
    t, w, central = world(account, reorder="3000")
    cancel_order(w, 1)                                                    # nothing else on order for cement
    grn(t, central, w, 200)                                               # the first order, all of it: 10000 kg
    issue(t, central, w, 150)                                             # 2500 kg: at or below 3000
    row = alert_row(t, w)
    assert row and row["status"] == "LOW_STOCK" and row["stage"] == "ALERT ACTIVE"
    assert D(row["available"]) == D("2500") and D(row["reorder_level"]) == D("3000") and D(row["shortage"]) == D("500")
    issue(t, central, w, 1)                                               # lower still: the same alert, its figures updated
    with database.SessionLocal() as s:
        assert s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.store_id == central["id"], DBStoreReorderAlert.item_id == w["item"]).count() == 1
    assert D(alert_row(t, w)["available"]) == D("2450")
    raised = ok(t.post("/api/store/levels/low-stock/raise", json={"action": "INDENT", "lines": [{"store_id": central["id"], "item_id": w["item"], "qty": "1000",
                                                                  "alert_id": row["alert_id"]}], "request_key": uuid.uuid4().hex, "project_id": w["job"]}))
    assert raised["raised"] == 1
    row = alert_row(t, w)
    assert row["status"] == "INDENT_RAISED" and row["stage"] == "INDENT RAISED"                       # raised, not resolved
    n = new_order(w, 40)
    assert alert_row(t, w)["stage"] == "PO CREATED"
    pending = grn(t, central, w, 30, po=n, post=False)
    assert alert_row(t, w)["stage"] == "GOODS RECEIVED"
    walk(t, "inward", "grn", pending["id"], "submit", "approve")
    assert alert_row(t, w) is not None                                    # approved is not posted: still low
    walk(t, "inward", "grn", pending["id"], "post")                       # 2450 + 1500 = 3950 kg, above 3000
    assert alert_row(t, w) is None
    with database.SessionLocal() as s:
        a = s.query(DBStoreReorderAlert).filter(DBStoreReorderAlert.store_id == central["id"], DBStoreReorderAlert.item_id == w["item"]).one()
        assert a.status == "RESOLVED" and a.resolved_qty == D("3950")


def test_quality_accepted_is_a_stage_and_resolves_nothing_until_posted(account):
    t, w, central = world(account, reorder="3000", qc=True)
    cancel_order(w, 1)
    first = grn(t, central, w, 40, post=False)                            # 2000 kg once posted: that posting raises the alert
    ok(t.post("/api/store/inward/grn/%d/qc/%d" % (first["id"], first["lines"][0]["id"]), json={"result": "PASSED"}))
    walk(t, "inward", "grn", first["id"], "submit", "approve", "post")
    assert alert_row(t, w)["stage"] == "PO CREATED"                       # 160 bags of the order still to come
    more = grn(t, central, w, 40, post=False)
    assert alert_row(t, w)["stage"] == "GOODS RECEIVED"
    ok(t.post("/api/store/inward/grn/%d/qc/%d" % (more["id"], more["lines"][0]["id"]), json={"result": "PASSED"}))
    assert alert_row(t, w)["stage"] == "QUALITY ACCEPTED"
    walk(t, "inward", "grn", more["id"], "submit", "approve", "post")     # 4000 kg
    assert alert_row(t, w) is None


def test_material_received_after_the_alert_that_leaves_it_still_low_reads_stock_updated(account):
    t, w, central = world(account, reorder="3000")
    cancel_order(w, 1)
    grn(t, central, w, 40)                                                # 2000 kg: the alert is raised here
    assert alert_row(t, w)["stage"] == "PO CREATED"                       # 160 bags of that order still to come
    cancel_order(w, 0)
    assert alert_row(t, w)["stage"] == "ALERT ACTIVE"                     # nothing on order now
    m = new_order(w, 10)
    assert alert_row(t, w)["stage"] == "PO CREATED"
    grn(t, central, w, 10, po=m)                                          # all of it in: 2500 kg, still at or below 3000
    row = alert_row(t, w)
    assert row["status"] == "LOW_STOCK" and row["stage"] == "STOCK UPDATED"
