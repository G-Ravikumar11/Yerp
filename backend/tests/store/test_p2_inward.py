"""P2: inward - goods receipts against purchase orders (with quality check), returns to the supplier, client supply, opening stock."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest

from app import db as database, models
from app.models.store_core import (
    DBStoreBatch, DBStoreBatchBalance, DBStoreLedgerBatch,
    DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.services.stock_ledger import freeze_store, get_balance, post_movement, unfreeze_store

from conftest import make_employee

D = Decimal
API = "/api/store/inward"
TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    """The suite empties the item master between tests, freeing item ids for reuse: clear what points at them."""
    yield
    with database.SessionLocal() as s:
        for model in (DBStoreLedgerBatch, DBStoreBatchBalance, DBStoreBatch):
            s.query(model).delete(synchronize_session=False)
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


class W:
    """One company's stores, items and an approved purchase order, built straight in the database."""


def world(account):
    w = W()
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        tag = uuid.uuid4().hex[:6]
        w.client_id = client.id
        job = models.DBJob(client_id=client.id, number="P-" + tag, name="Tower A")
        s.add(job)
        s.flush()
        w.project_id = job.id
        cs = DBStore(client_id=client.id, code="C" + tag[:3].upper(), name="Central", type="CENTRAL")
        st = DBStore(client_id=client.id, code="S" + tag[:3].upper(), name="Site", type="SITE", project_id=job.id)
        s.add_all([cs, st])
        s.flush()
        w.central, w.site, w.central_code = cs.id, st.id, cs.code
        w.item = {}
        for key, name, uom, qc, tol, conv in (("cement", "Cement OPC", "kg", False, "10", {"bag": 50}), ("steel", "TMT 12mm", "kg", True, "0", {}), ("sand", "River Sand", "cum", False, "0", {})):
            it = models.DBItem(client_id=client.id, kind="RM", item_code="IN-%s-%s" % (key.upper(), tag), item_name=name, units_of_measure=uom)
            s.add(it)
            s.flush()
            w.item[key] = it.id
            s.add(DBStoreItemSettings(item_id=it.id, category="CONSUMABLE", base_uom=uom, qc_required=qc, over_receipt_tolerance_pct=tol))
            s.add_all([DBStoreUomConversion(item_id=it.id, from_uom=u, to_base_factor=f) for u, f in conv.items()])
        po = models.DBPurchaseOrder(client_id=client.id, job_id=job.id, number="PO-" + tag, supplier_name="Shree Traders", status="Approved", issue_date=TODAY)
        s.add(po)
        s.flush()
        w.po = po.id
        w.po_line = {}
        for key, uom, qty, price in (("cement", "bag", 400, 350.0), ("steel", "kg", 1500, 62.0)):
            it = s.get(models.DBItem, w.item[key])
            pl = models.DBPurchaseOrderLineItem(order_id=po.id, description=it.item_name, item_code=it.item_code, uom=uom, qty=qty, price=price)
            s.add(pl)
            s.flush()
            w.po_line[key] = pl.id
        s.commit()
    return w


def staff(account, portal, rights, store_ids=()):
    email = "p2-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in store_ids])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    return emp


def grn_body(w, lines=None, store=None, **over):
    lines = lines if lines is not None else [{"po_line_id": w.po_line["cement"], "qty": "100", "uom": "bag"}]
    return {"store_id": store or w.central, "grn_date": TODAY, "po_id": w.po, "challan_no": "CH-1", "vehicle_no": "TS09AB1234", "lines": lines, **over}


def make_grn(tenant, w, **kw):
    res = tenant.post(API + "/grn", json=grn_body(w, **kw))
    assert res.status_code == 200, res.text
    return res.json()


def move(tenant, kind, doc_id, *steps):
    last = None
    for step in steps:
        res = tenant.post("%s/%s/%d/%s" % (API, kind, doc_id, step), json={"reason": "wrong delivery"} if step == "cancel" else None)
        assert res.status_code == 200, (step, res.text)
        last = res.json()
    return last


def balance(w, store, key):
    with database.SessionLocal() as s:
        b = get_balance(s, store, w.item[key])
        return b.qty, b.value, b.avg_rate


# --- the happy path ---------------------------------------------------------------------------------------------------

