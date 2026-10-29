"""The store controls an audit asked for: making and approving kept apart, real batch balances, the books locked up to a day
and a limit on back-dating, deliveries received while a count is on, purchase returns at the rate they came in at with a
debit note, purchase-order lines tied to a stock item from the receipt screen, and landed cost in the stock value."""
from datetime import date, timedelta
from decimal import Decimal

from app import db as database, models
from app.models.store_core import DBStoreStockLedger
from app.services.stock_ledger import freeze_store
from store.test_p2_inward import (  # noqa: F401  (the autouse cleanup comes with it)
    API, TODAY, _leave_no_stock_behind, balance, grn_body, make_grn, move, posted_grn, staff, world,
)

D = Decimal
CONTROL = "/api/store/control"
OUTWARD = "/api/store/outward"


def _lock(tenant, upto="", days=30, separate=True):
    res = tenant.put("/api/store/masters/controls", json={"books_locked_upto": upto, "max_backdate_days": days, "separate_duties": separate})
    assert res.status_code == 200, res.text
    return res.json()


# --- 1. making and approving are kept apart ---------------------------------------------------------------------------

def test_staff_cannot_approve_what_they_made_or_submitted(account, portal):
    tenant = account["client"]
    w = world(account)
    staff(account, portal, ["store.inward.view", "store.inward.create", "store.inward.approve", "store.inward.post"], [w.central])
    g = portal.post(API + "/grn", json=grn_body(w)).json()
    assert portal.post("%s/grn/%d/submit" % (API, g["id"])).status_code == 200
    res = portal.post("%s/grn/%d/approve" % (API, g["id"]))
    assert res.status_code == 403 and "someone else" in res.json()["detail"]
    # Made by the account holder but submitted by this person: still not theirs to approve.
    g2 = make_grn(tenant, w)
    assert portal.post("%s/grn/%d/submit" % (API, g2["id"])).status_code == 200
    assert portal.post("%s/grn/%d/approve" % (API, g2["id"])).status_code == 403
    # Another member of staff approves, and the first may then post.
    staff(account, portal, ["store.inward.view", "store.inward.approve"], [w.central])
    assert portal.post("%s/grn/%d/approve" % (API, g["id"])).status_code == 200
    # A company can turn the rule off.
    _lock(tenant, separate=False)
    staff(account, portal, ["store.inward.view", "store.inward.create", "store.inward.approve"], [w.central])
    g3 = portal.post(API + "/grn", json=grn_body(w)).json()
    for step in ("submit", "approve"):
        assert portal.post("%s/grn/%d/%s" % (API, g3["id"], step)).status_code == 200


def test_a_count_is_not_approved_by_whoever_counted_it(account, portal):
    tenant = account["client"]
    w = world(account)
    posted_grn(tenant, w, bags="10")
    staff(account, portal, ["store.control.view", "store.control.create", "store.control.approve", "store.control.approve_high_value"], [w.central])
    c = portal.post(CONTROL + "/count", json={"store_id": w.central, "count_date": TODAY, "count_type": "FULL"}).json()
    assert portal.post("%s/count/%d/start" % (CONTROL, c["id"])).status_code == 200
    sheet = [{"item_id": w.item["cement"], "counted_qty": "480", "uom": "kg", "reason": "bag torn"}]
    assert portal.put("%s/count/%d/sheet" % (CONTROL, c["id"]), json={"rows": sheet}).status_code == 200
    assert portal.post("%s/count/%d/submit" % (CONTROL, c["id"])).status_code == 200
    assert portal.post("%s/count/%d/approve" % (CONTROL, c["id"])).status_code == 403
    assert tenant.post("%s/count/%d/approve" % (CONTROL, c["id"])).status_code == 200


# --- 2. batches are real balances --------------------------------------------------------------------------------------

