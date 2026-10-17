"""The Store module end to end, through the API, across all five slices: masters, a goods receipt against a purchase order, an issue to a
project, returns and a lost tool, a transfer with its receipt, a stock count, scrap that deals with the lost tool's write-off request - and then
the reports and the integration reads, which must all agree with the stock the stores hold.

It needs every slice merged, so on a branch that has only some of them it skips itself (the merged tree runs it)."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest

from app import db as database, models
from app.models.store_core import DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion
from app.models.store_reports import DBStoreMaterialNorm
from app.routers import store_control, store_inward, store_masters, store_outward
from app.services import store_integration

D = Decimal
TODAY = date.today().isoformat()

pytestmark = pytest.mark.skipif(
    not (hasattr(store_masters, "add_store") and hasattr(store_inward, "create_grn") and hasattr(store_outward, "create_issue") and hasattr(store_control, "create_transfer")),
    reason="needs P1-P4 merged")


@pytest.fixture(autouse=True)
def _leave_no_stock_behind():
    yield
    with database.SessionLocal() as s:
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
        for model in (DBStoreStockLedger, DBStoreStockBalance, DBStoreItemSettings, DBStoreUomConversion, DBStoreMaterialNorm):
            s.query(model).delete(synchronize_session=False)
        s.commit()


def ok(res):
    assert res.status_code == 200, (res.request.method, res.request.url, res.text)
    return res.json()


def walk(t, base, kind, doc_id, *steps):
    last = None
    for step in steps:
        last = ok(t.post("/api/store/%s/%s/%d/%s" % (base, kind, doc_id, step), json={"reason": "end to end"} if step == "cancel" else None))
    return last


def test_the_whole_store_module_agrees_with_itself(account):
    t = account["client"]
    tag = uuid.uuid4().hex[:6]

    # --- the company's own records the store builds on: a project, its BOQ and work order, a supplier's approved order, items -------------------
    with database.SessionLocal() as s:
        client = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first()
        job = models.DBJob(client_id=client.id, number="P-" + tag, name="Tower A")
        s.add(job)
        s.flush()
        boq = models.DBBoq(client_id=client.id, job_id=job.id, number="B-" + tag, title="Tower A")
        s.add(boq)
        s.flush()
        rev = models.DBBoqRevision(boq_id=boq.id, rev_no=boq.current_rev or 0, label="R0")
        s.add(rev)
        s.flush()
        line = models.DBBoqLine(boq_id=boq.id, revision_id=rev.id, key="k1", kind="item", item_no="1", description="RCC M25 in columns", uom="cum", quantity=10, rate=100.0, amount=1000.0, display_order=1)
        s.add(line)
        wo = models.DBWorkOrder(client_id=client.id, job_id=job.id, number="WO-" + tag, status="Approved", boq_id=boq.id)
        s.add(wo)
        items = {}
        for key, name, uom in (("cement", "Cement OPC", "kg"), ("plate", "Shuttering Plate", "nos")):
            it = models.DBItem(client_id=client.id, kind="RM", item_code="E2E-%s-%s" % (key.upper(), tag), item_name=name, units_of_measure=uom)
            s.add(it)
            s.flush()
            items[key] = it.id
        po = models.DBPurchaseOrder(client_id=client.id, job_id=job.id, number="PO-" + tag, supplier_name="Shree Traders", status="Approved", issue_date=TODAY)
        s.add(po)
        s.flush()
        pl = models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_code="E2E-CEMENT-" + tag, uom="bag", qty=200, price=350.0)
        s.add(pl)
        s.commit()
        project, boq_line, work_order, po_id, po_line = job.id, line.id, wo.id, po.id, pl.id

    # --- P1: stores, item settings and unit conversions ---------------------------------------------------------------------------------------
    central = ok(t.post("/api/store/masters/stores", json={"code": "CS" + tag[:2].upper(), "name": "Central", "type": "CENTRAL"}))
    site = ok(t.post("/api/store/masters/stores", json={"code": "ST" + tag[:2].upper(), "name": "Site", "type": "SITE", "project_id": project}))
    ok(t.put("/api/store/masters/items/%d/settings" % items["cement"], json={"category": "CONSUMABLE", "base_uom": "kg", "reorder_level": "100"}))
    ok(t.put("/api/store/masters/items/%d/conversions/bag" % items["cement"], json={"to_base_factor": "50"}))
    ok(t.put("/api/store/masters/items/%d/settings" % items["plate"], json={"category": "RETURNABLE", "base_uom": "nos"}))

    # --- P2: opening stock for the tools, a goods receipt against the purchase order --------------------------------------------------------------
    opening = ok(t.post("/api/store/inward/opening", json={"store_id": central["id"], "as_on_date": (date.today() - timedelta(days=20)).isoformat(),
                                                             "lines": [{"item_id": items["plate"], "qty": "50", "uom": "nos", "rate": "450"}]}))
    walk(t, "inward", "opening", opening["id"], "submit", "approve", "post")
    grn = ok(t.post("/api/store/inward/grn", json={"store_id": central["id"], "grn_date": TODAY, "po_id": po_id, "challan_no": "CH-7",
                                                    "lines": [{"po_line_id": po_line, "qty": "100", "uom": "bag"}]}))
    posted = walk(t, "inward", "grn", grn["id"], "submit", "approve", "post")
    assert posted["status"] == "POSTED" and posted["lines"][0]["accepted_qty"] == "5000.000" and posted["lines"][0]["rate"] == "7.0000"

    # --- P3: an issue charged to the BOQ item, a part return, tools issued and one lost -------------------------------------------------------------
    issue = ok(t.post("/api/store/outward/issue", json={"store_id": central["id"], "issue_date": TODAY, "project_id": project, "work_order_id": work_order,
                                                          "lines": [{"item_id": items["cement"], "qty": "20", "uom": "bag", "boq_item_id": boq_line}]}))
    issue = walk(t, "outward", "issue", issue["id"], "submit", "approve", "post")
    ret = ok(t.post("/api/store/outward/returns", json={"issue_id": issue["id"], "return_date": TODAY, "lines": [{"issue_line_id": issue["lines"][0]["id"], "qty_returned": "2", "uom": "bag"}]}))
    walk(t, "outward", "returns", ret["id"], "submit", "approve", "post")
    tools = ok(t.post("/api/store/outward/issue/direct", json={"store_id": central["id"], "issue_date": TODAY, "project_id": project, "holder_type": "GANG", "holder_name": "Shuttering gang",
                                                                "lines": [{"item_id": items["plate"], "qty": "10", "cost_head": "TEMPORARY_WORKS"}]}))
    assert tools["status"] == "POSTED" and tools["direct"] is True
    lost = ok(t.post("/api/store/outward/returns", json={"issue_id": tools["id"], "return_date": TODAY, "lines": [{"issue_line_id": tools["lines"][0]["id"], "qty_returned": "6", "qty_lost": "3", "reason": "fell from scaffold"}]}))
    walk(t, "outward", "returns", lost["id"], "submit", "approve", "post")
    requests = ok(t.get("/api/store/outward/writeoffs"))["items"]
    assert len(requests) == 1 and requests[0]["qty"] == "3.000" and ok(t.get("/api/store/outward/returnables"))["items"][0]["qty_outstanding"] == "1.000"

    # --- P4: a transfer to the site store and its receipt, a count, scrap that deals with the write-off request ------------------------------------------
    trf = ok(t.post("/api/store/control/transfer", json={"store_id": central["id"], "to_store_id": site["id"], "transfer_date": TODAY, "lines": [{"item_id": items["cement"], "qty": "10", "uom": "bag"}]}))
    walk(t, "control", "transfer", trf["id"], "submit", "approve", "post")
    assert ok(t.get("/api/store/control/in-transit"))["total"] == 1
    ok(t.post("/api/store/control/transfer/%d/receive" % trf["id"]))
    assert ok(t.get("/api/store/control/in-transit"))["total"] == 0
    count = ok(t.post("/api/store/control/count", json={"store_id": site["id"], "count_date": TODAY}))
    ok(t.post("/api/store/control/count/%d/start" % count["id"]))
    ok(t.put("/api/store/control/count/%d/sheet" % count["id"], json={"rows": [{"item_id": items["cement"], "counted_qty": "490", "uom": "kg", "reason": "bag split"}]}))
    walk(t, "control", "count", count["id"], "submit", "approve", "post")
    scrap = ok(t.post("/api/store/control/scrap", json={"store_id": central["id"], "scrap_date": TODAY, "project_id": project,
                                                         "lines": [{"item_id": items["plate"], "qty": "3", "disposal": "WASTAGE", "reason": "lost on site", "cost_head": "TEMPORARY_WORKS", "writeoff_request_id": requests[0]["id"]}]}))
    posted_scrap = walk(t, "control", "scrap", scrap["id"], "submit", "approve", "post")
    assert posted_scrap["status"] == "POSTED" and ok(t.get("/api/store/outward/writeoffs"))["items"] == []        # P4 closed what P3 raised
    assert ok(t.get("/api/store/outward/writeoffs", params={"status": "CLOSED"}))["items"][0]["closed_ref"] == "SCRAP #%d" % scrap["id"]

    # --- the ledger and the balances agree, everywhere ----------------------------------------------------------------------------------------------
    with database.SessionLocal() as s:
        for store in (central["id"], site["id"]):
            for item in items.values():
                rows = s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id == store, DBStoreStockLedger.item_id == item).order_by(DBStoreStockLedger.id).all()
                bal = s.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store, DBStoreStockBalance.item_id == item).first()
                qty = sum((r.qty_in - r.qty_out for r in rows), D(0))
                value = sum((r.value if r.qty_in else -r.value for r in rows), D(0))
                assert qty == (bal.qty if bal else 0) and value == (bal.value if bal else 0), (store, item)
                assert all(r.running_qty >= 0 for r in rows)

    # cement: 5000 - 1000 issued + 100 back - 500 transferred = 4100 at the central store; the site got 500 and the count found 490
    # tools: 50 - 10 issued + 6 back = 46: the 3 that were lost left at the issue, so writing them off moves no stock
    enquiry = {(r["store_code"], r["item_name"]): r["qty"] for r in ok(t.get("/api/store/enquiry/balances"))["items"]}
    assert enquiry[(central["code"], "Cement OPC")] == "4100.000" and enquiry[(site["code"], "Cement OPC")] == "490.000" and enquiry[(central["code"], "Shuttering Plate")] == "46.000"
    valuation = ok(t.get("/api/store/reports/valuation"))
    assert {(r["store_code"], r["item_name"]): r["qty"] for r in valuation["rows"]} == enquiry
    assert valuation["total_value"] == str(sum((D(r["value"]) for r in valuation["rows"]), D(0)).quantize(D("0.01")))

    # --- the reports and the integration reads ----------------------------------------------------------------------------------------------------------
    movement = ok(t.get("/api/store/reports/movement", params={"from_date": (date.today() - timedelta(days=5)).isoformat()}))
    assert movement["totals"]["closing_value"] == valuation["total_value"]
    assert all(r["closing_value"] == next(v["value"] for v in valuation["rows"] if (v["store_code"], v["item_name"]) == (r["store_code"], r["item_name"])) for r in movement["rows"])
    use = ok(t.get("/api/store/reports/consumption", params={"project_id": project, "group_by": "cost_head"}))
    heads = {g["name"]: g["value"] for g in use["groups"]}
    assert heads["BOQ work"] == "6300.00" and heads["Temporary Works"] == "1800.00"                    # 900 kg at 7; 4 tools at 450 (10 issued, 6 back)
    with database.SessionLocal() as s:
        lines = store_integration.get_project_material_cost(s, project, date(2000, 1, 1), date.today())
        assert sum((l.value for l in lines), D(0)) == D(use["total_value"]) == D(ok(t.get("/api/store/reports/project-cost/%d" % project))["total_value"])
    assert ok(t.get("/api/jobs/%d" % project))["costing"]["store_material"] == float(use["total_value"])
    po_detail = ok(t.get("/api/purchase-orders/%d" % po_id))
    assert po_detail["store_receipt"][0]["accepted_qty"] == "5000.000" and po_detail["store_receipt"][0]["pending_qty"] == "5000.000"
    ok(t.post("/api/store/reports/norms", json={"boq_item_id": boq_line, "item_id": items["cement"], "qty_per_unit": "90", "wastage_pct": "0"}))      # 10 cum x 90 kg = 900 kg
    norm = ok(t.get("/api/store/reports/norm-variance", params={"project_id": project}))
    assert norm["rows"][0]["theoretical_qty"] == "900.000" and norm["rows"][0]["actual_qty"] == "900.000" and norm["rows"][0]["status"] == "OK"
    for report, params in (("valuation", {}), ("movement", {}), ("consumption", {"project_id": project}), ("norm-variance", {"project_id": project}), ("slow-moving", {"days": 1}), ("reorder", {})):
        xl = t.get("/api/store/reports/%s/export" % report, params=params)
        assert xl.status_code == 200 and openpyxl.load_workbook(io.BytesIO(xl.content)).active.max_row >= 2, report
        assert t.get("/api/store/reports/%s/print" % report, params=params).content[:4] == b"%PDF", report
    for kind, doc in (("inward/grn", grn), ("outward/issue", issue), ("control/transfer", trf), ("control/count", count), ("control/scrap", scrap)):
        assert t.get("/api/store/%s/%d/print" % (kind, doc["id"])).content[:4] == b"%PDF", kind
