"""The rules and workings behind the recruitment endpoints."""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import models

from app.constants.recruitment import INTERVIEW_REMINDER_HOURS
from app.core.currency import DEFAULT_CURRENCY, currency_symbol, esc
from app.core.notifications import default_from_email, send_email_background
from app.core.scheduler import scheduled_job
from app.validators.common import validate_email_address


@scheduled_job("interview_reminders")
def job_interview_reminders(db, now):
    """Remind both sides about an interview happening tomorrow.

    An interview was booked and then nothing happened until it either did or
    did not. Candidates no-show when nobody reminds them, and an interviewer
    who has forgotten is worse than one who cancels.
    """
    horizon = now + timedelta(hours=INTERVIEW_REMINDER_HOURS)
    sent = 0

    rows = db.query(models.DBInterview, models.DBFormSubmission).join(
        models.DBFormSubmission,
        models.DBInterview.submission_id == models.DBFormSubmission.id,
    ).filter(
        models.DBInterview.status == "scheduled",
        models.DBInterview.scheduled_at != "",
    ).all()

    for iv, sub in rows:
        try:
            when = datetime.strptime(iv.scheduled_at[:16], "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        # Only the ones inside the window, and never one already in the past.
        if not (now <= when <= horizon):
            continue

        client = db.query(models.DBClient).filter(
            models.DBClient.id == iv.client_id).first()
        company = (client.company_name if client else "") or "the team"
        from_email = default_from_email()
        where = iv.meeting_link or iv.location or (
            "a video call" if iv.mode == "video" else iv.mode)

        recipients = []
        if sub.candidate_email and validate_email_address(sub.candidate_email):
            recipients.append(("candidate", sub.candidate_email,
                               sub.candidate_name or "there"))
        if iv.interviewer_id:
            interviewer = db.query(models.DBEmployee).filter(
                models.DBEmployee.id == iv.interviewer_id).first()
            if interviewer and interviewer.email and validate_email_address(interviewer.email):
                recipients.append(("interviewer", interviewer.email,
                                   interviewer.first_name or "there"))

        for who, address, name in recipients:
            # Written before sending, and the unique index means two workers
            # racing cannot both send the same nudge.
            db.add(models.DBInterviewReminder(
                client_id=iv.client_id, interview_id=iv.id,
                recipient=who, sent_to=address))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                continue

            subject = "Reminder: {} on {}".format(iv.round_name, iv.scheduled_at[:16])
            if who == "candidate":
                body = (
                    "Hello {},\n\nA reminder that your {} with {} is on {}.\n\n"
                    "Where: {}\nLasting about {} minutes.\n\n"
                    "If you can no longer make it, reply to this email and we "
                    "will rearrange.\n\nGood luck,\n{}\n"
                ).format(name, iv.round_name, company, iv.scheduled_at[:16],
                         where, iv.duration_minutes, company)
            else:
                body = (
                    "Hello {},\n\nYou are interviewing {} ({}) on {}.\n\n"
                    "Where: {}\nLasting about {} minutes.\n\n{}\n"
                ).format(name, sub.candidate_name or "a candidate", iv.round_name,
                         iv.scheduled_at[:16], where, iv.duration_minutes, company)

            html = (
                '<!DOCTYPE html><html><body style="font-family:Arial,Helvetica,sans-serif;'
                'background:#f1f5f9;margin:0;"><div style="max-width:520px;margin:0 auto;'
                'padding:40px 20px;"><div style="background:#fff;border-radius:12px;'
                'overflow:hidden;"><div style="background:#0f172a;padding:28px;'
                'text-align:center;"><div style="font-size:12px;letter-spacing:2px;'
                'text-transform:uppercase;color:#94a3b8;">Interview reminder</div>'
                '<div style="font-size:22px;font-weight:800;color:#fff;margin-top:6px;">'
                + esc(iv.round_name) + '</div></div><div style="padding:26px;">'
                '<p style="margin:0 0 16px;font-size:15px;">Hello ' + esc(name) + ',</p>'
                '<p style="margin:0 0 18px;font-size:15px;color:#475569;">'
                'This is a reminder about the ' + esc(iv.round_name) + ' on <strong>'
                + esc(iv.scheduled_at[:16]) + '</strong>, lasting about '
                + str(iv.duration_minutes) + ' minutes.</p>'
                '<p style="margin:0;font-size:14px;"><strong>Where:</strong> '
                + esc(where) + '</p></div>'
                '<div style="background:#f8fafc;padding:18px;text-align:center;'
                'border-top:1px solid #e2e8f0;"><div style="font-size:13px;'
                'font-weight:700;color:#0f172a;">' + esc(company) + '</div></div>'
                '</div></div></body></html>'
            )

            send_email_background(address, subject, body,
                                  "{} <{}>".format(company, from_email),
                                  html, None, "", "", client_id=iv.client_id)
            sent += 1

    return "{} interview reminder(s) sent".format(sent)


def requisition_to_dict(job, db=None, counts=None):
    dept_name = job.department.name if job.department else ""
    manager_name = ""
    if job.hiring_manager:
        manager_name = f"{job.hiring_manager.first_name} {job.hiring_manager.last_name}"
    data = {
        "id": job.id, "reference": job.reference, "title": job.title,
        "department_id": job.department_id, "department_name": dept_name,
        "hiring_manager_id": job.hiring_manager_id, "hiring_manager_name": manager_name,
        "description": job.description or "", "requirements": job.requirements or "",
        "location": job.location or "", "work_mode": job.work_mode or "onsite",
        "employment_type": job.employment_type or "full_time", "level": job.level or "",
        "salary_min": job.salary_min or 0, "salary_max": job.salary_max or 0,
        "salary_currency": job.salary_currency or "", "show_salary": bool(job.show_salary),
        "openings": job.openings or 1, "status": job.status,
        "is_published": bool(job.is_published), "closing_date": job.closing_date or "",
        "opened_at": job.opened_at or "", "closed_at": job.closed_at or "",
        "created_at": job.created_at,
    }
    if counts is not None:
        data.update(counts)
    return data


def _get_submission_for_client(db, client_id, sub_id):
    sub = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.id == sub_id,
        models.DBFormSubmission.client_id == client_id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return sub


def interview_to_dict(iv):
    return {
        "id": iv.id, "submission_id": iv.submission_id, "round_name": iv.round_name,
        "scheduled_at": iv.scheduled_at, "duration_minutes": iv.duration_minutes,
        "mode": iv.mode, "location": iv.location, "meeting_link": iv.meeting_link,
        "interviewer_id": iv.interviewer_id, "interviewer_name": iv.interviewer_name,
        "status": iv.status, "outcome": iv.outcome, "score": iv.score,
        "feedback": iv.feedback, "created_at": iv.created_at,
    }


def _parse_datetime_minutes(value):
    """Accept 'YYYY-MM-DD HH:MM' or the HTML datetime-local 'YYYY-MM-DDTHH:MM'."""
    if not value:
        return None
    text_val = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text_val, fmt)
        except ValueError:
            continue
    return None


