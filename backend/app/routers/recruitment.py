"""The recruitment endpoints."""
import json
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.recruitment import (
    INTERVIEW_MODES,
    INTERVIEW_OUTCOMES,
    INTERVIEW_STATUSES,
    MAX_DOCUMENTS_PER_APPLICATION,
    OFFER_STATUSES,
)
from app.core.audit import log_audit
from app.core.auth import get_client_user
from app.core.currency import esc, money
from app.core.dates import _parse_date
from app.core.files import MAX_DOCUMENT_BYTES
from app.core.notifications import default_from_email, send_email_background
from app.core.security import rate_limiter
from app.core.serials import next_sequence_number
from app.schemas.recruitment import (
    CandidateDocumentIn,
    CandidateEmailIn,
    FormSubmissionCreate,
    InterviewIn,
    JobRequisitionIn,
    OfferIn,
    RecruitmentFormCreate,
)
from app.services.hr import start_onboarding
from app.services.recruitment import (
    _get_submission_for_client,
    _parse_datetime_minutes,
    build_candidate_email,
    interview_to_dict,
    offer_to_dict,
    requisition_to_dict,
)
from app.services.wallet_ai import require_credit
from app.validators.common import validate_candidate_document, validate_email_address, validate_job_payload
from app.validators.hr import validate_level, validate_manager, validate_role


router = APIRouter()