def test_a_goods_receipt_runs_draft_to_posted_and_stock_moves_only_at_the_end(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    assert g["status"] == "DRAFT" and g["number"].startswith("GRN/%s/" % w.central_code) and g["number"].endswith("/00001")
    line = g["lines"][0]
    assert (line["entry_qty"], line["entry_uom"], line["received_qty"], line["accepted_qty"], line["rate"]) == ("100.000", "bag", "5000.000", "5000.000", "7.0000")
    assert g["supplier_name"] == "Shree Traders" and g["project_id"] == w.project_id and g["value"] == "35000.00"
    assert balance(w, w.central, "cement")[0] == 0                                       # a draft moves nothing
    for step, status in (("submit", "SUBMITTED"), ("approve", "APPROVED")):
        assert move(tenant, "grn", g["id"], step)["status"] == status
        assert balance(w, w.central, "cement")[0] == 0
    posted = move(tenant, "grn", g["id"], "post")
    assert posted["status"] == "POSTED" and posted["posted_at"]
    assert balance(w, w.central, "cement") == (D("5000.000"), D("35000.00"), D("7.0000"))
    assert [h["action"] for h in posted["history"]] == ["create", "submit", "approve", "post"] and all(h["by"] for h in posted["history"])
    with database.SessionLocal() as s:
        rows = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "GRN", DBStoreStockLedger.ref_doc_id == g["id"]).all()
        assert [(r.movement_type, r.qty_in, r.project_id) for r in rows] == [("GRN_IN", D("5000.000"), w.project_id)]
    listed = tenant.get(API + "/grn", params={"status": "POSTED"}).json()
    assert listed["total"] == 1 and listed["items"][0]["number"] == g["number"]
    assert tenant.get(API).json()["slice"] == "inward"
    summary = tenant.get(API + "/po-summary/%d" % w.po).json()["lines"]
    cement = [l for l in summary if l["po_line_id"] == w.po_line["cement"]][0]
    assert (cement["ordered_qty"], cement["accepted_qty"], cement["pending_qty"]) == ("20000.000", "5000.000", "15000.000")
    opts = tenant.get(API + "/po-options").json()["items"]
    assert opts and {l["po_line_id"] for l in opts[0]["lines"]} == {w.po_line["cement"], w.po_line["steel"]}


