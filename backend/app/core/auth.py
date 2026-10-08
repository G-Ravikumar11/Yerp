"""Who is calling: the signed-in company, staff member or partner, and what each may do."""
import contextvars
import hashlib
import os
import secrets

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal

from app.core.config import ADMIN_PANEL_MIN_LENGTH, logger
from app.core.permissions import PORTAL_PERMISSIONS, employee_can
from app.core.security import admin_panel_password, hash_password, verify_password


def ensure_admin_user():
    try:
        with SessionLocal() as db:
            existing_admin = db.query(models.DBAdminUser).first()
            wanted = admin_panel_password()
            if not existing_admin:
                # With no password set, the row exists with one nobody knows.
                db.add(models.DBAdminUser(username="admin",
                                          password=hash_password(wanted or secrets.token_urlsafe(32))))
                db.commit()
                logger.info("Created the admin panel user (username=admin)")
            elif wanted and not verify_password(wanted, existing_admin.password or ""):
                # The environment is the one place the password is set.
                existing_admin.password = hash_password(wanted)
                db.commit()
                logger.info("Admin panel password taken from ADMIN_PASSWORD")
            if not wanted:
                logger.warning("The /admin panel is closed: set ADMIN_PASSWORD (at least %d characters) "
                               "to open it.", ADMIN_PANEL_MIN_LENGTH)
    except Exception as e:
        logger.error(f"Admin user init failed: {e}")


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# The company whose request this is, once it is known: a workbook built deep inside a route heads itself
# with the company's identity without every route passing it down.
CURRENT_CLIENT_ID = contextvars.ContextVar("current_client_id", default=None)


def get_client_user(request: Request, db: Session):
    client_id = request.session.get("client_id")
    if not client_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client or not client.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    CURRENT_CLIENT_ID.set(client.id)

    # Read-only members are stopped here rather than on each endpoint. Every
    # route that touches tenant data resolves the tenant through this function,
    # so there is one place to get right instead of two hundred to remember.
    member_id = request.session.get("member_id")
    if member_id:
        member = db.query(models.DBTeamMember).filter(
            models.DBTeamMember.id == member_id, models.DBTeamMember.client_id == client.id).first()
        if not member or not member.is_active:
            request.session.clear()
            raise HTTPException(status_code=401, detail="Your access has been removed")
        if member.role == "viewer" and request.method in WRITE_METHODS:
            raise HTTPException(status_code=403,
                                detail="Your account has read-only access.")
    return client


def end_every_session(request: Request):
    """Signing out ends every sign-in this browser holds - the owner's, a member's, a member of staff's and
    a partner's. A browser can hold two at once (an owner who also tried a staff login), and ending only
    the one the screen showed left the other to sign the person straight back in at the login page."""
    request.session.clear()


def ensure_super_admin():
    with SessionLocal() as db:
        env_emails = [e.strip().lower() for e in os.getenv("SUPERADMIN_EMAILS", "").split(",") if e.strip()]
        existing_all = db.query(models.DBSuperAdmin).all()
        existing_emails = {e.email.strip().lower() for e in existing_all if e.email}
        for em in env_emails:
            if em not in existing_emails:
                db.add(models.DBSuperAdmin(username="superadmin", password_hash="", email=em))
                existing_emails.add(em)
        pwd = os.getenv("SUPERADMIN_PASSWORD", "")
        if pwd:
            # The variable sets the password when it is first given or changed; a password changed in the panel
            # since then stays - it used to be put back from the variable at every restart.
            fingerprint = hashlib.sha256(pwd.encode()).hexdigest()
            mark = db.query(models.DBSettings).filter(models.DBSettings.client_id.is_(None),
                                                      models.DBSettings.key == "superadmin_env_password").first()
            changed = not mark or mark.value != fingerprint
            for sa in db.query(models.DBSuperAdmin).all():
                if changed or not sa.password_hash:
                    sa.password_hash = hash_password(pwd)
            if not mark:
                db.add(models.DBSettings(client_id=None, key="superadmin_env_password", value=fingerprint))
            elif changed:
                mark.value = fingerprint
        db.commit()
        logger.info("Super admin setup complete (%d admins)", len(env_emails))


def owned_or_404(db, model, client_id, ident, what):
    """An id that arrived in a request body, checked to be this company's before it is stored."""
    if not ident:
        return None
    if not db.query(model.id).filter(model.id == ident, model.client_id == client_id).first():
        raise HTTPException(status_code=404, detail="%s not found" % what)
    return ident