@router.get("/api/recruitment/interviews/{interview_id}/reminders")
def interview_reminders(interview_id: int, request: Request,
                        db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    iv = db.query(models.DBInterview).filter(
        models.DBInterview.id == interview_id,
        models.DBInterview.client_id == client.id,
    ).first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")
    rows = db.query(models.DBInterviewReminder).filter(
        models.DBInterviewReminder.interview_id == iv.id).all()
    return [{"recipient": r.recipient, "sent_to": r.sent_to, "sent_at": r.sent_at}
            for r in rows]


@router.get("/api/recruitment/jobs")
def list_requisitions(request: Request, status: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBJobRequisition).filter(models.DBJobRequisition.client_id == client.id)
    if status:
        query = query.filter(models.DBJobRequisition.status == status)
    jobs = query.order_by(models.DBJobRequisition.id.desc()).all()

    # Applicant and hire counts per job, in two queries rather than per row.
    form_rows = db.query(models.DBRecruitmentForm.id, models.DBRecruitmentForm.job_id).filter(
        models.DBRecruitmentForm.client_id == client.id
    ).all()
    form_to_job = {fid: jid for fid, jid in form_rows if jid}
    applicants, hires = defaultdict(int), defaultdict(int)
    if form_to_job:
        subs = db.query(
            models.DBFormSubmission.form_id, models.DBFormSubmission.hired_employee_id
        ).filter(models.DBFormSubmission.form_id.in_(list(form_to_job.keys()))).all()
        for form_id, hired in subs:
            job_id = form_to_job.get(form_id)
            if not job_id:
                continue
            applicants[job_id] += 1
            if hired:
                hires[job_id] += 1
    return [requisition_to_dict(j, counts={
        "applicant_count": applicants.get(j.id, 0),
        "hired_count": hires.get(j.id, 0),
        "remaining_openings": max(0, (j.openings or 1) - hires.get(j.id, 0)),
    }) for j in jobs]


@router.post("/api/recruitment/jobs")
def create_requisition(request: Request, body: JobRequisitionIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    status, mode, openings, level = validate_job_payload(body, db, client.id)
    reference = next_sequence_number(db, models.DBJobRequisition, client.id, "JOB-", field="reference")
    now = datetime.now().strftime("%Y-%m-%d")
    job = models.DBJobRequisition(
        client_id=client.id, reference=reference, title=body.title.strip(),
        department_id=body.department_id, hiring_manager_id=body.hiring_manager_id,
        description=body.description or "", requirements=body.requirements or "",
        location=body.location or "", work_mode=mode,
        employment_type=body.employment_type or "full_time", level=level,
        salary_min=float(body.salary_min or 0), salary_max=float(body.salary_max or 0),
        salary_currency=client.currency or "", show_salary=bool(body.show_salary),
        openings=openings, status=status,
        is_published=(status == "open"),
        closing_date=body.closing_date or "",
        opened_at=now if status == "open" else "",
    )
    db.add(job)
    log_audit(db, client.id, "job_created", "job", None, f"{reference} {body.title}", "", request)
    db.commit()
    db.refresh(job)
    return requisition_to_dict(job)


@router.get("/api/recruitment/jobs/{job_id}")
def get_requisition(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    job = db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.id == job_id, models.DBJobRequisition.client_id == client.id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    forms = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.job_id == job_id
    ).all()
    data = requisition_to_dict(job)
    data["forms"] = [{
        "id": f.id, "title": f.title, "form_token": f.form_token, "is_active": f.is_active
    } for f in forms]
    return data


@router.put("/api/recruitment/jobs/{job_id}")
def update_requisition(job_id: int, request: Request, body: JobRequisitionIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    job = db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.id == job_id, models.DBJobRequisition.client_id == client.id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    status, mode, openings, level = validate_job_payload(body, db, client.id)
    now = datetime.now().strftime("%Y-%m-%d")
    if status == "open" and job.status != "open":
        job.opened_at = job.opened_at or now
        job.closed_at = ""
    if status in ("closed", "filled") and job.status not in ("closed", "filled"):
        job.closed_at = now
    job.title = body.title.strip()
    job.department_id = body.department_id
    job.hiring_manager_id = body.hiring_manager_id
    job.description = body.description or ""
    job.requirements = body.requirements or ""
    job.location = body.location or ""
    job.work_mode = mode
    job.employment_type = body.employment_type or "full_time"
    job.level = level
    job.salary_min = float(body.salary_min or 0)
    job.salary_max = float(body.salary_max or 0)
    job.show_salary = bool(body.show_salary)
    job.openings = openings
    job.status = status
    job.is_published = status == "open"
    job.closing_date = body.closing_date or ""
    log_audit(db, client.id, "job_updated", "job", job.id, job.reference, f"Status: {status}", request)
    db.commit()
    return requisition_to_dict(job)


@router.delete("/api/recruitment/jobs/{job_id}")
def delete_requisition(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    job = db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.id == job_id, models.DBJobRequisition.client_id == client.id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    linked = db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.job_id == job_id).count()
    if linked:
        raise HTTPException(
            status_code=409,
            detail=f"{linked} application form(s) are attached to this job. Detach or delete them first.",
        )
    log_audit(db, client.id, "job_deleted", "job", job.id, job.reference, "", request)
    db.delete(job)
    db.commit()
    return {"message": "Job deleted"}


@router.get("/api/recruitment/submissions/{sub_id}/interviews")
def list_interviews(sub_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    _get_submission_for_client(db, client.id, sub_id)
    rows = db.query(models.DBInterview).filter(
        models.DBInterview.submission_id == sub_id
    ).order_by(models.DBInterview.scheduled_at.asc()).all()
    return [interview_to_dict(r) for r in rows]


@router.post("/api/recruitment/submissions/{sub_id}/interviews")
def schedule_interview(sub_id: int, request: Request, body: InterviewIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = _get_submission_for_client(db, client.id, sub_id)

    when = _parse_datetime_minutes(body.scheduled_at)
    if not when:
        raise HTTPException(status_code=400, detail="Scheduled time must look like YYYY-MM-DD HH:MM")
    mode = (body.mode or "video").strip().lower()
    if mode not in INTERVIEW_MODES:
        raise HTTPException(status_code=400, detail=f"Mode must be one of: {', '.join(INTERVIEW_MODES)}")
    duration = int(body.duration_minutes or 45)
    if duration < 5 or duration > 480:
        raise HTTPException(status_code=400, detail="Duration must be between 5 and 480 minutes")

    interviewer_name = (body.interviewer_name or "").strip()
    if body.interviewer_id:
        emp = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == body.interviewer_id,
            models.DBEmployee.client_id == client.id,
        ).first()
        if not emp:
            raise HTTPException(status_code=400, detail="Interviewer not found")
        interviewer_name = interviewer_name or f"{emp.first_name} {emp.last_name}"
        # Warn on a clash rather than silently double-booking someone.
        window_start = (when - timedelta(minutes=duration)).strftime("%Y-%m-%d %H:%M")
        window_end = (when + timedelta(minutes=duration)).strftime("%Y-%m-%d %H:%M")
        clash = db.query(models.DBInterview).filter(
            models.DBInterview.client_id == client.id,
            models.DBInterview.interviewer_id == body.interviewer_id,
            models.DBInterview.status == "scheduled",
            models.DBInterview.scheduled_at > window_start,
            models.DBInterview.scheduled_at < window_end,
        ).first()
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"{interviewer_name} already has an interview at {clash.scheduled_at}",
            )

    iv = models.DBInterview(
        client_id=client.id, submission_id=sub_id,
        round_name=body.round_name or "Interview",
        scheduled_at=when.strftime("%Y-%m-%d %H:%M"),
        duration_minutes=duration, mode=mode,
        location=body.location or "", meeting_link=body.meeting_link or "",
        interviewer_id=body.interviewer_id, interviewer_name=interviewer_name,
    )
    db.add(iv)
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub_id,
        from_stage=sub.current_stage or "", to_stage=sub.current_stage or "",
        actor="HR", note=f"{iv.round_name} scheduled for {iv.scheduled_at}",
    ))
    db.commit()
    db.refresh(iv)
    return interview_to_dict(iv)


@router.put("/api/recruitment/interviews/{iv_id}")
def update_interview(iv_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Record the outcome, reschedule, or cancel."""
    client = get_client_user(request, db)
    body = body or {}
    iv = db.query(models.DBInterview).filter(
        models.DBInterview.id == iv_id, models.DBInterview.client_id == client.id
    ).first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")

    if "status" in body:
        status = (body["status"] or "").strip().lower()
        if status not in INTERVIEW_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(INTERVIEW_STATUSES)}")
        iv.status = status
    if "outcome" in body:
        outcome = (body["outcome"] or "").strip().lower()
        if outcome not in INTERVIEW_OUTCOMES:
            raise HTTPException(status_code=400, detail="Outcome must be pass, fail or hold")
        iv.outcome = outcome
    if "score" in body:
        try:
            score = int(body["score"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Score must be a whole number")
        if score < 0 or score > 5:
            raise HTTPException(status_code=400, detail="Score must be between 0 and 5")
        iv.score = score
    if "scheduled_at" in body and body["scheduled_at"]:
        when = _parse_datetime_minutes(body["scheduled_at"])
        if not when:
            raise HTTPException(status_code=400, detail="Scheduled time must look like YYYY-MM-DD HH:MM")
        iv.scheduled_at = when.strftime("%Y-%m-%d %H:%M")
    for field in ("feedback", "meeting_link", "location", "round_name", "interviewer_name"):
        if field in body and body[field] is not None:
            setattr(iv, field, body[field])

    if iv.outcome and iv.status == "scheduled":
        iv.status = "completed"   # recording an outcome implies it happened
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=iv.submission_id,
        from_stage="", to_stage="", actor="HR",
        note=f"{iv.round_name}: {iv.status}" + (f" ({iv.outcome})" if iv.outcome else ""),
    ))
    db.commit()
    return interview_to_dict(iv)


@router.delete("/api/recruitment/interviews/{iv_id}")
def delete_interview(iv_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    iv = db.query(models.DBInterview).filter(
        models.DBInterview.id == iv_id, models.DBInterview.client_id == client.id
    ).first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(iv)
    db.commit()
    return {"message": "Interview removed"}


@router.get("/api/recruitment/interviews/upcoming")
def upcoming_interviews(request: Request, days: int = 14, db: Session = Depends(get_db)):
    """Everything scheduled in the next N days, for the recruiter's day view."""
    client = get_client_user(request, db)
    now = datetime.now()
    horizon = (now + timedelta(days=max(1, min(days, 90)))).strftime("%Y-%m-%d %H:%M")
    rows = db.query(models.DBInterview).filter(
        models.DBInterview.client_id == client.id,
        models.DBInterview.status == "scheduled",
        models.DBInterview.scheduled_at >= now.strftime("%Y-%m-%d 00:00"),
        models.DBInterview.scheduled_at <= horizon,
    ).order_by(models.DBInterview.scheduled_at.asc()).all()
    out = []
    for iv in rows:
        sub = db.query(models.DBFormSubmission).filter(
            models.DBFormSubmission.id == iv.submission_id
        ).first()
        data = interview_to_dict(iv)
        data["candidate_name"] = sub.candidate_name if sub else ""
        data["candidate_email"] = sub.candidate_email if sub else ""
        out.append(data)
    return out


@router.get("/api/recruitment/submissions/{sub_id}/offers")
def list_offers(sub_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    _get_submission_for_client(db, client.id, sub_id)
    rows = db.query(models.DBOffer).filter(
        models.DBOffer.submission_id == sub_id
    ).order_by(models.DBOffer.id.desc()).all()
    return [offer_to_dict(o) for o in rows]


@router.post("/api/recruitment/submissions/{sub_id}/offers")
def create_offer(sub_id: int, request: Request, body: OfferIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = _get_submission_for_client(db, client.id, sub_id)
    live = db.query(models.DBOffer).filter(
        models.DBOffer.submission_id == sub_id,
        models.DBOffer.status.in_(["draft", "sent", "accepted"]),
    ).first()
    if live:
        raise HTTPException(
            status_code=409,
            detail=f"This candidate already has a {live.status} offer. Withdraw it before creating another.",
        )
    salary = float(body.salary or 0)
    if salary < 0:
        raise HTTPException(status_code=400, detail="Salary cannot be negative")
    for label, value in (("Start date", body.start_date), ("Expiry date", body.expires_on)):
        if value and not _parse_date(value):
            raise HTTPException(status_code=400, detail=f"{label} must be in YYYY-MM-DD format")
    start, expires = _parse_date(body.start_date), _parse_date(body.expires_on)
    if start and expires and expires > start:
        raise HTTPException(status_code=400, detail="The offer would expire after the start date")

    offer = models.DBOffer(
        client_id=client.id, submission_id=sub_id,
        job_title=body.job_title or "", level=validate_level(body.level),
        salary=money(salary), currency=client.currency or "",
        start_date=body.start_date or "", expires_on=body.expires_on or "",
        notes=body.notes or "", status="draft",
    )
    db.add(offer)
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub_id,
        from_stage="", to_stage="", actor="HR",
        note=f"Offer drafted at {money(salary):.2f}",
    ))
    db.commit()
    db.refresh(offer)
    return offer_to_dict(offer)


@router.put("/api/recruitment/offers/{offer_id}")
def update_offer(offer_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    body = body or {}
    offer = db.query(models.DBOffer).filter(
        models.DBOffer.id == offer_id, models.DBOffer.client_id == client.id
    ).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    if "status" in body:
        status = (body["status"] or "").strip().lower()
        if status not in OFFER_STATUSES:
            raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(OFFER_STATUSES)}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if status == "sent" and offer.status != "sent":
            offer.sent_at = now
        if status in ("accepted", "declined") and offer.status not in ("accepted", "declined"):
            offer.responded_at = now
        offer.status = status
    if "decline_reason" in body:
        offer.decline_reason = body["decline_reason"] or ""
    for field in ("job_title", "start_date", "expires_on", "notes"):
        if field in body and body[field] is not None:
            setattr(offer, field, body[field])
    if "salary" in body:
        try:
            offer.salary = money(float(body["salary"]))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Salary must be a number")
    if "level" in body:
        offer.level = validate_level(body["level"])

    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=offer.submission_id,
        from_stage="", to_stage="", actor="HR",
        note=f"Offer {offer.status}" + (f": {offer.decline_reason}" if offer.decline_reason else ""),
    ))
    log_audit(db, client.id, f"offer_{offer.status}", "offer", offer.id, offer.job_title, "", request)
    db.commit()
    return offer_to_dict(offer)


