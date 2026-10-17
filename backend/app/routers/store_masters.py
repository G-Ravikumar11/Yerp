"""Store module - masters routes under /api/store/masters. Owned by P1.

Stores (central, site, yard - a site store belongs to a project), their bins, who works in each (the assignments
assert_store_access reads), what the store needs to know about each item (category, base unit, levels), the units an
item can be counted in, and opening stock - typed or imported from a sheet - posted as OPENING_IN.

Rights: store.masters.view to look, store.masters.create to set things up and to raise an opening, and
store.masters.approve / .post / .cancel for the opening's later steps. Anything about one store also needs access to
that store. Quantities and money travel as strings.
"""
import csv
import io
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app import models
from app.core.store_auth import store_actor, store_errors
from app.db import get_db
from app.models.store_core import (
    DBStore, DBStoreBin, DBStoreDocSequence, DBStoreDocStatusLog, DBStoreFreeze, DBStoreItemSettings, DBStoreOpening,
    DBStoreOpeningLine, DBStoreStockBalance, DBStoreStockLedger, DBStoreUomConversion, DBStoreUserAssignment, DocStatus,
    InvalidMovementError, ItemCategory, MovementType, OpeningSource, StoreError, StoreType,
)
from app.services.stock_ledger import assert_store_access, convert_to_base, post_movement, reverse_document
from app.services.store_numbering import next_doc_number

router = APIRouter(prefix="/api/store/masters", tags=["store-masters"])

VIEW, CREATE = "store.masters.view", "store.masters.create"
APPROVE, POST, CANCEL = "store.masters.approve", "store.masters.post", "store.masters.cancel"
OPENING_DOC = "OPENING_STOCK"          # the ref_doc_type of an opening's movements
OPENING_NUMBER = "OPEN"                # OPEN/CS01/26-27/00001
ROLES = ("STOREKEEPER", "SITE_ENGINEER", "STORE_INCHARGE", "APPROVER", "VIEWER")
MAX_IMPORT_ROWS = 5000

D = Decimal
_QTY, _RATE, _VALUE, _FACTOR = D("0.001"), D("0.0001"), D("0.01"), D("0.000001")


# --- small helpers shared with the enquiry routes ------------------------------------------------------------------

def dec(x, what="Number") -> Decimal:
    """A Decimal from what a screen or a sheet sent, or a 400 naming the field."""
    if isinstance(x, Decimal):
        out = x
    else:
        s = str(x if x is not None else "").strip().replace(",", "")
        if not s:
            raise HTTPException(400, "%s is missing." % what)
        try:
            out = D(s)
        except InvalidOperation:
            raise HTTPException(400, "%s is not a number: %r" % (what, x)) from None
    if not out.is_finite():
        raise HTTPException(400, "%s is not a number: %r" % (what, x))
    return out


def q(x, step) -> Decimal:
    return D(x).quantize(step, rounding=ROUND_HALF_UP)


def s(x, step=None) -> str:
    """A Decimal as the string the API sends: 12.500, never 12.5 or 1.25E+1."""
    if x is None:
        return None
    x = D(x)
    return format(q(x, step) if step is not None else x, "f")


def person(actor) -> str:
    return actor.name


def project_names(db, client_id) -> dict:
    return {j.id: ("%s %s" % (j.number or "", j.name or "")).strip() for j in db.query(
        models.DBJob.id, models.DBJob.number, models.DBJob.name).filter(models.DBJob.client_id == client_id).all()}


def accessible_store_ids(db, actor) -> Optional[set]:
    """The stores this person may work in, or None for every store of the company (the account holder, store.admin)."""
    if actor.employee is None:
        return None
    from app.core.permissions import permissions_for
    if "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(
        DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def company_store(db, actor, store_id, *, access=True) -> DBStore:
    """The store, of this company, that this person may work in (404 / 403 otherwise)."""
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != actor.client.id:
        raise HTTPException(404, "Store not found")
    if access:
        assert_store_access(actor.user, store.id)
    return store


def company_item(db, actor, item_id) -> models.DBItem:
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != actor.client.id or item.kind != "RM":
        raise HTTPException(404, "Item not found")
    return item


def base_uom_of(db, item, settings=None) -> str:
    if settings is None:
        settings = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    return ((settings.base_uom if settings else item.units_of_measure) or "").strip()


def log_status(db, client_id, doc_type, doc_id, from_status, to_status, actor, note=""):
    """One line in the document's trail: from what to what, who, when."""
    db.add(DBStoreDocStatusLog(client_id=client_id, doc_type=doc_type, doc_id=doc_id, from_status=from_status,
                               to_status=to_status, user_id=actor.user_id, user_name=person(actor), note=note or "",
                               at=datetime.now()))


def status_trail(db, doc_type, doc_id) -> list:
    return [{"from": r.from_status, "to": r.to_status, "by": r.user_name or "", "at": r.at.isoformat(timespec="seconds"),
             "note": r.note or ""}
            for r in db.query(DBStoreDocStatusLog).filter(DBStoreDocStatusLog.doc_type == doc_type,
                                                          DBStoreDocStatusLog.doc_id == doc_id)
            .order_by(DBStoreDocStatusLog.id).all()]


def has_history(db, store_id, item_id) -> bool:
    """Whether the store has stock history for the item that still stands - anything other than movements a later
    reversal has undone (and those reversals)."""
    reversed_ids = db.query(DBStoreStockLedger.reversal_of_id).filter(
        DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id,
        DBStoreStockLedger.reversal_of_id.isnot(None))
    return db.query(DBStoreStockLedger.id).filter(
        DBStoreStockLedger.store_id == store_id, DBStoreStockLedger.item_id == item_id,
        DBStoreStockLedger.reversal_of_id.is_(None), DBStoreStockLedger.id.notin_(reversed_ids)).first() is not None


# --- stores --------------------------------------------------------------------------------------------------------

_CODE = re.compile(r"^[A-Z0-9]{2,10}$")


class StoreIn(BaseModel):
    code: str = Field(..., description="2-10 capital letters or digits; appears in every document number (CS01)")
    name: str
    type: StoreType = StoreType.CENTRAL
    project_id: Optional[int] = None
    address: str = ""


class StoreUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    type: Optional[StoreType] = None
    project_id: Optional[int] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None


