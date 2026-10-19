"""Store module - masters under /api/store/masters: the stores, their bins, who works in which store, each item's stock
settings and its unit conversions. Owned by P1.

Rights: store.masters.view to read, store.masters.create to add or change anything, store.masters.approve to take a store
out of use or bring it back. A store a member of staff is not assigned to is not theirs to see (assert_store_access).
Nothing here moves stock: the ledger is only ever written through app/services/stock_ledger.py.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor
from app.db import get_db
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreDocSequence, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DBStoreStockLedger,
    DBStoreUomConversion, DBStoreUserAssignment, ItemCategory, StoreType,
)
from app.services.stock_ledger import assert_store_access
from app.services.store_codes import bin_tag, check_barcode, labels_pdf

router = APIRouter(prefix="/api/store/masters", tags=["store-masters"])

ZERO = Decimal("0")
STORE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,11}$")      # it is printed in every document number, so no "/" and no spaces
MAX_FACTOR = Decimal("1000000000")
MAX_QTY = Decimal("999999999999")


# --- shared with the enquiry slice --------------------------------------------------------------------------------

def num(x, places="0.001") -> str:
    """A Decimal (or None) as the plain string the API sends."""
    d = Decimal(str(x if x is not None else 0))
    return format(d.quantize(Decimal(places)), "f")


def visible_store_ids(db, actor) -> Optional[set]:
    """The stores this person may see: None for 'all of the company' (the account holder, store.admin), else their assignments."""
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(
        DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def my_store(db, actor, store_id) -> DBStore:
    """A store of this company the person may work in; 404 for anybody else's, 403 for one they are not assigned to."""
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != actor.client.id:
        raise HTTPException(404, "Store not found")
    assert_store_access(actor.user, store.id)
    return store


def _who(actor, request):
    return dict(request=request, user_type="employee" if actor.employee is not None else "client", user_name=actor.name)


def _clean(text, what, limit, required=True):
    out = " ".join((text or "").split())
    if required and not out:
        raise HTTPException(400, "Give the %s." % what)
    if len(out) > limit:
        raise HTTPException(400, "Keep the %s to %d characters." % (what, limit))
    return out


def _decimal(value, what, *, high=MAX_QTY, minimum=ZERO, allow_zero=True):
    try:
        d = Decimal(str(value if value is not None else 0).strip() or "0")
    except InvalidOperation:
        raise HTTPException(400, "%s is not a number." % what) from None
    if not d.is_finite():
        raise HTTPException(400, "%s is not a number." % what)
    if d < minimum or (d == minimum and not allow_zero) or d > high:
        raise HTTPException(400, "%s must be %s%s." % (what, "more than " if not allow_zero else "", str(minimum) if not allow_zero else "between %s and %s" % (minimum, high)))
    return d


# --- stores ---------------------------------------------------------------------------------------------------------

class StoreIn(BaseModel):
    code: str
    name: str
    type: str = StoreType.CENTRAL.value
    project_id: Optional[int] = None
    address: str = ""


def _check_store_fields(db, client_id, body):
    name = _clean(body.name, "store name", 100)
    kind = (body.type or "").strip().upper()
    if kind not in {t.value for t in StoreType}:
        raise HTTPException(400, "Type must be one of: %s." % ", ".join(t.value for t in StoreType))
    project = None
    if body.project_id:
        project = db.query(models.DBJob).filter(models.DBJob.id == body.project_id, models.DBJob.client_id == client_id).first()
        if project is None:
            raise HTTPException(400, "That project does not exist.")
    return name, kind, project, _clean(body.address, "address", 300, required=False)


def _store_row(s, extra):
    return {"id": s.id, "code": s.code, "name": s.name, "type": s.type, "project_id": s.project_id, "address": s.address or "",
            "is_active": bool(s.is_active), **extra}


