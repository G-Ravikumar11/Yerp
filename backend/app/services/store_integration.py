"""Store module - what the rest of the ERP (costing, billing) reads from the store. Owned by P5.

The existing modules call these (and only these) to see the store: project profit reads the material cost, subcontract
bills read the recovery due, purchase orders read what has been received, client billing reads client-supplied material
and material at site, and the old stock screens ask whether to send people to the Store module. Read-only throughout;
nothing here moves stock or writes another module's tables (except P5's own recovery records).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import List

from fastapi import HTTPException

from app import models
from app.models.store_core import DBStore, DBStoreOpening, DBStoreStockBalance, DBStoreStockLedger, DocStatus
from app.models.store_reports import DBStoreSubconRecovery
from app.schemas.store_contracts import MaterialCostLine
from app.services.store_reports import CONSUMPTION, ZERO, client_supply_reconciliation, consumed, q, reconciliation, s

D = Decimal
_QTY, _VALUE = D("0.001"), D("0.01")


def get_project_material_cost(db, project_id, from_date, to_date) -> List[MaterialCostLine]:
    """Material issued to a project between two dates, by cost head, work order and BOQ item.

    Issues (to site and to subcontractors) net of returns, plus what was written off or lost - wastage, scrap at book
    value, count and transit losses booked as adjustments (an adjustment up counts back). Reversed documents net out.
    Charged by the entry's project, whichever store it came from."""
    if not project_id:
        return []
    query = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.project_id == project_id,
                                                DBStoreStockLedger.movement_type.in_(list(CONSUMPTION)))
    if from_date:
        query = query.filter(DBStoreStockLedger.txn_date >= from_date)
    if to_date:
        query = query.filter(DBStoreStockLedger.txn_date <= to_date)
    acc = defaultdict(lambda: [ZERO, ZERO])
    for e in query.all():
        qty, value = consumed(e)
        a = acc[(e.cost_head, e.work_order_id, e.boq_item_id, e.item_id)]
        a[0] += qty
        a[1] += value
    return [MaterialCostLine(project_id=project_id, cost_head=ch, work_order_id=wo, boq_item_id=boq, item_id=item,
                             qty=q(v[0], _QTY), value=q(v[1], _VALUE))
            for (ch, wo, boq, item), v in sorted(acc.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or 0, kv[0][2] or 0, kv[0][3]))
            if v[0] or v[1]]


# --- project profit ------------------------------------------------------------------------------------------------

def store_active(db, client_id) -> bool:
    """Whether the company has started on the Store module (it has a store)."""
    return db.query(DBStore.id).filter(DBStore.client_id == client_id).first() is not None


def store_cutover(db, client_id):
    """The first business date the Store module's ledger holds for the company, or None before it has any."""
    from sqlalchemy import func
    first = (db.query(func.min(DBStoreStockLedger.txn_date)).join(DBStore, DBStore.id == DBStoreStockLedger.store_id)
             .filter(DBStore.client_id == client_id).scalar())
    if isinstance(first, str):
        first = date.fromisoformat(first[:10])
    return first


def legacy_moves_before_cutover(db, client_id, rows):
    """The old ledger's movements that still count for profit: all of them until the Store module starts, then only
    those dated before its first entry - the old balances were carried over as opening stock, not as issues, so the
    two never count the same material."""
    cut = store_cutover(db, client_id)
    if cut is None:
        return rows
    stamp = cut.isoformat()
    return [m for m in rows if (m.moved_on or "")[:10] < stamp]


def project_material_cost_by_job(db, client_id, job_id=None) -> dict:
    """{project id: material cost to date} from the Store module's ledger, as floats for the profit sheet."""
    store_ids = [x for (x,) in db.query(DBStore.id).filter(DBStore.client_id == client_id).all()]
    if not store_ids:
        return {}
    query = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(store_ids), DBStoreStockLedger.project_id.isnot(None),
                                                DBStoreStockLedger.movement_type.in_(list(CONSUMPTION)))
    if job_id:
        query = query.filter(DBStoreStockLedger.project_id == job_id)
    out = defaultdict(lambda: ZERO)
    for e in query.all():
        out[e.project_id] += consumed(e)[1]
    return {k: float(q(v, _VALUE)) for k, v in out.items()}


def store_stocked_share(db, client_id) -> dict:
    """{bill id: share of the bill that paid for goods taken into stock through a Store-module GRN} - the twin of the
    old stocked_share_of_bills, so a supplier bill for stocked material is not counted as cost as well as its issue."""
    from app.services.store_inward import get_po_receipt_summary
    bills = db.query(models.DBBill.id, models.DBBill.purchase_order_id).filter(
        models.DBBill.client_id == client_id, models.DBBill.purchase_order_id.isnot(None)).all()
    if not bills:
        return {}
    received = set()
    for po_id in {p for _, p in bills}:
        received |= {r.po_line_id for r in (get_po_receipt_summary(db, po_id) or []) if r.received_qty and r.received_qty > 0}
    if not received:
        return {}
    whole, stock = {}, {}
    for l in db.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id.in_([b for b, _ in bills])).all():
        value = (l.qty or 0) * (l.price or 0)
        whole[l.bill_id] = whole.get(l.bill_id, 0.0) + value
        if l.po_line_id in received:
            stock[l.bill_id] = stock.get(l.bill_id, 0.0) + value
    return {b: min(1.0, stock[b] / whole[b]) for b in stock if whole.get(b)}


