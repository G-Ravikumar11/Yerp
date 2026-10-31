"""An item entered once; items entered twice found, and folded into one with everything that hangs on them."""
import threading
from decimal import Decimal

import pytest

import main
from app import models
from app.models.store_core import DBStore, DBStoreBatch, DBStoreStockBalance


def item(tenant, name="Cement OPC 53", uom="Bag", kind="RM", **over):
    return tenant.post("/api/items", json={"item_name": name, "units_of_measure": uom, "kind": kind, **over})


def made(tenant, *a, **k):
    res = item(tenant, *a, **k)
    assert res.status_code == 200, res.text
    return res.json()["item"]


def older(client_id, name, uom="Bag", kind="RM", **over):
    """An item from before the check: no key on it."""
    with main.SessionLocal() as db:
        n = db.query(models.DBItem).count() + 1
        it = models.DBItem(client_id=client_id, kind=kind, item_code="OL%04d" % n, item_name=name, units_of_measure=uom, **over)
        db.add(it)
        db.commit()
        return it.id


def company(tenant, any_item):
    with main.SessionLocal() as db:
        return db.query(models.DBItem).get(any_item["id"]).client_id


def test_the_same_item_is_refused_whatever_the_case_or_spacing(tenant):
    first = made(tenant)
    for name in ("cement  opc 53", " CEMENT OPC 53 "):
        res = item(tenant, name, "bag")
        assert res.status_code == 409 and first["item_code"] in res.json()["detail"]


def test_another_unit_specification_or_make_is_another_item(tenant):
    made(tenant)
    assert item(tenant, uom="Kg").status_code == 200
    assert item(tenant, specification="IS 269").status_code == 200
    assert item(tenant, make="Ultratech").status_code == 200


def test_a_code_cannot_be_used_twice_in_any_case(tenant):
    made(tenant, item_code="CEM001")
    assert item(tenant, "Other", item_code="cem001").status_code == 409


def test_an_item_from_before_the_check_still_counts(tenant):
    first = made(tenant, "Anything")
    older(company(tenant, first), "River sand")
    assert item(tenant, "river  SAND").status_code == 409


def test_an_edit_cannot_turn_one_item_into_another(tenant):
    made(tenant, "Sand")
    b = made(tenant, "Gravel")
    res = tenant.put("/api/items/%d" % b["id"], json={**b, "item_name": "SAND"})
    assert res.status_code == 409


def test_two_people_saving_at_once_make_one_item(tenant):
    """The database has the last word: two rows with one key cannot exist."""
    a = made(tenant)
    with main.SessionLocal() as db:
        row = db.query(models.DBItem).get(a["id"])
        db.add(models.DBItem(client_id=row.client_id, kind="RM", item_code="DUP001", item_name=row.item_name, dup_key=row.dup_key))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    results = []
    barrier = threading.Barrier(2)

    def post():
        barrier.wait()
        results.append(item(tenant, "Binding wire").status_code)
    threads = [threading.Thread(target=post) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert 200 in results and all(c in (200, 409) for c in results)
    with main.SessionLocal() as db:
        assert db.query(models.DBItem).filter(models.DBItem.item_name == "Binding wire").count() == 1


def test_the_report_keeps_exact_and_possible_apart_and_merges_nothing(tenant):
    a = made(tenant, "Anchor")
    cid = company(tenant, a)
    older(cid, "Tile adhesive"), older(cid, "TILE  ADHESIVE")
    older(cid, "Paint, white"), older(cid, "White paint")
    older(cid, "Grout", "Kg"), older(cid, "Grout", "Bag")
    r = tenant.get("/api/items/duplicates").json()
    assert r["exact"] == 1 and r["possible"] == 2 and r["total"] == 3
    assert tenant.get("/api/items/duplicates?type=exact").json()["groups"][0]["type"] == "exact"
    assert len(tenant.get("/api/items/duplicates?per_page=1&page=2").json()["groups"]) == 1
    assert tenant.get("/api/items/duplicates?q=grout").json()["total"] == 1
    assert tenant.get("/api/items/duplicates.xlsx").status_code == 200
    with main.SessionLocal() as db:
        assert db.query(models.DBItem).filter(models.DBItem.merged_into_id.isnot(None)).count() == 0


def a_store(cid, code="ST1"):
    with main.SessionLocal() as db:
        s = DBStore(client_id=cid, code=code, name="Main " + code)
        db.add(s)
        db.commit()
        return s.id


def balance(item_id, store_id):
    with main.SessionLocal() as db:
        return db.query(DBStoreStockBalance).filter_by(item_id=item_id, store_id=store_id).first()


def test_a_merge_adds_the_stock_moves_the_records_and_keeps_the_duplicate(tenant):
    keep = made(tenant, "Cement")
    cid = company(tenant, keep)
    dup = older(cid, "cement ", reorder_level=3)
    st, st2 = a_store(cid), a_store(cid, "ST2")
    with main.SessionLocal() as db:
        for iid, s, q, v in ((keep["id"], st, 10, 1000), (dup, st, 30, 2400), (dup, st2, 5, 500)):
            db.add(DBStoreStockBalance(store_id=s, item_id=iid, qty=Decimal(q), value=Decimal(v), avg_rate=Decimal(v) / Decimal(q)))
        code = db.query(models.DBItem).get(dup).item_code
        db.add(models.DBStockMovement(client_id=cid, item_code=code, kind="ISSUE", quantity=2, rate=10, value=20, moved_on="2026-01-01"))
        db.commit()
    prev = tenant.post("/api/items/merge/preview", json={"primary_id": keep["id"], "item_ids": [dup]}).json()
    assert len(prev["items"]) == 2 and prev["problems"] == []
    assert balance(dup, st).qty == 30                                    # looking changes nothing
    res = tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [dup], "reason": "Same cement"})
    assert res.status_code == 200, res.text
    b = balance(keep["id"], st)
    assert b.qty == 40 and b.value == 3400 and float(b.avg_rate) == 85
    assert balance(keep["id"], st2).qty == 5 and balance(dup, st) is None
    with main.SessionLocal() as db:
        old = db.query(models.DBItem).get(dup)
        assert old is not None and old.is_active is False and old.merged_into_id == keep["id"]
        assert db.query(models.DBStockMovement).filter_by(client_id=cid).first().item_code == keep["item_code"]
        rec = db.query(models.DBItemMerge).filter_by(merged_item_id=dup).first()
        assert rec.primary_item_id == keep["id"] and rec.merged_code == code and "store_stock_balance.item_id" in rec.moved and rec.reason == "Same cement"
        assert db.query(models.DBAuditLog).filter_by(action="item_merged", entity_id=dup).count() == 1
    assert item(tenant, "Cement").status_code == 409                     # the item kept still blocks a repeat
    assert tenant.get("/api/items/duplicates?q=cement").json()["total"] == 0