def _store_rows(db, stores):
    ids = [s.id for s in stores]
    if not ids:
        return []
    bins = dict(db.query(DBStoreBin.store_id, func.count(DBStoreBin.id)).filter(DBStoreBin.store_id.in_(ids)).group_by(DBStoreBin.store_id).all())
    staff = dict(db.query(DBStoreUserAssignment.store_id, func.count(DBStoreUserAssignment.id)).filter(
        DBStoreUserAssignment.store_id.in_(ids), DBStoreUserAssignment.is_active.is_(True)).group_by(DBStoreUserAssignment.store_id).all())
    held = {sid: (n, v) for sid, n, v in db.query(DBStoreStockBalance.store_id, func.count(DBStoreStockBalance.id), func.sum(DBStoreStockBalance.value)).filter(
        DBStoreStockBalance.store_id.in_(ids), DBStoreStockBalance.qty > 0).group_by(DBStoreStockBalance.store_id).all()}
    frozen = {f.store_id: f.reason for f in db.query(DBStoreFreeze).filter(DBStoreFreeze.store_id.in_(ids), DBStoreFreeze.unfrozen_at.is_(None)).all()}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.id.in_([s.project_id for s in stores if s.project_id])).all()} if any(s.project_id for s in stores) else {}
    out = []
    for s in stores:
        n, v = held.get(s.id, (0, ZERO))
        job = jobs.get(s.project_id)
        out.append(_store_row(s, {"project_name": ("%s - %s" % (job.number, job.name)) if job else "", "bins": bins.get(s.id, 0),
                                  "staff": staff.get(s.id, 0), "items_held": n, "stock_value": num(v or ZERO, "0.01"),
                                  "frozen": s.id in frozen, "frozen_reason": frozen.get(s.id, "")}))
    return out


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: the stores this person may see."""
    return {"slice": "masters", **list_stores(request, db=db)}


@router.get("/stores")
def list_stores(request: Request, q: str = "", type: str = "", project_id: int = 0, status: str = "all", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    query = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    seen = visible_store_ids(db, actor)
    if seen is not None:
        query = query.filter(DBStore.id.in_(seen or {0}))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(DBStore.code.ilike(like), DBStore.name.ilike(like)))
    if type:
        query = query.filter(DBStore.type == type.strip().upper())
    if project_id:
        query = query.filter(DBStore.project_id == project_id)
    if status == "active":
        query = query.filter(DBStore.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(DBStore.is_active.is_(False))
    return {"items": _store_rows(db, query.order_by(DBStore.code).all())}


@router.get("/stores/{store_id}")
def get_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    return _store_rows(db, [my_store(db, actor, store_id)])[0]


@router.post("/stores")
def add_store(body: StoreIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    code = (body.code or "").strip().upper()
    if not STORE_CODE.match(code):
        raise HTTPException(400, "The store code is 2 to 12 capital letters or numbers (with - or _), like CS01. It is printed in every document number.")
    name, kind, _project, address = _check_store_fields(db, actor.client.id, body)
    if db.query(DBStore.id).filter(DBStore.client_id == actor.client.id, DBStore.code == code).first():
        raise HTTPException(409, "There is already a store with the code %s." % code)
    store = DBStore(client_id=actor.client.id, code=code, name=name, type=kind, project_id=body.project_id or None, address=address, is_active=True)
    db.add(store)
    db.flush()
    log_audit(db, actor.client.id, "store_added", "store", store.id, store.code, "%s %s" % (kind, name), **_who(actor, request))
    db.commit()
    return _store_rows(db, [store])[0]


@router.put("/stores/{store_id}")
def edit_store(store_id: int, body: StoreIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    store = my_store(db, actor, store_id)
    code = (body.code or "").strip().upper()
    name, kind, _project, address = _check_store_fields(db, actor.client.id, body)
    if code != store.code:
        if not STORE_CODE.match(code):
            raise HTTPException(400, "The store code is 2 to 12 capital letters or numbers (with - or _), like CS01.")
        used = db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.store_id == store.id).first() or \
            db.query(DBStoreDocSequence.id).filter(DBStoreDocSequence.store_id == store.id).first()
        if used:
            raise HTTPException(409, "%s already appears on stock entries and document numbers, so its code cannot change. Change the name instead." % store.code)
        if db.query(DBStore.id).filter(DBStore.client_id == actor.client.id, DBStore.code == code).first():
            raise HTTPException(409, "There is already a store with the code %s." % code)
    before = "%s %s %s project=%s" % (store.code, store.type, store.name, store.project_id)
    store.code, store.name, store.type, store.project_id, store.address = code, name, kind, body.project_id or None, address
    log_audit(db, actor.client.id, "store_edited", "store", store.id, store.code, "%s -> %s %s %s project=%s" % (before, code, kind, name, store.project_id), **_who(actor, request))
    db.commit()
    return _store_rows(db, [store])[0]


def _set_active(store_id, active, request, db):
    actor = store_actor(request, db, "store.masters.approve")
    store = my_store(db, actor, store_id)
    if bool(store.is_active) == active:
        raise HTTPException(409, "%s is already %s." % (store.code, "in use" if active else "out of use"))
    if not active:
        held = db.query(func.count(DBStoreStockBalance.id)).filter(DBStoreStockBalance.store_id == store.id, DBStoreStockBalance.qty > 0).scalar()
        if held:
            raise HTTPException(409, "%s still holds stock (%d items). Move it out or transfer it before taking the store out of use." % (store.code, held))
        if db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id == store.id, DBStoreFreeze.unfrozen_at.is_(None)).first():
            raise HTTPException(409, "%s is frozen for a stock count. Finish the count first." % store.code)
    store.is_active = active
    log_audit(db, actor.client.id, "store_activated" if active else "store_deactivated", "store", store.id, store.code, "", **_who(actor, request))
    db.commit()
    return _store_rows(db, [store])[0]


@router.post("/stores/{store_id}/deactivate")
def deactivate_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    """Take a store out of use. Refused while it holds stock; its history stays."""
    return _set_active(store_id, False, request, db)


@router.post("/stores/{store_id}/activate")
def activate_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    return _set_active(store_id, True, request, db)


# --- bins -----------------------------------------------------------------------------------------------------------

class BinIn(BaseModel):
    code: str
    description: str = ""


def _bin_dict(b):
    return {"id": b.id, "store_id": b.store_id, "code": b.code, "description": b.description or "", "is_active": bool(b.is_active)}


def _bin_fields(body):
    code = _clean(body.code, "bin code", 20).upper()
    return code, _clean(body.description, "description", 120, required=False)


@router.get("/labels.pdf")
def labels(request: Request, store_id: int, kind: str = "bins", item_ids: str = "", db: Session = Depends(get_db)):
    """Sticky QR labels to print: a tag for every rack and yard bay of a store (kind=bins), or a rack label for each item the
    store holds (kind=items; item_ids, comma-separated, for chosen ones). Scanning one in the app finds the bin or the item."""
    actor = store_actor(request, db, "store.masters.view")
    store = my_store(db, actor, store_id)
    if kind == "bins":
        rows = [(bin_tag(store, b), b.code, "%s - %s%s" % (store.code, store.name, (" - " + b.description) if b.description else ""))
                for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == store.id).order_by(DBStoreBin.code).all()]
        title = "Bin labels %s" % store.code
    elif kind == "items":
        chosen = [int(x) for x in re.findall(r"\d+", item_ids or "")]
        q = db.query(models.DBItem).filter(models.DBItem.client_id == actor.client.id, models.DBItem.kind == "RM")
        if chosen:
            q = q.filter(models.DBItem.id.in_(chosen))
        else:
            q = q.join(DBStoreStockBalance, DBStoreStockBalance.item_id == models.DBItem.id).filter(DBStoreStockBalance.store_id == store.id, DBStoreStockBalance.qty > 0)
        rows = [(i.item_code, i.item_code, "%s  (%s)" % (i.item_name, store.code)) for i in q.order_by(models.DBItem.item_name).limit(480).all()]
        title = "Item labels %s" % store.code
    else:
        raise HTTPException(400, "Labels are for bins or items.")
    return Response(content=labels_pdf(title, rows), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="%s.pdf"' % title.replace(" ", "-")})


@router.get("/stores/{store_id}/bins")
def list_bins(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    store = my_store(db, actor, store_id)
    return {"items": [_bin_dict(b) for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == store.id).order_by(DBStoreBin.code).all()]}


@router.post("/stores/{store_id}/bins")
def add_bin(store_id: int, body: BinIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    store = my_store(db, actor, store_id)
    code, description = _bin_fields(body)
    if db.query(DBStoreBin.id).filter(DBStoreBin.store_id == store.id, DBStoreBin.code == code).first():
        raise HTTPException(409, "%s already has a bin %s." % (store.code, code))
    row = DBStoreBin(store_id=store.id, code=code, description=description, is_active=True)
    db.add(row)
    db.flush()
    log_audit(db, actor.client.id, "store_bin_added", "store", store.id, store.code, code, **_who(actor, request))
    db.commit()
    return _bin_dict(row)


def _my_bin(db, actor, bin_id):
    row = db.get(DBStoreBin, bin_id)
    store = db.get(DBStore, row.store_id) if row else None
    if row is None or store is None or store.client_id != actor.client.id:
        raise HTTPException(404, "Bin not found")
    assert_store_access(actor.user, store.id)
    return row, store


@router.put("/bins/{bin_id}")
def edit_bin(bin_id: int, body: BinIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    row, store = _my_bin(db, actor, bin_id)
    code, description = _bin_fields(body)
    if code != row.code and db.query(DBStoreBin.id).filter(DBStoreBin.store_id == store.id, DBStoreBin.code == code).first():
        raise HTTPException(409, "%s already has a bin %s." % (store.code, code))
    row.code, row.description = code, description
    log_audit(db, actor.client.id, "store_bin_edited", "store", store.id, store.code, code, **_who(actor, request))
    db.commit()
    return _bin_dict(row)


@router.delete("/bins/{bin_id}")
def remove_bin(bin_id: int, request: Request, db: Session = Depends(get_db)):
    """Nothing else refers to a bin yet, so removing one loses nothing."""
    actor = store_actor(request, db, "store.masters.create")
    row, store = _my_bin(db, actor, bin_id)
    log_audit(db, actor.client.id, "store_bin_removed", "store", store.id, store.code, row.code, **_who(actor, request))
    db.delete(row)
    db.commit()
    return {"message": "Bin removed"}


# --- who works in which store ---------------------------------------------------------------------------------------

class AssignIn(BaseModel):
    employee_id: int
    role: str = "STOREKEEPER"


def _employee_name(e):
    return ("%s %s" % (e.first_name or "", e.last_name or "")).strip()


def _assign_dict(a, e):
    return {"id": a.id, "store_id": a.store_id, "employee_id": a.employee_id, "name": _employee_name(e) if e else "", "email": e.email if e else "",
            "job_title": (e.job_title or "") if e else "", "role": a.role or "", "is_active": bool(a.is_active)}


@router.get("/employees")
def employee_options(request: Request, q: str = "", limit: int = 30, db: Session = Depends(get_db)):
    """Staff who can be assigned to a store."""
    actor = store_actor(request, db, "store.masters.view")
    query = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == actor.client.id, models.DBEmployee.status.in_(["active", "onboarding"]))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBEmployee.first_name.ilike(like), models.DBEmployee.last_name.ilike(like), models.DBEmployee.email.ilike(like)))
    rows = query.order_by(models.DBEmployee.first_name).limit(max(1, min(limit, 100))).all()
    return {"items": [{"id": e.id, "name": _employee_name(e), "email": e.email, "job_title": e.job_title or ""} for e in rows]}


@router.get("/stores/{store_id}/assignments")
def list_assignments(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    store = my_store(db, actor, store_id)
    rows = db.query(DBStoreUserAssignment, models.DBEmployee).join(models.DBEmployee, models.DBEmployee.id == DBStoreUserAssignment.employee_id).filter(
        DBStoreUserAssignment.store_id == store.id).order_by(models.DBEmployee.first_name).all()
    return {"items": [_assign_dict(a, e) for a, e in rows]}


@router.post("/stores/{store_id}/assignments")
def assign(store_id: int, body: AssignIn, request: Request, db: Session = Depends(get_db)):
    """Put a member of staff in a store (or bring back one who was taken out, with the new role label)."""
    actor = store_actor(request, db, "store.masters.create")
    store = my_store(db, actor, store_id)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == body.employee_id, models.DBEmployee.client_id == actor.client.id).first()
    if emp is None:
        raise HTTPException(400, "That employee does not exist.")
    role = _clean(body.role, "role", 30).upper().replace(" ", "_")
    row = db.query(DBStoreUserAssignment).filter(DBStoreUserAssignment.store_id == store.id, DBStoreUserAssignment.employee_id == emp.id).first()
    if row is not None and row.is_active:
        raise HTTPException(409, "%s already works in %s." % (_employee_name(emp), store.code))
    if row is None:
        row = DBStoreUserAssignment(store_id=store.id, employee_id=emp.id, role=role, is_active=True)
        db.add(row)
    else:
        row.role, row.is_active = role, True
    db.flush()
    log_audit(db, actor.client.id, "store_staff_assigned", "store", store.id, store.code, "%s as %s" % (_employee_name(emp), role), **_who(actor, request))
    db.commit()
    return _assign_dict(row, emp)


@router.delete("/stores/{store_id}/assignments/{employee_id}")
def unassign(store_id: int, employee_id: int, request: Request, db: Session = Depends(get_db)):
    """Take a member of staff out of a store. The row stays, switched off, so the history of who worked there is kept."""
    actor = store_actor(request, db, "store.masters.create")
    store = my_store(db, actor, store_id)
    row = db.query(DBStoreUserAssignment).filter(DBStoreUserAssignment.store_id == store.id, DBStoreUserAssignment.employee_id == employee_id,
                                                  DBStoreUserAssignment.is_active.is_(True)).first()
    if row is None:
        raise HTTPException(404, "That person does not work in this store.")
    emp = db.get(models.DBEmployee, employee_id)
    row.is_active = False
    log_audit(db, actor.client.id, "store_staff_removed", "store", store.id, store.code, _employee_name(emp) if emp else str(employee_id), **_who(actor, request))
    db.commit()
    return {"message": "Removed from the store"}


# --- item settings and unit conversions -----------------------------------------------------------------------------

class SettingsIn(BaseModel):
    category: str = ItemCategory.CONSUMABLE.value
    base_uom: str
    reorder_level: str = "0"
    min_qty: str = "0"
    max_qty: str = "0"
    qc_required: bool = False
    over_receipt_tolerance_pct: str = "0"
    is_batch_tracked: bool = False
    barcode: Optional[str] = None        # the maker's barcode; left out keeps the one on file


class ConversionIn(BaseModel):
    to_base_factor: str


def _my_item(db, actor, item_id):
    item = db.get(models.DBItem, item_id)
    if item is None or item.client_id != actor.client.id or item.kind != "RM":
        raise HTTPException(404, "Item not found")
    return item


def _settings_dict(item, s):
    return {"item_id": item.id, "category": s.category if s else ItemCategory.CONSUMABLE.value, "base_uom": (s.base_uom if s else item.units_of_measure) or "",
            "reorder_level": num(s.reorder_level if s else 0), "min_qty": num(s.min_qty if s else 0), "max_qty": num(s.max_qty if s else 0),
            "qc_required": bool(s.qc_required) if s else False, "over_receipt_tolerance_pct": num(s.over_receipt_tolerance_pct if s else 0),
            "is_batch_tracked": bool(s.is_batch_tracked) if s else False, "barcode": (s.barcode or "") if s else ""}


def _item_dict(item, s, conversions, on_hand):
    return {"id": item.id, "code": item.item_code, "name": item.item_name, "item_uom": item.units_of_measure or "", "is_active": bool(item.is_active),
            "configured": s is not None, "settings": _settings_dict(item, s), "conversions": conversions, "on_hand": num(on_hand), }


def _conversions(db, item_ids):
    out = {i: [] for i in item_ids}
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id.in_(item_ids)).order_by(DBStoreUomConversion.id).all() if item_ids else []:
        out[c.item_id].append({"uom": c.from_uom, "to_base_factor": num(c.to_base_factor, "0.000001")})
    return out


@router.get("/items")
def list_items(request: Request, q: str = "", category: str = "", configured: str = "all", limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    """Every stock item with its store settings (or the defaults it would get) and how much is held in the stores this person may see."""
    actor = store_actor(request, db, "store.masters.view")
    query = db.query(models.DBItem, DBStoreItemSettings).outerjoin(DBStoreItemSettings, DBStoreItemSettings.item_id == models.DBItem.id).filter(
        models.DBItem.client_id == actor.client.id, models.DBItem.kind == "RM")
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        query = query.filter(or_(models.DBItem.item_code.ilike(like), models.DBItem.item_name.ilike(like)))
    if category:
        query = query.filter(DBStoreItemSettings.category == category.strip().upper())
    if configured == "yes":
        query = query.filter(DBStoreItemSettings.id.isnot(None))
    elif configured == "no":
        query = query.filter(DBStoreItemSettings.id.is_(None))
    total = query.count()
    rows = query.order_by(models.DBItem.item_name).offset(max(0, offset)).limit(max(1, min(limit, 500))).all()
    ids = [i.id for i, _ in rows]
    seen = visible_store_ids(db, actor)
    held = {}
    if ids:
        bq = db.query(DBStoreStockBalance.item_id, func.sum(DBStoreStockBalance.qty)).filter(DBStoreStockBalance.item_id.in_(ids))
        if seen is not None:
            bq = bq.filter(DBStoreStockBalance.store_id.in_(seen or {0}))
        held = dict(bq.group_by(DBStoreStockBalance.item_id).all())
    conv = _conversions(db, ids)
    return {"total": total, "items": [_item_dict(i, s, conv[i.id], held.get(i.id, ZERO)) for i, s in rows]}


@router.get("/items/{item_id}")
def get_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.view")
    item = _my_item(db, actor, item_id)
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    return _item_dict(item, s, _conversions(db, [item.id])[item.id], ZERO)


def _has_movements(db, item_id) -> bool:
    return db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.item_id == item_id).first() is not None


@router.put("/items/{item_id}/settings")
def save_settings(item_id: int, body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    item = _my_item(db, actor, item_id)
    category = (body.category or "").strip().upper()
    if category not in {c.value for c in ItemCategory}:
        raise HTTPException(400, "Category must be one of: %s." % ", ".join(c.value for c in ItemCategory))
    base = _clean(body.base_uom, "base unit", 20)
    reorder = _decimal(body.reorder_level, "Reorder level")
    low = _decimal(body.min_qty, "Minimum quantity")
    high = _decimal(body.max_qty, "Maximum quantity")
    tolerance = _decimal(body.over_receipt_tolerance_pct, "Over-receipt tolerance", high=Decimal("100"))
    if high and low > high:
        raise HTTPException(400, "The minimum cannot be more than the maximum.")
    row = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    current = ((row.base_uom if row else item.units_of_measure) or "").strip()
    if base.lower() != current.lower() and _has_movements(db, item.id):
        raise HTTPException(409, "Stock of this item is already counted in %s, so the base unit cannot change." % current)
    if row is None:
        row = DBStoreItemSettings(item_id=item.id, base_uom=base)
        db.add(row)
    row.category, row.base_uom, row.reorder_level, row.min_qty, row.max_qty = category, base, reorder, low, high
    row.qc_required, row.over_receipt_tolerance_pct, row.is_batch_tracked = body.qc_required, tolerance, body.is_batch_tracked
    if body.barcode is not None:
        code = _clean(body.barcode, "barcode", 64, required=False) if body.barcode.strip() else ""
        check_barcode(db, actor.client.id, item.id, code)
        row.barcode = code
    # A conversion from the unit that has become the base is meaningless; drop it rather than leave a loop behind.
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).all():
        if c.from_uom.strip().lower() == base.lower():
            db.delete(c)
    db.flush()
    log_audit(db, actor.client.id, "store_item_settings", "item", item.id, item.item_code, "%s base %s reorder %s min %s max %s" % (category, base, reorder, low, high), **_who(actor, request))
    db.commit()
    return _item_dict(item, row, _conversions(db, [item.id])[item.id], ZERO)


@router.put("/items/{item_id}/conversions/{uom}")
def save_conversion(item_id: int, uom: str, body: ConversionIn, request: Request, db: Session = Depends(get_db)):
    """1 `uom` of the item = `to_base_factor` of its base unit (1 bag = 50 kg). Adds it, or changes it. Documents already
    posted were stored in the base unit, so changing a factor only affects what is entered from now on."""
    actor = store_actor(request, db, "store.masters.create")
    item = _my_item(db, actor, item_id)
    code = _clean(uom, "unit", 20)
    settings = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    base = ((settings.base_uom if settings else item.units_of_measure) or "").strip()
    if code.lower() == base.lower():
        raise HTTPException(400, "%s is the base unit of this item; it needs no conversion." % base)
    factor = _decimal(body.to_base_factor, "The factor", high=MAX_FACTOR, allow_zero=False)
    factor = factor.quantize(Decimal("0.000001"))
    if factor <= 0:
        raise HTTPException(400, "The factor is too small: it must be at least 0.000001.")
    row = next((c for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).all() if c.from_uom.strip().lower() == code.lower()), None)
    if row is None:
        row = DBStoreUomConversion(item_id=item.id, from_uom=code, to_base_factor=factor)
        db.add(row)
    else:
        row.to_base_factor = factor
    db.flush()
    log_audit(db, actor.client.id, "store_uom_conversion", "item", item.id, item.item_code, "1 %s = %s %s" % (code, factor, base), **_who(actor, request))
    db.commit()
    return {"uom": row.from_uom, "to_base_factor": num(row.to_base_factor, "0.000001"), "base_uom": base}


@router.delete("/items/{item_id}/conversions/{uom}")
def remove_conversion(item_id: int, uom: str, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.masters.create")
    item = _my_item(db, actor, item_id)
    row = next((c for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).all() if c.from_uom.strip().lower() == uom.strip().lower()), None)
    if row is None:
        raise HTTPException(404, "No conversion from %s is set for this item." % uom)
    log_audit(db, actor.client.id, "store_uom_conversion_removed", "item", item.id, item.item_code, row.from_uom, **_who(actor, request))
    db.delete(row)
    db.commit()
    return {"message": "Conversion removed"}