def test_the_lifecycle_cannot_be_skipped_or_repeated(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    for step in ("approve", "post"):
        assert tenant.post("%s/grn/%d/%s" % (API, g["id"], step)).status_code == 409
    move(tenant, "grn", g["id"], "submit")
    assert tenant.post("%s/grn/%d/submit" % (API, g["id"])).status_code == 409
    assert tenant.post("%s/grn/%d/nonsense" % (API, g["id"])).status_code == 404
    assert tenant.put("%s/grn/%d" % (API, g["id"]), json=grn_body(w)).status_code == 409            # only a draft is edited
    assert tenant.delete("%s/grn/%d" % (API, g["id"])).status_code == 409


def test_a_draft_can_be_edited_and_thrown_away(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    edited = tenant.put("%s/grn/%d" % (API, g["id"]), json=grn_body(w, lines=[{"po_line_id": w.po_line["cement"], "qty": "60", "uom": "bag", "rate": "340"}], remarks="second look"))
    assert edited.status_code == 200 and edited.json()["lines"][0]["received_qty"] == "3000.000" and edited.json()["remarks"] == "second look"
    assert edited.json()["lines"][0]["rate"] == "6.8000"
    assert tenant.put("%s/grn/%d" % (API, g["id"]), json=grn_body(w, store=w.site)).status_code == 400    # not to another store
    assert tenant.delete("%s/grn/%d" % (API, g["id"])).status_code == 200
    assert tenant.get("%s/grn/%d" % (API, g["id"])).status_code == 404


# --- checks on what is typed ------------------------------------------------------------------------------------------

def test_a_receipt_cannot_run_past_the_order_plus_tolerance(account):
    tenant = account["client"]
    w = world(account)                                                          # 400 bags ordered, 10% tolerance = 440
    over = tenant.post(API + "/grn", json=grn_body(w, lines=[{"po_line_id": w.po_line["cement"], "qty": "441", "uom": "bag"}]))
    assert over.status_code == 409 and "more than the" in over.json()["detail"]
    first = make_grn(tenant, w, lines=[{"po_line_id": w.po_line["cement"], "qty": "400", "uom": "bag"}])
    move(tenant, "grn", first["id"], "submit", "approve", "post")
    second = tenant.post(API + "/grn", json=grn_body(w, lines=[{"po_line_id": w.po_line["cement"], "qty": "41", "uom": "bag"}]))
    assert second.status_code == 409 and "At most 2000.000 can still be accepted" in second.json()["detail"]
    assert tenant.post(API + "/grn", json=grn_body(w, lines=[{"po_line_id": w.po_line["cement"], "qty": "40", "uom": "bag"}])).status_code == 200


def test_bad_receipts_are_refused_in_words(account):
    tenant = account["client"]
    w = world(account)
    cl = w.po_line["cement"]
    bad = [
        ({"lines": []}, "at least one line"),
        ({"lines": [{"po_line_id": cl, "qty": "0", "uom": "bag"}]}, "more than zero"),
        ({"lines": [{"po_line_id": cl, "qty": "abc", "uom": "bag"}]}, "not a number"),
        ({"lines": [{"po_line_id": cl, "qty": "5", "uom": "furlong"}]}, "No conversion"),
        ({"lines": [{"po_line_id": 999999, "qty": "5", "uom": "bag"}]}, "not a line of purchase order"),
        ({"lines": [{"po_line_id": cl, "qty": "5", "uom": "bag"}, {"po_line_id": cl, "qty": "5", "uom": "bag"}]}, "twice"),
        ({"lines": [{"po_line_id": cl, "qty": "5", "uom": "bag", "rejected_qty": "6"}]}, "more was rejected"),
        ({"lines": [{"po_line_id": cl, "qty": "5", "uom": "bag", "rejected_qty": "1"}]}, "say why"),
        ({"lines": [{"item_id": w.item["cement"], "qty": "5", "uom": "bag"}]}, "choose the purchase-order line"),
        ({"grn_date": "2999-01-01"}, "future"),
        ({"grn_date": "nope"}, "not a date"),
        ({"store_id": 999999}, "store does not exist"),
        ({"po_id": 999999}, "purchase order does not exist"),
        ({"lines": [{"po_line_id": cl, "qty": "5", "uom": "bag", "rate": "-3"}]}, "more than zero"),
    ]
    for over, word in bad:
        res = tenant.post(API + "/grn", json=grn_body(w, **over))
        assert res.status_code in (400, 409) and word.lower() in res.json()["detail"].lower(), (over, res.text)
    assert tenant.get(API + "/grn").json()["total"] == 0                          # nothing half-made


def test_a_purchase_order_that_is_not_approved_takes_no_receipt(account):
    tenant = account["client"]
    w = world(account)
    with database.SessionLocal() as s:
        s.get(models.DBPurchaseOrder, w.po).status = "Closed"
        s.commit()
    res = tenant.post(API + "/grn", json=grn_body(w))
    assert res.status_code == 409 and "closed" in res.json()["detail"]


def test_a_receipt_without_an_order_needs_a_supplier_and_a_rate(account):
    tenant = account["client"]
    w = world(account)
    line = {"item_id": w.item["sand"], "qty": "10", "uom": "cum", "rate": "1800"}
    assert tenant.post(API + "/grn", json={"store_id": w.central, "grn_date": TODAY, "lines": [line]}).status_code == 400
    res = tenant.post(API + "/grn", json={"store_id": w.central, "grn_date": TODAY, "supplier_name": "Cash purchase", "lines": [{**line, "rate": ""}]})
    assert res.status_code == 400 and "give the rate" in res.json()["detail"].lower()
    ok = tenant.post(API + "/grn", json={"store_id": w.central, "grn_date": TODAY, "supplier_name": "Cash purchase", "lines": [line]})
    assert ok.status_code == 200 and ok.json()["po_id"] is None
    move(tenant, "grn", ok.json()["id"], "submit", "approve", "post")
    assert balance(w, w.central, "sand") == (D("10.000"), D("18000.00"), D("1800.0000"))


# --- quality check --------------------------------------------------------------------------------------------------------

def test_quality_check_decides_what_goes_into_stock(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w, lines=[{"po_line_id": w.po_line["steel"], "qty": "1000", "uom": "kg"}])
    line = g["lines"][0]
    assert line["qc_status"] == "PENDING" and line["accepted_qty"] == "0.000" and g["qc_pending"] == 1
    assert tenant.post("%s/grn/%d/submit" % (API, g["id"])).status_code == 409                    # a check is outstanding
    url = "%s/grn/%d/qc/%d" % (API, g["id"], line["id"])
    assert tenant.post(url, json={"result": "FAILED"}).status_code == 400                           # a failure needs its reason
    assert tenant.post(url, json={"result": "MAYBE"}).status_code == 400
    assert tenant.post(url, json={"result": "PASSED", "rejected_qty": "50"}).status_code == 400    # rejecting needs a reason
    assert tenant.post(url, json={"result": "PASSED", "rejected_qty": "2000", "note": "x"}).status_code == 400
    done = tenant.post(url, json={"result": "PASSED", "rejected_qty": "100", "note": "rusted bundle"}).json()["lines"][0]
    assert (done["qc_status"], done["accepted_qty"], done["rejected_qty"], done["qc_note"]) == ("PASSED", "900.000", "100.000", "rusted bundle")
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    assert balance(w, w.central, "steel") == (D("900.000"), D("55800.00"), D("62.0000"))           # only what passed
    assert tenant.post(url, json={"result": "PASSED"}).status_code == 409                          # too late to change


def test_a_failed_check_leaves_nothing_to_post(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w, lines=[{"po_line_id": w.po_line["steel"], "qty": "500", "uom": "kg"}])
    tenant.post("%s/grn/%d/qc/%d" % (API, g["id"], g["lines"][0]["id"]), json={"result": "FAILED", "note": "wrong grade"})
    move(tenant, "grn", g["id"], "submit", "approve")
    res = tenant.post("%s/grn/%d/post" % (API, g["id"]))
    assert res.status_code == 409 and "nothing was accepted" in res.json()["detail"].lower()
    assert tenant.get("%s/grn/%d" % (API, g["id"])).json()["status"] == "APPROVED"
    assert move(tenant, "grn", g["id"], "cancel")["status"] == "CANCELLED"


# --- cancel and reversal ----------------------------------------------------------------------------------------------------

def test_cancelling_needs_a_reason_and_before_posting_moves_nothing(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    assert tenant.post("%s/grn/%d/cancel" % (API, g["id"]), json={"reason": " "}).status_code == 400
    assert tenant.post("%s/grn/%d/cancel" % (API, g["id"])).status_code == 400
    done = move(tenant, "grn", g["id"], "cancel")
    assert done["status"] == "CANCELLED" and done["cancel_reason"] == "wrong delivery" and done["history"][-1]["action"] == "cancel"
    assert balance(w, w.central, "cement")[0] == 0
    assert tenant.post("%s/grn/%d/cancel" % (API, g["id"]), json={"reason": "again"}).status_code == 409


def test_cancelling_a_posted_receipt_reverses_its_stock(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    assert balance(w, w.central, "cement")[0] == D("5000")
    done = move(tenant, "grn", g["id"], "cancel")
    assert done["status"] == "CANCELLED"
    assert balance(w, w.central, "cement") == (D("0.000"), D("0.00"), D("7.0000"))
    with database.SessionLocal() as s:
        rows = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "GRN", DBStoreStockLedger.ref_doc_id == g["id"]).order_by(DBStoreStockLedger.id).all()
        assert len(rows) == 2 and rows[1].reversal_of_id == rows[0].id and rows[1].qty_out == D("5000.000")
    # the over-receipt room it had taken comes back
    assert tenant.get(API + "/po-summary/%d" % w.po).json()["lines"][0]["accepted_qty"] == "0.000"


def test_a_receipt_whose_stock_has_been_used_cannot_be_cancelled(account):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    move(tenant, "grn", g["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.central, item_id=w.item["cement"], qty=D("4000"), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=1, ref_line_id=1, user_id=None)
        s.commit()
    res = tenant.post("%s/grn/%d/cancel" % (API, g["id"]), json={"reason": "supplier error"})
    assert res.status_code == 409 and "on hand" in res.json()["detail"].lower()
    assert tenant.get("%s/grn/%d" % (API, g["id"])).json()["status"] == "POSTED"                  # nothing half-done
    assert balance(w, w.central, "cement")[0] == D("1000")


# --- returns to the supplier ---------------------------------------------------------------------------------------------------

def posted_grn(tenant, w, bags="100"):
    g = make_grn(tenant, w, lines=[{"po_line_id": w.po_line["cement"], "qty": bags, "uom": "bag"}])
    return move(tenant, "grn", g["id"], "submit", "approve", "post")


def test_goods_go_back_to_the_supplier_at_the_average_rate(account):
    tenant = account["client"]
    w = world(account)
    g = posted_grn(tenant, w)
    gl = g["lines"][0]["id"]
    avail = tenant.get(API + "/grn-lines/%d" % g["id"]).json()["lines"][0]
    assert (avail["accepted"], avail["returnable"]) == ("5000.000", "5000.000")
    ret = tenant.post(API + "/returns", json={"grn_id": g["id"], "return_date": TODAY, "reason": "damaged bags", "lines": [{"grn_line_id": gl, "qty": "30", "uom": "bag"}]})
    assert ret.status_code == 200, ret.text
    r = ret.json()
    assert r["number"].startswith("PRTN/") and r["grn_number"] == g["number"] and r["lines"][0]["qty"] == "1500.000"
    move(tenant, "returns", r["id"], "submit", "approve", "post")
    assert balance(w, w.central, "cement") == (D("3500.000"), D("24500.00"), D("7.0000"))
    assert tenant.get(API + "/grn-lines/%d" % g["id"]).json()["lines"][0]["returnable"] == "3500.000"
    # net of the return, the supplier still owes 1500 kg
    cement = [l for l in tenant.get(API + "/po-summary/%d" % w.po).json()["lines"] if l["po_line_id"] == w.po_line["cement"]][0]
    assert cement["accepted_qty"] == "3500.000" and cement["pending_qty"] == "16500.000"
    # a receipt with a live return cannot be cancelled until the return is
    res = tenant.post("%s/grn/%d/cancel" % (API, g["id"]), json={"reason": "not wanted"})
    assert res.status_code == 409 and r["number"] in res.json()["detail"]
    assert move(tenant, "returns", r["id"], "cancel")["status"] == "CANCELLED"
    assert balance(w, w.central, "cement")[0] == D("5000.000")
    assert move(tenant, "grn", g["id"], "cancel")["status"] == "CANCELLED"


def test_a_return_cannot_exceed_what_was_accepted_or_what_is_already_returning(account):
    tenant = account["client"]
    w = world(account)
    g = posted_grn(tenant, w, "100")
    gl = g["lines"][0]["id"]
    body = lambda qty: {"grn_id": g["id"], "return_date": TODAY, "lines": [{"grn_line_id": gl, "qty": qty, "uom": "bag"}]}     # noqa: E731
    assert tenant.post(API + "/returns", json=body("101")).status_code == 409
    assert tenant.post(API + "/returns", json=body("0")).status_code == 400
    first = tenant.post(API + "/returns", json=body("60"))
    assert first.status_code == 200
    move(tenant, "returns", first.json()["id"], "submit")
    second = tenant.post(API + "/returns", json=body("41"))
    assert second.status_code == 409 and "already on a return" in second.json()["detail"]
    assert tenant.post(API + "/returns", json=body("40")).status_code == 200
    unposted = make_grn(tenant, w)
    res = tenant.post(API + "/returns", json={"grn_id": unposted["id"], "return_date": TODAY, "lines": [{"grn_line_id": unposted["lines"][0]["id"], "qty": "1", "uom": "bag"}]})
    assert res.status_code == 409 and "posted receipt" in res.json()["detail"]


def test_a_return_cannot_post_stock_that_has_been_used(account):
    tenant = account["client"]
    w = world(account)
    g = posted_grn(tenant, w)
    ret = tenant.post(API + "/returns", json={"grn_id": g["id"], "return_date": TODAY, "lines": [{"grn_line_id": g["lines"][0]["id"], "qty": "60", "uom": "bag"}]}).json()
    move(tenant, "returns", ret["id"], "submit", "approve")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.central, item_id=w.item["cement"], qty=D("4000"), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=2, ref_line_id=1, user_id=None)
        s.commit()
    res = tenant.post("%s/returns/%d/post" % (API, ret["id"]))                                    # 3000 kg to send back, 1000 on hand
    assert res.status_code == 409 and "on hand" in res.json()["detail"].lower()
    assert tenant.get("%s/returns/%d" % (API, ret["id"])).json()["status"] == "APPROVED"
    assert balance(w, w.central, "cement")[0] == D("1000.000")


# --- client supply and opening stock ------------------------------------------------------------------------------------------

def test_material_supplied_by_the_client_is_stock_against_its_project(account):
    tenant = account["client"]
    w = world(account)
    body = {"store_id": w.site, "supply_date": TODAY, "project_id": w.project_id, "client_ref": "CL-77", "lines": [{"item_id": w.item["steel"], "qty": "2", "uom": "kg", "rate": "60"}]}
    for bad, word in (({"project_id": 0}, "choose the project"), ({"project_id": 999999}, "project does not exist"), ({"work_order_id": 999999}, "work order"),
                      ({"lines": [{"item_id": w.item["steel"], "qty": "1", "uom": "kg"}, {"item_id": w.item["steel"], "qty": "1", "uom": "kg"}]}, "twice")):
        res = tenant.post(API + "/client-supply", json={**body, **bad})
        assert res.status_code == 400 and word in res.json()["detail"].lower(), (bad, res.text)
    made = tenant.post(API + "/client-supply", json=body)
    assert made.status_code == 200 and made.json()["number"].startswith("CSUP/")
    move(tenant, "client-supply", made.json()["id"], "submit", "approve", "post")
    assert balance(w, w.site, "steel") == (D("2.000"), D("120.00"), D("60.0000"))
    with database.SessionLocal() as s:
        row = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "CSUP").one()
        assert row.movement_type == "CLIENT_SUPPLY_IN" and row.project_id == w.project_id
    free = tenant.post(API + "/client-supply", json={**body, "lines": [{"item_id": w.item["sand"], "qty": "5", "uom": "cum"}]})          # the client gives no value
    move(tenant, "client-supply", free.json()["id"], "submit", "approve", "post")
    assert balance(w, w.site, "sand") == (D("5.000"), D("0.00"), D("0.0000"))


def test_opening_stock_is_posted_as_opening(account):
    tenant = account["client"]
    w = world(account)
    body = {"store_id": w.central, "as_on_date": (date.today() - timedelta(days=30)).isoformat(), "lines": [{"item_id": w.item["cement"], "qty": "20", "uom": "bag", "rate": "340"}]}
    assert tenant.post(API + "/opening", json={**body, "as_on_date": "2999-01-01"}).status_code == 400
    assert tenant.post(API + "/opening", json={**body, "lines": [{"item_id": w.item["cement"], "qty": "1", "uom": "bag"}]}).status_code == 422
    made = tenant.post(API + "/opening", json=body).json()
    assert made["number"].startswith("OSTK/") and made["value"] == "6800.00"
    move(tenant, "opening", made["id"], "submit", "approve", "post")
    assert balance(w, w.central, "cement") == (D("1000.000"), D("6800.00"), D("6.8000"))
    with database.SessionLocal() as s:
        assert s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "OSTK").one().movement_type == "OPENING_IN"


# --- stores, rights and tenancy -----------------------------------------------------------------------------------------------------

def test_a_frozen_store_still_takes_a_delivery_but_sends_nothing_back(account):
    """A count on does not strand the lorry at the gate: the receipt posts, apart from the count. Nothing leaves, though."""
    tenant = account["client"]
    w = world(account)
    g = posted_grn(tenant, w, bags="10")
    ret = tenant.post(API + "/returns", json={"grn_id": g["id"], "return_date": TODAY, "lines": [{"grn_line_id": g["lines"][0]["id"], "qty": "1", "uom": "bag"}]}).json()
    move(tenant, "returns", ret["id"], "submit", "approve")
    g2 = make_grn(tenant, w)
    move(tenant, "grn", g2["id"], "submit", "approve")
    with database.SessionLocal() as s:
        freeze_store(s, w.central, "annual count", None)
        s.commit()
    assert move(tenant, "grn", g2["id"], "post")["status"] == "POSTED"
    res = tenant.post("%s/returns/%d/post" % (API, ret["id"]))
    assert res.status_code == 423 and "frozen" in res.json()["detail"].lower()
    assert tenant.get("%s/returns/%d" % (API, ret["id"])).json()["status"] == "APPROVED"
    with database.SessionLocal() as s:
        unfreeze_store(s, w.central, None)
        s.commit()
    assert move(tenant, "returns", ret["id"], "post")["status"] == "POSTED"


def test_each_step_needs_its_own_right(account, portal):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    staff(account, portal, ["store.inward.view", "store.inward.create"], [w.central])
    assert portal.post("%s/grn/%d/submit" % (API, g["id"])).status_code == 200
    for step in ("approve", "post"):
        assert portal.post("%s/grn/%d/%s" % (API, g["id"], step)).status_code == 403
    assert portal.post("%s/grn/%d/cancel" % (API, g["id"]), json={"reason": "no"}).status_code == 403
    assert portal.post("%s/grn/%d/qc/1" % (API, g["id"]), json={"result": "PASSED"}).status_code == 403


def test_a_viewer_can_look_but_not_make(account, portal):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    staff(account, portal, ["store.inward.view"], [w.central])
    assert portal.get(API + "/grn").json()["total"] == 1
    assert portal.get("%s/grn/%d" % (API, g["id"])).status_code == 200
    assert portal.post(API + "/grn", json=grn_body(w)).status_code == 403
    assert portal.put("%s/grn/%d" % (API, g["id"]), json=grn_body(w)).status_code == 403
    assert portal.delete("%s/grn/%d" % (API, g["id"])).status_code == 403
    assert portal.post(API + "/returns", json={"grn_id": g["id"], "return_date": TODAY, "lines": []}).status_code == 403


def test_staff_work_only_in_their_own_stores(account, portal):
    tenant = account["client"]
    w = world(account)
    at_site = make_grn(tenant, w, store=w.site)
    at_central = make_grn(tenant, w, store=w.central)
    staff(account, portal, ["store.inward.view", "store.inward.create", "store.inward.post"], [w.site])
    assert [d["number"] for d in portal.get(API + "/grn").json()["items"]] == [at_site["number"]]       # only their store's receipts
    assert portal.get("%s/grn/%d" % (API, at_central["id"])).status_code == 403
    assert portal.post("%s/grn/%d/submit" % (API, at_central["id"])).status_code == 403
    assert portal.post(API + "/grn", json=grn_body(w, store=w.central)).status_code == 403            # wrong-store access
    assert portal.get(API + "/grn", params={"store_id": w.central}).status_code == 403
    assert portal.post(API + "/grn", json=grn_body(w, store=w.site)).status_code == 200
    assert portal.get("%s/grn/%d/print" % (API, at_central["id"])).status_code == 403


def test_one_company_cannot_reach_anothers_documents(account, second_tenant):
    tenant = account["client"]
    w = world(account)
    g = make_grn(tenant, w)
    assert second_tenant.get("%s/grn/%d" % (API, g["id"])).status_code == 404
    assert second_tenant.post("%s/grn/%d/submit" % (API, g["id"])).status_code == 404
    assert second_tenant.get("%s/grn/%d/print" % (API, g["id"])).status_code == 404
    assert second_tenant.get(API + "/grn").json()["total"] == 0
    assert second_tenant.post(API + "/grn", json=grn_body(w)).status_code == 400                      # their store lookup finds nothing
    assert second_tenant.get(API + "/po-summary/%d" % w.po).status_code == 404
    assert second_tenant.get(API + "/po-options").json()["items"] == []
    assert second_tenant.get(API + "/nonsense").status_code == 404


# --- printing and exports ------------------------------------------------------------------------------------------------------------

def test_every_document_prints_and_the_lists_export(account):
    tenant = account["client"]
    w = world(account)
    g = posted_grn(tenant, w)
    ret = tenant.post(API + "/returns", json={"grn_id": g["id"], "return_date": TODAY, "lines": [{"grn_line_id": g["lines"][0]["id"], "qty": "1", "uom": "bag"}]}).json()
    sup = tenant.post(API + "/client-supply", json={"store_id": w.site, "supply_date": TODAY, "project_id": w.project_id, "lines": [{"item_id": w.item["sand"], "qty": "1", "uom": "cum"}]}).json()
    opn = tenant.post(API + "/opening", json={"store_id": w.central, "as_on_date": TODAY, "lines": [{"item_id": w.item["sand"], "qty": "1", "uom": "cum", "rate": "10"}]}).json()
    for kind, doc in (("grn", g), ("returns", ret), ("client-supply", sup), ("opening", opn)):
        res = tenant.get("%s/%s/%d/print" % (API, kind, doc["id"]))
        assert res.status_code == 200 and res.content[:4] == b"%PDF" and res.headers["content-type"] == "application/pdf", (kind, res.text[:200])
        xl = tenant.get("%s/%s/export" % (API, kind))
        assert xl.status_code == 200 and openpyxl.load_workbook(io.BytesIO(xl.content)).active.max_row >= 2
