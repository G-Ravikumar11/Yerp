"""What the company website (frontend/src/features/site) reads from the ERP, and the one thing it writes - and, for
Settings -> Website, the website's own content: its sections drafted and published, its pictures, the projects it shows,
and the preview.

Public: no sign-in. It is the company's own website, so the company is the one the ERP was set up for (as on the sign-in
page). Only totals, what a project's card says and the published words and pictures leave here - never a value, a cost,
a person or a contact, and never the draft. An enquiry comes in as a new lead in the Tender Pipeline and rings the bell.
"""
from typing import Any, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.constants.projects import JOB_STATUSES
from app.core.auth import require_items_access, session_can, wo_actor
from app.core.files import file_bytes, file_headers, hand_on_bytes, served_type, store_file
from app.core.notifications import notify
from app.core.security import rate_limiter
from app.db import get_db, get_read_db
from app.services import website_careers, website_content
from app.services.crm import _log_lead, next_lead_number
from app.services.safety_hours import safe_hours
from app.validators.common import validate_email_address

router = APIRouter()

FINISHED, RUNNING = "complete", ("won", "in_progress")
assert FINISHED in JOB_STATUSES and all(s in JOB_STATUSES for s in RUNNING)
PHOTOS_PER_PROJECT = website_content.MAX_PROJECT_PHOTOS
WEBSITE_FILES = "website"          # attached_type of a picture uploaded for the website itself, not for a project
# The shape the panel crops a picture to, by where it goes: width and height in pixels.
PLACES = {"hero": (1600, 900), "section": (1200, 900), "story": (1200, 800), "project": (1200, 900)}


def _company(db):
    c = db.query(models.DBClient).filter(models.DBClient.is_onboarded.is_(True)).order_by(models.DBClient.id).first()
    if not c:
        raise HTTPException(404, "Not found")
    return c


def _shown(db, client_id):
    return db.query(models.DBJob).filter(models.DBJob.client_id == client_id, models.DBJob.show_on_website.is_(True),
                                         models.DBJob.status != "cancelled")


def _photos(db, client_id, job_ids, chosen=None):
    """{project id: [photo ids]}: the photos chosen for its card in Settings -> Website, in that order, or else the newest
    ones kept against the project itself (not its diary days)."""
    F = models.DBFile
    out = {}
    if not job_ids:
        return out
    chosen = chosen or {}
    for fid, job_id in db.query(F.id, F.job_id).filter(
            F.client_id == client_id, F.job_id.in_(job_ids), F.kind == "photo", F.attached_type == "job",
            F.content_type.like("image/%")).order_by(F.id.desc()).all():
        picked = chosen.get(job_id)
        got = out.setdefault(job_id, [])
        if picked is not None:
            if fid in picked:
                got.append(fid)
        elif len(got) < PHOTOS_PER_PROJECT:
            got.append(fid)
    for job_id, picked in chosen.items():
        if job_id in out:
            out[job_id].sort(key=picked.index)
    return out


def _card(job, cards):
    """A project's card: as `cards` has it (the draft), or else as the project holds it (what is published)."""
    card = cards.get(str(job.id))
    if not isinstance(card, dict):
        return {"show": bool(job.show_on_website), "sector": job.website_sector or "", "location": job.website_location or "",
                "scope": job.website_scope or "", "photos": None}
    return {"show": bool(card.get("show")), "sector": card.get("sector") or "", "location": card.get("location") or "",
            "scope": card.get("scope") or "", "photos": card.get("photos")}


def _figures(db, c, content, cards, chosen, photo_url):
    """What the site is drawn from: the live totals, the projects on the website with their cards and photos, and the
    words and pictures. `cards` override what the projects hold (the draft, for the preview); `chosen` is the photos picked
    for each card, by project id."""
    J = models.DBJob
    order = (J.status != FINISHED, J.start_date.desc(), J.id.desc())
    if cards:
        pool = db.query(J).filter(J.client_id == c.id, J.status != "cancelled").order_by(*order).all()
        jobs = [j for j in pool if _card(j, cards)["show"]][:60]
    else:
        jobs = _shown(db, c.id).order_by(*order).limit(60).all()
    shown = {j.id: _card(j, cards) for j in jobs}
    photos = _photos(db, c.id, [j.id for j in jobs], chosen)
    return {
        "company_id": c.id,                  # the careers page's reference, already public on its links
        "numbers": {
            "projects_delivered": db.query(J.id).filter(J.client_id == c.id, J.status == FINISHED).count(),
            "ongoing_sites": db.query(J.id).filter(J.client_id == c.id, J.status.in_(RUNNING)).count(),
            "safe_man_hours": safe_hours(db, c.id)["safe_hours"],
        },
        "projects": [{
            "id": j.id, "name": j.name or "", "client": j.customer_name or "", "sector": shown[j.id]["sector"],
            "location": shown[j.id]["location"], "scope": shown[j.id]["scope"],
            "status": "Completed" if j.status == FINISHED else "Ongoing", "year": (j.start_date or "")[:4],
            "photos": [photo_url % f for f in photos.get(j.id, [])],
        } for j in jobs],
        "content": content,
        # The openings on the Careers section: Recruitment's open, published jobs, live as soon as they are posted.
        "openings": website_careers.public_openings(db, c.id),
    }