def _check_project(db, actor, store_type, project_id):
    if project_id:
        job = db.get(models.DBJob, project_id)
        if job is None or job.client_id != actor.client.id:
            raise HTTPException(400, "That project does not exist.")
    if store_type == StoreType.SITE.value and not project_id:
        raise HTTPException(400, "A site store belongs to a project: choose one.")


def _store_row(db, st, projects, mine) -> dict:
    return {"id": st.id, "code": st.code, "name": st.name, "type": st.type, "project_id": st.project_id,
            "project": projects.get(st.project_id, "") if st.project_id else "", "address": st.address or "",
            "is_active": bool(st.is_active), "accessible": mine is None or st.id in mine,
            "frozen": db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id == st.id,
                                                        DBStoreFreeze.unfrozen_at.is_(None)).first() is not None,
            "bins": db.query(func.count(DBStoreBin.id)).filter(DBStoreBin.store_id == st.id, DBStoreBin.is_active.is_(True)).scalar(),
            "users": db.query(func.count(DBStoreUserAssignment.id)).filter(
                DBStoreUserAssignment.store_id == st.id, DBStoreUserAssignment.is_active.is_(True)).scalar()}


def _stores(db, actor, include_inactive=False) -> list:
    query = db.query(DBStore).filter(DBStore.client_id == actor.client.id)
    if not include_inactive:
        query = query.filter(DBStore.is_active.is_(True))
    projects, mine = project_names(db, actor.client.id), accessible_store_ids(db, actor)
    return [_store_row(db, st, projects, mine) for st in query.order_by(DBStore.code).all()]


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door: the company's active stores."""
    actor = store_actor(request, db, VIEW)
    return {"slice": "masters", "items": _stores(db, actor)}


