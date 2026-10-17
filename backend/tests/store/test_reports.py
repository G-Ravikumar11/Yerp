"""P5 reports and integration: every report against P1's seed world (netting reversals, filters, exports), consumption
norms and get_theoretical_requirement, material reconciliation, client-supplied material, the dashboard, and the hooks
into project profit, purchase orders, subcontract bills, client billing and the old stock screens. Other slices'
functions are mocked (they are not merged into this branch)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app import models
from app.models.store_core import MovementType
from app.models.store_reports import DBStoreConsumptionNorm, DBStoreSubconRecovery
from app.schemas.store_contracts import (
    CountVarianceLine, InTransitLine, PoLineReceipt, ReturnableOutstanding, ScrapLine, SubconIssueLine,
)
from app.services import store_control, store_inward, store_outward
from app.services import store_integration as integ
from app.services import store_reports as rep
from app.services.stock_ledger import freeze_store, post_movement, reverse_document
from store.fixtures import db, store_world  # noqa: F401  (fixtures)
from store.test_masters import ok, sign_in  # noqa: F401  (fixtures)

D = Decimal
TODAY = date.today()
R = "/api/store/reports"


@pytest.fixture
def world(db, store_world):
    """store_world, and clearing what P5's tests make before store_world drops its stores."""
    made = {"orders": [], "bills": [], "wo_lines": [], "legacy": False}
    store_world.made = made
    yield store_world
    db.rollback()
    cid = store_world.client_id
    db.query(DBStoreSubconRecovery).filter(DBStoreSubconRecovery.client_id == cid).delete(synchronize_session=False)
    db.query(DBStoreConsumptionNorm).filter(DBStoreConsumptionNorm.client_id == cid).delete(synchronize_session=False)
    if made["bills"]:
        db.query(models.DBSubBill).filter(models.DBSubBill.id.in_(made["bills"])).delete(synchronize_session=False)
    if made["orders"]:
        db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id.in_(made["orders"])).delete(synchronize_session=False)
        db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id.in_(made["orders"])).delete(synchronize_session=False)
        db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id.in_(made["orders"])).delete(synchronize_session=False)
    db.query(models.DBMeasurement).filter(models.DBMeasurement.client_id == cid).delete(synchronize_session=False)
    if made["wo_lines"]:
        db.query(models.DBWorkOrderLine).filter(models.DBWorkOrderLine.id.in_(made["wo_lines"])).delete(synchronize_session=False)
    db.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id.in_(
        [b.id for b in db.query(models.DBBill).filter(models.DBBill.client_id == cid)])).delete(synchronize_session=False)
    for model in (models.DBBill, models.DBGoodsReceipt, models.DBStockMovement, models.DBStockBalance):
        db.query(model).filter(model.client_id == cid).delete(synchronize_session=False)
    db.commit()


def move(db, w, mtype, qty, rate=None, store=None, item="cement", doc=("GRN", 1), day=TODAY, **kw):
    e = post_movement(db, movement_type=mtype, store_id=store or w.central_id, item_id=w.item[item], qty=D(str(qty)),
                      rate=None if rate is None else D(str(rate)), txn_date=day, project_id=kw.pop("project_id", None),
                      ref_doc_type=doc[0], ref_doc_id=doc[1], ref_line_id=1, user_id=None, **kw)
    db.commit()
    return e


def F(w, **kw):
    return rep.Filters(client_id=w.client_id, **kw)


def rows_by(out, *keys):
    return {(r[keys[0]] if len(keys) == 1 else tuple(r[k] for k in keys)): r for r in out["rows"]}


def busy_cement(db, w):
    """GRN in, an issue that is reversed, and a second issue - in the last week."""
    move(db, w, MovementType.GRN_IN, 1000, 8, doc=("GRN", 1), day=TODAY - timedelta(days=2))
    move(db, w, MovementType.ISSUE_OUT, 600, doc=("ISSUE", 1), day=TODAY - timedelta(days=1), project_id=w.project_id,
         work_order_id=w.work_order_id, boq_item_id=w.boq_item_ids[0])
    reverse_document(db, ref_doc_type="ISSUE", ref_doc_id=1, user_id=None, reason="wrong site")
    db.commit()
    move(db, w, MovementType.ISSUE_OUT, 200, doc=("ISSUE", 2), project_id=w.project_id, work_order_id=w.work_order_id,
         boq_item_id=w.boq_item_ids[0], cost_head="SAFETY")


