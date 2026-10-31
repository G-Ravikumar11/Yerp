"""Quality holds on store batches.

A batch is on hold while any hold on it is active: one placed by hand, or one for each open NCR raised against it. Each
stands alone, so closing an NCR lifts that NCR's hold and nothing else. `DBStoreBatch.on_hold` is what the stock ledger
reads, with the batch row locked, so a hold and an issue cannot pass each other: whichever commits second sees the first.
"""
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.models.store_core import DBStore, DBStoreBatch, DBStoreBatchBalance, DBStoreBatchHold, DBStoreLedgerBatch, DBStoreStockLedger, MovementType
from app.models.store_extras import REJECTION_HELD, DBStoreRejection
from app.models.store_inward import DBStoreGrn
from app.core.audit import log_audit
from app.core.config import logger
from app.core.scheduler import scheduled_job
from app.services.stock_ledger import lot_label, post_movement


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
            if n is None or n.status in ("CLOSED", "REJECTED"):
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


def hold_for_failed_check(db, client_id, batch, grn, line, note, who):
    """A lot that failed its quality check at the gate. In the transaction that records the check; one hold for one line."""
    key = "q:%d" % line.id
    if db.query(DBStoreBatchHold.id).filter(DBStoreBatchHold.hold_key == key).first():
        return
    db.add(DBStoreBatchHold(client_id=client_id, batch_id=batch.id, kind="QC", hold_key=key, reason=("Failed quality inspection: %s" % note)[:500],
                            inspection_ref=("%s line %s, checked by %s" % (grn.number, line.line_no, who))[:200], placed_by=who))
    batch.on_hold = True


def lift_failed_check(db, client_id, line, who):
    """The check was recorded again and now passes: that hold goes, and nothing else."""
    h = db.query(DBStoreBatchHold).filter(DBStoreBatchHold.hold_key == "q:%d" % line.id, DBStoreBatchHold.status == "ACTIVE").first()
    if h is not None:
        h.status, h.hold_key, h.released_by, h.released_at, h.release_note = "RELEASED", None, who, _now(), "Quality check passed on re-inspection"
        sync(db, lock_batch(db, client_id, h.batch_id))


def place_manual(db, client_id, batch, reason, remarks, who):
    h = DBStoreBatchHold(client_id=client_id, batch_id=batch.id, kind="MANUAL", hold_key="m:%d" % batch.id, reason=reason[:500], remarks=(remarks or "").strip()[:1000], placed_by=who)
    db.add(h)
    batch.on_hold = True
    return h


def release_manual(db, batch, note, who):
    """Lifts a manual hold and a failed check's hold. NCR holds lift when their NCRs close."""
    mine = db.query(DBStoreBatchHold).filter(DBStoreBatchHold.batch_id == batch.id, DBStoreBatchHold.kind.in_(("MANUAL", "QC")), DBStoreBatchHold.status == "ACTIVE").all()
    h = mine[0] if mine else None
    open_ncrs = [x for x in active_holds(db, batch.id) if x.kind == "NCR"]
    if h is None and open_ncrs:
        raise HTTPException(409, "This batch is held by %s. It is released when that is closed." % ", ".join(_ncr_of(db, x).number for x in open_ncrs))
    if h is None and not batch.on_hold:
        raise HTTPException(409, "This batch is not on hold.")
    for x in mine:
        x.status, x.hold_key, x.released_by, x.released_at, x.release_note = "RELEASED", None, who, _now(), (note or "").strip()[:1000]
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


def reject_for_ncr(db, client_id, ncr, reason, user_id, who):
    """The lot is rejected: all that is left of it leaves usable stock for Rejected Goods, store by store, by one ledger
    entry each. In the transaction that rejects the NCR, so both happen or neither. Any other hold stays on the record."""
    batch = lock_batch(db, client_id, ncr.store_batch_id)
    moved = []
    balances = db.query(DBStoreBatchBalance).filter(DBStoreBatchBalance.batch_id == batch.id, DBStoreBatchBalance.qty > 0).order_by(DBStoreBatchBalance.id).all()
    for b in [(x.store_id, x.item_id, Decimal(str(x.qty))) for x in balances]:
        store_id, item_id, qty = b
        post_movement(db, movement_type=MovementType.REJECTED_OUT, store_id=store_id, item_id=item_id, qty=qty, rate=None, txn_date=date.today(), project_id=None, ref_doc_type="NCR_REJECT",
                      ref_doc_id=ncr.id, ref_line_id=store_id, user_id=user_id, remarks="%s rejected" % ncr.number, lots=[(batch.id, qty)])
        db.add(DBStoreRejection(client_id=client_id, store_id=store_id, item_id=item_id, ncr_id=ncr.id, batch_id=batch.id, qty=qty, reason=(reason or "")[:300], status=REJECTION_HELD, rejected_by=who))
        moved.append(format(qty.normalize(), "f"))
    for h in db.query(DBStoreBatchHold).filter(DBStoreBatchHold.ncr_id == ncr.id, DBStoreBatchHold.status == "ACTIVE").all():
        h.status, h.hold_key, h.released_by, h.released_at, h.release_note = "RELEASED", None, who, _now(), "NCR %s rejected: lot moved to Rejected Goods" % ncr.number
    batch.lot_status = "REJECTED"
    sync(db, batch)
    return {"on_hold": False, "rejected": True, "message": "Batch %s rejected: %s moved to Rejected Goods." % (lot_label(batch), " + ".join(moved) or "nothing on hand")}


