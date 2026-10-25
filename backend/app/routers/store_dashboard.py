"""Store module - the Overview page's figures. Under /api/store/dashboard. Read only: it summarises what the slices keep."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.routers.store_lookup import ANY_VIEW
from app.routers.store_reports import _scope, jsonable
from app.services import store_dashboard

router = APIRouter(prefix="/api/store/dashboard", tags=["store-dashboard"])


@router.get("")
def dashboard(request: Request, store_id: int = 0, db: Session = Depends(get_read_db)):
    """Stock, work waiting, recent movements and project budgets for the stores this person may see (or the one asked for)."""
    actor = store_actor(request, db, ANY_VIEW)
    stores = _scope(db, actor, store_id)
    return jsonable(store_dashboard.dashboard(db, actor, stores))
