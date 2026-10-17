"""P2 inward over HTTP: gate entries, GRNs against a purchase order (pending lines, units, tolerance, landed cost, GST,
steel weights, batches), quality checks and partial posting, rejection memos, purchase returns and debit notes, direct
receipts, client-supplied material, the receipt summary for P5, pending-to-receive, printables, rights and store access."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import models
from app.models.store_core import DBStoreDocStatusLog, DBStoreItemSettings, DBStoreStockLedger
from app.models.store_inward import (
    DBStoreClientSupplyRate, DBStoreGateEntry, DBStoreGrn, DBStoreGrnLine, DBStoreGrnQc, DBStoreInwardSettings,
    DBStorePurchaseReturn, DBStorePurchaseReturnLine, DBStoreRejectionMemo,
)
from app.services.stock_ledger import get_balance, post_movement
from app.services.store_inward import get_po_receipt_summary
from store.fixtures import db, store_world  # noqa: F401  (fixtures)
from store.test_masters import ok, sign_in  # noqa: F401  (fixtures)

D = Decimal
TODAY = date.today()
I = "/api/store/inward"


@pytest.fixture
def world(db, store_world):
    """store_world, and clearing away what P2's tests make before store_world drops its stores."""
    yield store_world
    db.rollback()
    cid = store_world.client_id
    grns = [g.id for g in db.query(DBStoreGrn).filter(DBStoreGrn.client_id == cid)]
    rets = [r.id for r in db.query(DBStorePurchaseReturn).filter(DBStorePurchaseReturn.client_id == cid)]
    if rets:
        db.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id.in_(rets)).delete(synchronize_session=False)
    db.query(DBStorePurchaseReturn).filter(DBStorePurchaseReturn.client_id == cid).delete(synchronize_session=False)
    if grns:
        lines = [l.id for l in db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id.in_(grns))]
        if lines:
            db.query(DBStoreGrnQc).filter(DBStoreGrnQc.grn_line_id.in_(lines)).delete(synchronize_session=False)
        db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id.in_(grns)).delete(synchronize_session=False)
        db.query(DBStoreRejectionMemo).filter(DBStoreRejectionMemo.grn_id.in_(grns)).delete(synchronize_session=False)
    db.query(DBStoreGrn).filter(DBStoreGrn.client_id == cid).delete(synchronize_session=False)
    for model in (DBStoreGateEntry, DBStoreClientSupplyRate, DBStoreInwardSettings, DBStoreDocStatusLog):
        db.query(model).filter(model.client_id == cid).delete(synchronize_session=False)
    db.commit()


def po_line(w, key):
    return w.po_line_ids[{"cement": 0, "tmt12": 1, "tmt16": 2}[key]]


def grn(client, w, lines, store=None, code=200, **head):
    body = {"store_id": store or w.site_id, "kind": "PO", "po_id": w.po_id, "grn_date": str(TODAY), "lines": lines}
    body.update(head)
    return ok(client.post(I + "/grn", json=body), code)


def step(client, g, *actions, code=200, reason=""):
    out = None
    for a in actions:
        out = ok(client.post(I + "/grn/%d/%s" % (g["id"], a), json={"reason": reason}), code)
    return out


def setting(db, w, item, **kw):
    row = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == w.item[item]).one()
    for k, v in kw.items():
        setattr(row, k, v)
    db.commit()


CEMENT = lambda w, **kw: dict({"po_line_id": po_line(w, "cement"), "uom": "bag", "received_qty": "100", "accepted_qty": "98",  # noqa: E731
                               "rejected_qty": "2"}, **kw)
TMT12 = lambda w, **kw: dict({"po_line_id": po_line(w, "tmt12"), "uom": "kg", "received_qty": "500", "accepted_qty": "500"}, **kw)  # noqa: E731


# --- against a purchase order --------------------------------------------------------------------------------------

