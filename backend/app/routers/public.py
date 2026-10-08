"""The public endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.dates import _parse_date


router = APIRouter()


@router.get("/api/public/jobs/{client_ref}")
def public_job_board(client_ref: str, db: Session = Depends(get_db)):
    """Open roles for a company's careers page. Public: only published jobs,
    and never anything that identifies internal staff."""
    try:
        client_id = int(client_ref)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found")
    client = db.query(models.DBClient).filter(
        models.DBClient.id == client_id, models.DBClient.is_active == True
    ).first()
    if not client:
        raise HTTPException(status_code=404, detail="Not found")
    jobs = db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.client_id == client_id,
        models.DBJobRequisition.status == "open",
        models.DBJobRequisition.is_published == True,
    ).order_by(models.DBJobRequisition.id.desc()).all()

    today = datetime.now().date()
    listings = []
    for job in jobs:
        closing = _parse_date(job.closing_date)
        if closing and closing < today:
            continue
        form = db.query(models.DBRecruitmentForm).filter(
            models.DBRecruitmentForm.job_id == job.id,
            models.DBRecruitmentForm.is_active == True,
        ).first()
        listings.append({
            "id": job.id, "reference": job.reference, "title": job.title,
            "department": job.department.name if job.department else "",
            "location": job.location or "", "work_mode": job.work_mode,
            "employment_type": job.employment_type, "level": job.level or "",
            "description": job.description or "", "requirements": job.requirements or "",
            "salary_min": job.salary_min if job.show_salary else None,
            "salary_max": job.salary_max if job.show_salary else None,
            "salary_currency": job.salary_currency or client.currency or "",
            "closing_date": job.closing_date or "",
            "apply_token": form.form_token if form else None,
        })
    return {
        "company": client.company_name or "",
        "logo_url": client.logo_url or "",
        "jobs": listings,
    }


@router.get("/api/public/brand")
def public_brand(db: Session = Depends(get_db)):
    """The name on the front door.

    A single company's ERP: the sign-in page says whose it is. Only the name
    and the logo - nothing that says anything about the business - and only
    once the account has been set up, so a fresh installation says nothing.
    """
    c = db.query(models.DBClient).filter(
        models.DBClient.is_onboarded.is_(True)).order_by(models.DBClient.id).first()
    if not c:
        return {"company_name": "", "logo_url": ""}
    return {"company_name": c.company_name or "", "logo_url": c.logo_url or ""}
