"""The Store home page's type-ahead: /api/store/enquiry/quick."""
import uuid

import pytest

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion

from conftest import make_employee
from store.test_p1_foundation import E, M, seed, staff  # noqa: F401  - the same seed and staff helpers P1 uses

Q = E + "/quick"


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


def test_finds_by_name_or_code_with_quantity_held(account):
    tenant = account["client"]
    _store, item, _cid = seed(account, qty="100")
    rows = tenant.get(Q, params={"q": "seed it"}).json()["rows"]
    assert [r["item_id"] for r in rows] == [item] and rows[0]["qty"].startswith("100") and rows[0]["stores"] == 1
    with database.SessionLocal() as s:
        code = s.get(models.DBItem, item).item_code
    assert [r["item_id"] for r in tenant.get(Q, params={"q": code.lower()}).json()["rows"]] == [item]


def test_short_or_wildcard_only_terms_return_nothing(account):
    tenant = account["client"]
    seed(account)
    for term in ("", "s", " a ", "%%", "__", "\\\\"):
        assert tenant.get(Q, params={"q": term}).json() == {"rows": []}


def test_shows_the_store_base_unit_and_hides_inactive_items(account):
    tenant = account["client"]
    _store, item, _cid = seed(account, item_uom="nos")
    assert tenant.get(Q, params={"q": "seed item"}).json()["rows"][0]["uom"] == "nos"
    with database.SessionLocal() as s:
        row = s.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item).first()
        if row is None:
            row = DBStoreItemSettings(item_id=item, category="CONSUMABLE")
            s.add(row)
        row.base_uom = "kg"
        s.commit()
    assert tenant.get(Q, params={"q": "seed item"}).json()["rows"][0]["uom"] == "kg"
    with database.SessionLocal() as s:
        s.get(models.DBItem, item).is_active = False
        s.commit()
    assert tenant.get(Q, params={"q": "seed item"}).json()["rows"] == []


def test_needs_the_enquiry_right_and_only_counts_the_stores_the_person_may_see(account, portal):
    tenant = account["client"]
    store, item, _cid = seed(account, qty="100")
    other_item = seed(account, qty="40")[1]
    staff(account, portal, ["store.masters.view"], [store["id"]])
    assert portal.get(Q, params={"q": "seed item"}).status_code in (401, 403)
    staff(account, portal, ["store.enquiry.view"], [store["id"]])
    r = portal.get(Q, params={"q": "seed item"})
    assert r.status_code == 200
    mine = [x for x in r.json()["rows"] if x["item_id"] == item][0]
    assert mine["qty"].startswith("100") and mine["stores"] == 1
    hidden = [x for x in r.json()["rows"] if x["item_id"] == other_item][0]
    assert hidden["qty"] == "0" and hidden["stores"] == 0       # held only in a store this person is not assigned to
