"""P1 - store masters and stock enquiry over HTTP: setup, stock position, ledger, freeze, access and rights."""
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
from app.services.stock_ledger import post_movement

D = Decimal
M, E = "/api/store/masters", "/api/store/enquiry"


@pytest.fixture(autouse=True)
def _clean_store_rows(account):
    """Item and store ids are reused between tests on SQLite; leave no store rows behind for the next test to collide with."""
    yield
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        stores = [i for (i,) in s.query(DBStore.id).filter(DBStore.client_id == cid).all()]
        items = [i for (i,) in s.query(models.DBItem.id).filter(models.DBItem.client_id == cid).all()]
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreStockBalance, DBStoreFreeze, DBStoreUserAssignment, DBStoreBin):
            s.query(model).filter(model.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreUomConversion, DBStoreItemSettings):
            s.query(model).filter(model.item_id.in_(items)).delete(synchronize_session=False)
        s.query(DBStore).filter(DBStore.id.in_(stores)).delete(synchronize_session=False)
        s.commit()


def _store(owner, code="HQ1", **kw):
    res = owner.post(M + "/stores", json={"code": code, "name": "Head Store", "type": "CENTRAL", **kw})
    assert res.status_code == 201, res.text
    return res.json()


def _item(owner_id, name="Cement", unit="kg"):
    with database.SessionLocal() as s:
        it = models.DBItem(client_id=owner_id, kind="RM", item_code="E-%s" % uuid.uuid4().hex[:8], item_name=name, units_of_measure=unit)
        s.add(it)
        s.commit()
        return it.id


def _owner_id(account):
    with database.SessionLocal() as s:
        return s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id


def _post(store_id, item_id, mtype, qty, rate=None, doc=1):
    with database.SessionLocal() as s:
        post_movement(s, movement_type=mtype, store_id=store_id, item_id=item_id, qty=D(qty), rate=D(rate) if rate else None,
                      txn_date=date.today(), project_id=None, ref_doc_type="GRN" if rate else "ISSUE", ref_doc_id=doc, ref_line_id=1, user_id=None)
        s.commit()


def _staff(account, portal, rights, stores=()):
    email = "keeper-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in stores])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    return emp["id"]


def test_store_bin_and_assignment_setup(account):
    o = account["client"]
    s = _store(o)
    assert s["code"] == "HQ1" and s["is_active"]
    assert o.post(M + "/stores", json={"code": "hq1", "name": "Dup"}).status_code == 409           # codes are unique, case aside
    assert o.post(M + "/stores", json={"code": "X", "name": "Bad", "type": "MOON"}).status_code == 400
    assert o.put("%s/stores/%d" % (M, s["id"]), json={"name": "Renamed", "code": "ZZZ"}).json()["code"] == "HQ1"   # code never changes

    b = o.post("%s/stores/%d/bins" % (M, s["id"]), json={"code": "a-1", "description": "Cement shed"})
    assert b.status_code == 201 and b.json()["code"] == "A-1"
    assert o.post("%s/stores/%d/bins" % (M, s["id"]), json={"code": "A-1"}).status_code == 409
    assert [x["code"] for x in o.get("%s/stores/%d/bins" % (M, s["id"])).json()["bins"]] == ["A-1"]

    emp = make_employee(o)
    a = o.post("%s/stores/%d/assignments" % (M, s["id"]), json={"employee_id": emp["id"], "role": "KEEPER"})
    assert a.status_code == 201 and a.json()["role"] == "KEEPER"
    assert o.post("%s/stores/%d/assignments" % (M, s["id"]), json={"employee_id": 999999}).status_code == 404
    assert o.delete("%s/assignments/%d" % (M, a.json()["id"])).json()["is_active"] is False
    assert o.get(M + "/summary").json()["stores"] == 1


def test_item_settings_and_conversions(account):
    o = account["client"]
    cid = _owner_id(account)
    item = _item(cid)
    row = [r for r in o.get(M + "/items").json()["items"] if r["item_id"] == item][0]
    assert row["configured"] is False and row["base_uom"] == "kg"
    res = o.put("%s/items/%d/settings" % (M, item), json={"category": "CONSUMABLE", "reorder_level": "50", "min_qty": "10", "max_qty": "500"})
    assert res.status_code == 200 and res.json()["reorder_level"] == "50.000" and res.json()["configured"]
    assert o.put("%s/items/%d/settings" % (M, item), json={"min_qty": "600", "max_qty": "500"}).status_code == 400
    assert o.put("%s/items/%d/settings" % (M, item), json={"category": "JUNK"}).status_code == 400
    assert o.put("%s/items/%d/settings" % (M, item), json={"reorder_level": "-1"}).status_code == 400

    c = o.post("%s/items/%d/uoms" % (M, item), json={"from_uom": "bag", "to_base_factor": "50"})
    assert c.status_code == 201
    assert o.post("%s/items/%d/uoms" % (M, item), json={"from_uom": "kg", "to_base_factor": "1"}).status_code == 400    # the base unit
    assert o.post("%s/items/%d/uoms" % (M, item), json={"from_uom": "t", "to_base_factor": "0"}).status_code == 400
    o.post("%s/items/%d/uoms" % (M, item), json={"from_uom": "BAG", "to_base_factor": "40"})                                # replaces
    convs = o.get("/api/store/lookup/items/%d/uoms" % item).json()["uoms"]
    assert [(u["code"], u["to_base_factor"]) for u in convs] == [("kg", 1.0), ("bag", 40.0)]
    assert o.delete("%s/uoms/%d" % (M, c.json()["id"])).json()["deleted"]
    assert o.get(M + "/items", params={"configured": "true"}).json()["total"] == 1


