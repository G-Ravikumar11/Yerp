"""P1: store masters (stores, bins, assignments, item settings, unit conversions) and stock enquiry."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest

from app import db as database, models
from app.models.store_core import (
    DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.services.stock_ledger import post_movement, reverse_document

from conftest import make_employee

D = Decimal
M = "/api/store/masters"
E = "/api/store/enquiry"


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    """The suite empties the item master between tests, which frees item ids for reuse; stock, settings and conversions
    pointing at the old ids would then belong to the next test's items."""
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


def seed(account, qty="100", rate="10", item_uom="kg"):
    """A store and an item of the signed-in company with stock in it, posted the proper way."""
    tenant = account["client"]
    store = tenant.post(M + "/stores", json={"code": "T" + uuid.uuid4().hex[:4].upper(), "name": "Seed store", "type": "CENTRAL"}).json()
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        item = models.DBItem(client_id=client.id, kind="RM", item_code="IT-" + uuid.uuid4().hex[:6], item_name="Seed item", units_of_measure=item_uom)
        s.add(item)
        s.flush()
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=store["id"], item_id=item.id, qty=D(qty), rate=D(rate),
                      txn_date=date.today() - timedelta(days=5), project_id=None, ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
        return store, item.id, client.id


def staff(account, portal, rights, store_ids=()):
    email = "p1-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in store_ids])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200
    return emp


# --- stores ---------------------------------------------------------------------------------------------------------

def test_a_store_is_added_listed_and_changed(tenant):
    made = tenant.post(M + "/stores", json={"code": "cs77", "name": " Central   Store ", "type": "central", "address": "Head yard"})
    assert made.status_code == 200, made.text
    s = made.json()
    assert (s["code"], s["name"], s["type"], s["is_active"], s["bins"], s["staff"], s["frozen"]) == ("CS77", "Central Store", "CENTRAL", True, 0, 0, False)
    assert [x["code"] for x in tenant.get(M + "/stores").json()["items"]] == ["CS77"]
    assert tenant.get(M).json()["slice"] == "masters"
    edit = tenant.put(M + "/stores/%d" % s["id"], json={"code": "CS78", "name": "Main Store", "type": "YARD"})
    assert edit.status_code == 200 and (edit.json()["code"], edit.json()["type"]) == ("CS78", "YARD")


def test_store_rules(tenant):
    ok = {"code": "CS01", "name": "A", "type": "CENTRAL"}
    assert tenant.post(M + "/stores", json=ok).status_code == 200
    assert tenant.post(M + "/stores", json=ok).status_code == 409                                  # same code twice
    for bad in ({"code": "C", "name": "A"}, {"code": "CS/01", "name": "A"}, {"code": "CS02", "name": " "},
                {"code": "CS02", "name": "A", "type": "SHED"}, {"code": "CS02", "name": "A", "project_id": 999999}):
        assert tenant.post(M + "/stores", json=bad).status_code == 400, bad


def test_a_stores_code_is_fixed_once_stock_moves_and_it_cannot_close_while_it_holds_stock(account):
    tenant = account["client"]
    store, _item, _cid = seed(account)
    r = tenant.put(M + "/stores/%d" % store["id"], json={"code": "NEWC", "name": "x", "type": "CENTRAL"})
    assert r.status_code == 409 and "cannot change" in r.json()["detail"]
    assert tenant.put(M + "/stores/%d" % store["id"], json={"code": store["code"], "name": "Renamed", "type": "CENTRAL"}).status_code == 200
    r = tenant.post(M + "/stores/%d/deactivate" % store["id"])
    assert r.status_code == 409 and "still holds stock" in r.json()["detail"]
    empty = tenant.post(M + "/stores", json={"code": "EMP1", "name": "Empty", "type": "YARD"}).json()
    assert tenant.post(M + "/stores/%d/deactivate" % empty["id"]).json()["is_active"] is False
    assert tenant.post(M + "/stores/%d/deactivate" % empty["id"]).status_code == 409
    assert [x["code"] for x in tenant.get(M + "/stores", params={"status": "inactive"}).json()["items"]] == ["EMP1"]
    assert tenant.post(M + "/stores/%d/activate" % empty["id"]).json()["is_active"] is True


