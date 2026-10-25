"""Store module - the lists every slice's pickers draw on (stores, items, units) and the module's fixed vocabularies.
Shared and finished: a slice uses these, it does not extend them. Under /api/store/lookup."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.permissions import STORE_ACTIONS, STORE_SLICES
from app.core.store_auth import store_actor
from app.db import get_db
from app.services.store_codes import resolve, scanning_on
from app.models.store_core import (
    CostHead, DBStore, DBStoreItemSettings, DBStoreUomConversion, DBStoreUserAssignment, DocStatus, ItemCategory,
    MovementType, StoreType,
)

router = APIRouter(prefix="/api/store/lookup", tags=["store-lookup"])

ANY_VIEW = tuple(f"store.{sl}.view" for sl in STORE_SLICES)


def _uoms(db, item, settings, conversions=None):
    """The item's base unit and the units it converts from. `conversions` is what a list read for all its items at once."""
    base = (settings.base_uom if settings else item.units_of_measure) or ""
    out = [{"code": base, "to_base_factor": 1.0}]
    if conversions is None:
        conversions = db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).order_by(DBStoreUomConversion.id).all()
    for c in conversions:
        out.append({"code": c.from_uom, "to_base_factor": float(c.to_base_factor)})
    return base, out


@router.get("/meta")
def meta(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, ANY_VIEW)
    return {"movement_types": [m.value for m in MovementType], "doc_statuses": [d.value for d in DocStatus],
            "cost_heads": [c.value for c in CostHead], "store_types": [t.value for t in StoreType],
            "item_categories": [c.value for c in ItemCategory], "slices": list(STORE_SLICES), "actions": list(STORE_ACTIONS),
            "scanning": scanning_on(db, actor.client.id)}


@router.get("/stores")
def stores(request: Request, project_id: int = 0, db: Session = Depends(get_db)):
    """The stores this person may work in: every store of the company for the account holder and store.admin, else their assignments."""
    actor = store_actor(request, db, ANY_VIEW)
    q = db.query(DBStore).filter(DBStore.client_id == actor.client.id, DBStore.is_active.is_(True))
    if project_id:
        q = q.filter(DBStore.project_id == project_id)
    rows = q.order_by(DBStore.code).all()
    if actor.employee is not None:
        from app.core.permissions import permissions_for
        if "store.admin" not in permissions_for(actor.employee):
            mine = {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(
                DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}
            rows = [s for s in rows if s.id in mine]
    return {"stores": [{"id": s.id, "code": s.code, "name": s.name, "type": s.type, "project_id": s.project_id} for s in rows]}


@router.get("/items")
def items(request: Request, q: str = "", limit: int = 30, db: Session = Depends(get_db)):
    """Stock items of the company, found by code or name."""
    actor = store_actor(request, db, ANY_VIEW)
    query = db.query(models.DBItem).filter(models.DBItem.client_id == actor.client.id, models.DBItem.kind == "RM",
                                           models.DBItem.is_active.is_(True))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBItem.item_code.ilike(like), models.DBItem.item_name.ilike(like)))
    rows = query.order_by(models.DBItem.item_name).limit(max(1, min(limit, 100))).all()
    settings = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_([r.id for r in rows])).all()} if rows else {}
    # Every item's conversions in one query: the picker asks on each key pressed.
    convs = {r.id: [] for r in rows}
    for c in (db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id.in_(list(convs))).order_by(DBStoreUomConversion.id).all() if rows else []):
        convs[c.item_id].append(c)
    return {"items": [_option(db, r, settings.get(r.id), convs[r.id]) for r in rows]}


def _option(db, item, s, conversions=None):
    """An item as the pickers hold it."""
    base, uoms = _uoms(db, item, s, conversions)
    return {"id": item.id, "code": item.item_code, "name": item.item_name, "base_uom": base, "uoms": uoms,
            "category": s.category if s else None, "batch_tracked": bool(s.is_batch_tracked) if s else False}


@router.get("/scan")
def scan(request: Request, code: str = "", db: Session = Depends(get_db)):
    """What a scanned or typed code is: an item (its code, or the maker's barcode on it), a rack or yard-bay tag, or a store
    document (a gate pass at the gate, an issue, a goods receipt)."""
    actor = store_actor(request, db, ANY_VIEW)
    mine = None
    if actor.employee is not None:
        from app.core.permissions import permissions_for
        if "store.admin" not in permissions_for(actor.employee):
            mine = {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(
                DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}
    found = resolve(db, actor.client.id, code, lambda store_id: mine is None or store_id in mine)
    if found["kind"] == "item":
        item = db.get(models.DBItem, found.pop("item_id"))
        found["item"] = _option(db, item, db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first())
    return found


@router.get("/items/{item_id}/uoms")
def item_uoms(item_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, ANY_VIEW)
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id:
        raise HTTPException(404, "Item not found")
    base, uoms = _uoms(db, item, db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first())
    return {"item_id": item_id, "base_uom": base, "uoms": uoms}
