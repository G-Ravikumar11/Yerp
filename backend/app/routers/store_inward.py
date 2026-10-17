"""Store module - inward routes under /api/store/inward. Owned by P2."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.store_auth import store_actor
from app.db import get_db

router = APIRouter(prefix="/api/store/inward", tags=["store-inward"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    """The slice's front door. TODO(P2): replace with the real list."""
    store_actor(request, db, "store.inward.view")
    return {"slice": "inward", "items": []}
