"""Telling people: email, WhatsApp and the in-app alerts."""
import base64
import json
import os
import re
import threading
import uuid
from datetime import datetime

import httpx
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal

from app.core.config import logger


def default_from_email():
    """The address mail is said to come from: the company's own, never a stranger's."""
    return (os.getenv("FROM_EMAIL", "") or "").strip() or "no-reply@localhost"


def get_gmail_credentials(access_token: str = None, refresh_token: str = None):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.error("GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not configured")
        return None
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    try:
        if creds.expired or not creds.valid:
            creds.refresh(GoogleRequest())
    except Exception as e:
        logger.error(f"Failed to refresh Gmail credentials: {e}")
        return None
    return creds


def get_stored_refresh_token(db: Session, client_id: int = None):
    q = db.query(models.DBSettings).filter(models.DBSettings.key == "GOOGLE_REFRESH_TOKEN")
    if client_id:
        # Try client-specific token first
        setting = q.filter(models.DBSettings.client_id == client_id).first()
        if setting:
            return setting.value
    # Fallback to global token (no client_id) for backward compat
    setting = q.filter(models.DBSettings.client_id == None).first()
    return setting.value if setting else None


def prepare_email_message(to_email, subject, body_text, html_body, from_email, logo_data="", pdf_bytes=None, pdf_filename="invoice.pdf"):
    """Build a properly structured MIME email with CID-embedded logo and PDF attachment."""
    import re as _re
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders as _encoders

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Reply-To'] = from_email
    msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')
    if (os.getenv("FROM_EMAIL", "") or "").strip():
        msg['List-Unsubscribe'] = '<mailto:%s?subject=unsubscribe>' % os.getenv("FROM_EMAIL").strip()
    msg['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'

    alt_part = MIMEMultipart('alternative')
    alt_part.attach(MIMEText(body_text, 'plain', 'utf-8'))

    if html_body and logo_data:
        logo_cid = 'logo_' + uuid.uuid4().hex[:12]
        data_url_match = _re.match(r'^data:(image/\w+);base64,(.+)$', logo_data, _re.DOTALL)
        if data_url_match:
            img_mime = data_url_match.group(1)
            img_b64 = data_url_match.group(2)
            img_sub = img_mime.split('/')[1] if '/' in img_mime else 'png'
            if img_sub == 'jpeg':
                img_sub = 'jpg'
            img_bytes = base64.b64decode(img_b64)
            logo_part = MIMEBase('image', img_sub)
            logo_part.set_payload(img_bytes)
            _encoders.encode_base64(logo_part)
            logo_part.add_header('Content-ID', f'<{logo_cid}>')
            logo_part.add_header('Content-Disposition', 'inline', filename='logo.' + img_sub)
            msg.attach(logo_part)
            html_body = html_body.replace(logo_data, f'cid:{logo_cid}')
        elif logo_data.startswith('http'):
            pass
        else:
            pass

    alt_part.attach(MIMEText(html_body, 'html', 'utf-8'))
    msg.attach(alt_part)

    if pdf_bytes:
        pdf_part = MIMEBase('application', 'pdf')
        pdf_part.set_payload(pdf_bytes)
        _encoders.encode_base64(pdf_part)
        pdf_part.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
        msg.attach(pdf_part)

    return msg.as_string()


def send_email_background(to_email: str, subject: str, body: str, from_email: str, html_body: str = None, pdf_b64: str = None, pdf_filename: str = "invoice.pdf", logo_data: str = "", client_id: int = None):
    pdf_bytes = None
    if pdf_b64:
        try:
            pdf_bytes = base64.b64decode(pdf_b64)
        except Exception as e:
            logger.error(f"Failed to decode PDF: {e}")

    raw_msg = prepare_email_message(to_email, subject, body, html_body or "", from_email, logo_data or "", pdf_bytes, pdf_filename)

    with SessionLocal() as db:
        refresh_token = get_stored_refresh_token(db, client_id=client_id)

    if not refresh_token:
        return False, "Gmail refresh token not configured"

    try:
        creds = get_gmail_credentials(access_token=None, refresh_token=refresh_token)
        service = build('gmail', 'v1', credentials=creds)
        encoded_message = base64.urlsafe_b64encode(raw_msg.encode('utf-8')).decode()
        send_result = service.users().messages().send(userId="me", body={'raw': encoded_message}).execute()
        logger.info(f"Email sent via Gmail API to {to_email} (ID: {send_result['id']})")
        return True, "Email sent via Gmail API"
    except Exception as e:
        logger.error(f"Gmail API failed: {e}")
        return False, f"Gmail API error: {str(e)}"


def notify_employee(db, client_id, employee_id, title, message, link=""):
    """Best-effort in-app notice. A missing notification must never be the
    reason an approval fails to record."""
    if not employee_id:
        return
    try:
        db.add(models.DBNotification(
            client_id=client_id, employee_id=employee_id,
            title=title, message=message, type="info", link=link,
        ))
    except Exception:
        logger.exception("Could not queue notification for employee %s", employee_id)


# NOTIFICATIONS
#
# A bill waiting on a signature, a receipt from a client, a gang bill to pay:
# each used to sit until somebody happened to open the right screen. They are
# announced now - on the bell in the app for everybody in the office, and by
# email or WhatsApp to whoever the company has named for each kind - and every
# morning the dashboard's list goes out as one digest.
NOTIFY_KINDS = {
    "ra_bill_submitted": "An RA bill is waiting to be certified",
    "ra_bill_certified": "An RA bill has been certified",
    "sub_bill_submitted": "A contractor's bill is waiting to be certified",
    "sub_bill_certified": "A contractor's bill has been certified",
    "subcontract_submitted": "A subcontract order is waiting for approval",
    "variation_submitted": "A variation is waiting for approval",
    "variation_approved": "A variation has been agreed",
    "money_in": "Money received",
    "money_out": "Money paid out",
    "qc_failed": "A quality check failed or an NCR was raised",
    "safety_incident": "A safety incident or near miss was reported",
    "retention_released": "Retention was released - to claim, or to pay a contractor",
    "portal_invoice": "A supplier sent an invoice through the partner portal",
    "chat_mention": "Somebody was named in a project chat",
    "daily_digest": "The morning list of what needs looking at",
}
# Out of the box: the bell for everything, email for the money and the digest.
NOTIFY_DEFAULT_EMAIL = {"ra_bill_certified", "money_in", "daily_digest"}


def notify_settings(db, client_id):
    rows = {s.key: s.value for s in db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client_id,
        models.DBSettings.key.in_(["notify_emails", "notify_whatsapp", "notify_channels",
                                   "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN"])).all()}
    try:
        channels = json.loads(rows.get("notify_channels") or "{}")
    except ValueError:
        channels = {}
    for k in NOTIFY_KINDS:
        channels.setdefault(k, ["email"] if k in NOTIFY_DEFAULT_EMAIL else [])
    split = lambda v: [x.strip() for x in re.split(r"[,;\s]+", v or "") if x.strip()]
    return {"emails": split(rows.get("notify_emails")),
            "whatsapp": [re.sub(r"\D", "", x) for x in split(rows.get("notify_whatsapp"))],
            "channels": channels,
            "whatsapp_ready": bool(rows.get("WHATSAPP_PHONE_NUMBER_ID") and rows.get("WHATSAPP_ACCESS_TOKEN")),
            "wa_phone_id": rows.get("WHATSAPP_PHONE_NUMBER_ID") or "",
            "wa_token": rows.get("WHATSAPP_ACCESS_TOKEN") or ""}


