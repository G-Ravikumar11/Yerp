"""How much work the Store Hub's screens cost the database as the month's documents pile up.

A screen that reads one row at a time answers correctly - just slower with every receipt, issue and order. These count
the statements a screen issues with a few documents and again with many more: the count must stay put. Where a list now
reads in bulk what it used to read row by row, the bulk answer is checked against the row-by-row one.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app import db as database, models
from app.models.store_core import DBStoreBatch, DBStoreItemSettings, DBStoreUomConversion, MovementType
from app.services import store_holds, store_inward
from app.services.stock_ledger import post_movement
from store.test_cutover import _company, _hub, ok, walk
from test_query_cost import Counter

TODAY = date.today().isoformat()


def _materials(w, central, n, tag):
    """n more materials, each in stock below its reorder level, bought in bags on an approved order still to arrive."""
    made = []
    with database.SessionLocal() as s:
        for k in range(n):
            code = "QC-%s-%d" % (tag, k)
            item = models.DBItem(client_id=w["client_id"], kind="RM", item_code=code, item_name="Material %s %d" % (tag, k), units_of_measure="kg")
            s.add(item)
            s.flush()
            s.add(DBStoreItemSettings(item_id=item.id, category="CONSUMABLE", base_uom="kg", reorder_level=5000, min_qty=1000, max_qty=20000, is_batch_tracked=True))
            s.add(DBStoreUomConversion(item_id=item.id, from_uom="bag", to_base_factor=50))
            s.flush()
            post_movement(s, movement_type=MovementType.OPENING_IN, store_id=central["id"], item_id=item.id, qty=Decimal("100"), rate=Decimal("7"),
                          txn_date=date.today() - timedelta(days=5), project_id=None, ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
            po = models.DBPurchaseOrder(client_id=w["client_id"], job_id=w["job"], number="PO-M%s-%d" % (tag, k), supplier_name="Shree Traders", status="Approved", issue_date=TODAY)
            s.add(po)
            s.flush()
            line = models.DBPurchaseOrderLineItem(order_id=po.id, description="Material", item_code=code, uom="bag", qty=40, price=350.0)
            s.add(line)
            s.flush()
            made.append({"item": item.id, "po": po.id, "line": line.id})
        s.commit()
    return made


def _receive(t, central, m, bags=10):
    g = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": m["po"],
                                                 "lines": [{"po_line_id": m["line"], "qty": str(bags), "uom": "bag", "batch_no": "LOT-%d" % m["line"],
                                                            "expiry_date": (date.today() + timedelta(days=60)).isoformat()}]}))
    return walk(t, "inward", "grn", g["id"], "submit", "approve", "post")


def _issue(t, w, central, m):
    d = ok(t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": TODAY, "project_id": w["job"], "received_by_type": "FOREMAN",
                                                    "received_by_name": "Suresh", "lines": [{"item_id": m["item"], "qty": "5", "uom": "kg", "cost_head": "OVERHEAD"}]}))
    return walk(t, "outward", "issue", d["id"], "submit", "approve", "post")


def _transfer(t, central, site, m):
    d = ok(t.post("/api/store/control/transfer", json={"store_id": central["id"], "to_store_id": site["id"], "transfer_date": TODAY,
                                                       "lines": [{"item_id": m["item"], "qty": "5"}]}))
    return walk(t, "control", "transfer", d["id"], "submit", "approve", "post")


SCREENS = ["/api/store/levels/low-stock", "/api/store/inward/po-options", "/api/store/deliveries/pending", "/api/store/dashboard",
           "/api/store/reports/reorder", "/api/store/inward/grn?limit=200", "/api/store/outward/issue?limit=200", "/api/store/control/transfer?limit=200",
           "/api/store/batches?page=1", "/api/store/batches?hold_status=AVAILABLE&page=1"]


def _cost(t):
    out = {}
    for url in SCREENS:
        with Counter() as c:
            assert t.get(url).status_code == 200, url
        out[url] = len(c)
    return out


def test_the_store_screens_cost_the_same_with_three_materials_or_fifteen(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    site = ok(t.post("/api/store/masters/stores", json={"code": "SQ" + tag[:3].upper(), "name": "Site", "type": "SITE", "project_id": w["job"]}))

    def month(ms):
        for m in ms:
            _receive(t, central, m)
            _issue(t, w, central, m)
            _transfer(t, central, site, m)

    first = _materials(w, central, 3, tag + "a")
    month(first)
    few = _cost(t)
    month(_materials(w, central, 12, tag + "b"))
    many = _cost(t)
    grew = {url: (few[url], many[url]) for url in SCREENS if many[url] > few[url] + 3}
    assert not grew, "these screens read row by row (queries with 3 materials, with 15): %s" % grew


def test_the_lot_list_reads_every_lot_as_the_lot_screen_does(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag)
    central = _hub(t, w, tag)
    for m in _materials(w, central, 4, tag):
        _receive(t, central, m)
    with database.SessionLocal() as s:
        lots = s.query(DBStoreBatch).filter(DBStoreBatch.client_id == w["client_id"]).order_by(DBStoreBatch.id).all()
        held = lots[0].id
    ok(t.post("/api/qc/ncrs", json={"store_batch_id": held, "description": "Lumps in bags", "severity": "Minor"}))
    with database.SessionLocal() as s:
        lots = s.query(DBStoreBatch).filter(DBStoreBatch.client_id == w["client_id"]).order_by(DBStoreBatch.id).all()
        one_by_one = [store_holds.batch_view(s, b) for b in lots]
        together = store_holds.batch_views(s, lots)
    assert together == one_by_one
    assert {v["hold_status"] for v in together} == {"On Hold", "Available"}


def test_receipts_against_a_list_of_orders_are_what_each_order_says(account):
    t, tag = account["client"], uuid.uuid4().hex[:6]
    w = _company(account, tag, orders=2)
    central = _hub(t, w, tag)
    made = _materials(w, central, 3, tag)
    _receive(t, central, made[0], bags=15)
    _receive(t, central, made[1], bags=40)                                   # received in full
    with database.SessionLocal() as s:
        orders = [s.get(models.DBPurchaseOrder, m["po"]) for m in made] + [s.get(models.DBPurchaseOrder, p) for p, _l in w["pos"]]
        together = store_inward.po_receipt_summaries(s, orders)[0]
        for o in orders:
            assert together.get(o.id, []) == store_inward.get_po_receipt_summary(s, o.id), o.number
