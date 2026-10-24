"""Store module - what accounts need from the stores, under /api/store/accounts: stock value, goods received and not billed, scrap sales to collect
(and receiving the money), inter-project transfers to charge across, and gate-delivery price differences. store.reports.view reads;
store.reports.create marks a cross-charge adjusted; receiving scrap money also needs the right to record money (bills.pay)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import wo_actor
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor
from app.db import get_db
from app.models.store_control import DBStoreScrap
from app.models.store_core import DBStoreUserAssignment
from app.services import store_accounts as svc
from app.services.store_inward import day
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/accounts", tags=["store-accounts"])


class ReceiveIn(BaseModel):
    amount: str
    account_id: Optional[int] = None
    paid_on: Optional[str] = None
    mode: str = "Bank transfer"
    reference: str = ""


class AdjustIn(BaseModel):
    note: str = ""


def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


@router.get("/summary")
def get_summary(request: Request, as_on: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    out = svc.summary(db, actor.client.id, _visible(db, actor), day(as_on, "date", required=False))
    db.commit()
    return out


@router.get("/not-billed")
def get_not_billed(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    return {"items": svc.grni(db, actor.client.id)}


@router.get("/scrap")
def get_scrap(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    return {"items": svc.scrap_sales(db, actor.client.id, _visible(db, actor))}


@router.post("/scrap/{scrap_id}/receive")
def receive_scrap(scrap_id: int, body: ReceiveIn, request: Request, db: Session = Depends(get_db)):
    wo_actor(request, db, "bills.pay")                                   # the right to record money
    actor = store_actor(request, db, "store.reports.view")
    scrap = db.get(DBStoreScrap, scrap_id)
    if scrap is None or scrap.client_id != actor.client.id:
        raise HTTPException(404, "Scrap document not found")
    assert_store_access(actor.user, scrap.store_id)
    try:
        entry = svc.receive_scrap_proceeds(db, actor, scrap_id, body.amount, body.account_id, body.paid_on, body.mode, body.reference)
        log_audit(db, actor.client.id, "store_scrap_received", "store_doc", scrap.id, scrap.number, body.amount, request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"scrap_id": scrap_id, "money_entry_id": entry.id, "receipt_number": entry.number, "message": "Receipt %s recorded" % entry.number}


@router.get("/cross-charges")
def get_cross_charges(request: Request, status: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    out = svc.cross_charges(db, actor.client.id, status)
    db.commit()
    return {"items": out}


@router.post("/cross-charges/{charge_id}/adjust")
def adjust_cross_charge(charge_id: int, body: AdjustIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.create")
    try:
        row = svc.mark_adjusted(db, actor, charge_id, body.note)
        log_audit(db, actor.client.id, "store_cross_charge_adjusted", "store_cross_charge", row.id, str(row.id), row.status, request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"id": row.id, "status": row.status}


@router.get("/price-variances")
def get_variances(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.reports.view")
    return {"items": svc.price_variances(db, actor.client.id)}
