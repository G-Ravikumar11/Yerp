"""Store module - what suppliers still owe and how they have delivered: the pending-deliveries list (per supplier, per project), short-closing
an order that will not be delivered in full, and a supplier scorecard built from posted receipts. Nothing here moves stock."""
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException

from app import models
from app.models.store_core import DocStatus
from app.models.store_extras import DBStorePoClosure
from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
from app.services import store_inward as inward

ZERO = Decimal("0")
OPEN_STATES = ("Approved",)


def _day(raw):
    try:
        return datetime.strptime(str(raw or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def pending_deliveries(db, client_id, supplier="", project_id=0):
    """Every approved, not short-closed order with something still to come: [{po..., lines: [...]}], latest due first by days late."""
    q = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.status.in_(OPEN_STATES))
    q = q.filter(~models.DBPurchaseOrder.id.in_(db.query(DBStorePoClosure.po_id).filter(DBStorePoClosure.client_id == client_id)))
    if supplier.strip():
        q = q.filter(models.DBPurchaseOrder.supplier_name.ilike("%" + supplier.strip().replace("%", "").replace("_", "") + "%"))
    if project_id:
        q = q.filter(models.DBPurchaseOrder.job_id == project_id)
    today = date.today()
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    out = []
    for po in q.order_by(models.DBPurchaseOrder.id).all():
        summary = {s.po_line_id: s for s in inward.get_po_receipt_summary(db, po.id)}
        lines = db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po.id).order_by(models.DBPurchaseOrderLineItem.id).all()
        rows = []
        for l in lines:
            sm = summary.get(l.id)
            item = inward.po_item(db, po, l)
            if sm is None or item is None or sm.pending_qty <= 0:
                continue
            rows.append({"po_line_id": l.id, "item_code": item.item_code, "item_name": item.item_name, "base_uom": inward.base_uom_of(db, item),
                         "ordered": inward.s3(sm.ordered_qty), "accepted": inward.s3(sm.accepted_qty), "pending": inward.s3(sm.pending_qty)})
        if not rows:
            continue
        due = _day(po.needed_by)
        job = jobs.get(po.job_id)
        out.append({"po_id": po.id, "number": po.number, "supplier_name": po.supplier_name or "", "project_id": po.job_id, "project": (job.name or job.number) if job else "",
                    "issue_date": po.issue_date or "", "needed_by": due.isoformat() if due else "", "days_late": max(0, (today - due).days) if due else 0, "lines": rows})
    out.sort(key=lambda r: (-r["days_late"], r["number"]))
    return out


def short_close(db, actor, po_id, reason):
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None or po.client_id != actor.client.id:
        raise HTTPException(404, "Purchase order not found")
    reason = " ".join((reason or "").split())[:200]
    if len(reason) < 3:
        raise HTTPException(400, "Say why the order is being short-closed.")
    if inward.short_closed(db, po.id):
        raise HTTPException(409, "Purchase order %s is already short-closed." % po.number)
    if po.status not in OPEN_STATES:
        raise HTTPException(409, "Purchase order %s is %s; only an approved order is short-closed." % (po.number, (po.status or "not approved").lower()))
    live = (db.query(DBStoreGrn.number).filter(DBStoreGrn.po_id == po.id, DBStoreGrn.status.in_((DocStatus.DRAFT.value, DocStatus.SUBMITTED.value, DocStatus.APPROVED.value))).first())
    if live:
        raise HTTPException(409, "Receipt %s is still open against this order. Post or cancel it first." % live[0])
    row = DBStorePoClosure(client_id=actor.client.id, po_id=po.id, reason=reason, closed_by_name=actor.name)
    db.add(row)
    db.flush()
    return row


def reopen(db, actor, po_id):
    row = db.query(DBStorePoClosure).filter(DBStorePoClosure.po_id == po_id, DBStorePoClosure.client_id == actor.client.id).first()
    if row is None:
        raise HTTPException(404, "That order is not short-closed.")
    db.delete(row)
    db.flush()


