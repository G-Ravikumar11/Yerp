"""Store module - supplier deliveries, under /api/store/deliveries: what is still owed on approved orders, short-closing an order that will not be
delivered in full (and reopening it), and the supplier scorecard. store.inward.view reads; store.inward.approve short-closes or reopens."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.store_auth import store_actor
from app.db import get_db
from app.services import store_deliveries as svc

router = APIRouter(prefix="/api/store/deliveries", tags=["store-deliveries"])


class CloseIn(BaseModel):
    reason: str = ""


@router.get("/pending")
def pending(request: Request, supplier: str = "", project_id: int = 0, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return {"items": svc.pending_deliveries(db, actor.client.id, supplier, project_id)}


@router.get("/short-closed")
def short_closed(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return {"items": svc.short_closed_orders(db, actor.client.id)}


@router.get("/suppliers")
def suppliers(request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.view")
    return {"items": svc.supplier_scorecard(db, actor.client.id)}


@router.post("/{po_id}/short-close")
def short_close(po_id: int, body: CloseIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.approve")
    try:
        row = svc.short_close(db, actor, po_id, body.reason)
        log_audit(db, actor.client.id, "store_po_short_close", "purchase_order", po_id, str(po_id), body.reason[:100], request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"po_id": row.po_id, "message": "Order short-closed"}


@router.post("/{po_id}/reopen")
def reopen(po_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.inward.approve")
    try:
        svc.reopen(db, actor, po_id)
        log_audit(db, actor.client.id, "store_po_reopen", "purchase_order", po_id, str(po_id), "reopened", request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"po_id": po_id, "message": "Order reopened for receiving"}
