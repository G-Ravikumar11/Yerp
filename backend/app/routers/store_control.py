"""Store module - control routes under /api/store/control. Owned by P4."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.store_auth import store_actor
from app.db import get_db

router = APIRouter(prefix="/api/store/control", tags=["store-control"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door. TODO(P4): replace with the real list."""
    store_actor(request, db, "store.control.view")
    return {"slice": "control", "items": []}
