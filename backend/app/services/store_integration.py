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


# --- the older screens' questions, answered with the Hub in them ------------------------------------------------------
# Purchase orders, project costs, material planning and the e-way check were written against the old store. Receipts
# and issues now come through the Hub as well, so these count both: the old store's history, and the Hub from its start.

def _per_unit(db, item, uom, seen):
    """How many of the item's base unit one `uom` is: 1 for the base unit itself, None when the Hub has no conversion."""
    from app.models.store_core import DBStoreUomConversion
    from app.services.store_inward import base_uom_of
    if item is None:
        return None
    key = (item.id, (uom or "").strip().lower())
    if key not in seen:
        if not key[1] or key[1] == base_uom_of(db, item).lower():
            seen[key] = Decimal(1)
        else:
            conv = next((c for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).all()
                         if c.from_uom.strip().lower() == key[1]), None)
            seen[key] = Decimal(str(conv.to_base_factor)) if conv and conv.to_base_factor else None
    return seen[key]


def hub_received_on_orders(db, po_ids):
    """What the Hub has accepted against purchase orders, in each order line's own unit and net of what went back to the
    supplier: ({po_id: {po_line_id: qty}}, {po_id: number of receipts}). Posted receipts only, for a whole list in a
    handful of queries."""
    from app.models.store_core import DocStatus
    from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
    from app.services.store_inward import _returned_by_grn_line
    ids = list({i for i in (po_ids or []) if i})
    if not ids:
        return {}, {}
    posted = (DocStatus.POSTED.value,)
    rows = (db.query(DBStoreGrn.po_id, DBStoreGrn.id, DBStoreGrnLine.id, DBStoreGrnLine.po_line_id, DBStoreGrnLine.item_id, DBStoreGrnLine.accepted_qty)
            .join(DBStoreGrnLine, DBStoreGrnLine.grn_id == DBStoreGrn.id)
            .filter(DBStoreGrn.po_id.in_(ids), DBStoreGrn.status.in_(posted)).all())
    if not rows:
        return {}, {}
    back = _returned_by_grn_line(db, [r[2] for r in rows], posted)
    po_lines = {l.id: l for l in db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.id.in_({r[3] for r in rows if r[3]} or {0})).all()}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_({r[4] for r in rows})).all()}
    received, receipts, seen = {}, {}, {}
    for po, grn, gl, pl, item_id, accepted in rows:
        receipts.setdefault(po, set()).add(grn)
        if pl not in po_lines:
            continue
        base = Decimal(str(accepted or 0)) - back.get(gl, ZERO)
        per = _per_unit(db, items.get(item_id), po_lines[pl].uom, seen)
        slot = received.setdefault(po, {})
        slot[pl] = float(Decimal(str(slot.get(pl, 0))) + (base / per if per else base))
    return received, {po: len(g) for po, g in receipts.items()}


def hub_received_po_lines(db, client_id):
    """The purchase-order lines the Hub has booked into stock (posted receipts): what a supplier bill paid for there is
    stock, charged to a job when it is issued and not when it is bought."""
    from app.models.store_core import DocStatus
    from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
    return {pl for (pl,) in db.query(DBStoreGrnLine.po_line_id).join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id).filter(
        DBStoreGrn.client_id == client_id, DBStoreGrn.status == DocStatus.POSTED.value, DBStoreGrnLine.po_line_id.isnot(None),
        DBStoreGrnLine.accepted_qty > 0).distinct().all()}


def old_received_in_base(db, lines_with_items):
    """What the old store's posted receipts accepted on purchase-order lines, in each item's base unit. `lines_with_items`
    is {po_line_id: (po line, stock item)}. The Hub's receipt summary adds it, so an order half received before the
    cut-over is not shown as wholly pending after it."""
    if not lines_with_items:
        return {}
    got = {}
    for pl, qty in db.query(models.DBGoodsReceiptLine.po_line_id, models.DBGoodsReceiptLine.accepted_qty).join(
            models.DBGoodsReceipt, models.DBGoodsReceipt.id == models.DBGoodsReceiptLine.goods_receipt_id).filter(
            models.DBGoodsReceiptLine.po_line_id.in_(list(lines_with_items)), models.DBGoodsReceipt.status == "POSTED").all():
        got[pl] = got.get(pl, 0.0) + (qty or 0.0)
    out, seen = {}, {}
    for pl, qty in got.items():
        line, item = lines_with_items[pl]
        per = _per_unit(db, item, line.uom, seen)
        out[pl] = (Decimal(str(qty)) * per if per else Decimal(str(qty))).quantize(Decimal("0.001"))
    return out


