"""Store module - outward routes under /api/store/outward. Owned by P3."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.store_auth import store_actor
from app.db import get_db

router = APIRouter(prefix="/api/store/outward", tags=["store-outward"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door. TODO(P3): replace with the real list."""
    store_actor(request, db, "store.outward.view")
    return {"slice": "outward", "items": []}
