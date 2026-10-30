"""The email endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.auth import get_client_user, require_owner
from app.core.notifications import default_from_email, get_gmail_credentials, get_stored_refresh_token, send_email_background
from app.core.security import rate_limiter
from app.validators.common import validate_email_address
from app.services.email import TRACKING_PIXEL


router = APIRouter()


@router.get("/api/track/open/{tracking_id}")
def track_email_open(tracking_id: str, db: Session = Depends(get_db)):
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.tracking_id == tracking_id).first()
    if inv:
        inv.open_count = (inv.open_count or 0) + 1
        inv.last_opened = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
    return StreamingResponse(iter([TRACKING_PIXEL]), media_type="image/gif", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    })


@router.get("/api/gmail/status")
def gmail_status(request: Request, db: Session = Depends(get_db)):
    # Which mailbox the company sends from is the company's business, not anybody's who asks.
    client_id = get_client_user(request, db).id
    user = request.session.get('user')
    refresh_token = get_stored_refresh_token(db, client_id=client_id)
    # Try to get the authorized Gmail email from the refresh token owner
    gmail_email = None
    if refresh_token:
        try:
            creds = get_gmail_credentials(access_token=None, refresh_token=refresh_token)
            if creds and creds.valid:
                service = build('gmail', 'v1', credentials=creds)
                profile = service.users().getProfile(userId="me").execute()
                gmail_email = profile.get("emailAddress")
        except Exception:
            pass
    return {
        "logged_in": bool(user),
        "user_email": user.get('email') if user else None,
        "user_name": user.get('name') if user else None,
        "refresh_token_stored": bool(refresh_token),
        "gmail_ready": bool(refresh_token),
        "gmail_authorized_email": gmail_email
    }


@router.post("/api/gmail/disconnect")
def disconnect_gmail(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    setting = db.query(models.DBSettings).filter(
        models.DBSettings.key == "GOOGLE_REFRESH_TOKEN",
        models.DBSettings.client_id == client.id
    ).first()
    if setting:
        db.delete(setting)
        db.commit()
    return {"ok": True, "message": "Gmail disconnected. Re-authorize with your Google account."}


@router.post("/api/gmail/test")
def send_test_email(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """The Master sends one short message to any address (Yahoo, Gmail, Outlook...) to see that mail goes out through the
    company's connected Gmail. Says what happened; never what the key to the mailbox is."""
    client = get_client_user(request, db)
    require_owner(request, db)
    if rate_limiter.is_rate_limited("gmail-test:%d" % client.id, max_requests=5, window=600):
        raise HTTPException(status_code=429, detail="Too many test emails. Try again in a few minutes.")
    to = ((body or {}).get("to") or "").strip()
    if not to or not validate_email_address(to):
        raise HTTPException(status_code=400, detail="Enter a valid email address to send the test to.")
    if not get_stored_refresh_token(db, client_id=client.id):
        raise HTTPException(status_code=409, detail="Gmail is not connected yet. Connect it first.")
    company = client.company_name or "Y ERP"
    ok, message = send_email_background(
        to, "Test email from %s" % company,
        "This is a test from %s on Y ERP. If you can read it, email is working.\n" % company,
        "%s <%s>" % (company, default_from_email()), None, None, "", "", client_id=client.id)
    if not ok:
        # The provider's own words can carry details of the account; the error log has them, the screen does not.
        raise HTTPException(status_code=502, detail="Gmail did not accept the message. Reconnect Gmail and try again.")
    return {"ok": True, "message": "Test email sent to %s." % to}