# --- reports -------------------------------------------------------------------------------------------------------

def test_stock_register_nets_reversals_by_direction(db, world):
    w = world
    busy_cement(db, w)
    out = rep.stock_register(db, F(w, item_id=w.item["cement"], date_from=TODAY - timedelta(days=7), date_to=TODAY))
    r = out["rows"][0]
    assert (r["store"], r["opening_qty"], r["opening_value"]) == ("CS01", "5000.000", "35000.00")
    assert (r["in_qty"], r["in_value"]) == ("1000.000", "8000.00")
    assert (r["out_qty"], r["out_value"]) == ("200.000", "1433.34")          # the reversed 600 nets out of "out"
    assert (r["closing_qty"], r["closing_value"]) == ("5800.000", "41566.66")
    whole = rep.stock_register(db, F(w))
    assert len(whole["rows"]) == 10 and D(whole["totals"]["closing_value"]) > 0


def test_valuation_as_on_a_date(db, world):
    w = world
    busy_cement(db, w)
    before = rows_by(rep.valuation(db, F(w, date_to=TODAY - timedelta(days=10))), "item_name")["Cement OPC 53"]
    assert (before["qty"], before["value"], before["avg_rate"]) == ("5000.000", "35000.00", "7.0000")
    now = rows_by(rep.valuation(db, F(w)), "item_name")["Cement OPC 53"]
    assert (now["qty"], now["value"]) == ("5800.000", "41566.66")


def test_registers_and_consumption(db, world):
    w = world
    busy_cement(db, w)
    grn = rep.grn_register(db, F(w))
    assert [(r["document"], r["qty"], r["value"]) for r in grn["rows"]] == [("GRN #1", "1000.000", "8000.00")]
    issues = rows_by(rep.issue_register(db, F(w)), "document")
    assert (issues["ISSUE #1"]["qty"], issues["ISSUE #1"]["status"]) == ("0.000", "Cancelled")
    assert (issues["ISSUE #2"]["qty"], issues["ISSUE #2"]["value"], issues["ISSUE #2"]["cost_head"]) == ("200.000", "1433.34", "SAFETY")
    by_wo = rep.consumption(db, F(w, project_id=w.project_id), "work_order")
    assert [(r["group"].startswith("WO-"), r["qty"], r["value"]) for r in by_wo["rows"]] == [(True, "200.000", "1433.34")]
    by_head = rep.consumption(db, F(w, project_id=w.project_id), "cost_head")
    assert by_head["rows"][0]["group"] == "SAFETY" and by_head["totals"]["value"] == "1433.34"
    by_boq = rep.consumption(db, F(w), "boq_item")
    assert "RCC M25" in by_boq["rows"][0]["group"]
    assert rep.consumption(db, F(w, project_id=999999), "work_order")["rows"] == []


def test_ageing_and_non_moving(db, world):
    w = world
    move(db, w, MovementType.OPENING_IN, 10, 180, store=w.site_id, item="helmet", doc=("OPENING_STOCK", 9001), day=TODAY - timedelta(days=200))
    busy_cement(db, w)
    out = rows_by(rep.ageing(db, F(w), 180), "store", "item_name")
    helmet = out[("ST01", "Safety Helmet")]
    assert (helmet["status"], helmet["days_idle"], helmet["age_181_365"], helmet["last_out"]) == ("Non-moving", 200, "1800.00", "never")
    cement = out[("CS01", "Cement OPC 53")]
    assert cement["status"] == "" and cement["last_out"] == TODAY.isoformat()
    assert D(cement["age_0_90"]) > 0
    assert out[("CS01", "River Sand")]["status"] == ""                       # 30 days, not 180
    assert rows_by(rep.ageing(db, F(w), 90), "store", "item_name")[("ST01", "Safety Helmet")]["status"] == "Non-moving"


