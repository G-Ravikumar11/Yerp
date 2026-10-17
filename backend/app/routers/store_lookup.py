"""Store module - the lists every slice's pickers draw on (stores, items, units) and the module's fixed vocabularies.
Shared and finished: a slice uses these, it does not extend them. Under /api/store/lookup."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.permissions import STORE_ACTIONS, STORE_SLICES
from app.core.store_auth import store_actor
from app.db import get_db
from app.models.store_core import (
    CostHead, DBStore, DBStoreItemSettings, DBStoreUomConversion, DBStoreUserAssignment, DocStatus, ItemCategory,
    MovementType, StoreType,
)

router = APIRouter(prefix="/api/store/lookup", tags=["store-lookup"])

ANY_VIEW = tuple(f"store.{sl}.view" for sl in STORE_SLICES)


def _uoms(db, item, settings):
    base = (settings.base_uom if settings else item.units_of_measure) or ""
    out = [{"code": base, "to_base_factor": 1.0}]
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).order_by(DBStoreUomConversion.id).all():
        out.append({"code": c.from_uom, "to_base_factor": float(c.to_base_factor)})
    return base, out


@router.get("/meta")
def meta(request: Request, db: Session = Depends(get_db)):
    store_actor(request, db, ANY_VIEW)
    return {"movement_types": [m.value for m in MovementType], "doc_statuses": [d.value for d in DocStatus],
            "cost_heads": [c.value for c in CostHead], "store_types": [t.value for t in StoreType],
            "item_categories": [c.value for c in ItemCategory], "slices": list(STORE_SLICES), "actions": list(STORE_ACTIONS)}


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
    out = []
    for r in rows:
        base, uoms = _uoms(db, r, settings.get(r.id))
        out.append({"id": r.id, "code": r.item_code, "name": r.item_name, "base_uom": base, "uoms": uoms,
                    "category": settings[r.id].category if r.id in settings else None})
    return {"items": out}


@router.get("/items/{item_id}/uoms")
def item_uoms(item_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, ANY_VIEW)
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id:
        raise HTTPException(404, "Item not found")
    base, uoms = _uoms(db, item, db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first())
    return {"item_id": item_id, "base_uom": base, "uoms": uoms}
