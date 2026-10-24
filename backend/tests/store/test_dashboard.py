"""Store Overview: every figure is the records' own - stock and value from the balances, low stock from the reorder levels, work waiting
from each document's status, movements from the ledger, and a project's budget beside what work orders and the store have spent of it.
Stock is seeded straight through post_movement, as every slice's tests do."""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import main
from app import db as database, models
from app.models.store_core import (
    DBStore, DBStoreBatch, DBStoreBatchBalance, DBStoreItemSettings, DBStoreLedgerBatch, DBStoreStockBalance, DBStoreStockLedger,
    DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.models.store_inward import DBStoreGrn
from app.services.stock_ledger import post_movement, reverse_document

from conftest import make_employee

D = Decimal
API = "/api/store/dashboard"


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    """The suite empties the item master between tests, freeing item ids for reuse: clear what points at them."""
    yield
    with database.SessionLocal() as s:
        for model in (DBStoreLedgerBatch, DBStoreBatchBalance, DBStoreBatch):
            s.query(model).delete(synchronize_session=False)
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion):
            s.query(model).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def world(account):
    """Two stores of one company; three items (one plentiful, one below its reorder level, one run out); an issue to a project that has a
    budget and a work order spending part of it; a reversed issue; and a goods receipt waiting to be approved."""
    w = W()
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        tag = uuid.uuid4().hex[:6]
        w.client_id = client.id
        job = models.DBJob(client_id=client.id, number="P-" + tag, name="Tower A")
        s.add(job)
        s.flush()
        w.proj = job.id
        a = DBStore(client_id=client.id, code="A" + tag[:3].upper(), name="Central", type="CENTRAL")
        b = DBStore(client_id=client.id, code="B" + tag[:3].upper(), name="Site", type="SITE", project_id=job.id)
        s.add_all([a, b])
        s.flush()
        w.a, w.b = a.id, b.id
        w.item = {}
        for key, name, level in (("cement", "Cement", 0), ("bolts", "Anchor bolts", 10), ("pipe", "GI pipe", 2)):
            it = models.DBItem(client_id=client.id, item_code="%s-%s" % (key.upper(), tag), item_name=name, kind="RM", units_of_measure="nos")
            s.add(it)
            s.flush()
            w.item[key] = it.id
            s.add(DBStoreItemSettings(item_id=it.id, base_uom="nos", reorder_level=D(level)))
        s.flush()

        def put(mtype, store, key, qty, rate=None, doc=("OSTK", 1), project=None):
            return post_movement(s, movement_type=mtype, store_id=store, item_id=w.item[key], qty=D(qty), rate=None if rate is None else D(rate),
                                 txn_date=date.today(), project_id=project, ref_doc_type=doc[0], ref_doc_id=doc[1], ref_line_id=1, user_id=None)

        put(MovementType.OPENING_IN, w.a, "cement", "100", "10")        # 1,000
        put(MovementType.OPENING_IN, w.a, "bolts", "5", "20")           # 100, below its level of 10
        put(MovementType.OPENING_IN, w.b, "pipe", "4", "50")            # 200, then all issued: out of stock
        put(MovementType.ISSUE_OUT, w.b, "pipe", "4", doc=("ISSUE", 7001), project=job.id)        # 200 to the project
        put(MovementType.ISSUE_OUT, w.a, "cement", "30", doc=("ISSUE", 7002), project=job.id)     # 300 to the project
        put(MovementType.ISSUE_OUT, w.a, "cement", "10", doc=("ISSUE", 7003), project=job.id)     # 100, then reversed
        s.flush()
        reverse_document(s, ref_doc_type="ISSUE", ref_doc_id=7003, user_id=None, reason="wrong item")

        budget = models.DBProjectBudget(client_id=client.id, job_id=job.id, code="MAT", name="Material", allocated_amount=1000.0)
        s.add(budget)
        s.flush()
        order = models.DBSubcontractOrder(client_id=client.id, job_id=job.id, wo_number="SC-" + tag, status="APPROVED")
        s.add(order)
        s.flush()
        s.add(models.DBSubcontractItem(order_id=order.id, item_description="Plastering", total_amount=600.0, budget_id=budget.id))
        s.add(DBStoreGrn(client_id=client.id, store_id=w.a, number="GRN-" + tag, status="SUBMITTED"))
        s.add(DBStoreGrn(client_id=client.id, store_id=w.b, number="GRN2-" + tag, status="APPROVED"))
        s.commit()
    return w