def test_transfers_in_transit_and_inter_project(db, world, monkeypatch):
    w = world
    out = move(db, w, MovementType.TRANSFER_OUT, 10, item="sand", doc=("TRANSFER", 7))
    move(db, w, MovementType.TRANSFER_IN, 8, out.rate, store=w.site_id, item="sand", doc=("TRANSFER", 7))
    monkeypatch.setattr(store_control, "get_in_transit", lambda db, project_id=None: [
        InTransitLine(transfer_id=7, from_store_id=w.central_id, to_store_id=w.site_id, item_id=w.item["sand"], qty=D(2), value=D(3600),
                      dispatched_on=TODAY, inter_project=True)])
    rep_ = rep.transfers(db, F(w))
    r = rep_["rows"][0]
    assert (r["from_store"], r["to_store"], r["sent"], r["received"], r["in_transit"], r["inter_project"]) == ("CS01", "ST01", "10.000", "8.000", "2.000", "Yes")
    assert rep_["totals"] == {"value": "18000.00", "in_transit_value": "3600.00"}
    assert "inter-project" in rep_["notes"][0]


def test_counts_and_scrap_come_from_the_control_slice(db, world, monkeypatch):
    w = world
    monkeypatch.setattr(store_control, "get_count_variances", lambda db, sid, a, b: [
        CountVarianceLine(count_id=3, item_id=w.item["bricks"], system_qty=D(20000), counted_qty=D(19950), variance_qty=D(-50), variance_value=D(-400))
    ] if sid == w.central_id else [])
    monkeypatch.setattr(store_control, "get_scrap_realisation", lambda db, pid, a, b: [
        ScrapLine(scrap_doc_id=4, item_id=w.item["tmt12"], qty=D(100), book_value=D(6200), realised_value=D(3500))])
    out = rep.count_and_scrap(db, F(w))
    kinds = rows_by(out, "kind")
    assert kinds["Count variance"]["variance_qty"] == "-50.000" and kinds["Scrap"]["gain_loss"] == "-2700.00"
    assert out["totals"] == {"variance_value": "-400.00", "scrap_book": "6200.00", "scrap_realised": "3500.00"}


def test_subcontractor_account(db, world, monkeypatch):
    w = world
    move(db, w, MovementType.SUBCON_ISSUE_OUT, 4500, doc=("SUBCON_ISSUE", 1), project_id=w.project_id, subcontractor_id=w.subcontractor_id)
    move(db, w, MovementType.SUBCON_RETURN_IN, 100, 7, doc=("SUBCON_RETURN", 1), project_id=w.project_id, subcontractor_id=w.subcontractor_id)
    monkeypatch.setattr(store_outward, "get_subcon_issues", lambda db, sid, upto: [
        SubconIssueLine(issue_line_id=1, issue_date=TODAY, item_id=w.item["cement"], qty_issued=D(4500), qty_returned=D(100), chargeable=True,
                        recovery_rate=D("7.5"), recovery_value=D(33000))] if sid == w.subcontractor_id else [])
    r = rep.subcontractor_account(db, F(w))["rows"][0]
    assert (r["subcontractor"], r["issued_value"], r["returned_value"], r["net_value"], r["recoverable"], r["recovered"], r["balance"]) == (
        "Sai Steel Fixers", "31500.00", "700.00", "30800.00", "33000.00", "0.00", "33000.00")


def test_exports_filters_rights_and_store_access(db, world, sign_in):
    w = world
    busy_cement(db, w)
    owner = sign_in("owner")
    js = ok(owner.get(R + "/run/stock-register?item_id=%d" % w.item["cement"]))
    assert js["rows"][0]["closing_qty"] == "5800.000" and js["filters"]["item_id"] == w.item["cement"]
    xl = owner.get(R + "/run/stock-register?format=xlsx")
    assert xl.status_code == 200 and xl.content[:2] == b"PK"
    pdf = owner.get(R + "/run/consumption?group=cost_head&format=pdf&project_id=%d" % w.project_id)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    for code in rep.REPORTS:
        assert owner.get(R + "/run/%s" % code).status_code == 200, code
    assert owner.get(R + "/run/nope").status_code == 404
    assert owner.get(R + "/run/ageing?days=45").status_code == 400
    assert owner.get(R + "/run/stock-register?category=returnable").json()["rows"][0]["item_name"] == "Shuttering Plate"
    assert len(ok(owner.get(R + "/catalogue"))["reports"]) == 10
    assert sign_in("viewer").get(R + "/run/stock-register").status_code == 403              # no store.reports.view
    site = sign_in("site_keeper")                                                           # works at ST01 only
    assert ok(site.get(R + "/run/stock-register"))["rows"] == []
    assert site.get(R + "/run/stock-register?store_id=%d" % w.central_id).status_code == 403
    assert sign_in("central_keeper").post(R + "/norms", json={"work_item_code": "X", "item_id": w.item["sand"], "coefficient": "1"}).status_code == 403


