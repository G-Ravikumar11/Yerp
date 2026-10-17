"""P5 - reports, norms and integration, plus the end-to-end run through every slice (GRN -> issue -> return -> transfer -> count -> scrap)."""
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from conftest import make_employee

from app import db as database, models
from app.models.store_control import (
    DBStoreAdjustment, DBStoreAdjustmentLine, DBStoreControlLog, DBStoreCount, DBStoreCountLine, DBStoreScrap, DBStoreScrapLine,
    DBStoreTransfer, DBStoreTransferLine,
)
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreDocSequence, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger,
    DBStoreUomConversion, DBStoreUserAssignment, MovementType,
)
from app.models.store_inward import (
    DBStoreGrn, DBStoreGrnLine, DBStoreInwardLog, DBStorePurchaseReturn, DBStorePurchaseReturnLine,
)
from app.models.store_outward import (
    DBStoreIssue, DBStoreIssueLine, DBStoreIssueReturn, DBStoreIssueReturnLine, DBStoreOutwardLog, DBStoreRequisition,
    DBStoreRequisitionLine, DBStoreWriteoffRequest,
)
from app.models.store_reports import DBStoreConsumptionNorm, DBStoreRecoveryLink
from app.services.stock_ledger import get_balance, post_movement
from app.services.store_integration import get_project_material_cost, sync_subcon_recoveries
from app.services.store_reports import get_theoretical_requirement

D = Decimal
R = "/api/store/reports"
VIEW = ["store.%s.view" % s for s in ("masters", "enquiry", "reports")]


@pytest.fixture(autouse=True)
def _clean(account):
    yield
    with database.SessionLocal() as s:
        cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        stores = [i for (i,) in s.query(DBStore.id).filter(DBStore.client_id == cid).all()]
        items = [i for (i,) in s.query(models.DBItem.id).filter(models.DBItem.client_id == cid).all()]
        s.query(DBStoreRecoveryLink).filter(DBStoreRecoveryLink.client_id == cid).delete(synchronize_session=False)
        s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == cid).delete(synchronize_session=False)
        s.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.client_id == cid).delete(synchronize_session=False)
        s.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == cid).delete(synchronize_session=False)
        for model, line, fk, t, log in (
                (DBStoreTransfer, DBStoreTransferLine, DBStoreTransferLine.transfer_id, "TRF", DBStoreControlLog), (DBStoreCount, DBStoreCountLine, DBStoreCountLine.count_id, "CNT", DBStoreControlLog),
                (DBStoreAdjustment, DBStoreAdjustmentLine, DBStoreAdjustmentLine.adjustment_id, "ADJ", DBStoreControlLog), (DBStoreScrap, DBStoreScrapLine, DBStoreScrapLine.scrap_id, "SCR", DBStoreControlLog),
                (DBStoreGrn, DBStoreGrnLine, DBStoreGrnLine.grn_id, "GRN", DBStoreInwardLog), (DBStorePurchaseReturn, DBStorePurchaseReturnLine, DBStorePurchaseReturnLine.return_id, "PRN", DBStoreInwardLog),
                (DBStoreRequisition, DBStoreRequisitionLine, DBStoreRequisitionLine.requisition_id, "MRQ", DBStoreOutwardLog), (DBStoreIssue, DBStoreIssueLine, DBStoreIssueLine.issue_id, "ISSUE", DBStoreOutwardLog)):
            ids = [i for (i,) in s.query(model.id).filter(model.client_id == cid).all()]
            if model is DBStoreIssue:
                rt = [i for (i,) in s.query(DBStoreIssueReturn.id).filter(DBStoreIssueReturn.client_id == cid).all()]
                s.query(DBStoreOutwardLog).filter(DBStoreOutwardLog.doc_type == "RTN", DBStoreOutwardLog.doc_id.in_(rt)).delete(synchronize_session=False)
                s.query(DBStoreWriteoffRequest).filter(DBStoreWriteoffRequest.client_id == cid).delete(synchronize_session=False)
                s.query(DBStoreIssueReturnLine).filter(DBStoreIssueReturnLine.return_id.in_(rt)).delete(synchronize_session=False)
                s.query(DBStoreIssueReturn).filter(DBStoreIssueReturn.id.in_(rt)).delete(synchronize_session=False)
            s.query(log).filter(log.doc_type == t, log.doc_id.in_(ids)).delete(synchronize_session=False)
            s.query(line).filter(fk.in_(ids)).delete(synchronize_session=False)
            s.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
        s.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreStockBalance, DBStoreFreeze, DBStoreUserAssignment, DBStoreBin, DBStoreDocSequence):
            s.query(model).filter(model.store_id.in_(stores)).delete(synchronize_session=False)
        for model in (DBStoreUomConversion, DBStoreItemSettings):
            s.query(model).filter(model.item_id.in_(items)).delete(synchronize_session=False)
        s.query(DBStore).filter(DBStore.id.in_(stores)).delete(synchronize_session=False)
        pos = [i for (i,) in s.query(models.DBPurchaseOrder.id).filter(models.DBPurchaseOrder.client_id == cid).all()]
        s.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id.in_(pos)).delete(synchronize_session=False)
        s.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id.in_(pos)).delete(synchronize_session=False)
        s.query(models.DBContractor).filter(models.DBContractor.client_id == cid).delete(synchronize_session=False)
        s.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == cid).delete(synchronize_session=False)
        boqs = [i for (i,) in s.query(models.DBBoq.id).filter(models.DBBoq.client_id == cid).all()]
        s.query(models.DBBoqLine).filter(models.DBBoqLine.boq_id.in_(boqs)).delete(synchronize_session=False)
        s.query(models.DBBoqRevision).filter(models.DBBoqRevision.boq_id.in_(boqs)).delete(synchronize_session=False)
        s.query(models.DBBoq).filter(models.DBBoq.id.in_(boqs)).delete(synchronize_session=False)
        s.query(models.DBJob).filter(models.DBJob.client_id == cid).delete(synchronize_session=False)
        s.commit()