def merge_stocked(legacy: dict, store: dict) -> dict:
    out = dict(legacy or {})
    for k, v in (store or {}).items():
        out[k] = min(1.0, out.get(k, 0.0) + v)
    return out


# --- purchase orders -----------------------------------------------------------------------------------------------

def po_receipts(db, client_id, po_id) -> dict:
    """Received and pending on each line of an order, from the inward slice's summary, for the PO screen."""
    from app.services.store_inward import get_po_receipt_summary
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None or po.client_id != client_id:
        raise HTTPException(404, "Purchase order not found")
    lines = {l.id: l for l in db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id)}
    rows = []
    for r in get_po_receipt_summary(db, po.id) or []:
        l = lines.get(r.po_line_id)
        rows.append({"po_line_id": r.po_line_id, "description": (l.description if l else "") or "", "item_code": (l.item_code if l else "") or "",
                     "uom": (l.uom if l else "") or "", "ordered": s(r.ordered_qty, _QTY), "received": s(r.received_qty, _QTY),
                     "accepted": s(r.accepted_qty, _QTY), "rejected": s(r.rejected_qty, _QTY), "pending": s(r.pending_qty, _QTY)})
    return {"po_id": po.id, "number": po.number, "store_module": store_active(db, client_id), "lines": rows,
            "receive_path": "/store/hub/inward/grn/new"}


def legacy_receipt_blocked(db, client_id) -> bool:
    """Whether the old goods-receipt screen may still post stock: not once the Store module is in use, or the same
    delivery could be counted into both ledgers."""
    return store_active(db, client_id)


# --- dashboard figures other slices do not publish yet ---------------------------------------------------------------

def pending_indents(db, client_id):
    """Indents waiting to be issued. P3 publishes no count yet (requested in docs/store/requests/P5.md)."""
    return None


def grns_pending_qc(db, client_id):
    """GRN lines waiting for a quality check. P2 publishes no count yet (requested in docs/store/requests/P5.md)."""
    return None


# --- subcontract bills ---------------------------------------------------------------------------------------------

def recorded_recoveries(db, client_id, subcontractor_id, kind=None, exclude_cancelled=True):
    query = db.query(DBStoreSubconRecovery).filter(DBStoreSubconRecovery.client_id == client_id,
                                                   DBStoreSubconRecovery.subcontractor_id == subcontractor_id)
    if kind:
        query = query.filter(DBStoreSubconRecovery.kind == kind)
    out = []
    for r in query.order_by(DBStoreSubconRecovery.id).all():
        bill = db.get(models.DBSubBill, r.sub_bill_id)
        if exclude_cancelled and (bill is None or (bill.status or "") == "CANCELLED"):
            continue
        out.append(r)
    return out


def subbill_recovery_due(db, client_id, bill) -> dict:
    """For a subcontractor bill: material recovery due - what P3's issue records make recoverable (chargeable lines at
    their recovery rate, net of returns) and what wastage beyond the norms makes recoverable (at the penal rate) -
    less what has already been recovered on their bills. Read-only: the bill's own deductions are typed by its owner."""
    from app.services import store_outward
    order = db.get(models.DBSubcontractOrder, bill.order_id)
    sub_id = bill.contractor_id or (order.contractor_id if order else None)
    upto = date.fromisoformat(bill.period_to[:10]) if (bill.period_to or "")[:10] else date.today()
    material = []
    total_material = ZERO
    for l in store_outward.get_subcon_issues(db, sub_id, upto) or []:
        if not l.chargeable:
            continue
        item = db.get(models.DBItem, l.item_id)
        material.append({"issue_line_id": l.issue_line_id, "issue_date": l.issue_date.isoformat(), "item_code": item.item_code if item else "",
                         "item_name": item.item_name if item else "", "issued": s(l.qty_issued, _QTY), "returned": s(l.qty_returned, _QTY),
                         "rate": s(l.recovery_rate), "value": s(l.recovery_value, _VALUE)})
        total_material += D(l.recovery_value)
    rec = reconciliation(db, client_id, "subcontractor", sub_id, upto, project_id=order.job_id if order else None) if sub_id else None
    wastage = [r for r in (rec["rows"] if rec else []) if D(r["recoverable"]) > 0]
    total_wastage = sum((D(r["recoverable"]) for r in wastage), ZERO)
    done_m = sum((D(r.amount) for r in recorded_recoveries(db, client_id, sub_id, "MATERIAL")), ZERO)
    done_w = sum((D(r.amount) for r in recorded_recoveries(db, client_id, sub_id, "EXCESS_WASTAGE")), ZERO)
    on_bill = [{"id": r.id, "kind": r.kind, "amount": s(r.amount, _VALUE), "note": r.note or "", "by": r.recorded_by_name or "",
                "at": r.recorded_at.isoformat(timespec="seconds")}
               for r in db.query(DBStoreSubconRecovery).filter(DBStoreSubconRecovery.sub_bill_id == bill.id).order_by(DBStoreSubconRecovery.id)]
    return {"sub_bill_id": bill.id, "number": bill.number, "subcontractor_id": sub_id, "upto": upto.isoformat(),
            "material": material, "material_recoverable": s(total_material, _VALUE), "material_recovered": s(done_m, _VALUE),
            "material_due": s(max(total_material - done_m, ZERO), _VALUE),
            "wastage": wastage, "wastage_recoverable": s(total_wastage, _VALUE), "wastage_recovered": s(done_w, _VALUE),
            "wastage_due": s(max(total_wastage - done_w, ZERO), _VALUE),
            "total_due": s(max(total_material - done_m, ZERO) + max(total_wastage - done_w, ZERO), _VALUE),
            "on_this_bill": on_bill,
            "note": "A guide for the bill's deductions. Recording a recovery here does not change the bill; type the deduction on it as usual."}


