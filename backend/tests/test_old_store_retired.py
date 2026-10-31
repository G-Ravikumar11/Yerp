"""The old store takes nothing new, whoever asks and however, and every record it holds can still be read."""
import uuid

import pytest

import main
from app import models


@pytest.fixture
def closed(monkeypatch):
    monkeypatch.delenv("OLD_STORE_OPEN", raising=False)


def job(tenant):
    return tenant.post("/api/jobs", json={"name": "Vizag STP", "customer_name": "L&T"}).json()


def test_new_vouchers_and_removals_are_refused_and_nothing_is_written(tenant, closed):
    j = job(tenant)
    res = tenant.post("/api/material-vouchers", json={"job_id": j["id"], "lines": [{"description": "Cement", "issued_qty": 5}]})
    assert res.status_code == 409 and "legacy store module" in res.json()["detail"]
    assert tenant.get("/api/material-vouchers").json()["vouchers"] == []


def test_a_voucher_from_before_can_be_read_and_printed_but_not_removed(tenant, closed, monkeypatch):
    j = job(tenant)
    monkeypatch.setenv("OLD_STORE_OPEN", "1")
    made = tenant.post("/api/material-vouchers", json={"job_id": j["id"], "lines": [{"description": "Cement", "uom": "Bag", "issued_qty": 5}]}).json()["voucher"]
    monkeypatch.delenv("OLD_STORE_OPEN")
    assert tenant.get("/api/material-vouchers").json()["vouchers"][0]["id"] == made["id"]
    assert tenant.get("/api/material-vouchers/%d/document.pdf" % made["id"]).status_code == 200
    assert tenant.get("/api/material-vouchers.xlsx").status_code == 200
    assert tenant.delete("/api/material-vouchers/%d" % made["id"]).status_code == 409
    assert len(tenant.get("/api/material-vouchers").json()["vouchers"]) == 1


@pytest.mark.parametrize("url,body", [
    ("/api/stock-issues", {"job_id": 1, "lines": []}),
    ("/api/stock/adjustments", {"item_code": "X", "counted": 1}),
    ("/api/stock/transfers", {"from_store": "A", "to_store": "B", "lines": [{"item_code": "X", "qty": 1}]}),
    ("/api/grn", {"purchase_order_id": 1, "lines": []}),
])
def test_old_issues_receipts_transfers_and_adjustments_are_refused(tenant, closed, url, body):
    res = tenant.post(url, json=body)
    assert res.status_code in (409, 422), res.text
    if url != "/api/stock-issues" and url != "/api/grn":
        assert res.status_code == 409 and "legacy store module" in res.json()["detail"]


def test_the_screens_are_told_it_is_closed(tenant, closed):
    assert tenant.get("/api/stock/cutover?brief=true").json()["closed"] is True
    assert tenant.get("/api/stock").status_code == 200
    assert tenant.get("/api/stock-issues").status_code == 200
    assert tenant.get("/api/grn").status_code == 200


def test_one_reorder_level_for_an_item(tenant):
    CODE = "R" + uuid.uuid4().hex[:5].upper()
    res = tenant.post("/api/erp/items", json={"kind": "RM", "item_code": CODE, "item_name": "Ready mix", "units_of_measure": "Bag"})
    assert res.status_code == 200, res.text
    with main.SessionLocal() as db:
        item = db.query(models.DBItem).filter(models.DBItem.item_code == CODE).first()
        db.add(models.DBStoreItemSettings(item_id=item.id, base_uom="Bag", reorder_level=5))
        db.commit()
        iid = item.id
        db.add(models.DBStoreItemSettings(item_id=iid, base_uom="Bag", reorder_level=9))
        with pytest.raises(Exception):
            db.commit()                                              # a second level for one item cannot exist
        db.rollback()
    assert tenant.put("/api/erp/items/%d" % iid, json={"kind": "RM", "item_name": "Ready mix", "units_of_measure": "Bag", "reorder_level": 40}).status_code == 200
    with main.SessionLocal() as db:
        assert float(db.query(models.DBStoreItemSettings).filter(models.DBStoreItemSettings.item_id == iid).first().reorder_level) == 40
        assert db.query(models.DBItem).get(iid).reorder_level == 40
