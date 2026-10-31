"""Settings > Error log: every error the app answered with, for the Master to see - and screen crashes reported from
the browser. What each code means is in app/core/errors.py (CODES) and docs/error-codes.md.

The traceback of a fault is the platform's own code: the company sees that one is kept (quote the ref), the platform
admin reads it - every company's, under /api/superadmin/errors, with the spike watch (services/error_watch.py)."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.auth import get_client_user, require_owner, require_superadmin
from app.core.errors import CODES, new_ref
from app.db import get_db, get_read_db
from app.core.security import rate_limiter
from app.services.error_watch import spike   # importing it also registers the hourly spike watch

router = APIRouter()

AREAS = {"AUTH": "Signing in", "ACCESS": "Access", "DATA": "Records", "FILE": "Files", "BUSY": "Busy",
         "SRV": "Server faults", "NET": "No connection", "APP": "Screen faults"}


def screen_of(path: str) -> str:
    """The screen an error came from, with the record's number taken out: /api/bills/412/pay and /api/bills/9/pay are one."""
    import re
    p = (path or "").split("?")[0]
    return re.sub(r"/\d+(?=/|$)", "/{id}", p) or "-"


def groups_of(rows, with_company=None):
    """The errors grouped by code and screen: how many, when last, the latest ref - the few causes behind many errors."""
    out = {}
    for r in rows:
        key = (r.code or "", screen_of(r.path), r.client_id if with_company else None)
        g = out.get(key)
        if g is None:
            g = out[key] = {"code": r.code or "", "screen": key[1], "count": 0, "last_at": "", "last_ref": ""}
            if with_company:
                g["company"] = with_company.get(r.client_id, "")
        g["count"] += 1
        if (r.at or "") >= g["last_at"]:
            g["last_at"], g["last_ref"] = r.at or "", r.ref or ""
    # The biggest first; of the same size, the most recent.
    return sorted(out.values(), key=lambda g: (g["count"], g["last_at"]), reverse=True)


def _area(code: str) -> str:
    parts = (code or "").split("-")
    return parts[1] if len(parts) > 1 else ""


def _names(db, client, rows):
    """Who, in words: the owner's name, a colleague's or a member of staff's, or the email tried at sign-in."""
    members = {"member:%d" % m.id: (m.name or m.email or "") for m in db.query(models.DBTeamMember).filter(
        models.DBTeamMember.client_id == client.id).all()} if any(r.who.startswith("member:") for r in rows) else {}
    staff_ids = [int(r.who.split(":")[1]) for r in rows if r.who.startswith("employee:") and r.who.split(":")[1].isdigit()]
    staff = {"employee:%d" % e.id: (e.full_name or e.email or "") for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.id.in_(staff_ids or [0])).all()}
    owner = client.contact_name or client.email or "Master"
    return lambda who: owner if who == "owner" else members.get(who) or staff.get(who) or who or "-"


@router.get("/api/errors")
def error_log(request: Request, area: str = "", q: str = "", days: int = 30, db: Session = Depends(get_read_db)):
    """The company's errors, newest first. The Master only."""
    require_owner(request, db)
    client = get_client_user(request, db)
    days = max(1, min(int(days or 30), 90))
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    base = db.query(models.DBErrorLog).filter(models.DBErrorLog.client_id == client.id, models.DBErrorLog.at >= since)
    by_area = {}
    for (code,) in base.with_entities(models.DBErrorLog.code).all():
        by_area[_area(code)] = by_area.get(_area(code), 0) + 1
    rows = base
    if area:
        rows = rows.filter(models.DBErrorLog.code.like("YE-%s%%" % area.upper()))
    words = (q or "").strip()
    if words:
        like = "%%%s%%" % words
        rows = rows.filter(models.DBErrorLog.ref.ilike(like) | models.DBErrorLog.path.ilike(like)
                           | models.DBErrorLog.detail.ilike(like) | models.DBErrorLog.code.ilike(like)
                           | models.DBErrorLog.who.ilike(like))
    rows = rows.order_by(models.DBErrorLog.id.desc()).limit(300).all()
    groups = groups_of(rows)
    name = _names(db, client, rows)
    return {"errors": [{"id": r.id, "at": r.at, "code": r.code, "title": CODES.get(r.code) or {
                            "YE-APP": "A screen hit a problem", "YE-NET": "Could not reach the server"}.get(r.code, ""),
                        "ref": r.ref, "status": r.status or 0, "method": r.method or "", "path": r.path or "",
                        "detail": r.detail or "", "who": name(r.who or ""), "trace": "",
                        # The traceback stays with the platform; the company is told one is kept, under the ref.
                        "has_trace": bool(r.trace)} for r in rows],
            "areas": AREAS, "groups": groups, "summary": {"total": sum(by_area.values()), "by_area": by_area, "days": days}}


