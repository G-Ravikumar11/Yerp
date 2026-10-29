"""The safety endpoints."""
import base64
import io
import json
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.documents import form_pdf
from app import models
from app.db import get_db, get_read_db

from app.constants.common import (INCIDENT_KINDS, INJURY_KINDS, PERMIT_PRECAUTIONS, WORKER_MARITAL_STATUS,
                                  WORKER_MIN_AGE, WORKER_SEX, WORKER_TRADES)
from app.constants.quality import SERIOUS_KINDS
from app.core import checks
from app.core.auth import require_erp_read, wo_actor
from app.core.notifications import notify
from app.core.files import file_bytes
from app.core.serials import next_number
from app.core.sheets import sheet_response
from app.documents.forms import _field_doc, _job_line, _pre, form_pdf_response
from app.routers.equipment_checks import router as checks_router
from app.schemas.safety import IncidentCloseIn, IncidentIn, PermitCloseIn, PermitIn, TalkIn, WorkerIn
from app.services.projects import job_or_404
from app.services.safety import incident_dict, permit_dict


router = APIRouter()
router.include_router(checks_router)


@router.get("/api/safety")
def safety_overview(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    """Everything on the safety screen for one project, or every project."""
    client = require_erp_read(request, db)

    def scoped(model):
        q = db.query(model).filter(model.client_id == client.id)
        return q.filter(model.job_id == job_id) if job_id else q
    incidents = [incident_dict(i) for i in scoped(models.DBSafetyIncident).order_by(models.DBSafetyIncident.id.desc()).all()]
    talks = scoped(models.DBToolboxTalk).order_by(models.DBToolboxTalk.held_on.desc(), models.DBToolboxTalk.id.desc()).all()
    permits = [permit_dict(p) for p in scoped(models.DBWorkPermit).order_by(models.DBWorkPermit.id.desc()).all()]
    today = date.today()
    ltis = sorted([i["happened_on"] for i in incidents if i["kind"] in ("Lost time injury", "Fatality") and i["happened_on"]])
    try:
        since = (today - datetime.strptime(ltis[-1], "%Y-%m-%d").date()).days if ltis else None
    except ValueError:
        since = None
    month = today.strftime("%Y-%m")
    week_ago = (today - timedelta(days=7)).isoformat()
    return {"incidents": incidents,
            "talks": [{"id": t.id, "job_id": t.job_id, "held_on": t.held_on, "topic": t.topic,
                       "conducted_by": t.conducted_by or "", "attendees": t.attendees or 0,
                       "attendee_names": t.attendee_names or "", "minutes": t.minutes or 0,
                       "notes": t.notes or ""} for t in talks],
            "permits": permits, "kinds": list(INCIDENT_KINDS), "permit_kinds": PERMIT_PRECAUTIONS,
            "summary": {"days_without_lti": since,
                        "incidents_this_month": len([i for i in incidents if (i["happened_on"] or "")[:7] == month]),
                        "near_misses": len([i for i in incidents if i["kind"] == "Near miss"]),
                        "open": len([i for i in incidents if i["status"] == "OPEN"]),
                        "talks_this_week": len([t for t in talks if (t.held_on or "") >= week_ago]),
                        "active_permits": len([p for p in permits if p["status"] == "ACTIVE" and not p["expired"]]),
                        "expired_open": len([p for p in permits if p["expired"]])}}


@router.get("/api/safety/hse-check")
def hse_check(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    """The site held against the company's HSE plan, from what is already recorded: each line ok, a warning, or a
    problem, with the count behind it and where in the app to put it right."""
    client = require_erp_read(request, db)

    def scoped(model):
        q = db.query(model).filter(model.client_id == client.id)
        return q.filter(model.job_id == job_id) if job_id else q
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    workers = scoped(models.DBWorkerScreening).all()
    medical_ids = {f.attached_id for f in db.query(models.DBFile.attached_id).filter(
        models.DBFile.client_id == client.id, models.DBFile.attached_type == "worker",
        models.DBFile.caption == "Medical certificate",
        models.DBFile.attached_id.in_([w.id for w in workers] or [0])).all()}
    incidents = [incident_dict(i) for i in scoped(models.DBSafetyIncident).all()]
    permits = [permit_dict(p) for p in scoped(models.DBWorkPermit).all()]
    talks = scoped(models.DBToolboxTalk).filter(models.DBToolboxTalk.held_on >= week_ago).count()

    unbriefed = [w for w in workers if not w.trial_briefed]
    no_medical = [w for w in workers if w.id not in medical_ids]
    open_inc = [i for i in incidents if i["status"] == "OPEN"]
    serious_open = [i for i in open_inc if i["serious"]]
    expired = [p for p in permits if p["expired"]]
    # Section 8.1: more than 3 days off is notified at once; anything worse needs a written report within 7 days.
    reportable = [i for i in open_inc if (i["lost_days"] or 0) > 3 or i["serious"]]
    overdue = []
    for i in reportable:
        try:
            if (today - datetime.strptime(i["happened_on"], "%Y-%m-%d").date()).days > 7:
                overdue.append(i)
        except ValueError:
            pass

    def names(rows):
        shown = ", ".join(w.name or w.number for w in rows[:4])
        return shown + (" and %d more" % (len(rows) - 4) if len(rows) > 4 else "")

    items = [
        {"key": "screened", "rule": "5.1.1", "label": "Workers screened before they start",
         "status": "ok" if workers else "info", "count": len(workers),
         "detail": "%d screened." % len(workers) if workers else "Nobody screened on this site yet.", "go": "workers"},
        {"key": "briefed", "rule": "5.1.1", "label": "Every worker briefed on the site's EHS rules",
         "status": "bad" if unbriefed else "ok", "count": len(unbriefed),
         "detail": ("Not briefed yet: %s." % names(unbriefed)) if unbriefed else "Everyone screened has been briefed.",
         "go": "workers"},
        {"key": "medical", "rule": "5.5", "label": "Medical certificate on file",
         "status": "warn" if no_medical else "ok", "count": len(no_medical),
         "detail": ("Missing for: %s." % names(no_medical)) if no_medical else "Every worker has one.", "go": "workers"},
        {"key": "talk", "rule": "5.1.2", "label": "Toolbox talk in the last 7 days",
         "status": "ok" if talks else "warn", "count": talks,
         "detail": "%d held this week." % talks if talks else "None recorded this week.", "go": "talks"},
        {"key": "permits", "rule": "5.4", "label": "No permit left open past its end time",
         "status": "bad" if expired else "ok", "count": len(expired),
         "detail": ("Close or renew: %s." % ", ".join(p["number"] for p in expired[:6])) if expired else "No permit has run out while still open.",
         "go": "permits"},
        {"key": "incidents", "rule": "8", "label": "Incidents investigated and closed",
         "status": "bad" if serious_open else ("warn" if open_inc else "ok"), "count": len(open_inc),
         "detail": ("%d open, %d of them serious." % (len(open_inc), len(serious_open))) if open_inc else "Nothing open.",
         "go": "incidents"},
        {"key": "reported", "rule": "8.1", "label": "Serious injuries reported in writing within 7 days",
         "status": "bad" if overdue else ("warn" if reportable else "ok"), "count": len(reportable),
         "detail": ("Past 7 days: %s." % ", ".join(i["number"] for i in overdue)) if overdue else
                   ("%d must be reported within 7 days of happening." % len(reportable) if reportable else "Nothing to report."),
         "go": "incidents"},
    ]
    scored = [x for x in items if x["status"] != "info"]
    return {"items": items, "ok": len([x for x in scored if x["status"] == "ok"]), "total": len(scored)}


@router.post("/api/safety/incidents")
def report_incident(body: IncidentIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, body.job_id)
    if body.kind not in INCIDENT_KINDS:
        raise HTTPException(400, "What kind: " + ", ".join(INCIDENT_KINDS))
    if not (body.description or "").strip():
        raise HTTPException(400, "Say what happened.")
    if body.kind in INJURY_KINDS and not (body.injured_name or "").strip():
        raise HTTPException(400, "Who was hurt?")
    happened_on = checks.day(body.happened_on, "date it happened", not_future=True, default_today=True)
    happened_at = checks.clock(body.happened_at, "time it happened")
    checks.between(body.lost_days, "days lost", 0, 365, unit="days")
    i = models.DBSafetyIncident(
        client_id=client.id, job_id=job.id, number=next_number(db, models.DBSafetyIncident, client.id, "INC"),
        happened_on=happened_on, happened_at=happened_at,
        kind=body.kind, location=(body.location or "").strip(), description=body.description.strip(),
        injured_name=(body.injured_name or "").strip(), injury=(body.injury or "").strip(),
        treatment=(body.treatment or "").strip(), lost_days=max(0.0, float(body.lost_days or 0)),
        immediate_action=(body.immediate_action or "").strip(), root_cause=(body.root_cause or "").strip(),
        corrective_action=(body.corrective_action or "").strip(), reported_by=actor_name)
    db.add(i)
    db.commit()
    notify(db, client.id, "safety_incident", "%s on %s: %s" % (i.kind, job.name, i.number),
           i.description[:300], view="safety-view", ref_type="incident", ref_id=i.id,
           severity="wrong" if i.kind in SERIOUS_KINDS else "action")
    return {"incident": incident_dict(i)}


@router.post("/api/safety/incidents/{iid}/close")
def close_incident(iid: int, body: IncidentCloseIn, request: Request, db: Session = Depends(get_db)):
    """Closed only with why it happened and what stops it happening again."""
    client, _, _ = wo_actor(request, db, "site.signoff")
    i = db.query(models.DBSafetyIncident).filter(models.DBSafetyIncident.id == iid,
                                                 models.DBSafetyIncident.client_id == client.id).first()
    if not i:
        raise HTTPException(404, "Incident not found")
    if i.status == "CLOSED":
        raise HTTPException(409, "%s is already closed." % i.number)
    i.root_cause = (body.root_cause or "").strip() or i.root_cause
    i.corrective_action = (body.corrective_action or "").strip() or i.corrective_action
    if not (i.root_cause and i.corrective_action):
        raise HTTPException(400, "Close it with why it happened and what stops it happening again.")
    i.status, i.closed_on, i.closure_note = "CLOSED", date.today().isoformat(), (body.closure_note or "").strip()
    db.commit()
    return {"incident": incident_dict(i)}


@router.post("/api/safety/talks")
def record_talk(body: TalkIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, body.job_id)
    if not (body.topic or "").strip():
        raise HTTPException(400, "What was the talk about?")
    names = [n.strip() for n in re.split(r"[,\n]+", body.attendee_names or "") if n.strip()]
    checks.between(body.attendees, "number who attended", 0, 2000)
    checks.between(body.minutes, "minutes the talk lasted", 0, 600, unit="minutes")
    count = max(int(body.attendees or 0), len(names))
    if count < 1:
        raise HTTPException(400, "How many stood through it?")
    held_on = checks.day(body.held_on, "date of the talk", not_future=True, default_today=True)
    t = models.DBToolboxTalk(client_id=client.id, job_id=job.id, held_on=held_on,
                             topic=body.topic.strip(), conducted_by=actor_name, attendees=count,
                             attendee_names=", ".join(names), minutes=max(1, int(body.minutes or 15)),
                             notes=(body.notes or "").strip())
    db.add(t)
    db.commit()
    return {"ok": True, "id": t.id}


@router.post("/api/safety/permits")
def issue_permit(body: PermitIn, request: Request, db: Session = Depends(get_db)):
    """Issued only with every precaution for that kind of work ticked, and
    for one shift at most."""
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    job = job_or_404(db, client.id, body.job_id)
    if body.kind not in PERMIT_PRECAUTIONS:
        raise HTTPException(400, "Which permit: " + ", ".join(PERMIT_PRECAUTIONS))
    start = (body.valid_from or datetime.now().strftime("%Y-%m-%d %H:%M")).replace("T", " ")[:16]
    end = (body.valid_to or "").replace("T", " ")[:16]
    try:
        a, b = datetime.strptime(start, "%Y-%m-%d %H:%M"), datetime.strptime(end, "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(400, "When it runs from and to, as date and time.")
    if b <= a or b - a > timedelta(hours=12):
        raise HTTPException(400, "A permit runs for one shift at most - twelve hours - and ends after it starts.")
    given = {(x.get("item") if isinstance(x, dict) else str(x)): bool(x.get("done")) if isinstance(x, dict) else True
             for x in (body.precautions or [])}
    missing = [p for p in PERMIT_PRECAUTIONS[body.kind] if not given.get(p)]
    if missing:
        raise HTTPException(409, "Not issued - still to be in place: %s." % "; ".join(missing))
    if not (body.receiver or "").strip():
        raise HTTPException(400, "Who is doing the work?")
    p = models.DBWorkPermit(client_id=client.id, job_id=job.id, number=next_number(db, models.DBWorkPermit, client.id, "PTW"),
                            kind=body.kind, location=(body.location or "").strip(), description=(body.description or "").strip(),
                            valid_from=start, valid_to=end, issued_by=actor_name, receiver=body.receiver.strip(),
                            precautions=json.dumps([{"item": x, "done": True} for x in PERMIT_PRECAUTIONS[body.kind]]))
    db.add(p)
    db.commit()
    return {"permit": permit_dict(p)}


@router.post("/api/safety/permits/{pid}/close")
def close_permit(pid: int, body: PermitCloseIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    p = db.query(models.DBWorkPermit).filter(models.DBWorkPermit.id == pid,
                                             models.DBWorkPermit.client_id == client.id).first()
    if not p:
        raise HTTPException(404, "Permit not found")
    if p.status != "ACTIVE":
        raise HTTPException(409, "%s is already %s." % (p.number, p.status.lower()))
    p.status = "CANCELLED" if body.cancel else "CLOSED"
    p.closed_at, p.closed_by = datetime.now().strftime("%Y-%m-%d %H:%M"), actor_name
    p.closure_note = (body.note or "").strip()
    db.commit()
    return {"permit": permit_dict(p)}


@router.get("/api/safety/incidents.xlsx")
def incidents_export(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    d = safety_overview(request, job_id, db)
    rows = [(i["number"], i["happened_on"], i["kind"], i["location"], i["description"], i["injured_name"], i["injury"],
             i["lost_days"], i["root_cause"], i["corrective_action"], i["status"]) for i in d["incidents"]]
    return sheet_response(("No.", "Date", "Kind", "Where", "What happened", "Hurt", "Injury", "Days lost", "Root cause",
                           "Corrective action", "Status"), rows, "incidents.xlsx",
                          preamble=_pre(client, "INCIDENT REGISTER"))


@router.get("/api/safety/permits.xlsx")
def permits_export(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    d = safety_overview(request, job_id, db)
    rows = [(p["number"], p["kind"], p["location"], p["valid_from"], p["valid_to"], p["receiver"],
             p.get("issued_by", ""), "RUN OUT" if p.get("expired") else p["status"]) for p in d["permits"]]
    return sheet_response(("Permit", "Kind", "Where", "From", "Until", "Worker", "Issued by", "Status"), rows,
                          "permits.xlsx", preamble=_pre(client, "PERMIT TO WORK REGISTER"))


@router.get("/api/safety/talks.xlsx")
def talks_export(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    d = safety_overview(request, job_id, db)
    rows = [(t["held_on"], t["topic"], t["conducted_by"], t["attendees"], t.get("attendee_names", ""))
            for t in d["talks"]]
    return sheet_response(("Date", "Topic", "Conducted by", "Attended", "Names"), rows, "toolbox_talks.xlsx",
                          preamble=_pre(client, "TOOLBOX TALKS"))


@router.get("/api/safety/permits/{pid}/document.pdf")
def permit_pdf(pid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    p = db.query(models.DBWorkPermit).filter(models.DBWorkPermit.id == pid, models.DBWorkPermit.client_id == client.id).first()
    if not p:
        raise HTTPException(404, "Permit not found")
    d = permit_dict(p)
    project, site = _job_line(db, p.job_id)
    blocks = [
        {"type": "pairs", "cols": 2, "rows": [("Project", project), ("Location", d["location"]),
                                              ("Work", d["description"] or "-"), ("Worker", d["receiver"]),
                                              ("Valid from", d["valid_from"]), ("Valid until", d["valid_to"])]},
        {"type": "band", "text": "PRECAUTIONS IN PLACE BEFORE WORK STARTS"},
        {"type": "table", "columns": [("#", 6, "C"), ("Precaution", 140, "L"), ("Done", 20, "C")],
         "rows": [[str(i), x.get("item", ""), "YES" if x.get("done") else "NO"]
                  for i, x in enumerate(d.get("precautions") or [], 1)]},
        {"type": "text", "style": "small", "text": "This permit is valid only for the work, place and hours stated. "
                                                   "It is to be displayed at the work point and returned for closing when "
                                                   "the work stops or the time runs out, whichever is first."},
        {"type": "pairs", "rows": [("Closed", ("%s by %s - %s" % (d["closed_at"], d["closed_by"], d["closure_note"]))
                                    if d["status"] != "ACTIVE" else "Open")], "label_width": 30},
    ]
    sig = [("Issued By", d["issued_by"]), ("Received By (Worker)", d["receiver"]), ("Safety Officer", ""),
           ("Closed By", d["closed_by"] or "")]
    wm = "RUN OUT - CLOSE THIS PERMIT" if d.get("expired") else ("CLOSED" if d["status"] == "CLOSED" else "")
    return form_pdf_response(_field_doc(db, client, "PERMIT TO WORK",
                                        [("Permit No", d["number"]), ("Kind", d["kind"]), ("Status", d["status"])],
                                        blocks, sig, d["number"], wm), d["number"])


@router.get("/api/safety/incidents/{iid}/document.pdf")
def incident_pdf(iid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    i = db.query(models.DBSafetyIncident).filter(models.DBSafetyIncident.id == iid,
                                                 models.DBSafetyIncident.client_id == client.id).first()
    if not i:
        raise HTTPException(404, "Incident not found")
    d = incident_dict(i)
    project, site = _job_line(db, i.job_id)
    blocks = [
        {"type": "pairs", "cols": 2, "rows": [("Project", project), ("Where", d["location"] or "-"),
                                              ("Date", form_pdf.date_text(d["happened_on"])), ("Time", d["happened_at"] or "-"),
                                              ("Reported by", d["reported_by"] or "-"), ("Serious", "YES" if d["serious"] else "No")]},
        {"type": "band", "text": "WHAT HAPPENED"},
        {"type": "text", "text": d["description"] or "-"},
        {"type": "pairs", "rows": [("Person hurt", d["injured_name"] or "None"), ("Injury", d["injury"] or "-"),
                                   ("Treatment", d["treatment"] or "-"), ("Days lost", str(d["lost_days"] or 0)),
                                   ("Done straight away", d["immediate_action"] or "-")], "label_width": 42},
        {"type": "band", "text": "INVESTIGATION"},
        {"type": "pairs", "rows": [("Root cause", d["root_cause"] or "To be found"),
                                   ("Corrective action", d["corrective_action"] or "To be decided"),
                                   ("Closed on", form_pdf.date_text(d["closed_on"]) or "Open")], "label_width": 42},
    ]
    sig = [("Reported By", d["reported_by"] or ""), ("Site Engineer", ""), ("Safety Officer", ""), ("Project Manager", "")]
    return form_pdf_response(_field_doc(db, client, "INCIDENT REPORT",
                                        [("Report No", d["number"]), ("Kind", d["kind"]), ("Status", d["status"])],
                                        blocks, sig, d["number"]), d["number"])


# ---- Workers: screened before they start on site -------------------------------------------------------------------

def _rows(text):
    try:
        got = json.loads(text or "[]")
        return got if isinstance(got, list) else []
    except (TypeError, ValueError):
        return []


# Files on a worker that are papers, not the face: never picked as the photo.
WORKER_PAPERS = ("Medical certificate", "PAN card", "Aadhaar card")
_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_SIGNATURE = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")


def _mask_aadhaar(a):
    return "XXXX XXXX %s" % a[-4:] if a else ""


def _worker_photo(mine):
    return next((f for f in mine if (f.caption or "") == "Photo"), None) or next(
        (f for f in mine if (f.content_type or "").startswith("image/") and (f.caption or "") not in WORKER_PAPERS), None)


def _file_url(f, thumb=False):
    """A file's address with when it was uploaded on it. A browser keeps a picture for a day by its address, and a
    database that hands a deleted file's number to the next one would otherwise show the old picture in its place."""
    stamp = re.sub(r"\D", "", getattr(f, "created_at", "") or "")
    return "/api/files/%d%s%s" % (f.id, "/thumb" if thumb else "", "?v=" + stamp if stamp else "")


def _worker_dict(w, files):
    mine = [f for f in files if f.attached_id == w.id]
    photo = _worker_photo(mine)
    papers = lambda caption: [{"id": f.id, "name": f.name or "", "url": _file_url(f), "thumb_url": _file_url(f, True),
                               "image": (f.content_type or "").startswith("image/")}
                              for f in mine if (f.caption or "") == caption]
    medical = [f for f in mine if (f.caption or "") == "Medical certificate"]
    return {"id": w.id, "job_id": w.job_id, "number": w.number or "", "name": w.name or "", "age": w.age or 0,
            "address": w.address or "", "trade": w.trade or "", "screened_on": w.screened_on or "",
            "screened_by": w.screened_by or "",
            "contractor_name": w.contractor_name or "", "father_name": w.father_name or "", "dob": w.dob or "",
            "sex": w.sex or "", "marital_status": w.marital_status or "", "children": w.children or 0,
            "mother_tongue": w.mother_tongue or "", "other_languages": w.other_languages or "",
            "emergency_contact": w.emergency_contact or "", "phone": w.phone or "", "identification_mark": w.identification_mark or "",
            "vision_normal": w.vision_normal if w.vision_normal is not None else True,
            "vision_problem": w.vision_problem or "",
            "health_normal": w.health_normal if w.health_normal is not None else True,
            "health_problem": w.health_problem or "",
            "weight_kg": w.weight_kg or 0, "height_cm": w.height_cm or 0, "blood_group": w.blood_group or "",
            "education": _rows(w.education), "experience": _rows(w.experience),
            "certificates_verified": bool(w.certificates_verified), "trial_briefed": bool(w.trial_briefed),
            "safety_officer_name": w.safety_officer_name or "",
            # Aadhaar is never sent whole: the last four digits are enough to tell two cards apart.
            "pan": w.pan or "", "aadhaar_masked": _mask_aadhaar(w.aadhaar or ""),
            "pan_card": papers("PAN card"), "aadhaar_card": papers("Aadhaar card"),
            # The picture is fetched on its own: a list of a few hundred workers should not carry every signature.
            "signed_at": w.signed_at or "" if w.signature else "",
            "signature_url": ("/api/workers/%d/signature.png?v=%s" % (w.id, re.sub(r"\D", "", w.signed_at or "")))
                             if w.signature else "",
            "photo_url": _file_url(photo, True) if photo else "",
            "photo_full_url": _file_url(photo) if photo else "",
            "medical": [{"id": f.id, "name": f.name or "", "url": _file_url(f)} for f in medical]}


@router.get("/api/workers")
def worker_list(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    """Every worker screened for one project, or every project: in the order they were screened."""
    client = require_erp_read(request, db)
    q = db.query(models.DBWorkerScreening).filter(models.DBWorkerScreening.client_id == client.id)
    if job_id:
        q = q.filter(models.DBWorkerScreening.job_id == job_id)
    rows = q.order_by(models.DBWorkerScreening.id.asc()).all()
    files = db.query(models.DBFile.id, models.DBFile.attached_id, models.DBFile.caption, models.DBFile.name,
                     models.DBFile.content_type, models.DBFile.created_at).filter(
        models.DBFile.client_id == client.id, models.DBFile.attached_type == "worker",
        models.DBFile.attached_id.in_([w.id for w in rows] or [0])).order_by(models.DBFile.id.desc()).all()
    workers = [_worker_dict(w, files) for w in rows]
    by_trade = {t: 0 for t in WORKER_TRADES}
    for w in workers:
        by_trade[w["trade"]] = by_trade.get(w["trade"], 0) + 1
    return {"workers": workers, "trades": list(WORKER_TRADES), "min_age": WORKER_MIN_AGE,
            "sexes": list(WORKER_SEX), "marital_statuses": list(WORKER_MARITAL_STATUS),
            "summary": {"workers": len(workers), "by_trade": by_trade,
                        "without_medical": len([w for w in workers if not w["medical"]]),
                        "without_photo": len([w for w in workers if not w["photo_url"]])}}


def _edu_rows(rows):
    out = []
    for r in (rows or [])[:20]:
        if not isinstance(r, dict):
            continue
        exam, school = (r.get("exam") or "").strip()[:120], (r.get("school") or "").strip()[:160]
        if not exam and not school:
            continue
        out.append({"exam": exam, "year": (r.get("year") or "").strip()[:10], "school": school})
    return out


def _exp_rows(rows):
    out = []
    for r in (rows or [])[:20]:
        if not isinstance(r, dict):
            continue
        org, site = (r.get("organization") or "").strip()[:160], (r.get("project_site") or "").strip()[:160]
        if not org and not site:
            continue
        out.append({"organization": org, "project_site": site,
                    "category": (r.get("category") or "").strip()[:80], "period": (r.get("period") or "").strip()[:80],
                    "salary": (r.get("salary") or "").strip()[:40]})
    return out


@router.post("/api/workers")
def worker_screen(body: WorkerIn, request: Request, db: Session = Depends(get_db)):
    """Screen a worker, after the company's own paper form: who they are, their trade, their physical and
    education details, previous work, and whether they have been briefed. The photo and the medical certificate
    follow as files."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, body.job_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "The worker's name.")
    if body.trade not in WORKER_TRADES:
        raise HTTPException(400, "Trade: " + ", ".join(WORKER_TRADES))
    if not body.age or body.age < WORKER_MIN_AGE:
        raise HTTPException(400, "A worker on site must be at least %d." % WORKER_MIN_AGE)
    if body.age > 75:
        raise HTTPException(400, "Check the age: %d is past working age on a site." % body.age)
    screened_on = checks.day(body.screened_on, "date screened", not_future=True, default_today=True)
    checks.between(body.weight_kg or None, "weight", 25, 250, unit="kg")        # 0 is how the form says "not given"
    checks.between(body.height_cm or None, "height", 100, 230, unit="cm")
    if body.sex and body.sex not in WORKER_SEX:
        raise HTTPException(400, "Sex: " + ", ".join(WORKER_SEX))
    if body.marital_status and body.marital_status not in WORKER_MARITAL_STATUS:
        raise HTTPException(400, "Marital status: " + ", ".join(WORKER_MARITAL_STATUS))
    pan = re.sub(r"\s", "", body.pan or "").upper()
    aadhaar = re.sub(r"[\s-]", "", body.aadhaar or "")
    # A mobile as people write it - "+91 98765 43210", "098765-43210" - kept as its ten digits.
    phone = re.sub(r"^(\+?91|0)(?=\d{10}$)", "", re.sub(r"[\s()-]", "", body.phone or ""))
    if phone and not re.fullmatch(r"[6-9]\d{9}", phone):
        raise HTTPException(400, "The contact number is a 10-digit mobile number, starting with 6, 7, 8 or 9.")
    if pan and not _PAN.match(pan):
        raise HTTPException(400, "The PAN is 5 letters, 4 digits and a letter, like ABCDE1234F.")
    if aadhaar and not re.fullmatch(r"[2-9]\d{11}", aadhaar):
        raise HTTPException(400, "The Aadhaar number is 12 digits and does not start with 0 or 1.")
    signature = (body.signature or "").strip()
    if signature and (not _SIGNATURE.match(signature) or len(signature) > 400_000):
        raise HTTPException(400, "The signature did not come through as a picture. Upload it again.")
    # The same person screened twice on one site is a double count on the diary and the muster.
    for field, value, what in (("aadhaar", aadhaar, "Aadhaar"), ("pan", pan, "PAN")):
        if not value:
            continue
        twin = db.query(models.DBWorkerScreening).filter(
            models.DBWorkerScreening.client_id == client.id, models.DBWorkerScreening.job_id == job.id,
            getattr(models.DBWorkerScreening, field) == value).first()
        if twin:
            raise HTTPException(409, "This %s is already screened on this site: %s, %s." % (what, twin.number, twin.name))
    w = models.DBWorkerScreening(
        client_id=client.id, job_id=job.id, number=next_number(db, models.DBWorkerScreening, client.id, "WKR"),
        name=name[:120], age=int(body.age), address=(body.address or "").strip()[:500], trade=body.trade,
        screened_on=screened_on, screened_by=actor_name,
        contractor_name=(body.contractor_name or "").strip()[:160], father_name=(body.father_name or "").strip()[:120],
        dob=(body.dob or "")[:10], sex=body.sex or "", marital_status=body.marital_status or "",
        children=max(0, int(body.children or 0)), mother_tongue=(body.mother_tongue or "").strip()[:60],
        other_languages=(body.other_languages or "").strip()[:160],
        emergency_contact=(body.emergency_contact or "").strip()[:160], phone=phone,
        identification_mark=(body.identification_mark or "").strip()[:200],
        vision_normal=body.vision_normal if body.vision_normal is not None else True,
        vision_problem=(body.vision_problem or "").strip()[:200] if not body.vision_normal else "",
        health_normal=body.health_normal if body.health_normal is not None else True,
        health_problem=(body.health_problem or "").strip()[:200] if not body.health_normal else "",
        weight_kg=max(0.0, float(body.weight_kg or 0)), height_cm=max(0.0, float(body.height_cm or 0)),
        blood_group=(body.blood_group or "").strip()[:10],
        education=json.dumps(_edu_rows(body.education)), experience=json.dumps(_exp_rows(body.experience)),
        certificates_verified=bool(body.certificates_verified), trial_briefed=bool(body.trial_briefed),
        safety_officer_name=(body.safety_officer_name or "").strip()[:120], pan=pan, aadhaar=aadhaar,
        signature=signature, signed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S") if signature else "")
    db.add(w)
    db.commit()
    return {"worker": _worker_dict(w, [])}


def _photo_data_uri(db, f):
    """The worker's photo, carried inside the PDF: the small copy is plenty for a 32 mm box."""
    if not f:
        return ""
    raw = file_bytes(db, f, thumb=True) or file_bytes(db, f)
    if not raw:
        return ""
    media = "image/jpeg" if f.thumb or (f.content_type or "") == "image/jpeg" else (f.content_type or "image/jpeg")
    return "data:%s;base64,%s" % (media, base64.b64encode(raw).decode("ascii"))


@router.get("/api/workers/{wid}/document.pdf")
def worker_pdf(wid: int, request: Request, db: Session = Depends(get_read_db)):
    """The worker's screening, filled in on the company's "Screening Of Worker" form, ready to print and sign."""
    client = require_erp_read(request, db)
    w = db.query(models.DBWorkerScreening).filter(models.DBWorkerScreening.id == wid,
                                                  models.DBWorkerScreening.client_id == client.id).first()
    if not w:
        raise HTTPException(404, "Worker not found")
    files = db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "worker",
                                           models.DBFile.attached_id == w.id).order_by(models.DBFile.id.desc()).all()
    d = _worker_dict(w, files)
    photo = _worker_photo(files)
    project, _ = _job_line(db, w.job_id)
    when = form_pdf.date_text
    dash = lambda v: str(v) if v not in (None, "", 0) else "-"  # noqa: E731
    person = [("Name of the Contractor / Sub-Contractor", dash(d["contractor_name"])),
              ("Full name of the workman", dash(d["name"])),
              ("Father / Husband's name", dash(d["father_name"])),
              ("Permanent address", dash(d["address"])),
              ("Date of birth", when(d["dob"]) or "-"), ("Sex", dash(d["sex"])), ("Age", "%s years" % d["age"] if d["age"] else "-"),
              ("Marital status", dash(d["marital_status"])), ("Number of children", str(d["children"] or 0)),
              ("Mother tongue", dash(d["mother_tongue"])), ("Other languages known", dash(d["other_languages"])),
              ("Contact number", dash(d["phone"])),
              ("In case of emergency, contact", dash(d["emergency_contact"])),
              ("Any other identification mark", dash(d["identification_mark"])),
              ("PAN", dash(d["pan"])), ("Aadhaar", dash(d["aadhaar_masked"]))]
    health = [("Vision", "Normal" if d["vision_normal"] else "Not normal: %s" % (d["vision_problem"] or "-")),
              ("Health", "Normal" if d["health_normal"] else "Not normal: %s" % (d["health_problem"] or "-")),
              ("Weight", "%g kg" % d["weight_kg"] if d["weight_kg"] else "-"),
              ("Height", "%g cm" % d["height_cm"] if d["height_cm"] else "-"),
              ("Blood group", dash(d["blood_group"])), ("Medical certificate", "On file" if d["medical"] else "Not given")]
    education = [[r["exam"], r["year"], r["school"]] for r in d["education"]] or [["", "", ""], ["", "", ""]]
    experience = [[str(i), r["organization"], r["project_site"], r["category"], r["period"], r["salary"]]
                  for i, r in enumerate(d["experience"], 1)] or [["", "", "", "", "", ""], ["", "", "", "", "", ""]]
    blocks = [
        {"type": "pairs", "label_width": 52, "photo": _photo_data_uri(db, photo), "rows": person},
        {"type": "band", "text": "HEALTH"},
        {"type": "pairs", "cols": 2, "rows": health},
        {"type": "band", "text": "EDUCATION DETAILS"},
        {"type": "table", "columns": [("Examination passed", 50, "L"), ("Year", 20, "C"), ("School / Board", 80, "L")],
         "rows": education},
        {"type": "band", "text": "PREVIOUS WORK EXPERIENCE"},
        {"type": "table", "columns": [("Sl. No.", 12, "C"), ("Organization name", 38, "L"), ("Project site", 32, "L"),
                                      ("Category", 24, "L"), ("Period", 22, "L"), ("Salary / Wage", 22, "R")],
         "rows": experience},
        {"type": "band", "text": "DECLARATION BY THE WORKER"},
        {"type": "text", "text": "The above information given by me is correct to the best of my knowledge."},
        {"type": "band", "text": "DECLARATION BY THE SUBCONTRACTOR / CONTRACTOR"},
        {"type": "text", "text": "We declare that this employee will be working for us on this site. He / She shall follow "
                                 "the entire site safety requirement. We take responsibility for his / her safety on the site."},
        {"type": "band", "text": "SCREENING"},
        {"type": "pairs", "label_width": 62, "rows": [
            ("Certificates / details", "Verified" if d["certificates_verified"] else "Not verified"),
            ("Suitable for employment as", dash(d["trade"])),
            ("Screened by", dash(d["screened_by"])),
            ("Trial report: seen and briefed the EHS rules of the site", "Yes" if d["trial_briefed"] else "No"),
            ("Safety officer", dash(d["safety_officer_name"]))]},
    ]
    sig = [("Signature / Left Hand Thumb impression of the worker", d["name"], w.signature or ""), ("Signature of the Contractor", d["contractor_name"]),
           ("Site in charge / Site Engineer", ""), ("Safety Officer", d["safety_officer_name"])]
    doc = _field_doc(db, client, "SCREENING OF WORKER",
                     [("Worker ID No", d["number"]), ("Date", when(d["screened_on"]) or "-"), ("Project", project or "-")],
                     blocks, sig, d["number"])
    return form_pdf_response(doc, "%s %s" % (d["number"], d["name"]))


@router.get("/api/workers/{wid}/signature.png")
def worker_signature(wid: int, request: Request, db: Session = Depends(get_read_db)):
    """The worker's signature, from the photo of it that was uploaded."""
    client = require_erp_read(request, db)
    w = db.query(models.DBWorkerScreening).filter(models.DBWorkerScreening.id == wid,
                                                  models.DBWorkerScreening.client_id == client.id).first()
    if not w or not w.signature:
        raise HTTPException(404, "No signature")
    raw = base64.b64decode(w.signature.partition(",")[2])
    return StreamingResponse(io.BytesIO(raw), media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/api/workers/{wid}")
def worker_remove(wid: int, request: Request, db: Session = Depends(get_db)):
    """Take a worker off the list, with their photo and certificate."""
    client, _, _ = wo_actor(request, db, "site.signoff")
    w = db.query(models.DBWorkerScreening).filter(models.DBWorkerScreening.id == wid,
                                                  models.DBWorkerScreening.client_id == client.id).first()
    if not w:
        raise HTTPException(404, "Worker not found")
    db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "worker",
                                   models.DBFile.attached_id == w.id).delete(synchronize_session=False)
    db.delete(w)
    db.commit()
    return {"message": "%s taken off the list." % (w.name or w.number)}
