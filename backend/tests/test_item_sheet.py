"""The project's Item sheet: every material its BOQ needs, from the budget's material rows, added up item by item, beside what
the store and purchase have done about it - and the store's warnings reading the same figures."""
import io
import uuid
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app import db as database, models
from app.models.store_core import DBStore, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion
from app.models.store_outward import DBStoreIndent, DBStoreIndentLine
from app.models.store_reports import DBStoreMaterialNorm
from app.services.stock_ledger import post_movement
from app.services.store_reports import get_theoretical_requirement

from test_budgeting import keyed, put_line

D = Decimal


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    yield
    with database.SessionLocal() as s:
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreUomConversion, DBStoreMaterialNorm, DBStoreIndentLine, DBStoreIndent):
            s.query(model).delete(synchronize_session=False)
        s.commit()


def material(jid, name="Cement OPC", unit="kg"):
    """An item in the master of the project's company: (id, code)."""
    with database.SessionLocal() as s:
        client_id = s.get(models.DBJob, jid).client_id
        it = models.DBItem(client_id=client_id, kind="RM", item_code="IS-%s" % uuid.uuid4().hex[:8].upper(), item_name=name, units_of_measure=unit)
        s.add(it)
        s.commit()
        return it.id, it.item_code


def budget(tenant, jid, key, *rows):
    res = put_line(tenant, jid, key, [dict({"kind": "MATERIAL", "uom": "kg", "rate": 8, "wastage_percent": 0}, **r) for r in rows])
    assert res.status_code == 200, res.text


def sheet(tenant, jid):
    res = tenant.get("/api/jobs/%d/item-sheet" % jid)
    assert res.status_code == 200, res.text
    return res.json()


def row(s, name):
    return next(r for r in s["rows"] if r["item_name"] == name)


def line_id(jid, key):
    with database.SessionLocal() as s:
        boq = s.query(models.DBBoq).filter(models.DBBoq.job_id == jid).first()
        return (s.query(models.DBBoqLine).join(models.DBBoqRevision, models.DBBoqRevision.id == models.DBBoqLine.revision_id)
                .filter(models.DBBoqLine.boq_id == boq.id, models.DBBoqLine.key == key, models.DBBoqRevision.rev_no == boq.current_rev).first().id)


def site_store(jid):
    with database.SessionLocal() as s:
        job = s.get(models.DBJob, jid)
        st = DBStore(client_id=job.client_id, code="S%s" % uuid.uuid4().hex[:5].upper(), name="Site store", type="SITE", project_id=jid)
        s.add(st)
        s.commit()
        return st.id


def test_a_material_on_many_boq_lines_is_one_row_with_its_wastage(tenant):
    jid, k = keyed(tenant)                                   # RCC 120 cum, MAS 60 cum
    cement, code = material(jid)
    budget(tenant, jid, k["RCC"], {"description": "Cement", "item_code": code, "coefficient": 2, "wastage_percent": 5},
           {"description": "River sand", "uom": "cum", "coefficient": 0.5, "rate": 1500})
    budget(tenant, jid, k["MAS"], {"description": "Cement", "item_code": code, "coefficient": 1})
    s = sheet(tenant, jid)
    c = row(s, "Cement OPC")
    assert c["in_master"] and c["uom"] == "kg"
    assert c["required"] == 312.0 and c["without_wastage"] == 300.0         # 120 x 2 x 1.05 + 60 x 1
    assert [(l["key"], l["required"]) for l in c["lines"]] == [(k["RCC"], 252.0), (k["MAS"], 60.0)]
    assert c["value"] == 2496.0 and c["status"] == "To arrange" and c["to_arrange"] == 312.0
    sand = row(s, "River sand")                              # typed without picking it from the item master
    assert not sand["in_master"] and sand["required"] == 60.0 and sand["uom"] == "cum"
    assert s["totals"]["items"] == 2 and s["totals"]["not_in_master"] == 1 and s["totals"]["boq_lines_with_materials"] == 2


def test_the_budgets_unit_is_turned_into_the_items_own(tenant):
    jid, k = keyed(tenant)
    cement, code = material(jid)
    with database.SessionLocal() as s:
        s.add(DBStoreUomConversion(item_id=cement, from_uom="bag", to_base_factor=50))
        s.commit()
    budget(tenant, jid, k["RCC"], {"description": "Cement", "item_code": code, "uom": "bag", "coefficient": 0.1, "rate": 400})
    c = row(sheet(tenant, jid), "Cement OPC")
    assert c["required"] == 600.0 and c["uom"] == "kg" and not c["unit_notes"]     # 120 x 0.1 bag = 12 bags = 600 kg
    assert c["value"] == 4800.0


