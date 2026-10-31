"""Quality holds on store batches.

A batch is on hold while any hold on it is active: one placed by hand, or one for each open NCR raised against it. Each
stands alone, so closing an NCR lifts that NCR's hold and nothing else. `DBStoreBatch.on_hold` is what the stock ledger
reads, with the batch row locked, so a hold and an issue cannot pass each other: whichever commits second sees the first.
"""
from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import DBStore, DBStoreBatch, DBStoreBatchBalance, DBStoreBatchHold, DBStoreLedgerBatch, DBStoreStockLedger
from app.models.store_inward import DBStoreGrn
from app.services.stock_ledger import lot_label


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def lock_batch(db, client_id, batch_id):
    """The batch, row-locked until this transaction ends, read fresh from the database."""
    b = (db.query(DBStoreBatch).filter(DBStoreBatch.id == batch_id, DBStoreBatch.client_id == client_id)
         .populate_existing().with_for_update().first())
    if b is None:
        raise HTTPException(404, "Batch not found")
    return b


def _ncr_of(db, hold):
    return db.get(models.DBNcr, hold.ncr_id) if hold.ncr_id else None


def active_holds(db, batch_id):
    """The holds standing now. An NCR hold stands only while its NCR is open and still exists."""
    rows = db.query(DBStoreBatchHold).filter(DBStoreBatchHold.batch_id == batch_id, DBStoreBatchHold.status == "ACTIVE").order_by(DBStoreBatchHold.id).all()
    out = []
    for h in rows:
        if h.kind == "NCR":
            n = _ncr_of(db, h)
            if n is None or n.status == "CLOSED":
                continue
        out.append(h)
    return out


def sync(db, batch):
    db.flush()
    batch.on_hold = bool(active_holds(db, batch.id))


def hold_for_ncr(db, client_id, batch, ncr, reason, who):
    """Called with the batch locked, in the transaction that creates the NCR."""
    db.add(DBStoreBatchHold(client_id=client_id, batch_id=batch.id, kind="NCR", ncr_id=ncr.id, hold_key="n:%d:%d" % (batch.id, ncr.id), reason=reason[:500], placed_by=who))
    batch.on_hold = True


def place_manual(db, client_id, batch, reason, remarks, who):
    h = DBStoreBatchHold(client_id=client_id, batch_id=batch.id, kind="MANUAL", hold_key="m:%d" % batch.id, reason=reason[:500], remarks=(remarks or "").strip()[:1000], placed_by=who)
    db.add(h)
    batch.on_hold = True
    return h


def release_manual(db, batch, note, who):
    """Lifts the manual hold only. NCR holds lift when their NCRs close."""
    h = db.query(DBStoreBatchHold).filter(DBStoreBatchHold.batch_id == batch.id, DBStoreBatchHold.kind == "MANUAL", DBStoreBatchHold.status == "ACTIVE").first()
    open_ncrs = [x for x in active_holds(db, batch.id) if x.kind == "NCR"]
    if h is None and open_ncrs:
        raise HTTPException(409, "This batch is held by %s. It is released when that is closed." % ", ".join(_ncr_of(db, x).number for x in open_ncrs))
    if h is None and not batch.on_hold:
        raise HTTPException(409, "This batch is not on hold.")
    if h is not None:
        h.status, h.hold_key, h.released_by, h.released_at, h.release_note = "RELEASED", None, who, _now(), (note or "").strip()[:1000]
    sync(db, batch)
    return outcome(db, batch)


def on_ncr_closed(db, client_id, ncr, who):
    """The NCR's hold ends; the batch is released only if nothing else holds it. In the transaction that closes the NCR."""
    if not ncr.store_batch_id:
        return None
    batch = lock_batch(db, client_id, ncr.store_batch_id)
    for h in db.query(DBStoreBatchHold).filter(DBStoreBatchHold.ncr_id == ncr.id, DBStoreBatchHold.status == "ACTIVE").all():
        h.status, h.hold_key, h.released_by, h.released_at, h.release_note = "RELEASED", None, who, _now(), "NCR %s closed" % ncr.number
    sync(db, batch)
    return outcome(db, batch)


