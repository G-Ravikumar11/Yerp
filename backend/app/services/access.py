"""The rules and workings behind the access endpoints."""
import os
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException

from app import models

from app.constants.common import PORTAL_INVITE_DAYS
from app.core.notifications import default_from_email, get_stored_refresh_token, send_email_background
from app.core.security import _portal_token_hash
from app.services.subcontract_billing import portal_party


def member_to_dict(m, is_owner=False):
    return {
        "id": m.id if m else 0,
        "email": m.email if m else "",
        "name": (m.name if m else "") or "",
        "role": "owner" if is_owner else (m.role if m else "admin"),
        "is_active": bool(m.is_active) if m else True,
        "accepted": bool(m.accepted_at) if m else True,
        "last_login": (m.last_login if m else "") or "",
        "is_account_owner": is_owner,
    }


def portal_user_dict(db, u):
    _, party = portal_party(db, u.client_id, u.party_type, u.party_id)
    return {"id": u.id, "party_type": u.party_type, "party_id": u.party_id, "party": party,
            "name": u.name or "", "email": u.email or "", "is_active": bool(u.is_active),
            "has_password": bool(u.password_hash),
            "invite_open": bool(u.invite_token_hash) and (u.invite_expires or "") > datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "invite_expires": u.invite_expires or "", "last_login": u.last_login or "",
            "created_by_name": u.created_by_name or "", "created_at": u.created_at or ""}


def _issue_invite(u):
    token = secrets.token_urlsafe(32)
    u.invite_token_hash = _portal_token_hash(token)
    u.invite_expires = (datetime.now() + timedelta(days=PORTAL_INVITE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    return token


def _invite_link(request, token):
    base = (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")
    return "%s/portal.html?invite=%s" % (base, token)


def _send_invite(background_tasks, db, client, u, link):
    """By email when the company's mail is connected; the link is always
    handed back as well, to send on WhatsApp or read out on the phone."""
    if not get_stored_refresh_token(db, client_id=client.id):
        return False
    company = client.company_name or "Our office"
    body = ("%s has given you access to its partner portal - your orders, bills, payments and "
            "statement in one place.\n\nSet your password here (the link works for %d days):\n%s\n"
            % (company, PORTAL_INVITE_DAYS, link))
    background_tasks.add_task(send_email_background, u.email, "%s - your partner portal" % company, body,
                              "%s <%s>" % (company, default_from_email()),
                              None, None, "", "", client_id=client.id)
    return True


def _portal_user_or_404(db, client_id, user_id):
    u = db.query(models.DBPortalUser).filter(models.DBPortalUser.id == user_id,
                                             models.DBPortalUser.client_id == client_id).first()
    if not u:
        raise HTTPException(404, "Portal login not found")
    return u