def record_recovery(db, client_id, bill, kind, amount, note, actor):
    """Note a recovery decided against this bill (at most what is due of that kind)."""
    if kind not in ("MATERIAL", "EXCESS_WASTAGE"):
        raise HTTPException(400, "Kind is MATERIAL or EXCESS_WASTAGE.")
    if (bill.status or "") == "CANCELLED":
        raise HTTPException(409, "A cancelled bill takes no recovery.")
    due = D(subbill_recovery_due(db, client_id, bill)["material_due" if kind == "MATERIAL" else "wastage_due"])
    amount = q(D(str(amount)), _VALUE)
    if amount <= 0:
        raise HTTPException(400, "Enter the amount recovered.")
    if amount > due:
        raise HTTPException(400, "Only %s of %s recovery is due." % (s(due, _VALUE), "material" if kind == "MATERIAL" else "excess-wastage"))
    order = db.get(models.DBSubcontractOrder, bill.order_id)
    row = DBStoreSubconRecovery(client_id=client_id, sub_bill_id=bill.id, subcontractor_id=bill.contractor_id or (order.contractor_id if order else None),
                                kind=kind, amount=amount, note=(note or "").strip(), recorded_by=actor.user_id, recorded_by_name=actor.name)
    db.add(row)
    db.flush()
    return row


# --- client billing ------------------------------------------------------------------------------------------------

def client_billing_data(db, client_id, project_id=0, work_order_id=0) -> dict:
    """For the client billing owner, read-only: client-supplied material to recover in the RA bill (consumed at the
    agreed rate), and the value of material at site (what the project's stores hold). Billing rules are not touched;
    whoever owns RA bills decides how to use it."""
    if work_order_id and not project_id:
        wo = db.get(models.DBWorkOrder, work_order_id)
        if wo is None or wo.client_id != client_id:
            raise HTTPException(404, "Work order not found")
        project_id = wo.job_id
    supply = client_supply_reconciliation(db, client_id, project_id, work_order_id)
    at_site, lines = ZERO, []
    for st in db.query(DBStore).filter(DBStore.client_id == client_id, DBStore.project_id == project_id).all() if project_id else []:
        for b in db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == st.id, DBStoreStockBalance.qty > 0).all():
            item = db.get(models.DBItem, b.item_id)
            lines.append({"store": st.code, "item_code": item.item_code, "item_name": item.item_name, "qty": s(b.qty, _QTY), "value": s(b.value, _VALUE)})
            at_site += D(b.value)
    return {"project_id": project_id, "work_order_id": work_order_id or None,
            "client_supply": {"rows": supply["rows"], "recovery_value": supply["totals"].get("recovery_value", "0.00"),
                              "balance_value": supply["totals"].get("balance_value", "0.00")},
            "material_at_site": {"value": s(at_site, _VALUE), "lines": lines},
            "note": "Read-only data for client RA bills. No billing rule uses it until the billing owner wires it in."}


# --- the old stock screens -----------------------------------------------------------------------------------------

def legacy_status(db, client_id) -> dict:
    """Whether the old stock screens should hand over to the Store module: once the company has a store and its old
    balances have been carried over (a posted LEGACY opening), or it never had old stock."""
    active = store_active(db, client_id)
    has_old = db.query(models.DBStockMovement.id).filter(models.DBStockMovement.client_id == client_id).first() is not None
    migrated = db.query(DBStoreOpening.id).filter(DBStoreOpening.client_id == client_id, DBStoreOpening.source == "LEGACY",
                                                  DBStoreOpening.status == DocStatus.POSTED.value).first() is not None
    return {"store_active": active, "legacy_movements": has_old, "legacy_migrated": migrated,
            "redirect": active and (migrated or not has_old), "legacy_receipt_blocked": active}