@router.post("/api/recruitment/submissions/{sub_id}/reject")
def reject_candidate(sub_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    body = body or {}
    sub = _get_submission_for_client(db, client.id, sub_id)
    if sub.hired_employee_id:
        raise HTTPException(status_code=409, detail="This candidate has already been hired")
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Please give a reason so the pipeline data stays useful")
    sub.status = "rejected"
    sub.rejected_reason = reason
    sub.rejected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub_id,
        from_stage=sub.current_stage or "", to_stage="Rejected",
        actor="HR", note=reason,
    ))
    log_audit(db, client.id, "candidate_rejected", "candidate", sub.id,
              sub.candidate_name or sub.candidate_email, reason, request)
    db.commit()
    return {"message": "Candidate rejected", "status": sub.status}


@router.post("/api/recruitment/submissions/{sub_id}/reopen")
def reopen_candidate(sub_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = _get_submission_for_client(db, client.id, sub_id)
    sub.status = "new"
    sub.rejected_reason = ""
    sub.rejected_at = ""
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub_id,
        from_stage="Rejected", to_stage=sub.current_stage or "Applied",
        actor="HR", note="Application reopened",
    ))
    db.commit()
    return {"message": "Candidate reopened"}


@router.get("/api/recruitment/submissions/{sub_id}/email-preview")
def preview_candidate_email(sub_id: int, request: Request, template: str = "custom", db: Session = Depends(get_db)):
    """Let the recruiter read and edit the wording before anything is sent."""
    client = get_client_user(request, db)
    sub = _get_submission_for_client(db, client.id, sub_id)
    form = db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.id == sub.form_id).first()
    job = db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.id == form.job_id
    ).first() if form and form.job_id else None
    interview = db.query(models.DBInterview).filter(
        models.DBInterview.submission_id == sub_id, models.DBInterview.status == "scheduled"
    ).order_by(models.DBInterview.scheduled_at.asc()).first()
    offer = db.query(models.DBOffer).filter(
        models.DBOffer.submission_id == sub_id
    ).order_by(models.DBOffer.id.desc()).first()
    subject, body = build_candidate_email(template, sub, client, job, interview, offer)
    return {"to": sub.candidate_email or "", "subject": subject, "body": body}


