"""An NCR that rejects a lot and sends it to Rejected Goods, each item's shelf life, and the watch on expired lots."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

import main
from app import models
from app.models.store_core import DBStoreBatch, DBStoreBatchBalance, DBStoreStockLedger, MovementType
from app.models.store_extras import DBStoreRejection
from app.services import store_holds
from app.services.store_batches import default_expiry, shelf_days

from tests.test_store_quality_holds import Lot, _fresh, close, day, hold, lot, ncr  # noqa: F401


def reject(tenant, nid, reason="Moisture throughout"):
    return tenant.post("/api/qc/ncrs/%d/reject" % nid, json={"reason": reason})


def rejected_moves(nid):
    with main.SessionLocal() as db:
        return db.query(DBStoreStockLedger).filter(DBStoreStockLedger.movement_type == MovementType.REJECTED_OUT.value, DBStoreStockLedger.ref_doc_id == nid).count()


def test_rejecting_an_ncr_moves_the_lot_to_rejected_goods(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    res = reject(tenant, n["id"])
    assert res.status_code == 200, res.text
    assert res.json()["ncr"]["status"] == "REJECTED" and res.json()["ncr"]["status_label"] == "Rejected"
    v = lot.view(lot.b1)
    assert v["hold_status"] == "Rejected" and v["status_code"] == "REJECTED" and v["available_qty"] == "0" and v["blocked"]
    assert rejected_moves(n["id"]) == 1
    rows = tenant.get("/api/store/rejections?status=HELD").json()["items"]
    row = [r for r in rows if r["ncr_id"] == n["id"]][0]
    assert row["batch_no"] == "B1" and row["ncr_number"] == n["number"] and Decimal(row["qty"]) == 100 and row["reason"] == "Moisture throughout" and row["rejected_by"] and row["rejected_on"]
    assert lot.view(lot.b2)["available_qty"] == "50"      # the other lot is none of its business


def test_a_rejected_lot_is_refused_with_its_own_code(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    assert reject(tenant, n["id"]).status_code == 200
    lot.batch_again = None
    with main.SessionLocal() as db:      # stock put back on it by mistake still cannot be used
        b = db.get(DBStoreBatch, lot.b1)
        assert b.lot_status == "REJECTED"
        db.query(DBStoreBatchBalance).filter(DBStoreBatchBalance.batch_id == lot.b1).update({"qty": 5})
        db.commit()
    with pytest.raises(Exception, match="has been rejected"):
        lot.issue(1, lot.b1)


def test_rejecting_twice_moves_the_stock_once(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    assert reject(tenant, n["id"]).status_code == 200
    assert reject(tenant, n["id"]).status_code == 409
    assert rejected_moves(n["id"]) == 1
    with main.SessionLocal() as db:
        assert db.query(DBStoreRejection).filter(DBStoreRejection.ncr_id == n["id"]).count() == 1


def test_a_failure_halfway_leaves_everything_as_it_was(tenant, lot, monkeypatch):
    n = ncr(tenant, lot, lot.b1)

    def boom(*a, **k):
        raise RuntimeError("the database went away")
    monkeypatch.setattr(store_holds, "post_movement", boom)
    try:
        res = reject(tenant, n["id"])
        assert res.status_code >= 500
    except RuntimeError:
        pass
    monkeypatch.undo()
    assert tenant.get("/api/qc/ncrs/%d" % n["id"]).json()["ncr"]["status"] == "OPEN"
    v = lot.view(lot.b1)
    assert v["hold_status"] == "On Hold" and v["available_qty"] == "100"
    with main.SessionLocal() as db:
        assert db.query(DBStoreRejection).filter(DBStoreRejection.ncr_id == n["id"]).count() == 0


def test_a_rejection_needs_a_reason_a_lot_and_a_live_ncr(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    assert reject(tenant, n["id"], "  ").status_code == 400
    site = tenant.post("/api/qc/ncrs", json={"job_id": lot.job["id"], "description": "Honeycombing", "severity": "Minor"})
    assert site.status_code == 200, site.text
    assert reject(tenant, site.json()["ncr"]["id"]).status_code == 409
    close(tenant, n["id"])
    assert reject(tenant, n["id"]).status_code == 409


def test_another_hold_on_the_lot_stays_on_the_record(tenant, lot):
    assert hold(tenant, lot.b1).status_code == 200
    n = ncr(tenant, lot, lot.b1)
    assert reject(tenant, n["id"]).status_code == 200
    holds = lot.view(lot.b1)["holds"]
    assert [h["status"] for h in holds if h["kind"] == "MANUAL"] == ["ACTIVE"] and [h["status"] for h in holds if h["kind"] == "NCR"] == ["RELEASED"]


def test_a_rejected_ncr_no_longer_counts_as_open_and_goes_on_being_read(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    assert reject(tenant, n["id"]).status_code == 200
    assert not [x for x in tenant.get("/api/qc/ncrs?status=not_closed").json().get("ncrs", []) if x["id"] == n["id"]]
    assert tenant.post("/api/qc/ncrs/%d/assign" % n["id"], json={"responsible": "X", "target_date": day(5), "corrective_action": "Y", "root_cause": "Z", "severity": "Minor"}).status_code == 409


def test_rejected_goods_from_an_ncr_can_be_disposed_of(tenant, lot):
    n = ncr(tenant, lot, lot.b1)
    reject(tenant, n["id"])
    row = [r for r in tenant.get("/api/store/rejections?status=HELD").json()["items"] if r["ncr_id"] == n["id"]][0]
    res = tenant.post("/api/store/rejections/%d/resolve" % row["id"], json={"outcome": "DISPOSED", "note": "Sent to landfill"})
    assert res.status_code == 200, res.text
    assert lot.view(lot.b1)["available_qty"] == "0" and rejected_moves(n["id"]) == 1


# ---- shelf life ----------------------------------------------------------------------------

def test_the_items_own_shelf_life_comes_first_and_cement_keeps_its_ninety_days():
    made = date(2026, 1, 1)
    item = models.DBItem(item_name="Admixture", shelf_life_applicable=True, shelf_life_days=30)
    assert shelf_days(item) == 30 and default_expiry(item, made) == date(2026, 1, 31)
    assert default_expiry(models.DBItem(item_name="OPC Cement 53"), made) == made + timedelta(days=90)
    assert default_expiry(models.DBItem(item_name="Cement", shelf_life_applicable=True, shelf_life_days=45), made) == made + timedelta(days=45)
    assert default_expiry(models.DBItem(item_name="Steel"), made) is None


def test_the_receipt_form_gets_the_same_sum_as_the_save(tenant, lot):
    with main.SessionLocal() as db:
        i = db.get(models.DBItem, lot.item)
        i.shelf_life_applicable, i.shelf_life_days, i.expiry_tracking = True, 60, True
        db.commit()
    res = tenant.get("/api/store/batches/shelf-life/%d?made=2026-01-01" % lot.item).json()
    assert res == {"applicable": True, "days": 60, "tracked": True, "expiry_date": "2026-03-02"}
    assert tenant.get("/api/store/batches/shelf-life/999999").status_code == 404


# ---- expired lots --------------------------------------------------------------------------

def test_expired_lots_show_filter_and_are_noted_once_without_being_written_off(tenant, lot):
    with main.SessionLocal() as db:
        db.get(DBStoreBatch, lot.b1).expiry_date = date.today() - timedelta(days=1)
        db.commit()
    v = lot.view(lot.b1)
    assert v["hold_status"] == "Expired" and v["status_code"] == "EXPIRED" and v["blocked"] and v["available_qty"] == "100"
    listed = tenant.get("/api/store/batches?hold_status=EXPIRED").json()["batches"]
    assert [b["batch_no"] for b in listed] == ["B1"]
    with main.SessionLocal() as db:
        run = getattr(store_holds.note_expired_lots, "__wrapped__", store_holds.note_expired_lots)
        assert run(db, datetime.now()) == "1 lots"
        assert run(db, datetime.now()) == "0 lots"
        assert db.query(models.DBAuditLog).filter(models.DBAuditLog.action == "store.batch.expired", models.DBAuditLog.entity_id == str(lot.b1)).count() == 1
    assert lot.view(lot.b1)["available_qty"] == "100"
