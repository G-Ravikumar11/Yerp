"""The Feed's announcements: what HR wants everybody in the company to read. Everybody signed in reads them; only HR and
the Master post, change or take them down. (Birthdays and special days are on the Feed too, from the celebrations router.)"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.audit import log_audit
from app.core.auth import is_hr_or_master, require_hr_or_master
from app.db import get_db, get_read_db
from app.routers.celebrations import _viewer
from app.services.celebrations import parse_day

router = APIRouter()

CATEGORIES = ("general", "site", "holiday", "important")
MAX_TITLE, MAX_BODY, SHOWN = 120, 2000, 50
LINK = "/feed"


class AnnouncementIn(BaseModel):
    title: str
    body: Optional[str] = ""
    category: Optional[str] = "general"
    pinned: Optional[bool] = False
    expires_on: Optional[str] = ""
    notify: Optional[bool] = True          # tell every employee on the bell and the phone (new posts only)


def _clean(body: AnnouncementIn):
    title = " ".join((body.title or "").split())
    if not title:
        raise HTTPException(status_code=400, detail="Give the announcement a title.")
    if len(title) > MAX_TITLE:
        raise HTTPException(status_code=400, detail="Keep the title to %d characters." % MAX_TITLE)
    text = (body.body or "").replace("\r\n", "\n").strip()
    if len(text) > MAX_BODY:
        raise HTTPException(status_code=400, detail="Keep the message to %d characters." % MAX_BODY)
    category = (body.category or "general").strip().lower()
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Choose a kind of announcement: %s." % ", ".join(CATEGORIES))
    expires = (body.expires_on or "").strip()
    if expires:
        day = parse_day(expires)
        if not day or len(expires) != 10:
            raise HTTPException(status_code=400, detail="Give the last day it should show as a date.")
        expires = day.isoformat()
    return title, text, category, bool(body.pinned), expires


def _dict(a, hr, today):
    expired = bool(a.expires_on) and a.expires_on < today
    return {"id": a.id, "title": a.title, "body": a.body or "", "category": a.category or "general", "pinned": bool(a.pinned),
            "expires_on": a.expires_on or "", "expired": expired, "posted_by": a.posted_by or "", "created_at": a.created_at,
            "updated_at": a.updated_at or "", "can_edit": hr}


@router.get("/api/announcements")
def list_announcements(request: Request, db: Session = Depends(get_read_db)):
    """The Feed's announcements, pinned first and newest first. One that has passed its last day is left out for staff;
    HR still sees it, marked, so it can be put right or removed."""
    client_id, _me, _name = _viewer(request, db)
    hr = is_hr_or_master(request, db)
    today = date.today().isoformat()
    A = models.DBAnnouncement
    rows = db.query(A).filter(A.client_id == client_id).order_by(A.pinned.desc(), A.created_at.desc(), A.id.desc()).all()
    shown = [a for a in rows if hr or not a.expires_on or a.expires_on >= today][:SHOWN]
    return {"announcements": [_dict(a, hr, today) for a in shown], "can_post": hr, "categories": list(CATEGORIES)}


def _tell_everyone(db, client_id, title, text, by):
    """One notice each on the bell, and the phone's push, for every employee still on the books."""
    from app.core.notifications import notify_employee
    told = 0
    for emp in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id,
                                                  models.DBEmployee.status.notin_(PAYROLL_EXCLUDED_STATUSES)).all():
        notify_employee(db, client_id, emp.id, "Announcement: %s" % title, (text[:200] or "From %s" % by), link=LINK)
        told += 1
    return told


@router.post("/api/announcements")
def post_announcement(body: AnnouncementIn, request: Request, db: Session = Depends(get_db)):
    client = require_hr_or_master(request, db)
    title, text, category, pinned, expires = _clean(body)
    _client_id, me, name = _viewer(request, db)
    row = models.DBAnnouncement(client_id=client.id, title=title, body=text, category=category, pinned=pinned,
                                expires_on=expires, posted_by=name, posted_by_key=me)
    db.add(row)
    db.flush()
    told = _tell_everyone(db, client.id, title, text, name) if body.notify is not False else 0
    log_audit(db, client.id, "announcement_posted", "announcement", row.id, title, category, request)
    out = _dict(row, True, date.today().isoformat())
    db.commit()
    return {**out, "told": told}


def _mine_to_change(db, request, announcement_id):
    client = require_hr_or_master(request, db)
    row = db.query(models.DBAnnouncement).filter(models.DBAnnouncement.id == announcement_id,
                                                  models.DBAnnouncement.client_id == client.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return client, row


@router.put("/api/announcements/{announcement_id}")
def change_announcement(announcement_id: int, body: AnnouncementIn, request: Request, db: Session = Depends(get_db)):
    client, row = _mine_to_change(db, request, announcement_id)
    row.title, row.body, row.category, row.pinned, row.expires_on = _clean(body)
    row.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client.id, "announcement_changed", "announcement", row.id, row.title, row.category, request)
    out = _dict(row, True, date.today().isoformat())
    db.commit()
    return out


@router.post("/api/announcements/{announcement_id}/pin")
def pin_announcement(announcement_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Keep one at the top of the Feed, or let it go back into its place."""
    client, row = _mine_to_change(db, request, announcement_id)
    row.pinned = bool((body or {}).get("pinned", not row.pinned))
    log_audit(db, client.id, "announcement_pinned" if row.pinned else "announcement_unpinned", "announcement", row.id, row.title, "", request)
    db.commit()
    return {"id": row.id, "pinned": row.pinned}


@router.delete("/api/announcements/{announcement_id}")
def remove_announcement(announcement_id: int, request: Request, db: Session = Depends(get_db)):
    client, row = _mine_to_change(db, request, announcement_id)
    log_audit(db, client.id, "announcement_removed", "announcement", row.id, row.title, "", request)
    db.delete(row)
    db.commit()
    return {"message": "Announcement removed"}
