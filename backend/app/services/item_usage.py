"""Where an item is used: the BOQs, orders and stock records that carry its code."""
from sqlalchemy import func

from app import models
from app.constants.boq import BOQ_PRICED
from app.services.site_rates import current_lines_of_item

SHOWN = 10          # rows listed per kind; the count is always the full one


def _group(key, label, count, rows):
    return {"key": key, "label": label, "count": count, "rows": rows[:SHOWN], "more": max(0, count - SHOWN)}


def where_used(db, client_id, item):
    """Every place the item's code appears, grouped, with the full count of each and the first few rows."""
    code, groups = item.item_code, []

    lines = current_lines_of_item(db, client_id, None, code)
    rows = []
    for l in lines:
        boq = db.query(models.DBBoq).get(l.boq_id)
        job = db.query(models.DBJob).get(boq.job_id) if boq else None
        if boq:
            rows.append({"label": "%s - %s" % (boq.number or "BOQ", job.name if job else ""), "detail": "quantity %g %s" % (l.quantity or 0, l.uom or ""),
                         "path": "/projects/boq/%d" % boq.id})
    groups.append(_group("boq", "BOQs", len(rows), rows))

    wo = db.query(models.DBWorkOrder.id, models.DBWorkOrder.number, models.DBWorkOrder.status).join(
        models.DBWorkOrderLine, models.DBWorkOrderLine.work_order_id == models.DBWorkOrder.id).filter(
        models.DBWorkOrder.client_id == client_id, models.DBWorkOrderLine.fg_code == code).distinct().all()
    groups.append(_group("client_orders", "Client work orders", len(wo),
                         [{"label": n or "Work order", "detail": s or "", "path": "/clients/work-orders"} for _, n, s in wo]))

    po = db.query(models.DBPurchaseOrder.id, models.DBPurchaseOrder.number, models.DBPurchaseOrder.supplier_name).join(
        models.DBPurchaseOrderLineItem, models.DBPurchaseOrderLineItem.order_id == models.DBPurchaseOrder.id).filter(
        models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrderLineItem.item_code == code).distinct().all()
    groups.append(_group("purchase_orders", "Purchase orders", len(po),
                         [{"label": n or "Purchase order", "detail": s or "", "path": "/store/purchase-orders"} for _, n, s in po]))

    so = db.query(models.DBSubcontractOrder.id, models.DBSubcontractOrder.wo_number, models.DBSubcontractOrder.status).join(
        models.DBSubcontractItem, models.DBSubcontractItem.order_id == models.DBSubcontractOrder.id).filter(
        models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractItem.item_code == code).distinct().all()
    groups.append(_group("contractor_orders", "Contractor orders", len(so),
                         [{"label": n or "Contractor order", "detail": s or "", "path": "/subcontractors/work-orders/%d" % i} for i, n, s in so]))

    budgets = db.query(func.count(models.DBBomLine.id)).filter(
        models.DBBomLine.client_id == client_id, (models.DBBomLine.fg_code == code) | (models.DBBomLine.rm_code == code)).scalar() or 0
    groups.append(_group("budgets", "Budget lines", budgets, []))
    moves = db.query(func.count(models.DBStockMovement.id)).filter(
        models.DBStockMovement.client_id == client_id, models.DBStockMovement.item_code == code).scalar() or 0
    groups.append(_group("stock", "Store movements", moves, []))
    groups = [g for g in groups if g["count"]]
    return {"total": sum(g["count"] for g in groups), "groups": groups}


def used_codes(db, client_id, codes):
    """Which of these codes appear on a BOQ, order or in the store: four queries however many are asked about."""
    codes = list(codes)
    if not codes:
        return set()
    found = set()
    found |= {c for (c,) in db.query(models.DBBoqLine.item_code).join(models.DBBoq, models.DBBoq.id == models.DBBoqLine.boq_id).filter(
        models.DBBoq.client_id == client_id, models.DBBoqLine.kind.in_(BOQ_PRICED), models.DBBoqLine.item_code.in_(codes)).distinct()}
    found |= {c for (c,) in db.query(models.DBWorkOrderLine.fg_code).join(
        models.DBWorkOrder, models.DBWorkOrder.id == models.DBWorkOrderLine.work_order_id).filter(
        models.DBWorkOrder.client_id == client_id, models.DBWorkOrderLine.fg_code.in_(codes)).distinct()}
    found |= {c for (c,) in db.query(models.DBPurchaseOrderLineItem.item_code).join(
        models.DBPurchaseOrder, models.DBPurchaseOrder.id == models.DBPurchaseOrderLineItem.order_id).filter(
        models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrderLineItem.item_code.in_(codes)).distinct()}
    found |= {c for (c,) in db.query(models.DBSubcontractItem.item_code).join(
        models.DBSubcontractOrder, models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id).filter(
        models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractItem.item_code.in_(codes)).distinct()}
    found |= {c for (c,) in db.query(models.DBStockMovement.item_code).filter(
        models.DBStockMovement.client_id == client_id, models.DBStockMovement.item_code.in_(codes)).distinct()}
    return found
