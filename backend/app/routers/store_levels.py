"""Store module - levels per store, under /api/store/levels: an item's reorder, minimum and maximum quantity for one store where it differs from the
item's own, and a scan that raises the alert for any item already below its level. store.masters.view reads; store.masters.create changes."""
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockBalance
from app.models.store_extras import DBStoreItemLevel
from app.routers.store_masters import visible_store_ids
from app.services import store_levels
from app.services.stock_ledger import assert_store_access, raise_reorder_alert

router = APIRouter(prefix="/api/store/levels", tags=["store-levels"])
ZERO = Decimal("0")


class LevelIn(BaseModel):
    reorder_level: Optional[str] = None      # empty = use the item's own
    min_qty: Optional[str] = None
    max_qty: Optional[str] = None


def _num(x):
    return format(Decimal(str(x)).quantize(Decimal("0.001")), "f")


def _opt(raw, what):
    if raw is None or str(raw).strip() == "":
        return None
    try:
        d = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite() or d < 0 or d > Decimal("999999999999"):
        raise HTTPException(400, "%s must be zero or more." % what)
    return d


def _row(o, item, s):
    base = s.base_uom if s else item.units_of_measure
    return {"store_id": o.store_id, "item_id": o.item_id, "item_code": item.item_code, "item_name": item.item_name, "base_uom": base or "",
            "reorder_level": None if o.reorder_level is None else _num(o.reorder_level), "min_qty": None if o.min_qty is None else _num(o.min_qty),
            "max_qty": None if o.max_qty is None else _num(o.max_qty),
            "default_reorder_level": _num(s.reorder_level if s else 0), "default_min_qty": _num(s.min_qty if s else 0), "default_max_qty": _num(s.max_qty if s else 0)}


def _store(db, actor, store_id):
    store = db.get(DBStore, store_id)
    if store is None or store.client_id != actor.client.id:
        raise HTTPException(404, "Store not found")
    assert_store_access(actor.user, store.id)
    return store


def _item(db, actor, item_id):
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id or item.kind != "RM":
        raise HTTPException(404, "Item not found")
    return item


@router.get("/{store_id}")
def store_levels_list(store_id: int, request: Request, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, "store.masters.view")
    store = _store(db, actor, store_id)
    rows = db.query(DBStoreItemLevel).filter(DBStoreItemLevel.store_id == store.id).all()
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([r.item_id for r in rows] or [0])).all()}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([r.item_id for r in rows] or [0])).all()}
    return {"items": sorted((_row(r, items[r.item_id], sets.get(r.item_id)) for r in rows), key=lambda x: x["item_name"].lower())}


@router.put("/{store_id}/{item_id}")
def save_level(store_id: int, item_id: int, body: LevelIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    store, item = _store(db, actor, store_id), _item(db, actor, item_id)
    reorder, low, high = _opt(body.reorder_level, "Reorder level"), _opt(body.min_qty, "Minimum quantity"), _opt(body.max_qty, "Maximum quantity")
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    eff_low = low if low is not None else (s.min_qty if s else 0)
    eff_high = high if high is not None else (s.max_qty if s else 0)
    if eff_high and Decimal(str(eff_low or 0)) > Decimal(str(eff_high)):
        raise HTTPException(400, "The minimum cannot be more than the maximum.")
    if reorder is None and low is None and high is None:
        raise HTTPException(400, "Give at least one level, or remove this store's levels instead.")
    row = db.query(DBStoreItemLevel).filter(DBStoreItemLevel.store_id == store.id, DBStoreItemLevel.item_id == item.id).first()
    if row is None:
        row = DBStoreItemLevel(store_id=store.id, item_id=item.id)
        db.add(row)
    row.reorder_level, row.min_qty, row.max_qty = reorder, low, high
    db.flush()
    log_audit(db, actor.client.id, "store_item_level", "store", store.id, store.code, "%s reorder %s min %s max %s" % (item.item_code, reorder, low, high),
              user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
    db.commit()
    return _row(row, item, s)


@router.delete("/{store_id}/{item_id}")
def remove_level(store_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    store, item = _store(db, actor, store_id), _item(db, actor, item_id)
    row = db.query(DBStoreItemLevel).filter(DBStoreItemLevel.store_id == store.id, DBStoreItemLevel.item_id == item.id).first()
    if row is None:
        raise HTTPException(404, "This store has no levels of its own for that item.")
    db.delete(row)
    db.commit()
    return {"message": "The item's own levels apply again"}


@router.post("/scan")
def scan(request: Request, db: Session = Depends(get_db)):
    """Raise the alert for every item already at or below its reorder level in a store with none open - stock that fell below before alerts
    were kept, or whose level was raised afterwards. Only the stores this person works in."""
    actor = store_actor(request, db, "store.masters.create")
    seen = visible_store_ids(db, actor)                                 # the stores this person works in (all of them for an administrator)
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == actor.client.id, DBStore.is_active.is_(True)).all() if seen is None or s.id in seen}
    if not stores:
        return {"raised": 0}
    over = store_levels.overrides(db, list(stores))
    held = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id.in_(list(stores))).all()
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([b.item_id for b in held] or [0])).all()}
    raised = 0
    try:
        for bal in held:
            level = store_levels.effective(sets.get(bal.item_id), over.get((bal.store_id, bal.item_id)))[0]
            if level > 0 and Decimal(str(bal.qty)) <= level:
                item = db.get(models.DBItem, bal.item_id)
                if item is not None and raise_reorder_alert(db, actor.client.id, stores[bal.store_id], item, Decimal(str(bal.qty)), level):
                    raised += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"raised": raised}