@router.get("/stores")
def list_stores(request: Request, include_inactive: bool = False, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    return {"stores": _stores(db, actor, include_inactive)}


@router.post("/stores")
def create_store(body: StoreIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    code = body.code.strip().upper()
    if not _CODE.match(code):
        raise HTTPException(400, "A store code is 2 to 10 capital letters or digits, like CS01.")
    if not body.name.strip():
        raise HTTPException(400, "Give the store a name.")
    if db.query(DBStore.id).filter(DBStore.client_id == actor.client.id, func.upper(DBStore.code) == code).first():
        raise HTTPException(409, "Store code %s is already in use." % code)
    _check_project(db, actor, body.type.value, body.project_id)
    st = DBStore(client_id=actor.client.id, code=code, name=body.name.strip(), type=body.type.value,
                 project_id=body.project_id or None, address=body.address.strip(), is_active=True)
    db.add(st)
    db.commit()
    return _store_row(db, st, project_names(db, actor.client.id), accessible_store_ids(db, actor))


@router.put("/stores/{store_id}")
def update_store(store_id: int, body: StoreUpdate, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    st = company_store(db, actor, store_id)
    if body.code is not None and body.code.strip().upper() != st.code:
        code = body.code.strip().upper()
        if not _CODE.match(code):
            raise HTTPException(400, "A store code is 2 to 10 capital letters or digits, like CS01.")
        used = (db.query(DBStoreDocSequence.id).filter(DBStoreDocSequence.store_id == st.id).first()
                or db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.store_id == st.id).first())
        if used:
            raise HTTPException(409, "Documents have already been numbered with %s; its code cannot change." % st.code)
        if db.query(DBStore.id).filter(DBStore.client_id == actor.client.id, func.upper(DBStore.code) == code,
                                       DBStore.id != st.id).first():
            raise HTTPException(409, "Store code %s is already in use." % code)
        st.code = code
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "Give the store a name.")
        st.name = body.name.strip()
    new_type = body.type.value if body.type is not None else st.type
    new_project = st.project_id if body.project_id is None else (body.project_id or None)
    _check_project(db, actor, new_type, new_project)
    st.type, st.project_id = new_type, new_project
    if body.address is not None:
        st.address = body.address.strip()
    if body.is_active is False and st.is_active:
        held = db.query(DBStoreStockBalance.id).filter(DBStoreStockBalance.store_id == st.id, DBStoreStockBalance.qty > 0).first()
        if held:
            raise HTTPException(409, "%s still holds stock. Transfer or adjust it out before closing the store." % st.code)
        if db.query(DBStoreFreeze.id).filter(DBStoreFreeze.store_id == st.id, DBStoreFreeze.unfrozen_at.is_(None)).first():
            raise HTTPException(409, "%s is frozen for a count. Finish the count first." % st.code)
    if body.is_active is not None:
        st.is_active = body.is_active
    db.commit()
    return _store_row(db, st, project_names(db, actor.client.id), accessible_store_ids(db, actor))


# --- bins ----------------------------------------------------------------------------------------------------------

class BinIn(BaseModel):
    code: str
    description: str = ""


class BinUpdate(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


def _bin_row(b) -> dict:
    return {"id": b.id, "store_id": b.store_id, "code": b.code, "description": b.description or "", "is_active": bool(b.is_active)}


def _bin_code(db, store_id, code, not_id=None) -> str:
    code = (code or "").strip().upper()
    if not code or len(code) > 20:
        raise HTTPException(400, "A bin code is 1 to 20 characters, like A-01.")
    clash = db.query(DBStoreBin.id).filter(DBStoreBin.store_id == store_id, func.upper(DBStoreBin.code) == code)
    if not_id:
        clash = clash.filter(DBStoreBin.id != not_id)
    if clash.first():
        raise HTTPException(409, "Bin %s is already in this store." % code)
    return code


@router.get("/stores/{store_id}/bins")
def list_bins(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    st = company_store(db, actor, store_id)
    return {"store_id": st.id, "bins": [_bin_row(b) for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == st.id)
                                        .order_by(DBStoreBin.code).all()]}


@router.post("/stores/{store_id}/bins")
def create_bin(store_id: int, body: BinIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    st = company_store(db, actor, store_id)
    b = DBStoreBin(store_id=st.id, code=_bin_code(db, st.id, body.code), description=body.description.strip(), is_active=True)
    db.add(b)
    db.commit()
    return _bin_row(b)


@router.put("/bins/{bin_id}")
def update_bin(bin_id: int, body: BinUpdate, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    b = db.get(DBStoreBin, bin_id)
    if b is None:
        raise HTTPException(404, "Bin not found")
    company_store(db, actor, b.store_id)
    if body.code is not None:
        b.code = _bin_code(db, b.store_id, body.code, not_id=b.id)
    if body.description is not None:
        b.description = body.description.strip()
    if body.is_active is not None:
        b.is_active = body.is_active
    db.commit()
    return _bin_row(b)


# --- who works where -----------------------------------------------------------------------------------------------

class AssignIn(BaseModel):
    employee_id: int
    role: str = "STOREKEEPER"


class AssignUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


def _role(role) -> str:
    role = (role or "").strip().upper()
    if role not in ROLES:
        raise HTTPException(400, "Role is one of %s." % ", ".join(ROLES))
    return role


def _assignment_row(a, emp) -> dict:
    name = ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip() if emp else ""
    return {"id": a.id, "store_id": a.store_id, "employee_id": a.employee_id, "name": name,
            "email": (emp.email if emp else "") or "", "job_title": (emp.job_title if emp else "") or "",
            "role": a.role or "", "is_active": bool(a.is_active),
            "assigned_at": a.assigned_at.isoformat(timespec="seconds") if a.assigned_at else ""}


@router.get("/stores/{store_id}/users")
def list_users(store_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    st = company_store(db, actor, store_id)
    rows = (db.query(DBStoreUserAssignment, models.DBEmployee)
            .join(models.DBEmployee, models.DBEmployee.id == DBStoreUserAssignment.employee_id)
            .filter(DBStoreUserAssignment.store_id == st.id).order_by(models.DBEmployee.first_name).all())
    return {"store_id": st.id, "roles": list(ROLES), "users": [_assignment_row(a, e) for a, e in rows]}


@router.post("/stores/{store_id}/users")
def assign_user(store_id: int, body: AssignIn, request: Request, db: Session = Depends(get_db)):
    """Give a member of staff a place in the store (or bring back one who was taken off it)."""
    actor = store_actor(request, db, CREATE)
    st = company_store(db, actor, store_id)
    emp = db.get(models.DBEmployee, body.employee_id)
    if emp is None or emp.client_id != actor.client.id:
        raise HTTPException(404, "Employee not found")
    if emp.status == "terminated":
        raise HTTPException(400, "%s %s has left." % (emp.first_name or "", emp.last_name or ""))
    a = db.query(DBStoreUserAssignment).filter(DBStoreUserAssignment.store_id == st.id,
                                               DBStoreUserAssignment.employee_id == emp.id).first()
    if a is None:
        a = DBStoreUserAssignment(store_id=st.id, employee_id=emp.id)
        db.add(a)
    a.role, a.is_active, a.assigned_at = _role(body.role), True, datetime.now()
    db.commit()
    return _assignment_row(a, emp)


@router.put("/assignments/{assignment_id}")
def update_assignment(assignment_id: int, body: AssignUpdate, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    a = db.get(DBStoreUserAssignment, assignment_id)
    if a is None:
        raise HTTPException(404, "Assignment not found")
    company_store(db, actor, a.store_id)
    if body.role is not None:
        a.role = _role(body.role)
    if body.is_active is not None:
        a.is_active = body.is_active
    db.commit()
    return _assignment_row(a, db.get(models.DBEmployee, a.employee_id))


@router.get("/employees")
def employee_options(request: Request, q: str = "", limit: int = 30, db: Session = Depends(get_db)):
    """Staff who could be given a place in a store."""
    actor = store_actor(request, db, CREATE)
    query = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == actor.client.id,
                                               or_(models.DBEmployee.status.is_(None), models.DBEmployee.status != "terminated"))
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        like = "%" + term + "%"
        query = query.filter(or_(models.DBEmployee.first_name.ilike(like), models.DBEmployee.last_name.ilike(like),
                                 models.DBEmployee.email.ilike(like)))
    rows = query.order_by(models.DBEmployee.first_name, models.DBEmployee.last_name).limit(max(1, min(limit, 100))).all()
    return {"employees": [{"id": e.id, "name": ("%s %s" % (e.first_name or "", e.last_name or "")).strip(),
                           "email": e.email or "", "job_title": e.job_title or ""} for e in rows]}


# --- item settings and units ---------------------------------------------------------------------------------------

class SettingsIn(BaseModel):
    category: ItemCategory = ItemCategory.CONSUMABLE
    base_uom: str
    reorder_level: Decimal = D(0)
    min_qty: Decimal = D(0)
    max_qty: Decimal = D(0)
    qc_required: bool = False
    over_receipt_tolerance_pct: Decimal = D(0)
    is_batch_tracked: bool = False


class UomIn(BaseModel):
    from_uom: str
    to_base_factor: Decimal


class UomUpdate(BaseModel):
    to_base_factor: Decimal


class PresetIn(BaseModel):
    kind: str = Field(..., description="CEMENT (kg / bag / MT), STEEL (nos and MT for a bar of dia_mm x bar_length_m), "
                                       "VOLUME (cum / cft)")
    dia_mm: Optional[Decimal] = None
    bar_length_m: Decimal = D(12)


# 1 unit = so many kg / cum. Cement bags are 50 kg; 1 cft = 0.028316846592 cum.
CEMENT_KG = {"kg": D(1), "bag": D(50), "mt": D(1000)}
VOLUME_CUM = {"cum": D(1), "cft": D("0.028316846592")}


def steel_kg_per_nos(dia_mm, bar_length_m=D(12)) -> Decimal:
    """A TMT bar's weight: d squared over 162 kg per metre, times its length."""
    dia, length = dec(dia_mm, "Diameter"), dec(bar_length_m, "Bar length")
    if dia <= 0 or length <= 0:
        raise HTTPException(400, "Diameter and bar length must be more than zero.")
    return q(dia * dia / D(162) * length, _FACTOR)


def preset_factors(kind, base, dia_mm=None, bar_length_m=D(12)) -> dict:
    """{unit: factor to the base unit} for a standard set of conversions."""
    kind, b = (kind or "").strip().upper(), (base or "").strip().lower()
    if kind == "CEMENT":
        if b not in CEMENT_KG:
            raise HTTPException(400, "Cement conversions need the base unit to be kg, bag or MT (it is %s)." % base)
        names = {"kg": "kg", "bag": "bag", "mt": "MT"}
        return {names[u]: q(kg / CEMENT_KG[b], _FACTOR) for u, kg in CEMENT_KG.items() if u != b}
    if kind == "STEEL":
        if b not in ("kg", "mt"):
            raise HTTPException(400, "Steel conversions need the base unit to be kg or MT (it is %s)." % base)
        if dia_mm is None:
            raise HTTPException(400, "Give the bar diameter in mm.")
        kg = steel_kg_per_nos(dia_mm, bar_length_m)
        per_base = D(1) if b == "kg" else D(1000)
        out = {"nos": q(kg / per_base, _FACTOR)}
        out["MT" if b == "kg" else "kg"] = q(D(1000) / per_base if b == "kg" else D(1) / D(1000), _FACTOR)
        return out
    if kind == "VOLUME":
        if b not in VOLUME_CUM:
            raise HTTPException(400, "Volume conversions need the base unit to be cum or cft (it is %s)." % base)
        other = "cft" if b == "cum" else "cum"
        return {other: q(VOLUME_CUM[other] / VOLUME_CUM[b], _FACTOR)}
    raise HTTPException(400, "Preset is CEMENT, STEEL or VOLUME.")


def _uoms(db, item) -> list:
    base = base_uom_of(db, item)
    out = [{"id": None, "code": base, "to_base_factor": "1.000000", "base": True}]
    for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).order_by(DBStoreUomConversion.id).all():
        out.append({"id": c.id, "code": c.from_uom, "to_base_factor": s(c.to_base_factor, _FACTOR), "base": False})
    return out


def _item_row(db, item, settings, held=None) -> dict:
    return {"id": item.id, "code": item.item_code, "name": item.item_name, "item_category": item.item_category or "",
            "item_uom": item.units_of_measure or "", "configured": settings is not None,
            "settings": None if settings is None else {
                "category": settings.category, "base_uom": settings.base_uom, "reorder_level": s(settings.reorder_level, _QTY),
                "min_qty": s(settings.min_qty, _QTY), "max_qty": s(settings.max_qty, _QTY), "qc_required": bool(settings.qc_required),
                "over_receipt_tolerance_pct": s(settings.over_receipt_tolerance_pct, D("0.001")),
                "is_batch_tracked": bool(settings.is_batch_tracked)},
            "base_uom": base_uom_of(db, item, settings), "uoms": _uoms(db, item),
            "has_stock_history": held if held is not None else
            db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.item_id == item.id).first() is not None}


@router.get("/items")
def list_items(request: Request, q: str = "", category: str = "", configured: str = "", limit: int = 200,
               db: Session = Depends(get_db)):
    """Stock items (the item master's RM items) with what the store has set for each."""
    actor = store_actor(request, db, VIEW)
    query = db.query(models.DBItem).filter(models.DBItem.client_id == actor.client.id, models.DBItem.kind == "RM",
                                           models.DBItem.is_active.is_(True))
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        like = "%" + term + "%"
        query = query.filter(or_(models.DBItem.item_code.ilike(like), models.DBItem.item_name.ilike(like)))
    items = query.order_by(models.DBItem.item_name).limit(max(1, min(limit, 1000))).all()
    ids = [i.id for i in items]
    settings = {x.item_id: x for x in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(ids)).all()} if ids else {}
    held = {r for (r,) in db.query(DBStoreStockLedger.item_id).filter(DBStoreStockLedger.item_id.in_(ids)).distinct()} if ids else set()
    rows = [_item_row(db, i, settings.get(i.id), i.id in held) for i in items]
    if category:
        rows = [r for r in rows if r["settings"] and r["settings"]["category"] == category.upper()]
    if configured in ("yes", "no"):
        rows = [r for r in rows if r["configured"] == (configured == "yes")]
    return {"items": rows, "categories": [c.value for c in ItemCategory]}


@router.get("/items/{item_id}")
def get_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    item = company_item(db, actor, item_id)
    return _item_row(db, item, db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first())


@router.put("/items/{item_id}/settings")
def save_settings(item_id: int, body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    item = company_item(db, actor, item_id)
    base = body.base_uom.strip()
    if not base:
        raise HTTPException(400, "Give the base unit stock is counted in.")
    for name in ("reorder_level", "min_qty", "max_qty"):
        if getattr(body, name) < 0:
            raise HTTPException(400, "%s cannot be negative." % name.replace("_", " ").capitalize())
    if body.max_qty and body.min_qty > body.max_qty:
        raise HTTPException(400, "The minimum is more than the maximum.")
    if not (0 <= body.over_receipt_tolerance_pct <= 100):
        raise HTTPException(400, "Over-receipt tolerance is a percentage between 0 and 100.")
    row = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    current = base_uom_of(db, item, row)
    if base.lower() != current.lower():
        if db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.item_id == item.id).first():
            raise HTTPException(409, "%s already has stock counted in %s; its base unit cannot change." % (item.item_code, current))
        if db.query(DBStoreUomConversion.id).filter(DBStoreUomConversion.item_id == item.id,
                                                   func.lower(DBStoreUomConversion.from_uom) == base.lower()).first():
            raise HTTPException(409, "%s is set up as a conversion; remove it before making it the base unit." % base)
    if row is None:
        row = DBStoreItemSettings(item_id=item.id, base_uom=base)
        db.add(row)
    row.category, row.base_uom = body.category.value, base
    row.reorder_level, row.min_qty, row.max_qty = q(body.reorder_level, _QTY), q(body.min_qty, _QTY), q(body.max_qty, _QTY)
    row.qc_required, row.is_batch_tracked = body.qc_required, body.is_batch_tracked
    row.over_receipt_tolerance_pct = q(body.over_receipt_tolerance_pct, D("0.001"))
    db.commit()
    return _item_row(db, item, row)


def _uom_code(db, item, code, not_id=None) -> str:
    code = (code or "").strip()
    if not code or len(code) > 20:
        raise HTTPException(400, "A unit is 1 to 20 characters, like bag.")
    if code.lower() == base_uom_of(db, item).lower():
        raise HTTPException(400, "%s is the base unit; it needs no conversion." % code)
    clash = db.query(DBStoreUomConversion.id).filter(DBStoreUomConversion.item_id == item.id,
                                                    func.lower(DBStoreUomConversion.from_uom) == code.lower())
    if not_id:
        clash = clash.filter(DBStoreUomConversion.id != not_id)
    if clash.first():
        raise HTTPException(409, "%s already has a conversion for %s." % (item.item_code, code))
    return code


def _factor(x) -> Decimal:
    f = q(dec(x, "Factor"), _FACTOR)
    if f <= 0:
        raise HTTPException(400, "The factor must be more than zero.")
    return f


@router.get("/items/{item_id}/uoms")
def list_uoms(item_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    item = company_item(db, actor, item_id)
    return {"item_id": item.id, "base_uom": base_uom_of(db, item), "uoms": _uoms(db, item)}


@router.post("/items/{item_id}/uoms")
def add_uom(item_id: int, body: UomIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    item = company_item(db, actor, item_id)
    db.add(DBStoreUomConversion(item_id=item.id, from_uom=_uom_code(db, item, body.from_uom), to_base_factor=_factor(body.to_base_factor)))
    db.commit()
    return {"item_id": item.id, "base_uom": base_uom_of(db, item), "uoms": _uoms(db, item)}


@router.post("/items/{item_id}/uoms/preset")
def add_preset(item_id: int, body: PresetIn, request: Request, db: Session = Depends(get_db)):
    """The standard conversions for cement, a steel bar size or volume, worked out from the item's base unit. A unit
    already set up is brought to the standard factor."""
    actor = store_actor(request, db, CREATE)
    item = company_item(db, actor, item_id)
    factors = preset_factors(body.kind, base_uom_of(db, item), body.dia_mm, body.bar_length_m)
    existing = {c.from_uom.lower(): c for c in db.query(DBStoreUomConversion).filter(DBStoreUomConversion.item_id == item.id).all()}
    for code, f in factors.items():
        if code.lower() in existing:
            existing[code.lower()].to_base_factor = f
        else:
            db.add(DBStoreUomConversion(item_id=item.id, from_uom=code, to_base_factor=f))
    db.commit()
    return {"item_id": item.id, "base_uom": base_uom_of(db, item), "uoms": _uoms(db, item)}


@router.put("/uoms/{uom_id}")
def update_uom(uom_id: int, body: UomUpdate, request: Request, db: Session = Depends(get_db)):
    """A new factor applies to what is entered from now on; stock already posted was posted in the base unit."""
    actor = store_actor(request, db, CREATE)
    c = db.get(DBStoreUomConversion, uom_id)
    if c is None:
        raise HTTPException(404, "Conversion not found")
    item = company_item(db, actor, c.item_id)
    c.to_base_factor = _factor(body.to_base_factor)
    db.commit()
    return {"item_id": item.id, "base_uom": base_uom_of(db, item), "uoms": _uoms(db, item)}


@router.delete("/uoms/{uom_id}")
def delete_uom(uom_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    c = db.get(DBStoreUomConversion, uom_id)
    if c is None:
        raise HTTPException(404, "Conversion not found")
    item = company_item(db, actor, c.item_id)
    db.delete(c)
    db.commit()
    return {"item_id": item.id, "base_uom": base_uom_of(db, item), "uoms": _uoms(db, item)}


@router.get("/steel-weight")
def steel_weight(request: Request, dia_mm: str, bar_length_m: str = "12", db: Session = Depends(get_db)):
    """kg per bar and per metre for a TMT size: d squared / 162 per metre."""
    store_actor(request, db, VIEW)
    per_m = q(dec(dia_mm, "Diameter") ** 2 / D(162), _FACTOR)
    return {"dia_mm": dia_mm, "bar_length_m": bar_length_m, "kg_per_m": s(per_m), "kg_per_nos": s(steel_kg_per_nos(dia_mm, bar_length_m))}


# --- opening stock -------------------------------------------------------------------------------------------------

class OpeningLineIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""
    rate: str
    bin_id: Optional[int] = None
    remarks: str = ""


class OpeningIn(BaseModel):
    store_id: int
    opening_date: date
    remarks: str = ""
    lines: List[OpeningLineIn]


class OpeningUpdate(BaseModel):
    opening_date: Optional[date] = None
    remarks: Optional[str] = None
    lines: Optional[List[OpeningLineIn]] = None


class ReasonIn(BaseModel):
    reason: str = ""


def _priced(db, item, qty, uom, rate):
    """(entered qty, unit, entered rate, base qty, base rate, value) - the base figures being what is posted, and the
    value being exactly what the ledger will record for them."""
    entered_qty, entered_rate = q(dec(qty, "Quantity"), _QTY), q(dec(rate, "Rate"), _RATE)
    if entered_qty <= 0:
        raise InvalidMovementError("Quantity must be more than zero.")
    if entered_rate < 0:
        raise InvalidMovementError("Rate cannot be negative.")
    unit = (uom or "").strip() or base_uom_of(db, item)
    base_qty = convert_to_base(db, item.id, entered_qty, unit)
    if base_qty <= 0:
        raise InvalidMovementError("%s %s is less than one thousandth of the base unit." % (entered_qty, unit))
    base_rate = q(entered_qty * entered_rate / base_qty, _RATE)
    return entered_qty, unit, entered_rate, base_qty, base_rate, q(base_qty * base_rate, _VALUE)


def _check_lines(db, actor, store, opening_date, lines, *, not_doc=None) -> list:
    """Each line worked out and checked: [{...line, errors: [...]}]. Nothing is saved."""
    out, seen = [], set()
    bins = {b.id: b for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == store.id).all()}
    # Items already on another opening of this store that is still in hand (not cancelled, not yet posted).
    others = {line.item_id: doc.number for line, doc in (
        db.query(DBStoreOpeningLine, DBStoreOpening).join(DBStoreOpening, DBStoreOpening.id == DBStoreOpeningLine.opening_id)
        .filter(DBStoreOpening.store_id == store.id, DBStoreOpening.id != (not_doc or 0),
                DBStoreOpening.status.in_([DocStatus.DRAFT.value, DocStatus.SUBMITTED.value, DocStatus.APPROVED.value])).all())}
    for n, ln in enumerate(lines, 1):
        row = {"line_no": n, "item_id": ln.get("item_id"), "item_code": ln.get("item_code", ""), "item_name": "",
               "qty": ln.get("qty"), "uom": ln.get("uom") or "", "rate": ln.get("rate"), "bin_id": ln.get("bin_id"),
               "bin_code": ln.get("bin_code", ""), "remarks": (ln.get("remarks") or "")[:400], "errors": []}
        item = db.get(models.DBItem, row["item_id"]) if row["item_id"] else None
        if item is None or item.client_id != actor.client.id or item.kind != "RM" or not item.is_active:
            row["errors"].append("No stock item %s." % (row["item_code"] or row["item_id"] or "given"))
            out.append(row)
            continue
        row.update(item_code=item.item_code, item_name=item.item_name, base_uom=base_uom_of(db, item))
        try:
            eq, unit, er, bq, br, value = _priced(db, item, row["qty"], row["uom"], row["rate"])
            row.update(qty=s(eq), uom=unit, rate=s(er), base_qty=s(bq), base_rate=s(br), value=s(value))
        except (InvalidMovementError, HTTPException) as exc:
            row["errors"].append(exc.detail if isinstance(exc, HTTPException) else str(exc))
        if row["bin_id"]:
            b = bins.get(row["bin_id"])
            if b is None or not b.is_active:
                row["errors"].append("Bin %s is not in %s." % (row["bin_code"] or row["bin_id"], store.code))
            else:
                row["bin_code"] = b.code
        key = (item.id, row["bin_id"] or None)
        if key in seen:
            row["errors"].append("%s appears twice%s." % (item.item_code, " in the same bin" if row["bin_id"] else ""))
        seen.add(key)
        if has_history(db, store.id, item.id):
            row["errors"].append("%s already has stock movements in %s; opening stock is the first entry. Use a stock "
                                 "adjustment instead." % (item.item_code, store.code))
        elif item.id in others:
            row["errors"].append("%s is already on opening %s." % (item.item_code, others[item.id]))
        out.append(row)
    return out


def _check_head(store, opening_date):
    if not store.is_active:
        raise HTTPException(400, "%s is not active." % store.code)
    if opening_date > date.today():
        raise HTTPException(400, "Opening stock cannot be dated in the future.")


def _lines_in(lines) -> list:
    return [ln.model_dump() if hasattr(ln, "model_dump") else dict(ln) for ln in lines]


def _save_lines(db, doc, checked):
    db.query(DBStoreOpeningLine).filter(DBStoreOpeningLine.opening_id == doc.id).delete(synchronize_session=False)
    for row in checked:
        db.add(DBStoreOpeningLine(opening_id=doc.id, line_no=row["line_no"], item_id=row["item_id"], bin_id=row["bin_id"] or None,
                                  entered_qty=D(row["qty"]), entered_uom=row["uom"], entered_rate=D(row["rate"]),
                                  qty=D(row["base_qty"]), rate=D(row["base_rate"]), value=D(row["value"]),
                                  remarks=row["remarks"]))


def _refuse_errors(checked):
    bad = [r for r in checked if r["errors"]]
    if bad:
        raise HTTPException(400, "; ".join("Line %d: %s" % (r["line_no"], " ".join(r["errors"])) for r in bad[:10])
                            + (" (and %d more)" % (len(bad) - 10) if len(bad) > 10 else ""))


def _opening_or_404(db, actor, opening_id) -> DBStoreOpening:
    doc = db.get(DBStoreOpening, opening_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "Opening stock not found")
    assert_store_access(actor.user, doc.store_id)
    return doc


def _opening_row(db, doc, store=None, detail=False) -> dict:
    store = store or db.get(DBStore, doc.store_id)
    totals = db.query(func.count(DBStoreOpeningLine.id), func.coalesce(func.sum(DBStoreOpeningLine.value), 0)).filter(
        DBStoreOpeningLine.opening_id == doc.id).one()
    row = {"id": doc.id, "number": doc.number, "store_id": doc.store_id, "store_code": store.code, "store_name": store.name,
           "opening_date": doc.opening_date.isoformat(), "status": doc.status, "source": doc.source, "remarks": doc.remarks or "",
           "created_by": doc.created_by_name or "", "created_at": doc.created_at.isoformat(timespec="seconds") if doc.created_at else "",
           "posted_at": doc.posted_at.isoformat(timespec="seconds") if doc.posted_at else "",
           "cancel_reason": doc.cancel_reason or "", "lines_count": totals[0], "total_value": s(totals[1], _VALUE)}
    if detail:
        lines = (db.query(DBStoreOpeningLine, models.DBItem).join(models.DBItem, models.DBItem.id == DBStoreOpeningLine.item_id)
                 .filter(DBStoreOpeningLine.opening_id == doc.id).order_by(DBStoreOpeningLine.line_no).all())
        bins = {b.id: b.code for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == doc.store_id).all()}
        row["lines"] = [{"id": ln.id, "line_no": ln.line_no, "item_id": it.id, "item_code": it.item_code, "item_name": it.item_name,
                         "qty": s(ln.entered_qty, _QTY), "uom": ln.entered_uom, "rate": s(ln.entered_rate, _RATE),
                         "base_qty": s(ln.qty, _QTY), "base_uom": base_uom_of(db, it), "base_rate": s(ln.rate, _RATE),
                         "value": s(ln.value, _VALUE), "bin_id": ln.bin_id, "bin_code": bins.get(ln.bin_id, ""),
                         "remarks": ln.remarks or ""} for ln, it in lines]
        row["trail"] = status_trail(db, OPENING_DOC, doc.id)
    return row


def _create_opening(db, actor, store, opening_date, remarks, checked, source) -> DBStoreOpening:
    with store_errors():
        number = next_doc_number(db, OPENING_NUMBER, store.id, on_date=opening_date)
    doc = DBStoreOpening(client_id=actor.client.id, store_id=store.id, number=number, opening_date=opening_date,
                         status=DocStatus.DRAFT.value, source=source, remarks=(remarks or "").strip(),
                         created_by=actor.user_id, created_by_name=person(actor))
    db.add(doc)
    db.flush()
    _save_lines(db, doc, checked)
    log_status(db, actor.client.id, OPENING_DOC, doc.id, None, DocStatus.DRAFT.value, actor,
               "Imported from a sheet" if source == OpeningSource.CSV.value else "")
    return doc


@router.get("/opening")
def list_openings(request: Request, store_id: int = 0, status: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    query = db.query(DBStoreOpening).filter(DBStoreOpening.client_id == actor.client.id)
    mine = accessible_store_ids(db, actor)
    if mine is not None:
        query = query.filter(DBStoreOpening.store_id.in_(mine or {-1}))
    if store_id:
        query = query.filter(DBStoreOpening.store_id == store_id)
    if status:
        query = query.filter(DBStoreOpening.status == status.upper())
    stores = {st.id: st for st in db.query(DBStore).filter(DBStore.client_id == actor.client.id).all()}
    return {"openings": [_opening_row(db, d, stores.get(d.store_id))
                         for d in query.order_by(DBStoreOpening.id.desc()).limit(500).all()]}


@router.post("/opening")
def create_opening(body: OpeningIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    store = company_store(db, actor, body.store_id)
    _check_head(store, body.opening_date)
    if not body.lines:
        raise HTTPException(400, "Add at least one item.")
    checked = _check_lines(db, actor, store, body.opening_date, _lines_in(body.lines))
    _refuse_errors(checked)
    doc = _create_opening(db, actor, store, body.opening_date, body.remarks, checked, OpeningSource.MANUAL.value)
    db.commit()
    return _opening_row(db, doc, store, detail=True)


@router.get("/opening/template.csv")
def opening_template(request: Request, db: Session = Depends(get_db)):
    store_actor(request, db, VIEW)
    body = "item_code,qty,uom,rate,bin_code,remarks\nCEM-OPC53,400,bag,350,A-01,Shed 1\nTMT-12,1.5,MT,62000,,\n"
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="opening-stock.csv"'})


@router.get("/opening/{opening_id:int}")
def get_opening(opening_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    doc = _opening_or_404(db, actor, opening_id)
    return _opening_row(db, doc, detail=True)


@router.put("/opening/{opening_id:int}")
def update_opening(opening_id: int, body: OpeningUpdate, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, CREATE)
    doc = _opening_or_404(db, actor, opening_id)
    if doc.status != DocStatus.DRAFT.value:
        raise HTTPException(409, "Only a draft can be changed; this one is %s." % doc.status.lower())
    store = db.get(DBStore, doc.store_id)
    if body.opening_date is not None:
        _check_head(store, body.opening_date)
        doc.opening_date = body.opening_date
    if body.remarks is not None:
        doc.remarks = body.remarks.strip()
    if body.lines is not None:
        if not body.lines:
            raise HTTPException(400, "Add at least one item.")
        checked = _check_lines(db, actor, store, doc.opening_date, _lines_in(body.lines), not_doc=doc.id)
        _refuse_errors(checked)
        _save_lines(db, doc, checked)
    db.commit()
    return _opening_row(db, doc, store, detail=True)


# action -> (right, statuses it can be taken from, status it leads to)
OPENING_FLOW = {
    "submit": (CREATE, (DocStatus.DRAFT,), DocStatus.SUBMITTED),
    "approve": (APPROVE, (DocStatus.SUBMITTED,), DocStatus.APPROVED),
    "post": (POST, (DocStatus.APPROVED,), DocStatus.POSTED),
    "cancel": (CANCEL, (DocStatus.DRAFT, DocStatus.SUBMITTED, DocStatus.APPROVED, DocStatus.POSTED), DocStatus.CANCELLED),
}


def _post_opening(db, actor, doc, store):
    """Every line as an OPENING_IN, in one go: re-checked first, since stock may have moved since it was approved."""
    lines = db.query(DBStoreOpeningLine).filter(DBStoreOpeningLine.opening_id == doc.id).order_by(DBStoreOpeningLine.line_no).all()
    if not lines:
        raise HTTPException(400, "There is nothing on this opening to post.")
    checked = _check_lines(db, actor, store, doc.opening_date,
                           [{"item_id": ln.item_id, "qty": ln.entered_qty, "uom": ln.entered_uom, "rate": ln.entered_rate,
                             "bin_id": ln.bin_id, "remarks": ln.remarks} for ln in lines], not_doc=doc.id)
    _refuse_errors(checked)
    with store_errors():
        for ln in lines:
            post_movement(db, movement_type=MovementType.OPENING_IN, store_id=store.id, item_id=ln.item_id, qty=ln.qty,
                          rate=ln.rate, txn_date=doc.opening_date, project_id=store.project_id, ref_doc_type=OPENING_DOC,
                          ref_doc_id=doc.id, ref_line_id=ln.id, user_id=actor.user_id,
                          remarks=("Opening %s" % doc.number) + ((": " + ln.remarks) if ln.remarks else ""))
    doc.posted_at = datetime.now()


@router.post("/opening/{opening_id:int}/{action}")
def opening_action(opening_id: int, action: str, request: Request, body: Optional[ReasonIn] = None, db: Session = Depends(get_db)):
    """submit / approve / post / cancel. Posting moves the stock; cancelling a posted opening reverses it."""
    if action not in OPENING_FLOW:
        raise HTTPException(404, "Unknown action")
    right, sources, target = OPENING_FLOW[action]
    actor = store_actor(request, db, right)
    doc = _opening_or_404(db, actor, opening_id)
    store = db.get(DBStore, doc.store_id)
    if DocStatus(doc.status) not in sources:
        raise HTTPException(409, "A %s opening cannot be %s." % (doc.status.lower(), {"submit": "submitted", "approve": "approved",
                                                                                     "post": "posted", "cancel": "cancelled"}[action]))
    reason = ((body.reason if body else "") or "").strip()
    was = doc.status
    try:
        if action == "post":
            _post_opening(db, actor, doc, store)
        elif action == "cancel":
            if not reason:
                raise HTTPException(400, "Say why the opening is being cancelled.")
            if was == DocStatus.POSTED.value:
                with store_errors():
                    reverse_document(db, ref_doc_type=OPENING_DOC, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
            doc.cancel_reason = reason
        doc.status = target.value
        log_status(db, actor.client.id, OPENING_DOC, doc.id, was, target.value, actor, reason)
        db.commit()
    except (HTTPException, StoreError):
        db.rollback()
        raise
    return _opening_row(db, doc, store, detail=True)


@router.get("/opening/{opening_id:int}/document.pdf")
def opening_pdf(opening_id: int, request: Request, db: Session = Depends(get_db)):
    """The opening stock as a printed form: the store, every line in the unit entered and in the base unit, the total,
    and the signatures."""
    from app.documents import form_pdf
    from app.documents.forms import _field_doc, form_pdf_response
    actor = store_actor(request, db, VIEW)
    d = _opening_row(db, _opening_or_404(db, actor, opening_id), detail=True)
    rows = [[str(ln["line_no"]), "%s %s" % (ln["item_code"], ln["item_name"]), ln["bin_code"] or "-",
             "%s %s" % (ln["qty"], ln["uom"]), ln["rate"], "%s %s" % (ln["base_qty"], ln["base_uom"]), ln["value"]]
            for ln in d["lines"]]
    blocks = [
        {"type": "pairs", "rows": [("Store", "%s - %s" % (d["store_code"], d["store_name"])), ("Status", d["status"].title()),
                                   ("Source", d["source"].title()), ("Remarks", d["remarks"] or "-")], "label_width": 30},
        {"type": "table", "columns": [("S.No.", 10, "C"), ("Item", 70, "L"), ("Bin", 16, "C"), ("Quantity", 28, "R"),
                                      ("Rate", 22, "R"), ("Base quantity", 28, "R"), ("Value", 26, "R")],
         "rows": rows, "totals": [("Total value", d["total_value"], True)]},
    ]
    by = {t["to"]: t["by"] for t in d["trail"]}
    sig = [("Prepared by", d["created_by"]), ("Approved by", by.get("APPROVED", "")), ("Posted by", by.get("POSTED", ""))]
    name = d["number"].replace("/", "-")
    return form_pdf_response(_field_doc(db, actor.client, "OPENING STOCK", [("No.", d["number"]),
                                                                            ("Date", form_pdf.date_text(d["opening_date"]))],
                                        blocks, sig, name, watermark="CANCELLED" if d["status"] == "CANCELLED" else ""), name)


# --- opening stock from a sheet ------------------------------------------------------------------------------------

_HEADERS = {"item_code": ("item_code", "item code", "code", "item"), "qty": ("qty", "quantity"),
            "uom": ("uom", "unit"), "rate": ("rate", "price"), "bin_code": ("bin_code", "bin"), "remarks": ("remarks", "note", "notes")}


async def _read_sheet(file: UploadFile) -> list:
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "The sheet is larger than 5 MB.")
    try:
        text_ = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_ = raw.decode("latin-1")
    reader = csv.reader(io.StringIO(text_))
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(400, "The sheet is empty.") from None
    names = [h.strip().lower() for h in header]
    where = {}
    for key, aliases in _HEADERS.items():
        for i, h in enumerate(names):
            if h in aliases:
                where[key] = i
                break
    missing = [k for k in ("item_code", "qty", "rate") if k not in where]
    if missing:
        raise HTTPException(400, "The sheet needs the columns item_code, qty and rate (uom, bin_code and remarks are "
                                 "optional). Missing: %s." % ", ".join(missing))
    rows = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        rows.append({k: (cells[i].strip() if i < len(cells) else "") for k, i in where.items()})
        if len(rows) > MAX_IMPORT_ROWS:
            raise HTTPException(400, "A sheet can carry up to %d rows." % MAX_IMPORT_ROWS)
    if not rows:
        raise HTTPException(400, "The sheet has a header but no rows.")
    return rows


def _sheet_lines(db, actor, store, rows) -> list:
    """Sheet rows -> lines for _check_lines, the item and bin found by their codes."""
    codes = {r["item_code"].upper() for r in rows if r.get("item_code")}
    items = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == actor.client.id, func.upper(models.DBItem.item_code).in_(codes)).all()} if codes else {}
    bins = {b.code.upper(): b for b in db.query(DBStoreBin).filter(DBStoreBin.store_id == store.id).all()}
    out = []
    for r in rows:
        it = items.get((r.get("item_code") or "").upper())
        b = bins.get((r.get("bin_code") or "").upper()) if r.get("bin_code") else None
        out.append({"item_id": it.id if it else None, "item_code": r.get("item_code", ""), "qty": r.get("qty", ""),
                    "uom": r.get("uom", ""), "rate": r.get("rate", ""), "bin_id": b.id if b else (-1 if r.get("bin_code") else None),
                    "bin_code": r.get("bin_code", ""), "remarks": r.get("remarks", "")})
    return out


def _preview(checked) -> dict:
    ok = [r for r in checked if not r["errors"]]
    for r in checked:
        if r.get("bin_id") == -1:
            r["bin_id"] = None
    return {"rows": checked, "summary": {"rows": len(checked), "ok": len(ok), "errors": len(checked) - len(ok),
                                         "total_value": s(sum((D(r["value"]) for r in ok), D(0)), _VALUE)}}


@router.post("/opening/import/preview")
async def import_preview(request: Request, file: UploadFile = File(...), store_id: int = Form(...), opening_date: date = Form(...),
                         db: Session = Depends(get_db)):
    """What the sheet would make, row by row, and what is wrong with each row. Nothing is saved."""
    actor = store_actor(request, db, CREATE)
    store = company_store(db, actor, store_id)
    _check_head(store, opening_date)
    rows = await _read_sheet(file)
    return _preview(_check_lines(db, actor, store, opening_date, _sheet_lines(db, actor, store, rows)))


@router.post("/opening/import")
async def import_opening(request: Request, file: UploadFile = File(...), store_id: int = Form(...), opening_date: date = Form(...),
                         remarks: str = Form(""), skip_errors: bool = Form(False), db: Session = Depends(get_db)):
    """The sheet as a draft opening. Refused while any row is wrong, unless skip_errors: then the good rows only."""
    actor = store_actor(request, db, CREATE)
    store = company_store(db, actor, store_id)
    _check_head(store, opening_date)
    rows = await _read_sheet(file)
    preview = _preview(_check_lines(db, actor, store, opening_date, _sheet_lines(db, actor, store, rows)))
    good = [r for r in preview["rows"] if not r["errors"]]
    if preview["summary"]["errors"] and not skip_errors:
        raise HTTPException(400, "%d of %d rows have problems; fix them or import the good rows only."
                            % (preview["summary"]["errors"], preview["summary"]["rows"]))
    if not good:
        raise HTTPException(400, "No row of the sheet can be imported.")
    for n, r in enumerate(good, 1):
        r["line_no"] = n
    doc = _create_opening(db, actor, store, opening_date, remarks, good, OpeningSource.CSV.value)
    db.commit()
    return {"opening": _opening_row(db, doc, store, detail=True), "summary": preview["summary"]}
