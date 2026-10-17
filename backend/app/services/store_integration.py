"""Store module - what the rest of the ERP (costing, billing, purchasing) reads from the store. Owned by P5.

Material cost is read straight from the stock ledger. The movements that are a cost to a project are the ones that consume stock:
ISSUE_OUT, SUBCON_ISSUE_OUT, WASTAGE_OUT and SCRAP_OUT; what comes back from site (ISSUE_RETURN_IN, SUBCON_RETURN_IN) is taken off. A reversal is
a row of the same movement type in the opposite column, so it nets by itself; its `txn_date` is the day it was made. Transfers between stores
are not consumption and are left out, and so are receipts and adjustments. Values are the ledger's own (issues at the average rate of the day).
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import case, func

from app import models
from app.models.store_core import DBStore, DBStoreStockLedger, MovementType
from app.schemas.store_contracts import MaterialCostLine, PoLineReceipt

ZERO = Decimal("0")
COST_OUT = (MovementType.ISSUE_OUT.value, MovementType.SUBCON_ISSUE_OUT.value, MovementType.WASTAGE_OUT.value, MovementType.SCRAP_OUT.value)
COST_BACK = (MovementType.ISSUE_RETURN_IN.value, MovementType.SUBCON_RETURN_IN.value)
COST_TYPES = COST_OUT + COST_BACK


def _day(x, default) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return default


def signed_value():
    """The ledger row's value as a cost: positive when stock was consumed, negative when it came back (or when a consumption was reversed)."""
    out_cost = case((DBStoreStockLedger.qty_out > 0, DBStoreStockLedger.value), else_=-DBStoreStockLedger.value)
    back_cost = case((DBStoreStockLedger.qty_in > 0, -DBStoreStockLedger.value), else_=DBStoreStockLedger.value)
    return case((DBStoreStockLedger.movement_type.in_(COST_OUT), out_cost), else_=back_cost)


def signed_qty():
    """The quantity as consumption, the way value is a cost: stock going out is positive, stock coming back is negative, whichever type the row is."""
    return DBStoreStockLedger.qty_out - DBStoreStockLedger.qty_in


def material_cost_rows(db, client_id, project_id=None, from_date=None, to_date=None, store_ids=None, boq_item_id=None):
    """Consumption by (project, cost head, work order, BOQ item, item) for one company, net of returns and reversals.
    Returns [(project_id, cost_head, work_order_id, boq_item_id, item_id, qty, value)] with the zero rows left out."""
    q = (db.query(DBStoreStockLedger.project_id, DBStoreStockLedger.cost_head, DBStoreStockLedger.work_order_id, DBStoreStockLedger.boq_item_id, DBStoreStockLedger.item_id,
                  func.sum(signed_qty()), func.sum(signed_value()))
         .join(DBStore, DBStore.id == DBStoreStockLedger.store_id)
         .filter(DBStore.client_id == client_id, DBStoreStockLedger.movement_type.in_(COST_TYPES), DBStoreStockLedger.project_id.isnot(None)))
    if project_id:
        q = q.filter(DBStoreStockLedger.project_id == project_id)
    if from_date:
        q = q.filter(DBStoreStockLedger.txn_date >= _day(from_date, date.min))
    if to_date:
        q = q.filter(DBStoreStockLedger.txn_date <= _day(to_date, date.max))
    if store_ids is not None:
        q = q.filter(DBStoreStockLedger.store_id.in_(list(store_ids) or [0]))
    if boq_item_id:
        q = q.filter(DBStoreStockLedger.boq_item_id == boq_item_id)
    rows = q.group_by(DBStoreStockLedger.project_id, DBStoreStockLedger.cost_head, DBStoreStockLedger.work_order_id, DBStoreStockLedger.boq_item_id, DBStoreStockLedger.item_id).all()
    return [(p, h, w, b, i, Decimal(str(qty or 0)), Decimal(str(val or 0))) for p, h, w, b, i, qty, val in rows if (qty or 0) != 0 or (val or 0) != 0]


def get_project_material_cost(db, project_id, from_date, to_date) -> List[MaterialCostLine]:
    """Material issued to a project between two dates, by cost head, work order and BOQ item.

    Net of what came back from site and of reversals, in the item's base unit and at the ledger's value. Lines are sorted by cost head, work
    order, BOQ item and item so a caller can total them in groups. A project with nothing issued gives []."""
    job = db.get(models.DBJob, project_id) if project_id else None
    if job is None:
        return []
    rows = material_cost_rows(db, job.client_id, project_id=project_id, from_date=from_date, to_date=to_date)
    lines = [MaterialCostLine(project_id=p, cost_head=h, work_order_id=w, boq_item_id=b, item_id=i, qty=qty.quantize(Decimal("0.001")), value=val.quantize(Decimal("0.01")))
             for p, h, w, b, i, qty, val in rows]
    return sorted(lines, key=lambda l: (l.cost_head or "", l.work_order_id or 0, l.boq_item_id or 0, l.item_id))


def project_store_material(db, project_id) -> Decimal:
    """What the store has issued to a project in all, net: the figure the project's costing shows beside its bills."""
    total = (db.query(func.sum(signed_value())).filter(DBStoreStockLedger.project_id == project_id, DBStoreStockLedger.movement_type.in_(COST_TYPES)).scalar())
    return Decimal(str(total or 0)).quantize(Decimal("0.01"))


def store_material_by_project(db, client_id) -> dict:
    """{project_id: net value issued} for a company - one query, for the project board."""
    rows = (db.query(DBStoreStockLedger.project_id, func.sum(signed_value())).join(DBStore, DBStore.id == DBStoreStockLedger.store_id)
            .filter(DBStore.client_id == client_id, DBStoreStockLedger.movement_type.in_(COST_TYPES), DBStoreStockLedger.project_id.isnot(None))
            .group_by(DBStoreStockLedger.project_id).all())
    return {p: Decimal(str(v or 0)).quantize(Decimal("0.01")) for p, v in rows}


def po_receipt_for_order(db, po_id) -> List[dict]:
    """What the store has received against a purchase order, line by line, for the purchase-order screens (posted receipts only)."""
    from app.services import store_inward
    out = []
    for r in store_inward.get_po_receipt_summary(db, po_id) or []:
        r: PoLineReceipt
        out.append({"po_line_id": r.po_line_id, "item_id": r.item_id, "ordered_qty": str(r.ordered_qty), "received_qty": str(r.received_qty), "accepted_qty": str(r.accepted_qty),
                    "rejected_qty": str(r.rejected_qty), "pending_qty": str(r.pending_qty)})
    return out


def subcon_material_to_recover(db, contractor_id, upto: Optional[date] = None) -> Decimal:
    """What is still to be recovered from a subcontractor's bills for material the store issued them (chargeable lines, net of returns)."""
    from app.services import store_outward
    total = ZERO
    for l in store_outward.get_subcon_issues(db, contractor_id, upto or date.today()) or []:
        total += l.recovery_value
    return total.quantize(Decimal("0.01"))