@router.get("/api/superadmin/errors")
def platform_errors(request: Request, area: str = "", q: str = "", client_id: int = 0, days: int = 7,
                    db: Session = Depends(get_read_db)):
    """Every company's errors with their tracebacks, newest first, and whether server faults are spiking. The platform
    admin only."""
    require_superadmin(request)
    days = max(1, min(int(days or 7), 90))
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.query(models.DBErrorLog).filter(models.DBErrorLog.at >= since)
    if client_id:
        rows = rows.filter(models.DBErrorLog.client_id == client_id)
    if area:
        rows = rows.filter(models.DBErrorLog.code.like("YE-%s%%" % area.upper()))
    words = (q or "").strip()
    if words:
        like = "%%%s%%" % words
        rows = rows.filter(models.DBErrorLog.ref.ilike(like) | models.DBErrorLog.path.ilike(like)
                           | models.DBErrorLog.detail.ilike(like) | models.DBErrorLog.code.ilike(like)
                           | models.DBErrorLog.trace.ilike(like))
    rows = rows.order_by(models.DBErrorLog.id.desc()).limit(300).all()
    names = {c.id: (c.company_name or c.email or "") for c in db.query(models.DBClient).filter(
        models.DBClient.id.in_({r.client_id for r in rows if r.client_id} or {0})).all()}
    return {"errors": [{"id": r.id, "at": r.at, "code": r.code, "ref": r.ref, "status": r.status or 0, "method": r.method or "",
                        "path": r.path or "", "detail": r.detail or "", "who": r.who or "", "client_id": r.client_id,
                        "company": names.get(r.client_id, "") if r.client_id else "", "trace": r.trace or ""} for r in rows],
            "areas": AREAS, "groups": groups_of(rows, names), "spike": spike(db), "days": days}


class ScreenFault(BaseModel):
    ref: str = ""
    path: str = ""
    message: str = ""
    stack: str = ""


@router.post("/api/errors/report")
def report_screen_fault(body: ScreenFault, request: Request, db: Session = Depends(get_db)):
    """A screen crashed in the browser (YE-APP): the page reports itself so it shows in the error log too."""
    client_id = request.session.get("client_id") or request.session.get("employee_client_id")
    if not client_id:
        raise HTTPException(401, "Not signed in")
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited("screen_fault:%s" % ip, max_requests=20, window=60):
        return {"kept": False}
    who = ("member:%s" % request.session["member_id"]) if request.session.get("member_id") else (
        "employee:%s" % request.session["employee_id"]) if request.session.get("employee_id") else "owner"
    ref = "".join(ch for ch in (body.ref or "").upper() if ch in "0123456789ABCDEF")[:8] or new_ref()
    db.add(models.DBErrorLog(client_id=client_id, code="YE-APP", ref=ref, status=0, method="SCREEN",
                             path=(body.path or "")[:300], detail=(body.message or "")[:1000], who=who,
                             trace=(body.stack or "")[-8000:]))
    db.commit()
    return {"kept": True, "ref": ref}
