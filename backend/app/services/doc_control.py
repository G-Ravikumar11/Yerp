"""Document control: transmittals, RFIs and submittals - numbered, due, answered, and chased.

A transmittal sends drawings (at the revision they are at) and papers to a party, to be acknowledged. An RFI asks a
question that needs an answer. A submittal puts material or a shop drawing up for approval: approved, approved with
comments, or rejected (a rejected one is resubmitted as the next revision). Each has a due date: the party is emailed
a reminder the day before it and every few days once it is overdue, the person who raised it is told when it goes
overdue, and what is overdue is in "What needs you".
"""
from datetime import date, datetime

from fastapi import HTTPException

from app import models
from app.core.audit import log_audit
from app.core.config import logger
from app.core.notifications import default_from_email, notify, notify_employee, send_email_background
from app.core.scheduler import scheduled_job
from app.models.doc_control import DBDocControl, DBDocControlItem

KINDS = {"TRANSMITTAL": ("TR-", "Transmittal"), "RFI": ("RFI-", "RFI"), "SUBMITTAL": ("SUB-", "Submittal")}
# The replies each kind can get; any of them ends the wait.
REPLIES = {"TRANSMITTAL": ("ACKNOWLEDGED",), "RFI": ("ANSWERED",), "SUBMITTAL": ("APPROVED", "APPROVED_AS_NOTED", "REJECTED")}
DONE = ("CLOSED", "CANCELLED")
WAITING = ("OPEN",)
PURPOSES = ("For approval", "For information", "For construction", "For comments", "For tender")
OVERDUE_EVERY = 3                # days between reminders once overdue
MAX_REMINDERS = 6


def day(raw, what, required=False):
    raw = (raw or "").strip()[:10]
    if not raw:
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return ""
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "The %s is not a date (use YYYY-MM-DD)." % what) from None
    return raw


def next_number(db, client_id, kind):
    stem = KINDS[kind][0]
    top = 0
    for (n,) in db.query(DBDocControl.number).filter(DBDocControl.client_id == client_id, DBDocControl.kind == kind).all():
        tail = (n or "")[len(stem):]
        if tail.isdigit():
            top = max(top, int(tail))
    return "%s%04d" % (stem, top + 1)


def doc_or_404(db, client_id, doc_id):
    d = db.query(DBDocControl).filter(DBDocControl.id == doc_id, DBDocControl.client_id == client_id).first()
    if d is None:
        raise HTTPException(404, "Not found")
    return d


def overdue(d, today=None):
    return d.status in WAITING and bool(d.due_date) and d.due_date < (today or date.today()).isoformat()


def doc_dict(db, d, jobs=None, items=False):
    job = (jobs or {}).get(d.job_id) if jobs is not None else (db.get(models.DBJob, d.job_id) if d.job_id else None)
    out = {"id": d.id, "kind": d.kind, "kind_label": KINDS[d.kind][1], "number": d.number, "subject": d.subject or "",
           "job_id": d.job_id, "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
           "to_party": d.to_party or "", "to_email": d.to_email or "", "details": d.details or "", "purpose": d.purpose or "",
           "revision": d.revision or "", "due_date": d.due_date or "", "status": d.status, "response": d.response or "",
           "responded_on": d.responded_on or "", "responded_by": d.responded_by or "", "created_by_name": d.created_by_name or "",
           "created_at": d.created_at or "", "closed_at": d.closed_at or "", "reminders": d.reminders or 0,
           "reminded_on": d.reminded_on or "", "overdue": overdue(d), "replies": list(REPLIES[d.kind])}
    if items:
        rows = db.query(DBDocControlItem).filter(DBDocControlItem.doc_id == d.id).order_by(DBDocControlItem.id).all()
        drawings = {x.id: x for x in db.query(models.DBDrawing).filter(models.DBDrawing.id.in_({r.drawing_id for r in rows if r.drawing_id} or {0})).all()}
        out["items"] = [{"id": r.id, "drawing_id": r.drawing_id, "revision": r.revision or "",
                         "number": drawings[r.drawing_id].number if r.drawing_id in drawings else "",
                         "description": r.description or (drawings[r.drawing_id].title if r.drawing_id in drawings else "")} for r in rows]
    return out


