"""The rules and workings behind the client orders endpoints."""
from datetime import datetime

from app import models

from app.core.currency import money, unit_rate


def preload_work_orders(db, client_id, orders):
    """Everything work_order_to_dict asks for, fetched once for a whole list.

    A list of a hundred orders used to cost three hundred queries - the job,
    the budget total and the line count for each row, one at a time. On a
    database an ocean away that is half a minute for a screen that should
    take a blink. Three GROUP BYs now cover the lot.
    """
    ids = [w.id for w in orders]
    if not ids:
        return {"jobs": {}, "cost": {}, "lines": {}}
    from sqlalchemy import func
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client_id).all()}
    cost = dict(db.query(models.DBBomLine.work_order_id,
                         func.coalesce(func.sum(models.DBBomLine.amount), 0.0)).filter(
        models.DBBomLine.work_order_id.in_(ids)).group_by(
            models.DBBomLine.work_order_id).all())
    lines = dict(db.query(models.DBWorkOrderLine.work_order_id,
                          func.count(models.DBWorkOrderLine.id)).filter(
        models.DBWorkOrderLine.work_order_id.in_(ids)).group_by(
            models.DBWorkOrderLine.work_order_id).all())
    return {"jobs": jobs, "cost": cost, "lines": lines}


def financial_year(on_date: str):
    """The Indian financial year containing a date: April to March."""
    try:
        d = datetime.strptime((on_date or "")[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        d = datetime.now()
    start = d.year if d.month >= 4 else d.year - 1
    return "01/04/%d - 31/03/%d" % (start, start + 1)


def budget_report(db, client, wo):
    """The allocation, gathered under the lines it was allocated against.

    Every sold line appears, including the ones nothing has been budgeted
    against yet. A material that was never costed is the single thing this
    report exists to make visible, and leaving those lines out would hide
    exactly the case somebody is printing it to find.
    """
    job = db.query(models.DBJob).filter(models.DBJob.id == wo.job_id).first()
    sold = db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).all()
    allocated = db.query(models.DBBomLine).filter(
        models.DBBomLine.work_order_id == wo.id).all()

    by_fg = {}
    for b in allocated:
        by_fg.setdefault((b.fg_code or "").upper(), []).append(b)

    groups = []
    for line in sold:
        code = (line.fg_code or "").upper()
        materials = [{
            "rm_code": b.rm_code, "rm_name": b.rm_name,
            "description": "%s  -  %s" % (b.rm_code, b.rm_name),
            "qty": money(b.qty), "uom": b.uom or "",
            "rate": unit_rate(b.rate), "wo_qty": money(line.qty),
            "amount": money(b.amount),
        } for b in by_fg.get(code, [])]
        cost = money(sum(m["amount"] for m in materials))
        value = money(line.amount)
        groups.append({
            "fg_code": line.fg_code, "item_name": line.item_name,
            "description": line.description or "",
            "qty": money(line.qty), "uom": line.uom or "",
            "rate": unit_rate(line.rate), "value": value,
            "cost": cost, "margin": money(value - cost),
            "budgeted": bool(materials), "lines": materials,
        })

    cost = money(sum(g["cost"] for g in groups))
    value = money(wo.total_value or 0)
    return {
        "title": "Budget Entry Report",
        "company": client.company_name or "",
        "printed_at": datetime.now().strftime("%d/%m/%Y   %H:%M"),
        "fiscal_year": financial_year(wo.order_date),
        "sale_order_no": wo.reference or wo.number,
        "work_order_no": wo.number,
        "order_date": wo.order_date or "",
        "project": (job.name if job else ""),
        "project_number": (job.number if job else ""),
        "customer": (job.customer_name if job else ""),
        "status": wo.status or "Draft",
        "approval_status": wo.approval_status or "none",
        "groups": groups,
        "totals": {
            "ordered_lines": len(groups),
            "material_lines": len(allocated),
            "unbudgeted_lines": len([g for g in groups if not g["budgeted"]]),
            "value": value, "cost": cost, "margin": money(value - cost),
            "margin_percent": round((value - cost) / value * 100, 1) if value else 0.0,
        },
    }