@router.post("/api/recruitment/submissions/{sub_id}/email")
def email_candidate(sub_id: int, request: Request, background_tasks: BackgroundTasks,
                    body: CandidateEmailIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = _get_submission_for_client(db, client.id, sub_id)
    if not sub.candidate_email:
        raise HTTPException(status_code=400, detail="This candidate has no email address on file")
    if not validate_email_address(sub.candidate_email):
        raise HTTPException(status_code=400, detail=f"'{sub.candidate_email}' is not a valid email address")

    subject = (body.subject or "").strip()
    text_body = (body.body or "").strip()
    if not subject or not text_body:
        form = db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.id == sub.form_id).first()
        job = db.query(models.DBJobRequisition).filter(
            models.DBJobRequisition.id == form.job_id
        ).first() if form and form.job_id else None
        interview = db.query(models.DBInterview).filter(
            models.DBInterview.submission_id == sub_id, models.DBInterview.status == "scheduled"
        ).order_by(models.DBInterview.scheduled_at.asc()).first()
        offer = db.query(models.DBOffer).filter(
            models.DBOffer.submission_id == sub_id
        ).order_by(models.DBOffer.id.desc()).first()
        default_subject, default_body = build_candidate_email(
            body.template or "custom", sub, client, job, interview, offer
        )
        subject = subject or default_subject
        text_body = text_body or default_body

    from_email = default_from_email()
    company = client.company_name or "Recruitment"
    html_body = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#1e293b;line-height:1.6;'
        'max-width:600px;margin:0 auto;padding:24px;">'
        + "".join(f"<p>{esc(p)}</p>" for p in text_body.split("\n\n") if p.strip())
        + "</div>"
    )
    require_credit(db, client.id, "candidate_email", 1, sub.candidate_email)
    background_tasks.add_task(
        send_email_background, sub.candidate_email, subject, text_body,
        f"{company} <{from_email}>", html_body, None, "attachment.pdf", "", client.id,
    )
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub_id,
        from_stage="", to_stage="", actor="HR",
        note=f"Email sent: {subject}",
    ))
    log_audit(db, client.id, "candidate_emailed", "candidate", sub.id,
              sub.candidate_name or sub.candidate_email, subject, request)
    db.commit()
    return {"message": f"Email queued to {sub.candidate_email}", "subject": subject}


@router.get("/api/recruitment/analytics")
def recruitment_analytics(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    """Funnel, time-to-hire and offer acceptance - the numbers a head of talent
    is asked for."""
    client = get_client_user(request, db)
    form_query = db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.client_id == client.id)
    if job_id:
        form_query = form_query.filter(models.DBRecruitmentForm.job_id == job_id)
    forms = form_query.all()
    form_ids = [f.id for f in forms]

    subs = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.client_id == client.id,
        models.DBFormSubmission.form_id.in_(form_ids or [0]),
    ).all()

    stage_counts = defaultdict(int)
    source_counts = defaultdict(int)
    for s in subs:
        stage_counts[s.current_stage or "Applied"] += 1
        source_counts[s.source or "direct"] += 1

    hired = [s for s in subs if s.hired_employee_id]
    rejected = [s for s in subs if s.status == "rejected"]

    # Time to hire, measured from application to the hire event.
    durations = []
    for s in hired:
        applied = _parse_date((s.created_at or "")[:10])
        hired_on = _parse_date((getattr(s, "hired_at", "") or "")[:10])
        if not hired_on:
            # Records created before hired_at existed fall back to the event log.
            event = db.query(models.DBSubmissionEvent).filter(
                models.DBSubmissionEvent.submission_id == s.id,
                models.DBSubmissionEvent.to_stage == "Hired",
            ).order_by(models.DBSubmissionEvent.id.desc()).first()
            hired_on = _parse_date((event.created_at or "")[:10]) if event else None
        if applied and hired_on and hired_on >= applied:
            durations.append((hired_on - applied).days)

    offers = db.query(models.DBOffer).filter(models.DBOffer.client_id == client.id).all()
    if job_id:
        sub_ids = {s.id for s in subs}
        offers = [o for o in offers if o.submission_id in sub_ids]
    sent_offers = [o for o in offers if o.status in ("sent", "accepted", "declined")]
    accepted = [o for o in offers if o.status == "accepted"]

    interviews = db.query(models.DBInterview).filter(models.DBInterview.client_id == client.id).all()
    if job_id:
        sub_ids = {s.id for s in subs}
        interviews = [i for i in interviews if i.submission_id in sub_ids]

    total = len(subs)
    return {
        "total_applicants": total,
        "by_stage": dict(stage_counts),
        "by_source": dict(source_counts),
        "hired": len(hired),
        "rejected": len(rejected),
        "in_progress": total - len(hired) - len(rejected),
        "interviews_scheduled": sum(1 for i in interviews if i.status == "scheduled"),
        "interviews_completed": sum(1 for i in interviews if i.status == "completed"),
        "offers_sent": len(sent_offers),
        "offers_accepted": len(accepted),
        "offer_acceptance_rate": round(len(accepted) / len(sent_offers) * 100, 1) if sent_offers else 0.0,
        "conversion_rate": round(len(hired) / total * 100, 1) if total else 0.0,
        "avg_days_to_hire": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "open_jobs": db.query(models.DBJobRequisition).filter(
            models.DBJobRequisition.client_id == client.id,
            models.DBJobRequisition.status == "open",
        ).count(),
    }