def test_pending_lines_of_an_approved_order(world, sign_in):
    w, owner = world, sign_in("owner")
    orders = ok(owner.get(I + "/pos?store_id=%d" % w.site_id))["orders"]
    assert [o["id"] for o in orders] == [w.po_id] and orders[0]["open_lines"] == 3
    lines = {l["po_line_id"]: l for l in ok(owner.get(I + "/pos/%d/lines?store_id=%d" % (w.po_id, w.site_id)))["lines"]}
    cem = lines[po_line(w, "cement")]
    assert (cem["po_uom"], cem["factor"], cem["ordered_base"], cem["pending_qty"], cem["base_rate"], cem["gst_pct"]) == (
        "bag", "50.000000", "20000.000", "400.000", "7.0000", "20.000")


def test_a_grn_against_an_order_lands_at_po_rate_plus_charges(world, sign_in, db):
    w, owner = world, sign_in("owner")
    g = grn(owner, w, [CEMENT(w), TMT12(w)], freight="800", loading="200", invoice_no="INV-9")
    cem, tmt = g["lines"]
    # 100 bag = 5000 kg at 7 = 35000; 500 kg at 62 = 31000. 1000 of charges shared 530.30 / 469.70.
    assert (cem["received_base"], cem["accepted_base"], cem["base_rate"], cem["charges_share"], cem["landed_rate"]) == (
        "5000.000", "4900.000", "7.0000", "530.30", "7.1061")
    assert (tmt["charges_share"], tmt["landed_rate"]) == ("469.70", "62.9394")
    assert g["status"] == "DRAFT" and g["number"].startswith("GRN/ST01/") and g["gst_recoverable"] is True
    assert get_balance(db, w.site_id, w.item["cement"]).qty == 0
    posted = step(owner, g, "submit", "approve", "post")
    assert posted["status"] == "POSTED" and posted["rejection_memo"].startswith("RJM/ST01/")
    db.expire_all()
    bal = get_balance(db, w.site_id, w.item["cement"])
    assert (bal.qty, bal.value) == (D("4900.000"), D("34819.89"))                      # only the accepted 98 bags
    led = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "GRN", DBStoreStockLedger.ref_doc_id == g["id"]).all()
    assert {(e.movement_type, e.project_id) for e in led} == {("GRN_IN", w.project_id)} and len(led) == 2
    assert [t["to"] for t in posted["trail"]] == ["DRAFT", "SUBMITTED", "APPROVED", "POSTED"]
    left = {l["po_line_id"]: l for l in ok(owner.get(I + "/pos/%d/lines" % w.po_id))["lines"]}
    assert left[po_line(w, "cement")]["pending_qty"] == "302.000"                      # 400 - 98 accepted


def test_gst_that_cannot_be_recovered_is_part_of_the_stock_value(world, sign_in):
    w, owner = world, sign_in("owner")
    ok(owner.put(I + "/settings", json={"gst_recoverable": False}))
    g = grn(owner, w, [TMT12(w)])
    assert g["gst_recoverable"] is False and g["lines"][0]["landed_rate"] == "74.4000"  # 62 + 20 %
    g2 = grn(owner, w, [TMT12(w, received_qty="100", accepted_qty="100")], gst_recoverable=True)
    assert g2["lines"][0]["landed_rate"] == "62.0000"


def test_over_receipt_only_within_the_tolerance(world, sign_in, db):
    w, owner = world, sign_in("owner")
    line = {"po_line_id": po_line(w, "tmt16"), "uom": "kg", "received_qty": "2600", "accepted_qty": "2600"}
    res = owner.post(I + "/grn", json={"store_id": w.site_id, "kind": "PO", "po_id": w.po_id, "grn_date": str(TODAY), "lines": [line]})
    assert res.status_code == 400 and "more than the order allows" in res.json()["detail"]
    setting(db, w, "tmt16", over_receipt_tolerance_pct=D(5))
    g = grn(owner, w, [line])                                                          # 2600 <= 2625
    res = owner.post(I + "/grn", json={"store_id": w.site_id, "kind": "PO", "po_id": w.po_id, "grn_date": str(TODAY),
                                       "lines": [dict(line, received_qty="100", accepted_qty="100")]})
    assert res.status_code == 400 and "at most 25" in res.json()["detail"]             # the first GRN has 2600 in hand
    step(owner, g, "submit", "approve", "post")
    assert {l["po_line_id"]: l for l in ok(owner.get(I + "/pos/%d/lines" % w.po_id))["lines"]}[po_line(w, "tmt16")]["pending_qty"] == "0.000"