class W:
    pass


def seed(account):
    """Project + work order (BOQ item 10 cum), a subcontractor with an order, cement (kg, 1 bag = 50 kg), a PO for 400 bags, two stores."""
    o = account["client"]
    w = W()
    tag = uuid.uuid4().hex[:6]
    with database.SessionLocal() as s:
        w.cid = s.query(models.DBClient).filter(models.DBClient.email == account["email"]).first().id
        job = models.DBJob(client_id=w.cid, number="P-" + tag, name="Tower A")
        s.add(job)
        s.flush()
        boq = models.DBBoq(client_id=w.cid, job_id=job.id, number="B-" + tag, title="Tower A")
        s.add(boq)
        s.flush()
        rev = models.DBBoqRevision(boq_id=boq.id, rev_no=0, label="R0")
        s.add(rev)
        s.flush()
        line = models.DBBoqLine(boq_id=boq.id, revision_id=rev.id, key="k1", kind="item", item_no="1", description="RCC M25", uom="cum", quantity=10, rate=100, amount=1000)
        wo = models.DBWorkOrder(client_id=w.cid, job_id=job.id, number="WO-" + tag, status="Approved", boq_id=boq.id)
        sub = models.DBContractor(client_id=w.cid, vendor_code="V-" + tag, company_name="Sai Steel Fixers")
        cement = models.DBItem(client_id=w.cid, kind="RM", item_code="CEM-" + tag, item_name="Cement", units_of_measure="kg")
        s.add_all([line, wo, sub, cement])
        s.flush()
        s.add_all([DBStoreItemSettings(item_id=cement.id, base_uom="kg", reorder_level=3000, max_qty=10000), DBStoreUomConversion(item_id=cement.id, from_uom="bag", to_base_factor=50)])
        order = models.DBSubcontractOrder(client_id=w.cid, wo_number="SC-" + tag, status="Approved", contractor_id=sub.id, job_id=job.id)
        po = models.DBPurchaseOrder(client_id=w.cid, job_id=job.id, number="PO-" + tag, supplier_name="Shree Cement", status="Approved", issue_date=str(date.today()), needed_by=str(date.today() + timedelta(days=9)))
        s.add_all([order, po])
        s.flush()
        pl = models.DBPurchaseOrderLineItem(order_id=po.id, description="Cement", item_code=cement.item_code, uom="bag", qty=400, price=350.0)
        s.add(pl)
        s.commit()
        w.job, w.boq1, w.wo, w.sub, w.cement, w.po, w.pl, w.order = job.id, line.id, wo.id, sub.id, cement.id, po.id, pl.id, order.id
    mk = lambda name, typ, pid: o.post("/api/store/masters/stores", json={"code": name + uuid.uuid4().hex[:3].upper(), "name": name, "type": typ, "project_id": pid}).json()["id"]   # noqa: E731
    w.central, w.site = mk("CEN", "CENTRAL", None), mk("SIT", "SITE", w.job)
    return w