def require_items_access(request, db, permission="items.manage"):
    """The tenant behind this request, from either kind of session.

    The account holder owns the tenancy and holds everything. A member of
    staff needs the named right, which HR grants. Returns the tenant either
    way, so every caller keeps working off `client.id` and none of them has to
    know which sort of session it was.
    """
    try:
        return get_client_user(request, db)
    except HTTPException as exc:
        # 401 means "no owner session" - a member of staff may still be signed
        # in. Anything else (a disabled account, a read-only member) is a real
        # refusal and must not be retried as somebody else.
        if exc.status_code != 401:
            raise

    emp = get_employee_user(request, db)
    # One right, or several of which any will do: the plant register is kept
    # by the store and by the project office alike.
    wanted = (permission,) if isinstance(permission, str) else tuple(permission or ())
    if wanted and not any(employee_can(emp, p) for p in wanted):
        label = " or ".join(next((p["label"] for p in PORTAL_PERMISSIONS if p["key"] == w), w)
                            for w in wanted)
        raise HTTPException(
            status_code=403,
            detail="Your access does not include: " + label + ". Ask HR if you need it.")
    client = db.query(models.DBClient).filter(
        models.DBClient.id == emp.client_id).first()
    if not client or not client.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    return client


def require_workorder_access(request, db):
    return require_items_access(request, db, "workorders.manage")


def require_erp_read(request, db):
    """Reading the master data. Anyone signed in to this tenancy: a person
    picking a code from a list has to be able to see the list."""
    return require_items_access(request, db, None)


def current_member(request: Request, db: Session):
    """The signed-in team member, or None when it is the account owner."""
    member_id = request.session.get("member_id")
    if not member_id:
        return None
    return db.query(models.DBTeamMember).filter(
        models.DBTeamMember.id == member_id).first()


def current_role(request: Request, db: Session) -> str:
    member = current_member(request, db)
    return (member.role if member else "owner")


def require_owner(request: Request, db: Session):
    if current_role(request, db) != "owner":
        raise HTTPException(status_code=403,
                            detail="Only the account Master can do that")


def get_employee_user(request: Request, db: Session):
    """The employee behind an employee-portal session.

    The tenant is read from the employee row rather than the session, so a
    stale `employee_client_id` can never point somebody at another company's
    data.
    """
    emp_id = request.session.get("employee_id")
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not signed in")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=401, detail="Not signed in")
    if emp.status in ("terminated",):
        raise HTTPException(status_code=403, detail="Account deactivated")
    client = db.query(models.DBClient).filter(models.DBClient.id == emp.client_id).first()
    if not client or not client.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    STAFF_VIEWER.set(emp.id)
    CURRENT_CLIENT_ID.set(client.id)
    return emp


# The member of staff this request is for, once it has been worked out - so a
# lookup deep inside a route can ask "may this person see it" without every
# route passing the person down. Unset for the owner. One per request.
STAFF_VIEWER = contextvars.ContextVar("staff_viewer", default=None)


def require_employee_permission(request: Request, db: Session, permission: str):
    """Employee session + a specific right. The message names the action rather
    than saying "forbidden", so the person knows to ask HR for it."""
    emp = get_employee_user(request, db)
    if not employee_can(emp, permission):
        label = next((p["label"] for p in PORTAL_PERMISSIONS if p["key"] == permission),
                     permission)
        raise HTTPException(
            status_code=403,
            detail=f"Your access does not include: {label}. Ask HR if you need it.",
        )
    return emp


def require_superadmin(request):
    if not request.session.get("superadmin_id"):
        raise HTTPException(status_code=401, detail="Not authorized")


def wo_actor(request, db, permission="workorders.manage"):
    """The tenant, plus who is doing this, for the approval history."""
    client = require_items_access(request, db, permission)
    name, actor_id = "", None
    try:
        emp = get_employee_user(request, db)
        if emp:
            actor_id = emp.id
            name = ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()
    except Exception:
        name = client.company_name or "Account holder"
    return client, actor_id, (name or "Account holder")


def session_employee(request, db):
    """The member of staff behind this request, or None for the owner."""
    try:
        get_client_user(request, db)
        return None
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    try:
        return get_employee_user(request, db)
    except HTTPException:
        return None


def session_person(request, db):
    """The tenant and, for a staff login, the member of staff."""
    try:
        return get_client_user(request, db), None
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    emp = get_employee_user(request, db)
    client = db.query(models.DBClient).filter(models.DBClient.id == emp.client_id).first()
    if not client or not client.is_active:
        raise HTTPException(403, "Account disabled")
    return client, emp
