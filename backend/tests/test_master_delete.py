"""The Master deletes a record, or a whole project, with everything that hangs off it.

Rows are inserted directly and the leftovers are looked at afterwards: on SQLite a delete that forgot a table still
answers 200, and Postgres - which the live site runs on - is where it would fail.
"""
import main
from app import models
from app.services import purge


def _db():
    return main.SessionLocal()


def _cls(table):
    for m in models.Base.registry.mappers:
        if m.local_table.name == table:
            return m.class_
    raise KeyError(table)


def _add(db, table, **values):
    obj = _cls(table)(**values)
    db.add(obj)
    db.commit()
    return obj.id


def _count(table, **where):
    with _db() as db:
        q = db.query(_cls(table))
        for k, v in where.items():
            q = q.filter(getattr(_cls(table), k) == v)
        return q.count()


def _client_id():
    with _db() as db:
        return db.query(models.DBClient).order_by(models.DBClient.id.desc()).first().id


def _project_with_records(client_id):
    with _db() as db:
        job = _add(db, "jobs", client_id=client_id, name="Tower Z", number="JOB-ZZ")
        po = _add(db, "purchase_orders", client_id=client_id, job_id=job, number="PO-ZZ")
        _add(db, "purchase_order_line_items", order_id=po, description="Cement")
        grn = _add(db, "goods_receipts", client_id=client_id, job_id=job, purchase_order_id=po, number="GRN-ZZ")
        _add(db, "goods_receipt_lines", goods_receipt_id=grn)
        bill = _add(db, "bills", client_id=client_id, job_id=job, purchase_order_id=po, number="BILL-ZZ")
        _add(db, "bill_line_items", bill_id=bill, description="Cement")
        _add(db, "money_entries", client_id=client_id, job_id=job, number="PMT-ZZ", doc_type="supplier_bill", doc_id=bill, amount=500)
        _add(db, "site_diaries", client_id=client_id, job_id=job, diary_date="2026-10-01")
        _add(db, "drawings", client_id=client_id, job_id=job, number="DWG-ZZ")
        equipment = _add(db, "assets", client_id=client_id, name="Crane", code="EQ-ZZ", current_job_id=job)
        lead = _add(db, "leads", client_id=client_id, job_id=job, number="TND-ZZ")
        return {"job": job, "po": po, "grn": grn, "bill": bill, "equipment": equipment, "lead": lead}


def test_deleting_a_project_takes_every_record_about_it_and_keeps_what_existed_apart_from_it(tenant):
    ids = _project_with_records(_client_id())
    other_job = None
    with _db() as db:
        other_job = _add(db, "jobs", client_id=_client_id(), name="Other", number="JOB-OTHER")
        other_po = _add(db, "purchase_orders", client_id=_client_id(), job_id=other_job, number="PO-OTHER")

    preview = tenant.get("/api/jobs/%d/delete-preview" % ids["job"]).json()
    assert preview["can_delete"] and preview["counts"].get("purchase orders") == 1 and preview["counts"].get("supplier bills") == 1
    assert preview["kept"].get("equipment") == 1, "equipment is kept, and the preview says so"

    res = tenant.delete("/api/jobs/%d" % ids["job"])
    assert res.status_code == 200, res.text

    assert _count("jobs", id=ids["job"]) == 0
    for table in ("purchase_orders", "goods_receipts", "bills", "money_entries", "site_diaries", "drawings"):
        assert _count(table, job_id=ids["job"]) == 0, table
    assert _count("purchase_order_line_items", order_id=ids["po"]) == 0, "an order's lines go with it"
    assert _count("goods_receipt_lines", goods_receipt_id=ids["grn"]) == 0
    assert _count("bill_line_items", bill_id=ids["bill"]) == 0
    with _db() as db:
        assert db.query(models.DBAsset).get(ids["equipment"]).current_job_id is None, "equipment stays and is no longer on the project"
        assert db.query(models.DBLead).get(ids["lead"]).job_id is None, "a tender stays and loses its project"
        assert db.query(models.DBJob).get(other_job) is not None and db.query(models.DBPurchaseOrder).get(other_po) is not None, \
            "another project is untouched"