def _send_whatsapp_for(phone_id, token, number, text):
    """One WhatsApp message through the company's own Business number."""
    try:
        r = httpx.post("https://graph.facebook.com/v17.0/%s/messages" % phone_id,
                       headers={"Authorization": "Bearer %s" % token, "Content-Type": "application/json"},
                       json={"messaging_product": "whatsapp", "to": number, "type": "text",
                             "text": {"body": text[:4000]}}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:
        logger.error("WhatsApp to %s failed: %s", number, exc)
        return False


def _deliver(client_id, from_email, emails, numbers, wa_phone_id, wa_token, subject, text):
    """Runs off the request: the person who certified a bill is not kept
    waiting on a mail server."""
    for to in emails:
        try:
            send_email_background(to, subject, text, from_email, client_id=client_id)
        except Exception as exc:
            logger.error("Notification email to %s failed: %s", to, exc)
    for n in numbers:
        _send_whatsapp_for(wa_phone_id, wa_token, n, "%s\n\n%s" % (subject, text))


NOTIFY_SYNC = False          # tests set this to deliver inline instead of on a thread


def notify(db, client_id, kind, title, body="", view="", ref_type="", ref_id=None, severity="info"):
    """Announce something. Never allowed to break what raised it."""
    try:
        n = models.DBAlert(client_id=client_id, kind=kind, title=title[:200], body=(body or "")[:2000],
                                  view=view or "", ref_type=ref_type or "", ref_id=ref_id, severity=severity)
        cfg = notify_settings(db, client_id)
        wanted = cfg["channels"].get(kind, [])
        emails = cfg["emails"] if "email" in wanted else []
        numbers = cfg["whatsapp"] if ("whatsapp" in wanted and cfg["whatsapp_ready"]) else []
        n.sent_to = ", ".join(emails + ["+" + x for x in numbers])
        db.add(n)
        db.commit()
        # Paper waiting for a decision is also put in front of the people who
        # can make it, in their own notices - the bell alone told everybody,
        # which is the same as telling nobody.
        right = APPROVER_ALERTS.get(kind)
        if right:
            for emp in holders_of(db, client_id, right):
                notify_employee(db, client_id, emp.id, title[:200], (body or title)[:500],
                                link="/next/approvals")
            db.commit()
        if emails or numbers:
            client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
            args = (client_id, (client.email if client else "") or "", emails, numbers,
                    cfg["wa_phone_id"], cfg["wa_token"],
                    "%s - %s" % ((client.company_name if client else "") or "Y ERP", title), body or title)
            if NOTIFY_SYNC:
                _deliver(*args)
            else:
                threading.Thread(target=_deliver, args=args, daemon=True).start()
        return n
    except Exception as exc:
        logger.error("Notification %s failed: %s", kind, exc)
        db.rollback()
        return None


# Tenant notices that mean "somebody has to decide this", and who decides.
APPROVER_ALERTS = {"ra_bill_submitted": "subcontracts.approve",
                   "sub_bill_submitted": "subcontracts.approve",
                   "variation_submitted": "subcontracts.approve"}


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.approvals import holders_of
