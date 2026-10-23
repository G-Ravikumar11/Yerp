"""Goods turned away at the gate: a receipt line with a rejected quantity leaves a HELD record when the receipt posts, and the storekeeper
closes it by saying the goods went back to the supplier or were disposed of. Cancelling the receipt voids what it left. No stock is involved:
rejected goods are never taken into a store."""
from datetime import date

from fastapi import HTTPException

from app.models.store_extras import REJECTION_DISPOSED, REJECTION_HELD, REJECTION_RETURNED, REJECTION_VOID, DBStoreRejection
from app.models.store_inward import DBStoreGrnLine


def record_for_grn(db, grn):
    """One HELD record for each line of a posted receipt that turned goods away (once per line)."""
    lines = db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id, DBStoreGrnLine.rejected_qty > 0).all()
    have = {r for (r,) in db.query(DBStoreRejection.grn_line_id).filter(DBStoreRejection.grn_id == grn.id).all()}
    for l in lines:
        if l.id not in have:
            db.add(DBStoreRejection(client_id=grn.client_id, store_id=grn.store_id, grn_id=grn.id, grn_line_id=l.id, item_id=l.item_id, qty=l.rejected_qty,
                                    reason=l.reject_reason or "", status=REJECTION_HELD))
    db.flush()


def void_for_grn(db, grn):
    db.query(DBStoreRejection).filter(DBStoreRejection.grn_id == grn.id, DBStoreRejection.status != REJECTION_VOID).update({"status": REJECTION_VOID}, synchronize_session=False)


def resolve(db, actor, row, outcome, note="", vehicle_no="", on_date=None):
    outcome = (outcome or "").strip().upper()
    if outcome not in (REJECTION_RETURNED, REJECTION_DISPOSED):
        raise HTTPException(400, "Say whether the goods were RETURNED to the supplier or DISPOSED of.")
    if row.status != REJECTION_HELD:
        raise HTTPException(409, "These goods are already %s." % row.status.lower())
    note = " ".join((note or "").split())[:300]
    if outcome == REJECTION_DISPOSED and len(note) < 3:
        raise HTTPException(400, "Say how the goods were disposed of.")
    vehicle = " ".join((vehicle_no or "").split())[:30]
    if outcome == REJECTION_RETURNED and not vehicle:
        raise HTTPException(400, "Give the vehicle number they went back on.")
    day = on_date or date.today()
    if day > date.today():
        raise HTTPException(400, "The date cannot be in the future.")
    row.status, row.resolved_on, row.resolved_by_name, row.vehicle_no, row.resolution_note = outcome, day, actor.name, vehicle, note
    db.flush()
    return row
