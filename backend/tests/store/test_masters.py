"""P1 masters over HTTP: stores, bins, who works where, item settings, unit conversions, and opening stock - typed or
from a sheet - through draft, submit, approve, post and cancel. Rights and store access are checked on every route."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import main
from app import models
from app.core import passwords
from app.models.store_core import DBStoreDocStatusLog, DBStoreOpening, DBStoreOpeningLine, DBStoreStockLedger
from app.services.stock_ledger import get_balance, post_movement
from store.fixtures import db, store_world  # noqa: F401  (fixtures)

D = Decimal
TODAY = date.today()
PASSWORD = "Store1234!"


@pytest.fixture
def world(db, store_world):
    """store_world, plus clearing away the opening documents P1's tests make (store_world's own teardown does not
    know of them, and Postgres would refuse to drop the stores beneath them)."""
    yield store_world
    db.rollback()
    ids = [d.id for d in db.query(DBStoreOpening).filter(DBStoreOpening.client_id == store_world.client_id)]
    if ids:
        db.query(DBStoreOpeningLine).filter(DBStoreOpeningLine.opening_id.in_(ids)).delete(synchronize_session=False)
    db.query(DBStoreOpening).filter(DBStoreOpening.client_id == store_world.client_id).delete(synchronize_session=False)
    db.query(DBStoreDocStatusLog).filter(DBStoreDocStatusLog.client_id == store_world.client_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def sign_in(db, world):
    """sign_in("central_keeper") / sign_in("owner") -> a browser signed in as that person. sign_in(who, rights=[...])
    first gives the member of staff those rights on top of what they hold."""
    browsers = []

    def go(who, rights=None):
        c = TestClient(main.app)
        c.__enter__()
        browsers.append(c)
        if who == "owner":
            owner = db.get(models.DBClient, world.client_id)
            owner.password_hash = passwords.hash_password(PASSWORD)
            db.commit()
            res = c.post("/api/client/login", json={"email": owner.email, "password": PASSWORD})
        else:
            emp = db.get(models.DBEmployee, world.staff[who])
            emp.password_hash = passwords.hash_password(PASSWORD)
            if rights:
                emp.extra_permissions = ",".join(sorted((set((emp.extra_permissions or "").split(",")) | set(rights)) - {""}))
            db.commit()
            res = c.post("/api/employee/auth/login", json={"email": emp.email, "password": PASSWORD})
        assert res.status_code == 200, res.text
        return c
    yield go
    for c in browsers:
        c.__exit__(None, None, None)


def ok(res, code=200):
    assert res.status_code == code, res.text
    return res.json()


M = "/api/store/masters"


# --- stores, bins, people ------------------------------------------------------------------------------------------

def test_the_owner_sets_up_stores(world, sign_in):
    w, owner = world, sign_in("owner")
    listed = ok(owner.get(M + "/stores"))["stores"]
    assert [x["code"] for x in listed] == ["CS01", "ST01"]
    assert listed[1]["project_id"] == w.project_id and listed[1]["project"].endswith("Tower A") and listed[0]["bins"] == 1
    yard = ok(owner.post(M + "/stores", json={"code": "yd01", "name": "Steel yard", "type": "YARD"}))
    assert yard["code"] == "YD01" and yard["accessible"] is True
    assert owner.post(M + "/stores", json={"code": "YD01", "name": "Again", "type": "YARD"}).status_code == 409
    assert owner.post(M + "/stores", json={"code": "Y D/1", "name": "Bad", "type": "YARD"}).status_code == 400
    assert "project" in owner.post(M + "/stores", json={"code": "ST02", "name": "Site", "type": "SITE"}).json()["detail"]
    site = ok(owner.post(M + "/stores", json={"code": "ST02", "name": "Site 2", "type": "SITE", "project_id": w.project_id}))
    assert site["project_id"] == w.project_id
    assert owner.post(M + "/stores", json={"code": "BAD1", "name": "x", "type": "TENT"}).status_code == 422
    # a store that has numbered documents keeps its code; an empty one can be renamed and closed
    assert owner.put(M + "/stores/%d" % w.central_id, json={"code": "CS99"}).status_code == 409
    assert ok(owner.put(M + "/stores/%d" % yard["id"], json={"code": "YD02", "name": "Yard"}))["code"] == "YD02"
    assert owner.put(M + "/stores/%d" % w.central_id, json={"is_active": False}).status_code == 409   # it holds stock
    assert ok(owner.put(M + "/stores/%d" % yard["id"], json={"is_active": False}))["is_active"] is False
    assert [x["code"] for x in ok(owner.get(M + "/stores"))["stores"]] == ["CS01", "ST01", "ST02"]
    assert ok(owner.get(M))["slice"] == "masters"


def test_bins(world, sign_in):
    w, owner = world, sign_in("owner")
    b = ok(owner.post(M + "/stores/%d/bins" % w.central_id, json={"code": "b-02", "description": "Steel rack"}))
    assert b["code"] == "B-02"
    assert owner.post(M + "/stores/%d/bins" % w.central_id, json={"code": "A-01"}).status_code == 409
    assert ok(owner.put(M + "/bins/%d" % b["id"], json={"is_active": False}))["is_active"] is False
    assert [x["code"] for x in ok(owner.get(M + "/stores/%d/bins" % w.central_id))["bins"]] == ["A-01", "B-02"]


def test_assigning_staff_is_what_opens_a_store_to_them(world, sign_in, db):
    w, owner = world, sign_in("owner")
    keeper = sign_in("unassigned", rights=["store.masters.view"])
    assert keeper.get(M + "/stores/%d/bins" % w.central_id).status_code == 403
    a = ok(owner.post(M + "/stores/%d/users" % w.central_id, json={"employee_id": w.staff["unassigned"], "role": "site_engineer"}))
    assert a["role"] == "SITE_ENGINEER" and a["is_active"]
    assert keeper.get(M + "/stores/%d/bins" % w.central_id).status_code == 200
    assert "CS01" in [x["code"] for x in keeper.get("/api/store/lookup/stores").json()["stores"]]
    ok(owner.put(M + "/assignments/%d" % a["id"], json={"is_active": False}))
    assert keeper.get(M + "/stores/%d/bins" % w.central_id).status_code == 403
    assert owner.post(M + "/stores/%d/users" % w.central_id, json={"employee_id": w.staff["viewer"], "role": "BOSS"}).status_code == 400
    names = [u["name"] for u in ok(owner.get(M + "/stores/%d/users" % w.central_id))["users"]]
    assert "Central Keeper Test" in names and "Unassigned Test" in names
    assert any(e["id"] == w.staff["viewer"] for e in ok(owner.get(M + "/employees?q=viewer"))["employees"])


def test_rights_and_store_access_are_checked(world, sign_in):
    w = world
    viewer = sign_in("viewer")                                         # no store.masters.view at all
    assert viewer.get(M + "/stores").status_code == 403
    keeper = sign_in("central_keeper")                                 # may look, may not set up
    assert keeper.get(M + "/stores").status_code == 200
    assert keeper.post(M + "/stores", json={"code": "ZZ01", "name": "x"}).status_code == 403
    assert keeper.put(M + "/items/%d/settings" % w.item["sand"], json={"base_uom": "cum"}).status_code == 403
    assert keeper.get(M + "/stores/%d/bins" % w.site_id).status_code == 403          # not their store
    site = sign_in("site_keeper", rights=["store.masters.create"])
    assert site.post(M + "/stores/%d/bins" % w.central_id, json={"code": "X"}).status_code == 403
    assert site.post(M + "/stores/%d/users" % w.central_id, json={"employee_id": w.staff["site_keeper"]}).status_code == 403
    assert site.post(M + "/stores/%d/bins" % w.site_id, json={"code": "S-1"}).status_code == 200
    admin = sign_in("admin")                                           # store.admin: every store
    assert admin.post(M + "/stores/%d/bins" % w.site_id, json={"code": "S-2"}).status_code == 200


def test_another_companys_store_is_not_found(world, sign_in, second_tenant):
    w = world
    assert second_tenant.get(M + "/stores/%d/bins" % w.central_id).status_code == 404
    assert second_tenant.put(M + "/stores/%d" % w.central_id, json={"name": "mine"}).status_code == 404
    assert second_tenant.get(M + "/items/%d" % w.item["cement"]).status_code == 404


# --- items and units -----------------------------------------------------------------------------------------------

def _new_item(db, w, code, base="kg"):
    it = models.DBItem(client_id=w.client_id, kind="RM", item_code="%s-%d" % (code, w.client_id), item_name=code.title(), units_of_measure=base)
    db.add(it)
    db.commit()
    return it.id


def test_item_settings(world, sign_in, db):
    w, owner = world, sign_in("owner")
    listed = ok(owner.get(M + "/items?q=cement"))["items"]
    assert len(listed) == 1 and listed[0]["settings"]["base_uom"] == "kg" and listed[0]["has_stock_history"]
    body = {"category": "CONSUMABLE", "base_uom": "bag", "reorder_level": "10"}
    assert "cannot change" in owner.put(M + "/items/%d/settings" % w.item["cement"], json=body).json()["detail"]
    fresh = _new_item(db, w, "GROUT")
    assert ok(owner.get(M + "/items?configured=no"))["items"][0]["id"] == fresh
    saved = ok(owner.put(M + "/items/%d/settings" % fresh, json={"category": "SPARE", "base_uom": "kg", "reorder_level": "12.5",
                                                                   "min_qty": "5", "max_qty": "100", "qc_required": True}))
    assert saved["settings"]["reorder_level"] == "12.500" and saved["settings"]["category"] == "SPARE"
    assert owner.put(M + "/items/%d/settings" % fresh, json={"base_uom": "kg", "min_qty": "10", "max_qty": "5"}).status_code == 400
    assert owner.put(M + "/items/%d/settings" % fresh, json={"base_uom": "kg", "over_receipt_tolerance_pct": "101"}).status_code == 400
    assert owner.put(M + "/items/%d/settings" % fresh, json={"base_uom": "kg", "category": "GOLD"}).status_code == 422


def factors(res):
    return {u["code"]: u["to_base_factor"] for u in ok(res)["uoms"]}


def test_unit_presets_for_cement_steel_and_volume(world, sign_in, db):
    w, owner = world, sign_in("owner")
    bagged = _new_item(db, w, "CEMPPC", base="bag")
    ok(owner.put(M + "/items/%d/settings" % bagged, json={"base_uom": "bag"}))
    assert factors(owner.post(M + "/items/%d/uoms/preset" % bagged, json={"kind": "CEMENT"})) == {
        "bag": "1.000000", "kg": "0.020000", "MT": "20.000000"}
    bar = _new_item(db, w, "TMT20")
    got = factors(owner.post(M + "/items/%d/uoms/preset" % bar, json={"kind": "STEEL", "dia_mm": "20"}))
    assert got == {"kg": "1.000000", "nos": "29.629630", "MT": "1000.000000"}                    # 400/162 x 12
    got = factors(owner.post(M + "/items/%d/uoms/preset" % bar, json={"kind": "STEEL", "dia_mm": "20", "bar_length_m": "6"}))
    assert got["nos"] == "14.814815"                                                             # re-run brings it to the new bar
    sand = factors(owner.post(M + "/items/%d/uoms/preset" % w.item["sand"], json={"kind": "VOLUME"}))
    assert sand == {"cum": "1.000000", "cft": "0.028317"}
    assert owner.post(M + "/items/%d/uoms/preset" % w.item["sand"], json={"kind": "CEMENT"}).status_code == 400
    assert owner.post(M + "/items/%d/uoms/preset" % bar, json={"kind": "STEEL"}).status_code == 400   # no diameter
    w8 = ok(owner.get(M + "/steel-weight?dia_mm=12"))
    assert (w8["kg_per_m"], w8["kg_per_nos"]) == ("0.888889", "10.666667")


def test_conversions_by_hand(world, sign_in):
    w, owner = world, sign_in("owner")
    item = w.item["binding_wire"]
    got = ok(owner.post(M + "/items/%d/uoms" % item, json={"from_uom": "coil", "to_base_factor": "25"}))["uoms"]
    coil = next(u for u in got if u["code"] == "coil")
    assert owner.post(M + "/items/%d/uoms" % item, json={"from_uom": "COIL", "to_base_factor": "20"}).status_code == 409
    assert owner.post(M + "/items/%d/uoms" % item, json={"from_uom": "kg", "to_base_factor": "1"}).status_code == 400
    assert owner.post(M + "/items/%d/uoms" % item, json={"from_uom": "box", "to_base_factor": "0"}).status_code == 400
    assert factors(owner.put(M + "/uoms/%d" % coil["id"], json={"to_base_factor": "24.5"}))["coil"] == "24.500000"
    assert "coil" not in factors(owner.delete(M + "/uoms/%d" % coil["id"]))
    assert "bag" in factors(owner.get("/api/store/lookup/items/%d/uoms" % w.item["cement"]))


# --- opening stock -------------------------------------------------------------------------------------------------

def opening(client, w, lines, store=None, day=None, code=200):
    return ok(client.post(M + "/opening", json={"store_id": store or w.site_id, "opening_date": str(day or TODAY - timedelta(days=3)),
                                                "lines": lines}), code)


def act(client, doc, action, reason="", code=200):
    return ok(client.post(M + "/opening/%d/%s" % (doc["id"], action), json={"reason": reason}), code)


def test_opening_stock_from_draft_to_posted_and_back(world, sign_in, db):
    w = world
    clerk = sign_in("site_keeper", rights=["store.masters.create"])
    boss = sign_in("approver", rights=["store.masters.approve", "store.masters.post", "store.masters.cancel"])
    doc = opening(clerk, w, [{"item_id": w.item["cement"], "qty": "40", "uom": "bag", "rate": "350"},
                             {"item_id": w.item["tmt12"], "qty": "10", "uom": "nos", "rate": "661.33"},
                             {"item_id": w.item["sand"], "qty": "12.5", "rate": "1800", "remarks": "heap by gate"}])
    assert doc["number"].startswith("OPEN/ST01/") and doc["status"] == "DRAFT" and doc["source"] == "MANUAL"
    cement, steel, sand = doc["lines"]
    assert (cement["base_qty"], cement["base_uom"], cement["base_rate"], cement["value"]) == ("2000.000", "kg", "7.0000", "14000.00")
    assert (steel["base_qty"], steel["base_rate"], steel["value"]) == ("106.667", "61.9995", "6613.30")  # 6613.30 entered, kept to the paisa
    assert (sand["uom"], sand["value"]) == ("cum", "22500.00")
    assert doc["total_value"] == "43113.30"

    assert ok(clerk.put(M + "/opening/%d" % doc["id"], json={"remarks": "first count"}))["remarks"] == "first count"
    assert clerk.post(M + "/opening/%d/approve" % doc["id"]).status_code == 403             # not theirs to approve
    act(clerk, doc, "submit")
    assert clerk.put(M + "/opening/%d" % doc["id"], json={"remarks": "late"}).status_code == 409  # only a draft changes
    assert act(boss, doc, "post", code=409)["detail"].startswith("A submitted opening cannot be posted")
    act(boss, doc, "approve")
    assert get_balance(db, w.site_id, w.item["cement"]).qty == 0                            # nothing moves before posting
    posted = act(boss, doc, "post")
    assert posted["status"] == "POSTED" and posted["posted_at"]
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["cement"]) .qty == D("2000.000")
    assert get_balance(db, w.site_id, w.item["sand"]).value == D("22500.00")
    led = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_type == "OPENING_STOCK",
                                              DBStoreStockLedger.ref_doc_id == doc["id"]).all()
    assert {(e.movement_type, e.txn_date, e.project_id) for e in led} == {("OPENING_IN", TODAY - timedelta(days=3), w.project_id)}
    assert {e.user_id for e in led} == {w.staff["approver"]}
    assert [(t["from"], t["to"]) for t in posted["trail"]] == [(None, "DRAFT"), ("DRAFT", "SUBMITTED"),
                                                               ("SUBMITTED", "APPROVED"), ("APPROVED", "POSTED")]
    assert posted["trail"][1]["by"] == "Site Keeper Test" and posted["trail"][3]["by"] == "Approver Test"

    assert act(boss, doc, "cancel", code=400)["detail"].startswith("Say why")
    cancelled = act(boss, doc, "cancel", reason="counted twice")
    assert cancelled["status"] == "CANCELLED" and cancelled["cancel_reason"] == "counted twice"
    db.expire_all()
    assert get_balance(db, w.site_id, w.item["cement"]).qty == 0
    assert db.query(DBStoreStockLedger).filter(DBStoreStockLedger.ref_doc_id == doc["id"],
                                               DBStoreStockLedger.ref_doc_type == "OPENING_STOCK",
                                               DBStoreStockLedger.reversal_of_id.isnot(None)).count() == 3
    assert act(boss, doc, "cancel", reason="again", code=409)
    # cancelled, the items are free for a fresh opening
    again = opening(clerk, w, [{"item_id": w.item["cement"], "qty": "38", "uom": "bag", "rate": "350"}])
    assert again["number"] != doc["number"]

    pdf = boss.get(M + "/opening/%d/document.pdf" % doc["id"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"


def test_a_posted_opening_whose_stock_was_used_cannot_be_cancelled(world, sign_in, db):
    w, owner = world, sign_in("owner")
    doc = opening(owner, w, [{"item_id": w.item["helmet"], "qty": "20", "rate": "180"}])
    for a in ("submit", "approve", "post"):
        act(owner, doc, a)
    post_movement(db, movement_type="ISSUE_OUT", store_id=w.site_id, item_id=w.item["helmet"], qty=D(15), rate=None, txn_date=TODAY,
                  project_id=w.project_id, ref_doc_type="ISSUE", ref_doc_id=4401, ref_line_id=1, user_id=None)
    db.commit()
    res = owner.post(M + "/opening/%d/cancel" % doc["id"], json={"reason": "wrong"})
    assert res.status_code == 409 and "only 5 nos of" in res.json()["detail"] and "Safety Helmet" in res.json()["detail"]
    assert ok(owner.get(M + "/opening/%d" % doc["id"]))["status"] == "POSTED"


def test_opening_stock_is_refused_where_it_cannot_be_the_first_entry(world, sign_in, db):
    w, owner = world, sign_in("owner")
    res = owner.post(M + "/opening", json={"store_id": w.central_id, "opening_date": str(TODAY), "lines": [
        {"item_id": w.item["cement"], "qty": "1", "rate": "7"}]})
    assert res.status_code == 400 and "already has stock movements in CS01" in res.json()["detail"]
    opening(owner, w, [{"item_id": w.item["bricks"], "qty": "100", "rate": "8"}])
    res = owner.post(M + "/opening", json={"store_id": w.site_id, "opening_date": str(TODAY), "lines": [
        {"item_id": w.item["bricks"], "qty": "1", "rate": "8"}]})
    assert res.status_code == 400 and "already on opening OPEN/ST01/" in res.json()["detail"]
    future = owner.post(M + "/opening", json={"store_id": w.site_id, "opening_date": str(TODAY + timedelta(days=1)),
                                              "lines": [{"item_id": w.item["sand"], "qty": "1", "rate": "1"}]})
    assert future.status_code == 400
    bad = owner.post(M + "/opening", json={"store_id": w.site_id, "opening_date": str(TODAY), "lines": [
        {"item_id": w.item["sand"], "qty": "-1", "rate": "1"}, {"item_id": w.item["sand"], "qty": "1", "uom": "bag", "rate": "1"}]})
    assert bad.status_code == 400 and "Line 1" in bad.json()["detail"] and "Line 2" in bad.json()["detail"]


def test_opening_rights_and_store_access(world, sign_in):
    w = world
    keeper = sign_in("central_keeper", rights=["store.masters.create"])
    assert keeper.post(M + "/opening", json={"store_id": w.site_id, "opening_date": str(TODAY), "lines": [
        {"item_id": w.item["sand"], "qty": "1", "rate": "1"}]}).status_code == 403              # not their store
    owner = sign_in("owner")
    doc = opening(owner, w, [{"item_id": w.item["sand"], "qty": "1", "rate": "1"}])
    assert keeper.get(M + "/opening/%d" % doc["id"]).status_code == 403
    assert all(o["store_code"] == "CS01" for o in ok(keeper.get(M + "/opening"))["openings"])
    looker = sign_in("viewer")
    assert looker.get(M + "/opening").status_code == 403


SHEET = (
    "Item Code,Qty,UOM,Rate,Bin,Remarks\n"
    "{cement},40,bag,350,,ok\n"
    "{tmt16},2,MT,61000,S-01,ok in a bin\n"
    "NOPE-1,5,kg,10,,unknown item\n"
    "{sand},abc,cum,10,,bad quantity\n"
    "{bricks},100,box,8,,unknown unit\n"
    "{aggregate},5,cum,1500,Z-99,unknown bin\n"
    "{cement},10,bag,350,,twice\n"
    "\n"
)


def _sheet(w, db):
    codes = {k: db.get(models.DBItem, v).item_code for k, v in w.item.items()}
    return SHEET.format(**codes).encode()


def test_a_sheet_is_previewed_row_by_row_and_imported(world, sign_in, db):
    w, owner = world, sign_in("owner")
    ok(owner.post(M + "/stores/%d/bins" % w.site_id, json={"code": "S-01"}))
    form = {"store_id": str(w.site_id), "opening_date": str(TODAY - timedelta(days=1))}
    files = {"file": ("opening.csv", _sheet(w, db), "text/csv")}
    prev = ok(owner.post(M + "/opening/import/preview", data=form, files=files))
    assert prev["summary"] == {"rows": 7, "ok": 2, "errors": 5, "total_value": "136000.00"}
    rows = prev["rows"]
    assert rows[0]["errors"] == [] and rows[0]["base_qty"] == "2000.000" and rows[0]["base_rate"] == "7.0000"
    assert rows[1]["errors"] == [] and rows[1]["base_qty"] == "2000.000" and rows[1]["bin_code"] == "S-01"
    assert "No stock item NOPE-1" in rows[2]["errors"][0]
    assert "not a number" in rows[3]["errors"][0]
    assert "No conversion" in rows[4]["errors"][0]
    assert "Bin Z-99" in rows[5]["errors"][0]
    assert "appears twice" in rows[6]["errors"][0]
    refused = owner.post(M + "/opening/import", data=form, files={"file": ("o.csv", _sheet(w, db), "text/csv")})
    assert refused.status_code == 400 and "5 of 7 rows" in refused.json()["detail"]
    made = ok(owner.post(M + "/opening/import", data=dict(form, skip_errors="true", remarks="from the sheet"),
                         files={"file": ("o.csv", _sheet(w, db), "text/csv")}))
    doc = made["opening"]
    assert doc["status"] == "DRAFT" and doc["source"] == "CSV" and len(doc["lines"]) == 2 and doc["total_value"] == "136000.00"
    assert doc["trail"][0]["note"] == "Imported from a sheet"


def test_a_sheet_without_the_columns_it_needs(world, sign_in):
    w, owner = world, sign_in("owner")
    form = {"store_id": str(w.site_id), "opening_date": str(TODAY)}
    res = owner.post(M + "/opening/import/preview", data=form, files={"file": ("x.csv", b"code,amount\nA,1\n", "text/csv")})
    assert res.status_code == 400 and "Missing: qty, rate" in res.json()["detail"]
    res = owner.post(M + "/opening/import/preview", data=form, files={"file": ("x.csv", b"", "text/csv")})
    assert res.status_code == 400
    tpl = owner.get(M + "/opening/template.csv")
    assert tpl.status_code == 200 and tpl.text.startswith("item_code,qty,uom,rate")
