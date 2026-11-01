"""The Feed's announcements: what HR wants everybody in the company to read. Everybody signed in reads them; only HR and
the Master post, change or take them down. (Birthdays and special days are on the Feed too, from the celebrations router.)"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import defer
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
MAX_MEDIA, MAX_IMAGE_BYTES, MAX_VIDEO_BYTES = 6, 10 * 1024 * 1024, 50 * 1024 * 1024
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
VIDEO_TYPES = ("video/mp4", "video/webm", "video/quicktime")


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


def _media(m):
    return {"id": m.id, "kind": m.kind, "name": m.name or "", "content_type": m.content_type or "", "size": m.size or 0,
            "url": "/api/announcements/media/%d" % m.id}


def _dict(a, hr, today, media=()):
    expired = bool(a.expires_on) and a.expires_on < today
    return {"id": a.id, "title": a.title, "body": a.body or "", "category": a.category or "general", "pinned": bool(a.pinned),
            "expires_on": a.expires_on or "", "expired": expired, "posted_by": a.posted_by or "", "created_at": a.created_at,
            "updated_at": a.updated_at or "", "can_edit": hr, "media": [_media(m) for m in media]}


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
    media = _media_of(db, client_id, [a.id for a in shown])
    return {"announcements": [_dict(a, hr, today, media.get(a.id, ())) for a in shown], "can_post": hr, "categories": list(CATEGORIES)}


def _media_of(db, client_id, ids):
    """The photos and videos of these announcements, without their bytes, in one query."""
    M = models.DBAnnouncementMedia
    out = {}
    if ids:
        for m in db.query(M).options(defer(M.data)).filter(M.client_id == client_id, M.announcement_id.in_(ids)).order_by(M.id).all():
            out.setdefault(m.announcement_id, []).append(m)
    return out


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
    out = _dict(row, True, date.today().isoformat(), _media_of(db, client.id, [row.id]).get(row.id, ()))
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
    db.query(models.DBAnnouncementMedia).filter(models.DBAnnouncementMedia.announcement_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return {"message": "Announcement removed"}



def _sniff(data):
    """What the bytes really are, so a renamed file cannot pass as a picture or a video: (kind, content type) or None."""
    if data[:3] == b"\xff\xd8\xff":
        return "image", "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "video", "video/webm"
    if data[4:8] == b"ftyp":
        return "video", "video/quicktime" if data[8:12] == b"qt  " else "video/mp4"
    return None


@router.post("/api/announcements/{announcement_id}/media")
async def add_media(announcement_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Attach a photo or a video to an announcement."""
    client, row = _mine_to_change(db, request, announcement_id)
    M = models.DBAnnouncementMedia
    if db.query(M.id).filter(M.announcement_id == row.id).count() >= MAX_MEDIA:
        raise HTTPException(status_code=400, detail="An announcement holds up to %d photos and videos." % MAX_MEDIA)
    data = await file.read(MAX_VIDEO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    found = _sniff(data)
    if not found:
        raise HTTPException(status_code=400, detail="A photo (JPG, PNG, WebP, GIF) or a video (MP4, WebM, MOV).")
    kind, ctype = found
    if kind == "image" and len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="That photo is over %d MB." % (MAX_IMAGE_BYTES // 1048576))
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="That video is over %d MB. Shorten or compress it." % (MAX_VIDEO_BYTES // 1048576))
    m = M(client_id=client.id, announcement_id=row.id, kind=kind, name=(file.filename or kind)[:200], content_type=ctype, size=len(data), data=data)
    db.add(m)
    db.flush()
    log_audit(db, client.id, "announcement_media_added", "announcement", row.id, row.title, m.name, request)
    out = _media(m)
    db.commit()
    return out


@router.delete("/api/announcements/{announcement_id}/media/{media_id}")
def remove_media(announcement_id: int, media_id: int, request: Request, db: Session = Depends(get_db)):
    client, row = _mine_to_change(db, request, announcement_id)
    M = models.DBAnnouncementMedia
    m = db.query(M).options(defer(M.data)).filter(M.id == media_id, M.announcement_id == row.id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    log_audit(db, client.id, "announcement_media_removed", "announcement", row.id, row.title, m.name, request)
    db.delete(m)
    db.commit()
    return {"message": "Removed"}


@router.get("/api/announcements/media/{media_id}")
def get_media(media_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The bytes, to anybody signed in to this company. Honours Range so a video can be skipped through."""
    client_id, _me, _name = _viewer(request, db)
    m = db.query(models.DBAnnouncementMedia).filter(models.DBAnnouncementMedia.id == media_id,
                                                    models.DBAnnouncementMedia.client_id == client_id).first()
    if not m or not m.data:
        raise HTTPException(status_code=404, detail="Not found")
    data, total = m.data, len(m.data)
    headers = {"X-Content-Type-Options": "nosniff", "Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600",
               "Content-Security-Policy": "default-src 'none'; sandbox"}
    rng = request.headers.get("range", "")
    if rng.startswith("bytes=") and "," not in rng:
        a, _, b = rng[6:].partition("-")
        try:
            start = int(a) if a else max(0, total - int(b))
            end = min(int(b), total - 1) if (a and b) else total - 1
        except ValueError:
            start, end = 0, total - 1
        if start > end or start >= total:
            return Response(status_code=416, headers={**headers, "Content-Range": "bytes */%d" % total})
        headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, total)
        return Response(data[start:end + 1], status_code=206, media_type=m.content_type, headers=headers)
    return Response(data, media_type=m.content_type, headers=headers)