def offer_to_dict(o):
    return {
        "id": o.id, "submission_id": o.submission_id, "job_title": o.job_title,
        "level": o.level, "salary": o.salary, "currency": o.currency,
        "start_date": o.start_date, "expires_on": o.expires_on, "notes": o.notes,
        "status": o.status, "sent_at": o.sent_at, "responded_at": o.responded_at,
        "decline_reason": o.decline_reason, "created_at": o.created_at,
    }


def build_candidate_email(template, sub, client, job=None, interview=None, offer=None):
    """Default wording for the three moments a candidate hears from you."""
    company = client.company_name or "our team"
    name = (sub.candidate_name or "there").split()[0] if sub.candidate_name else "there"
    role = (job.title if job else "") or "the role"
    if template == "interview" and interview:
        subject = f"Interview invitation - {role} at {company}"
        when = interview.scheduled_at or "a time we will confirm"
        where = interview.meeting_link or interview.location or f"{interview.mode} call"
        body = (
            f"Hi {name},\n\n"
            f"Thank you for applying for {role} at {company}. We would like to invite you to "
            f"a {interview.round_name.lower()}.\n\n"
            f"When: {when}\n"
            f"Duration: {interview.duration_minutes} minutes\n"
            f"Where: {where}\n\n"
            f"If that time does not suit, reply to this email and we will rearrange.\n\n"
            f"Best regards,\n{company}"
        )
    elif template == "offer" and offer:
        subject = f"Offer of employment - {offer.job_title or role} at {company}"
        sym = currency_symbol(offer.currency or client.currency or DEFAULT_CURRENCY)
        body = (
            f"Hi {name},\n\n"
            f"We are delighted to offer you the position of {offer.job_title or role} at {company}.\n\n"
            f"Salary: {sym}{offer.salary:,.2f}\n"
            f"Start date: {offer.start_date or 'to be agreed'}\n"
            + (f"This offer is open until {offer.expires_on}.\n" if offer.expires_on else "")
            + (f"\n{offer.notes}\n" if offer.notes else "")
            + f"\nPlease reply to confirm whether you would like to accept.\n\n"
            f"Best regards,\n{company}"
        )
    elif template == "rejection":
        subject = f"Your application for {role} at {company}"
        body = (
            f"Hi {name},\n\n"
            f"Thank you for taking the time to apply for {role} at {company} and for talking with us.\n\n"
            f"On this occasion we have decided to progress other candidates. It was a competitive "
            f"process and this is not a reflection of your ability.\n\n"
            f"We will keep your details on file and would welcome an application from you in future.\n\n"
            f"Best regards,\n{company}"
        )
    else:
        subject = f"An update on your application - {company}"
        body = f"Hi {name},\n\nWe wanted to give you an update on your application.\n\nBest regards,\n{company}"
    return subject, body