def test_base_unit_is_locked_once_stock_exists(account):
    o = account["client"]
    item = _item(_owner_id(account))
    s = _store(o)
    o.put("%s/items/%d/settings" % (M, item), json={"base_uom": "kg"})
    _post(s["id"], item, MovementType.OPENING_IN, "10", "5")
    assert o.put("%s/items/%d/settings" % (M, item), json={"base_uom": "bag"}).status_code == 409
    assert o.put("%s/stores/%d" % (M, s["id"]), json={"is_active": False}).status_code == 409      # still holds stock


def test_stock_position_and_ledger(account):
    o = account["client"]
    s1, s2 = _store(o), _store(o, "YD1", type="YARD")
    item = _item(_owner_id(account))
    o.put("%s/items/%d/settings" % (M, item), json={"reorder_level": "100"})
    _post(s1["id"], item, MovementType.GRN_IN, "500", "8", doc=1)
    _post(s1["id"], item, MovementType.ISSUE_OUT, "420", doc=2)
    _post(s2["id"], item, MovementType.GRN_IN, "50", "9", doc=3)

    rows = o.get(E + "/stock").json()
    assert rows["total"] == 2 and rows["total_value"] == "1090.00"        # 80 @ 8 + 50 @ 9
    first = [r for r in rows["rows"] if r["store_id"] == s1["id"]][0]
    assert (first["qty"], first["value"], first["below_reorder"]) == ("80.000", "640.00", True)
    assert o.get(E + "/stock", params={"below_reorder": "true"}).json()["total"] == 2
    assert o.get(E + "/stock", params={"store_id": s2["id"]}).json()["total"] == 1

    led = o.get(E + "/ledger", params={"store_id": s1["id"], "item_id": item}).json()
    assert led["total"] == 2 and led["rows"][0]["movement_type"] == "ISSUE_OUT" and led["rows"][0]["running_qty"] == "80.000"
    assert o.get(E + "/ledger", params={"movement_type": "GRN_IN"}).json()["total"] == 2
    assert o.get(E + "/ledger", params={"movement_type": "NOPE"}).status_code == 400
    assert o.get(E + "/ledger", params={"from_date": "garbage"}).status_code == 400
    assert o.get(E + "/ledger", params={"from_date": "2999-01-01"}).json()["total"] == 0

    pos = o.get("%s/items/%d" % (E, item)).json()
    assert pos["total_qty"] == "130.000" and len(pos["stores"]) == 2 and pos["used_last_30_days"] == "420.000"


def test_freeze_and_unfreeze(account):
    o = account["client"]
    s = _store(o)
    item = _item(_owner_id(account))
    _post(s["id"], item, MovementType.OPENING_IN, "10", "5")
    assert o.post("%s/stores/%d/freeze" % (M, s["id"]), json={}).status_code == 400                  # a reason is needed
    assert o.post("%s/stores/%d/freeze" % (M, s["id"]), json={"reason": "annual count"}).json()["frozen"]
    assert o.post("%s/stores/%d/freeze" % (M, s["id"]), json={"reason": "again"}).status_code == 400
    assert o.get(M + "/stores").json()["stores"][0]["frozen"] is True
    assert o.get(E + "/stock").json()["frozen_store_ids"] == [s["id"]]
    assert o.post("%s/stores/%d/unfreeze" % (M, s["id"])).json()["frozen"] is False
    assert o.post("%s/stores/%d/unfreeze" % (M, s["id"])).status_code == 400
    assert len(o.get("%s/stores/%d/freezes" % (M, s["id"])).json()["freezes"]) == 1


def test_rights_and_store_access(account, portal):
    o = account["client"]
    mine, other = _store(o, "MY1"), _store(o, "OT1")
    item = _item(_owner_id(account))
    _post(mine["id"], item, MovementType.OPENING_IN, "10", "5")
    _post(other["id"], item, MovementType.OPENING_IN, "20", "5", doc=2)

    _staff(account, portal, ["store.masters.view", "store.enquiry.view"], stores=[mine["id"]])
    assert portal.get(M + "/stores").json()["stores"][0]["code"] == "MY1" and len(portal.get(M + "/stores").json()["stores"]) == 1
    assert portal.get(E + "/stock").json()["total"] == 1                                              # only their store's stock
    assert portal.get(E + "/stock", params={"store_id": other["id"]}).status_code == 403              # wrong store
    assert portal.get("%s/stores/%d/bins" % (M, other["id"])).status_code == 403
    assert portal.get(E + "/ledger", params={"store_id": other["id"]}).status_code == 403
    # view only: no create, no freeze, no assignment, no switching off
    assert portal.post(M + "/stores", json={"code": "NEW", "name": "New"}).status_code == 403
    assert portal.post("%s/stores/%d/freeze" % (M, mine["id"]), json={"reason": "x"}).status_code == 403
    assert portal.put("%s/items/%d/settings" % (M, item), json={}).status_code == 403
    assert portal.delete("%s/uoms/1" % M).status_code == 403


def test_staff_without_any_store_right_is_refused(account, portal):
    _staff(account, portal, ["store.inward.view"])
    assert portal.get(M).status_code == 403 and portal.get(E + "/stock").status_code == 403
    assert portal.get(M + "/stores").status_code == 403
