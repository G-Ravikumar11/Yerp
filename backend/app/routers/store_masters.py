"""Store module - masters routes under /api/store/masters. Owned by P1.

Stores, bins, who works where, per-item stock settings, unit conversions and the freeze switch.
Rights: view = read; create = add and edit; approve = assignments and freeze/unfreeze; cancel = switch off.
"""
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreUomConversion,
    DBStoreUserAssignment, ItemCategory, StoreType,
)
from app.services.stock_ledger import assert_store_access, freeze_store, unfreeze_store

router = APIRouter(prefix="/api/store/masters", tags=["store-masters"])

D = Decimal
_STORE_TYPES = {t.value for t in StoreType}
_CATEGORIES = {c.value for c in ItemCategory}


def accessible_store_ids(actor, db) -> Optional[set]:
    """The ids of the stores this person may work in; None means every store of the company."""
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(
        DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def _dec(v, what):
    try:
        out = D(str(v))
    except (InvalidOperation, ValueError):
        raise HTTPException(400, "%s is not a number." % what) from None
    if out < 0:
        raise HTTPException(400, "%s cannot be negative." % what)
    return out


def _store(db, actor, store_id) -> DBStore:
    assert_store_access(actor.user, store_id)
    return db.get(DBStore, store_id)


def _clean(v: str, what: str) -> str:
    v = (v or "").strip()
    if not v:
        raise HTTPException(400, "%s is required." % what)
    return v


def _store_row(s, frozen=False, items=0):
    return {"id": s.id, "code": s.code, "name": s.name, "type": s.type, "project_id": s.project_id, "address": s.address or "",
            "is_active": bool(s.is_active), "frozen": frozen, "stock_lines": items}


def _check_project(db, actor, project_id):
    if project_id and not db.query(models.DBJob.id).filter(models.DBJob.id == project_id, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(404, "Project not found")


# ---------------------------------------------------------------------------------------------------- schemas
class StoreIn(BaseModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=120)
    type: str = StoreType.CENTRAL.value
    project_id: Optional[int] = None
    address: str = ""


class StoreEdit(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    type: Optional[str] = None
    project_id: Optional[int] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


class BinIn(BaseModel):
    code: str = Field(max_length=30)
    description: str = ""
    is_active: bool = True


class AssignIn(BaseModel):
    employee_id: int
    role: str = "STOREKEEPER"


class ItemSettingsIn(BaseModel):
    category: str = ItemCategory.CONSUMABLE.value
    base_uom: Optional[str] = None
    reorder_level: str = "0"
    min_qty: str = "0"
    max_qty: str = "0"
    qc_required: bool = False
    over_receipt_tolerance_pct: str = "0"
    is_batch_tracked: bool = False


class UomIn(BaseModel):
    from_uom: str = Field(max_length=20)
    to_base_factor: str


class FreezeIn(BaseModel):
    reason: str = ""


# ---------------------------------------------------------------------------------------------------- overview
@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door (kept as the skeleton's smoke test expects); the real overview is /summary."""
    store_actor(request, db, "store.masters.view")
    return {"slice": "masters", "items": []}


@router.get("/summary")
def summary(request: Request, db: Session = Depends(get_db)):
    """Counts for the masters home."""
    actor = store_actor(request, db, "store.masters.view")
    mine = accessible_store_ids(actor, db)
    q = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    if mine is not None:
        q = q.filter(DBStore.id.in_(mine or [0]))
    rows = q.all()
    ids = [s.id for s in rows]
    frozen = db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id.in_(ids or [0]), DBStoreFreeze.unfrozen_at.is_(None)).count()
    settled = db.query(DBStoreItemSettings.id).join(models.DBItem, models.DBItem.id == DBStoreItemSettings.item_id).filter(
        models.DBItem.client_id == actor.client.id).count()
    stock_items = db.query(models.DBItem.id).filter(models.DBItem.client_id == actor.client.id, models.DBItem.kind == "RM",
                                                    models.DBItem.is_active.is_(True)).count()
    return {"stores": len(rows), "active_stores": sum(1 for s in rows if s.is_active),
            "frozen_stores": frozen, "items_with_settings": settled, "items_without_settings": max(stock_items - settled, 0)}


# ---------------------------------------------------------------------------------------------------- stores
@router.get("/stores")
def list_stores(request: Request, include_inactive: bool = False, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    q = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    if not include_inactive:
        q = q.filter(DBStore.is_active.is_(True))
    mine = accessible_store_ids(actor, db)
    if mine is not None:
        q = q.filter(DBStore.id.in_(mine or [0]))
    rows = q.order_by(DBStore.code).all()
    ids = [s.id for s in rows] or [0]
    frozen = {r for (r,) in db.query(DBStoreFreeze.store_id).filter(DBStoreFreeze.store_id.in_(ids), DBStoreFreeze.unfrozen_at.is_(None)).all()}
    lines = dict(db.query(DBStoreStockBalance.store_id, func.count(DBStoreStockBalance.id)).filter(
        DBStoreStockBalance.store_id.in_(ids), DBStoreStockBalance.qty > 0).group_by(DBStoreStockBalance.store_id).all())
    return {"stores": [_store_row(s, s.id in frozen, lines.get(s.id, 0)) for s in rows]}


@router.post("/stores", status_code=201)
def create_store(body: StoreIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    code = _clean(body.code, "Store code").upper()
    if body.type not in _STORE_TYPES:
        raise HTTPException(400, "Store type must be one of %s." % ", ".join(sorted(_STORE_TYPES)))
    _check_project(db, actor, body.project_id)
    if db.query(DBStore.id).filter(DBStore.client_id == actor.client.id, DBStore.code == code).first():
        raise HTTPException(409, "A store with code %s already exists." % code)
    s = DBStore(client_id=actor.client.id, code=code, name=_clean(body.name, "Store name"), type=body.type,
                project_id=body.project_id, address=body.address or "", is_active=True)
    db.add(s)
    db.commit()
    return _store_row(s)


@router.put("/stores/{store_id}")
def edit_store(store_id: int, body: StoreEdit, request: Request, db: Session = Depends(get_db)):
    """The code never changes: it is printed on every document number."""
    actor = store_actor(request, db, "store.masters.create")
    s = _store(db, actor, store_id)
    data = body.model_dump(exclude_unset=True)
    if "is_active" in data and data["is_active"] is False:
        store_actor(request, db, "store.masters.cancel")
        if db.query(DBStoreStockBalance.id).filter(DBStoreStockBalance.store_id == s.id, DBStoreStockBalance.qty > 0).first():
            raise HTTPException(409, "Store %s still holds stock; move it out before switching the store off." % s.code)
    if "name" in data:
        s.name = _clean(data["name"], "Store name")
    if "type" in data:
        if data["type"] not in _STORE_TYPES:
            raise HTTPException(400, "Store type must be one of %s." % ", ".join(sorted(_STORE_TYPES)))
        s.type = data["type"]
    if "project_id" in data:
        _check_project(db, actor, data["project_id"])
        s.project_id = data["project_id"]
    if "address" in data:
        s.address = data["address"] or ""
    if "is_active" in data:
        s.is_active = bool(data["is_active"])
    db.commit()
    return _store_row(s)


# ---------------------------------------------------------------------------------------------------- bins
@router.get("/stores/{store_id}/bins")
def list_bins(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    _store(db, actor, store_id)
    rows = db.query(DBStoreBin).filter(DBStoreBin.store_id == store_id).order_by(DBStoreBin.code).all()
    return {"bins": [{"id": b.id, "code": b.code, "description": b.description or "", "is_active": bool(b.is_active)} for b in rows]}


@router.post("/stores/{store_id}/bins", status_code=201)
def create_bin(store_id: int, body: BinIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    _store(db, actor, store_id)
    code = _clean(body.code, "Bin code").upper()
    if db.query(DBStoreBin.id).filter(DBStoreBin.store_id == store_id, DBStoreBin.code == code).first():
        raise HTTPException(409, "Bin %s already exists in this store." % code)
    b = DBStoreBin(store_id=store_id, code=code, description=body.description or "", is_active=body.is_active)
    db.add(b)
    db.commit()
    return {"id": b.id, "code": b.code, "description": b.description, "is_active": bool(b.is_active)}


@router.put("/bins/{bin_id}")
def edit_bin(bin_id: int, body: BinIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    b = db.get(DBStoreBin, bin_id)
    if b is None:
        raise HTTPException(404, "Bin not found")
    _store(db, actor, b.store_id)
    if not body.is_active and b.is_active:
        store_actor(request, db, "store.masters.cancel")
    b.description, b.is_active = body.description or "", body.is_active
    db.commit()
    return {"id": b.id, "code": b.code, "description": b.description, "is_active": bool(b.is_active)}


# ---------------------------------------------------------------------------------------------------- who works where
@router.get("/employees")
def list_employees(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Staff who can be assigned to a store."""
    actor = store_actor(request, db, "store.masters.view")
    query = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == actor.client.id)
    term = (q or "").strip().replace("%", "")
    if term:
        like = "%" + term + "%"
        query = query.filter(func.lower(models.DBEmployee.first_name + " " + models.DBEmployee.last_name).like(like.lower()))
    rows = query.order_by(models.DBEmployee.first_name).limit(50).all()
    return {"employees": [{"id": e.id, "name": ("%s %s" % (e.first_name, e.last_name)).strip(), "job_title": e.job_title or ""} for e in rows]}


def _assign_row(a, emp):
    return {"id": a.id, "employee_id": a.employee_id, "name": ("%s %s" % (emp.first_name, emp.last_name)).strip() if emp else "",
            "role": a.role or "", "is_active": bool(a.is_active)}


@router.get("/stores/{store_id}/assignments")
def list_assignments(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    _store(db, actor, store_id)
    rows = db.query(DBStoreUserAssignment, models.DBEmployee).join(models.DBEmployee, models.DBEmployee.id == DBStoreUserAssignment.employee_id).filter(
        DBStoreUserAssignment.store_id == store_id).order_by(models.DBEmployee.first_name).all()
    return {"assignments": [_assign_row(a, e) for a, e in rows]}


@router.post("/stores/{store_id}/assignments", status_code=201)
def assign(store_id: int, body: AssignIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.approve")
    _store(db, actor, store_id)
    emp = db.get(models.DBEmployee, body.employee_id)
    if emp is None or emp.client_id != actor.client.id:
        raise HTTPException(404, "Employee not found")
    a = db.query(DBStoreUserAssignment).filter(DBStoreUserAssignment.store_id == store_id, DBStoreUserAssignment.employee_id == emp.id).first()
    if a is None:
        a = DBStoreUserAssignment(store_id=store_id, employee_id=emp.id)
        db.add(a)
    a.role, a.is_active = (body.role or "STOREKEEPER").strip(), True
    db.commit()
    return _assign_row(a, emp)


@router.delete("/assignments/{assignment_id}")
def unassign(assignment_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.approve")
    a = db.get(DBStoreUserAssignment, assignment_id)
    if a is None:
        raise HTTPException(404, "Assignment not found")
    _store(db, actor, a.store_id)
    a.is_active = False
    db.commit()
    return {"id": a.id, "is_active": False}


# ---------------------------------------------------------------------------------------------------- freeze
@router.get("/stores/{store_id}/freezes")
def freezes(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    _store(db, actor, store_id)
    rows = db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id == store_id).order_by(DBStoreFreeze.id.desc()).limit(50).all()
    return {"freezes": [{"id": f.id, "reason": f.reason, "frozen_at": f.frozen_at.isoformat() if f.frozen_at else None,
                         "unfrozen_at": f.unfrozen_at.isoformat() if f.unfrozen_at else None} for f in rows]}


@router.post("/stores/{store_id}/freeze")
def freeze(store_id: int, body: FreezeIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.approve")
    _store(db, actor, store_id)
    try:
        with store_errors():
            freeze_store(db, store_id, body.reason, actor.user_id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return {"store_id": store_id, "frozen": True}


@router.post("/stores/{store_id}/unfreeze")
def unfreeze(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.approve")
    _store(db, actor, store_id)
    try:
        with store_errors():
            unfreeze_store(db, store_id, actor.user_id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return {"store_id": store_id, "frozen": False}


# ---------------------------------------------------------------------------------------------------- item settings
def _item(db, actor, item_id):
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id:
        raise HTTPException(404, "Item not found")
    return item


def _settings_row(item, st, convs):
    return {"item_id": item.id, "code": item.item_code, "name": item.item_name, "item_unit": item.units_of_measure or "",
            "configured": st is not None, "category": st.category if st else ItemCategory.CONSUMABLE.value,
            "base_uom": st.base_uom if st else (item.units_of_measure or ""),
            "reorder_level": str(st.reorder_level or 0) if st else "0", "min_qty": str(st.min_qty or 0) if st else "0",
            "max_qty": str(st.max_qty or 0) if st else "0", "qc_required": bool(st.qc_required) if st else False,
            "over_receipt_tolerance_pct": str(st.over_receipt_tolerance_pct or 0) if st else "0",
            "is_batch_tracked": bool(st.is_batch_tracked) if st else False,
            "conversions": [{"id": c.id, "from_uom": c.from_uom, "to_base_factor": str(c.to_base_factor)} for c in convs]}


@router.get("/items")
def list_items(request: Request, q: str = "", configured: Optional[bool] = None, limit: int = 100, db: Session = Depends(get_db)):
    """Stock items with their store settings (or the gaps where none are set yet)."""
    actor = store_actor(request, db, "store.masters.view")
    query = db.query(models.DBItem).filter(models.DBItem.client_id == actor.client.id, models.DBItem.kind == "RM",
                                           models.DBItem.is_active.is_(True))
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        like = "%" + term + "%"
        query = query.filter(models.DBItem.item_code.ilike(like) | models.DBItem.item_name.ilike(like))
    rows = query.order_by(models.DBItem.item_name).all()
    ids = [r.id for r in rows] or [0]
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(ids)).all()}
    convs: dict = {}
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id.in_(ids)).order_by(DBStoreUomConversion.id).all():
        convs.setdefault(c.item_id, []).append(c)
    out = [_settings_row(r, sets.get(r.id), convs.get(r.id, [])) for r in rows if configured is None or (r.id in sets) == configured]
    return {"items": out[:max(1, min(limit, 500))], "total": len(out)}


@router.put("/items/{item_id}/settings")
def save_item_settings(item_id: int, body: ItemSettingsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    item = _item(db, actor, item_id)
    if body.category not in _CATEGORIES:
        raise HTTPException(400, "Category must be one of %s." % ", ".join(sorted(_CATEGORIES)))
    st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    base = (body.base_uom or (st.base_uom if st else None) or item.units_of_measure or "").strip()
    if not base:
        raise HTTPException(400, "A base unit is required.")
    held = db.query(DBStoreStockBalance.id).filter(DBStoreStockBalance.item_id == item_id).first() is not None
    if st is not None and held and base != st.base_uom:
        raise HTTPException(409, "Stock of this item already exists in %s; its base unit cannot change." % st.base_uom)
    reorder, mn, mx = _dec(body.reorder_level, "Reorder level"), _dec(body.min_qty, "Minimum"), _dec(body.max_qty, "Maximum")
    tol = _dec(body.over_receipt_tolerance_pct, "Over-receipt tolerance")
    if mx and mn > mx:
        raise HTTPException(400, "Minimum cannot exceed maximum.")
    if tol > 100:
        raise HTTPException(400, "Tolerance cannot exceed 100%.")
    if st is None:
        st = DBStoreItemSettings(item_id=item_id)
        db.add(st)
    st.category, st.base_uom, st.reorder_level, st.min_qty, st.max_qty = body.category, base, reorder, mn, mx
    st.qc_required, st.over_receipt_tolerance_pct, st.is_batch_tracked = body.qc_required, tol, body.is_batch_tracked
    db.commit()
    convs = db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item_id).order_by(DBStoreUomConversion.id).all()
    return _settings_row(item, st, convs)


@router.post("/items/{item_id}/uoms", status_code=201)
def add_conversion(item_id: int, body: UomIn, request: Request, db: Session = Depends(get_db)):
    """1 `from_uom` = `to_base_factor` of the base unit. Adding the same unit again replaces its factor."""
    actor = store_actor(request, db, "store.masters.create")
    item = _item(db, actor, item_id)
    st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item_id).first()
    base = st.base_uom if st else (item.units_of_measure or "")
    unit = _clean(body.from_uom, "Unit")
    factor = _dec(body.to_base_factor, "Factor")
    if factor <= 0:
        raise HTTPException(400, "The factor must be more than zero.")
    if unit.lower() == base.lower():
        raise HTTPException(400, "%s is the base unit; it needs no conversion." % base)
    c = next((x for x in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item_id).all() if x.from_uom.lower() == unit.lower()), None)
    if c is None:
        c = DBStoreUomConversion(item_id=item_id, from_uom=unit)
        db.add(c)
    c.to_base_factor = factor
    db.commit()
    return {"id": c.id, "from_uom": c.from_uom, "to_base_factor": str(c.to_base_factor)}


@router.delete("/uoms/{conversion_id}")
def remove_conversion(conversion_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.cancel")
    c = db.get(DBStoreUomConversion, conversion_id)
    if c is None:
        raise HTTPException(404, "Conversion not found")
    _item(db, actor, c.item_id)
    db.delete(c)
    db.commit()
    return {"id": conversion_id, "deleted": True}
