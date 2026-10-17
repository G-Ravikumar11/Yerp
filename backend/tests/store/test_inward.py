"""P2 - inward: GRN against a purchase order, quality check, over-receipt, cancel/reversal, purchase returns, rights."""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from conftest import make_employee

from app import db as database, models
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion,
    DBStoreUserAssignment, MovementType,
)
from app.models.store_inward import (
    DBStoreGrn, DBStoreGrnLine, DBStoreInwardLog, DBStorePurchaseReturn, DBStorePurchaseReturnLine,
)
from app.services.stock_ledger import get_balance, post_movement
from app.services.store_inward import get_po_receipt_summary

D = Decimal
I = "/api/store/inward"
ALL = ["store.%s.view" % s for s in ("masters", "enquiry", "inward")]


@pytest.fixture(autouse=True)
def _clean(account):
    yield
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        stores = [i for (i,) in s.query(DBStore.id).filter(DBStore.client_id == cid).all()]
        items = [i for (i,) in s.query(models.DBItem.id).filter(models.DBItem.client_id == cid).all()]
        grns = [i for (i,) in s.query(DBStoreGrn.id).filter(DBStoreGrn.client_id == cid).all()]
        prns = [i for (i,) in s.query(DBStorePurchaseReturn.id).filter(DBStorePurchaseReturn.client_id == cid).all()]
        s.query(DBStoreInwardLog).filter(DBStoreInwardLog.doc_type == "GRN", DBStoreInwardLog.doc_id.in_(grns)).delete(synchronize_session=False)
        s.query(DBStoreInwardLog).filter(DBStoreInwardLog.doc_type == "PRN", DBStoreInwardLog.doc_id.in_(prns)).delete(synchronize_session=False)
        s.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id.in_(prns)).delete(synchronize_session=False)
        s.query(DBStorePurchaseReturn).filter(DBStorePurchaseReturn.id.in_(prns)).delete(synchronize_session=False)
        s.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id.in_(grns)).delete(synchronize_session=False)
        s.query(DBStoreGrn).filter(DBStoreGrn.id.in_(grns)).delete(synchronize_session=False)
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreStockBalance, DBStoreFreeze, DBStoreUserAssignment, DBStoreBin):
            s.query(model).filter(model.store_id.in_(stores)).delete(synchronize_session=False)
        from app.models.store_core import DBStoreDocSequence
        s.query(DBStoreDocSequence).filter(DBStoreDocSequence.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreUomConversion, DBStoreItemSettings):
            s.query(model).filter(model.item_id.in_(items)).delete(synchronize_session=False)
        s.query(DBStore).filter(DBStore.id.in_(stores)).delete(synchronize_session=False)
        pos = [i for (i,) in s.query(models.DBPurchaseOrder.id).filter(models.DBPurchaseOrder.client_id == cid).all()]
        s.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id.in_(pos)).delete(synchronize_session=False)
        s.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id.in_(pos)).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def seed(account, tolerance=0, qc_steel=True):
    """A store, cement (kg, 1 bag = 50 kg), steel (kg, quality check), and an approved PO for 400 bags and 1000 kg."""
    o = account["client"]
    w = W()
    with database.SessionLocal() as s:
        w.cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        tag = uuid.uuid4().hex[:6]
        cement = models.DBItem(client_id=w.cid, kind="RM", item_code="CEM-" + tag, item_name="Cement OPC", units_of_measure="kg")
        steel = models.DBItem(client_id=w.cid, kind="RM", item_code="TMT-" + tag, item_name="TMT 12mm", units_of_measure="kg")
        s.add_all([cement, steel])
        s.flush()
        s.add_all([DBStoreItemSettings(item_id=cement.id, base_uom="kg", over_receipt_tolerance_pct=tolerance),
                   DBStoreItemSettings(item_id=steel.id, base_uom="kg", qc_required=qc_steel),
                   DBStoreUomConversion(item_id=cement.id, from_uom="bag", to_base_factor=50)])
        po = models.DBPurchaseOrder(client_id=w.cid, number="PO-" + tag, supplier_name="Shree Cement", status="Approved", issue_date=str(date.today()))
        s.add(po)
        s.flush()
        l1 = models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_code=cement.item_code, uom="bag", qty=400, price=350.0)
        l2 = models.DBPurchaseOrderLineItem(order_id=po.id, description="TMT", item_code=steel.item_code, uom="kg", qty=1000, price=62.0)
        s.add_all([l1, l2])
        s.commit()
        w.cement, w.steel, w.po, w.l1, w.l2 = cement.id, steel.id, po.id, l1.id, l2.id
    w.store = o.post("/api/store/masters/stores", json={"code": "CS" + uuid.uuid4().hex[:4].upper(), "name": "Central", "type": "CENTRAL"}).json()["id"]
    return w