def step(o, path, *actions):
    res = None
    for a in actions:
        res = o.post("%s/%s" % (path, a), json={"reason": "because"} if a == "cancel" else {})
        assert res.status_code == 200, (path, a, res.text)
    return res.json()


def bal(store, item):
    with database.SessionLocal() as s:
        b = get_balance(s, store, item)
        return b.qty, b.value


def run(o, code, **params):
    res = o.get("%s/run/%s" % (R, code), params=params)
    assert res.status_code == 200, res.text
    return res.json()


def by(rep, key, value):
    return [r for r in rep["rows"] if r.get(key) == value]


def flow(o, w):
    """The whole store life of one lot of cement."""
    g = o.post("/api/store/inward/grn", json={"store_id": w.central, "po_id": w.po, "lines": [{"po_line_id": w.pl, "qty": "200", "uom": "bag"}]}).json()      # 10,000 kg @ 7
    step(o, "/api/store/inward/grn/%d" % g["id"], "submit", "approve", "post")
    t = o.post("/api/store/control/transfers", json={"store_id": w.central, "to_store_id": w.site, "lines": [{"item_id": w.cement, "qty": "4000"}]}).json()
    step(o, "/api/store/control/transfers/%d" % t["id"], "submit", "approve", "post")
    assert o.post("/api/store/control/transfers/%d/receive" % t["id"], json={}).status_code == 200
    i = o.post("/api/store/outward/issues", json={"store_id": w.site, "work_order_id": w.wo, "boq_item_id": w.boq1, "lines": [{"item_id": w.cement, "qty": "1000"}]}).json()
    step(o, "/api/store/outward/issues/%d" % i["id"], "submit", "approve", "post")
    sc = o.post("/api/store/outward/issues", json={"store_id": w.site, "issue_type": "SUBCONTRACTOR", "subcontractor_id": w.sub, "project_id": w.job,
                                                   "lines": [{"item_id": w.cement, "qty": "300", "chargeable": True, "recovery_rate": "8"}]}).json()
    step(o, "/api/store/outward/issues/%d" % sc["id"], "submit", "approve", "post")
    rt = o.post("/api/store/outward/returns", json={"store_id": w.site, "issue_id": i["id"], "lines": [{"issue_line_id": i["lines"][0]["id"], "qty": "100"}]}).json()
    step(o, "/api/store/outward/returns/%d" % rt["id"], "submit", "approve", "post")
    return {"grn": g, "trf": t, "issue": i, "subcon": sc, "ret": rt}


def test_end_to_end_through_every_slice_and_the_reports_agree(account):
    o = account["client"]
    w = seed(account)
    f = flow(o, w)
    # 10,000 in; 4,000 to site; site issued 1,000 (-100 back) and 300 to the subcontractor
    assert bal(w.central, w.cement) == (D("6000"), D("42000")) and bal(w.site, w.cement) == (D("2800"), D("19600"))

    val = run(o, "stock-valuation")
    assert val["totals"]["value"] == "61600.00" and {r["store"][:3]: r["qty"] for r in val["rows"]} == {"CEN": "6000.000", "SIT": "2800.000"}
    assert run(o, "stock-valuation", as_on=str(date.today() - timedelta(days=1)))["rows"] == []                       # nothing the day before
    assert run(o, "stock-valuation", store_id=w.site)["totals"]["value"] == "19600.00"

    mv = run(o, "stock-movement", **{"from": str(date.today()), "to": str(date.today()), "store_id": w.site})
    row = mv["rows"][0]
    assert (row["oq"], row["rq"], row["iq"], row["cq"]) == ("0.000", "4100.000", "1300.000", "2800.000")            # received 4,000 + the 100 returned
    assert mv["totals"]["cv"] == "19600.00"
    assert o.get(R + "/run/stock-movement").status_code == 400                                                       # needs a period

    cons = run(o, "consumption", project_id=w.job)
    assert cons["totals"]["value"] == "8400.00"                                                                       # (900 + 300) kg at 7
    assert f["grn"]["status"] == "DRAFT" and f["ret"]["status"] == "DRAFT"                                             # the documents as created; the flow posted them