# --- norms and requirement -----------------------------------------------------------------------------------------

def test_norms_and_the_theoretical_requirement(db, world, sign_in):
    w = world
    owner = sign_in("owner")
    pinned = ok(owner.post(R + "/norms", json={"work_item_code": "RCC-M25", "boq_item_id": w.boq_item_ids[0], "item_id": w.item["cement"],
                                                "coefficient": "425", "wastage_pct": "2", "penal_rate": "9.5", "work_uom": "cum"}))
    assert pinned["boq_item"].startswith("1 RCC M25") and pinned["coefficient"] == "425.000000"
    assert rep.get_theoretical_requirement(db, w.boq_item_ids[0], w.item["cement"]) == D("51000.000")      # 120 cum x 425
    assert rep.get_theoretical_requirement(db, w.boq_item_ids[0], w.item["sand"]) is None
    db.get(models.DBBoqLine, w.boq_item_ids[0]).item_code = "RCC-M25"
    db.commit()
    ok(owner.post(R + "/norms", json={"work_item_code": "RCC-M25", "item_id": w.item["sand"], "coefficient": "0.42", "work_uom": "cum"}))
    assert rep.get_theoretical_requirement(db, w.boq_item_ids[0], w.item["sand"]) == D("50.400")           # by the code
    assert ok(owner.get(R + "/norms/requirement?boq_item_id=%d&item_id=%d" % (w.boq_item_ids[0], w.item["sand"])))["theoretical"] == "50.400"
    dup = owner.post(R + "/norms", json={"work_item_code": "RCC-M25", "item_id": w.item["sand"], "coefficient": "0.5"})
    assert dup.status_code == 409
    assert owner.post(R + "/norms", json={"work_item_code": "X", "item_id": w.item["sand"], "coefficient": "0"}).status_code == 400
    upd = ok(owner.put(R + "/norms/%d" % pinned["id"], json=dict(pinned, coefficient="430", penal_rate="10")))
    assert (upd["coefficient"], upd["penal_rate"]) == ("430.000000", "10.0000")
    ok(owner.delete(R + "/norms/%d" % pinned["id"]))
    assert rep.get_theoretical_requirement(db, w.boq_item_ids[0], w.item["cement"]) is None
    assert any(i["code"] == "RCC-M25" for i in ok(owner.get(R + "/work-items"))["items"])


def test_norms_from_a_sheet(db, world, sign_in):
    w = world
    owner = sign_in("owner")
    code = {k: db.get(models.DBItem, v).item_code for k, v in w.item.items()}
    sheet = ("work_item_code,item_code,coefficient,wastage_pct,penal_rate,work_uom\n"
             "RCC-M25,%s,425,2,9.5,cum\nREINF,%s,1050,3,70,MT\nPCC,NOPE,10,0,,cum\nRCC-M25,%s,-1,0,,cum\n" % (code["cement"], code["tmt12"], code["sand"])).encode()
    dry = ok(owner.post(R + "/norms/import", files={"file": ("n.csv", sheet, "text/csv")}))
    assert dry["summary"] == {"rows": 4, "ok": 2, "errors": 2} and not dry["applied"]
    assert ok(owner.get(R + "/norms"))["norms"] == []                                       # a dry run saves nothing
    done = ok(owner.post(R + "/norms/import?apply=true", files={"file": ("n.csv", sheet, "text/csv")}))
    assert [r["action"] for r in done["rows"][:2]] == ["add", "add"]
    assert {n["work_item_code"] for n in ok(owner.get(R + "/norms"))["norms"]} == {"RCC-M25", "REINF"}
    again = ok(owner.post(R + "/norms/import?apply=true", files={"file": ("n.csv", sheet, "text/csv")}))
    assert again["rows"][0]["action"] == "update" and len(ok(owner.get(R + "/norms"))["norms"]) == 2
    assert owner.post(R + "/norms/import", files={"file": ("n.csv", b"code,qty\nA,1\n", "text/csv")}).status_code == 400


# --- reconciliation ------------------------------------------------------------------------------------------------