def _chosen(cards):
    return {int(k): v["photos"] for k, v in cards.items()
            if str(k).isdigit() and isinstance(v, dict) and isinstance(v.get("photos"), list)}


@router.get("/api/public/site")
def site_figures(db: Session = Depends(get_read_db)):
    """The live numbers, the projects on the website, and the words and pictures as last published - never the draft."""
    c = _company(db)
    return _figures(db, c, website_content.published(db, c.id), {},
                    _chosen(website_content.published_projects(db, c.id)), "/api/public/site/photos/%d")


def _image(db, f, thumb, cache):
    small = file_bytes(db, f, thumb=True) if thumb else None
    media = "image/jpeg" if small else served_type(f.content_type)
    if not media.startswith("image/"):
        raise HTTPException(404, "Not found")
    return Response(content=small or file_bytes(db, f) or b"", media_type=media,
                    headers=dict(file_headers(media), **{"Cache-Control": cache}))


@router.get("/api/public/site/photos/{fid}")
def site_photo(fid: int, thumb: int = 0, db: Session = Depends(get_read_db)):
    """A photo of a project shown on the website, and nothing else."""
    c = _company(db)
    F = models.DBFile
    f = db.query(F).filter(F.id == fid, F.client_id == c.id, F.kind == "photo", F.attached_type == "job").first()
    if f is None or not (f.content_type or "").startswith("image/") or \
            not _shown(db, c.id).filter(models.DBJob.id == f.job_id).first():
        raise HTTPException(404, "Not found")
    return _image(db, f, thumb, "public, max-age=86400")


@router.get("/api/public/site/images/{fid}")
def site_image(fid: int, request: Request, thumb: int = 0, db: Session = Depends(get_read_db)):
    """A picture uploaded for the website, once it is on the published website. Whoever manages the website also sees the
    draft's pictures here, which is how the preview shows them before they are published."""
    c = _company(db)
    F = models.DBFile
    f = db.query(F).filter(F.id == fid, F.client_id == c.id, F.attached_type == WEBSITE_FILES).first()
    if f is None:
        raise HTTPException(404, "Not found")
    if website_content.image_in_use(db, c.id, fid):
        return _image(db, f, thumb, "public, max-age=86400")
    if session_can(request, db, "website.manage"):
        return _image(db, f, thumb, "private, no-store")
    raise HTTPException(404, "Not found")


# SETTINGS -> WEBSITE: the Master, or whoever has been given "Manage website". Reading needs the right; changing anything
# also needs a session that may change things (an account's read-only member may look, not change).

def _reader(request, db):
    return require_items_access(request, db, "website.manage")


def _manager(request, db):
    client, _, name = wo_actor(request, db, "website.manage")
    if not session_can(request, db, "website.manage"):
        raise HTTPException(403, "Your access does not include: Manage website.")
    return client, name


@router.get("/api/website/sections")
def website_sections(request: Request, db: Session = Depends(get_db)):
    """The website's sections, each with what is published and the draft, and the latest version."""
    client = _reader(request, db)
    if website_content.ensure_sections(db, client.id):
        db.commit()
    return {"sections": website_content.sections(db, client.id), "latest": (website_content.versions(db, client.id, 1) or [None])[0]}


class DraftIn(BaseModel):
    draft: Any = None


@router.put("/api/website/sections/{key}")
def save_section(key: str, body: DraftIn, request: Request, db: Session = Depends(get_db)):
    """Keep a section's draft. The website does not change until it is published."""
    client, name = _manager(request, db)
    website_content.save_draft(db, client.id, key, body.draft, name)
    db.commit()
    return {"ok": True, "message": "Draft saved. Publish to put it on the website."}


