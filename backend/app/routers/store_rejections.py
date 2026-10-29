"""Store module - goods rejected at the gate, under /api/store/rejections: what is being held for the supplier to collect, and what
became of it. store.inward.view reads, store.inward.create closes one."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.store_core import DBStore, DBStoreUserAssignment
from app.models.store_extras import DBStoreRejection
from app.models.store_inward import DBStoreGrn
from app.services import store_rejections as svc
from app.services.store_inward import day, s3
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/rejections", tags=["store-rejections"])


class ResolveIn(BaseModel):
    outcome: str
    note: str = ""
    vehicle_no: str = ""
    on_date: Optional[str] = None


def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def _dicts(db, rows, client_id):
    grns = {g.id: g for g in db.query(DBStoreGrn).filter(DBStoreGrn.id.in_([r.grn_id for r in rows] or [0])).all()}
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == client_id).all()}
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([r.item_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        g, it = grns.get(r.grn_id), items.get(r.item_id)
        held = (date.today() - g.grn_date).days if g is not None and g.grn_date and r.status == "HELD" else 0
        out.append({"id": r.id, "status": r.status, "store_id": r.store_id, "store_code": stores[r.store_id].code if r.store_id in stores else "", "grn_id": r.grn_id,
                    "grn_number": g.number if g else "", "supplier_name": (g.supplier_name if g else "") or "", "grn_date": g.grn_date.isoformat() if g and g.grn_date else "",
                    "item_id": r.item_id, "item_code": it.item_code if it else "", "item_name": it.item_name if it else "", "qty": s3(r.qty), "reason": r.reason or "",
                    "resolved_on": r.resolved_on.isoformat() if r.resolved_on else "", "resolved_by": r.resolved_by_name or "", "vehicle_no": r.vehicle_no or "",
                    "note": r.resolution_note or "", "days_held": held})
    return out


@router.get("")
def list_rejections(request: Request, status: str = "HELD", store_id: int = 0, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, "store.inward.view")
    q = db.query(DBStoreRejection).filter(DBStoreRejection.client_id == actor.client.id, DBStoreRejection.status != "VOID")
    seen = _visible(db, actor)
    if seen is not None:
        q = q.filter(DBStoreRejection.store_id.in_(seen or {0}))
    if store_id:
        assert_store_access(actor.user, store_id)
        q = q.filter(DBStoreRejection.store_id == store_id)
    if status:
        q = q.filter(DBStoreRejection.status == status.strip().upper())
    return {"items": _dicts(db, q.order_by(DBStoreRejection.id.desc()).limit(500).all(), actor.client.id)}


@router.post("/{rejection_id}/resolve")
def resolve_rejection(rejection_id: int, body: ResolveIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.create")
    row = db.get(DBStoreRejection, rejection_id)
    if row is None or row.client_id != actor.client.id:
        raise HTTPException(404, "Rejected goods not found")
    assert_store_access(actor.user, row.store_id)
    try:
        svc.resolve(db, actor, row, body.outcome, body.note, body.vehicle_no, day(body.on_date, "date", required=False))
        log_audit(db, actor.client.id, "store_rejection_" + row.status.lower(), "store_rejection", row.id, str(row.id), row.status, request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _dicts(db, [row], actor.client.id)[0]