def test_different_units_are_refused_and_nothing_moves(tenant):
    keep = made(tenant, "Sand", "Cum")
    dup = older(company(tenant, keep), "Sand", "Bag")
    prev = tenant.post("/api/items/merge/preview", json={"primary_id": keep["id"], "item_ids": [dup]}).json()
    assert prev["problems"] and "Reconcile" in prev["problems"][0]
    assert tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [dup]}).status_code == 409
    with main.SessionLocal() as db:
        assert db.query(models.DBItem).get(dup).merged_into_id is None


def test_a_material_is_not_merged_with_a_work_item_nor_twice(tenant):
    keep = made(tenant, "Steel")
    cid = company(tenant, keep)
    work = older(cid, "Steel", kind="FG")
    assert tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [work]}).status_code == 409
    dup = older(cid, "Steel")
    assert tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [dup]}).status_code == 200
    assert tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [dup]}).status_code == 409


def test_a_batch_on_both_stops_the_merge(tenant):
    keep = made(tenant, "Paint")
    cid = company(tenant, keep)
    dup = older(cid, "paint")
    with main.SessionLocal() as db:
        db.add(DBStoreBatch(client_id=cid, item_id=keep["id"], batch_no="B1"))
        db.add(DBStoreBatch(client_id=cid, item_id=dup, batch_no="B1"))
        db.commit()
    res = tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [dup]})
    assert res.status_code == 409 and "B1" in res.json()["detail"]


def test_a_failure_part_way_leaves_nothing_changed(tenant, monkeypatch):
    keep = made(tenant, "Lime")
    cid = company(tenant, keep)
    dup = older(cid, "lime")
    st = a_store(cid)
    with main.SessionLocal() as db:
        db.add(DBStoreStockBalance(store_id=st, item_id=dup, qty=Decimal(5), value=Decimal(50), avg_rate=Decimal(10)))
        db.commit()
    from app.services import item_merge

    def boom(*a, **k):
        raise RuntimeError("power cut")
    monkeypatch.setattr(item_merge.models, "DBItemMerge", boom)
    assert tenant.post("/api/items/merge", json={"primary_id": keep["id"], "item_ids": [dup]}).status_code != 200
    monkeypatch.undo()
    assert balance(dup, st).qty == 5 and balance(keep["id"], st) is None


def test_only_those_who_manage_items_may_merge_and_only_their_own(tenant, second_tenant, portal):
    keep = made(tenant, "Nails")
    dup = older(company(tenant, keep), "nails")
    body = {"primary_id": keep["id"], "item_ids": [dup]}
    assert portal.post("/api/items/merge", json=body).status_code in (401, 403)
    assert second_tenant.post("/api/items/merge", json=body).status_code == 404
