"""The openings on the company website's Careers section, kept as Recruitment's own job requisitions.

An opening posted from Settings -> Website is an open, published requisition with an application form of its own, so the
site's "Apply" goes to that form and every application arrives in Recruitment like any other. Openings posted in
Recruitment show on the website too. They are live as soon as they are posted or closed: a job advert is not part of the
website's draft.
"""
import json
from datetime import datetime

from fastapi import HTTPException

from app import models
from app.core.dates import _parse_date
from app.core.serials import next_sequence_number

# What the website's application form asks. The CV is the first file, which Recruitment files as the resume.
APPLICATION_FIELDS = [
    {"label": "Full name", "type": "text", "required": True},
    {"label": "Email", "type": "email", "required": True},
    {"label": "Phone", "type": "phone", "required": True},
    {"label": "Years of experience", "type": "text", "required": False},
    {"label": "Where you live now", "type": "text", "required": False},
    {"label": "CV", "type": "file", "required": False},
    {"label": "Anything else you would like us to know", "type": "textarea", "required": False},
]
LIMITS = {"title": 120, "location": 120, "experience": 80, "description": 4000}


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _clean(body):
    out = {k: (getattr(body, k, "") or "").strip() for k in LIMITS}
    if not out["title"]:
        raise HTTPException(400, "Give the opening a title.")
    for k, most in LIMITS.items():
        if len(out[k]) > most:
            raise HTTPException(400, "%s: at most %d characters." % (k.capitalize(), most))
    return out


def _form(db, job):
    return db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.job_id == job.id,
                                                    models.DBRecruitmentForm.is_active.is_(True)).first()


def _job(db, client_id, job_id):
    job = db.query(models.DBJobRequisition).filter(models.DBJobRequisition.id == job_id,
                                                  models.DBJobRequisition.client_id == client_id).first()
    if not job:
        raise HTTPException(404, "That opening is not one of ours.")
    return job


def _ensure_form(db, client_id, job):
    """The opening's application form, made when it has none, so "Apply" on the website always works."""
    form = _form(db, job)
    if form is None:
        form = models.DBRecruitmentForm(client_id=client_id, job_id=job.id, title="Apply: %s" % job.title,
                                        description=job.description or "", fields=json.dumps(APPLICATION_FIELDS))
        db.add(form)
        db.flush()
    return form


def listing(db, client_id):
    """Every opening, newest first, with how many have applied - for the Careers part of the panel."""
    R, F, S = models.DBJobRequisition, models.DBRecruitmentForm, models.DBFormSubmission
    jobs = db.query(R).filter(R.client_id == client_id).order_by(R.id.desc()).all()
    forms = dict(db.query(F.id, F.job_id).filter(F.client_id == client_id, F.job_id.isnot(None)).all())
    applied = {}
    if forms:
        for (form_id,) in db.query(S.form_id).filter(S.form_id.in_(list(forms))).all():
            applied[forms[form_id]] = applied.get(forms[form_id], 0) + 1
    return [{"id": j.id, "reference": j.reference or "", "title": j.title, "location": j.location or "",
             "experience": j.experience or "", "description": j.description or "", "status": j.status,
             "on_website": is_live(j), "opened_at": j.opened_at or "", "closed_at": j.closed_at or "",
             "applications": applied.get(j.id, 0)} for j in jobs]


def is_live(job):
    closing = _parse_date(job.closing_date)
    return job.status == "open" and bool(job.is_published) and not (closing and closing < datetime.now().date())


def post(db, client_id, body):
    data = _clean(body)
    job = models.DBJobRequisition(
        client_id=client_id, reference=next_sequence_number(db, models.DBJobRequisition, client_id, "JOB-", field="reference"),
        title=data["title"], location=data["location"], experience=data["experience"], description=data["description"],
        status="open", is_published=True, opened_at=_today())
    db.add(job)
    db.flush()
    _ensure_form(db, client_id, job)
    return job


def edit(db, client_id, job_id, body):
    job = _job(db, client_id, job_id)
    data = _clean(body)
    job.title, job.location, job.experience, job.description = data["title"], data["location"], data["experience"], data["description"]
    form = _form(db, job)
    if form is not None:
        form.title = "Apply: %s" % job.title
    return job


def close(db, client_id, job_id):
    job = _job(db, client_id, job_id)
    job.status, job.is_published, job.closed_at = "closed", False, _today()
    return job


def reopen(db, client_id, job_id):
    job = _job(db, client_id, job_id)
    job.status, job.is_published, job.closed_at = "open", True, ""
    job.opened_at = job.opened_at or _today()
    if job.closing_date and _parse_date(job.closing_date) and _parse_date(job.closing_date) < datetime.now().date():
        job.closing_date = ""                       # reopened by hand: the old closing date no longer holds it shut
    _ensure_form(db, client_id, job)
    return job


def public_openings(db, client_id):
    """The openings the website's Careers section lists, each with the token its "Apply" link carries."""
    R = models.DBJobRequisition
    out = []
    for j in db.query(R).filter(R.client_id == client_id, R.status == "open", R.is_published.is_(True)).order_by(R.id.desc()).all():
        if not is_live(j):
            continue
        form = _form(db, j)
        out.append({"id": j.id, "title": j.title, "location": j.location or "", "experience": j.experience or "",
                    "description": j.description or "", "apply_token": form.form_token if form else None})
    return out
