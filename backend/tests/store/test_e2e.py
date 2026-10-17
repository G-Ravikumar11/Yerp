"""The Store module end to end, on P1's seed world:

    PO -> GRN with partial QC rejection -> purchase return -> indent -> issue to WO / BOQ -> subcontractor free issue
    -> partial return -> transfer to another site -> physical count with variance -> reconciliation -> project material
    cost -> sub-bill recovery

with quantities and values tied out at every step: each store's balance equals its ledger, the reports agree with the
balances, and at the end every rupee received is either still held, sent back, or charged to a project.

Until P2, P3 and P4 are merged into this branch, each of their documents is the ledger movement it posts (made with
post_movement, as their services do) and their published functions are mocked with what those documents would report.
After the merge the `slice_*` helpers below are replaced by calls to the real services; the assertions stay as they are.
"""
from datetime import date, timedelta
from decimal import Decimal

from app import models
from app.models.store_core import DBStore, MovementType
from app.models.store_reports import DBStoreConsumptionNorm, DBStoreSubconRecovery
from app.schemas.store_contracts import CountVarianceLine, InTransitLine, PoLineReceipt, SubconIssueLine
from app.services import store_control, store_inward, store_outward
from app.services import store_integration as integ
from app.services import store_reports as rep
from app.services.stock_ledger import get_balance, ledger_position, post_movement
from store.fixtures import db, store_world  # noqa: F401  (fixtures)
from store.test_masters import ok, sign_in  # noqa: F401  (fixtures)
from store.test_reports import world  # noqa: F401  (fixture: cleans up P5's rows)

D = Decimal
TODAY = date.today()
M = MovementType
R = "/api/store/reports"


def ties_out(db, *pairs):
    """Every (store, item) balance is exactly what its ledger adds up to."""
    for store_id, item_id in pairs:
        bal, led = get_balance(db, store_id, item_id), ledger_position(db, store_id, item_id)
        assert (bal.qty, bal.value) == (led.qty, led.value), (store_id, item_id, bal, led)


def at(db, store_id, item_id):
    b = get_balance(db, store_id, item_id)
    return b.qty, b.value


def slice_post(db, w, mtype, store, qty, rate, doc, **kw):
    """A slice's document posting one line, as its service would."""
    e = post_movement(db, movement_type=mtype, store_id=store, item_id=w.item["cement"], qty=D(str(qty)), rate=None if rate is None else D(str(rate)),
                      txn_date=TODAY, project_id=kw.pop("project_id", None), ref_doc_type=doc[0], ref_doc_id=doc[1], ref_line_id=1, user_id=None, **kw)
    db.commit()
    return e