def test_deleting_a_project_that_a_staff_member_may_not_delete_is_refused(tenant):
    # Only the account Master. The tenant fixture is the Master; a staff session is exercised in test_employee_portal.
    ids = _project_with_records(_client_id())
    assert tenant.delete("/api/jobs/%d" % ids["job"]).status_code == 200


def test_the_master_can_delete_a_single_record_of_any_kind_with_what_hangs_off_it(tenant):
    ids = _project_with_records(_client_id())
    pre = tenant.get("/api/master/purchase_order/%d/delete-preview" % ids["po"]).json()
    assert pre["counts"].get("purchase order lines") == 1
    assert tenant.delete("/api/master/purchase_order/%d" % ids["po"]).status_code == 200
    assert _count("purchase_orders", id=ids["po"]) == 0
    assert _count("purchase_order_line_items", order_id=ids["po"]) == 0
    with _db() as db:
        bill = db.query(models.DBBill).get(ids["bill"])
        assert bill is not None and bill.purchase_order_id is None, "a bill that named the order stays, unlinked"
        grn = db.query(models.DBGoodsReceipt).get(ids["grn"])
        assert grn is not None and grn.purchase_order_id is None

    assert tenant.delete("/api/master/supplier_bill/%d" % ids["bill"]).status_code == 200
    assert _count("money_entries", doc_type="supplier_bill", doc_id=ids["bill"]) == 0, "payments against the bill go with it"
    assert _count("bill_line_items", bill_id=ids["bill"]) == 0


def test_bulk_delete_and_unknown_kinds(tenant):
    ids = _project_with_records(_client_id())
    out = tenant.post("/api/master/grn/bulk-delete", json={"ids": [ids["grn"], 999999]}).json()
    assert out["deleted"] == 1 and out["gone"] == 1
    assert tenant.delete("/api/master/nonsense/1").status_code == 404
    assert tenant.get("/api/master/purchase_order/999999/delete-preview").status_code == 404


def test_another_company_cannot_delete_or_preview_it(tenant, second_tenant):
    email = tenant.get("/api/client/me").json()["email"]
    with _db() as db:
        mine = db.query(models.DBClient).filter(models.DBClient.email == email).first().id
    ids = _project_with_records(mine)
    assert second_tenant.delete("/api/jobs/%d" % ids["job"]).status_code == 404
    assert second_tenant.delete("/api/master/purchase_order/%d" % ids["po"]).status_code == 404
    assert second_tenant.get("/api/master/purchase_order/%d/delete-preview" % ids["po"]).status_code == 404
    assert _count("purchase_orders", id=ids["po"]) == 1


def test_every_kind_the_master_can_delete_names_a_real_table_and_model():
    for kind, (table, model, noun, col) in purge.KINDS.items():
        cls = getattr(models, model)
        assert cls.__tablename__ == table, kind
        assert hasattr(cls, col), (kind, col)


def test_deleting_a_project_takes_its_work_orders_measurements_and_bills_too(tenant):
    from test_delete_work_order import book, live_order
    order = live_order(tenant, pay_advance=False)
    item = book(tenant, order["id"])["lines"][0]["item_id"]
    assert tenant.post("/api/sub-mb/%d/entries" % order["id"], json={"item_id": item, "quantity": 5}).status_code == 200
    bill = tenant.post("/api/sub-bills", json={"order_id": order["id"]}).json()["bill"]
    with _db() as db:
        job_id = db.query(models.DBSubcontractOrder).get(order["id"]).job_id
    assert job_id, "the order is filed against a project"

    pre = tenant.get("/api/jobs/%d/delete-preview" % job_id).json()
    assert pre["counts"].get("work orders") == 1

    assert tenant.delete("/api/jobs/%d" % job_id).status_code == 200
    assert _count("subcontract_orders", id=order["id"]) == 0
    assert _count("sub_measurements", order_id=order["id"]) == 0, "the measurement book goes"
    assert _count("sub_bills", id=bill["id"]) == 0, "and its bills"
    assert _count("jobs", id=job_id) == 0


def test_a_supplier_and_an_item_can_be_deleted_by_the_master(tenant):
    cid = _client_id()
    with _db() as db:
        supplier = _add(db, "suppliers", client_id=cid, name="ACC Ltd")
    assert tenant.delete("/api/master/supplier/%d" % supplier).status_code == 200
    assert _count("suppliers", id=supplier) == 0