def _batch_grn(tenant, w, batch, bags, rate="350", made=None):
    line = {"po_line_id": w.po_line["cement"], "qty": bags, "uom": "bag", "rate": rate, "batch_no": batch,
            "manufacturing_date": (made or date.today()).isoformat()}
    g = make_grn(tenant, w, lines=[line])
    return move(tenant, "grn", g["id"], "submit", "approve", "post")


def _lots(tenant, store, item):
    res = tenant.get(OUTWARD + "/batches", params={"store_id": store, "item_id": item})
    assert res.status_code == 200, res.text
    return [(b["batch_no"], b["qty"]) for b in res.json()["batches"]]


def test_batches_travel_with_a_transfer_and_come_back_when_it_is_cancelled(account):
    tenant = account["client"]
    w = world(account)
    _batch_grn(tenant, w, "A1", "10", made=date.today() - timedelta(days=30))
    _batch_grn(tenant, w, "B2", "10")
    t = tenant.post(CONTROL + "/transfer", json={"store_id": w.central, "to_store_id": w.site, "transfer_date": TODAY,
                                                 "lines": [{"item_id": w.item["cement"], "qty": "600", "uom": "kg"}]}).json()
    for step in ("submit", "approve", "post"):
        assert tenant.post("%s/transfer/%d/%s" % (CONTROL, t["id"], step)).status_code == 200
    assert _lots(tenant, w.central, w.item["cement"]) == [("B2", "400.000")]          # the earlier expiry went first
    assert tenant.post("%s/transfer/%d/receive" % (CONTROL, t["id"])).status_code == 200
    assert _lots(tenant, w.site, w.item["cement"]) == [("A1", "500.000"), ("B2", "100.000")]
    assert tenant.post("%s/transfer/%d/cancel" % (CONTROL, t["id"]), json={"reason": "sent by mistake"}).status_code == 200
    assert _lots(tenant, w.central, w.item["cement"]) == [("A1", "500.000"), ("B2", "500.000")]
    assert _lots(tenant, w.site, w.item["cement"]) == []


# --- 3. the books are locked up to a day, and back-dating has a limit --------------------------------------------------

def test_nothing_is_dated_into_closed_books_and_a_reversal_keeps_its_day(account):
    tenant = account["client"]
    w = world(account)
    ten_ago = (date.today() - timedelta(days=10)).isoformat()
    g = make_grn(tenant, w, grn_date=ten_ago)
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    # Cancelled, the reversal is dated the receipt's own day, so a report for that day sees neither.
    g2 = move(tenant, "grn", make_grn(tenant, w, grn_date=ten_ago)["id"], "submit", "approve", "post")
    move(tenant, "grn", g2["id"], "cancel")
    with database.SessionLocal() as s:
        days = {r.txn_date.isoformat() for r in s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "GRN", DBStoreStockLedger.ref_doc_id == g2["id"]).all()}
    assert days == {ten_ago}
    # Close the books up to five days ago: the ten-day-old receipt can no longer be cancelled, nor a new one dated then.
    _lock(tenant, upto=(date.today() - timedelta(days=5)).isoformat())
    res = tenant.post("%s/grn/%d/cancel" % (API, g["id"]), json={"reason": "wrong delivery"})
    assert res.status_code == 400 and "closed up to" in res.json()["detail"]
    res = tenant.post(API + "/grn", json=grn_body(w, grn_date=ten_ago))
    assert res.status_code == 400 and "closed up to" in res.json()["detail"]
    assert tenant.put("/api/store/masters/controls", json={"books_locked_upto": TODAY}).status_code == 400   # not today or later