def outcome(db, batch):
    """Where the batch stands, in words a person can act on."""
    held = active_holds(db, batch.id)
    label = lot_label(batch)
    if not held:
        return {"on_hold": False, "message": "Batch %s has been released and can be issued." % label}
    why = [("manual hold" if h.kind == "MANUAL" else "open %s" % _ncr_of(db, h).number) for h in held]
    return {"on_hold": True, "message": "Batch %s remains on hold because of: %s." % (label, ", ".join(why))}


def hold_dict(db, h):
    n = _ncr_of(db, h)
    return {"id": h.id, "kind": h.kind, "status": h.status, "reason": h.reason or "", "remarks": h.remarks or "", "ncr_id": h.ncr_id, "ncr_number": n.number if n else "", "ncr_status": n.status if n else "",
            "placed_by": h.placed_by or "", "placed_at": h.placed_at or "", "released_by": h.released_by or "", "released_at": h.released_at or "", "release_note": h.release_note or ""}


def batch_view(db, b, detail=False):
    """A batch as the screens show it: how much came in, how much is left, who it came from and where it stands."""
    held = active_holds(db, b.id)
    ever = db.query(DBStoreBatchHold.id).filter(DBStoreBatchHold.batch_id == b.id).first() is not None
    item = db.get(models.DBItem, b.item_id)
    balances = db.query(DBStoreBatchBalance).filter(DBStoreBatchBalance.batch_id == b.id).all()
    available = sum((Decimal(str(x.qty or 0)) for x in balances), Decimal("0"))
    received = db.query(func.coalesce(func.sum(DBStoreLedgerBatch.qty), 0)).join(DBStoreStockLedger, DBStoreStockLedger.id == DBStoreLedgerBatch.ledger_id).filter(
        DBStoreLedgerBatch.batch_id == b.id, DBStoreStockLedger.qty_in > 0, DBStoreStockLedger.reversal_of_id.is_(None)).scalar()
    grn_ref = db.query(DBStoreStockLedger.ref_doc_id).join(DBStoreLedgerBatch, DBStoreStockLedger.id == DBStoreLedgerBatch.ledger_id).filter(
        DBStoreLedgerBatch.batch_id == b.id, DBStoreStockLedger.ref_doc_type == "GRN").first()
    grn = db.get(DBStoreGrn, grn_ref[0]) if grn_ref else None
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.id.in_([x.store_id for x in balances] or [0])).all()}
    project_id = (grn.project_id if grn else None) or next((s.project_id for s in stores.values() if s.project_id), None)
    job = db.get(models.DBJob, project_id) if project_id else None
    out = {"id": b.id, "batch_no": lot_label(b), "item_id": b.item_id, "item_name": item.item_name if item else "", "item_code": item.item_code if item else "", "uom": item.units_of_measure if item else "",
           "supplier": (grn.supplier_name if grn else "") or b.source or "", "job_id": project_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
           "received_qty": format(Decimal(str(received or 0)).normalize(), "f"), "available_qty": format(available.normalize(), "f"), "expiry_date": b.expiry_date.isoformat() if b.expiry_date else "",
           "hold_status": "On Hold" if held else "Released" if ever else "Available", "blocked": bool(held),
           "hold_reason": "; ".join(h.reason or "" for h in held), "ncrs": [{"id": h.ncr_id, "number": _ncr_of(db, h).number} for h in held if h.kind == "NCR"]}
    if detail:
        out["holds"] = [hold_dict(db, h) for h in db.query(DBStoreBatchHold).filter(DBStoreBatchHold.batch_id == b.id).order_by(DBStoreBatchHold.id.desc()).all()]
        out["all_ncrs"] = [{"id": n.id, "number": n.number, "status": n.status, "raised_on": n.raised_on or "", "description": (n.description or "")[:200]}
                           for n in db.query(models.DBNcr).filter(models.DBNcr.store_batch_id == b.id).order_by(models.DBNcr.id.desc()).all()]
    return out

