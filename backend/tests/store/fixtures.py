"""Seed data for the Store module's tests: one company with a project, a work order of two BOQ items, a supplier with an
approved purchase order of three lines, a subcontractor, six staff with different rights, two stores (central and
the project's site store), ten items and opening stock posted the proper way, through post_movement.

    from store.fixtures import db, store_world   # noqa: F401  - a conftest.py here would shadow tests/conftest.py

    def test_something(store_world, db):
        w = store_world
        get_balance(db, w.central_id, w.item["cement"])

Build one in a script with `build_store_world(session)` - it commits, and `drop_store_world(session, world)` removes it.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import db as database, models
from app.models.store_core import (
    DBStore, DBStoreBatch, DBStoreBatchBalance, DBStoreBin, DBStoreControlSetting, DBStoreDocSequence, DBStoreFreeze, DBStoreItemSettings,
    DBStoreLedgerBatch, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.services.stock_ledger import post_movement

D = Decimal
OPENING_DOC = ("OPENING", 1)


def kg_per_nos(diameter_mm: int, length_m: int = 12) -> Decimal:
    """TMT bar weight: d squared over 162 kg per metre, times the bar length (12 m)."""
    return (D(diameter_mm * diameter_mm) / D(162) * D(length_m)).quantize(D("0.000001"))


# key, name, base unit, category, opening qty at the central store, rate per base unit, conversions {unit: factor}
ITEMS = [
    ("cement", "Cement OPC 53", "kg", "CONSUMABLE", 5000, "7.0000", {"bag": D(50), "MT": D(1000)}),
    ("tmt12", "TMT Steel 12mm", "kg", "CONSUMABLE", 2000, "62.0000", {"nos": kg_per_nos(12), "MT": D(1000)}),
    ("tmt16", "TMT Steel 16mm", "kg", "CONSUMABLE", 3000, "62.0000", {"nos": kg_per_nos(16), "MT": D(1000)}),
    ("sand", "River Sand", "cum", "CONSUMABLE", 100, "1800.0000", {}),
    ("aggregate", "Aggregate 20mm", "cum", "CONSUMABLE", 80, "1500.0000", {}),
    ("bricks", "Red Bricks", "nos", "CONSUMABLE", 20000, "8.0000", {}),
    ("binding_wire", "Binding Wire", "kg", "CONSUMABLE", 200, "85.0000", {}),
    ("shuttering", "Shuttering Plate", "nos", "RETURNABLE", 150, "450.0000", {}),
    ("helmet", "Safety Helmet", "nos", "CONSUMABLE", 60, "180.0000", {}),
    ("diesel", "Diesel", "litre", "CONSUMABLE", 1000, "92.0000", {}),
]

_VIEWS = ["store.%s.view" % s for s in ("masters", "enquiry", "inward", "outward", "control", "reports")]
# staff key -> (stores they are assigned to, rights)
STAFF = {
    "central_keeper": (["central"], _VIEWS + ["store.inward.create", "store.inward.post", "store.outward.create", "store.outward.post"]),
    "site_keeper": (["site"], _VIEWS + ["store.inward.create", "store.outward.create", "store.outward.post"]),
    "approver": (["central", "site"], _VIEWS + ["store.inward.approve", "store.outward.approve", "store.control.approve",
                                                 "store.control.approve_high_value"]),
    "viewer": (["site"], ["store.inward.view", "store.outward.view"]),
    "unassigned": ([], _VIEWS + ["store.inward.create"]),
    "admin": ([], ["store.admin"]),
}


@dataclass
class StoreWorld:
    client_id: int
    project_id: int
    work_order_id: int
    boq_item_ids: list
    supplier_id: int
    po_id: int
    po_line_ids: list
    subcontractor_id: int
    central_id: int
    site_id: int
    bin_id: int
    item: dict = field(default_factory=dict)       # key -> item id
    staff: dict = field(default_factory=dict)      # key -> employee id
    opening: dict = field(default_factory=dict)    # key -> opening qty at the central store


def build_store_world(db) -> StoreWorld:
    tag = uuid.uuid4().hex[:8]
    client = models.DBClient(email="store-%s@example.com" % tag, password_hash="x", company_name="Store Test Co", is_active=True)
    db.add(client)
    db.flush()
    cid = client.id
    job = models.DBJob(client_id=cid, number="P-%s" % tag, name="Tower A")
    db.add(job)
    db.flush()
    boq = models.DBBoq(client_id=cid, job_id=job.id, number="BOQ-%s" % tag, title="Tower A")
    db.add(boq)
    db.flush()
    rev = models.DBBoqRevision(boq_id=boq.id, rev_no=0, label="R0")
    db.add(rev)
    db.flush()
    boq_lines = [models.DBBoqLine(boq_id=boq.id, revision_id=rev.id, key="k%d" % i, kind="item", item_no=str(i), description=d,
                                  uom=u, quantity=q, rate=r, amount=q * r)
                 for i, (d, u, q, r) in enumerate([("RCC M25 in columns", "cum", 120, 7500.0), ("Steel reinforcement Fe500D", "MT", 40, 68000.0)], 1)]
    db.add_all(boq_lines)
    wo = models.DBWorkOrder(client_id=cid, job_id=job.id, number="WO-%s" % tag, status="Approved", boq_id=boq.id)
    db.add(wo)
    supplier = models.DBSupplier(client_id=cid, code="S-%s" % tag, name="Shree Cement Traders")
    contractor = models.DBContractor(client_id=cid, vendor_code="V-%s" % tag, company_name="Sai Steel Fixers")
    db.add_all([supplier, contractor])
    db.flush()

    items = {}
    for key, name, base, cat, _qty, _rate, conv in ITEMS:
        it = models.DBItem(client_id=cid, kind="RM", item_code="ST-%s-%s" % (key.upper(), tag), item_name=name, units_of_measure=base)
        db.add(it)
        db.flush()
        items[key] = it.id
        db.add(DBStoreItemSettings(item_id=it.id, category=cat, base_uom=base, reorder_level=10, min_qty=5, max_qty=100000))
        db.add_all([DBStoreUomConversion(item_id=it.id, from_uom=u, to_base_factor=f) for u, f in conv.items()])

    po = models.DBPurchaseOrder(client_id=cid, job_id=job.id, number="PO-%s" % tag, supplier_name=supplier.name, status="Approved",
                                issue_date=str(date.today() - timedelta(days=20)))
    db.add(po)
    db.flush()
    lines = [models.DBPurchaseOrderLineItem(order_id=po.id, description=n, item_code="ST-%s-%s" % (k.upper(), tag), uom=u, qty=q, price=p)
             for n, k, u, q, p in [("Cement OPC 53", "cement", "bag", 400, 350.0), ("TMT Steel 12mm", "tmt12", "kg", 1500, 62.0),
                                   ("TMT Steel 16mm", "tmt16", "kg", 2500, 62.0)]]
    db.add_all(lines)

    central = DBStore(client_id=cid, code="CS01", name="Central Store", type="CENTRAL", address="Head yard")
    site = DBStore(client_id=cid, code="ST01", name="Tower A Site Store", type="SITE", project_id=job.id)
    db.add_all([central, site])
    db.flush()
    bin_ = DBStoreBin(store_id=central.id, code="A-01", description="Cement shed")
    db.add(bin_)
    by_name = {"central": central.id, "site": site.id}

    staff = {}
    for key, (where, rights) in STAFF.items():
        emp = models.DBEmployee(client_id=cid, first_name=key.replace("_", " ").title(), last_name="Test",
                                email="%s-%s@example.com" % (key, tag), permission_role="staff", extra_permissions=",".join(rights))
        db.add(emp)
        db.flush()
        staff[key] = emp.id
        db.add_all([DBStoreUserAssignment(store_id=by_name[w], employee_id=emp.id) for w in where])

    day = date.today() - timedelta(days=30)
    opening = {}
    for key, _n, _b, _c, qty, rate, _conv in ITEMS:
        post_movement(db, movement_type=MovementType.OPENING_IN, store_id=central.id, item_id=items[key], qty=D(qty), rate=D(rate),
                      txn_date=day, project_id=None, ref_doc_type=OPENING_DOC[0], ref_doc_id=OPENING_DOC[1], ref_line_id=None, user_id=None)
        opening[key] = D(qty)
    db.commit()
    return StoreWorld(client_id=cid, project_id=job.id, work_order_id=wo.id, boq_item_ids=[b.id for b in boq_lines], supplier_id=supplier.id,
                      po_id=po.id, po_line_ids=[l.id for l in lines], subcontractor_id=contractor.id, central_id=central.id, site_id=site.id,
                      bin_id=bin_.id, item=items, staff=staff, opening=opening)


def drop_store_world(db, w: StoreWorld):
    """Remove everything build_store_world made, children first (Postgres enforces the order SQLite does not)."""
    db.rollback()
    stores = [w.central_id, w.site_id]
    items = list(w.item.values())
    led = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(stores))
    db.query(DBStoreLedgerBatch).filter(DBStoreLedgerBatch.ledger_id.in_(led.with_entities(DBStoreStockLedger.id))).delete(synchronize_session=False)
    db.query(DBStoreBatchBalance).filter(DBStoreBatchBalance.store_id.in_(stores)).delete(synchronize_session=False)
    led.filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
    led.delete(synchronize_session=False)
    for model, col in ((DBStoreStockBalance, DBStoreStockBalance.store_id), (DBStoreFreeze, DBStoreFreeze.store_id),
                       (DBStoreDocSequence, DBStoreDocSequence.store_id), (DBStoreUserAssignment, DBStoreUserAssignment.store_id),
                       (DBStoreBin, DBStoreBin.store_id)):
        db.query(model).filter(col.in_(stores)).delete(synchronize_session=False)
    db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id.in_(items)).delete(synchronize_session=False)
    db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(items)).delete(synchronize_session=False)
    db.query(DBStore).filter(DBStore.id.in_(stores)).delete(synchronize_session=False)
    db.query(DBStoreBatch).filter(DBStoreBatch.client_id == w.client_id).delete(synchronize_session=False)
    db.query(DBStoreControlSetting).filter(DBStoreControlSetting.client_id == w.client_id).delete(synchronize_session=False)
    db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == w.po_id).delete(synchronize_session=False)
    db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id == w.po_id).delete(synchronize_session=False)
    db.query(models.DBItem).filter(models.DBItem.id.in_(items)).delete(synchronize_session=False)
    db.query(models.DBEmployee).filter(models.DBEmployee.client_id == w.client_id).delete(synchronize_session=False)
    db.query(models.DBContractor).filter(models.DBContractor.id == w.subcontractor_id).delete(synchronize_session=False)
    db.query(models.DBSupplier).filter(models.DBSupplier.id == w.supplier_id).delete(synchronize_session=False)
    db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == w.work_order_id).delete(synchronize_session=False)
    boq = db.query(models.DBBoq).filter(models.DBBoq.job_id == w.project_id).first()
    if boq:
        db.query(models.DBBoqLine).filter(models.DBBoqLine.boq_id == boq.id).delete(synchronize_session=False)
        db.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id == boq.id).delete(synchronize_session=False)
        db.delete(boq)
    db.query(models.DBJob).filter(models.DBJob.id == w.project_id).delete(synchronize_session=False)
    db.query(models.DBClient).filter(models.DBClient.id == w.client_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def db():
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def store_world(db):
    world = build_store_world(db)
    try:
        yield world
    finally:
        drop_store_world(db, world)