def test_consumption_nets_returns_and_compares_with_norms(account):
    o = account["client"]
    w = seed(account)
    flow(o, w)
    detail = run(o, "consumption", project_id=w.job)
    site = [r for r in detail["rows"] if r["boq"] != "—"][0]
    assert site["qty"] == "900.000" and site["value"] == "6300.00" and site["theory"] == ""                          # 1,000 issued less 100 back
    assert detail["totals"]["value"] == "8400.00"                                                                      # plus 300 kg to the subcontractor
    assert o.put(R + "/norms", json={"boq_item_id": w.boq1, "item_id": w.cement, "qty_per_unit": "80", "wastage_pct": "5"}).json()["theoretical"] == "840.000"      # 10 cum x 80 kg x 1.05
    with database.SessionLocal() as s:
        assert get_theoretical_requirement(s, w.boq1, w.cement) == D("840.000") and get_theoretical_requirement(s, w.boq1, 99999) is None
    site = [r for r in run(o, "consumption", project_id=w.job)["rows"] if r["boq"] != "—"][0]
    assert (site["theory"], site["variance"]) == ("840.000", "60.000")                                                 # 60 kg over
    assert run(o, "consumption", project_id=w.job, group_by="cost_head")["totals"]["value"] == "8400.00"
    assert run(o, "consumption", project_id=w.job, group_by="item")["rows"][0]["qty"] == "1200.000"
    assert o.get(R + "/run/consumption", params={"project_id": w.job, "group_by": "nope"}).status_code == 400
    assert o.get(R + "/run/consumption").status_code == 400
    assert o.put(R + "/norms", json={"boq_item_id": w.boq1, "item_id": w.cement, "qty_per_unit": "0"}).status_code == 400
    assert o.put(R + "/norms", json={"boq_item_id": 999999, "item_id": w.cement, "qty_per_unit": "1"}).status_code == 404
    nid = o.get(R + "/norms", params={"work_order_id": w.wo}).json()["rows"][0]["id"]
    assert o.delete("%s/norms/%d" % (R, nid)).json()["deleted"]

    with database.SessionLocal() as s:
        lines = get_project_material_cost(s, w.job, None, None)
        assert sum(l.value for l in lines) == D("8400.00") and {l.cost_head for l in lines} == {None}
        assert get_project_material_cost(s, w.job, date.today() + timedelta(days=1), None) == []
    pc = o.get(R + "/integration/project-cost", params={"project_id": w.job}).json()
    assert pc["total"] == "8400.00" and len(pc["lines"]) == 2


def test_other_slices_reports(account):
    o = account["client"]
    w = seed(account)
    f = flow(o, w)
    sub = run(o, "subcon-material", subcontractor_id=w.sub)
    assert sub["rows"][0]["issued"] == "300.000" and sub["totals"]["recovery"] == "2400.00"
    po = run(o, "po-pending")
    assert po["rows"][0]["pending"] == "10000.000" and po["rows"][0]["received"] == "10000.000"                       # 400 bags ordered (20,000 kg), 200 bags (10,000) received
    t2 = o.post("/api/store/control/transfers", json={"store_id": w.central, "to_store_id": w.site, "lines": [{"item_id": w.cement, "qty": "500"}]}).json()
    step(o, "/api/store/control/transfers/%d" % t2["id"], "submit", "approve", "post")
    assert run(o, "in-transit")["rows"][0]["qty"] == "500.000"
    sh = o.post("/api/store/outward/issues", json={"store_id": w.site, "project_id": w.job, "holder_type": "GANG", "holder_name": "Carpenters",
                                                    "expected_return_date": str(date.today() - timedelta(days=2)), "lines": [{"item_id": w.cement, "qty": "10"}]})
    assert sh.status_code == 201                                                                                       # not returnable: cement is a consumable
    assert run(o, "returnables")["rows"] == []
    reorder = run(o, "reorder")
    assert [r["store"][:3] for r in reorder["rows"]] == ["SIT"]                                                        # the site holds 2,800 against a level of 3,000
    sc = o.post("/api/store/control/scrap", json={"store_id": w.site, "reason": "Torn bags", "lines": [{"item_id": w.cement, "qty": "20", "realised_value": "40"}]}).json()
    step(o, "/api/store/control/scrap/%d" % sc["id"], "submit", "approve", "post")
    sr = run(o, "scrap", project_id=w.job)
    assert sr["totals"]["book"] == "140.00" and sr["totals"]["gain"] == "-100.00"
    c = o.post("/api/store/control/counts", json={"store_id": w.site}).json()
    o.put("/api/store/control/counts/%d" % c["id"], json={"lines": [{"item_id": w.cement, "counted_qty": "2770"}]})
    step(o, "/api/store/control/counts/%d" % c["id"], "submit", "approve", "post")
    cv = run(o, "count-variances", store_id=w.site)
    assert cv["rows"][0]["diff"] == "-20.000" or cv["rows"][0]["diff"].startswith("-") and cv["totals"]["value"].startswith("-")
    assert run(o, "slow-moving", days=30)["rows"] == []                                                               # everything has moved lately
    idle = o.post("/api/store/masters/stores", json={"code": "IDL" + uuid.uuid4().hex[:3].upper(), "name": "Idle yard", "type": "YARD"}).json()["id"]
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=idle, item_id=w.cement, qty=D(10), rate=D(7), txn_date=date.today(), project_id=None,
                      ref_doc_type="OPENING", ref_doc_id=3, ref_line_id=None, user_id=None)
        s.commit()
    slow = run(o, "slow-moving", days=30)["rows"]
    assert len(slow) == 1 and slow[0]["store"].startswith("IDL") and slow[0]["last_out"] == "never"
    assert o.get(R + "/run/count-variances").status_code == 400
    summary = o.get(R + "/summary").json()
    assert summary["stock_lines"] == 3 and summary["in_transit"] == 1