def test_bins(tenant):
    s = tenant.post(M + "/stores", json={"code": "BN01", "name": "Bins", "type": "SITE"}).json()
    b = tenant.post(M + "/stores/%d/bins" % s["id"], json={"code": "a-01", "description": "Cement shed"})
    assert b.status_code == 200 and b.json()["code"] == "A-01"
    assert tenant.post(M + "/stores/%d/bins" % s["id"], json={"code": "A-01"}).status_code == 409
    assert tenant.post(M + "/stores/%d/bins" % s["id"], json={"code": " "}).status_code == 400
    bid = b.json()["id"]
    assert tenant.put(M + "/bins/%d" % bid, json={"code": "A-02", "description": "Moved"}).json()["code"] == "A-02"
    assert tenant.get(M + "/stores/%d" % s["id"]).json()["bins"] == 1
    assert tenant.delete(M + "/bins/%d" % bid).status_code == 200
    assert tenant.delete(M + "/bins/%d" % bid).status_code == 404


def test_assignments_give_and_take_away_a_store(account):
    tenant = account["client"]
    s = tenant.post(M + "/stores", json={"code": "AS01", "name": "Assigned", "type": "SITE"}).json()
    emp = make_employee(tenant, email="as-%s@example.com" % uuid.uuid4().hex[:6])
    r = tenant.post(M + "/stores/%d/assignments" % s["id"], json={"employee_id": emp["id"], "role": "store keeper"})
    assert r.status_code == 200 and r.json()["role"] == "STORE_KEEPER"
    assert tenant.post(M + "/stores/%d/assignments" % s["id"], json={"employee_id": emp["id"]}).status_code == 409
    assert tenant.post(M + "/stores/%d/assignments" % s["id"], json={"employee_id": 999999}).status_code == 400
    assert tenant.get(M + "/stores/%d" % s["id"]).json()["staff"] == 1
    assert tenant.delete(M + "/stores/%d/assignments/%d" % (s["id"], emp["id"])).status_code == 200
    assert tenant.delete(M + "/stores/%d/assignments/%d" % (s["id"], emp["id"])).status_code == 404
    assert tenant.get(M + "/stores/%d" % s["id"]).json()["staff"] == 0
    assert tenant.post(M + "/stores/%d/assignments" % s["id"], json={"employee_id": emp["id"], "role": "Incharge"}).json()["is_active"] is True
    assert emp["id"] in [e["id"] for e in tenant.get(M + "/employees").json()["items"]]


# --- item settings and conversions ----------------------------------------------------------------------------------