def test_line_checks(world, sign_in):
    w, owner = world, sign_in("owner")
    for bad, words in (([CEMENT(w, accepted_qty="90")], "must add up"), ([CEMENT(w, received_qty="0", accepted_qty="0", rejected_qty="0")], "quantity received"),
                       ([CEMENT(w, uom="drum")], "no conversion"), ([CEMENT(w), CEMENT(w)], "appears twice"),
                       ([{"po_line_id": 999999, "received_qty": "1", "accepted_qty": "1"}], "not on")):
        res = owner.post(I + "/grn", json={"store_id": w.site_id, "kind": "PO", "po_id": w.po_id, "grn_date": str(TODAY), "lines": bad})
        assert res.status_code == 400 and words in res.json()["detail"], (words, res.text)


def test_steel_weights_against_the_weighbridge(world, sign_in):
    w, owner = world, sign_in("owner")
    gate = ok(owner.post(I + "/gate", json={"store_id": w.site_id, "entry_date": str(TODAY), "time_in": "10:15", "vehicle_no": "ka01ab1234",
                                            "po_id": w.po_id, "vendor_name": "Sai Steels", "challan_no": "DC-77",
                                            "weighbridge_slip_no": "WB-5", "gross_weight": "11900", "tare_weight": "10000"}))
    assert (gate["net_weight"], gate["vehicle_no"], gate["status"]) == ("1900.000", "KA01AB1234", "OPEN")
    g = grn(owner, w, [{"po_line_id": po_line(w, "tmt16"), "uom": "kg", "received_qty": "1900", "accepted_qty": "1900",
                        "nos": 100, "bundles": 10, "dia_mm": "16", "bar_length_m": "12"}], gate_entry_id=gate["id"])
    steel = g["lines"][0]["steel"]
    assert (steel["theoretical_kg"], steel["actual_kg"], steel["variance_kg"], steel["variance_pct"]) == ("1896.296", "1900.000", "3.704", "0.20")
    assert g["challan_no"] == "DC-77" and g["gate_number"] == gate["number"]
    assert ok(owner.get(I + "/gate/%d" % gate["id"]))["status"] == "GRN_MADE"
    step(owner, g, "cancel", reason="wrong vehicle")
    assert ok(owner.get(I + "/gate/%d" % gate["id"]))["status"] == "OPEN"                # free for another GRN
    assert owner.post(I + "/gate", json={"store_id": w.site_id, "entry_date": str(TODAY), "gross_weight": "5", "tare_weight": "9"}).status_code == 400


def test_batch_tracked_material_needs_its_heat_number_and_mtc(world, sign_in, db):
    w, owner = world, sign_in("owner")
    setting(db, w, "tmt12", is_batch_tracked=True)
    g = grn(owner, w, [TMT12(w)])
    res = owner.post(I + "/grn/%d/submit" % g["id"], json={})
    assert res.status_code == 400 and "batch tracked" in res.json()["detail"]
    g = ok(owner.put(I + "/grn/%d" % g["id"], json={"lines": [TMT12(w, batch_no="HT-4411", mtc_ref="MTC/26/118")]}))
    assert step(owner, g, "submit")["status"] == "SUBMITTED"


# --- quality check and partial posting -----------------------------------------------------------------------------

def test_qc_lines_wait_and_post_when_passed(world, sign_in, db):
    w, owner = world, sign_in("owner")
    setting(db, w, "cement", qc_required=True)
    g = grn(owner, w, [CEMENT(w, accepted_qty="0", rejected_qty="0"), TMT12(w)])
    cem = g["lines"][0]
    assert cem["qc_status"] == "QC_PENDING" and cem["accepted_qty"] == "0.000"
    posted = step(owner, g, "submit", "approve", "post")                                # posts in part
    assert posted["qc_pending"] == 1 and posted["rejection_memo"] is None
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["cement"]).qty == 0 and get_balance(db, w.site_id, w.item["tmt12"]).qty == D("500.000")
    assert owner.post(I + "/grn/lines/%d/qc" % cem["id"], json={"accepted_qty": "90", "rejected_qty": "5", "test_ref": "x"}).status_code == 400
    assert owner.post(I + "/grn/lines/%d/qc" % cem["id"], json={"accepted_qty": "90", "rejected_qty": "10"}).status_code == 400  # no test ref
    after = ok(owner.post(I + "/grn/lines/%d/qc" % cem["id"], json={"accepted_qty": "90", "rejected_qty": "10", "test_type": "Setting time",
                                                                  "test_ref": "LAB/2211", "remarks": "10 bags set hard"}))
    line = after["lines"][0]
    assert (line["qc_status"], line["posted"], line["qc"]["test_ref"], line["qc"]["inspector"]) == ("DONE", True, "LAB/2211", "Store Test Co")
    assert after["qc_pending"] == 0 and after["rejection_memo"]
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["cement"]).qty == D("4500.000")
    assert owner.post(I + "/grn/lines/%d/qc" % cem["id"], json={"accepted_qty": "90", "rejected_qty": "10", "test_ref": "x"}).status_code == 409


