"""Store module - reports routes under /api/store/reports. Owned by P5."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.store_auth import store_actor
from app.db import get_db

router = APIRouter(prefix="/api/store/reports", tags=["store-reports"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door. TODO(P5): replace with the real list."""
    store_actor(request, db, "store.reports.view")
    return {"slice": "reports", "items": []}