def test_the_overview_figures_are_the_records_own(account):
    w = world(account)
    d = account["client"].get(API).json()
    stock = d["stock"]
    # Cement 70 left at 10 (700 - the reversed issue put its 10 back) + bolts 5 at 20 (100); the pipe is gone.
    assert D(stock["total_value"]) == D("800.00")
    assert stock["items_in_stock"] == 2 and stock["stores"] == 2
    assert stock["low_stock"] == 2 and stock["out_of_stock"] == 1
    assert stock["low_rows"][0]["item_id"] == w.item["pipe"], "nothing left comes before merely low"
    with database.SessionLocal() as s:
        held = sum(D(str(b.value)) for b in s.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_([w.a, w.b]), DBStoreStockBalance.qty > 0))
    assert D(stock["total_value"]) == held.quantize(D("0.01"))

    waiting = {(r["label"], r["action"]): r["count"] for r in d["waiting"]}
    assert waiting[("Goods receipts", "to approve")] == 1 and waiting[("Goods receipts", "to post")] == 1

    recent = d["recent"]
    assert recent[0]["reversal"] is True and D(recent[0]["qty"]) == D("10"), "newest first, and a reversal is shown as one"
    assert recent and all(r["doc_path"].startswith("/store/hub/") for r in recent if r["doc_path"])

    row = next(r for r in d["budgets"]["rows"] if r["project_id"] == w.proj)
    # Allocated 1,000; the work order commits 600; the store issued 500 net (the reversed 100 gave its money back).
    assert D(row["allocated"]) == D("1000.00") and D(row["committed"]) == D("600.00") and D(row["store_material"]) == D("500.00")
    assert D(row["left"]) == D("-100.00") and row["over"] is True and row["used_pct"] == 110


def test_one_store_at_a_time(account):
    w = world(account)
    d = account["client"].get(API, params={"store_id": w.b}).json()
    assert d["stock"]["stores"] == 1 and D(d["stock"]["total_value"]) == D("0.00")
    assert {r["label"] for r in d["waiting"]} == {"Goods receipts"} and len(d["waiting"]) == 1


def test_a_storekeeper_sees_only_their_store_and_only_what_their_rights_open(account):
    w = world(account)
    c = account["client"]
    e = make_employee(c, password="Store1Pass")
    c.put(f"/api/employees/{e['id']}/permissions", json={"permission_role": "staff", "permissions": ["store.enquiry.view", "store.inward.view"]})
    with database.SessionLocal() as s:
        s.add(DBStoreUserAssignment(employee_id=e["id"], store_id=w.a, is_active=True))
        s.commit()
    with TestClient(main.app) as staff:
        assert staff.post("/api/employee/auth/login", json={"email": e["email"], "password": "Store1Pass"}).status_code == 200
        d = staff.get(API).json()
        assert d["stock"]["stores"] == 1 and D(d["stock"]["total_value"]) == D("800.00")
        assert d["budgets"] is None, "budgets need the reports right"
        assert d["overdue_returnables"] is None, "returnables need the outward right"
        assert d["waiting"] == [], "seeing receipts is not approving or posting them"
        assert staff.get(API, params={"store_id": w.b}).status_code in (403, 404)


def test_no_store_rights_no_overview(account):
    c = account["client"]
    e = make_employee(c, password="Store1Pass")
    with TestClient(main.app) as staff:
        staff.post("/api/employee/auth/login", json={"email": e["email"], "password": "Store1Pass"})
        assert staff.get(API).status_code == 403
    with TestClient(main.app) as nobody:
        assert nobody.get(API).status_code == 401


def test_another_company_sees_none_of_it(account, second_tenant):
    world(account)
    d = second_tenant.get(API).json()
    assert d["stock"]["stores"] == 0 and D(d["stock"]["total_value"]) == 0
    assert d["recent"] == [] and d["waiting"] == [] and d["budgets"]["rows"] == []
