"""The auth endpoints."""
import os
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app import models
from app.core import passwords
from app.db import get_db

from app.constants.common import ALLOW_SELF_REGISTRATION, GOOGLE_SIGNIN_SCOPES
from app.core.audit import log_audit, log_login
from app.core.auth import end_every_session, get_client_user
from app.core.config import logger
from app.core.notifications import default_from_email, send_email_background
from app.core.oauth import oauth
from app.core.security import (
    RESET_TOKEN_TTL_MINUTES,
    hash_password,
    issue_reset_token,
    rate_limiter,
    upgrade_password_hash,
    validate_password_strength,
    verify_password,
)
from app.schemas.auth import (
    ClientLogin,
    ClientOnboard,
    ClientRegister,
    ForgotPasswordIn,
    LogoUpdate,
    ResetPasswordIn,
)
from app.services.auth import (
    find_valid_reset,
    google_configured,
    reset_email_bodies,
    superadmin_google_emails,
)
from app.services.partner_portal import _portal_signed_in
from app.services.subcontract_billing import portal_party


router = APIRouter()


@router.post("/api/client/register")
def client_register(body: ClientRegister, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"register:{ip}", max_requests=5, window=300):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Try again later.")

    # This install belongs to one business. Registration exists to create that
    # business once; left open afterwards, anybody who finds the address can
    # sign themselves up on the same database and appear in the same admin
    # panel. Staff are added by the owner, with a role, not by registering.
    if not ALLOW_SELF_REGISTRATION and db.query(models.DBClient).count():
        raise HTTPException(
            status_code=403,
            detail="This system is already set up. Ask the Master to add you as "
                   "an employee - staff sign in with the account they are given, "
                   "not by registering.")

    validate_password_strength(body.password)
    existing = db.query(models.DBClient).filter(models.DBClient.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    client = models.DBClient(
        email=body.email,
        password_hash=hash_password(body.password),
        company_name=body.company_name,
        contact_name=body.contact_name,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return {"message": "Account created", "client_id": client.id}


@router.post("/api/client/login")
def client_login(body: ClientLogin, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"login:{ip}", max_requests=10, window=60):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    client = db.query(models.DBClient).filter(models.DBClient.email == body.email).first()
    if client and verify_password(body.password, client.password_hash):
        upgrade_password_hash(client, "password_hash", body.password)
    if not client or not verify_password(body.password, client.password_hash):
        # Not the account owner - it may be one of their colleagues.
        member = db.query(models.DBTeamMember).filter(
            sqlfunc.lower(models.DBTeamMember.email) == (body.email or "").strip().lower()
        ).first()
        if (member and member.is_active and member.password_hash
                and verify_password(body.password, member.password_hash)):
            upgrade_password_hash(member, "password_hash", body.password)
            owner = db.query(models.DBClient).filter(
                models.DBClient.id == member.client_id).first()
            if not owner or not owner.is_active:
                raise HTTPException(status_code=403, detail="Account disabled")
            request.session.pop("employee_id", None)
            request.session.pop("employee_client_id", None)
            request.session.pop("portal_user_id", None)
            request.session["client_id"] = owner.id
            request.session["member_id"] = member.id
            member.last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_login(db, owner.id, member.email, "member", "password", request, "success")
            db.commit()
            return {"message": "Logged in", "is_onboarded": owner.is_onboarded,
                    "company_name": owner.company_name, "role": member.role}
        log_login(db, None, body.email, "client", "password", request, "failed")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not client.is_active:
        log_login(db, client.id, body.email, "client", "password", request, "disabled")
        raise HTTPException(status_code=403, detail="Account disabled")
    request.session.pop("employee_id", None)
    request.session.pop("employee_client_id", None)
    request.session.pop("portal_user_id", None)
    request.session["client_id"] = client.id
    request.session.pop("member_id", None)
    log_login(db, client.id, body.email, "client", "password", request, "success")
    return {"message": "Logged in", "is_onboarded": client.is_onboarded, "company_name": client.company_name}


@router.post("/api/client/logout")
def client_logout(request: Request):
    end_every_session(request)
    return {"message": "Logged out"}


@router.get("/api/client/me")
def client_me(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    return {
        "id": client.id,
        "email": client.email,
        "company_name": client.company_name,
        "contact_name": client.contact_name,
        "phone_number": client.phone_number,
        "logo_url": client.logo_url,
        "address": client.address,
        "website": client.website,
        "abn": client.abn,
        "industry": client.industry,
        "is_onboarded": client.is_onboarded,
        "created_at": client.created_at,
    }


@router.post("/api/client/onboard")
def client_onboard(body: ClientOnboard, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    client.company_name = body.company_name or client.company_name
    client.contact_name = body.contact_name or client.contact_name
    client.phone_number = body.phone_number or client.phone_number
    client.address = body.address or client.address
    client.website = body.website or client.website
    client.abn = body.abn or client.abn
    client.industry = body.industry or client.industry
    if body.logo_url:
        client.logo_url = body.logo_url
    client.is_onboarded = True
    db.commit()
    return {"message": "Onboarding complete"}


@router.post("/api/client/logo")
def upload_logo(request: Request, db: Session = Depends(get_db)):

    client = get_client_user(request, db)
    return {"logo_url": client.logo_url or ""}


@router.get("/api/client/logo")
def get_logo(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    return {"logo_url": client.logo_url or ""}


@router.put("/api/client/logo")
def save_logo(body: LogoUpdate, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    client.logo_url = body.logo_url
    db.commit()
    return {"message": "Logo saved"}


@router.get("/api/auth/login")
async def login(request: Request, role: str = "client", portal: str = None):
    request.session['oauth_role'] = role
    if portal:
        request.session['oauth_portal'] = portal
    redirect_uri = str(request.url_for('auth_callback'))
    if redirect_uri.startswith('http://') and 'localhost' not in redirect_uri:
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)
    return await oauth.google.authorize_redirect(request, redirect_uri, access_type='offline', prompt='consent')


@router.get("/api/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    """Back from Google with permission to send mail as the company.

    It attaches that Gmail to the company already signed in, and nothing else: it never signs anybody in as
    somebody else and never creates an account. (It used to create a new company for any Google address it
    did not know, which let anyone with a Gmail account into the system.) Signing in with Google is
    /api/auth/google/start."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        logger.error(f"Google token exchange failed: {e}")
        return RedirectResponse(url="/login.html?error=auth_failed")
    user = token.get('userinfo') or {}
    refresh_token = token.get('refresh_token')
    oauth_role = request.session.pop('oauth_role', 'client')
    oauth_portal = request.session.pop('oauth_portal', 'invoicing')
    target_dashboard = "/next/people/employees" if oauth_portal == "hr" else "/next/"
    google_email = (user.get('email') or '').strip().lower()
    verified = user.get("email_verified") is not False

    if oauth_role == 'superadmin':
        sa_user = db.query(models.DBSuperAdmin).filter(
            sqlfunc.lower(models.DBSuperAdmin.email) == google_email).first() \
            if google_email and verified and google_email in superadmin_google_emails() else None
        if sa_user:
            request.session['superadmin_id'] = sa_user.id
            log_login(db, None, google_email, "superadmin", "google", request, "success")
            return RedirectResponse(url="/superadmin.html")
        log_login(db, None, google_email or "superadmin", "superadmin", "google", request, "failed")
        return RedirectResponse(url="/superadmin-login.html?error=not_admin")

    client_id = request.session.get("client_id")
    if not client_id or not db.query(models.DBClient).filter(models.DBClient.id == client_id).first():
        return RedirectResponse(url="/login.html?error=gmail_sign_in_first")
    # Who the Gmail belongs to, for the screen that says which address mail goes out from. Never the tokens:
    # the session lives in a cookie, and a cookie is no place for the key to somebody's mailbox.
    request.session['user'] = {"email": google_email, "name": user.get("name", "")}
    if refresh_token:
        try:
            setting = db.query(models.DBSettings).filter(
                models.DBSettings.key == "GOOGLE_REFRESH_TOKEN",
                models.DBSettings.client_id == client_id
            ).first()
            if not setting:
                db.add(models.DBSettings(key="GOOGLE_REFRESH_TOKEN", value=refresh_token, client_id=client_id))
            else:
                setting.value = refresh_token
            log_audit(db, client_id, "gmail_connected", "client", client_id, google_email, "", request)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to save refresh token: {e}")
    return RedirectResponse(url=target_dashboard)


@router.get("/api/auth/google/status")
def google_status():
    """Whether the button should be offered at all.

    A sign-in button that cannot work is worse than no button: people try it,
    it fails, and they conclude the account is broken rather than unconfigured.
    """
    return {"configured": google_configured()}


@router.get("/api/auth/google/start")
async def google_signin_start(request: Request, next: str = "/next/", who: str = ""):
    if not google_configured():
        # Back to the sign-in page with something readable, rather than a raw
        # server error. Somebody can reach this from a stale tab long after the
        # button stopped being offered.
        return RedirectResponse("/login.html?error=google_unconfigured")
    # Only a path on this site, so the redirect cannot be pointed elsewhere.
    request.session["google_next"] = next if next.startswith("/") and not next.startswith("//") else "/next/"
    # The partner portal has its own door: a partner signs in there, never into the office's app.
    request.session["google_for"] = "portal" if who == "portal" else ""
    redirect_uri = str(request.url_for("google_signin_callback"))
    if redirect_uri.startswith("http://") and "localhost" not in redirect_uri:
        redirect_uri = redirect_uri.replace("http://", "https://", 1)
    # The scope is passed explicitly rather than inherited from the registered
    # client, which also carries gmail.send. Signing in must not ask for
    # permission to send mail: it is a sensitive scope, so Google would hold
    # the whole sign-in behind app verification for the sake of a feature the
    # person may never touch. Connecting Gmail asks for it separately.
    return await oauth.google.authorize_redirect(
        request, redirect_uri, scope=GOOGLE_SIGNIN_SCOPES)


@router.get("/api/auth/google/callback", name="google_signin_callback")
async def google_signin_callback(request: Request, db: Session = Depends(get_db)):
    """Come back from Google, work out who this is, and sign them in.

    An address is matched against the account holders first and then against
    the staff, so somebody who is both signs in as the owner - the same
    precedence the password form uses.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        logger.exception("Google sign-in failed at the token exchange")
        page = "/portal.html" if request.session.pop("google_for", "") == "portal" else "/login.html"
        return RedirectResponse(page + "?error=google_failed")

    portal = request.session.pop("google_for", "") == "portal"
    page = "/portal.html" if portal else "/login.html"
    info = token.get("userinfo") or {}
    email = (info.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse(page + "?error=google_no_email")
    if info.get("email_verified") is False:
        return RedirectResponse(page + "?error=google_unverified")

    target = request.session.pop("google_next", "/next/")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if portal:
        u = db.query(models.DBPortalUser).filter(sqlfunc.lower(models.DBPortalUser.email) == email,
                                                 models.DBPortalUser.is_active.is_(True)).first()
        if not u:
            log_login(db, None, email, "partner", "google", request, status="failed")
            db.commit()
            return RedirectResponse("/portal.html?error=google_unknown")
        client = db.query(models.DBClient).filter(models.DBClient.id == u.client_id).first()
        party, _ = portal_party(db, u.client_id, u.party_type, u.party_id)
        if not client or not client.is_active or not party or party.is_active is False:
            return RedirectResponse("/portal.html?error=account_disabled")
        _portal_signed_in(request, db, u, method="google")
        return RedirectResponse("/portal.html")

    client = db.query(models.DBClient).filter(
        sqlfunc.lower(models.DBClient.email) == email).first()
    if client:
        if not client.is_active:
            return RedirectResponse("/login.html?error=account_disabled")
        request.session.pop("employee_id", None)
        request.session.pop("employee_client_id", None)
        request.session.pop("portal_user_id", None)
        request.session.pop("member_id", None)
        request.session["client_id"] = client.id
        log_login(db, client.id, email, "client", "google", request)
        return RedirectResponse(target if client.is_onboarded else "/onboard.html")

    # A colleague on the Master's team: signing in with the Google account their invite went to is as good as
    # accepting it.
    member = db.query(models.DBTeamMember).filter(
        sqlfunc.lower(models.DBTeamMember.email) == email, models.DBTeamMember.is_active.is_(True)).first()
    if member:
        owner = db.query(models.DBClient).filter(models.DBClient.id == member.client_id).first()
        if not owner or not owner.is_active:
            return RedirectResponse("/login.html?error=account_disabled")
        for k in ("employee_id", "employee_client_id", "portal_user_id"):
            request.session.pop(k, None)
        request.session["client_id"] = owner.id
        request.session["member_id"] = member.id
        member.accepted_at = member.accepted_at or now
        member.last_login = now
        log_login(db, owner.id, member.email, "member", "google", request, "success")
        db.commit()
        return RedirectResponse(target)

    emp = db.query(models.DBEmployee).filter(
        sqlfunc.lower(models.DBEmployee.email) == email).first()
    if emp and emp.status != "terminated":
        request.session.pop("client_id", None)
        request.session.pop("member_id", None)
        request.session.pop("portal_user_id", None)
        request.session["employee_id"] = emp.id
        request.session["employee_client_id"] = emp.client_id
        log_login(db, emp.client_id, email, "employee", "google", request)
        return RedirectResponse(target)

    # Deliberately no account creation. On a system where HR issues the
    # addresses, anyone with a Google account could otherwise let themselves
    # in and land in a tenancy they have nothing to do with.
    log_login(db, None, email, "google", "google", request, status="failed")
    return RedirectResponse("/login.html?error=google_unknown")


@router.get("/api/auth/me")
def get_current_user(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    client_id = request.session.get('client_id')
    if user:
        return {"user": user}
    if client_id:
        client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
        if client:
            return {"user": {"email": client.email, "name": client.contact_name or client.company_name}}
    return JSONResponse(status_code=401, content={"error": "Not authenticated"})


@router.get("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@router.post("/api/client/forgot-password")
def forgot_password(body: ForgotPasswordIn, background_tasks: BackgroundTasks,
                    request: Request, db: Session = Depends(get_db)):
    """Send a reset link.

    The reply is the same whether or not the address has an account. Saying
    "no such account" would turn this into a way to find out who banks here.
    """
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"forgot:{ip}", max_requests=5, window=300):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    generic = {"message": "If that email has an account, a reset link is on its way."}
    email = (body.email or "").strip().lower()
    if not email:
        return generic

    client = db.query(models.DBClient).filter(
        sqlfunc.lower(models.DBClient.email) == email).first()
    if not client or not client.is_active:
        return generic

    token = issue_reset_token(db, "client", client.id, ip)
    log_login(db, client.id, client.email, "client", "password_reset_requested",
              request, "requested")
    db.commit()

    base = (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")
    link = f"{base}/reset-password.html?token={token}"
    company = client.company_name or "your account"
    from_email = default_from_email()

    text_body, html_body = reset_email_bodies(link, company, RESET_TOKEN_TTL_MINUTES)

    background_tasks.add_task(
        send_email_background, client.email, "Reset your password",
        text_body, f"Y ERP <{from_email}>", html_body, None, "", "",
        client_id=client.id,
    )
    return generic


@router.get("/api/client/reset-password")
def check_reset_token(token: str = "", db: Session = Depends(get_db)):
    """So the page can say the link is dead before someone types a new password."""
    return {"valid": find_valid_reset(db, token) is not None}


@router.post("/api/client/reset-password")
def reset_password(body: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"reset:{ip}", max_requests=10, window=300):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    row = find_valid_reset(db, body.token)
    if not row:
        raise HTTPException(status_code=400, detail="That reset link is invalid or has expired")
    validate_password_strength(body.password)

    if row.user_type == "member":
        subject = db.query(models.DBTeamMember).filter(
            models.DBTeamMember.id == row.member_id).first()
        if not subject or not subject.is_active:
            raise HTTPException(status_code=400,
                                detail="That link is invalid or has expired")
        subject.password_hash = hash_password(body.password)
        # Setting a password is how an invite is accepted.
        if not subject.accepted_at:
            subject.accepted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client_id, who = subject.client_id, subject.email
    elif row.user_type == "employee":
        subject = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == row.employee_id).first()
        if not subject or subject.status == "terminated":
            raise HTTPException(status_code=400,
                                detail="That reset link is invalid or has expired")
        subject.password_hash = passwords.hash_password(body.password)
        client_id, who = subject.client_id, subject.email
    else:
        subject = db.query(models.DBClient).filter(
            models.DBClient.id == row.client_id).first()
        if not subject:
            raise HTTPException(status_code=400,
                                detail="That reset link is invalid or has expired")
        subject.password_hash = hash_password(body.password)
        client_id, who = subject.id, subject.email

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.used_at = now
    # Spend every other outstanding link for the same account as well.
    spent = db.query(models.DBPasswordReset).filter(
        models.DBPasswordReset.user_type == row.user_type,
        models.DBPasswordReset.used_at == "",
    )
    spent_column, spent_value = {
        "client": (models.DBPasswordReset.client_id, row.client_id),
        "employee": (models.DBPasswordReset.employee_id, row.employee_id),
        "member": (models.DBPasswordReset.member_id, row.member_id),
    }[row.user_type]
    spent = spent.filter(spent_column == spent_value)
    spent.update({"used_at": now}, synchronize_session=False)

    log_login(db, client_id, who, row.user_type, "password_reset", request, "success")
    log_audit(db, client_id, "password_reset", row.user_type,
              row.employee_id or row.client_id, who, "", request)
    db.commit()
    return {"message": "Password updated. You can sign in now."}