def create(db, client, actor_id, actor_name, body, request=None):
    kind = (body.get("kind") or "").strip().upper()
    if kind not in KINDS:
        raise HTTPException(400, "One of: transmittal, RFI, submittal.")
    subject = (body.get("subject") or "").strip()[:200]
    if not subject:
        raise HTTPException(400, "Say what it is about.")
    to_party = (body.get("to_party") or "").strip()[:120]
    if not to_party:
        raise HTTPException(400, "Who is it to?")
    job_id = body.get("job_id") or None
    if job_id and not db.query(models.DBJob.id).filter(models.DBJob.id == job_id, models.DBJob.client_id == client.id).first():
        raise HTTPException(404, "Project not found")
    due = day(body.get("due_date"), "due date")
    if due and due < date.today().isoformat():
        raise HTTPException(400, "It cannot be due on a day that has gone.")
    if kind == "RFI" and not (body.get("details") or "").strip():
        raise HTTPException(400, "What is the question?")
    purpose = (body.get("purpose") or "").strip()
    if purpose and purpose not in PURPOSES:
        raise HTTPException(400, "Purpose: one of %s." % ", ".join(PURPOSES))
    d = DBDocControl(client_id=client.id, job_id=job_id, kind=kind, number=next_number(db, client.id, kind), subject=subject,
                     to_party=to_party, to_email=(body.get("to_email") or "").strip()[:120], details=(body.get("details") or "").strip(),
                     purpose=purpose, revision=(body.get("revision") or "").strip()[:20] or ("R0" if kind == "SUBMITTAL" else ""),
                     due_date=due, status="OPEN", created_by_id=actor_id, created_by_name=actor_name)
    db.add(d)
    db.flush()
    for it in (body.get("items") or [])[:100] if kind == "TRANSMITTAL" else []:
        did = it.get("drawing_id")
        drawing = None
        if did:
            drawing = db.query(models.DBDrawing).filter(models.DBDrawing.id == did, models.DBDrawing.client_id == client.id).first()
            if drawing is None:
                raise HTTPException(404, "That drawing is not on the register.")
        text = (it.get("description") or "").strip()[:300]
        if drawing is None and not text:
            continue
        # A drawing goes at the revision it is at now: the transmittal records what was sent, whatever comes later.
        db.add(DBDocControlItem(doc_id=d.id, drawing_id=drawing.id if drawing else None,
                                revision=(drawing.current_revision or "") if drawing else "", description=text))
    log_audit(db, client.id, "doc_control_raised", "doc_control", d.id, d.number, "%s to %s" % (subject, to_party), request)
    db.commit()
    return d


def respond(db, client, d, actor_name, reply, response, request=None):
    if d.status not in WAITING:
        raise HTTPException(409, "%s is %s already." % (d.number, d.status.replace("_", " ").lower()))
    reply = (reply or "").strip().upper()
    if reply not in REPLIES[d.kind]:
        raise HTTPException(400, "%s can be: %s." % (KINDS[d.kind][1], ", ".join(r.replace("_", " ").lower() for r in REPLIES[d.kind])))
    if d.kind == "RFI" and not (response or "").strip():
        raise HTTPException(400, "What was the answer?")
    if reply in ("APPROVED_AS_NOTED", "REJECTED") and not (response or "").strip():
        raise HTTPException(400, "Record the comments that came with it.")
    d.status, d.response = reply, (response or "").strip()
    d.responded_on, d.responded_by = date.today().isoformat(), actor_name
    log_audit(db, client.id, "doc_control_reply", "doc_control", d.id, d.number, reply.lower(), request)
    db.commit()
    return d


def resubmit(db, client, actor_id, actor_name, d, request=None):
    """A rejected submittal goes up again as its next revision: R0 -> R1."""
    if d.kind != "SUBMITTAL" or d.status != "REJECTED":
        raise HTTPException(409, "Only a rejected submittal is resubmitted.")
    rev = d.revision or "R0"
    head = rev.rstrip("0123456789")
    nxt = "%s%d" % (head or "R", int(rev[len(head):] or 0) + 1)
    n = DBDocControl(client_id=client.id, job_id=d.job_id, kind="SUBMITTAL", number=d.number, subject=d.subject, to_party=d.to_party,
                     to_email=d.to_email, details=d.details, purpose=d.purpose, revision=nxt, due_date="", status="OPEN",
                     created_by_id=actor_id, created_by_name=actor_name)
    d.status, d.closed_at = "CLOSED", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.add(n)
    db.flush()
    log_audit(db, client.id, "doc_control_resubmitted", "doc_control", n.id, n.number, "revision %s" % nxt, request)
    db.commit()
    return n


