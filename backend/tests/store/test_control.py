"""P4 - control: transfers with in-transit and short receipt, blind stock counts that freeze the store, adjustments, scrap, rights."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import make_employee

from app import db as database, models
from app.models.store_control import (
    DBStoreAdjustment, DBStoreAdjustmentLine, DBStoreControlLog, DBStoreCount, DBStoreCountLine, DBStoreScrap, DBStoreScrapLine,
    DBStoreTransfer, DBStoreTransferLine,
)
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreDocSequence, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger,
    DBStoreUomConversion, DBStoreUserAssignment, MovementType, StoreFrozenError,
)
from app.models.store_outward import DBStoreWriteoffRequest
from app.services.stock_ledger import get_balance, post_movement
from app.services.store_control import get_count_variances, get_in_transit, get_scrap_realisation
from app.services.store_outward import list_writeoff_requests

D = Decimal
C = "/api/store/control"
VIEW = ["store.%s.view" % s for s in ("masters", "enquiry", "control")]


@pytest.fixture(autouse=True)
def _clean(account):
    yield
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        stores = [i for (i,) in s.query(DBStore.id).filter(DBStore.client_id == cid).all()]
        items = [i for (i,) in s.query(models.DBItem.id).filter(models.DBItem.client_id == cid).all()]
        for model, line, fk, t in ((DBStoreTransfer, DBStoreTransferLine, DBStoreTransferLine.transfer_id, "TRF"), (DBStoreCount, DBStoreCountLine, DBStoreCountLine.count_id, "CNT"),
                                   (DBStoreAdjustment, DBStoreAdjustmentLine, DBStoreAdjustmentLine.adjustment_id, "ADJ"), (DBStoreScrap, DBStoreScrapLine, DBStoreScrapLine.scrap_id, "SCR")):
            ids = [i for (i,) in s.query(model.id).filter(model.client_id == cid).all()]
            s.query(DBStoreControlLog).filter(DBStoreControlLog.doc_type == t, DBStoreControlLog.doc_id.in_(ids)).delete(synchronize_session=False)
            s.query(line).filter(fk.in_(ids)).delete(synchronize_session=False)
            s.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
        s.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.client_id == cid).delete(synchronize_session=False)
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreStockBalance, DBStoreFreeze, DBStoreUserAssignment, DBStoreBin, DBStoreDocSequence):
            s.query(model).filter(model.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreUomConversion, DBStoreItemSettings):
            s.query(model).filter(model.item_id.in_(items)).delete(synchronize_session=False)
        s.query(DBStore).filter(DBStore.id.in_(stores)).delete(synchronize_session=False)
        s.query(models.DBJob).filter(models.DBJob.client_id == cid).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def seed(account):
    """Two stores on two projects; cement (kg, 7/kg) and steel (kg, 62/kg) held at store A."""
    o = account["client"]
    w = W()
    tag = uuid.uuid4().hex[:6]
    with database.SessionLocal() as s:
        w.cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        ja, jb = models.DBJob(client_id=w.cid, number="PA-" + tag, name="Tower A"), models.DBJob(client_id=w.cid, number="PB-" + tag, name="Tower B")
        cement = models.DBItem(client_id=w.cid, kind="RM", item_code="CEM-" + tag, item_name="Cement", units_of_measure="kg")
        steel = models.DBItem(client_id=w.cid, kind="RM", item_code="STL-" + tag, item_name="Steel", units_of_measure="kg")
        s.add_all([ja, jb, cement, steel])
        s.flush()
        s.add_all([DBStoreItemSettings(item_id=cement.id, base_uom="kg"), DBStoreItemSettings(item_id=steel.id, base_uom="kg")])
        s.commit()
        w.ja, w.jb, w.cement, w.steel = ja.id, jb.id, cement.id, steel.id
    mk = lambda code, name, pid: o.post("/api/store/masters/stores", json={"code": code + uuid.uuid4().hex[:3].upper(), "name": name, "type": "SITE", "project_id": pid}).json()["id"]   # noqa: E731
    w.a, w.b = mk("A", "Store A", w.ja), mk("B", "Store B", w.jb)
    with database.SessionLocal() as s:
        for item, qty, rate in ((w.cement, "1000", "7"), (w.steel, "500", "62")):
            post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.a, item_id=item, qty=D(qty), rate=D(rate), txn_date=date.today() - timedelta(days=5),
                          project_id=None, ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
    return w


def bal(store, item):
    with database.SessionLocal() as s:
        b = get_balance(s, store, item)
        return b.qty, b.value


def go(o, kind, doc_id, *actions):
    res = None
    for a in actions:
        res = o.post("%s/%s/%d/%s" % (C, kind, doc_id, a), json={"reason": "because"} if a == "cancel" else {})
        assert res.status_code == 200, (a, res.text)
    return res.json()


def trf(o, w, qty="100", item=None, **kw):
    res = o.post(C + "/transfers", json={"store_id": w.a, "to_store_id": w.b, "vehicle_no": "KA01", "lines": [{"item_id": item or w.cement, "qty": qty}], **kw})
    assert res.status_code == 201, res.text
    return res.json()


def test_transfer_goes_in_transit_then_is_received(account):
    o = account["client"]
    w = seed(account)
    t = trf(o, w)
    assert t["number"].startswith("TRF/") and t["inter_project"] and t["status"] == "DRAFT"
    go(o, "transfers", t["id"], "submit", "approve")
    assert bal(w.a, w.cement)[0] == D("1000")
    posted = go(o, "transfers", t["id"], "post")
    assert posted["transit"] == "IN_TRANSIT" and posted["lines"][0]["rate"] == "7.0000" and posted["total_value"] == "700.00"
    assert bal(w.a, w.cement) == (D("900"), D("6300")) and bal(w.b, w.cement) == (0, 0)                    # out of A, not yet in B
    with database.SessionLocal() as s:
        rows = get_in_transit(s, project_id=w.jb)
        assert len(rows) == 1 and (rows[0].qty, rows[0].value, rows[0].inter_project) == (D("100"), D("700.00"), True)
        assert get_in_transit(s, project_id=999999) == []
    assert len(o.get(C + "/in-transit").json()["rows"]) == 1

    done = o.post("%s/transfers/%d/receive" % (C, t["id"]), json={}).json()
    assert done["transit"] == "RECEIVED" and done["lines"][0]["received_qty"] == "100.000"
    assert bal(w.b, w.cement) == (D("100"), D("700"))                                                       # in at the rate it left at
    with database.SessionLocal() as s:
        assert get_in_transit(s) == []
    assert o.post("%s/transfers/%d/receive" % (C, t["id"]), json={}).status_code == 409                     # not twice
    pdf = o.get("%s/transfers/%d/pdf" % (C, t["id"]))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_short_receipt_returns_the_shortage_to_the_sender(account):
    o = account["client"]
    w = seed(account)
    t = trf(o, w)
    go(o, "transfers", t["id"], "submit", "approve", "post")
    line = o.get("%s/transfers/%d" % (C, t["id"])).json()["lines"][0]["id"]
    assert o.post("%s/transfers/%d/receive" % (C, t["id"]), json={"received": {str(line): "101"}}).status_code == 400
    res = o.post("%s/transfers/%d/receive" % (C, t["id"]), json={"received": {str(line): "90"}}).json()
    assert res["lines"][0]["received_qty"] == "90.000"
    assert bal(w.b, w.cement)[0] == D("90") and bal(w.a, w.cement)[0] == D("910")                           # 10 never arrived: back at A
    assert any("shortage" in x["note"] for x in res["log"])


def test_transfer_stock_checks_and_cancel(account):
    o = account["client"]
    w = seed(account)
    big = trf(o, w, "1001")
    go(o, "transfers", big["id"], "submit", "approve")
    assert o.post("%s/transfers/%d/post" % (C, big["id"])).status_code == 409                               # insufficient stock
    assert bal(w.a, w.cement)[0] == D("1000")

    t = trf(o, w, "100")
    go(o, "transfers", t["id"], "submit", "approve", "post")
    assert go(o, "transfers", t["id"], "cancel")["status"] == "CANCELLED"                                    # in transit: stock returns to A
    assert bal(w.a, w.cement)[0] == D("1000")

    r = trf(o, w, "100")
    go(o, "transfers", r["id"], "submit", "approve", "post")
    o.post("%s/transfers/%d/receive" % (C, r["id"]), json={})
    with database.SessionLocal() as s:                                                                      # B used some of it
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.b, item_id=w.cement, qty=D(20), rate=None, txn_date=date.today(), project_id=w.jb,
                      ref_doc_type="ISSUE", ref_doc_id=5, ref_line_id=1, user_id=None)
        s.commit()
    assert o.post("%s/transfers/%d/cancel" % (C, r["id"]), json={"reason": "x"}).status_code == 409
    assert o.get("%s/transfers/%d" % (C, r["id"])).json()["status"] == "POSTED" and bal(w.b, w.cement)[0] == D("80")
    assert o.post(C + "/transfers", json={"store_id": w.a, "to_store_id": w.a, "lines": [{"item_id": w.cement, "qty": "1"}]}).status_code == 400
    assert o.post("%s/transfers/%d/cancel" % (C, t["id"]), json={"reason": "x"}).status_code == 409        # already cancelled


def _login(account, portal, rights, stores):
    email = "staff-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in stores])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200


def test_inter_project_transfer_needs_the_high_value_right(account, portal):
    o = account["client"]
    w = seed(account)
    t = trf(o, w)
    go(o, "transfers", t["id"], "submit")
    _login(account, portal, VIEW + ["store.control.approve", "store.control.post"], [w.a, w.b])
    res = portal.post("%s/transfers/%d/approve" % (C, t["id"]))
    assert res.status_code == 403 and "high-value" in res.text
    _login(account, portal, VIEW + ["store.control.approve", "store.control.post", "store.control.approve_high_value"], [w.a, w.b])
    assert portal.post("%s/transfers/%d/approve" % (C, t["id"])).status_code == 200
    assert portal.post("%s/transfers/%d/post" % (C, t["id"])).status_code == 200

    _login(account, portal, VIEW + ["store.control.post"], [w.a])                                           # sender only: cannot receive
    assert portal.post("%s/transfers/%d/receive" % (C, t["id"]), json={}).status_code == 403
    _login(account, portal, VIEW + ["store.control.post"], [w.b])                                           # the receiving store can
    assert portal.get("%s/transfers/%d" % (C, t["id"])).status_code == 200
    assert portal.post("%s/transfers/%d/receive" % (C, t["id"]), json={}).status_code == 200
    assert bal(w.b, w.cement)[0] == D("100")


def test_count_freezes_counts_blind_and_posts_the_differences(account, portal):
    o = account["client"]
    w = seed(account)
    c = o.post(C + "/counts", json={"store_id": w.a}).json()
    assert c["number"].startswith("CNT/") and len(c["lines"]) == 2 and c["lines"][0]["system_qty"] is not None                # the account holder sees the books
    with database.SessionLocal() as s:
        with pytest.raises(StoreFrozenError):
            post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.a, item_id=w.cement, qty=D(1), rate=None, txn_date=date.today(), project_id=None,
                          ref_doc_type="ISSUE", ref_doc_id=9, ref_line_id=1, user_id=None)
    assert o.post(C + "/counts", json={"store_id": w.a}).status_code == 400                                  # already frozen
    by = {l["item_id"]: l["id"] for l in c["lines"]}

    _login(account, portal, VIEW + ["store.control.create"], [w.a])                                          # a counter: no right to see the books
    blind = portal.get("%s/counts/%d" % (C, c["id"])).json()
    assert blind["revealed"] is False and all(l["system_qty"] is None and l["variance_qty"] is None for l in blind["lines"])
    assert portal.get("%s/counts/%d/pdf" % (C, c["id"])).status_code == 200

    assert o.post("%s/counts/%d/submit" % (C, c["id"])).status_code == 400                                   # nothing counted
    upd = o.put("%s/counts/%d" % (C, c["id"]), json={"lines": [{"item_id": w.cement, "counted_qty": "985"}, {"item_id": w.steel, "counted_qty": "503"}]})
    assert upd.status_code == 200 and upd.json()["counted_count"] == 2
    go(o, "counts", c["id"], "submit", "approve")
    done = go(o, "counts", c["id"], "post")
    assert done["status"] == "POSTED" and done["variance_value"] == "81.00"                                  # -15 x 7 + 3 x 62
    assert bal(w.a, w.cement) == (D("985"), D("6895")) and bal(w.a, w.steel)[0] == D("503")
    with database.SessionLocal() as s:
        v = {x.item_id: x for x in get_count_variances(s, w.a, date.today(), date.today())}
        assert (v[w.cement].system_qty, v[w.cement].counted_qty, v[w.cement].variance_qty, v[w.cement].variance_value) == (D("1000"), D("985"), D("-15"), D("-105.00"))
        assert get_count_variances(s, w.a, date.today() + timedelta(days=1), None) == []
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.a, item_id=w.cement, qty=D(1), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=10, ref_line_id=1, user_id=None)              # unfrozen again
        s.commit()
    assert go(o, "counts", c["id"], "cancel")["status"] == "CANCELLED"                                       # the adjustments are reversed
    assert bal(w.a, w.cement)[0] == D("1000") - 1 and bal(w.a, w.steel)[0] == D("500")


def test_cancelling_a_draft_count_unfreezes_the_store(account):
    o = account["client"]
    w = seed(account)
    c = o.post(C + "/counts", json={"store_id": w.a, "item_ids": [w.cement]}).json()
    assert len(c["lines"]) == 1
    go(o, "counts", c["id"], "cancel")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.a, item_id=w.cement, qty=D(1), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=11, ref_line_id=1, user_id=None)
        s.commit()


def test_count_finding_unrecorded_item_and_no_difference(account):
    o = account["client"]
    w = seed(account)
    c = o.post(C + "/counts", json={"store_id": w.b, "item_ids": [w.cement]}).json()                         # B holds none
    o.put("%s/counts/%d" % (C, c["id"]), json={"lines": [{"item_id": w.cement, "counted_qty": "0"}]})
    go(o, "counts", c["id"], "submit", "approve", "post")                                                    # nothing differs: nothing posts
    assert bal(w.b, w.cement) == (0, 0) and o.get("%s/counts/%d" % (C, c["id"])).json()["status"] == "POSTED"


def test_adjustments_stock_wastage_and_high_value(account, portal):
    o = account["client"]
    w = seed(account)
    base = {"store_id": w.a, "reason": "Damaged by rain", "lines": [{"item_id": w.cement, "direction": "OUT", "qty": "40"}]}
    assert o.post(C + "/adjustments", json={**base, "reason": ""}).status_code == 400
    a = o.post(C + "/adjustments", json=base).json()
    assert a["number"].startswith("ADJ/") and a["kind"] == "STOCK"
    done = go(o, "adjustments", a["id"], "submit", "approve", "post")
    assert done["total_value"] == "280.00" and bal(w.a, w.cement) == (D("960"), D("6720"))
    up = o.post(C + "/adjustments", json={"store_id": w.a, "reason": "Found in yard", "lines": [{"item_id": w.cement, "direction": "IN", "qty": "10", "rate": "8"}]}).json()
    go(o, "adjustments", up["id"], "submit", "approve", "post")
    assert bal(w.a, w.cement) == (D("970"), D("6800"))
    assert go(o, "adjustments", up["id"], "cancel")["status"] == "CANCELLED" and bal(w.a, w.cement)[0] == D("960")

    assert o.post(C + "/adjustments", json={"store_id": w.a, "reason": "bad", "lines": [{"item_id": w.cement, "direction": "SIDEWAYS", "qty": "1"}]}).status_code == 400
    plain = o.post("/api/store/masters/stores", json={"code": "NP" + uuid.uuid4().hex[:3].upper(), "name": "No project"}).json()["id"]
    assert o.post(C + "/adjustments", json={"store_id": plain, "kind": "WASTAGE", "reason": "spill", "lines": [{"item_id": w.cement, "qty": "1"}]}).status_code == 400   # charged to nothing
    wa = o.post(C + "/adjustments", json={"store_id": w.a, "kind": "WASTAGE", "reason": "Spillage", "cost_head": "OVERHEAD", "lines": [{"item_id": w.cement, "qty": "5"}]}).json()
    go(o, "adjustments", wa["id"], "submit", "approve", "post")
    with database.SessionLocal() as s:
        e = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "ADJUST", DBStoreStockLedger.ref_doc_id == wa["id"]).one()
        assert (e.movement_type, e.cost_head, e.project_id) == ("WASTAGE_OUT", "OVERHEAD", w.ja)

    with database.SessionLocal() as s:                                                                      # 20,000 kg of steel at 62 is Rs 12.4 lakh
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.a, item_id=w.steel, qty=D(20000), rate=D(62), txn_date=date.today(), project_id=None,
                      ref_doc_type="OPENING", ref_doc_id=2, ref_line_id=None, user_id=None)
        s.commit()
    hv = o.post(C + "/adjustments", json={"store_id": w.a, "reason": "Theft", "lines": [{"item_id": w.steel, "direction": "OUT", "qty": "5000"}]}).json()
    go(o, "adjustments", hv["id"], "submit")
    _login(account, portal, VIEW + ["store.control.approve"], [w.a])
    assert portal.post("%s/adjustments/%d/approve" % (C, hv["id"])).status_code == 403
    _login(account, portal, VIEW + ["store.control.approve", "store.control.approve_high_value"], [w.a])
    assert portal.post("%s/adjustments/%d/approve" % (C, hv["id"])).json()["high_value"] is True


def test_writeoff_adjustment_closes_outward_requests(account):
    o = account["client"]
    w = seed(account)
    with database.SessionLocal() as s:
        wr = DBStoreWriteoffRequest(client_id=w.cid, store_id=w.a, item_id=w.steel, qty=D(3), reason="bent beyond use", status="OPEN")
        s.add(wr)
        s.commit()
        rid = wr.id
    assert o.get(C + "/writeoff-requests").json()["rows"][0]["request_id"] == rid
    assert o.post(C + "/adjustments", json={"store_id": w.a, "kind": "WRITEOFF", "reason": "Lost", "lines": [{"writeoff_request_id": 999999}]}).status_code == 400
    a = o.post(C + "/adjustments", json={"store_id": w.a, "kind": "WRITEOFF", "reason": "Lost on site", "lines": [{"writeoff_request_id": rid}]}).json()
    assert a["lines"][0]["qty"] == "3.000"
    before = bal(w.a, w.steel)
    done = go(o, "adjustments", a["id"], "submit", "approve", "post")
    assert bal(w.a, w.steel) == before and done["lines"][0]["value"] == "186.00"                             # no stock moves; valued at the average
    with database.SessionLocal() as s:
        assert list_writeoff_requests(s) == [] and list_writeoff_requests(s, "CLOSED")[0].request_id == rid
    assert o.post("%s/adjustments/%d/cancel" % (C, a["id"]), json={"reason": "x"}).status_code == 409


def test_scrap_records_book_value_and_realisation(account):
    o = account["client"]
    w = seed(account)
    assert o.post(C + "/scrap", json={"store_id": w.a, "lines": [{"item_id": w.steel, "qty": "10"}]}).status_code == 400          # a reason
    s_ = o.post(C + "/scrap", json={"store_id": w.a, "buyer": "Kabadi Traders", "reason": "Cut-offs", "lines": [{"item_id": w.steel, "qty": "50", "realised_value": "1500"}]}).json()
    assert s_["number"].startswith("SCR/") and s_["project_id"] == w.ja
    done = go(o, "scrap", s_["id"], "submit", "approve", "post")
    assert done["book_value"] == "3100.00" and done["realised_value"] == "1500.00" and bal(w.a, w.steel)[0] == D("450")
    with database.SessionLocal() as s:
        rows = get_scrap_realisation(s, w.ja, date.today(), date.today())
        assert len(rows) == 1 and (rows[0].qty, rows[0].book_value, rows[0].realised_value) == (D("50"), D("3100.00"), D("1500.00"))
        assert get_scrap_realisation(s, w.jb, None, None) == []
    assert o.get("%s/scrap/%d/pdf" % (C, s_["id"])).status_code == 200
    assert go(o, "scrap", s_["id"], "cancel")["status"] == "CANCELLED" and bal(w.a, w.steel)[0] == D("500")


def test_lifecycle_rights_and_wrong_store(account, portal):
    o = account["client"]
    w = seed(account)
    t = trf(o, w)
    for step in ("approve", "post"):
        assert o.post("%s/transfers/%d/%s" % (C, t["id"], step)).status_code == 409
    assert o.put("%s/transfers/%d" % (C, t["id"]), json={"vehicle_no": "KA02"}).json()["vehicle_no"] == "KA02"
    go(o, "transfers", t["id"], "submit")
    assert o.put("%s/transfers/%d" % (C, t["id"]), json={"vehicle_no": "x"}).status_code == 409
    assert o.get(C + "/transfers", params={"status": "BOGUS"}).status_code == 400
    assert o.post(C + "/transfers/%d/bogus" % t["id"]).status_code == 404

    _login(account, portal, VIEW + ["store.control.create"], [w.b])                                          # assigned to B only: A's documents are out of reach
    assert portal.post(C + "/adjustments", json={"store_id": w.a, "reason": "x", "lines": [{"item_id": w.cement, "direction": "OUT", "qty": "1"}]}).status_code == 403
    assert portal.post(C + "/counts", json={"store_id": w.a}).status_code == 403
    assert portal.post("%s/transfers/%d/cancel" % (C, t["id"]), json={"reason": "x"}).status_code == 403    # no cancel right
    assert portal.get(C + "/scrap").json()["total"] == 0

    _login(account, portal, ["store.inward.view"], [w.a])
    assert portal.get(C + "/transfers").status_code == 403