def test_item_settings_and_conversions(account):
    tenant = account["client"]
    _store, item, _cid = seed(account, item_uom="kg")
    listed = [i for i in tenant.get(M + "/items", params={"q": "Seed item"}).json()["items"] if i["id"] == item][0]
    assert listed["configured"] is False and listed["settings"]["base_uom"] == "kg" and listed["on_hand"] == "100.000"
    body = {"category": "returnable", "base_uom": "kg", "reorder_level": "20", "min_qty": "5", "max_qty": "500", "qc_required": True,
            "over_receipt_tolerance_pct": "2.5"}
    saved = tenant.put(M + "/items/%d/settings" % item, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["category"] == "RETURNABLE" and saved.json()["settings"]["over_receipt_tolerance_pct"] == "2.500" and saved.json()["configured"]
    for bad in ({"reorder_level": "-1"}, {"min_qty": "9", "max_qty": "3"}, {"over_receipt_tolerance_pct": "101"}, {"category": "JUNK"}, {"base_uom": " "}, {"max_qty": "abc"}):
        assert tenant.put(M + "/items/%d/settings" % item, json={**body, **bad}).status_code == 400, bad
    assert tenant.put(M + "/items/%d/settings" % item, json={**body, "base_uom": "bag"}).status_code == 409    # stock is counted in kg
    c = tenant.put(M + "/items/%d/conversions/bag" % item, json={"to_base_factor": "50"})
    assert c.status_code == 200 and c.json()["to_base_factor"] == "50.000000"
    assert tenant.put(M + "/items/%d/conversions/KG" % item, json={"to_base_factor": "1"}).status_code == 400     # the base unit itself
    for bad in ("0", "-2", "x", "1000000001"):
        assert tenant.put(M + "/items/%d/conversions/MT" % item, json={"to_base_factor": bad}).status_code == 400, bad
    assert tenant.put(M + "/items/%d/conversions/BAG" % item, json={"to_base_factor": "40"}).json()["uom"] == "bag"     # same unit, changed
    assert [x["to_base_factor"] for x in tenant.get(M + "/items/%d" % item).json()["conversions"]] == ["40.000000"]
    assert tenant.delete(M + "/items/%d/conversions/bag" % item).status_code == 200
    assert tenant.delete(M + "/items/%d/conversions/bag" % item).status_code == 404


def test_a_base_unit_can_change_before_any_stock_moves(account):
    tenant = account["client"]
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        item = models.DBItem(client_id=client.id, kind="RM", item_code="NM-" + uuid.uuid4().hex[:6], item_name="No stock", units_of_measure="nos")
        s.add(item)
        s.commit()
        item_id = item.id
    assert tenant.put(M + "/items/%d/conversions/kg" % item_id, json={"to_base_factor": "2"}).status_code == 200
    r = tenant.put(M + "/items/%d/settings" % item_id, json={"category": "TOOL", "base_uom": "kg"})
    assert r.status_code == 200 and r.json()["conversions"] == []                                      # kg is the base now: no loop left


# --- rights and tenancy ---------------------------------------------------------------------------------------------

def test_masters_need_their_rights_and_stay_inside_the_company(account, portal, second_tenant):
    tenant = account["client"]
    mine = tenant.post(M + "/stores", json={"code": "OW01", "name": "Mine", "type": "SITE"}).json()
    other = second_tenant.post(M + "/stores", json={"code": "OW01", "name": "Theirs", "type": "SITE"}).json()      # same code, another company
    assert second_tenant.get(M + "/stores/%d" % mine["id"]).status_code == 404
    assert second_tenant.put(M + "/stores/%d" % mine["id"], json={"code": "OW01", "name": "x", "type": "SITE"}).status_code == 404
    assert second_tenant.post(M + "/stores/%d/bins" % mine["id"], json={"code": "A"}).status_code == 404
    assert [x["id"] for x in second_tenant.get(M + "/stores").json()["items"]] == [other["id"]]
    staff(account, portal, ["store.masters.view"], [mine["id"]])
    assert portal.get(M + "/stores").status_code == 200
    assert portal.post(M + "/stores", json={"code": "NO01", "name": "x", "type": "SITE"}).status_code == 403
    assert portal.post(M + "/stores/%d/deactivate" % mine["id"]).status_code == 403
    assert portal.post(M + "/stores/%d/bins" % mine["id"], json={"code": "A"}).status_code == 403


def test_staff_see_only_the_stores_they_are_assigned_to(account, portal):
    tenant = account["client"]
    a = tenant.post(M + "/stores", json={"code": "VA01", "name": "A", "type": "SITE"}).json()
    b = tenant.post(M + "/stores", json={"code": "VB01", "name": "B", "type": "SITE"}).json()
    staff(account, portal, ["store.masters.view", "store.masters.create"], [a["id"]])
    assert [x["code"] for x in portal.get(M + "/stores").json()["items"]] == ["VA01"]
    assert portal.get(M + "/stores/%d" % b["id"]).status_code == 403
    assert portal.post(M + "/stores/%d/bins" % b["id"], json={"code": "A"}).status_code == 403          # wrong-store access
    assert portal.post(M + "/stores/%d/bins" % a["id"], json={"code": "A"}).status_code == 200


# --- enquiry --------------------------------------------------------------------------------------------------------

def test_stock_position_and_item_position(account):
    tenant = account["client"]
    store, item, _cid = seed(account, qty="100", rate="10")
    tenant.put(M + "/items/%d/settings" % item, json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "150", "min_qty": "0", "max_qty": "0"})
    tenant.put(M + "/items/%d/conversions/bag" % item, json={"to_base_factor": "50"})
    r = tenant.get(E + "/balances", params={"store_id": store["id"]}).json()
    assert r["total"] == 1 and r["total_value"] == "1000.00" and r["low"] == 1
    row = r["items"][0]
    assert (row["qty"], row["avg_rate"], row["value"], row["status"], row["base_uom"]) == ("100.000", "10.0000", "1000.00", "REORDER", "kg")
    assert tenant.get(E + "/balances", params={"store_id": store["id"], "status": "OK"}).json()["total"] == 0
    assert tenant.get(E + "/balances", params={"q": "nothing like this"}).json()["total"] == 0
    pos = tenant.get(E + "/items/%d" % item).json()
    assert pos["total_qty"] == "100.000" and pos["also_in"] == [{"uom": "bag", "qty": "2.000"}] and pos["stores"][0]["store_code"] == store["code"]
    assert tenant.get(E).json()["slice"] == "enquiry"
    assert tenant.get(E + "/items/999999").status_code == 404