def bal(store, item):
    with database.SessionLocal() as s:
        b = get_balance(s, store, item)
        return b.qty, b.value


def grn(o, w, lines, **kw):
    res = o.post(I + "/grn", json={"store_id": w.store, "po_id": w.po, "lines": lines, **kw})
    assert res.status_code == 201, res.text
    return res.json()


def go(o, kind, doc_id, *actions):
    for a in actions:
        res = o.post("%s/%s/%d/%s" % (I, kind, doc_id, a), json={"reason": "because"} if a == "cancel" else {})
        assert res.status_code == 200, (a, res.text)
    return res.json()


def cement_line(qty="100", **kw):
    return {"po_line_id": None, "item_id": None, "qty": qty, "uom": "bag", "rate": "350", **kw}


def test_grn_against_po_posts_to_stock(account):
    o = account["client"]
    w = seed(account)
    lines = o.get("%s/pos/%d/lines" % (I, w.po)).json()["lines"]
    assert [l["pending_qty"] for l in lines] == ["20000.000", "1000.000"]                  # 400 bags = 20,000 kg
    g = grn(o, w, [{"po_line_id": w.l1, "qty": "100", "uom": "bag"}], challan_no="CH-7", vehicle_no="KA01")
    assert g["status"] == "DRAFT" and g["number"].startswith("GRN/CS") and g["lines"][0]["received_qty"] == "5000.000"
    assert g["lines"][0]["rate"] == "7.0000"                                                # Rs 350 a bag = Rs 7 a kg
    assert bal(w.store, w.cement) == (0, 0)                                                 # stock moves only on POSTED
    go(o, "grn", g["id"], "submit", "approve")
    assert bal(w.store, w.cement) == (0, 0)
    done = go(o, "grn", g["id"], "post")
    assert done["status"] == "POSTED" and done["total_value"] == "35000.00"
    assert bal(w.store, w.cement) == (D("5000"), D("35000"))
    assert [x["to"] for x in done["log"]] == ["DRAFT", "SUBMITTED", "APPROVED", "POSTED"]
    with database.SessionLocal() as s:
        r = [x for x in get_po_receipt_summary(s, w.po) if x.po_line_id == w.l1][0]
        assert (r.ordered_qty, r.received_qty, r.accepted_qty, r.pending_qty) == (D("20000"), D("5000"), D("5000"), D("15000"))
    pdf = o.get("%s/grn/%d/pdf" % (I, g["id"]))
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    assert o.get(I + "/grn", params={"status": "POSTED"}).json()["total"] == 1


def test_lifecycle_is_enforced_and_posted_is_immutable(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [cement_line() | {"item_id": w.cement}])
    for step in ("approve", "post"):
        assert o.post("%s/grn/%d/%s" % (I, g["id"], step)).status_code == 409                # cannot skip ahead
    assert o.put("%s/grn/%d" % (I, g["id"]), json={"remarks": "edited"}).json()["remarks"] == "edited"
    go(o, "grn", g["id"], "submit")
    assert o.put("%s/grn/%d" % (I, g["id"]), json={"remarks": "late"}).status_code == 409    # only a draft is edited
    go(o, "grn", g["id"], "approve", "post")
    assert o.put("%s/grn/%d" % (I, g["id"]), json={"remarks": "late"}).status_code == 409
    assert o.post("%s/grn/%d/post" % (I, g["id"])).status_code == 409                        # not twice
    assert bal(w.store, w.cement)[0] == D("5000")
    assert o.post("%s/grn/%d/cancel" % (I, g["id"]), json={}).status_code == 400            # a reason is needed
    assert o.post(I + "/grn", json={"store_id": w.store, "lines": []}).status_code == 400
    assert o.post(I + "/grn", json={"store_id": w.store, "grn_date": "2999-01-01", "lines": [cement_line() | {"item_id": w.cement}]}).status_code == 400


