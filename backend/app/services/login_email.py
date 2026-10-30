"""The email that tells a new member of staff how to sign in.

It goes only to the address the organisation issued them. The password is in hand once, while the employee is being
created: it goes out in that email and is kept nowhere, so a resend carries a one-time link to set a password instead.
"""
import os
from datetime import datetime
from html import escape as esc

from app import models
from app.core.config import logger
from app.core.notifications import default_from_email, send_email_background
from app.core.security import issue_reset_token
from app.db import SessionLocal

# Long enough to reach somebody who only checks their work mail on the next site visit.
LOGIN_LINK_HOURS = 72


def _base_url(request):
    return (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")


def login_url(request):
    return _base_url(request) + "/next/login"


def login_email(company, name, employee_code, org_email, url, password="", set_password_link=""):
    """Subject, plain text and HTML of the welcome: with the password, or with the link to set one."""
    subject = f"Welcome to {company} – Your Login Credentials"
    rows = [("Employee ID", employee_code), ("Organisation Email", org_email)]
    if password:
        rows.append(("Password", password))
        closing = "You can now log in to the application using your credentials."
    else:
        rows.append(("Set your password", set_password_link))
        closing = (f"The link works once and expires in {LOGIN_LINK_HOURS} hours. "
                   "Once your password is set, you can log in to the application using your credentials.")
    rows.append(("Login URL", url))
    credentials = "\n\n".join(f"{label}: {value}" for label, value in rows)
    text_body = (f"Hello {name},\n\nWelcome to {company}!\n\nYour employee account has been successfully created.\n\n"
                 f"Your login credentials are:\n\n{credentials}\n\n{closing}\n\n"
                 f"Regards,\n{company} Administration Team\n")
    html_rows = "".join(f'<p style="margin:0 0 12px;"><strong>{esc(label)}:</strong> {esc(value)}</p>' for label, value in rows)
    html_body = (f'<!DOCTYPE html><html><body style="font-family:Arial,Helvetica,sans-serif;font-size:15px;">'
                 f"<p>Hello {esc(name)},</p><p>Welcome to {esc(company)}!</p>"
                 f"<p>Your employee account has been successfully created.</p><p>Your login credentials are:</p>"
                 f"{html_rows}<p>{esc(closing)}</p><p>Regards,<br>{esc(company)} Administration Team</p></body></html>")
    return subject, text_body, html_body


def delivery(ok):
    """What goes on the employee's record once the mail server has answered."""
    return {"credentials_email_status": "sent" if ok else "failed",
            "credentials_email_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _send(client_id, emp_id, company, to, mail):
    """Whether it went. The reason it did not is in the mail log; the message itself is never logged."""
    subject, text_body, html_body = mail
    try:
        ok, _ = send_email_background(to, subject, text_body, f"{company} <{default_from_email()}>", html_body,
                                      None, "", "", client_id=client_id)
        return bool(ok)
    except Exception as exc:
        logger.error("Login email for employee %s failed: %s", emp_id, type(exc).__name__)
        return False


def deliver_login_email(client_id, emp_id, company, to, mail):
    """Runs off the request: the employee exists whatever happens here, and the outcome goes on their record."""
    ok = _send(client_id, emp_id, company, to, mail)
    with SessionLocal() as db:
        db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).update(delivery(ok), synchronize_session=False)
        db.commit()


def resend_login_email(request, db, company, emp):
    """A one-time link in place of the password, which nobody has any more. Whether it went."""
    client_id, emp_id, to = emp.client_id, emp.id, emp.org_email
    name, code = f"{emp.first_name} {emp.last_name}".strip(), emp.employee_id
    ip = request.client.host if request.client else ""
    token = issue_reset_token(db, "employee", emp_id, ip, minutes=LOGIN_LINK_HOURS * 60)
    db.commit()         # the mail server is not waited on inside a transaction
    link = f"{_base_url(request)}/next/reset-password?token={token}&portal=employee"
    ok = _send(client_id, emp_id, company, to, login_email(company, name, code, to, login_url(request), set_password_link=link))
    for key, value in delivery(ok).items():
        setattr(emp, key, value)
    db.commit()
    return ok