def test_documents_cannot_be_dated_further_back_than_allowed(account):
    tenant = account["client"]
    w = world(account)
    old = (date.today() - timedelta(days=45)).isoformat()
    res = tenant.post(API + "/grn", json=grn_body(w, grn_date=old))
    assert res.status_code == 400 and "30 days back" in res.json()["detail"]
    # Opening stock is dated to the day the store was taken on, however long ago.
    op = tenant.post(API + "/opening", json={"store_id": w.central, "as_on_date": old, "lines": [{"item_id": w.item["sand"], "qty": "5", "uom": "cum", "rate": "1800"}]})
    assert op.status_code == 200, op.text
    move(tenant, "opening", op.json()["id"], "submit", "approve", "post")
    _lock(tenant, days=60)
    assert tenant.post(API + "/grn", json=grn_body(w, grn_date=old)).status_code == 200


# --- 4. a count does not strand deliveries ------------------------------------------------------------------------------

def test_a_delivery_received_during_a_count_is_kept_apart_from_it(account):
    tenant = account["client"]
    w = world(account)
    posted_grn(tenant, w, bags="10")                                           # 500 kg
    c = tenant.post(CONTROL + "/count", json={"store_id": w.central, "count_date": TODAY, "count_type": "FULL"}).json()
    assert tenant.post("%s/count/%d/start" % (CONTROL, c["id"])).status_code == 200
    posted_grn(tenant, w, bags="4")                                            # 200 kg arrive while the count is on
    got = tenant.get("%s/count/%d" % (CONTROL, c["id"])).json()
    assert got["lines"][0]["arrived_since"] == "200.000"
    sheet = [{"item_id": w.item["cement"], "counted_qty": "490", "uom": "kg", "reason": "spilt"}]
    assert tenant.put("%s/count/%d/sheet" % (CONTROL, c["id"]), json={"rows": sheet}).status_code == 200
    for step in ("submit", "approve", "post"):
        assert tenant.post("%s/count/%d/%s" % (CONTROL, c["id"], step)).status_code == 200, step
    assert balance(w, w.central, "cement")[0] == D("690.000")                 # 500 counted as 490, plus the 200 that came in


def test_a_count_warns_of_transfers_still_on_their_way(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w, store=w.site)
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    t = tenant.post(CONTROL + "/transfer", json={"store_id": w.site, "to_store_id": w.central, "transfer_date": TODAY,
                                                 "lines": [{"item_id": w.item["cement"], "qty": "100", "uom": "kg"}]}).json()
    for step in ("submit", "approve", "post"):
        assert tenant.post("%s/transfer/%d/%s" % (CONTROL, t["id"], step)).status_code == 200
    c = tenant.post(CONTROL + "/count", json={"store_id": w.central, "count_date": TODAY, "count_type": "PARTIAL", "item_ids": [w.item["cement"]]}).json()
    assert [x["number"] for x in tenant.get("%s/count/%d" % (CONTROL, c["id"])).json()["in_transit"]] == [t["number"]]
    assert tenant.post("%s/count/%d/start" % (CONTROL, c["id"])).status_code == 200
    assert tenant.post("%s/transfer/%d/receive" % (CONTROL, t["id"])).status_code == 200    # received although the count is on


# --- 5. a purchase return goes back at what it came in at, with a debit note ------------------------------------------------

def test_a_return_is_valued_at_the_receipt_rate_and_carries_a_debit_note(account):
    tenant = account["client"]
    w = world(account)
    with database.SessionLocal() as s:
        po = s.get(models.DBPurchaseOrder, w.po)
        po.tax_amount = 1.0
        s.get(models.DBPurchaseOrderLineItem, w.po_line["cement"]).tax_rate = "28%"
        s.commit()
    posted_grn(tenant, w, bags="10")                                          # 500 kg at 7.00
    dear = move(tenant, "grn", make_grn(tenant, w, lines=[{"po_line_id": w.po_line["cement"], "qty": "10", "uom": "bag", "rate": "450"}])["id"],
                "submit", "approve", "post")                                  # 500 kg at 9.00
    assert balance(w, w.central, "cement") == (D("1000.000"), D("8000.00"), D("8.0000"))
    ret = tenant.post(API + "/returns", json={"grn_id": dear["id"], "return_date": TODAY, "reason": "wet bags",
                                              "lines": [{"grn_line_id": dear["lines"][0]["id"], "qty": "4", "uom": "bag"}]}).json()
    assert (ret["debit_value"], ret["tax_value"], ret["debit_total"]) == ("1800.00", "504.00", "2304.00")
    move(tenant, "returns", ret["id"], "submit", "approve", "post")
    # 200 kg left at 9.00 (1800), not at the 8.00 average: what stays is worth what it cost.
    assert balance(w, w.central, "cement") == (D("800.000"), D("6200.00"), D("7.7500"))
    pdf = tenant.get("%s/returns/%d/print" % (API, ret["id"]))
    assert pdf.status_code in (200, 503)


