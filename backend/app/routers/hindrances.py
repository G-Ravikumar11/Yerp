"""The hindrance register endpoints: a site's list and its workbook, an entry added, changed or removed, and one started from a day's diary."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.sheets import sheet_response
from app.db import get_db, get_read_db
from app.schemas.projects import HindranceIn
from app.services.hindrances import (activity_names, apply_hindrance, draft_from_diary, hindrance_dict, hindrance_or_404, next_number,
                                     register, register_sheet)
from app.services.projects import diary_or_404, job_or_404

router = APIRouter()


@router.get("/api/jobs/{job_id}/hindrances")
def list_hindrances(job_id: int, request: Request, activity_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return register(db, client.id, job_or_404(db, client.id, job_id), activity_id or None)


@router.get("/api/jobs/{job_id}/hindrances.xlsx")
def export_hindrances(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    headers, rows, preamble, closing = register_sheet(db, client, job)
    return sheet_response(headers, rows, "hindrance_register_%s.xlsx" % (job.number or job.id), preamble=preamble, closing=closing)


@router.post("/api/jobs/{job_id}/hindrances")
def add_hindrance(job_id: int, body: HindranceIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, job_id)
    h = models.DBHindrance(client_id=client.id, job_id=job.id, created_by_name=actor_name)
    apply_hindrance(db, client.id, job, h, body, creating=True)
    h.number = next_number(db, job.id)
    db.add(h)
    db.flush()
    log_audit(db, client.id, "hindrance_added", "hindrance", h.id, h.number, "%s: %s" % (actor_name, h.cause), request)
    db.commit()
    return {"ok": True, "hindrance": hindrance_dict(h, activity_names(db, job.id)), "message": "%s added to the hindrance register." % h.number}


@router.put("/api/hindrances/{hid}")
def edit_hindrance(hid: int, body: HindranceIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    h = hindrance_or_404(db, client.id, hid)
    job = job_or_404(db, client.id, h.job_id)
    apply_hindrance(db, client.id, job, h, body, creating=False)
    h.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client.id, "hindrance_changed", "hindrance", h.id, h.number or "", "%s: %s, %s" % (actor_name, h.status, h.impact_days), request)
    db.commit()
    return {"ok": True, "hindrance": hindrance_dict(h, activity_names(db, job.id)), "message": "%s saved." % (h.number or "Hindrance")}


@router.delete("/api/hindrances/{hid}")
def delete_hindrance(hid: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    h = hindrance_or_404(db, client.id, hid)
    log_audit(db, client.id, "hindrance_deleted", "hindrance", h.id, h.number or "", "%s: %s %s" % (actor_name, h.cause, h.from_date), request)
    number = h.number or "Hindrance"
    db.delete(h)
    db.commit()
    return {"ok": True, "message": "%s removed from the register." % number}


@router.get("/api/diary/{diary_id}/hindrance-draft")
def hindrance_from_diary(diary_id: int, request: Request, db: Session = Depends(get_read_db)):
    """A hindrance started from the day's diary - what held the work up, or the rain - for the form to open with."""
    client = require_erp_read(request, db)
    return draft_from_diary(db, client.id, diary_or_404(db, client.id, diary_id))
