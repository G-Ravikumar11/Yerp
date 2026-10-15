"""The programme endpoints: Planning & Progress as the office's Excel schedule has it.

    GET /api/jobs/{job_id}/programme?as_of=YYYY-MM-DD     every row worked out: dates, days, numbering, roll-ups,
                                                          critical path, progress and planned progress on as_of
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_erp_read
from app.db import get_db
from app.services.programme import programme_view
from app.services.projects import _d, job_or_404

router = APIRouter()


@router.get("/api/jobs/{job_id}/programme")
def job_programme(job_id: int, request: Request, as_of: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return programme_view(db, client, job_or_404(db, client.id, job_id), _d(as_of))