def outcome(db, batch):
    """Where the batch stands, in words a person can act on."""
    held = active_holds(db, batch.id)
    label = lot_label(batch)
    if not held:
        return {"on_hold": False, "message": "Batch %s has been released and can be issued." % label}
    why = [("manual hold" if h.kind == "MANUAL" else "failed quality inspection" if h.kind == "QC" else "open %s" % _ncr_of(db, h).number) for h in held]
    return {"on_hold": True, "message": "Batch %s remains on hold because of: %s." % (label, ", ".join(why))}


def hold_dict(db, h):
    n = _ncr_of(db, h)
    return {"id": h.id, "kind": h.kind, "status": h.status, "reason": h.reason or "", "remarks": h.remarks or "", "ncr_id": h.ncr_id, "ncr_number": n.number if n else "", "ncr_status": n.status if n else "", "inspection_ref": h.inspection_ref or "",
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
    expired = b.expiry_date is not None and b.expiry_date < date.today() and available > 0
    status = "Rejected" if b.lot_status == "REJECTED" else "On Hold" if held else "Expired" if expired else "Released" if ever else "Available"
    project_id = (grn.project_id if grn else None) or next((s.project_id for s in stores.values() if s.project_id), None)
    job = db.get(models.DBJob, project_id) if project_id else None
    out = {"id": b.id, "batch_no": lot_label(b), "item_id": b.item_id, "item_name": item.item_name if item else "", "item_code": item.item_code if item else "", "uom": item.units_of_measure if item else "",
           "supplier": (grn.supplier_name if grn else "") or b.source or "", "job_id": project_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
           "received_qty": format(Decimal(str(received or 0)).normalize(), "f"), "available_qty": format(available.normalize(), "f"), "expiry_date": b.expiry_date.isoformat() if b.expiry_date else "",
           "lot_id": b.id, "hold_status": status, "status_code": {"On Hold": "ON_HOLD", "Rejected": "REJECTED", "Expired": "EXPIRED"}.get(status, "AVAILABLE"), "blocked": bool(held) or status in ("Rejected", "Expired"),
           "held_at": held[0].placed_at if held else "", "held_by": held[0].placed_by if held else "",
           "hold_reason": "; ".join(h.reason or "" for h in held), "ncrs": [{"id": h.ncr_id, "number": _ncr_of(db, h).number} for h in held if h.kind == "NCR"]}
    if detail:
        out["holds"] = [hold_dict(db, h) for h in db.query(DBStoreBatchHold).filter(DBStoreBatchHold.batch_id == b.id).order_by(DBStoreBatchHold.id.desc()).all()]
        out["all_ncrs"] = [{"id": n.id, "number": n.number, "status": n.status, "raised_on": n.raised_on or "", "description": (n.description or "")[:200]}
                           for n in db.query(models.DBNcr).filter(models.DBNcr.store_batch_id == b.id).order_by(models.DBNcr.id.desc()).all()]
    return out


@scheduled_job("store_expiry_watch")
def note_expired_lots(db, now_):
    """Puts each lot on the audit trail the day it is found expired, once. Nothing is written off or moved: an expired lot
    is kept from issue by its date, and stays in the store until someone deals with it."""
    today = now_.date()
    noted = 0
    for b in db.query(DBStoreBatch).filter(DBStoreBatch.expiry_date < today, DBStoreBatch.expired_noted.isnot(True)).all():
        held = db.query(func.coalesce(func.sum(DBStoreBatchBalance.qty), 0)).filter(DBStoreBatchBalance.batch_id == b.id).scalar()
        if held and held > 0:
            log_audit(db, b.client_id, "store.batch.expired", entity_type="store_batch", entity_id=b.id, entity_name=b.batch_no, details="Expired %s with %s on hand" % (b.expiry_date, held), user_name="System")
            noted += 1
        b.expired_noted = True
    db.commit()
    logger.info("Expired lots noted: %d", noted)
    return "%d lots" % noted