def sub_work(db, w, measured, held=0):
    """A subcontract order for the fixture's subcontractor on the project, with an RCC-M25 item measured."""
    order = models.DBSubcontractOrder(client_id=w.client_id, wo_number="SWO-1", status="APPROVED", contractor_id=w.subcontractor_id, job_id=w.project_id)
    db.add(order)
    db.flush()
    item = models.DBSubcontractItem(order_id=order.id, item_code="RCC-M25", item_description="RCC M25", uom="cum", quantity=100, unit_rate=900)
    db.add(item)
    db.flush()
    db.add(models.DBSubMeasurement(client_id=w.client_id, order_id=order.id, item_id=item.id, quantity=measured, measured_on=str(TODAY)))
    if held:
        db.add(models.DBSubMeasurement(client_id=w.client_id, order_id=order.id, item_id=item.id, quantity=held, kind="hold", measured_on=str(TODAY)))
    db.commit()
    w.made["orders"].append(order.id)
    return order


def cement_norm(db, w):
    db.add(DBStoreConsumptionNorm(client_id=w.client_id, work_item_code="RCC-M25", item_id=w.item["cement"], coefficient=D(425),
                                  wastage_pct=D(2), penal_rate=D("9.5"), work_uom="cum"))
    db.commit()


def subcon_cement(db, w):
    move(db, w, MovementType.SUBCON_ISSUE_OUT, 4500, doc=("SUBCON_ISSUE", 1), project_id=w.project_id, subcontractor_id=w.subcontractor_id,
         work_order_id=w.work_order_id)
    move(db, w, MovementType.SUBCON_RETURN_IN, 100, 7, doc=("SUBCON_RETURN", 1), project_id=w.project_id, subcontractor_id=w.subcontractor_id,
         work_order_id=w.work_order_id)


def test_reconciliation_for_a_subcontractor_recovers_excess_at_the_penal_rate(db, world, sign_in):
    w = world
    cement_norm(db, w)
    sub_work(db, w, 10, held=3)                                                             # a hold is not more work
    subcon_cement(db, w)
    out = rep.reconciliation(db, w.client_id, "subcontractor", w.subcontractor_id)
    r = out["rows"][0]
    assert (r["theoretical"], r["allowance"], r["permitted"], r["actual"], r["variance"], r["variance_pct"]) == (
        "4250.000", "85.000", "4335.000", "4400.000", "150.000", "3.53")
    assert (r["excess"], r["penal_rate"], r["recoverable"], r["excess_value"], r["status"]) == ("65.000", "9.5000", "617.50", "455.00", "Over allowance")
    assert out["totals"]["recoverable"] == "617.50"
    owner = sign_in("owner")
    http = ok(owner.get(R + "/reconciliation?scope=subcontractor&scope_id=%d" % w.subcontractor_id))
    assert http["rows"][0]["recoverable"] == "617.50"
    assert owner.get(R + "/reconciliation?scope=subcontractor&scope_id=%d&format=pdf" % w.subcontractor_id).content[:4] == b"%PDF"
    assert owner.get(R + "/reconciliation?scope=moon&scope_id=1").status_code == 400


def test_reconciliation_for_a_project_and_a_work_order(db, world):
    w = world
    cement_norm(db, w)
    line = models.DBWorkOrderLine(work_order_id=w.work_order_id, fg_code="RCC-M25", item_name="RCC M25", qty=120, uom="cum", rate=7500)
    db.add(line)
    db.flush()
    w.made["wo_lines"].append(line.id)
    db.add(models.DBMeasurement(client_id=w.client_id, work_order_id=w.work_order_id, line_id=line.id, fg_code="RCC-M25", quantity=8,
                                measured_on=str(TODAY)))
    db.commit()
    subcon_cement(db, w)
    for scope, sid in (("project", w.project_id), ("work_order", w.work_order_id)):
        r = rep.reconciliation(db, w.client_id, scope, sid)["rows"][0]
        assert (r["theoretical"], r["permitted"], r["actual"], r["excess"], r["recoverable"]) == ("3400.000", "3468.000", "4400.000", "932.000", "0.00")