# --- cancelling ----------------------------------------------------------------------------------------------------

def test_cancelling_a_posted_grn_reverses_it_unless_the_stock_has_gone(world, sign_in, db):
    w, owner = world, sign_in("owner")
    g = step(owner, grn(owner, w, [TMT12(w)]), "submit", "approve", "post")
    post_movement(db, movement_type="ISSUE_OUT", store_id=w.site_id, item_id=w.item["tmt12"], qty=D(450), rate=None, txn_date=TODAY,
                  project_id=w.project_id, ref_doc_type="ISSUE", ref_doc_id=7001, ref_line_id=1, user_id=None)
    db.commit()
    res = owner.post(I + "/grn/%d/cancel" % g["id"], json={"reason": "wrong PO"})
    assert res.status_code == 409 and "only 50 kg of" in res.json()["detail"] and "TMT Steel 12mm" in res.json()["detail"]
    assert ok(owner.get(I + "/grn/%d" % g["id"]))["status"] == "POSTED"
    g2 = step(owner, grn(owner, w, [TMT12(w, received_qty="100", accepted_qty="100")]), "submit", "approve", "post")
    assert owner.post(I + "/grn/%d/cancel" % g2["id"], json={}).status_code == 400            # a reason is needed
    done = step(owner, g2, "cancel", reason="duplicate")
    assert done["status"] == "CANCELLED" and done["cancel_reason"] == "duplicate"
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["tmt12"]).qty == D("50.000")
    assert owner.post(I + "/grn/%d/post" % g2["id"], json={}).status_code == 409


# --- rejection and purchase return ---------------------------------------------------------------------------------

def test_purchase_return_and_debit_note(world, sign_in, db):
    w, owner = world, sign_in("owner")
    g = step(owner, grn(owner, w, [CEMENT(w)], invoice_no="INV-55"), "submit", "approve", "post")
    line = g["lines"][0]
    res = owner.post(I + "/returns", json={"grn_id": g["id"], "return_date": str(TODAY), "reason": "x",
                                           "lines": [{"grn_line_id": line["id"], "source": "REJECTED", "qty": "3"}]})
    assert res.status_code == 400 and "only 2 bag rejected" in res.json()["detail"]
    ret = ok(owner.post(I + "/returns", json={"grn_id": g["id"], "return_date": str(TODAY), "reason": "lumps and short weight",
                                              "lines": [{"grn_line_id": line["id"], "source": "REJECTED", "qty": "2"},
                                                        {"grn_line_id": line["id"], "source": "ACCEPTED", "qty": "8"}]}))
    note = ret["debit_note"]
    assert ret["number"].startswith("PRN/ST01/") and note["po_number"] and note["invoice_no"] == "INV-55"
    assert [(l["source"], l["qty"], l["qty_base"], l["rate"], l["taxable_value"], l["gst"]) for l in note["lines"]] == [
        ("REJECTED", "2.000", "100.000", "7.0000", "700.00", "140.00"), ("ACCEPTED", "8.000", "400.000", "7.0000", "2800.00", "560.00")]
    assert (note["taxable_value"], note["gst"], note["total"]) == ("3500.00", "700.00", "4200.00")
    assert ok(owner.get(I + "/returns/%d/debit-note" % ret["id"]))["total"] == "4200.00"
    res = owner.post(I + "/grn/%d/cancel" % g["id"], json={"reason": "x"})
    assert res.status_code == 409 and ret["number"] in res.json()["detail"]                    # the return first
    for a in ("submit", "approve", "post"):
        ok(owner.post(I + "/returns/%d/%s" % (ret["id"], a), json={}))
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["cement"]).qty == D("4500.000")                    # 4900 - 400; rejected never came in
    out = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "PURCHASE_RETURN", DBStoreStockLedger.ref_doc_id == ret["id"]).all()
    assert [(e.movement_type, e.qty_out) for e in out] == [("PURCHASE_RETURN_OUT", D("400.000"))]
    again = owner.post(I + "/returns", json={"grn_id": g["id"], "return_date": str(TODAY), "reason": "more",
                                             "lines": [{"grn_line_id": line["id"], "source": "REJECTED", "qty": "1"}]})
    assert again.status_code == 400 and "only 0 bag rejected" in again.json()["detail"]
    ok(owner.post(I + "/returns/%d/cancel" % ret["id"], json={"reason": "supplier kept it"}))
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["cement"]).qty == D("4900.000")


