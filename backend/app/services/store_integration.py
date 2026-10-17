"""Store module - what the rest of the ERP (costing, billing) reads from the store. Owned by P5.

  * get_project_material_cost: material charged to a project, from the ledger, net of reversals and of material returned.
  * sync_subcon_recoveries: makes the subcontract billing's material-recovery rows from chargeable subcontractor issues, so the
    next bill deducts what the store gave the subcontractor. It only adds to / withdraws from rows the store itself made (tracked in
    store_recovery_link) and never touches a row a bill has already taken.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from sqlalchemy import func

from app import models
from app.models.store_core import DBStoreItemSettings, DBStoreStockLedger, DocStatus, MovementType
from app.models.store_outward import DBStoreIssue, DBStoreIssueLine
from app.models.store_reports import DBStoreRecoveryLink
from app.schemas.store_contracts import MaterialCostLine
from app.services import store_outward

ZERO = Decimal("0")
# Movements that charge material to a project, and the returns that take some of it back. Reversals reuse the type with the
# opposite direction, so signing by direction nets everything out.
COST_MOVEMENTS = (MovementType.ISSUE_OUT.value, MovementType.SUBCON_ISSUE_OUT.value, MovementType.WASTAGE_OUT.value,
                  MovementType.ISSUE_RETURN_IN.value, MovementType.SUBCON_RETURN_IN.value)


def _day(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def get_project_material_cost(db, project_id, from_date, to_date) -> List[MaterialCostLine]:
    """Material issued to a project between two dates, by cost head, work order, BOQ item and item (net of returns and reversals)."""
    q = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.project_id == project_id, DBStoreStockLedger.movement_type.in_(COST_MOVEMENTS))
    if _day(from_date):
        q = q.filter(DBStoreStockLedger.txn_date >= _day(from_date))
    if _day(to_date):
        q = q.filter(DBStoreStockLedger.txn_date <= _day(to_date))
    groups = {}
    for e in q.all():
        key = (e.cost_head, e.work_order_id, e.boq_item_id, e.item_id)
        qty, value = groups.get(key, (ZERO, ZERO))
        out = e.qty_out > 0
        groups[key] = (qty + (e.qty_out if out else -e.qty_in), value + (e.value if out else -e.value))
    return [MaterialCostLine(project_id=project_id, cost_head=h, work_order_id=w, boq_item_id=b, item_id=i, qty=qty, value=value)
            for (h, w, b, i), (qty, value) in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])) if qty != 0 or value != 0]


# =============================================================================================== subcontract recoveries
_DEAD_ORDER = ("DRAFT", "CANCELLED", "CANCELED", "SUPERSEDED", "REJECTED")


def _order_for(db, client_id, contractor_id, job_id):
    rows = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractOrder.contractor_id == contractor_id,
                                                      models.DBSubcontractOrder.job_id == job_id).order_by(models.DBSubcontractOrder.id.desc()).all()
    return next((o for o in rows if (o.status or "").upper() not in _DEAD_ORDER), None)


def sync_subcon_recoveries(db, client_id) -> dict:
    """Bring material_recoveries in line with the store's chargeable subcontractor issues. The caller commits."""
    created = updated = withdrawn = 0
    skipped = []
    issues = db.query(DBStoreIssue).filter(DBStoreIssue.client_id == client_id, DBStoreIssue.issue_type == "SUBCONTRACTOR").all()
    for issue in issues:
        lines = db.query(DBStoreIssueLine).filter(DBStoreIssueLine.issue_id == issue.id, DBStoreIssueLine.chargeable.is_(True)).all()
        live = issue.status == DocStatus.POSTED.value
        for l in lines:
            link = db.query(DBStoreRecoveryLink).filter(DBStoreRecoveryLink.issue_line_id == l.id).first()
            rec = db.get(models.DBMaterialRecovery, link.recovery_id) if link else None
            back, _lost = store_outward._gone_from_issue_line(db, l.id, posted_only=True)
            net = (l.qty - back) if live else ZERO
            if rec is not None and rec.sub_bill_id:
                continue                                                  # a bill has taken it; leave it as billed
            if net <= 0:
                if rec is not None:
                    db.delete(link)
                    db.flush()
                    db.delete(rec)
                    withdrawn += 1
                continue
            rate = l.recovery_rate or l.rate or ZERO
            amount = (net * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if rec is not None:
                if abs(float(net) - (rec.quantity or 0)) > 1e-9 or abs(float(amount) - (rec.amount or 0)) > 1e-9:
                    rec.quantity, rec.rate, rec.amount = float(net), float(rate), float(amount)
                    updated += 1
                continue
            order = _order_for(db, client_id, issue.subcontractor_id, issue.project_id)
            if order is None:
                skipped.append({"issue": issue.number, "reason": "No active subcontract order for this subcontractor on the project."})
                continue
            item = db.get(models.DBItem, l.item_id)
            st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == l.item_id).first()
            rec = models.DBMaterialRecovery(client_id=client_id, order_id=order.id, job_id=issue.project_id, issue_number=issue.number, item_code=item.item_code,
                                            item_name=item.item_name, uom=(st.base_uom if st else item.units_of_measure) or "", quantity=float(net), rate=float(rate),
                                            amount=float(amount), issued_on=issue.issue_date.isoformat())
            db.add(rec)
            db.flush()
            db.add(DBStoreRecoveryLink(client_id=client_id, issue_line_id=l.id, recovery_id=rec.id))
            created += 1
    db.flush()
    return {"created": created, "updated": updated, "withdrawn": withdrawn, "skipped": skipped}
