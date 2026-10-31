"""Store batches and their quality holds. Placing a hold is open to those who receive stock and those who sign off site work;
releasing one is for those who sign off. Both lock the batch row, so they cannot cross an issue being posted."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.store_core import DBStoreBatch
from app.services import store_holds as sh
from app.core.dates import _parse_date
from app.services.stock_ledger import HIDDEN_LOT
from app.services.store_batches import default_expiry, shelf_days

router = APIRouter(prefix="/api/store/batches", tags=["store-batches"])
READ = ("store.enquiry.view", "site.signoff", "site.record")
PLACE = ("store.inward.create", "site.signoff")
RELEASE = ("site.signoff",)


class HoldIn(BaseModel):
    reason: str = ""
    remarks: Optional[str] = ""


class ReleaseIn(BaseModel):
    note: str = ""


@router.get("")
def list_batches(request: Request, q: str = "", hold_status: str = "", page: int = 1, per_page: int = 25, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, READ)
    query = db.query(DBStoreBatch).filter(DBStoreBatch.client_id == actor.client.id, ~DBStoreBatch.batch_no.like(HIDDEN_LOT + "%"))
    if q:
        like = "%" + q.strip() + "%"
        ids = [i for (i,) in db.query(models.DBItem.id).filter(models.DBItem.client_id == actor.client.id, models.DBItem.item_name.ilike(like)).all()]
        query = query.filter(DBStoreBatch.batch_no.ilike(like) | DBStoreBatch.item_id.in_(ids or [0]))
    rows = query.order_by(DBStoreBatch.on_hold.desc(), DBStoreBatch.id.desc()).all()
    hold_status = {"ON_HOLD": "On Hold", "AVAILABLE": "Available", "EXPIRED": "Expired", "REJECTED": "Rejected"}.get(hold_status, hold_status)
    views = [sh.batch_view(db, b) for b in rows] if hold_status else None
    if views is not None:
        views = [v for v in views if v["hold_status"] == hold_status]
    per_page = max(1, min(per_page, 100))
    start = (max(1, page) - 1) * per_page
    shown = views[start:start + per_page] if views is not None else [sh.batch_view(db, b) for b in rows[start:start + per_page]]
    return {"batches": shown, "total": len(views if views is not None else rows), "page": page, "per_page": per_page}


def _read_one(request, db, bid):
    actor = store_actor(request, db, READ)
    b = db.query(DBStoreBatch).filter(DBStoreBatch.id == bid, DBStoreBatch.client_id == actor.client.id).first()
    if b is None:
        raise HTTPException(404, "Batch not found")
    return b


@router.get("/shelf-life/{item_id}")
def shelf_life(item_id: int, request: Request, made: str = "", db: Session = Depends(get_read_db)):
    """What a receipt of this item has to give, and the expiry it comes to: the same sum as saving it."""
    actor = store_actor(request, db, READ + ("store.inward.view", "store.inward.create"))
    item = db.query(models.DBItem).filter(models.DBItem.id == item_id, models.DBItem.client_id == actor.client.id).first()
    if item is None:
        raise HTTPException(404, "Item not found")
    day = _parse_date(made)
    expiry = default_expiry(item, day) if day else None
    return {"applicable": bool(item.shelf_life_applicable), "days": shelf_days(item), "tracked": bool(item.expiry_tracking), "expiry_date": expiry.isoformat() if expiry else ""}


@router.get("/{bid}")
def get_batch(bid: int, request: Request, db: Session = Depends(get_read_db)):
    """The batch, every hold it has had, and every NCR against it."""
    return sh.batch_view(db, _read_one(request, db, bid), detail=True)


@router.get("/{bid}/ncrs")
def batch_ncrs(bid: int, request: Request, db: Session = Depends(get_read_db)):
    return {"ncrs": sh.batch_view(db, _read_one(request, db, bid), detail=True)["all_ncrs"]}


@router.post("/{bid}/hold")
def place_hold(bid: int, body: HoldIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, PLACE)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Say why the batch is being held.")
    b = sh.lock_batch(db, actor.client.id, bid)
    h = sh.place_manual(db, actor.client.id, b, reason, body.remarks, actor.name)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This batch already has a manual hold.")
    log_audit(db, actor.client.id, "store.batch.hold_placed", entity_type="store_batch", entity_id=b.id, entity_name=b.batch_no, details=reason[:500], request=request, user_name=actor.name)
    db.commit()
    return {"batch": sh.batch_view(db, b, detail=True), "hold_id": h.id, "message": "Batch placed on hold. It cannot be issued."}


@router.post("/{bid}/release")
def release_hold(bid: int, body: ReleaseIn, request: Request, db: Session = Depends(get_db)):
    """Lifts the manual hold. An open NCR keeps the batch on hold, and the answer says so."""
    actor = store_actor(request, db, RELEASE)
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "Say why the hold is being released.")
    b = sh.lock_batch(db, actor.client.id, bid)
    result = sh.release_manual(db, b, note, actor.name)
    log_audit(db, actor.client.id, "store.batch.hold_released", entity_type="store_batch", entity_id=b.id, entity_name=b.batch_no, details=note[:500], request=request, user_name=actor.name)
    db.commit()
    return {"batch": sh.batch_view(db, b, detail=True), **result}