# --- direct receipt and client supply ------------------------------------------------------------------------------

def test_a_direct_receipt_needs_a_reason_and_another_persons_approval(world, sign_in, db):
    w = world
    clerk = sign_in("site_keeper", rights=["store.inward.approve"])
    body = {"store_id": w.site_id, "kind": "DIRECT", "grn_date": str(TODAY), "vendor_name": "Local hardware",
            "lines": [{"item_id": w.item["binding_wire"], "uom": "kg", "received_qty": "20", "accepted_qty": "20", "rate": "90", "gst_pct": "18"}]}
    res = clerk.post(I + "/grn", json=body)
    assert res.status_code == 400 and "without a purchase order" in res.json()["detail"]
    g = ok(clerk.post(I + "/grn", json=dict(body, reason="Slab pour tonight, supplier out of stock")))
    assert g["kind"] == "DIRECT" and g["lines"][0]["landed_rate"] == "90.0000"
    step(clerk, g, "submit")
    res = clerk.post(I + "/grn/%d/approve" % g["id"], json={})
    assert res.status_code == 403 and "someone other" in res.json()["detail"]
    boss = sign_in("approver", rights=["store.inward.post"])
    step(boss, g, "approve", "post")
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["binding_wire"]).value == D("1800.00")


def test_client_supplied_material_at_the_agreed_rate(world, sign_in, db):
    w, owner = world, sign_in("owner")
    body = {"store_id": w.site_id, "kind": "CLIENT_SUPPLY", "work_order_id": w.work_order_id, "grn_date": str(TODAY),
            "lines": [{"item_id": w.item["cement"], "uom": "bag", "received_qty": "200", "accepted_qty": "200"}]}
    res = owner.post(I + "/grn", json=body)
    assert res.status_code == 400 and "no agreed rate" in res.json()["detail"]
    assert [x["id"] for x in ok(owner.get(I + "/work-orders?store_id=%d" % w.site_id))["work_orders"]] == [w.work_order_id]
    ok(owner.post(I + "/client-rates", json={"work_order_id": w.work_order_id, "item_id": w.item["cement"], "rate": "6.5",
                                             "reference": "Clause 14.2"}))
    g = ok(owner.post(I + "/grn", json=body))
    assert g["number"].startswith("CSR/ST01/") and g["doc_type"] == "CLIENT_SUPPLY" and g["lines"][0]["landed_rate"] == "6.5000"
    step(owner, g, "submit", "approve", "post")
    e = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "CLIENT_SUPPLY", DBStoreStockLedger.ref_doc_id == g["id"]).one()
    assert (e.movement_type, e.qty_in, e.value, e.work_order_id) == ("CLIENT_SUPPLY_IN", D("10000.000"), D("65000.00"), w.work_order_id)


# --- for P5, and the pending view ----------------------------------------------------------------------------------