def test_client_supplied_material_reconciliation_and_billing_data(db, world, sign_in):
    w = world
    move(db, w, MovementType.CLIENT_SUPPLY_IN, 1000, "6.5", store=w.site_id, doc=("CLIENT_SUPPLY", 1), project_id=w.project_id,
         work_order_id=w.work_order_id)
    move(db, w, MovementType.ISSUE_OUT, 600, store=w.site_id, doc=("ISSUE", 5), project_id=w.project_id, work_order_id=w.work_order_id)
    r = rep.client_supply_reconciliation(db, w.client_id, work_order_id=w.work_order_id)["rows"][0]
    assert (r["received"], r["agreed_rate"], r["consumed"], r["balance_at_site"], r["balance_value"], r["recovery_value"]) == (
        "1000.000", "6.5000", "600.000", "400.000", "2600.00", "3900.00")
    data = ok(sign_in("owner").get(R + "/integration/client-billing?work_order_id=%d" % w.work_order_id))
    assert data["project_id"] == w.project_id and data["client_supply"]["recovery_value"] == "3900.00"
    assert data["material_at_site"]["value"] == "2600.00"


# --- integration ---------------------------------------------------------------------------------------------------

def test_project_material_cost_and_profit_use_the_store_ledger(db, world):
    w = world
    from app.services.projects import project_pnl
    from app.services.stores import stock_movement
    busy_cement(db, w)
    move(db, w, MovementType.WASTAGE_OUT, 10, item="sand", doc=("WRITE_OFF", 1), project_id=w.project_id, cost_head="SITE_ESTABLISHMENT")
    lines = integ.get_project_material_cost(db, w.project_id, None, None)
    assert [(l.cost_head, l.item_id, l.qty, l.value) for l in lines] == [
        ("SAFETY", w.item["cement"], D("200.000"), D("1433.34")), ("SITE_ESTABLISHMENT", w.item["sand"], D("10.000"), D("18000.00"))]
    assert integ.get_project_material_cost(db, w.project_id, TODAY + timedelta(days=1), None) == []
    # Old ledger: one issue before the Store module began (counted), one after (not - the screens moved over).
    code = db.get(models.DBItem, w.item["bricks"]).item_code
    stock_movement(db, w.client_id, code, "ISSUE", -10, 5, job_id=w.project_id, moved_on=str(TODAY - timedelta(days=60)))
    stock_movement(db, w.client_id, code, "ISSUE", -20, 5, job_id=w.project_id, moved_on=str(TODAY))
    db.commit()
    cost = project_pnl(db, w.client_id, db.get(models.DBJob, w.project_id))["cost"]
    assert cost["material_from_store_module"] == 19433.34
    assert cost["material_from_store"] == 19483.34                                         # + 50 from the old ledger


def test_old_receipts_cannot_post_stock_once_the_store_module_is_used(db, world):
    from app.services.procurement import grn_apply
    w = world
    grn = models.DBGoodsReceipt(client_id=w.client_id, number="GRN-OLD-1", status="DRAFT")
    db.add(grn)
    db.commit()
    with pytest.raises(HTTPException) as err:
        grn_apply(db, w.client_id, grn, "POST")
    assert err.value.status_code == 409 and "Store > Inward" in err.value.detail
    assert integ.legacy_receipt_blocked(db, w.client_id) and not integ.legacy_receipt_blocked(db, 999999)


def test_purchase_order_receipts_and_stocked_bills(db, world, sign_in, monkeypatch):
    w = world
    monkeypatch.setattr(store_inward, "get_po_receipt_summary", lambda db, po_id: [
        PoLineReceipt(po_line_id=w.po_line_ids[0], item_id=w.item["cement"], ordered_qty=D(400), received_qty=D(100), accepted_qty=D(98),
                      rejected_qty=D(2), pending_qty=D(302))] if po_id == w.po_id else [])
    got = ok(sign_in("owner").get(R + "/integration/po/%d" % w.po_id))
    assert got["store_module"] and got["lines"][0]["pending"] == "302.000" and got["receive_path"] == "/store/hub/inward/grn/new"
    bill = models.DBBill(client_id=w.client_id, number="B-1", purchase_order_id=w.po_id, total=4900)
    db.add(bill)
    db.flush()
    db.add_all([models.DBBillLineItem(bill_id=bill.id, po_line_id=w.po_line_ids[0], qty=10, price=350),
                models.DBBillLineItem(bill_id=bill.id, po_line_id=None, qty=1, price=1500)])
    db.commit()
    assert integ.store_stocked_share(db, w.client_id) == {bill.id: 3500 / 5000}
    assert integ.merge_stocked({bill.id: 0.5}, {bill.id: 0.7}) == {bill.id: 1.0}