def short_closed_orders(db, client_id):
    rows = db.query(DBStorePoClosure, models.DBPurchaseOrder).join(models.DBPurchaseOrder, models.DBPurchaseOrder.id == DBStorePoClosure.po_id).filter(DBStorePoClosure.client_id == client_id).order_by(DBStorePoClosure.id.desc()).all()
    return [{"po_id": c.po_id, "number": po.number, "supplier_name": po.supplier_name or "", "reason": c.reason or "", "closed_by": c.closed_by_name or "",
             "closed_at": c.closed_at.isoformat(timespec="seconds") if c.closed_at else ""} for c, po in rows]


def supplier_scorecard(db, client_id):
    """Per supplier, from the orders placed and the receipts posted against them: how much of the order value arrived accepted, how much was
    turned away, and how many orders with a needed-by date had their first delivery on or before it."""
    pos = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.status.in_(("Approved", "Closed"))).all()
    if not pos:
        return []
    by_po = {p.id: p for p in pos}
    ordered = {}
    for oid, qty, price in db.query(models.DBPurchaseOrderLineItem.order_id, models.DBPurchaseOrderLineItem.qty, models.DBPurchaseOrderLineItem.price).filter(
            models.DBPurchaseOrderLineItem.order_id.in_(list(by_po))).all():
        ordered[oid] = ordered.get(oid, ZERO) + Decimal(str(qty or 0)) * Decimal(str(price or 0))
    recv = {}
    first = {}
    for po_id, gdate, acc, rej, rate in (db.query(DBStoreGrn.po_id, DBStoreGrn.grn_date, DBStoreGrnLine.accepted_qty, DBStoreGrnLine.rejected_qty, DBStoreGrnLine.rate)
                                         .join(DBStoreGrnLine, DBStoreGrnLine.grn_id == DBStoreGrn.id)
                                         .filter(DBStoreGrn.po_id.in_(list(by_po)), DBStoreGrn.status == DocStatus.POSTED.value).all()):
        a, r = recv.get(po_id, (ZERO, ZERO)), Decimal(str(rate or 0))
        recv[po_id] = (a[0] + Decimal(str(acc or 0)) * r, a[1] + Decimal(str(rej or 0)) * r)
        if gdate is not None and (po_id not in first or gdate < first[po_id]):
            first[po_id] = gdate
    cards = {}
    for p in pos:
        name = (p.supplier_name or "").strip() or "(no supplier)"
        c = cards.setdefault(name, {"supplier_name": name, "orders": 0, "ordered_value": ZERO, "accepted_value": ZERO, "rejected_value": ZERO, "dated_orders": 0, "on_time": 0})
        c["orders"] += 1
        c["ordered_value"] += ordered.get(p.id, ZERO)
        acc, rej = recv.get(p.id, (ZERO, ZERO))
        c["accepted_value"] += acc
        c["rejected_value"] += rej
        due = _day(p.needed_by)
        if due is not None and p.id in first:
            c["dated_orders"] += 1
            c["on_time"] += 1 if first[p.id] <= due else 0
    out = []
    for c in cards.values():
        got = c["accepted_value"] + c["rejected_value"]
        out.append({"supplier_name": c["supplier_name"], "orders": c["orders"], "ordered_value": format(c["ordered_value"].quantize(Decimal("0.01")), "f"),
                    "accepted_value": format(c["accepted_value"].quantize(Decimal("0.01")), "f"), "rejected_value": format(c["rejected_value"].quantize(Decimal("0.01")), "f"),
                    "fill_pct": format((c["accepted_value"] * 100 / c["ordered_value"]).quantize(Decimal("0.1")), "f") if c["ordered_value"] > 0 else "0.0",
                    "rejection_pct": format((c["rejected_value"] * 100 / got).quantize(Decimal("0.1")), "f") if got > 0 else "0.0",
                    "on_time_pct": format((Decimal(c["on_time"]) * 100 / c["dated_orders"]).quantize(Decimal("0.1")), "f") if c["dated_orders"] else ""})
    out.sort(key=lambda r: r["supplier_name"].lower())
    return out