# --- 6. a purchase-order line is tied to its stock item from the receipt screen ----------------------------------------------

def test_an_order_line_with_no_item_code_can_be_given_its_item_and_received(account):
    tenant = account["client"]
    w = world(account)
    with database.SessionLocal() as s:
        pl = models.DBPurchaseOrderLineItem(order_id=w.po, description="Sand for plastering", item_code="", uom="cum", qty=20, price=1800.0)
        s.add(pl)
        s.commit()
        pl_id = pl.id
    po = next(p for p in tenant.get(API + "/po-options").json()["items"] if p["id"] == w.po)
    row = next(l for l in po["lines"] if l["po_line_id"] == pl_id)
    assert row["needs_item"] is True and row["item_id"] is None
    res = tenant.post(API + "/grn", json=grn_body(w, lines=[{"po_line_id": pl_id, "qty": "5", "uom": "cum"}]))
    assert res.status_code == 400 and "Choose the item" in res.json()["detail"]
    mapped = tenant.post("%s/po-line/%d/item" % (API, pl_id), json={"item_id": w.item["sand"]})
    assert mapped.status_code == 200 and mapped.json()["item_id"] == w.item["sand"]
    g = make_grn(tenant, w, lines=[{"po_line_id": pl_id, "qty": "5", "uom": "cum"}])
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    assert balance(w, w.central, "sand")[0] == D("5.000")
    # Received as sand, the line cannot now be turned into cement.
    assert tenant.post("%s/po-line/%d/item" % (API, pl_id), json={"item_id": w.item["cement"]}).status_code == 409


# --- 7. landed cost goes into the stock value ----------------------------------------------------------------------------------

def test_freight_and_loading_are_spread_into_the_stock_value(account):
    tenant = account["client"]
    w = world(account)
    body = grn_body(w, lines=[{"po_line_id": w.po_line["cement"], "qty": "100", "uom": "bag"},           # 5000 kg x 7 = 35000
                              {"po_line_id": w.po_line["steel"], "qty": "500", "uom": "kg"}],            # 500 kg x 62 = 31000
                    charges=[{"kind": "FREIGHT", "amount": "6600", "basis": "VALUE"}, {"kind": "LOADING", "amount": "550", "basis": "QTY"}])
    res = tenant.post(API + "/grn", json=body)
    assert res.status_code == 200, res.text
    g = res.json()
    # steel waits for its quality check, so until then only the cement is in stock to carry the charges
    assert g["lines"][0]["charges_share"] == "7150.00"
    g = tenant.post("%s/grn/%d/qc/%d" % (API, g["id"], g["lines"][1]["id"]), json={"result": "PASSED"}).json()
    assert g["charges_total"] == "7150.00" and g["landed_value"] == "73150.00"
    cement, steel = g["lines"]
    assert (cement["charges_share"], steel["charges_share"]) == ("4000.00", "3150.00")    # 3500 + 500, 3100 + 50
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    assert balance(w, w.central, "cement") == (D("5000.000"), D("39000.00"), D("7.8000"))
    assert balance(w, w.central, "steel") == (D("500.000"), D("34150.00"), D("68.3000"))
