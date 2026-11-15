"""What the company website (frontend/src/features/site) reads from the ERP, and the one thing it writes.

Public: no sign-in. It is the company's own website, so the company is the one the ERP was set up for (as on the sign-in
page). Only totals and what a project's "show on website" card says leave here - never a value, a cost, a person or a
contact. An enquiry comes in as a new lead in the Tender Pipeline and rings the bell.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.constants.projects import JOB_STATUSES
from app.core.files import file_bytes, file_headers, served_type
from app.core.notifications import notify
from app.core.security import rate_limiter
from app.db import get_db, get_read_db
from app.services.crm import _log_lead, next_lead_number
from app.services.safety_hours import safe_hours
from app.validators.common import validate_email_address

router = APIRouter()

FINISHED, RUNNING = "complete", ("won", "in_progress")
assert FINISHED in JOB_STATUSES and all(s in JOB_STATUSES for s in RUNNING)
PHOTOS_PER_PROJECT = 6


def _company(db):
    c = db.query(models.DBClient).filter(models.DBClient.is_onboarded.is_(True)).order_by(models.DBClient.id).first()
    if not c:
        raise HTTPException(404, "Not found")
    return c


def _shown(db, client_id):
    return db.query(models.DBJob).filter(models.DBJob.client_id == client_id, models.DBJob.show_on_website.is_(True),
                                         models.DBJob.status != "cancelled")


def _photos(db, client_id, job_ids):
    """{project id: [photo ids]}, newest first: the photos kept against the project itself, not its diary days."""
    F = models.DBFile
    out = {}
    if not job_ids:
        return out
    for fid, job_id in db.query(F.id, F.job_id).filter(
            F.client_id == client_id, F.job_id.in_(job_ids), F.kind == "photo", F.attached_type == "job",
            F.content_type.like("image/%")).order_by(F.id.desc()).all():
        got = out.setdefault(job_id, [])
        if len(got) < PHOTOS_PER_PROJECT:
            got.append(fid)
    return out


@router.get("/api/public/site")
def site_figures(db: Session = Depends(get_read_db)):
    """The live numbers and the projects ticked for the website."""
    c = _company(db)
    J = models.DBJob
    jobs = _shown(db, c.id).order_by(J.status != FINISHED, J.start_date.desc(), J.id.desc()).limit(60).all()
    photos = _photos(db, c.id, [j.id for j in jobs])
    return {
        "company_id": c.id,                  # the careers page's reference, already public on its links
        "numbers": {
            "projects_delivered": db.query(J.id).filter(J.client_id == c.id, J.status == FINISHED).count(),
            "ongoing_sites": db.query(J.id).filter(J.client_id == c.id, J.status.in_(RUNNING)).count(),
            "safe_man_hours": safe_hours(db, c.id)["safe_hours"],
        },
        "projects": [{
            "id": j.id, "name": j.name or "", "client": j.customer_name or "", "sector": j.website_sector or "",
            "location": j.website_location or "", "scope": j.website_scope or "",
            "status": "Completed" if j.status == FINISHED else "Ongoing", "year": (j.start_date or "")[:4],
            "photos": ["/api/public/site/photos/%d" % f for f in photos.get(j.id, [])],
        } for j in jobs],
    }


@router.get("/api/public/site/photos/{fid}")
def site_photo(fid: int, thumb: int = 0, db: Session = Depends(get_read_db)):
    """A photo of a project shown on the website, and nothing else."""
    c = _company(db)
    F = models.DBFile
    f = db.query(F).filter(F.id == fid, F.client_id == c.id, F.kind == "photo", F.attached_type == "job").first()
    if f is None or not (f.content_type or "").startswith("image/") or \
            not _shown(db, c.id).filter(models.DBJob.id == f.job_id).first():
        raise HTTPException(404, "Not found")
    small = file_bytes(db, f, thumb=True) if thumb else None
    media = "image/jpeg" if small else served_type(f.content_type)
    if not media.startswith("image/"):
        raise HTTPException(404, "Not found")
    return Response(content=small or file_bytes(db, f) or b"", media_type=media,
                    headers=dict(file_headers(media), **{"Cache-Control": "public, max-age=86400"}))


class EnquiryIn(BaseModel):
    name: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    city: str = ""
    project_type: str = ""
    scopes: List[str] = []
    message: str = ""
    website: str = ""            # left empty by people; a form-filling robot fills it in


@router.post("/api/public/enquiry")
def site_enquiry(body: EnquiryIn, request: Request, db: Session = Depends(get_db)):
    """An enquiry from the website: a new lead in the Tender Pipeline, and a notice on the bell."""
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited("enquiry:%s" % ip, max_requests=5, window=600):
        raise HTTPException(429, "Too many enquiries from here. Please try again later, or call us.")
    name, phone, email = body.name.strip()[:120], body.phone.strip()[:40], body.email.strip()[:160]
    if not name:
        raise HTTPException(400, "Please tell us your name.")
    if not phone and not email:
        raise HTTPException(400, "Please give a phone number or an email so we can reply.")
    if email and not validate_email_address(email):
        raise HTTPException(400, "Please enter a valid email address.")
    if body.website:
        return {"ok": True, "message": "Thank you. We will be in touch."}     # a robot: thanked, and nothing kept
    c = _company(db)
    city, kind = body.city.strip()[:80], body.project_type.strip()[:80]
    scopes = ", ".join(s.strip()[:40] for s in body.scopes[:12] if s.strip())
    title = "Website enquiry: %s" % ", ".join(x for x in (kind or "General", city) if x)
    notes = "\n".join(x for x in (body.message.strip()[:3000], "Scope: %s" % scopes if scopes else "") if x)
    lead = models.DBLead(client_id=c.id, number=next_lead_number(db, c.id), status="NEW", title=title[:200],
                         customer_name=(body.company.strip() or name)[:160], contact_person=name, phone=phone,
                         email=email, location=city, source="Website enquiry", notes=notes)
    db.add(lead)
    db.flush()
    _log_lead(db, c.id, lead, "Status", "Came in from the website.", "Website")
    db.commit()
    notify(db, c.id, "website_enquiry", "%s - %s" % (lead.number, title),
           "%s (%s). %s" % (name, " / ".join(x for x in (phone, email) if x), notes[:300]),
           view="leads-view", ref_type="lead", ref_id=lead.id)
    return {"ok": True, "message": "Thank you, %s. We have your enquiry and will be in touch." % name.split(" ")[0]}
