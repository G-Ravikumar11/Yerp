"""The safety endpoints."""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.documents import form_pdf
from app import models
from app.db import get_db

from app.constants.common import INCIDENT_KINDS, PERMIT_PRECAUTIONS
from app.constants.quality import SERIOUS_KINDS
from app.core.auth import require_erp_read, wo_actor
from app.core.notifications import notify
from app.core.serials import next_number
from app.core.sheets import sheet_response
from app.documents.forms import _field_doc, _job_line, _pre, form_pdf_response
from app.schemas.safety import IncidentCloseIn, IncidentIn, PermitCloseIn, PermitIn, TalkIn
from app.services.projects import job_or_404
from app.services.safety import incident_dict, permit_dict


router = APIRouter()


@router.get("/api/safety")
def safety_overview(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
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


@router.post("/api/safety/incidents")
def report_incident(body: IncidentIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, body.job_id)
    if body.kind not in INCIDENT_KINDS:
        raise HTTPException(400, "What kind: " + ", ".join(INCIDENT_KINDS))
    if not (body.description or "").strip():
        raise HTTPException(400, "Say what happened.")
    if body.kind in ("First aid", "Medical treatment", "Lost time injury", "Fatality") and not (body.injured_name or "").strip():
        raise HTTPException(400, "Who was hurt?")
    i = models.DBSafetyIncident(
        client_id=client.id, job_id=job.id, number=next_number(db, models.DBSafetyIncident, client.id, "INC"),
        happened_on=(body.happened_on or date.today().isoformat())[:10], happened_at=(body.happened_at or "")[:5],
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
    count = max(int(body.attendees or 0), len(names))
    if count < 1:
        raise HTTPException(400, "How many stood through it?")
    t = models.DBToolboxTalk(client_id=client.id, job_id=job.id, held_on=(body.held_on or date.today().isoformat())[:10],
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
def incidents_export(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = safety_overview(request, job_id, db)
    rows = [(i["number"], i["happened_on"], i["kind"], i["location"], i["description"], i["injured_name"], i["injury"],
             i["lost_days"], i["root_cause"], i["corrective_action"], i["status"]) for i in d["incidents"]]
    return sheet_response(("No.", "Date", "Kind", "Where", "What happened", "Hurt", "Injury", "Days lost", "Root cause",
                           "Corrective action", "Status"), rows, "incidents.xlsx",
                          preamble=_pre(client, "INCIDENT REGISTER"))


@router.get("/api/safety/permits.xlsx")
def permits_export(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = safety_overview(request, job_id, db)
    rows = [(p["number"], p["kind"], p["location"], p["valid_from"], p["valid_to"], p["receiver"],
             p.get("issued_by", ""), "RUN OUT" if p.get("expired") else p["status"]) for p in d["permits"]]
    return sheet_response(("Permit", "Kind", "Where", "From", "Until", "Worker", "Issued by", "Status"), rows,
                          "permits.xlsx", preamble=_pre(client, "PERMIT TO WORK REGISTER"))


@router.get("/api/safety/talks.xlsx")
def talks_export(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = safety_overview(request, job_id, db)
    rows = [(t["held_on"], t["topic"], t["conducted_by"], t["attendees"], t.get("attendee_names", ""))
            for t in d["talks"]]
    return sheet_response(("Date", "Topic", "Conducted by", "Attended", "Names"), rows, "toolbox_talks.xlsx",
                          preamble=_pre(client, "TOOLBOX TALKS"))


@router.get("/api/safety/permits/{pid}/document.pdf")
def permit_pdf(pid: int, request: Request, db: Session = Depends(get_db)):
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
def incident_pdf(iid: int, request: Request, db: Session = Depends(get_db)):
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