def test_quality_check_decides_what_reaches_stock(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [{"po_line_id": w.l2, "qty": "500", "uom": "kg"}])
    line = g["lines"][0]
    assert line["qc_required"] and line["accepted_qty"] == "0.000" and not line["qc_done"]
    go(o, "grn", g["id"], "submit")
    assert o.post("%s/grn/%d/approve" % (I, g["id"])).status_code == 409                    # QC not recorded
    bad = o.post("%s/grn/%d/qc" % (I, g["id"]), json={"lines": [{"line_id": line["id"], "accepted_qty": "450", "rejected_qty": "10"}]})
    assert bad.status_code == 400                                                           # 450 + 10 is not 500
    ok = o.post("%s/grn/%d/qc" % (I, g["id"]), json={"lines": [{"line_id": line["id"], "accepted_qty": "480", "rejected_qty": "20", "remarks": "rusted"}]})
    assert ok.status_code == 200 and ok.json()["lines"][0]["rejected_qty"] == "20.000"
    go(o, "grn", g["id"], "approve", "post")
    assert bal(w.store, w.steel) == (D("480"), D("29760"))                                  # only the accepted 480 @ 62
    with database.SessionLocal() as s:
        r = get_po_receipt_summary(s, w.po)[1]
        assert (r.received_qty, r.accepted_qty, r.rejected_qty, r.pending_qty) == (D("500"), D("480"), D("20"), D("520"))


def test_everything_rejected_posts_nothing(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [{"po_line_id": w.l2, "qty": "100", "uom": "kg"}])
    go(o, "grn", g["id"], "submit")
    o.post("%s/grn/%d/qc" % (I, g["id"]), json={"lines": [{"line_id": g["lines"][0]["id"], "accepted_qty": "0", "rejected_qty": "100"}]})
    go(o, "grn", g["id"], "approve")
    assert o.post("%s/grn/%d/post" % (I, g["id"])).status_code == 400


def test_over_receipt_and_tolerance(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [{"po_line_id": w.l1, "qty": "401", "uom": "bag"}])
    assert o.post("%s/grn/%d/submit" % (I, g["id"])).status_code == 409                      # 401 against 400 ordered

    w2 = seed(account, tolerance=5)
    g2 = grn(o, w2, [{"po_line_id": w2.l1, "qty": "410", "uom": "bag"}])
    assert o.post("%s/grn/%d/submit" % (I, g2["id"])).status_code == 200                     # within 5 %
    g3 = grn(o, w2, [{"po_line_id": w2.l1, "qty": "421", "uom": "bag"}])
    assert o.post("%s/grn/%d/submit" % (I, g3["id"])).status_code == 409


