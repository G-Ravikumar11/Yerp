"""Store module - masters routes under /api/store/masters. Owned by P1."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.store_auth import store_actor
from app.db import get_db

router = APIRouter(prefix="/api/store/masters", tags=["store-masters"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door. TODO(P1): replace with the real list."""
    store_actor(request, db, "store.masters.view")
    return {"slice": "masters", "items": []}