def test_subcontract_bill_recovery_due(db, world, sign_in, monkeypatch):
    w = world
    cement_norm(db, w)
    order = sub_work(db, w, 10)
    subcon_cement(db, w)
    monkeypatch.setattr(store_outward, "get_subcon_issues", lambda db, sid, upto: [
        SubconIssueLine(issue_line_id=1, issue_date=TODAY, item_id=w.item["cement"], qty_issued=D(4500), qty_returned=D(100), chargeable=True,
                        recovery_rate=D("7.5"), recovery_value=D(33000)),
        SubconIssueLine(issue_line_id=2, issue_date=TODAY, item_id=w.item["binding_wire"], qty_issued=D(10), qty_returned=D(0), chargeable=False,
                        recovery_rate=D(0), recovery_value=D(0))] if sid == w.subcontractor_id else [])
    bill = models.DBSubBill(client_id=w.client_id, order_id=order.id, job_id=w.project_id, contractor_id=w.subcontractor_id, number="SWO-1/RA-01",
                            status="DRAFT", period_to=str(TODAY))
    db.add(bill)
    db.commit()
    w.made["bills"].append(bill.id)
    owner = sign_in("owner")
    due = ok(owner.get(R + "/integration/sub-bills/%d/recovery" % bill.id))
    assert (due["material_recoverable"], due["wastage_recoverable"], due["total_due"]) == ("33000.00", "617.50", "33617.50")
    assert len(due["material"]) == 1                                                        # the free-issue line is not charged
    after = ok(owner.post(R + "/integration/sub-bills/%d/recovery" % bill.id, json={"kind": "MATERIAL", "amount": "30000", "note": "RA-01"}))
    assert (after["material_due"], after["total_due"], len(after["on_this_bill"])) == ("3000.00", "3617.50", 1)
    too_much = owner.post(R + "/integration/sub-bills/%d/recovery" % bill.id, json={"kind": "EXCESS_WASTAGE", "amount": "700"})
    assert too_much.status_code == 400 and "617.50" in too_much.json()["detail"]
    acc = rows_by(rep.subcontractor_account(db, F(w)), "subcontractor")["Sai Steel Fixers"]
    assert (acc["recovered"], acc["balance"]) == ("30000.00", "3000.00")
    assert db.get(models.DBSubBill, bill.id).other_deductions in (0, 0.0, None)              # the bill itself is untouched


def test_dashboard(db, world, sign_in, monkeypatch):
    w = world
    move(db, w, MovementType.ISSUE_OUT, 55, item="helmet", doc=("ISSUE", 8))
    freeze_store(db, w.site_id, "annual count", user_id=None)
    db.commit()
    monkeypatch.setattr(store_control, "get_in_transit", lambda db, project_id=None: [
        InTransitLine(transfer_id=1, from_store_id=w.central_id, to_store_id=w.site_id, item_id=w.item["sand"], qty=D(2), value=D(3600),
                      dispatched_on=TODAY, inter_project=True)])
    monkeypatch.setattr(store_outward, "get_outstanding_returnables", lambda db, project_id=None, store_id=None: [
        ReturnableOutstanding(issue_line_id=1, item_id=w.item["shuttering"], holder_type="GANG", holder_id=1, qty_outstanding=D(20),
                              expected_return_date=TODAY, overdue_days=4)] if store_id == w.central_id else [])
    d = ok(sign_in("owner").get(R + "/dashboard"))
    assert [s["code"] for s in d["by_store"]] == ["CS01", "ST01"] and d["by_store"][1]["value"] == "0.00"
    assert (d["below_reorder"], d["overdue_returnables"], d["in_transit"]) == (1, 1, {"lines": 1, "value": "3600.00"})
    assert [f["code"] for f in d["frozen_stores"]] == ["ST01"]
    assert d["pending_indents"] is None and d["grns_pending_qc"] is None                    # not published by P2 / P3 yet


def test_old_stock_screens_hand_over_once_migrated(db, world, sign_in):
    w = world
    owner = sign_in("owner")
    st = ok(owner.get(R + "/integration/status"))
    assert (st["store_active"], st["legacy_movements"], st["redirect"]) == (True, False, True)       # never had old stock
    from app.services.stores import stock_movement
    stock_movement(db, w.client_id, db.get(models.DBItem, w.item["sand"]).item_code, "RECEIPT", 5, 1800)
    db.commit()
    st = ok(owner.get(R + "/integration/status"))
    assert (st["legacy_movements"], st["legacy_migrated"], st["redirect"]) == (True, False, False)  # not until carried over