@router.post("/api/website/sections/{key}/discard")
def discard_section(key: str, request: Request, db: Session = Depends(get_db)):
    """Throw a section's draft away: it goes back to what is on the website."""
    client, name = _manager(request, db)
    website_content.discard_draft(db, client.id, key, name)
    db.commit()
    return {"ok": True, "message": "Draft discarded."}


class PublishIn(BaseModel):
    note: str = ""


@router.post("/api/website/publish")
def publish_website(body: PublishIn, request: Request, db: Session = Depends(get_db)):
    """Put every draft on the website, and keep this as the next version in the history."""
    client, name = _manager(request, db)
    v = website_content.publish(db, client.id, name, body.note)
    db.commit()
    return {"ok": True, "version": v.number, "message": "Published. The website now shows version %d." % v.number}


@router.get("/api/website/versions")
def website_versions(request: Request, db: Session = Depends(get_db)):
    client = _reader(request, db)
    return {"versions": website_content.versions(db, client.id)}


@router.post("/api/website/versions/{vid}/restore")
def restore_version(vid: int, request: Request, db: Session = Depends(get_db)):
    """Put an earlier version back on the website, as a new version."""
    client, name = _manager(request, db)
    v = website_content.restore(db, client.id, vid, name)
    db.commit()
    return {"ok": True, "version": v.number, "message": "%s. The website now shows version %d." % (v.note, v.number)}


@router.get("/api/website/preview")
def website_preview(request: Request, db: Session = Depends(get_db)):
    """The site as it will look once the draft is published: the draft's words, pictures and project cards."""
    client = _reader(request, db)
    cards = website_content.draft_projects(db, client.id)
    return _figures(db, client, website_content.draft(db, client.id), cards, _chosen(cards), "/api/website/images/%d")


@router.get("/api/website/projects")
def website_projects(request: Request, db: Session = Depends(get_db)):
    """Every project, with its card on the website as published and as drafted, and the photos kept against it."""
    client = _reader(request, db)
    J, F = models.DBJob, models.DBFile
    jobs = db.query(J).filter(J.client_id == client.id, J.status != "cancelled").order_by(J.id.desc()).all()
    drafts = website_content.draft_projects(db, client.id)
    published = website_content.published_projects(db, client.id)
    photos = {}
    for fid, job_id in db.query(F.id, F.job_id).filter(
            F.client_id == client.id, F.kind == "photo", F.attached_type == "job", F.job_id.in_([j.id for j in jobs] or [0]),
            F.content_type.like("image/%")).order_by(F.id.desc()).all():
        photos.setdefault(job_id, []).append(fid)
    out = []
    for j in jobs:
        live = _card(j, published) if str(j.id) in published else _card(j, {})
        live["show"], live["sector"], live["location"], live["scope"] = (
            bool(j.show_on_website), j.website_sector or "", j.website_location or "", j.website_scope or "")
        out.append({"id": j.id, "number": j.number or "", "name": j.name or "", "client": j.customer_name or "",
                    "status": "Completed" if j.status == FINISHED else "Ongoing", "published": live,
                    "draft": _card(j, drafts) if str(j.id) in drafts else dict(live),
                    "photos": photos.get(j.id, [])})
    return {"projects": out, "most_photos": PHOTOS_PER_PROJECT}


@router.get("/api/website/images")
def website_images(request: Request, db: Session = Depends(get_db)):
    """The pictures uploaded for the website, newest first, with whether each is in use."""
    client = _reader(request, db)
    F = models.DBFile
    rows = db.query(F.id, F.name, F.caption, F.created_at, F.size).filter(
        F.client_id == client.id, F.attached_type == WEBSITE_FILES).order_by(F.id.desc()).all()
    return {"images": [{"id": r.id, "name": r.name, "place": r.caption or "section", "created_at": r.created_at,
                        "size": r.size, "path": "%s%d" % (website_content.IMAGE_PATH, r.id),
                        "published": website_content.image_in_use(db, client.id, r.id),
                        "in_draft": website_content.image_in_use(db, client.id, r.id, "draft")} for r in rows],
            "places": {k: {"width": w, "height": h} for k, (w, h) in PLACES.items()}}


