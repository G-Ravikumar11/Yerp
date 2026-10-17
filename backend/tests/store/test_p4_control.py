"""P4: control - transfers (with in-transit), stock counts that freeze and adjust a store, wastage and scrap."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest

from app import db as database, models
from app.models.store_core import (
    DBStore, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, MovementType, StoreFrozenError,
)
from app.services import store_control, store_outward
from app.services.stock_ledger import get_balance, post_movement

from conftest import make_employee

D = Decimal
API = "/api/store/control"
TODAY = date.today().isoformat()


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    """The suite empties the item master between tests, freeing item ids for reuse: clear what points at them."""
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def world(account):
    """A company with a central store holding stock and two project site stores (each on its own project)."""
    w = W()
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        tag = uuid.uuid4().hex[:6]
        w.client_id = client.id
        a = models.DBJob(client_id=client.id, number="P-" + tag, name="Tower A")
        b = models.DBJob(client_id=client.id, number="Q-" + tag, name="Tower B")
        s.add_all([a, b])
        s.flush()
        w.proj_a, w.proj_b = a.id, b.id
        cs = DBStore(client_id=client.id, code="C" + tag[:3].upper(), name="Central", type="CENTRAL")
        sa = DBStore(client_id=client.id, code="A" + tag[:3].upper(), name="Site A", type="SITE", project_id=a.id)
        sb = DBStore(client_id=client.id, code="B" + tag[:3].upper(), name="Site B", type="SITE", project_id=b.id)
        s.add_all([cs, sa, sb])
        s.flush()
        w.central, w.site_a, w.site_b = cs.id, sa.id, sb.id
        w.item = {}
        for key, name, uom, cat, qty, rate, conv in (("cement", "Cement OPC", "kg", "CONSUMABLE", 5000, "7", {"bag": 50}), ("steel", "TMT 12mm", "kg", "CONSUMABLE", 2000, "62", {}),
                                                      ("plate", "Shuttering Plate", "nos", "RETURNABLE", 100, "450", {}), ("sand", "River Sand", "cum", "CONSUMABLE", 0, "0", {})):
            it = models.DBItem(client_id=client.id, kind="RM", item_code="CT-%s-%s" % (key.upper(), tag), item_name=name, units_of_measure=uom)
            s.add(it)
            s.flush()
            w.item[key] = it.id
            s.add(DBStoreItemSettings(item_id=it.id, category=cat, base_uom=uom))
            s.add_all([DBStoreUomConversion(item_id=it.id, from_uom=u, to_base_factor=f) for u, f in conv.items()])
            if qty:
                post_movement(s, movement_type=MovementType.OPENING_IN, store_id=cs.id, item_id=it.id, qty=D(qty), rate=D(rate), txn_date=date.today() - timedelta(days=30), project_id=None,
                              ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
    return w


def staff(account, portal, rights, store_ids=()):
    email = "p4-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in store_ids])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    return emp


def balance(w, store, key):
    with database.SessionLocal() as s:
        b = get_balance(s, store, w.item[key])
        return b.qty, b.value


def move(tenant, kind, doc_id, *steps):
    last = None
    for step in steps:
        res = tenant.post("%s/%s/%d/%s" % (API, kind, doc_id, step), json={"reason": "changed my mind"} if step == "cancel" else None)
        assert res.status_code == 200, (step, res.text)
        last = res.json()
    return last


# --- transfers --------------------------------------------------------------------------------------------------------------

def transfer_body(w, lines=None, **over):
    lines = lines if lines is not None else [{"item_id": w.item["cement"], "qty": "20", "uom": "bag"}]
    return {"store_id": w.central, "to_store_id": w.site_a, "transfer_date": TODAY, "vehicle_no": "TS09AB1234", "lines": lines, **over}


def make_transfer(tenant, w, **kw):
    res = tenant.post(API + "/transfer", json=transfer_body(w, **kw))
    assert res.status_code == 200, res.text
    return res.json()


def test_a_transfer_leaves_the_source_at_dispatch_and_arrives_at_receipt(account):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    assert t["status"] == "DRAFT" and t["number"].startswith("TRF/") and t["receipt_status"] == "" and t["inter_project"] is True
    assert t["lines"][0]["qty"] == "1000.000" and t["lines"][0]["entry_qty"] == "20.000" and t["value"] == "7000.00"
    for step in ("submit", "approve"):
        assert move(tenant, "transfer", t["id"], step)["status"] in ("SUBMITTED", "APPROVED")
        assert balance(w, w.central, "cement")[0] == D("5000.000")
    sent = move(tenant, "transfer", t["id"], "post")
    assert sent["status"] == "POSTED" and sent["receipt_status"] == "IN_TRANSIT" and sent["lines"][0]["rate"] == "7.0000" and sent["lines"][0]["value"] == "7000.00"
    assert balance(w, w.central, "cement") == (D("4000.000"), D("28000.00"))
    assert balance(w, w.site_a, "cement")[0] == 0                                          # in the lorry, not yet in the site store
    transit = tenant.get(API + "/in-transit").json()
    assert transit["total"] == 1 and transit["total_value"] == "7000.00" and transit["items"][0]["to_store"] and transit["items"][0]["inter_project"] is True
    assert tenant.get(API + "/in-transit", params={"project_id": w.proj_a}).json()["total"] == 1
    assert tenant.get(API + "/in-transit", params={"project_id": w.proj_b}).json()["total"] == 0
    with database.SessionLocal() as s:
        got = store_control.get_in_transit(s)
        assert len(got) == 1 and (got[0].qty, got[0].value, got[0].inter_project, got[0].dispatched_on) == (D("1000.000"), D("7000.00"), True, date.today())
    got = move(tenant, "transfer", t["id"], "receive")
    assert got["receipt_status"] == "RECEIVED" and got["received_by"] and got["received_at"]
    assert balance(w, w.site_a, "cement") == (D("1000.000"), D("7000.00"))
    assert tenant.get(API + "/in-transit").json()["total"] == 0
    with database.SessionLocal() as s:
        rows = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "TRANSFER", DBStoreStockLedger.ref_doc_id == t["id"]).order_by(DBStoreStockLedger.id).all()
        assert [(r.movement_type, r.store_id, r.project_id) for r in rows] == [("TRANSFER_OUT", w.central, None), ("TRANSFER_IN", w.site_a, w.proj_a)]
    assert [h["action"] for h in got["history"]] == ["create", "submit", "approve", "post", "receive"]


def test_a_transfer_between_stores_of_one_project_is_not_inter_project(account):
    tenant = account["client"]
    w = world(account)
    with database.SessionLocal() as s:
        extra = DBStore(client_id=w.client_id, code="X" + uuid.uuid4().hex[:3].upper(), name="Site A yard", type="YARD", project_id=w.proj_a)
        s.add(extra)
        s.commit()
        extra_id = extra.id
    first = make_transfer(tenant, w)
    move(tenant, "transfer", first["id"], "submit", "approve", "post", "receive")
    second = make_transfer(tenant, w, store_id=w.site_a, to_store_id=extra_id, lines=[{"item_id": w.item["cement"], "qty": "5", "uom": "bag"}])
    assert second["inter_project"] is False


def test_a_transfer_cannot_take_more_than_the_source_holds_and_a_post_rechecks(account):
    tenant = account["client"]
    w = world(account)
    big = make_transfer(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "101", "uom": "bag"}])
    res = tenant.post("%s/transfer/%d/submit" % (API, big["id"]))
    assert res.status_code == 409 and "Only 5000.000 kg of Cement OPC on hand" in res.json()["detail"]
    t = make_transfer(tenant, w, lines=[{"item_id": w.item["cement"], "qty": "90", "uom": "bag"}])
    move(tenant, "transfer", t["id"], "submit", "approve")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.central, item_id=w.item["cement"], qty=D("1000"), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=77, ref_line_id=1, user_id=None)
        s.commit()
    res = tenant.post("%s/transfer/%d/post" % (API, t["id"]))
    assert res.status_code == 409 and "on hand" in res.json()["detail"].lower()
    assert tenant.get("%s/transfer/%d" % (API, t["id"])).json()["status"] == "APPROVED" and balance(w, w.central, "cement")[0] == D("4000.000")


def test_bad_transfers_are_refused_in_words(account, second_tenant):
    tenant = account["client"]
    w = world(account)
    c = w.item["cement"]
    bad = [
        ({"lines": []}, "at least one line"),
        ({"to_store_id": w.central}, "not to the same store"),
        ({"to_store_id": 999999}, "destination store does not exist"),
        ({"store_id": 999999}, "source store does not exist"),
        ({"lines": [{"item_id": c, "qty": "0", "uom": "bag"}]}, "more than zero"),
        ({"lines": [{"item_id": c, "qty": "x", "uom": "bag"}]}, "not a number"),
        ({"lines": [{"item_id": c, "qty": "1", "uom": "furlong"}]}, "No conversion"),
        ({"lines": [{"item_id": 999999, "qty": "1"}]}, "not a stock item"),
        ({"lines": [{"item_id": c, "qty": "1", "uom": "bag"}] * 2}, "twice"),
        ({"transfer_date": "2999-01-01"}, "future"),
        ({"transfer_date": "nope"}, "not a date"),
    ]
    for over, word in bad:
        res = tenant.post(API + "/transfer", json=transfer_body(w, **over))
        assert res.status_code in (400, 409) and word.lower() in res.json()["detail"].lower(), (over, res.text)
    assert tenant.get(API + "/transfer").json()["total"] == 0
    other = second_tenant.post(API + "/transfer", json=transfer_body(w))
    assert other.status_code == 400                                                         # somebody else's stores do not exist for them


def test_receiving_needs_the_right_the_destination_and_a_dispatch(account, portal):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    assert tenant.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 409        # not dispatched yet
    move(tenant, "transfer", t["id"], "submit", "approve", "post")
    staff(account, portal, ["store.control.view", "store.control.post"], [w.central])         # works at the SOURCE only
    assert portal.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 403
    assert balance(w, w.site_a, "cement")[0] == 0
    staff(account, portal, ["store.control.view"], [w.site_a])                                 # destination, but no right to post
    assert portal.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 403
    staff(account, portal, ["store.control.view", "store.control.post"], [w.site_a])
    assert portal.get("%s/transfer/%d" % (API, t["id"])).status_code == 200                  # can see a transfer coming to its store
    assert portal.get(API + "/transfer").json()["total"] == 1
    assert portal.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 200
    assert portal.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 409        # only once
    assert balance(w, w.site_a, "cement")[0] == D("1000.000")


def test_cancelling_a_dispatched_transfer_brings_the_stock_back(account):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    move(tenant, "transfer", t["id"], "submit", "approve", "post")
    done = move(tenant, "transfer", t["id"], "cancel")
    assert done["status"] == "CANCELLED" and done["receipt_status"] == "" and balance(w, w.central, "cement") == (D("5000.000"), D("35000.00"))
    assert tenant.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 409
    assert tenant.get(API + "/in-transit").json()["total"] == 0


def test_cancelling_a_received_transfer_reverses_both_ends_or_neither(account):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    move(tenant, "transfer", t["id"], "submit", "approve", "post", "receive")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.site_a, item_id=w.item["cement"], qty=D("600"), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=5, ref_line_id=1, user_id=None)
        s.commit()
    res = tenant.post("%s/transfer/%d/cancel" % (API, t["id"]), json={"reason": "sent to the wrong site"})
    assert res.status_code == 409 and "on hand" in res.json()["detail"].lower()
    assert tenant.get("%s/transfer/%d" % (API, t["id"])).json()["receipt_status"] == "RECEIVED"
    assert balance(w, w.central, "cement")[0] == D("4000.000") and balance(w, w.site_a, "cement")[0] == D("400.000")           # nothing half-done
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ADJUST_IN, store_id=w.site_a, item_id=w.item["cement"], qty=D("600"), rate=D("7"), txn_date=date.today(), project_id=None,
                      ref_doc_type="COUNT", ref_doc_id=5, ref_line_id=1, user_id=None)
        s.commit()
    assert move(tenant, "transfer", t["id"], "cancel")["status"] == "CANCELLED"
    assert balance(w, w.central, "cement")[0] == D("5000.000") and balance(w, w.site_a, "cement")[0] == 0


def test_a_high_value_transfer_needs_the_right_to_approve_it(account, portal):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w, lines=[{"item_id": w.item["steel"], "qty": "1000", "uom": "kg"}])          # 62,000
    assert t["value"] == "62000.00"
    move(tenant, "transfer", t["id"], "submit")
    staff(account, portal, ["store.control.view", "store.control.approve"], [w.central])
    res = portal.post("%s/transfer/%d/approve" % (API, t["id"]))
    assert res.status_code == 403 and "high-value" in res.json()["detail"]
    assert tenant.get("%s/transfer/%d" % (API, t["id"])).json()["status"] == "SUBMITTED"
    staff(account, portal, ["store.control.view", "store.control.approve", "store.control.approve_high_value"], [w.central])
    assert portal.post("%s/transfer/%d/approve" % (API, t["id"])).status_code == 200
    small = make_transfer(tenant, w)                                                            # 7,000: any approver
    move(tenant, "transfer", small["id"], "submit")
    staff(account, portal, ["store.control.view", "store.control.approve"], [w.central])
    assert portal.post("%s/transfer/%d/approve" % (API, small["id"])).status_code == 200


# --- stock counts -------------------------------------------------------------------------------------------------------------

def make_count(tenant, w, **over):
    res = tenant.post(API + "/count", json={"store_id": w.central, "count_date": TODAY, **over})
    assert res.status_code == 200, res.text
    return res.json()


def sheet(tenant, c, w, entries):
    rows = [{"item_id": w.item[k], "counted_qty": v[0], "uom": "kg" if k in ("cement", "steel") else "", "reason": v[1] if len(v) > 1 else "", **({"rate": v[2]} if len(v) > 2 else {})} for k, v in entries.items()]
    return tenant.put("%s/count/%d/sheet" % (API, c["id"]), json={"rows": rows})


def test_a_count_freezes_the_store_adjusts_it_to_what_was_found_and_lets_it_move_again(account):
    tenant = account["client"]
    w = world(account)
    c = make_count(tenant, w)
    assert c["status"] == "DRAFT" and c["number"].startswith("COUNT/") and c["started"] is False and c["lines"] == []
    assert sheet(tenant, c, w, {"cement": ("1",)}).status_code == 409                                 # start it first
    started = tenant.post("%s/count/%d/start" % (API, c["id"])).json()
    assert started["started"] and started["frozen"] and started["line_count"] == 3                     # cement, steel, plate hold stock
    with database.SessionLocal() as s:
        with pytest.raises(StoreFrozenError):
            post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.central, item_id=w.item["cement"], qty=D("1"), rate=None, txn_date=date.today(), project_id=None,
                          ref_doc_type="ISSUE", ref_doc_id=9, ref_line_id=1, user_id=None)
        s.rollback()
    assert tenant.post("%s/count/%d/start" % (API, c["id"])).status_code == 409                       # not twice
    # a submit with nothing counted says what is left
    res = tenant.post("%s/count/%d/submit" % (API, c["id"]))
    assert res.status_code == 409 and "3 items still to count" in res.json()["detail"]
    r = sheet(tenant, c, w, {"cement": ("4900", "bags damaged in rain"), "steel": ("2010", "weighbridge slip"), "plate": ("100",)})
    assert r.status_code == 200, r.text
    d = r.json()
    by = {l["item_code"].split("-")[1]: l for l in d["lines"]}
    assert (by["CEMENT"]["system_qty"], by["CEMENT"]["counted_qty"], by["CEMENT"]["variance_qty"], by["CEMENT"]["variance_value"]) == ("5000.000", "4900.000", "-100.000", "-700.00")
    assert (by["STEEL"]["variance_qty"], by["STEEL"]["variance_value"]) == ("10.000", "620.00") and by["PLATE"]["variance_qty"] == "0.000" and d["variance_value"] == "-80.00"
    assert d["counted"] == 3
    move(tenant, "count", c["id"], "submit", "approve")
    assert balance(w, w.central, "cement")[0] == D("5000.000")                                          # nothing changes until posted
    posted = move(tenant, "count", c["id"], "post")
    assert posted["status"] == "POSTED" and posted["frozen"] is False
    assert balance(w, w.central, "cement") == (D("4900.000"), D("34300.00")) and balance(w, w.central, "steel") == (D("2010.000"), D("124620.00"))
    assert balance(w, w.central, "plate")[0] == D("100.000")
    with database.SessionLocal() as s:
        rows = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "COUNT", DBStoreStockLedger.ref_doc_id == c["id"]).order_by(DBStoreStockLedger.id).all()
        assert sorted((r.movement_type, r.qty_in or r.qty_out) for r in rows) == [("ADJUST_IN", D("10.000")), ("ADJUST_OUT", D("100.000"))]
        assert s.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == w.central, DBStoreFreeze.unfrozen_at.is_(None)).count() == 0
        got = store_control.get_count_variances(s, w.central, date.today() - timedelta(days=1), date.today())
        assert sorted((g.variance_qty, g.variance_value) for g in got) == [(D("-100.000"), D("-700.00")), (D("0.000"), D("0.00")), (D("10.000"), D("620.00"))]
    rep = tenant.get(API + "/count-variances", params={"store_id": w.central}).json()
    assert len(rep["items"]) == 2 and rep["net_value"] == "-80.00"                                      # only what differed
    post_movement_ok = tenant.post("%s/transfer" % API, json=transfer_body(w))
    assert post_movement_ok.status_code == 200
    assert move(tenant, "count", c["id"], "cancel")["status"] == "CANCELLED"                           # reverses the adjustments
    assert balance(w, w.central, "cement")[0] == D("5000.000") and balance(w, w.central, "steel")[0] == D("2000.000")


def test_a_blind_count_hides_the_books_from_those_without_the_right(account, portal):
    tenant = account["client"]
    w = world(account)
    c = make_count(tenant, w)
    tenant.post("%s/count/%d/start" % (API, c["id"]))
    staff(account, portal, ["store.control.view", "store.control.create"], [w.central])
    blind = portal.get("%s/count/%d" % (API, c["id"])).json()
    assert blind["revealed"] is False and blind["variance_value"] is None
    assert all(l["system_qty"] is None and l["variance_qty"] is None and l["avg_rate"] is None for l in blind["lines"])
    r = sheet(portal, c, w, {"cement": ("4900", "short")})
    assert r.status_code == 200 and all(l["system_qty"] is None for l in r.json()["lines"])
    assert [l["counted_qty"] for l in r.json()["lines"] if "CEMENT" in l["item_code"]] == ["4900.000"]
    staff(account, portal, ["store.control.view", "store.control.reveal_count"], [w.central])
    seen = portal.get("%s/count/%d" % (API, c["id"])).json()
    assert seen["revealed"] is True and any(l["system_qty"] == "5000.000" for l in seen["lines"])
    assert tenant.get("%s/count/%d" % (API, c["id"])).json()["revealed"] is True                       # the account holder holds every right


def test_every_difference_needs_a_reason_and_a_count_can_be_redone(account):
    tenant = account["client"]
    w = world(account)
    c = make_count(tenant, w)
    tenant.post("%s/count/%d/start" % (API, c["id"]))
    sheet(tenant, c, w, {"cement": ("4900",), "steel": ("2000",), "plate": ("100",)})
    res = tenant.post("%s/count/%d/submit" % (API, c["id"]))
    assert res.status_code == 409 and "Say why Cement OPC differs" in res.json()["detail"]
    assert sheet(tenant, c, w, {"cement": ("5000",)}).status_code == 200                                # recounted: no difference, so no reason needed
    assert move(tenant, "count", c["id"], "submit")["status"] == "SUBMITTED"
    done = move(tenant, "count", c["id"], "approve", "post")
    assert done["status"] == "POSTED" and balance(w, w.central, "cement")[0] == D("5000.000")
    with database.SessionLocal() as s:
        assert s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "COUNT").count() == 0      # nothing to adjust
    assert move(tenant, "count", c["id"], "cancel")["status"] == "CANCELLED"                          # and nothing to reverse


def test_an_item_found_that_the_books_do_not_have_needs_a_rate(account):
    tenant = account["client"]
    w = world(account)
    c = make_count(tenant, w)
    tenant.post("%s/count/%d/start" % (API, c["id"]))
    sheet(tenant, c, w, {"cement": ("5000",), "steel": ("2000",), "plate": ("100",)})
    res = sheet(tenant, c, w, {"sand": ("12",)})
    assert res.status_code == 400 and "give the rate" in res.json()["detail"]
    ok = tenant.put("%s/count/%d/sheet" % (API, c["id"]), json={"rows": [{"item_id": w.item["sand"], "counted_qty": "12", "reason": "found behind the shed", "rate": "1800"}]})
    assert ok.status_code == 200 and [l for l in ok.json()["lines"] if "SAND" in l["item_code"]][0]["in_snapshot"] is False
    move(tenant, "count", c["id"], "submit", "approve", "post")
    assert balance(w, w.central, "sand") == (D("12.000"), D("21600.00"))


def test_a_partial_count_covers_only_the_items_chosen(account):
    tenant = account["client"]
    w = world(account)
    assert tenant.post(API + "/count", json={"store_id": w.central, "count_date": TODAY, "count_type": "PARTIAL"}).status_code == 400
    assert tenant.post(API + "/count", json={"store_id": w.central, "count_date": TODAY, "count_type": "WEIRD"}).status_code == 400
    c = make_count(tenant, w, count_type="PARTIAL", item_ids=[w.item["cement"], w.item["cement"]])
    assert c["line_count"] == 1
    started = tenant.post("%s/count/%d/start" % (API, c["id"])).json()
    assert started["lines"][0]["system_qty"] == "5000.000"
    assert sheet(tenant, c, w, {"steel": ("1",)}).status_code == 400
    assert sheet(tenant, c, w, {"cement": ("5000",)}).status_code == 200


def test_cancelling_an_open_count_lets_the_store_move_and_a_second_count_waits(account):
    tenant = account["client"]
    w = world(account)
    c = make_count(tenant, w)
    tenant.post("%s/count/%d/start" % (API, c["id"]))
    other = make_count(tenant, w)
    res = tenant.post("%s/count/%d/start" % (API, other["id"]))
    assert res.status_code == 409 and "already frozen" in res.json()["detail"]
    assert tenant.delete("%s/count/%d" % (API, c["id"])).status_code == 409                        # started: cancel, do not delete
    assert move(tenant, "count", c["id"], "cancel")["frozen"] is False
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=w.central, item_id=w.item["cement"], qty=D("1"), rate=None, txn_date=date.today(), project_id=None,
                      ref_doc_type="ISSUE", ref_doc_id=11, ref_line_id=1, user_id=None)
        s.commit()
    assert tenant.post("%s/count/%d/start" % (API, other["id"])).status_code == 200
    assert tenant.delete("%s/count/%d" % (API, make_count(tenant, w)["id"])).status_code == 200


def test_a_high_value_count_needs_the_right_to_approve_it(account, portal):
    tenant = account["client"]
    w = world(account)
    c = make_count(tenant, w, count_type="PARTIAL", item_ids=[w.item["steel"]])
    tenant.post("%s/count/%d/start" % (API, c["id"]))
    sheet(tenant, c, w, {"steel": ("1000", "stolen from the yard")})                                   # 1000 kg short = 62,000
    move(tenant, "count", c["id"], "submit")
    staff(account, portal, ["store.control.view", "store.control.approve"], [w.central])
    res = portal.post("%s/count/%d/approve" % (API, c["id"]))
    assert res.status_code == 403 and "high-value" in res.json()["detail"]
    staff(account, portal, ["store.control.view", "store.control.approve", "store.control.approve_high_value"], [w.central])
    assert portal.post("%s/count/%d/approve" % (API, c["id"])).status_code == 200


# --- wastage and scrap --------------------------------------------------------------------------------------------------------------

def scrap_body(w, lines=None, **over):
    lines = lines if lines is not None else [{"item_id": w.item["steel"], "qty": "100", "uom": "kg", "disposal": "SCRAP", "reason": "cut-offs", "realised_value": "4000"}]
    return {"store_id": w.central, "scrap_date": TODAY, "project_id": w.proj_a, "buyer": "Gupta Scrap Traders", "reference": "GP-12", "lines": lines, **over}


def make_scrap(tenant, w, **kw):
    res = tenant.post(API + "/scrap", json=scrap_body(w, **kw))
    assert res.status_code == 200, res.text
    return res.json()


def test_scrap_is_written_off_at_book_value_and_the_sale_is_recorded(account):
    tenant = account["client"]
    w = world(account)
    s1 = make_scrap(tenant, w, lines=[{"item_id": w.item["steel"], "qty": "100", "uom": "kg", "disposal": "SCRAP", "reason": "cut-offs", "realised_value": "4000"},
                                       {"item_id": w.item["cement"], "qty": "4", "uom": "bag", "disposal": "WASTAGE", "reason": "set in the bag", "cost_head": "overhead"}])
    assert s1["number"].startswith("SCRAP/") and s1["realised"] == "4000.00" and s1["lines"][1]["cost_head"] == "OVERHEAD"
    move(tenant, "scrap", s1["id"], "submit", "approve", "post")
    assert balance(w, w.central, "steel") == (D("1900.000"), D("117800.00")) and balance(w, w.central, "cement")[0] == D("4800.000")
    with database.SessionLocal() as s:
        rows = {r.movement_type: r for r in s.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "SCRAP").all()}
        assert (rows["SCRAP_OUT"].value, rows["SCRAP_OUT"].project_id) == (D("6200.00"), w.proj_a) and (rows["WASTAGE_OUT"].cost_head, rows["WASTAGE_OUT"].value) == ("OVERHEAD", D("1400.00"))
        got = store_control.get_scrap_realisation(s, w.proj_a, date.today() - timedelta(days=1), date.today())
        assert len(got) == 1 and (got[0].qty, got[0].book_value, got[0].realised_value) == (D("100.000"), D("6200.00"), D("4000.00"))      # wastage is not scrap
        assert store_control.get_scrap_realisation(s, w.proj_b, date.today() - timedelta(days=1), date.today()) == []
    rep = tenant.get(API + "/scrap-realisation", params={"project_id": w.proj_a}).json()
    assert (rep["book_value"], rep["realised_value"]) == ("6200.00", "4000.00") and rep["items"][0]["gain"] == "-2200.00"
    assert tenant.get(API + "/scrap-realisation", params={"project_id": 999999}).status_code == 404
    assert move(tenant, "scrap", s1["id"], "cancel")["status"] == "CANCELLED"
    assert balance(w, w.central, "steel")[0] == D("2000.000") and balance(w, w.central, "cement")[0] == D("5000.000")
    with database.SessionLocal() as s:
        assert store_control.get_scrap_realisation(s, w.proj_a, date.today() - timedelta(days=1), date.today()) == []


def test_bad_scrap_is_refused_in_words(account):
    tenant = account["client"]
    w = world(account)
    s, c = w.item["steel"], w.item["cement"]
    line = {"item_id": s, "qty": "1", "uom": "kg", "disposal": "SCRAP", "reason": "x"}
    bad = [
        ({"lines": []}, "at least one line"),
        ({"lines": [{**line, "reason": ""}]}, "give the reason"),
        ({"lines": [{**line, "disposal": "GIFT"}]}, "SCRAP or WASTAGE"),
        ({"lines": [{**line, "disposal": "WASTAGE", "realised_value": "50"}]}, "wastage fetches nothing"),
        ({"lines": [{**line, "realised_value": "-5"}]}, "zero or more"),
        ({"lines": [{**line, "cost_head": "LUNCH"}]}, "cost head must be"),
        ({"lines": [{**line, "writeoff_request_id": 12345}]}, "write-off request is not open"),
        ({"lines": [{**line, "qty": "0"}]}, "more than zero"),
        ({"project_id": 999999}, "project does not exist"),
        ({"scrap_date": "2999-01-01"}, "future"),
        ({"store_id": 999999}, "store does not exist"),
    ]
    for over, word in bad:
        res = tenant.post(API + "/scrap", json=scrap_body(w, **over))
        assert res.status_code in (400, 409) and word.lower() in res.json()["detail"].lower(), (over, res.text)
    big = make_scrap(tenant, w, lines=[{"item_id": c, "qty": "5001", "uom": "kg", "disposal": "WASTAGE", "reason": "flood"}])
    res = tenant.post("%s/scrap/%d/submit" % (API, big["id"]))
    assert res.status_code == 409 and "on hand" in res.json()["detail"]


def test_scrap_can_deal_with_an_outward_write_off_request(account, monkeypatch):
    tenant = account["client"]
    w = world(account)
    from app.schemas.store_contracts import WriteOffRequest
    closed = []
    request = WriteOffRequest(request_id=41, store_id=w.central, item_id=w.item["plate"], qty=D("6"), reason="fell from scaffold", source_issue_line_id=None, status="OPEN")
    monkeypatch.setattr(store_outward, "list_writeoff_requests", lambda db, status="OPEN": [request])
    monkeypatch.setattr(store_outward, "close_writeoff_request", lambda db, rid, rtype, rid2, uid: closed.append((rid, rtype, rid2, uid)))
    assert tenant.get(API + "/pick/writeoffs", params={"store_id": w.central}).json()["items"][0]["id"] == 41
    assert tenant.get(API + "/pick/writeoffs", params={"store_id": w.site_a}).json()["items"] == []
    line = {"item_id": w.item["plate"], "qty": "6", "disposal": "WASTAGE", "reason": "lost on site", "writeoff_request_id": 41}
    wrong_item = tenant.post(API + "/scrap", json=scrap_body(w, lines=[{**line, "item_id": w.item["steel"], "uom": "kg"}]))
    assert wrong_item.status_code == 400
    assert tenant.post(API + "/scrap", json=scrap_body(w, lines=[{**line, "qty": "7"}])).status_code == 400        # more than the request
    s = make_scrap(tenant, w, lines=[line])
    move(tenant, "scrap", s["id"], "submit", "approve", "post")
    assert closed == [(41, "SCRAP", s["id"], None)]
    assert balance(w, w.central, "plate")[0] == D("100.000")                          # no stock moved: the lost tools left the store when they were issued
    with database.SessionLocal() as sess:
        assert sess.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "SCRAP", DBStoreStockLedger.ref_doc_id == s["id"]).count() == 0
    res = tenant.post("%s/scrap/%d/cancel" % (API, s["id"]), json={"reason": "my mistake"})
    assert res.status_code == 409 and "cannot be reopened" in res.json()["detail"]
    # it can sit beside a line that does write stock off, and only that line moves it
    mixed = make_scrap(tenant, w, lines=[line, {"item_id": w.item["cement"], "qty": "10", "uom": "kg", "disposal": "WASTAGE", "reason": "spilt"}])
    move(tenant, "scrap", mixed["id"], "submit", "approve", "post")
    assert balance(w, w.central, "cement")[0] == D("4990.000") and balance(w, w.central, "plate")[0] == D("100.000")
    assert closed[-1] == (41, "SCRAP", mixed["id"], None) and len(closed) == 2


# --- rights, tenancy, pickers, printing -------------------------------------------------------------------------------------------

def test_a_transfer_can_be_sent_to_a_store_the_sender_does_not_work_in(account, portal):
    tenant = account["client"]
    w = world(account)
    staff(account, portal, ["store.control.view", "store.control.create", "store.control.approve", "store.control.post"], [w.central])
    assert {s["id"] for s in portal.get(API + "/pick/stores").json()["items"]} == {w.central, w.site_a, w.site_b}      # all of the company's
    assert portal.get("/api/store/lookup/stores").json()["stores"][0]["id"] == w.central                                           # the shared picker is not enough
    res = portal.post(API + "/transfer", json=transfer_body(w, to_store_id=w.site_b))
    assert res.status_code == 200, res.text
    for step in ("submit", "approve", "post"):
        assert portal.post("%s/transfer/%d/%s" % (API, res.json()["id"], step)).status_code == 200
    assert portal.post("%s/transfer/%d/receive" % (API, res.json()["id"])).status_code == 403          # receiving needs the destination
    assert tenant.post("%s/transfer/%d/receive" % (API, res.json()["id"])).status_code == 200


def test_each_step_needs_its_own_right_and_a_viewer_only_looks(account, portal):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    staff(account, portal, ["store.control.view", "store.control.create"], [w.central])
    assert portal.post("%s/transfer/%d/submit" % (API, t["id"])).status_code == 200
    for step in ("approve", "post"):
        assert portal.post("%s/transfer/%d/%s" % (API, t["id"], step)).status_code == 403
    assert portal.post("%s/transfer/%d/cancel" % (API, t["id"]), json={"reason": "no way"}).status_code == 403
    staff(account, portal, ["store.control.view"], [w.central])
    assert portal.get(API + "/transfer").json()["total"] == 1 and portal.get(API + "/in-transit").status_code == 200
    assert portal.post(API + "/transfer", json=transfer_body(w)).status_code == 403
    assert portal.post(API + "/count", json={"store_id": w.central, "count_date": TODAY}).status_code == 403
    assert portal.post(API + "/scrap", json=scrap_body(w)).status_code == 403
    assert portal.delete("%s/transfer/%d" % (API, t["id"])).status_code == 403


def test_staff_work_only_in_their_own_stores(account, portal):
    tenant = account["client"]
    w = world(account)
    t_central = make_transfer(tenant, w)
    c_central = make_count(tenant, w)
    staff(account, portal, ["store.control.view", "store.control.create"], [w.site_b])
    assert portal.get(API + "/transfer").json()["total"] == 0 and portal.get(API + "/count").json()["total"] == 0
    assert portal.get("%s/transfer/%d" % (API, t_central["id"])).status_code == 403
    assert portal.post("%s/transfer/%d/submit" % (API, t_central["id"])).status_code == 403
    assert portal.post(API + "/transfer", json=transfer_body(w)).status_code == 403                  # wrong-store access
    assert portal.post(API + "/count", json={"store_id": w.central, "count_date": TODAY}).status_code == 403
    assert portal.post("%s/count/%d/start" % (API, c_central["id"])).status_code == 403
    assert portal.post(API + "/scrap", json=scrap_body(w)).status_code == 403
    assert portal.get(API + "/transfer", params={"store_id": w.central}).status_code == 403
    assert portal.get(API + "/count-variances", params={"store_id": w.central}).status_code == 403
    assert portal.get("%s/transfer/%d/print" % (API, t_central["id"])).status_code == 403
    assert portal.post(API + "/transfer", json=transfer_body(w, store_id=w.site_b, to_store_id=w.site_a, lines=[{"item_id": w.item["cement"], "qty": "1", "uom": "bag"}])).status_code == 200


def test_one_company_cannot_reach_anothers_documents(account, second_tenant):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    c = make_count(tenant, w)
    for path in ("transfer/%d" % t["id"], "count/%d" % c["id"], "transfer/%d/print" % t["id"]):
        assert second_tenant.get("%s/%s" % (API, path)).status_code == 404, path
    assert second_tenant.post("%s/transfer/%d/submit" % (API, t["id"])).status_code == 404
    assert second_tenant.post("%s/transfer/%d/receive" % (API, t["id"])).status_code == 404
    assert second_tenant.post("%s/count/%d/start" % (API, c["id"])).status_code == 404
    assert second_tenant.get(API + "/transfer").json()["total"] == 0 and second_tenant.get(API + "/in-transit").json()["total"] == 0
    assert second_tenant.get(API + "/count-variances", params={"store_id": w.central}).status_code == 404
    assert second_tenant.get(API + "/scrap-realisation", params={"project_id": w.proj_a}).status_code == 404
    assert second_tenant.get(API + "/nonsense").status_code == 404
    assert tenant.get(API).json()["slice"] == "control"


def test_every_document_prints_and_the_lists_export(account):
    tenant = account["client"]
    w = world(account)
    t = make_transfer(tenant, w)
    dispatched = make_transfer(tenant, w)
    move(tenant, "transfer", dispatched["id"], "submit", "approve", "post")
    c = make_count(tenant, w)
    tenant.post("%s/count/%d/start" % (API, c["id"]))
    s = make_scrap(tenant, w)
    for kind, doc in (("transfer", t), ("transfer", dispatched), ("count", c), ("scrap", s)):
        res = tenant.get("%s/%s/%d/print" % (API, kind, doc["id"]))
        assert res.status_code == 200 and res.content[:4] == b"%PDF", (kind, res.text[:200])
    for kind in ("transfer", "count", "scrap"):
        xl = tenant.get("%s/%s/export" % (API, kind))
        assert xl.status_code == 200 and "spreadsheetml" in xl.headers["content-type"] and openpyxl.load_workbook(io.BytesIO(xl.content)).active.max_row >= 2