def test_the_store_and_purchase_figures_stand_beside_the_need(tenant):
    jid, k = keyed(tenant)
    cement, code = material(jid)
    budget(tenant, jid, k["RCC"], {"description": "Cement", "item_code": code, "coefficient": 2})        # 240 kg
    store = site_store(jid)
    rcc = line_id(jid, k["RCC"])
    with database.SessionLocal() as s:
        job = s.get(models.DBJob, jid)
        common = dict(store_id=store, item_id=cement, txn_date=date.today(), project_id=jid, ref_line_id=1, user_id=None)
        post_movement(s, movement_type="OPENING_IN", qty=D(100), rate=D(8), ref_doc_type="OPENING", ref_doc_id=1, **common)
        post_movement(s, movement_type="ISSUE_OUT", qty=D(40), rate=None, ref_doc_type="ISSUE", ref_doc_id=1, boq_item_id=rcc, **common)
        po = models.DBPurchaseOrder(client_id=job.client_id, job_id=jid, number="PO-IS1", status="Approved")
        draft = models.DBPurchaseOrder(client_id=job.client_id, job_id=jid, number="PO-IS2", status="Draft")
        s.add_all([po, draft])
        s.flush()
        s.add_all([models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_id=cement, uom="kg", qty=50, price=8),
                   models.DBPurchaseOrderLineItem(order_id=draft.id, description="Cement", item_id=cement, uom="kg", qty=999, price=8)])
        ind = DBStoreIndent(client_id=job.client_id, store_id=store, number="IND-IS1", status="OPEN", project_id=jid, boq_item_id=rcc)
        s.add(ind)
        s.flush()
        s.add(DBStoreIndentLine(indent_id=ind.id, line_no=1, item_id=cement, qty=D(35), approved_qty=D(30)))
        s.commit()
    c = row(sheet(tenant, jid), "Cement OPC")
    assert (c["indented"], c["ordered"], c["on_way"], c["issued"], c["at_site"]) == (30.0, 50.0, 50.0, 40.0, 60.0)
    assert c["to_arrange"] == 90.0                             # 240 - 40 issued - 60 at site - 50 on its way
    assert c["lines"][0]["issued"] == 40.0


def test_more_issued_than_needed_is_called_out(tenant):
    jid, k = keyed(tenant)
    cement, code = material(jid)
    budget(tenant, jid, k["EXC"], {"description": "Cement", "item_code": code, "coefficient": 0.01})     # 5 kg
    store = site_store(jid)
    with database.SessionLocal() as s:
        common = dict(store_id=store, item_id=cement, txn_date=date.today(), project_id=jid, ref_line_id=1, user_id=None)
        post_movement(s, movement_type="OPENING_IN", qty=D(20), rate=D(8), ref_doc_type="OPENING", ref_doc_id=1, **common)
        post_movement(s, movement_type="ISSUE_OUT", qty=D(9), rate=None, ref_doc_type="ISSUE", ref_doc_id=1, **common)
        s.commit()
    c = row(sheet(tenant, jid), "Cement OPC")
    assert c["status"] == "Issued past need" and c["to_arrange"] == 0.0


def test_the_stores_issue_warning_reads_the_budget_where_no_norm_is_set(tenant):
    jid, k = keyed(tenant)
    cement, code = material(jid)
    rcc = line_id(jid, k["RCC"])
    with database.SessionLocal() as s:
        assert get_theoretical_requirement(s, rcc, cement) is None                    # nothing says what it needs
    budget(tenant, jid, k["RCC"], {"description": "Cement", "item_code": code, "coefficient": 2, "wastage_percent": 5})
    with database.SessionLocal() as s:
        assert get_theoretical_requirement(s, rcc, cement) == D("252.000")             # the budget: 120 x 2 x 1.05
        client_id = s.get(models.DBJob, jid).client_id
        s.add(DBStoreMaterialNorm(client_id=client_id, boq_item_id=rcc, item_id=cement, qty_per_unit=D(3), wastage_pct=D(0)))
        s.commit()
        assert get_theoretical_requirement(s, rcc, cement) == D("360.000")             # a norm, where set, is the store's answer


def test_an_indent_past_the_need_is_warned_and_not_stopped(tenant):
    from app.services.item_sheet import indent_warnings
    jid, k = keyed(tenant)
    cement, code = material(jid)
    budget(tenant, jid, k["RCC"], {"description": "Cement", "item_code": code, "coefficient": 1})        # 120 kg
    store = site_store(jid)
    with database.SessionLocal() as s:
        client_id = s.get(models.DBJob, jid).client_id
        first = DBStoreIndent(client_id=client_id, store_id=store, number="IND-A", status="OPEN", project_id=jid)
        second = DBStoreIndent(client_id=client_id, store_id=store, number="IND-B", status="SUBMITTED", project_id=jid)
        s.add_all([first, second])
        s.flush()
        s.add(DBStoreIndentLine(indent_id=first.id, line_no=1, item_id=cement, qty=D(100), approved_qty=D(100)))
        mine = DBStoreIndentLine(indent_id=second.id, line_no=1, item_id=cement, qty=D(15))
        s.add(mine)
        s.flush()
        assert indent_warnings(s, second, [mine]) == []                                  # 115 of 120
        mine.qty = D(30)
        s.flush()
        (w,) = indent_warnings(s, second, [mine])
        assert "Cement OPC" in w and "130" in w and "120" in w
        s.rollback()


def test_the_sheet_downloads_as_a_workbook(tenant):
    jid, k = keyed(tenant)
    _cement, code = material(jid)
    budget(tenant, jid, k["RCC"], {"description": "Cement", "item_code": code, "coefficient": 2})
    res = tenant.get("/api/jobs/%d/item-sheet.xlsx" % jid)
    assert res.status_code == 200, res.text
    text = " ".join(str(c.value) for r in openpyxl.load_workbook(io.BytesIO(res.content)).active.iter_rows() for c in r if c.value is not None)
    assert "ITEM SHEET" in text and "Cement OPC" in text and "240" in text


def test_a_project_without_a_boq_has_an_empty_sheet_and_another_business_none(tenant, second_tenant):
    job = tenant.post("/api/jobs", json={"name": "No BOQ yet", "customer_name": "X"}).json()
    jid = job.get("id") or job["job"]["id"]
    s = sheet(tenant, jid)
    assert s["boq"] is False and s["rows"] == []
    assert second_tenant.get("/api/jobs/%d/item-sheet" % jid).status_code == 404