def remind(db, client, d, now=None):
    """Email the party a reminder. Returns (ok, message); nothing is raised."""
    if not (d.to_email or "").strip() or "@" not in d.to_email:
        return False, "no email for %s" % (d.to_party or "the party")
    company = client.company_name or "Our company"
    what = {"TRANSMITTAL": "please acknowledge receipt of", "RFI": "we are waiting for your answer to",
            "SUBMITTAL": "we are waiting for your decision on"}[d.kind]
    late = overdue(d, (now or datetime.now()).date())
    due = (" It was due on %s." % d.due_date) if d.due_date and late else (" It is due on %s." % d.due_date) if d.due_date else ""
    body = "Dear %s,\n\nA reminder from %s: %s %s %s%s.%s\n\n%s\n\nThank you." % (
        d.to_party, company, what, KINDS[d.kind][1], d.number, (" - " + d.subject) if d.subject else "", due, d.details or "")
    ok, why = send_email_background(d.to_email, "Reminder: %s %s - %s" % (KINDS[d.kind][1], d.number, d.subject)[:200], body,
                                    "%s <%s>" % (company, default_from_email()), client_id=client.id)
    if ok:
        d.reminded_on, d.reminders = (now or datetime.now()).strftime("%Y-%m-%d"), (d.reminders or 0) + 1
        log_audit(db, client.id, "doc_control_reminded", "doc_control", d.id, d.number, d.to_email)
    return ok, why


def due_for_a_reminder(d, today):
    """The day before it is due, and every OVERDUE_EVERY days once overdue - a few times at most, never twice a day."""
    if d.status not in WAITING or not d.due_date or (d.reminders or 0) >= MAX_REMINDERS or d.reminded_on == today.isoformat():
        return False
    try:
        due = datetime.strptime(d.due_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    left = (due - today).days
    if left == 1:
        return True
    return left < 0 and (-left) % OVERDUE_EVERY == 0


@scheduled_job("doc_control_reminders")
def job_doc_control_reminders(db, now):
    today = now.date()
    sent = told = 0
    for d in db.query(DBDocControl).filter(DBDocControl.status.in_(WAITING), DBDocControl.due_date != "").all():
        client = db.get(models.DBClient, d.client_id)
        if due_for_a_reminder(d, today):
            ok, _ = remind(db, client, d, now)
            sent += 1 if ok else 0
        if overdue(d, today) and not d.overdue_told:
            text = "%s %s to %s is overdue: it was due on %s." % (KINDS[d.kind][1], d.number, d.to_party, d.due_date)
            notify(db, d.client_id, "doc_control_overdue", text, view="documents-view", ref_type="doc_control", ref_id=d.id, severity="action")
            notify_employee(db, d.client_id, d.created_by_id, "Overdue: %s" % d.number, text, link="/next/projects/documents")
            d.overdue_told = 1
            told += 1
        db.commit()
    logger.info("doc control: %d reminders, %d overdue notices", sent, told)
    return "%d reminders, %d overdue notices" % (sent, told)


def attention_items(db, client_id, today=None):
    """What is overdue, by kind, for "What needs you"."""
    today = today or date.today()
    late = [d for d in db.query(DBDocControl).filter(DBDocControl.client_id == client_id, DBDocControl.status.in_(WAITING),
                                                     DBDocControl.due_date != "").all() if overdue(d, today)]
    if not late:
        return []
    by = {}
    for d in late:
        by.setdefault(KINDS[d.kind][1], []).append(d.number)
    detail = "; ".join("%d %s%s (%s)" % (len(v), k, "" if len(v) == 1 else "s", ", ".join(v[:3]) + (" ..." if len(v) > 3 else ""))
                       for k, v in by.items())
    return [{"kind": "doc_control_overdue", "severity": "action", "value": 0.0, "count": len(late), "view": "documents-view",
             "title": "Transmittals, RFIs and submittals overdue", "detail": detail + " past the due date with no reply."}]