def test_the_stock_card_adds_up_and_flags_reversals(account):
    tenant = account["client"]
    store, item, _cid = seed(account, qty="100", rate="10")
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.ISSUE_OUT, store_id=store["id"], item_id=item, qty=D("30"), rate=None, txn_date=date.today(),
                      project_id=None, ref_doc_type="ISSUE", ref_doc_id=7, ref_line_id=1, user_id=None)
        reverse_document(s, ref_doc_type="ISSUE", ref_doc_id=7, user_id=None, reason="wrong site")
        s.commit()
    card = tenant.get(E + "/ledger", params={"store_id": store["id"], "item_id": item}).json()
    assert card["total"] == 3 and card["opening_qty"] == "0.000" and card["closing_qty"] == "100.000"
    types = [(r["movement_type"], r["is_reversal"], r["reversed"]) for r in card["items"]]
    assert types == [("OPENING_IN", False, False), ("ISSUE_OUT", False, True), ("ISSUE_OUT", True, False)]
    assert card["items"][-1]["running_qty"] == "100.000" and "Reversal" in card["items"][-1]["remarks"]
    # a window that starts today: what came before is the opening position
    today = tenant.get(E + "/ledger", params={"store_id": store["id"], "item_id": item, "from_date": date.today().isoformat()}).json()
    assert today["opening_qty"] == "100.000" and today["closing_qty"] == "100.000" and today["total"] == 2
    assert tenant.get(E + "/ledger", params={"movement_type": "NOPE"}).status_code == 400
    assert tenant.get(E + "/ledger", params={"from_date": "2026-13-01"}).status_code == 400
    assert tenant.get(E + "/ledger", params={"from_date": "2026-02-01", "to_date": "2026-01-01"}).status_code == 400
    doc = tenant.get(E + "/documents/issue/7").json()
    assert doc["ref_doc_type"] == "ISSUE" and len(doc["items"]) == 2
    assert tenant.get(E + "/documents/ISSUE/9999").status_code == 404


def test_exports_open_as_workbooks(account):
    tenant = account["client"]
    store, _item, _cid = seed(account)
    for path in ("/balances/export", "/ledger/export"):
        res = tenant.get(E + path, params={"store_id": store["id"]})
        assert res.status_code == 200 and "spreadsheetml" in res.headers["content-type"]
        assert openpyxl.load_workbook(io.BytesIO(res.content)).active.max_row >= 2


def test_enquiry_follows_store_assignments_and_company(account, portal, second_tenant):
    a, item, _cid = seed(account)
    b, _item2, _cid2 = seed(account)
    staff(account, portal, ["store.enquiry.view"], [a["id"]])
    assert [r["store_code"] for r in portal.get(E + "/balances").json()["items"]] == [a["code"]]
    assert portal.get(E + "/balances", params={"store_id": b["id"]}).status_code == 403
    assert portal.get(E + "/ledger", params={"store_id": b["id"]}).status_code == 403
    assert {r["store_code"] for r in portal.get(E + "/ledger").json()["items"]} == {a["code"]}
    assert portal.get(M + "/stores").status_code == 403                       # no masters right
    assert second_tenant.get(E + "/balances").json()["total"] == 0
    assert second_tenant.get(E + "/items/%d" % item).status_code == 404
    assert second_tenant.get(E + "/balances", params={"store_id": a["id"]}).status_code == 404


def test_quick_find_groups_stock_for_the_home_page_search(account):
    tenant = account["client"]
    store, item, _cid = seed(account, qty="15", rate="5")
    assert tenant.get(E + "/quick", params={"q": "s"}).json()["rows"] == []                  # too short to search
    rows = tenant.get(E + "/quick", params={"q": "seed item"}).json()["rows"]
    assert len(rows) == 1 and rows[0]["item_id"] == item and rows[0]["qty"] == "15.000" and rows[0]["stores"] == 1
