"""Push notifications to the native app, sent through Firebase Cloud Messaging (FCM).

FCM reaches Android directly and iOS through Apple's push service once an Apple push key has been uploaded to
Firebase. Until FCM_PROJECT_ID and FCM_SERVICE_ACCOUNT_JSON are set, nothing here sends anything: every call is a
quiet no-op, so the rest of the app never depends on it.
"""
import json
import os
import threading

import httpx
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal

from app.core.config import logger

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def push_ready() -> bool:
    return bool(os.getenv("FCM_PROJECT_ID", "").strip() and os.getenv("FCM_SERVICE_ACCOUNT_JSON", "").strip())


def _access_token():
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["FCM_SERVICE_ACCOUNT_JSON"]), scopes=[_SCOPE])
    creds.refresh(GoogleRequest())
    return creds.token


def _send(tokens, title, body, link):
    """Runs on its own thread. A token FCM says is gone is removed."""
    try:
        bearer = _access_token()
        url = "https://fcm.googleapis.com/v1/projects/%s/messages:send" % os.environ["FCM_PROJECT_ID"].strip()
        dead = []
        with httpx.Client(timeout=10) as http:
            for token in tokens:
                msg = {"message": {"token": token, "notification": {"title": title[:100], "body": body[:300]},
                                   "data": {"link": link or ""}}}
                r = http.post(url, json=msg, headers={"Authorization": "Bearer " + bearer})
                if r.status_code in (400, 404) and ("UNREGISTERED" in r.text or "INVALID_ARGUMENT" in r.text):
                    dead.append(token)
                elif r.status_code >= 400:
                    logger.warning("Push failed (%s): %s", r.status_code, r.text[:200])
        if dead:
            db = SessionLocal()
            try:
                db.query(models.DBDevice).filter(models.DBDevice.token.in_(dead)).delete(synchronize_session=False)
                db.commit()
            finally:
                db.close()
    except Exception:
        logger.exception("Push delivery failed")


def push_to(db: Session, client_id, title, body="", link="", employee_id=None, owner=False):
    """Push to one employee's phones, or the owner's. Never raises, never blocks the caller."""
    if not push_ready():
        return
    try:
        q = db.query(models.DBDevice.token).filter(models.DBDevice.client_id == client_id)
        q = q.filter(models.DBDevice.employee_id == employee_id) if employee_id else q.filter(models.DBDevice.employee_id.is_(None))
        tokens = [t for (t,) in q.all()]
        if tokens:
            threading.Thread(target=_send, args=(tokens, title, body or title, link), daemon=True).start()
    except Exception:
        logger.exception("Could not queue push")