@router.get("/api/recruitment/talent-pool")
def talent_pool(request: Request, q: str = "", stage: str = "", limit: int = 100,
                db: Session = Depends(get_db)):
    """Every candidate across every job, so a strong applicant for one role can
    be found again for another."""
    client = get_client_user(request, db)
    query = db.query(models.DBFormSubmission).filter(models.DBFormSubmission.client_id == client.id)
    if stage:
        query = query.filter(models.DBFormSubmission.current_stage == stage)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            models.DBFormSubmission.candidate_name.ilike(like),
            models.DBFormSubmission.candidate_email.ilike(like),
            models.DBFormSubmission.answers.ilike(like),
        ))
    rows = query.order_by(models.DBFormSubmission.id.desc()).limit(max(1, min(limit, 500))).all()

    form_titles = {
        f.id: f.title for f in db.query(models.DBRecruitmentForm).filter(
            models.DBRecruitmentForm.client_id == client.id
        ).all()
    }
    # Flag people who have applied more than once so a recruiter sees the
    # history instead of treating each application as a new person.
    email_counts = defaultdict(int)
    for r in db.query(models.DBFormSubmission.candidate_email).filter(
        models.DBFormSubmission.client_id == client.id
    ).all():
        if r.candidate_email:
            email_counts[r.candidate_email.lower()] += 1

    return [{
        "id": s.id, "candidate_name": s.candidate_name, "candidate_email": s.candidate_email,
        "candidate_phone": getattr(s, "candidate_phone", "") or "",
        "form_id": s.form_id, "form_title": form_titles.get(s.form_id, ""),
        "current_stage": s.current_stage, "status": s.status,
        "rating": getattr(s, "rating", 0) or 0,
        "applications": email_counts.get((s.candidate_email or "").lower(), 1),
        "hired_employee_id": getattr(s, "hired_employee_id", None),
        "created_at": s.created_at,
    } for s in rows]


@router.get("/api/recruitment/forms")
def list_recruitment_forms(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    forms = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.client_id == client.id
    ).order_by(models.DBRecruitmentForm.created_at.desc()).all()
    result = []
    for f in forms:
        sub_count = db.query(models.DBFormSubmission).filter(models.DBFormSubmission.form_id == f.id).count()
        hired_count = db.query(models.DBFormSubmission).filter(models.DBFormSubmission.form_id == f.id, models.DBFormSubmission.current_stage == 'Hired').count()
        pipeline_count = db.query(models.DBFormSubmission).filter(models.DBFormSubmission.form_id == f.id, models.DBFormSubmission.current_stage.notin_(['Hired', 'Rejected'])).count()
        result.append({
            "id": f.id, "title": f.title, "description": f.description,
            "fields": f.fields, "is_active": f.is_active,
            "form_token": f.form_token, "pipeline_stages": f.pipeline_stages,
            "job_id": f.job_id, "job_title": f.job.title if f.job else "",
            "created_at": f.created_at, "submission_count": sub_count,
            "hired_count": hired_count, "pipeline_count": pipeline_count
        })
    return result


