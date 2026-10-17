"""Store module - enquiry routes under /api/store/enquiry. Owned by P1.

Read-only: what each store holds, and every movement behind it. A person sees only the stores they are assigned to
(everything with store.admin and for the account holder).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor
from app.db import get_db
from app.models.store_core import DBStore, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger, MovementType
from app.routers.store_masters import accessible_store_ids
from app.services.stock_ledger import assert_store_access, is_frozen

router = APIRouter(prefix="/api/store/enquiry", tags=["store-enquiry"])

ZERO = Decimal("0")


def _date(v: Optional[str], what: str) -> Optional[date]:
    if not v:
        return None
    try:
        return datetime.strptime(v[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s must be a date like 2026-04-01." % what) from None


def _visible_stores(actor, db, store_id: int):
    """The stores a query may cover: the one asked for (access checked), else all the person can reach."""
    if store_id:
        assert_store_access(actor.user, store_id)
        return [db.get(DBStore, store_id)]
    q = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    mine = accessible_store_ids(actor, db)
    if mine is not None:
        q = q.filter(DBStore.id.in_(mine or [0]))
    return q.order_by(DBStore.code).all()


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door (kept as the skeleton's smoke test expects); stock on hand is /stock."""
    store_actor(request, db, "store.enquiry.view")
    return {"slice": "enquiry", "items": []}


@router.get("/stock")
def stock_position(request: Request, store_id: int = 0, q: str = "", below_reorder: bool = False, include_zero: bool = False,
                   limit: int = 200, offset: int = 0, db: Session = Depends(get_db)):
    """Stock on hand, one row per store and item, with value and whether it is under its reorder level."""
    actor = store_actor(request, db, "store.enquiry.view")
    stores = _visible_stores(actor, db, store_id)
    ids = [s.id for s in stores] or [0]
    query = db.query(DBStoreStockBalance, models.DBItem).join(models.DBItem, models.DBItem.id == DBStoreStockBalance.item_id).filter(
        DBStoreStockBalance.store_id.in_(ids))
    if not include_zero:
        query = query.filter(DBStoreStockBalance.qty > 0)
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        like = "%" + term + "%"
        query = query.filter(models.DBItem.item_code.ilike(like) | models.DBItem.item_name.ilike(like))
    rows = query.order_by(models.DBItem.item_name, DBStoreStockBalance.store_id).all()
    settings = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_({b.item_id for b, _ in rows} or [0])).all()}
    by_store = {s.id: s for s in stores}
    out, total_value = [], ZERO
    for bal, item in rows:
        st = settings.get(item.id)
        reorder = (st.reorder_level or ZERO) if st else ZERO
        low = bool(reorder) and bal.qty <= reorder
        if below_reorder and not low:
            continue
        total_value += bal.value or ZERO
        out.append({"store_id": bal.store_id, "store_code": by_store[bal.store_id].code, "store_name": by_store[bal.store_id].name,
                    "item_id": item.id, "item_code": item.item_code, "item_name": item.item_name,
                    "base_uom": st.base_uom if st else (item.units_of_measure or ""), "category": st.category if st else None,
                    "qty": str(bal.qty), "avg_rate": str(bal.avg_rate), "value": str(bal.value),
                    "reorder_level": str(reorder), "below_reorder": low})
    page = out[max(offset, 0):max(offset, 0) + max(1, min(limit, 1000))]
    return {"rows": page, "total": len(out), "total_value": str(total_value),
            "frozen_store_ids": [s.id for s in stores if is_frozen(db, s.id)]}


@router.get("/ledger")
def ledger(request: Request, store_id: int = 0, item_id: int = 0, movement_type: str = "", from_date: str = "", to_date: str = "",
           project_id: int = 0, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    """Every movement, newest first. A reversal appears as its own row, flagged with the entry it undoes."""
    actor = store_actor(request, db, "store.enquiry.view")
    stores = _visible_stores(actor, db, store_id)
    by_store = {s.id: s for s in stores}
    query = db.query(DBStoreStockLedger, models.DBItem).join(models.DBItem, models.DBItem.id == DBStoreStockLedger.item_id).filter(
        DBStoreStockLedger.store_id.in_(list(by_store) or [0]))
    if item_id:
        query = query.filter(DBStoreStockLedger.item_id == item_id)
    if movement_type:
        if movement_type not in {m.value for m in MovementType}:
            raise HTTPException(400, "Unknown movement type.")
        query = query.filter(DBStoreStockLedger.movement_type == movement_type)
    if project_id:
        query = query.filter(DBStoreStockLedger.project_id == project_id)
    start, end = _date(from_date, "From date"), _date(to_date, "To date")
    if start:
        query = query.filter(DBStoreStockLedger.txn_date >= start)
    if end:
        query = query.filter(DBStoreStockLedger.txn_date <= end)
    total = query.count()
    rows = query.order_by(DBStoreStockLedger.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 500))).all()
    return {"total": total, "rows": [{
        "id": e.id, "txn_date": e.txn_date.isoformat(), "store_id": e.store_id, "store_code": by_store[e.store_id].code,
        "item_id": item.id, "item_code": item.item_code, "item_name": item.item_name, "movement_type": e.movement_type,
        "qty_in": str(e.qty_in), "qty_out": str(e.qty_out), "rate": str(e.rate), "value": str(e.value),
        "running_qty": str(e.running_qty), "running_value": str(e.running_value), "avg_rate": str(e.avg_rate),
        "project_id": e.project_id, "ref_doc_type": e.ref_doc_type, "ref_doc_id": e.ref_doc_id, "reversal_of_id": e.reversal_of_id,
        "remarks": e.remarks or "", "created_at": e.created_at.isoformat() if e.created_at else None} for e, item in rows]}


