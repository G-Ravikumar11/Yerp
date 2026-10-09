"""Whether the AI is switched on and has a key, so a screen knows whether to show its AI buttons.

    GET /api/ai/subcontracts/status
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from Ai_service import guard
from app.core.auth import require_erp_read
from app.db import get_db

router = APIRouter()


@router.get("/api/ai/subcontracts/status")
def ai_status(request: Request, db: Session = Depends(get_db)):
    require_erp_read(request, db)
    return guard.status()