def test_receipt_summary_and_what_is_still_to_come(world, sign_in, db):
    w, owner = world, sign_in("owner")
    step(owner, grn(owner, w, [CEMENT(w), TMT12(w)]), "submit", "approve", "post")
    grn(owner, w, [{"po_line_id": po_line(w, "tmt16"), "uom": "kg", "received_qty": "100", "accepted_qty": "100"}])   # a draft: not counted
    summary = {r.po_line_id: r for r in get_po_receipt_summary(db, w.po_id)}
    cem = summary[po_line(w, "cement")]
    assert (cem.item_id, cem.ordered_qty, cem.received_qty, cem.accepted_qty, cem.rejected_qty, cem.pending_qty) == (
        w.item["cement"], D("400.000"), D("100.000"), D("98.000"), D("2.000"), D("302.000"))
    assert summary[po_line(w, "tmt16")].pending_qty == D("2500.000")
    assert get_po_receipt_summary(db, 999999) == []
    http = ok(owner.get(I + "/pos/%d/receipt-summary" % w.po_id))["lines"]
    assert http[0]["pending_qty"] == "302.000"
    by_po = ok(owner.get(I + "/pending?group=po"))["rows"]
    assert len(by_po) == 1 and by_po[0]["lines"] == 3
    # 302 bag x 50 x 7 + 1000 kg x 62 + 2500 kg x 62
    assert by_po[0]["pending_value"] == "322700.00"
    by_vendor = ok(owner.get(I + "/pending?group=vendor"))["rows"]
    assert by_vendor[0]["vendor"] == "Shree Cement Traders" and by_vendor[0]["orders"] == [by_po[0]["po_number"]]


# --- printables ----------------------------------------------------------------------------------------------------

def test_printables(world, sign_in, db):
    w, owner = world, sign_in("owner")
    setting(db, w, "tmt12", qc_required=True)
    g = step(owner, grn(owner, w, [CEMENT(w), TMT12(w, accepted_qty="0")]), "submit", "approve", "post")
    ok(owner.post(I + "/grn/lines/%d/qc" % g["lines"][1]["id"], json={"accepted_qty": "490", "rejected_qty": "10", "test_ref": "TC-9"}))
    ret = ok(owner.post(I + "/returns", json={"grn_id": g["id"], "return_date": str(TODAY), "reason": "rejected",
                                              "lines": [{"grn_line_id": g["lines"][0]["id"], "qty": "2"}]}))
    for url in ("/grn/%d/document.pdf" % g["id"], "/grn/%d/qc.pdf" % g["id"], "/grn/%d/rejection.pdf" % g["id"],
                "/returns/%d/document.pdf" % ret["id"]):
        res = owner.get(I + url)
        assert res.status_code == 200 and res.content[:4] == b"%PDF", url
    clean = grn(owner, w, [{"po_line_id": po_line(w, "tmt16"), "uom": "kg", "received_qty": "10", "accepted_qty": "10"}])
    assert owner.get(I + "/grn/%d/rejection.pdf" % clean["id"]).status_code == 404


# --- rights and store access ---------------------------------------------------------------------------------------

def test_rights_and_store_access(world, sign_in, second_tenant):
    w = world
    viewer = sign_in("viewer")                                         # inward.view at the site only
    assert viewer.get(I + "/grn").status_code == 200
    assert viewer.post(I + "/grn", json={"store_id": w.site_id, "kind": "PO", "po_id": w.po_id, "grn_date": str(TODAY),
                                         "lines": [TMT12(w)]}).status_code == 403
    keeper = sign_in("central_keeper")                                 # works at the central store only
    assert keeper.post(I + "/grn", json={"store_id": w.site_id, "kind": "PO", "po_id": w.po_id, "grn_date": str(TODAY),
                                         "lines": [TMT12(w)]}).status_code == 403
    site = sign_in("site_keeper")
    g = grn(site, w, [TMT12(w)])
    assert keeper.get(I + "/grn/%d" % g["id"]).status_code == 403
    assert site.post(I + "/grn/%d/submit" % g["id"], json={}).status_code == 200
    assert site.post(I + "/grn/%d/approve" % g["id"], json={}).status_code == 403          # no inward.approve
    assert second_tenant.get(I + "/grn/%d" % g["id"]).status_code == 404
    assert second_tenant.get(I + "/pos/%d/lines" % w.po_id).status_code == 404
    assert all(x["store_code"] == "CS01" for x in ok(keeper.get(I + "/grn"))["grns"])
