"""Store module - cycle counting, under /api/store/cycle: items ranked A, B, C; what is due for counting; the company's counting rules; and the blind
second count of any line whose first count was far from the books. store.control.view reads; store.control.create counts; changing the rules needs store.control.approve, so those who count
cannot loosen the check on their own counts."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.store_control import DBStoreCount
from app.models.store_core import DBStoreUserAssignment
from app.services import store_cycle as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/cycle", tags=["store-cycle"])


class SettingsIn(BaseModel):
    days_a: Optional[str] = None
    days_b: Optional[str] = None
    days_c: Optional[str] = None
    recount_value: Optional[str] = None
    recount_pct: Optional[str] = None
    recount_min_value: Optional[str] = None


class RecountRowIn(BaseModel):
    item_id: int
    qty: str
    uom: str = ""


class RecountIn(BaseModel):
    rows: List[RecountRowIn]


def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def _stores(db, actor, store_id):
    seen = _visible(db, actor)
    if store_id:
        assert_store_access(actor.user, store_id)
        return {store_id}
    return seen


def _count(db, actor, doc_id):
    doc = db.get(DBStoreCount, doc_id)
    if doc is None or doc.client_id != actor.client.id:
        raise HTTPException(404, "Count not found")
    assert_store_access(actor.user, doc.store_id)
    return doc


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    out = svc.settings_dict(svc.settings_of(db, actor.client.id))
    db.commit()
    return out


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.approve")
    try:
        row = svc.save_settings(db, actor.client.id, body)
        log_audit(db, actor.client.id, "store_cycle_settings", "company", actor.client.id, "cycle counting", str(svc.settings_dict(row))[:200], request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return svc.settings_dict(row)


@router.get("/abc")
def get_abc(request: Request, store_id: int = 0, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, "store.control.view")
    stores = _stores(db, actor, store_id)
    return {"items": svc.abc(db, actor.client.id, None if stores is None else (stores or {0}))}


@router.get("/due")
def get_due(request: Request, store_id: int = 0, due_only: bool = True, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.view")
    stores = _stores(db, actor, store_id)
    rows = svc.due_for_counting(db, actor.client.id, stores)
    db.commit()
    return {"items": [r for r in rows if r["due"]] if due_only else rows}


@router.get("/recount/{doc_id}")
def recount_list(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """The lines of an open count to be counted again. Only names and units: the books and the first count stay hidden."""
    actor = store_actor(request, db, "store.control.create")
    doc = _count(db, actor, doc_id)
    open_ = doc.status == "DRAFT" and doc.started_at is not None
    out = svc.recount_list(db, doc) if open_ else []
    db.commit()
    return {"count_id": doc.id, "number": doc.number, "items": out}


@router.post("/recount/{doc_id}")
def save_recount(doc_id: int, body: RecountIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.control.create")
    doc = _count(db, actor, doc_id)
    try:
        svc.save_recounts(db, actor, doc, body.rows)
        log_audit(db, actor.client.id, "store_count_recounted", "store_doc", doc.id, doc.number, "%d line(s)" % len(body.rows), request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"count_id": doc.id, "still_to_recount": len(svc.lines_to_recount(db, doc))}