def current_stock(db, client_id, codes=None):
    """{item code: {item_code, item_name, uom, on_hand, value, rate}}: what the company holds now, in the shape the older
    screens read. Until the company moves its old store into the Hub that is the old store, as it always was; after the
    cut-over it is the Hub's stores together, which began from the old store's closing stock."""
    from app.models.store_core import DBStoreStockBalance
    from app.services.store_cutover import cutover_of
    from app.services.stores import stock_balances
    if codes is not None:
        codes = {c for c in codes if c}
        if not codes:
            return {}
    if cutover_of(db, client_id) is None:
        return stock_balances(db, client_id, item_codes=codes)
    q = (db.query(models.DBItem.item_code, models.DBItem.item_name, models.DBItem.units_of_measure,
                  func.sum(DBStoreStockBalance.qty), func.sum(DBStoreStockBalance.value))
         .join(DBStoreStockBalance, DBStoreStockBalance.item_id == models.DBItem.id)
         .join(DBStore, DBStore.id == DBStoreStockBalance.store_id)
         .filter(DBStore.client_id == client_id))
    if codes is not None:
        q = q.filter(models.DBItem.item_code.in_(list(codes)))
    out = {}
    for code, name, uom, qty, value in q.group_by(models.DBItem.item_code, models.DBItem.item_name, models.DBItem.units_of_measure).all():
        on_hand, worth = float(qty or 0), float(value or 0)
        out[code] = {"item_code": code, "item_name": name or "", "uom": uom or "", "on_hand": round(on_hand, 3),
                     "value": round(worth, 2), "rate": round(worth / on_hand, 4) if on_hand else 0.0}
    return out


def _dispatched(db, client_id, number=None):
    """Hub transfers that have left their store and were not cancelled."""
    from app.models.store_control import DBStoreTransfer
    from app.models.store_core import DocStatus
    q = (db.query(DBStoreTransfer).join(DBStore, DBStore.id == DBStoreTransfer.store_id)
         .filter(DBStore.client_id == client_id, DBStoreTransfer.status == DocStatus.POSTED.value))
    if number is not None:
        q = q.filter(DBStoreTransfer.number == number)
    return q.all()


def hub_transfers_out(db, client_id):
    """{transfer number: value} for every Hub transfer dispatched: goods on the road, which need an e-way bill over the limit."""
    from app.models.store_control import DBStoreTransferLine
    docs = {t.id: t.number for t in _dispatched(db, client_id)}
    if not docs:
        return {}
    return {docs[tid]: float(Decimal(str(value or 0)).quantize(Decimal("0.01")))
            for tid, value in db.query(DBStoreTransferLine.transfer_id, func.sum(DBStoreTransferLine.value)).filter(
                DBStoreTransferLine.transfer_id.in_(list(docs))).group_by(DBStoreTransferLine.transfer_id).all()}


def hub_transfer_lines(db, client_id, number):
    """The lines of one dispatched Hub transfer, by its number, at what they left at and with HSN: for its e-way bill.
    [] when there is no such transfer."""
    from app.models.store_control import DBStoreTransferLine
    docs = _dispatched(db, client_id, number)
    if not docs:
        return []
    out = []
    for l in db.query(DBStoreTransferLine).filter(DBStoreTransferLine.transfer_id == docs[0].id).order_by(
            DBStoreTransferLine.line_no, DBStoreTransferLine.id).all():
        item = db.get(models.DBItem, l.item_id)
        out.append({"item_code": item.item_code if item else "", "item_name": item.item_name if item else "",
                    "hsn": (item.hsn_code if item else "") or "", "qty": float(l.qty or 0),
                    "uom": (item.units_of_measure if item else "") or "", "value": float(l.value or 0)})
    return out


def hub_debit_notes(db, po_ids):
    """Posted purchase returns against purchase orders - the debit notes the supplier's bills are matched net of:
    {po_id: [{number, date, value, tax, total}]}."""
    from app.models.store_core import DocStatus
    from app.models.store_inward import DBStoreGrn, DBStorePurchaseReturn
    ids = list({i for i in (po_ids or []) if i})
    if not ids:
        return {}
    out = {}
    for r, po in (db.query(DBStorePurchaseReturn, DBStoreGrn.po_id).join(DBStoreGrn, DBStoreGrn.id == DBStorePurchaseReturn.grn_id)
                  .filter(DBStoreGrn.po_id.in_(ids), DBStorePurchaseReturn.status == DocStatus.POSTED.value).order_by(DBStorePurchaseReturn.id).all()):
        value, tax = float(r.debit_value or 0), float(r.tax_value or 0)
        out.setdefault(po, []).append({"id": r.id, "number": r.number, "date": r.return_date.isoformat() if r.return_date else "",
                                       "value": round(value, 2), "tax": round(tax, 2), "total": round(value + tax, 2)})
    return out