@router.get("/quick")
def quick_find(request: Request, q: str = "", limit: int = 8, db: Session = Depends(get_db)):
    """Type-ahead for the Store home page: a few matching items with the quantity held across the person's stores. One grouped query."""
    actor = store_actor(request, db, "store.enquiry.view")
    term = (q or "").strip().replace("%", "").replace("_", "")
    if len(term) < 2:
        return {"rows": []}
    like = "%" + term + "%"
    ids = [s.id for s in _visible_stores(actor, db, 0)] or [0]
    held = (db.query(DBStoreStockBalance.item_id.label("item_id"), func.sum(DBStoreStockBalance.qty).label("qty"), func.count(DBStoreStockBalance.store_id).label("stores"))
            .filter(DBStoreStockBalance.store_id.in_(ids), DBStoreStockBalance.qty > 0).group_by(DBStoreStockBalance.item_id).subquery())
    rows = (db.query(models.DBItem.id, models.DBItem.item_code, models.DBItem.item_name, models.DBItem.units_of_measure, held.c.qty, held.c.stores)
            .outerjoin(held, held.c.item_id == models.DBItem.id)
            .filter(models.DBItem.client_id == actor.client.id, models.DBItem.item_code.ilike(like) | models.DBItem.item_name.ilike(like))
            .order_by(held.c.qty.is_(None), models.DBItem.item_name).limit(max(1, min(limit, 20))).all())
    return {"rows": [{"item_id": r[0], "item_code": r[1], "item_name": r[2], "uom": r[3] or "", "qty": str(r[4] or 0), "stores": int(r[5] or 0)} for r in rows]}


@router.get("/items/{item_id}")
def item_position(item_id: int, request: Request, db: Session = Depends(get_db)):
    """One item across the stores the person can reach: balance in each and the last ten movements."""
    actor = store_actor(request, db, "store.enquiry.view")
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id:
        raise HTTPException(404, "Item not found")
    stores = {s.id: s for s in _visible_stores(actor, db, 0)}
    bals = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.item_id == item_id, DBStoreStockBalance.store_id.in_(list(stores) or [0])).all()
    st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    recent = db.query(DBStoreStockLedger).filter(DBStoreStockLedger.item_id == item_id, DBStoreStockLedger.store_id.in_(list(stores) or [0])).order_by(
        DBStoreStockLedger.id.desc()).limit(10).all()
    total_qty = sum((b.qty for b in bals), ZERO)
    total_value = sum((b.value for b in bals), ZERO)
    # Consumption over the last 30 days (net of reversals) gives a rough days-of-cover.
    since = date.today() - timedelta(days=30)
    used = sum((e.qty_out - e.qty_in for e in db.query(DBStoreStockLedger).filter(
        DBStoreStockLedger.item_id == item_id, DBStoreStockLedger.store_id.in_(list(stores) or [0]),
        DBStoreStockLedger.movement_type.in_(["ISSUE_OUT", "SUBCON_ISSUE_OUT", "WASTAGE_OUT"]), DBStoreStockLedger.txn_date >= since).all()), ZERO)
    return {"item": {"id": item.id, "code": item.item_code, "name": item.item_name, "base_uom": st.base_uom if st else (item.units_of_measure or ""),
                     "category": st.category if st else None, "reorder_level": str(st.reorder_level or 0) if st else "0"},
            "total_qty": str(total_qty), "total_value": str(total_value), "used_last_30_days": str(used),
            "stores": [{"store_id": b.store_id, "store_code": stores[b.store_id].code, "qty": str(b.qty), "avg_rate": str(b.avg_rate),
                        "value": str(b.value)} for b in bals],
            "recent": [{"id": e.id, "txn_date": e.txn_date.isoformat(), "store_code": stores[e.store_id].code, "movement_type": e.movement_type,
                        "qty_in": str(e.qty_in), "qty_out": str(e.qty_out), "running_qty": str(e.running_qty)} for e in recent]}
