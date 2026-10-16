"""Settings > Error log: every error the app answered with, for the Master to see - and screen crashes reported from
the browser. What each code means is in app/core/errors.py (CODES) and docs/error-codes.md."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.auth import get_client_user, require_owner
from app.core.errors import CODES, new_ref
from app.db import get_db
from app.core.security import rate_limiter

router = APIRouter()

AREAS = {"AUTH": "Signing in", "ACCESS": "Access", "DATA": "Records", "FILE": "Files", "BUSY": "Busy",
         "SRV": "Server faults", "NET": "No connection", "APP": "Screen faults"}


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
def error_log(request: Request, area: str = "", q: str = "", days: int = 30, db: Session = Depends(get_db)):
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
    name = _names(db, client, rows)
    return {"errors": [{"id": r.id, "at": r.at, "code": r.code, "title": CODES.get(r.code) or {
                            "YE-APP": "A screen hit a problem", "YE-NET": "Could not reach the server"}.get(r.code, ""),
                        "ref": r.ref, "status": r.status or 0, "method": r.method or "", "path": r.path or "",
                        "detail": r.detail or "", "who": name(r.who or ""), "trace": r.trace or ""} for r in rows],
            "areas": AREAS, "summary": {"total": sum(by_area.values()), "by_area": by_area, "days": days}}


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
