"""The access endpoints."""
import os
import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import PORTAL_INVITE_DAYS, PORTAL_PARTY_TYPES
from app.core.audit import log_audit
from app.core.auth import current_role, get_client_user, require_erp_read, require_owner, wo_actor
from app.core.notifications import default_from_email, send_email_background
from app.core.security import RESET_TOKEN_TTL_MINUTES, issue_reset_token
from app.schemas.access import PortalInviteIn, TeamInvite, TeamUpdate
from app.services.access import (
    _invite_link,
    _issue_invite,
    _portal_user_or_404,
    _send_invite,
    member_to_dict,
    portal_user_dict,
)
from app.services.auth import reset_email_bodies
from app.services.subcontract_billing import portal_party
from app.validators.common import validate_email_address


router = APIRouter()


@router.get("/api/team")
def list_team(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    rows = db.query(models.DBTeamMember).filter(
        models.DBTeamMember.client_id == client.id
    ).order_by(models.DBTeamMember.id.asc()).all()

    # The owner is on DBClient, not in this table, but they are a person on the
    # team and leaving them out of the list would be confusing.
    owner = {
        "id": 0, "email": client.email, "name": client.contact_name or "",
        "role": "owner", "is_active": bool(client.is_active), "accepted": True,
        "last_login": client.last_login or "", "is_account_owner": True,
    }
    return {"members": [owner] + [member_to_dict(m) for m in rows],
            "your_role": current_role(request, db)}


@router.post("/api/team/invite")
def invite_member(body: TeamInvite, background_tasks: BackgroundTasks,
                  request: Request, db: Session = Depends(get_db)):
    """Add a colleague and email them a link to set their own password.

    Reuses the password-reset machinery rather than inventing a second kind of
    token, so an invite is single-use and expires like any other link, and no
    password ever travels by email.
    """
    client = get_client_user(request, db)
    require_owner(request, db)

    email = (body.email or "").strip().lower()
    if not email or not validate_email_address(email):
        raise HTTPException(status_code=400, detail="A valid email address is required")
    role = (body.role or "admin").strip().lower()
    if role not in ("admin", "viewer"):
        raise HTTPException(status_code=400,
                            detail="Role must be admin or viewer. There is one Master.")
    if email == (client.email or "").lower():
        raise HTTPException(status_code=400, detail="That is the account Master's address")
    if db.query(models.DBTeamMember).filter(
        models.DBTeamMember.client_id == client.id,
        sqlfunc.lower(models.DBTeamMember.email) == email,
    ).first():
        raise HTTPException(status_code=400, detail="They are already on the team")

    member = models.DBTeamMember(
        client_id=client.id, email=email, name=(body.name or "").strip(), role=role)
    db.add(member)
    db.flush()

    token = issue_reset_token(db, "member", member.id, request.client.host if request.client else "")
    log_audit(db, client.id, "team_invited", "team", member.id, email, role, request)
    db.commit()

    base = (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")
    link = f"{base}/reset-password.html?token={token}&portal=team"
    who = client.company_name or "the team"
    text_body, html_body = reset_email_bodies(link, who, RESET_TOKEN_TTL_MINUTES)
    text_body = text_body.replace("Someone asked to reset the password for",
                                  "You have been invited to")
    from_email = default_from_email()
    background_tasks.add_task(
        send_email_background, email, f"You have been added to {who} on Y ERP",
        text_body, f"Y ERP <{from_email}>", html_body, None, "", "",
        client_id=client.id)

    return member_to_dict(member)


@router.put("/api/team/{member_id}")
def update_member(member_id: int, body: TeamUpdate, request: Request,
                  db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    member = db.query(models.DBTeamMember).filter(
        models.DBTeamMember.id == member_id,
        models.DBTeamMember.client_id == client.id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")

    if body.role is not None:
        role = body.role.strip().lower()
        if role not in ("admin", "viewer"):
            raise HTTPException(status_code=400, detail="Role must be admin or viewer")
        member.role = role
    if body.is_active is not None:
        member.is_active = bool(body.is_active)
    if body.name is not None:
        member.name = body.name.strip()

    log_audit(db, client.id, "team_updated", "team", member.id, member.email,
              member.role, request)
    db.commit()
    db.refresh(member)
    return member_to_dict(member)


@router.delete("/api/team/{member_id}")
def remove_member(member_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    member = db.query(models.DBTeamMember).filter(
        models.DBTeamMember.id == member_id,
        models.DBTeamMember.client_id == client.id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")

    # Any outstanding invite or reset link for them dies with the account.
    db.query(models.DBPasswordReset).filter(
        models.DBPasswordReset.member_id == member.id,
        models.DBPasswordReset.used_at == "",
    ).update({"used_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
             synchronize_session=False)

    log_audit(db, client.id, "team_removed", "team", member.id, member.email, "", request)
    db.delete(member)
    db.commit()
    return {"message": "Removed from the team"}


@router.get("/api/portal-access")
def list_portal_access(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    users = [portal_user_dict(db, u) for u in db.query(models.DBPortalUser).filter(
        models.DBPortalUser.client_id == client.id).order_by(models.DBPortalUser.id.desc()).all()]
    contractors = [{"id": c.id, "name": c.company_name or "", "email": c.email or "",
                    "contact": c.contact_person or ""}
                   for c in db.query(models.DBContractor).filter(
                       models.DBContractor.client_id == client.id,
                       models.DBContractor.is_active.isnot(False)).order_by(models.DBContractor.company_name).all()]
    suppliers = [{"id": s.id, "name": s.name or "", "email": s.email or "", "contact": s.contact_person or ""}
                 for s in db.query(models.DBSupplier).filter(
                     models.DBSupplier.client_id == client.id,
                     models.DBSupplier.is_active.isnot(False)).order_by(models.DBSupplier.name).all()]
    return {"users": users, "contractors": contractors, "suppliers": suppliers}


@router.post("/api/portal-access")
def invite_to_portal(body: PortalInviteIn, request: Request, background_tasks: BackgroundTasks,
                     db: Session = Depends(get_db)):
    """Give one person at a gang or a supplier their own login. Letting an
    outsider in is an approver's decision, like passing their bill."""
    client, _, actor_name = wo_actor(request, db, "subcontracts.approve")
    if body.party_type not in PORTAL_PARTY_TYPES:
        raise HTTPException(400, "A portal login is for a subcontractor or a supplier.")
    party, party_name = portal_party(db, client.id, body.party_type, body.party_id)
    if not party:
        raise HTTPException(404, "Not on your list.")
    if party.is_active is False:
        raise HTTPException(409, "%s is marked inactive." % party_name)
    email = (body.email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "Their email address - it is what they sign in with.")
    if db.query(models.DBPortalUser).filter(sqlfunc.lower(models.DBPortalUser.email) == email).first():
        raise HTTPException(409, "%s already has a portal login." % email)
    u = models.DBPortalUser(client_id=client.id, party_type=body.party_type, party_id=party.id,
                            name=(body.name or getattr(party, "contact_person", "") or party_name).strip()[:120],
                            email=email, created_by_name=actor_name or "")
    token = _issue_invite(u)
    db.add(u)
    db.flush()
    log_audit(db, client.id, "portal_invited", body.party_type, party.id, party_name, email, request)
    db.commit()
    link = _invite_link(request, token)
    emailed = _send_invite(background_tasks, db, client, u, link)
    return {"user": portal_user_dict(db, u), "invite_url": link, "emailed": emailed,
            "message": "%s invited%s. The link works for %d days." % (
                email, " by email" if emailed else "", PORTAL_INVITE_DAYS)}


@router.post("/api/portal-access/{user_id}/reinvite")
def reinvite_to_portal(user_id: int, request: Request, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db)):
    """A fresh link - for an invite that ran out, or a forgotten password.
    Any earlier link stops working."""
    client, _, _ = wo_actor(request, db, "subcontracts.approve")
    u = _portal_user_or_404(db, client.id, user_id)
    if not u.is_active:
        raise HTTPException(409, "Turn the login back on first.")
    token = _issue_invite(u)
    log_audit(db, client.id, "portal_reinvited", u.party_type, u.party_id, u.email, "", request)
    db.commit()
    link = _invite_link(request, token)
    emailed = _send_invite(background_tasks, db, client, u, link)
    return {"user": portal_user_dict(db, u), "invite_url": link, "emailed": emailed,
            "message": "A new link for %s%s." % (u.email, ", sent by email" if emailed else "")}


@router.post("/api/portal-access/{user_id}/{action}")
def switch_portal_access(user_id: int, action: str, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "subcontracts.approve")
    if action not in ("disable", "enable"):
        raise HTTPException(404, "Not found")
    u = _portal_user_or_404(db, client.id, user_id)
    u.is_active = action == "enable"
    if not u.is_active:
        u.invite_token_hash = ""
    log_audit(db, client.id, "portal_" + action + "d", u.party_type, u.party_id, u.email, "", request)
    db.commit()
    return {"user": portal_user_dict(db, u),
            "message": "%s can %s sign in." % (u.email, "now" if u.is_active else "no longer")}