def test_cancelling_a_posted_grn_reverses_stock_unless_it_was_used(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [cement_line() | {"item_id": w.cement}])
    go(o, "grn", g["id"], "submit", "approve", "post")
    res = o.post("%s/grn/%d/cancel" % (I, g["id"]), json={"reason": "wrong supplier"})
    assert res.status_code == 200 and res.json()["status"] == "CANCELLED" and res.json()["cancel_reason"] == "wrong supplier"
    assert bal(w.store, w.cement) == (0, 0)

    g2 = grn(o, w, [cement_line("10") | {"item_id": w.cement}])
    go(o, "grn", g2["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:                                                        # the store used some of it
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.store, item_id=w.cement, qty=D("200"), rate=None, txn_date=date.today(),
                      project_id=None, ref_doc_type="ISSUE", ref_doc_id=2, ref_line_id=1, user_id=None)
        s.commit()
    refused = o.post("%s/grn/%d/cancel" % (I, g2["id"]), json={"reason": "oops"})
    assert refused.status_code == 409
    assert o.get("%s/grn/%d" % (I, g2["id"])).json()["status"] == "POSTED" and bal(w.store, w.cement)[0] == D("300")      # nothing half-done


def test_draft_can_be_cancelled_without_touching_stock(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [cement_line() | {"item_id": w.cement}])
    assert go(o, "grn", g["id"], "cancel")["status"] == "CANCELLED"
    assert bal(w.store, w.cement) == (0, 0)


def test_purchase_return(account):
    o = account["client"]
    w = seed(account)
    g = grn(o, w, [cement_line("100") | {"item_id": w.cement}])
    assert o.post(I + "/returns", json={"store_id": w.store, "grn_id": g["id"], "reason": "x", "lines": []}).status_code == 409     # GRN not posted
    go(o, "grn", g["id"], "submit", "approve", "post")
    ret = o.get("%s/grn/%d/returnable" % (I, g["id"])).json()["lines"][0]
    assert ret["returnable_qty"] == "5000.000"

    body = {"store_id": w.store, "grn_id": g["id"], "reason": "damaged bags", "lines": [{"grn_line_id": ret["grn_line_id"], "qty": "1500"}]}
    assert o.post(I + "/returns", json={**body, "reason": ""}).status_code == 400                                                    # a reason
    assert o.post(I + "/returns", json={**body, "lines": [{"grn_line_id": ret["grn_line_id"], "qty": "5001"}]}).status_code == 409   # more than accepted
    p = o.post(I + "/returns", json=body).json()
    assert p["number"].startswith("PRN/CS") and p["status"] == "DRAFT"
    done = go(o, "returns", p["id"], "submit", "approve", "post")
    assert done["total_value"] == "10500.00" and bal(w.store, w.cement) == (D("3500"), D("24500"))                                 # 1500 kg @ 7
    assert o.get("%s/grn/%d/returnable" % (I, g["id"])).json()["lines"][0]["returnable_qty"] == "3500.000"
    assert o.post("%s/grn/%d/cancel" % (I, g["id"]), json={"reason": "r"}).status_code == 409                                      # a return stands against it
    over = o.post(I + "/returns", json={**body, "lines": [{"grn_line_id": ret["grn_line_id"], "qty": "3501"}]})
    assert over.status_code == 409                                                                                                  # counts the earlier return
    assert go(o, "returns", p["id"], "cancel")["status"] == "CANCELLED"
    assert bal(w.store, w.cement) == (D("5000"), D("35000"))                                                                        # reversed
    assert go(o, "grn", g["id"], "cancel")["status"] == "CANCELLED"
    assert o.get("%s/returns/%d/pdf" % (I, p["id"])).status_code == 200


def test_return_without_stock_is_refused(account):
    o = account["client"]
    w = seed(account)
    p = o.post(I + "/returns", json={"store_id": w.store, "reason": "excess", "lines": [{"item_id": w.cement, "qty": "10"}]}).json()
    go(o, "returns", p["id"], "submit", "approve")
    res = o.post("%s/returns/%d/post" % (I, p["id"]))
    assert res.status_code == 409 and bal(w.store, w.cement) == (0, 0)
    assert o.get("%s/returns/%d" % (I, p["id"])).json()["status"] == "APPROVED"


def _login(account, portal, rights, stores):
    email = "staff-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in stores])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    return emp["id"]


def test_rights_store_access_and_maker_checker_split(account, portal):
    o = account["client"]
    w = seed(account)
    other = o.post("/api/store/masters/stores", json={"code": "OT1", "name": "Other"}).json()["id"]
    g = grn(o, w, [cement_line() | {"item_id": w.cement}])
    go(o, "grn", g["id"], "submit")

    _login(account, portal, ALL + ["store.inward.create"], [w.store])                      # a keeper who can draft and submit
    assert portal.get(I + "/grn").json()["total"] == 1
    assert portal.post(I + "/grn", json={"store_id": other, "lines": [cement_line() | {"item_id": w.cement}]}).status_code == 403   # wrong store
    assert portal.post(I + "/grn", json={"store_id": w.store, "lines": [cement_line() | {"item_id": w.cement}]}).status_code == 201
    assert portal.post("%s/grn/%d/approve" % (I, g["id"])).status_code == 403
    assert portal.post("%s/grn/%d/qc" % (I, g["id"]), json={"lines": []}).status_code == 403
    assert portal.post("%s/grn/%d/post" % (I, g["id"])).status_code == 403
    assert portal.post("%s/grn/%d/cancel" % (I, g["id"]), json={"reason": "x"}).status_code == 403

    _login(account, portal, ALL, [w.store])                                                  # view only
    assert portal.post(I + "/grn", json={"store_id": w.store, "lines": []}).status_code == 403
    assert portal.get("%s/grn/%d" % (I, g["id"])).status_code == 200

    _login(account, portal, ALL + ["store.inward.approve", "store.inward.post"], [other])    # right rights, wrong store
    assert portal.get("%s/grn/%d" % (I, g["id"])).status_code == 403
    assert portal.post("%s/grn/%d/approve" % (I, g["id"])).status_code == 403
    assert portal.get(I + "/grn").json()["total"] == 0

    _login(account, portal, ["store.masters.view"], [w.store])                               # no inward right at all
    assert portal.get(I + "/grn").status_code == 403

    _login(account, portal, ALL + ["store.inward.approve", "store.inward.post"], [w.store])  # the checker
    assert portal.post("%s/grn/%d/approve" % (I, g["id"])).status_code == 200
    assert portal.post("%s/grn/%d/post" % (I, g["id"])).status_code == 200