@router.post("/api/website/images")
def upload_website_image(request: Request, file: UploadFile = File(...), place: str = Form("section"),
                         job_id: int = Form(0), db: Session = Depends(get_db)):
    """A picture for the website, already cropped and made small in the browser. For a project it is kept with the
    project's own photos; anything else goes to the website's pictures."""
    client, name = _manager(request, db)
    if place not in PLACES:
        raise HTTPException(400, "Choose where the picture goes: the banner, a section, the story or a project.")
    if (file.content_type or "").lower() not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "A photo: JPEG, PNG or WebP.")
    data = file.file.read()
    if place == "project":
        if not db.query(models.DBJob.id).filter(models.DBJob.client_id == client.id, models.DBJob.id == job_id).first():
            raise HTTPException(404, "That project is not one of ours.")
        f = store_file(db, client.id, file, data, job_id=job_id, attached_type="job", attached_id=job_id, kind="photo", by=name)
        path = "/api/website/images/%d" % f.id
    else:
        f = store_file(db, client.id, file, data, job_id=None, attached_type=WEBSITE_FILES, attached_id=None, kind="photo",
                       caption=place, by=name)
        path = "%s%d" % (website_content.IMAGE_PATH, f.id)
    db.commit()
    return {"ok": True, "id": f.id, "path": path, "message": "Picture uploaded."}


@router.get("/api/website/images/{fid}")
def website_image(fid: int, request: Request, thumb: int = 0, db: Session = Depends(get_read_db)):
    """A picture for the panel and the preview: one uploaded for the website, or a project's photo."""
    client = _reader(request, db)
    F = models.DBFile
    f = db.query(F).filter(F.id == fid, F.client_id == client.id, F.kind == "photo",
                           F.attached_type.in_((WEBSITE_FILES, "job"))).first()
    if f is None:
        raise HTTPException(404, "Not found")
    return _image(db, f, thumb, "private, max-age=3600")


@router.delete("/api/website/images/{fid}")
def delete_website_image(fid: int, request: Request, db: Session = Depends(get_db)):
    """Remove a picture nobody uses: not on the website, and not in the draft."""
    client, _ = _manager(request, db)
    F = models.DBFile
    f = db.query(F).filter(F.id == fid, F.client_id == client.id, F.attached_type == WEBSITE_FILES).first()
    if f is None:
        raise HTTPException(404, "Not found")
    if website_content.image_in_use(db, client.id, fid) or website_content.image_in_use(db, client.id, fid, "draft"):
        raise HTTPException(409, "That picture is used on the website or in the draft. Take it out of there first.")
    hand_on_bytes(db, f)
    db.delete(f)
    db.commit()
    return {"ok": True, "message": "Picture removed."}


class OpeningIn(BaseModel):
    title: str = ""
    location: str = ""
    experience: str = ""
    description: str = ""


def _opening_reply(db, job, message):
    return {"ok": True, "message": message, "opening": next(o for o in website_careers.listing(db, job.client_id) if o["id"] == job.id)}


@router.get("/api/website/careers")
def website_careers_list(request: Request, db: Session = Depends(get_db)):
    """Every opening, with whether it is on the website and how many have applied."""
    client = _reader(request, db)
    return {"openings": website_careers.listing(db, client.id)}


@router.post("/api/website/careers")
def post_opening(body: OpeningIn, request: Request, db: Session = Depends(get_db)):
    """Post an opening: it is on the website's Careers section straight away, and applications arrive in Recruitment."""
    client, _ = _manager(request, db)
    job = website_careers.post(db, client.id, body)
    db.commit()
    return _opening_reply(db, job, "%s is posted on the website." % job.title)


@router.put("/api/website/careers/{job_id}")
def edit_opening(job_id: int, body: OpeningIn, request: Request, db: Session = Depends(get_db)):
    client, _ = _manager(request, db)
    job = website_careers.edit(db, client.id, job_id, body)
    db.commit()
    return _opening_reply(db, job, "Opening saved.")


@router.post("/api/website/careers/{job_id}/close")
def close_opening(job_id: int, request: Request, db: Session = Depends(get_db)):
    """Take an opening off the website. Its applications stay in Recruitment."""
    client, _ = _manager(request, db)
    job = website_careers.close(db, client.id, job_id)
    db.commit()
    return _opening_reply(db, job, "%s is closed and off the website." % job.title)


@router.post("/api/website/careers/{job_id}/reopen")
def reopen_opening(job_id: int, request: Request, db: Session = Depends(get_db)):
    client, _ = _manager(request, db)
    job = website_careers.reopen(db, client.id, job_id)
    db.commit()
    return _opening_reply(db, job, "%s is open again and on the website." % job.title)


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