def test_po_to_sub_bill_recovery_ties_out_at_every_step(db, world, sign_in, monkeypatch):
    w = world
    owner = sign_in("owner")
    site, cem = w.site_id, w.item["cement"]
    # A second project with its own site store, for the inter-project transfer.
    job2 = models.DBJob(client_id=w.client_id, number="P-2-%d" % w.client_id, name="Tower B")
    db.add(job2)
    db.flush()
    site2 = DBStore(client_id=w.client_id, code="ST02", name="Tower B Site Store", type="SITE", project_id=job2.id)
    db.add(site2)
    db.commit()

    # 1. PO 400 bag -> GRN: 100 bag arrive, QC rejects 4, 96 bag (4800 kg) accepted at the landed 7.10 a kg.
    slice_post(db, w, M.GRN_IN, site, 4800, "7.10", ("GRN", 1), project_id=w.project_id)
    monkeypatch.setattr(store_inward, "get_po_receipt_summary", lambda db, po_id: [
        PoLineReceipt(po_line_id=w.po_line_ids[0], item_id=cem, ordered_qty=D(400), received_qty=D(100), accepted_qty=D(96), rejected_qty=D(4),
                      pending_qty=D(304))] if po_id == w.po_id else [])
    assert at(db, site, cem) == (D("4800.000"), D("34080.00"))
    assert ok(owner.get(R + "/integration/po/%d" % w.po_id))["lines"][0]["pending"] == "304.000"
    ties_out(db, (site, cem))

    # 2. Purchase return: 10 accepted bags (500 kg) go back. They leave at the average, 7.10.
    slice_post(db, w, M.PURCHASE_RETURN_OUT, site, 500, None, ("PURCHASE_RETURN", 1), project_id=w.project_id)
    assert at(db, site, cem) == (D("4300.000"), D("30530.00"))
    grn = rep.grn_register(db, rep.Filters(client_id=w.client_id, item_id=cem))
    assert [(r["document"], r["qty"], r["value"]) for r in grn["rows"]] == [("GRN #1", "4800.000", "34080.00"), ("PURCHASE_RETURN #1", "-500.000", "-3550.00")]
    ties_out(db, (site, cem))

    # 3. An indent moves no stock (P3 publishes no indent count yet - the dashboard says so rather than guessing).
    assert ok(owner.get(R + "/dashboard"))["pending_indents"] is None

    # 4. Issue to the work order / BOQ item: 1500 kg.
    slice_post(db, w, M.ISSUE_OUT, site, 1500, None, ("ISSUE", 1), project_id=w.project_id, work_order_id=w.work_order_id, boq_item_id=w.boq_item_ids[0])
    assert at(db, site, cem) == (D("2800.000"), D("19880.00"))
    ties_out(db, (site, cem))

    # 5. Free issue to the subcontractor: 2000 kg. 6. They return 300 kg.
    slice_post(db, w, M.SUBCON_ISSUE_OUT, site, 2000, None, ("SUBCON_ISSUE", 1), project_id=w.project_id, subcontractor_id=w.subcontractor_id)
    slice_post(db, w, M.SUBCON_RETURN_IN, site, 300, "7.10", ("SUBCON_RETURN", 1), project_id=w.project_id, subcontractor_id=w.subcontractor_id)
    monkeypatch.setattr(store_outward, "get_subcon_issues", lambda db, sid, upto: [
        SubconIssueLine(issue_line_id=1, issue_date=TODAY, item_id=cem, qty_issued=D(2000), qty_returned=D(300), chargeable=False,
                        recovery_rate=D(0), recovery_value=D(0))] if sid == w.subcontractor_id else [])
    assert at(db, site, cem) == (D("1100.000"), D("7810.00"))
    acct = rep.subcontractor_account(db, rep.Filters(client_id=w.client_id))["rows"][0]
    assert (acct["issued_value"], acct["returned_value"], acct["net_value"], acct["recoverable"]) == ("14200.00", "2130.00", "12070.00", "0.00")
    ties_out(db, (site, cem))

    # 7. Transfer 600 kg to Tower B's store - another project.
    out = slice_post(db, w, M.TRANSFER_OUT, site, 600, None, ("TRANSFER", 1))
    slice_post(db, w, M.TRANSFER_IN, site2.id, 600, out.rate, ("TRANSFER", 1), project_id=job2.id)
    monkeypatch.setattr(store_control, "get_in_transit", lambda db, project_id=None: [])
    assert at(db, site, cem) == (D("500.000"), D("3550.00")) and at(db, site2.id, cem) == (D("600.000"), D("4260.00"))
    tr = rep.transfers(db, rep.Filters(client_id=w.client_id))["rows"][0]
    assert (tr["sent"], tr["received"], tr["in_transit"], tr["inter_project"], tr["value"]) == ("600.000", "600.000", "0.000", "Yes", "4260.00")
    ties_out(db, (site, cem), (site2.id, cem))

    # 8. Physical count at Tower A: 480 kg found against 500 - a 20 kg adjustment down.
    slice_post(db, w, M.ADJUST_OUT, site, 20, None, ("COUNT", 1), project_id=w.project_id)
    monkeypatch.setattr(store_control, "get_count_variances", lambda db, sid, a, b: [
        CountVarianceLine(count_id=1, item_id=cem, system_qty=D(500), counted_qty=D(480), variance_qty=D(-20), variance_value=D(-142))] if sid == site else [])
    monkeypatch.setattr(store_control, "get_scrap_realisation", lambda db, pid, a, b: [])
    assert at(db, site, cem) == (D("480.000"), D("3408.00"))
    counts = rep.count_and_scrap(db, rep.Filters(client_id=w.client_id))
    assert counts["totals"]["variance_value"] == "-142.00" and "count 1: -142.00" in counts["notes"][0]
    ties_out(db, (site, cem))

    # The stock register agrees with the balances, store by store.
    reg = {(r["store"], r["item_name"]): r for r in rep.stock_register(db, rep.Filters(client_id=w.client_id, item_id=cem))["rows"]}
    assert (reg[("ST01", "Cement OPC 53")]["closing_qty"], reg[("ST01", "Cement OPC 53")]["closing_value"]) == ("480.000", "3408.00")
    assert (reg[("ST02", "Cement OPC 53")]["closing_qty"], reg[("ST02", "Cement OPC 53")]["closing_value"]) == ("600.000", "4260.00")

    # 9. Reconciliation: the subcontractor did 3.8 cum of RCC M25 at 425 kg a cum + 2 %, and used 1700 kg net.
    db.add(DBStoreConsumptionNorm(client_id=w.client_id, work_item_code="RCC-M25", item_id=cem, coefficient=D(425), wastage_pct=D(2),
                                  penal_rate=D("9.5"), work_uom="cum"))
    order = models.DBSubcontractOrder(client_id=w.client_id, wo_number="SWO-E2E", status="APPROVED", contractor_id=w.subcontractor_id, job_id=w.project_id)
    db.add(order)
    db.flush()
    w.made["orders"].append(order.id)
    sub_item = models.DBSubcontractItem(order_id=order.id, item_code="RCC-M25", uom="cum", quantity=50, unit_rate=900)
    db.add(sub_item)
    db.flush()
    db.add(models.DBSubMeasurement(client_id=w.client_id, order_id=order.id, item_id=sub_item.id, quantity=3.8, measured_on=str(TODAY)))
    db.commit()
    recon = rep.reconciliation(db, w.client_id, "subcontractor", w.subcontractor_id, project_id=w.project_id)["rows"][0]
    assert (recon["theoretical"], recon["permitted"], recon["actual"], recon["excess"], recon["recoverable"]) == (
        "1615.000", "1647.300", "1700.000", "52.700", "500.65")

    # 10. Project material cost: issue + subcontractor issue - return + count loss. Transfers and returns to the
    # supplier are not cost.
    lines = integ.get_project_material_cost(db, w.project_id, None, None)
    assert sum(l.qty for l in lines) == D("3220.000") and sum(l.value for l in lines) == D("22862.00")
    assert integ.get_project_material_cost(db, job2.id, None, None) == []
    from app.services.projects import project_pnl
    assert project_pnl(db, w.client_id, db.get(models.DBJob, w.project_id))["cost"]["material_from_store_module"] == 22862.00

    # Every rupee that came in is held, went back, or was charged to the project.
    held = at(db, site, cem)[1] + at(db, site2.id, cem)[1]
    assert D("34080.00") == held + D("3550.00") + D("22862.00")

    # 11. Sub-bill recovery: the free issue is not charged; the 52.7 kg beyond the allowance is, at 9.50.
    bill = models.DBSubBill(client_id=w.client_id, order_id=order.id, job_id=w.project_id, contractor_id=w.subcontractor_id, number="SWO-E2E/RA-01",
                            status="DRAFT", period_to=str(TODAY))
    db.add(bill)
    db.commit()
    w.made["bills"].append(bill.id)
    due = ok(owner.get(R + "/integration/sub-bills/%d/recovery" % bill.id))
    assert (due["material_due"], due["wastage_due"], due["total_due"]) == ("0.00", "500.65", "500.65")
    after = ok(owner.post(R + "/integration/sub-bills/%d/recovery" % bill.id, json={"kind": "EXCESS_WASTAGE", "amount": "500.65"}))
    assert after["total_due"] == "0.00"
    assert db.query(DBStoreSubconRecovery).filter(DBStoreSubconRecovery.sub_bill_id == bill.id).one().amount == D("500.65")

    # Tower B is not part of store_world, so its rows go here (children first, for Postgres).
    from app.models.store_core import DBStoreStockBalance, DBStoreStockLedger
    led = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id == site2.id)
    led.filter(DBStoreStockLedger.reversal_of_id.isnot(None)).delete(synchronize_session=False)
    led.delete(synchronize_session=False)
    db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == site2.id).delete(synchronize_session=False)
    db.query(DBStore).filter(DBStore.id == site2.id).delete(synchronize_session=False)
    db.query(models.DBJob).filter(models.DBJob.id == job2.id).delete(synchronize_session=False)
    db.commit()