@router.post("/api/recruitment/forms")
def create_recruitment_form(request: Request, body: RecruitmentFormCreate, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if body.job_id:
        job = db.query(models.DBJobRequisition).filter(
            models.DBJobRequisition.id == body.job_id,
            models.DBJobRequisition.client_id == client.id,
        ).first()
        if not job:
            raise HTTPException(status_code=400, detail="Job not found")
    form = models.DBRecruitmentForm(
        client_id=client.id, title=body.title, description=body.description, fields=body.fields,
        pipeline_stages=body.pipeline_stages, job_id=body.job_id,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    return {"id": form.id, "form_token": form.form_token, "job_id": form.job_id, "message": "Form created"}


@router.put("/api/recruitment/forms/{form_id}")
def update_recruitment_form(form_id: int, request: Request, body: dict, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    form = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.id == form_id, models.DBRecruitmentForm.client_id == client.id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    if "title" in body: form.title = body["title"]
    if "description" in body: form.description = body["description"]
    if "fields" in body: form.fields = body["fields"]
    if "is_active" in body: form.is_active = body["is_active"]
    if "pipeline_stages" in body: form.pipeline_stages = body["pipeline_stages"]
    db.commit()
    return {"message": "Form updated"}


@router.delete("/api/recruitment/forms/{form_id}")
def delete_recruitment_form(form_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    form = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.id == form_id, models.DBRecruitmentForm.client_id == client.id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    # Documents and pipeline history reference the submissions, so they must go
    # first or the delete fails on a foreign key.
    sub_ids = [s.id for s in db.query(models.DBFormSubmission.id).filter(
        models.DBFormSubmission.form_id == form_id
    ).all()]
    if sub_ids:
        for model in (models.DBCandidateDocument, models.DBSubmissionEvent,
                      models.DBInterview, models.DBOffer):
            db.query(model).filter(model.submission_id.in_(sub_ids)).delete(synchronize_session=False)
    db.query(models.DBFormSubmission).filter(models.DBFormSubmission.form_id == form_id).delete()
    log_audit(db, client.id, "recruitment_form_deleted", "form", form.id, form.title,
              f"{len(sub_ids)} application(s) removed", request)
    db.delete(form)
    db.commit()
    return {"message": "Form deleted"}


@router.get("/api/recruitment/forms/{form_id}/submissions")
def list_form_submissions(form_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    form = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.id == form_id, models.DBRecruitmentForm.client_id == client.id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    subs = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.form_id == form_id
    ).order_by(models.DBFormSubmission.created_at.desc()).all()
    # File payloads are deliberately omitted: a list of 200 candidates each
    # carrying a base64 CV is tens of megabytes. Documents are fetched per
    # candidate from /api/recruitment/submissions/{id}/documents.
    doc_counts = dict(
        db.query(models.DBCandidateDocument.submission_id, sqlfunc.count(models.DBCandidateDocument.id))
        .filter(models.DBCandidateDocument.submission_id.in_([s.id for s in subs] or [0]))
        .group_by(models.DBCandidateDocument.submission_id).all()
    )
    return [{
        "id": s.id, "form_id": s.form_id, "answers": s.answers, "file_name": s.file_name,
        "file_type": s.file_type,
        "has_resume": bool(s.file_data) or doc_counts.get(s.id, 0) > 0,
        "document_count": doc_counts.get(s.id, 0) or (1 if s.file_data else 0),
        "candidate_name": s.candidate_name,
        "candidate_email": s.candidate_email,
        "candidate_phone": getattr(s, 'candidate_phone', '') or '',
        "status": s.status,
        "rating": getattr(s, 'rating', 0) or 0,
        "hired_employee_id": getattr(s, 'hired_employee_id', None),
        "source": getattr(s, 'source', 'direct') or 'direct',
        "rejected_reason": getattr(s, 'rejected_reason', '') or '',
        "current_stage": getattr(s, 'current_stage', 'Applied'),
        "stage_order": getattr(s, 'stage_order', 0),
        "notes": s.notes, "created_at": s.created_at,
    } for s in subs]


@router.put("/api/recruitment/submissions/{sub_id}")
def update_submission(sub_id: int, request: Request, body: dict, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = db.query(models.DBFormSubmission).join(models.DBRecruitmentForm).filter(
        models.DBFormSubmission.id == sub_id,
        models.DBRecruitmentForm.client_id == client.id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if "status" in body: sub.status = body["status"]
    if "notes" in body: sub.notes = body["notes"]
    db.commit()
    return {"message": "Submission updated"}


@router.get("/api/recruitment/forms/{form_id}/pipeline")
def get_form_pipeline(form_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    form = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.id == form_id, models.DBRecruitmentForm.client_id == client.id
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
    import json
    stages_str = form.pipeline_stages or '["Applied","Screening","Interview","Offer","Hired"]'
    try:
        stages = json.loads(stages_str)
    except Exception:
        stages = ["Applied","Screening","Interview","Offer","Hired"]
    subs = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.form_id == form_id
    ).order_by(models.DBFormSubmission.stage_order.asc(), models.DBFormSubmission.created_at.desc()).all()
    pipeline = {}
    for s in subs:
        stage = getattr(s, 'current_stage', 'Applied') or 'Applied'
        if stage not in pipeline:
            pipeline[stage] = []
        pipeline[stage].append({
            "id": s.id, "answers": s.answers, "file_name": s.file_name,
            "file_type": s.file_type, "candidate_name": s.candidate_name,
            "candidate_email": s.candidate_email, "status": s.status,
            "rating": getattr(s, 'rating', 0) or 0,
            "hired_employee_id": getattr(s, 'hired_employee_id', None),
            "current_stage": stage, "stage_order": getattr(s, 'stage_order', 0),
            "notes": s.notes, "created_at": s.created_at,
        })
    # Stages with no candidates must still render as empty columns.
    for st in stages:
        pipeline.setdefault(st, [])
    return {"stages": stages, "pipeline": pipeline}


@router.put("/api/recruitment/submissions/{sub_id}/stage")
def move_submission_stage(sub_id: int, request: Request, body: dict, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = db.query(models.DBFormSubmission).join(models.DBRecruitmentForm).filter(
        models.DBFormSubmission.id == sub_id,
        models.DBRecruitmentForm.client_id == client.id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    new_stage = body.get("stage")
    stage_order = body.get("stage_order", 0)
    if not new_stage:
        raise HTTPException(status_code=400, detail="stage is required")
    # Only stages the form actually defines, so a typo cannot strand a
    # candidate in a column the board never renders.
    form = db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.id == sub.form_id).first()
    try:
        valid_stages = json.loads(form.pipeline_stages or "[]") if form else []
    except (ValueError, TypeError):
        valid_stages = []
    if valid_stages and new_stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"'{new_stage}' is not a stage on this form. Valid stages: {', '.join(valid_stages)}",
        )
    previous = sub.current_stage
    if previous == new_stage:
        return {"message": f"Candidate already in {new_stage}", "stage": new_stage}
    sub.current_stage = new_stage
    sub.stage_order = stage_order
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub.id,
        from_stage=previous or "", to_stage=new_stage,
        note=body.get("note", ""), actor=body.get("actor", "HR"),
    ))
    log_audit(db, client.id, "candidate_stage_changed", "candidate", sub.id,
              sub.candidate_name or sub.candidate_email, f"{previous} -> {new_stage}", request)
    db.commit()
    return {"message": f"Candidate moved to {new_stage}", "stage": new_stage, "from_stage": previous}


@router.get("/api/recruitment/submissions/{sub_id}/documents")
def list_candidate_documents(sub_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.id == sub_id, models.DBFormSubmission.client_id == client.id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    docs = db.query(models.DBCandidateDocument).filter(
        models.DBCandidateDocument.submission_id == sub_id
    ).order_by(models.DBCandidateDocument.id.asc()).all()
    # Metadata only; the payload is fetched per file so a candidate list with
    # many CVs does not ship megabytes of base64.
    return [{
        "id": d.id, "doc_type": d.doc_type, "file_name": d.file_name,
        "file_type": d.file_type, "file_size": d.file_size, "created_at": d.created_at,
    } for d in docs]


@router.get("/api/recruitment/documents/{doc_id}")
def get_candidate_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    doc = db.query(models.DBCandidateDocument).filter(
        models.DBCandidateDocument.id == doc_id, models.DBCandidateDocument.client_id == client.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id, "file_name": doc.file_name, "file_type": doc.file_type,
        "doc_type": doc.doc_type, "file_size": doc.file_size, "file_data": doc.file_data,
    }


@router.post("/api/recruitment/submissions/{sub_id}/documents")
def add_candidate_document(sub_id: int, body: CandidateDocumentIn, request: Request, db: Session = Depends(get_db)):
    """Let HR attach a document to an existing application (signed offer,
    interview scorecard, reference)."""
    client = get_client_user(request, db)
    sub = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.id == sub_id, models.DBFormSubmission.client_id == client.id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    existing = db.query(models.DBCandidateDocument).filter(
        models.DBCandidateDocument.submission_id == sub_id
    ).count()
    if existing >= MAX_DOCUMENTS_PER_APPLICATION * 2:
        raise HTTPException(status_code=400, detail="This candidate already has the maximum number of documents")
    size = validate_candidate_document(body)
    doc = models.DBCandidateDocument(
        client_id=client.id, submission_id=sub_id,
        doc_type=body.doc_type or "other", file_name=body.file_name,
        file_type=body.file_type or "", file_size=size, file_data=body.file_data,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"id": doc.id, "message": "Document attached"}


@router.delete("/api/recruitment/documents/{doc_id}")
def delete_candidate_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    doc = db.query(models.DBCandidateDocument).filter(
        models.DBCandidateDocument.id == doc_id, models.DBCandidateDocument.client_id == client.id
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"message": "Document removed"}


@router.get("/api/recruitment/submissions/{sub_id}/history")
def get_submission_history(sub_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    sub = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.id == sub_id, models.DBFormSubmission.client_id == client.id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    events = db.query(models.DBSubmissionEvent).filter(
        models.DBSubmissionEvent.submission_id == sub_id
    ).order_by(models.DBSubmissionEvent.id.asc()).all()
    return [{
        "id": e.id, "from_stage": e.from_stage, "to_stage": e.to_stage,
        "note": e.note, "actor": e.actor, "created_at": e.created_at,
    } for e in events]


@router.post("/api/recruitment/submissions/{sub_id}/hire")
def hire_candidate(sub_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Turn a successful candidate into an employee.

    Previously a hire had to be retyped by hand into the employee form, which
    is where names, emails and start dates get transcribed wrongly.
    """
    client = get_client_user(request, db)
    body = body or {}
    sub = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.id == sub_id, models.DBFormSubmission.client_id == client.id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.hired_employee_id:
        raise HTTPException(status_code=409, detail="This candidate has already been converted to an employee")
    if sub.status == "rejected":
        raise HTTPException(
            status_code=409,
            detail="This candidate was rejected. Reopen the application before hiring them.",
        )

    email = (body.get("email") or sub.candidate_email or "").strip()
    if not email or not validate_email_address(email):
        raise HTTPException(status_code=400, detail="A valid email address is required to create the employee record")
    if db.query(models.DBEmployee).filter(
        models.DBEmployee.email == email, models.DBEmployee.client_id == client.id
    ).first():
        raise HTTPException(status_code=400, detail="An employee with this email already exists")

    full_name = (body.get("full_name") or sub.candidate_name or "").strip()
    parts = full_name.split()
    first_name = body.get("first_name") or (parts[0] if parts else "New")
    last_name = body.get("last_name") or (" ".join(parts[1:]) if len(parts) > 1 else "Starter")

    level = validate_level(body.get("level"))
    role = validate_role(body.get("role"))
    reports_to = validate_manager(db, client.id, None, body.get("reports_to"))

    max_num = db.query(sqlfunc.coalesce(sqlfunc.max(models.DBEmployee.id), 0)).filter(
        models.DBEmployee.client_id == client.id
    ).scalar()
    emp = models.DBEmployee(
        client_id=client.id, employee_id=f"EMP-{max_num + 1:04d}",
        first_name=first_name, last_name=last_name, email=email,
        phone=body.get("phone") or sub.candidate_phone or "",
        job_title=body.get("job_title", ""), department_id=body.get("department_id"),
        reports_to=reports_to, level=level, role=role,
        employment_type=body.get("employment_type", "full_time"),
        pay_frequency=body.get("pay_frequency", "monthly"),
        salary=float(body.get("salary") or 0),
        start_date=body.get("start_date", ""),
        status="onboarding",
    )
    db.add(emp)
    db.flush()

    # Carry the application's files across so the new starter's record already
    # holds their CV and right-to-work documents.
    for doc in db.query(models.DBCandidateDocument).filter(
        models.DBCandidateDocument.submission_id == sub.id
    ).all():
        db.add(models.DBDocument(
            client_id=client.id, employee_id=emp.id,
            title=doc.file_name or doc.doc_type, doc_type=doc.doc_type,
            file_name=doc.file_name, file_type=doc.file_type,
            file_data=doc.file_data, uploaded_by="Recruitment",
        ))

    # Same start as anyone added by hand: a checklist and the documents HR
    # asks new starters for. Without this a hire arrived with nothing to do
    # and nothing asked of them.
    start_onboarding(db, client.id, emp)

    sub.hired_employee_id = emp.id
    sub.status = "hired"
    sub.hired_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    form = db.query(models.DBRecruitmentForm).filter(models.DBRecruitmentForm.id == sub.form_id).first()
    try:
        stages = json.loads(form.pipeline_stages or "[]") if form else []
    except (ValueError, TypeError):
        stages = []
    sub.current_stage = stages[-1] if stages else "Hired"
    db.add(models.DBSubmissionEvent(
        client_id=client.id, submission_id=sub.id,
        from_stage=sub.current_stage or "", to_stage="Hired",
        actor="HR", note=f"Converted to employee {emp.employee_id}",
    ))
    log_audit(db, client.id, "candidate_hired", "candidate", sub.id,
              full_name or email, f"Employee {emp.employee_id}", request)
    db.commit()
    db.refresh(emp)
    return {
        "message": f"{first_name} {last_name} added as {emp.employee_id}",
        "employee_id": emp.id, "employee_number": emp.employee_id,
    }


@router.put("/api/recruitment/submissions/{sub_id}/rating")
def rate_candidate(sub_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    body = body or {}
    sub = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.id == sub_id, models.DBFormSubmission.client_id == client.id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        rating = int(body.get("rating", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Rating must be a whole number")
    if rating < 0 or rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 0 and 5")
    sub.rating = rating
    db.commit()
    return {"message": "Rating saved", "rating": rating}


@router.get("/api/recruitment/form/{token}")
def get_public_form(token: str, db: Session = Depends(get_db)):
    form = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.form_token == token,
        models.DBRecruitmentForm.is_active == True,
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found or inactive")
    return {"title": form.title, "description": form.description, "fields": form.fields}


@router.post("/api/recruitment/form/{token}/submit")
def submit_application(token: str, body: FormSubmissionCreate, request: Request, db: Session = Depends(get_db)):
    """Public endpoint - anyone with the form link can post here, so it is rate
    limited and every attachment is size- and type-checked."""
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"apply:{ip}", max_requests=5, window=600):
        raise HTTPException(status_code=429, detail="Too many applications submitted. Please try again later.")

    form = db.query(models.DBRecruitmentForm).filter(
        models.DBRecruitmentForm.form_token == token,
        models.DBRecruitmentForm.is_active == True,
    ).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found or inactive")

    if body.candidate_email and not validate_email_address(body.candidate_email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    docs = list(body.documents or [])
    # Fold the single legacy attachment into the document list.
    if body.file_data and body.file_name:
        docs.insert(0, CandidateDocumentIn(
            doc_type="resume", file_name=body.file_name,
            file_type=body.file_type or "", file_data=body.file_data,
        ))
    if len(docs) > MAX_DOCUMENTS_PER_APPLICATION:
        raise HTTPException(
            status_code=400,
            detail=f"Please attach at most {MAX_DOCUMENTS_PER_APPLICATION} files",
        )
    sizes = [validate_candidate_document(d, i + 1) for i, d in enumerate(docs)]
    if sum(sizes) > MAX_DOCUMENT_BYTES * 2:
        raise HTTPException(status_code=413, detail="The attachments are too large in total")

    first_stage = "Applied"
    try:
        stages = json.loads(form.pipeline_stages or "[]")
        if stages:
            first_stage = stages[0]
    except (ValueError, TypeError):
        pass

    sub = models.DBFormSubmission(
        client_id=form.client_id, form_id=form.id,
        answers=body.answers,
        file_name=docs[0].file_name if docs else "",
        file_type=docs[0].file_type if docs else "",
        file_data=docs[0].file_data if docs else "",
        candidate_name=body.candidate_name, candidate_email=body.candidate_email,
        candidate_phone=body.candidate_phone or "",
        current_stage=first_stage, stage_order=0,
    )
    db.add(sub)
    db.flush()

    for doc, size in zip(docs, sizes):
        db.add(models.DBCandidateDocument(
            client_id=form.client_id, submission_id=sub.id,
            doc_type=doc.doc_type or "other", file_name=doc.file_name,
            file_type=doc.file_type or "", file_size=size, file_data=doc.file_data,
        ))
    db.add(models.DBSubmissionEvent(
        client_id=form.client_id, submission_id=sub.id,
        from_stage="", to_stage=first_stage, actor="Candidate",
        note="Application received",
    ))
    db.commit()
    return {
        "message": "Application submitted successfully",
        "documents_received": len(docs),
        "stage": first_stage,
    }