def test_low_stock_report(account):
    o = account["client"]
    w = seed(account)
    with database.SessionLocal() as s:
        post_movement(s, movement_type=MovementType.OPENING_IN, store_id=w.site, item_id=w.cement, qty=D(2500), rate=D(7), txn_date=date.today(), project_id=None,
                      ref_doc_type="OPENING", ref_doc_id=1, ref_line_id=None, user_id=None)
        s.commit()
    r = run(o, "reorder")
    assert r["rows"][0]["short"] == "500.000" and r["rows"][0]["suggest"] == "7500.000"                              # level 3,000, maximum 10,000


def test_exports_are_real_files(account):
    o = account["client"]
    w = seed(account)
    flow(o, w)
    x = o.get("%s/run/stock-valuation" % R, params={"format": "xlsx"})
    assert x.status_code == 200 and "spreadsheetml" in x.headers["content-type"] and "Stock_valuation" in x.headers["content-disposition"]
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A2"].value == "Stock valuation" and [c.value for c in ws[5]][:3] == ["Store", "Code", "Item"]
    assert isinstance(ws["F6"].value, (int, float)) and ws.cell(row=ws.max_row, column=8).value == 61600.0              # the quantity and the total are numbers
    p = o.get("%s/run/consumption" % R, params={"format": "pdf", "project_id": w.job})
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    assert o.get("%s/run/nope" % R).status_code == 404
    assert o.get("%s/run/reorder" % R, params={"format": "docx"}).status_code == 400
    cat = o.get(R + "/catalog").json()["reports"]
    assert {c["code"] for c in cat} >= {"stock-valuation", "consumption", "po-pending", "returnables"}


def test_subcontract_recoveries_are_synced_and_follow_returns(account):
    o = account["client"]
    w = seed(account)
    f = flow(o, w)
    res = o.post(R + "/integration/subcon-recoveries/sync").json()
    assert res["created"] == 1 and res["skipped"] == []
    with database.SessionLocal() as s:
        rec = s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid).one()
        assert (rec.order_id, rec.job_id, rec.quantity, rec.rate, rec.amount, rec.sub_bill_id) == (w.order, w.job, 300.0, 8.0, 2400.0, None)
    assert o.post(R + "/integration/subcon-recoveries/sync").json() == {"created": 0, "updated": 0, "withdrawn": 0, "skipped": []}      # repeatable

    rt = o.post("/api/store/outward/returns", json={"store_id": w.site, "issue_id": f["subcon"]["id"], "lines": [{"issue_line_id": f["subcon"]["lines"][0]["id"], "qty": "100"}]}).json()
    step(o, "/api/store/outward/returns/%d" % rt["id"], "submit", "approve", "post")
    assert o.post(R + "/integration/subcon-recoveries/sync").json()["updated"] == 1
    with database.SessionLocal() as s:
        assert s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid).one().amount == 1600.0           # 200 kg kept @ 8
    step(o, "/api/store/outward/returns/%d" % rt["id"], "cancel")
    assert o.post(R + "/integration/subcon-recoveries/sync").json()["updated"] == 1

    with database.SessionLocal() as s:                                                                              # a bill takes it: the store leaves it alone
        rec = s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid).one()
        rec.sub_bill_id = None
        link = s.query(DBStoreRecoveryLink).one()
        s.commit()
    o.post("/api/store/outward/issues/%d/cancel" % f["subcon"]["id"], json={"reason": "wrong contractor"})
    assert o.post(R + "/integration/subcon-recoveries/sync").json()["withdrawn"] == 1
    with database.SessionLocal() as s:
        assert s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid).count() == 0


