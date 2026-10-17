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
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockLedger, MovementType
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


def _issue_facts(db, store_ids):
    """For each subcontractor issue line posted from these stores: (issue id, issue number, project id, subcontractor id), read from the shared ledger."""
    out = {}
    for e in db.query(DBStoreStockLedger).filter(DBStoreStockLedger.store_id.in_(store_ids or [0]), DBStoreStockLedger.movement_type == MovementType.SUBCON_ISSUE_OUT.value,
                                                 DBStoreStockLedger.reversal_of_id.is_(None)).all():
        number = (e.remarks or "")[len("Issue "):] if (e.remarks or "").startswith("Issue ") else "ISSUE-%s" % e.ref_doc_id
        out[e.ref_line_id] = (e.ref_doc_id, number, e.project_id, e.subcontractor_id)
    return out


def sync_subcon_recoveries(db, client_id) -> dict:
    """Bring material_recoveries in line with the store's chargeable subcontractor issues. The caller commits.

    Reads the outward slice only through get_subcon_issues (posted issues, with what came back) and the shared ledger."""
    created = updated = withdrawn = 0
    skipped = []
    stores = [i for (i,) in db.query(DBStore.id).filter(DBStore.client_id == client_id).all()]
    facts = _issue_facts(db, stores)
    live = set()
    for sub_id in sorted({f[3] for f in facts.values() if f[3]}):
        for l in store_outward.get_subcon_issues(db, sub_id, date.today()):
            if not l.chargeable or l.issue_line_id not in facts:
                continue
            live.add(l.issue_line_id)
            _issue_id, number, project_id, _sub = facts[l.issue_line_id]
            net = l.qty_issued - l.qty_returned
            link = db.query(DBStoreRecoveryLink).filter(DBStoreRecoveryLink.issue_line_id == l.issue_line_id).first()
            rec = db.get(models.DBMaterialRecovery, link.recovery_id) if link else None
            if rec is not None and rec.sub_bill_id:
                continue                                                  # a bill has taken it; leave it as billed
            if net <= 0:
                if rec is not None:
                    db.delete(link)
                    db.flush()
                    db.delete(rec)
                    withdrawn += 1
                continue
            rate = l.recovery_rate or ZERO
            amount = (net * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if rec is not None:
                if abs(float(net) - (rec.quantity or 0)) > 1e-9 or abs(float(amount) - (rec.amount or 0)) > 1e-9:
                    rec.quantity, rec.rate, rec.amount = float(net), float(rate), float(amount)
                    updated += 1
                continue
            order = _order_for(db, client_id, sub_id, project_id)
            if order is None:
                skipped.append({"issue": number, "reason": "No active subcontract order for this subcontractor on the project."})
                continue
            item = db.get(models.DBItem, l.item_id)
            st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == l.item_id).first()
            rec = models.DBMaterialRecovery(client_id=client_id, order_id=order.id, job_id=project_id, issue_number=number, item_code=item.item_code, item_name=item.item_name,
                                            uom=(st.base_uom if st else item.units_of_measure) or "", quantity=float(net), rate=float(rate), amount=float(amount),
                                            issued_on=l.issue_date.isoformat())
            db.add(rec)
            db.flush()
            db.add(DBStoreRecoveryLink(client_id=client_id, issue_line_id=l.issue_line_id, recovery_id=rec.id))
            created += 1
    # issues that are no longer posted (cancelled) give their unbilled recovery back
    for link in db.query(DBStoreRecoveryLink).filter(DBStoreRecoveryLink.client_id == client_id).all():
        if link.issue_line_id in live:
            continue
        rec = db.get(models.DBMaterialRecovery, link.recovery_id)
        if rec is not None and rec.sub_bill_id:
            continue
        db.delete(link)
        db.flush()
        if rec is not None:
            db.delete(rec)
        withdrawn += 1
    db.flush()
    return {"created": created, "updated": updated, "withdrawn": withdrawn, "skipped": skipped}