def test_recovery_needs_an_order_and_leaves_billed_rows(account):
    o = account["client"]
    w = seed(account)
    with database.SessionLocal() as s:
        s.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == w.order).update({"status": "DRAFT"})
        s.commit()
    f = flow(o, w)
    res = o.post(R + "/integration/subcon-recoveries/sync").json()
    assert res["created"] == 0 and "No active subcontract order" in res["skipped"][0]["reason"]
    with database.SessionLocal() as s:
        s.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == w.order).update({"status": "Approved"})
        s.commit()
    assert o.post(R + "/integration/subcon-recoveries/sync").json()["created"] == 1
    with database.SessionLocal() as s:
        bill = models.DBSubBill(client_id=w.cid, order_id=w.order, number="SB-1")
        s.add(bill)
        s.flush()
        s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid).update({"sub_bill_id": bill.id})
        s.commit()
        bid = bill.id
    o.post("/api/store/outward/issues/%d/cancel" % f["subcon"]["id"], json={"reason": "late"})
    out = o.post(R + "/integration/subcon-recoveries/sync").json()
    assert out["withdrawn"] == 0                                                                                   # already billed: not touched
    with database.SessionLocal() as s:
        assert s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid, models.DBMaterialRecovery.sub_bill_id == bid).count() == 1
        s.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.client_id == w.cid).delete()
        s.query(models.DBSubBill).filter(models.DBSubBill.id == bid).delete()
        s.commit()


def _login(account, portal, rights, stores):
    email = "staff-%s@example.com" % uuid.uuid4().hex[:8]
    emp = make_employee(account["client"], email=email, password="Crew1234", permission_role="staff", status="active")
    with database.SessionLocal() as s:
        row = s.get(models.DBEmployee, emp["id"])
        row.extra_permissions = ",".join(rights)
        s.add_all([DBStoreUserAssignment(store_id=i, employee_id=row.id) for i in stores])
        s.commit()
    assert portal.post("/api/employee/auth/login", json={"email": email, "password": "Crew1234"}).status_code == 200


def test_rights_and_store_scoping(account, portal):
    o = account["client"]
    w = seed(account)
    flow(o, w)
    _login(account, portal, VIEW, [w.site])
    val = portal.get(R + "/run/stock-valuation").json()
    assert [r["qty"] for r in val["rows"]] == ["2800.000"]                                                           # only the assigned store
    assert portal.get(R + "/run/stock-valuation", params={"store_id": w.central}).status_code == 403
    assert portal.get(R + "/summary").json()["stock_lines"] == 1
    assert portal.get(R + "/run/stock-valuation", params={"format": "xlsx"}).status_code == 200
    assert portal.put(R + "/norms", json={"boq_item_id": w.boq1, "item_id": w.cement, "qty_per_unit": "1"}).status_code == 403
    assert portal.post(R + "/integration/subcon-recoveries/sync").status_code == 403
    assert portal.delete(R + "/norms/1").status_code == 403

    _login(account, portal, VIEW + ["store.reports.create", "store.reports.cancel", "store.reports.post"], [w.site])
    n = portal.put(R + "/norms", json={"boq_item_id": w.boq1, "item_id": w.cement, "qty_per_unit": "50"})
    assert n.status_code == 200
    assert portal.delete("%s/norms/%d" % (R, n.json()["id"])).status_code == 200
    assert portal.post(R + "/integration/subcon-recoveries/sync").status_code == 200

    _login(account, portal, ["store.inward.view"], [w.site])
    assert portal.get(R + "/catalog").status_code == 403 and portal.get(R + "/run/reorder").status_code == 403
