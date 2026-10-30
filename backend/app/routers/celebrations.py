"""Birthdays and special days: shown to everybody, reacted to with an emoji, answered with a message. HR adds special days."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.audit import log_audit
from app.core.auth import current_member, get_client_user, is_hr_or_master, require_hr_or_master
from app.db import get_db, get_read_db
from app.services import celebrations as svc

router = APIRouter()


class ReactIn(BaseModel):
    celebration: str
    emoji: str


class WishIn(BaseModel):
    celebration: str
    message: str


class SpecialDayIn(BaseModel):
    date: str
    name: str
    message: Optional[str] = ""
    emoji: Optional[str] = ""
    yearly: Optional[bool] = False


def _viewer(request: Request, db: Session):
    """Who is asking: (company id, author key, name). The company's own sign-in, or a member of staff - each sees
    the same celebrations, and each can react and write."""
    if request.session.get("client_id"):
        client = get_client_user(request, db)
        member = current_member(request, db)
        if member:
            return client.id, "m:%d" % member.id, member.name or member.email
        return client.id, "owner", client.contact_name or client.company_name or "The Master"
    emp_id = request.session.get("employee_id")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first() if emp_id else None
    if not emp or (emp.status or "active") in PAYROLL_EXCLUDED_STATUSES:
        raise HTTPException(status_code=401, detail="Not signed in")
    return emp.client_id, "e:%d" % emp.id, ("%s %s" % (emp.first_name, emp.last_name)).strip()


def _with_responses(db, client_id, me, items, hr):
    """Each celebration with its reactions (counted per emoji, marking the ones that are mine) and its messages."""
    keys = [c["key"] for c in items]
    reactions = db.query(models.DBCelebrationReaction).filter(
        models.DBCelebrationReaction.client_id == client_id,
        models.DBCelebrationReaction.celebration.in_(keys or [""])).order_by(models.DBCelebrationReaction.id).all()
    wishes = db.query(models.DBCelebrationWish).filter(
        models.DBCelebrationWish.client_id == client_id,
        models.DBCelebrationWish.celebration.in_(keys or [""])).order_by(models.DBCelebrationWish.id).all()
    out = []
    for c in items:
        counts = {}
        for r in (r for r in reactions if r.celebration == c["key"]):
            slot = counts.setdefault(r.emoji, {"emoji": r.emoji, "count": 0, "mine": False, "names": []})
            slot["count"] += 1
            slot["mine"] = slot["mine"] or r.author == me
            slot["names"].append(r.author_name)
        out.append({**c, "reactions": list(counts.values()),
                    "wishes": [{"id": w.id, "author": w.author_name, "message": w.message, "at": w.created_at,
                                "mine": w.author == me, "can_delete": hr or w.author == me}
                               for w in wishes if w.celebration == c["key"]]})
    return out


@router.get("/api/celebrations")
def celebrations_feed(request: Request, db: Session = Depends(get_read_db)):
    """Today's birthdays, festivals and special days with their reactions and messages, and what is coming in the next
    month. Everybody in the company sees the same."""
    client_id, me, _ = _viewer(request, db)
    today = date.today()
    hr = is_hr_or_master(request, db)
    return {"today": _with_responses(db, client_id, me, svc.celebrations_on(db, client_id, today), hr),
            "upcoming": svc.upcoming(db, client_id, today),
            "emojis": list(svc.REACTION_EMOJIS), "can_manage": hr}


@router.post("/api/celebrations/react")
def react(body: ReactIn, request: Request, db: Session = Depends(get_db)):
    """Put an emoji on a celebration, or take it back by sending the same one again."""
    client_id, me, name = _viewer(request, db)
    if body.emoji not in svc.REACTION_EMOJIS:
        raise HTTPException(status_code=400, detail="Pick one of the emoji offered.")
    if not svc.key_is_ours(db, client_id, body.celebration):
        raise HTTPException(status_code=404, detail="Celebration not found")
    q = db.query(models.DBCelebrationReaction).filter(
        models.DBCelebrationReaction.client_id == client_id, models.DBCelebrationReaction.celebration == body.celebration,
        models.DBCelebrationReaction.author == me, models.DBCelebrationReaction.emoji == body.emoji)
    had = q.first()
    if had:
        db.delete(had)
    else:
        db.add(models.DBCelebrationReaction(client_id=client_id, celebration=body.celebration, author=me,
                                            author_name=name, emoji=body.emoji))
    db.commit()
    return {"reacted": not had}


@router.post("/api/celebrations/wishes")
def add_wish(body: WishIn, request: Request, db: Session = Depends(get_db)):
    client_id, me, name = _viewer(request, db)
    message = " ".join((body.message or "").split())
    if not message:
        raise HTTPException(status_code=400, detail="Write a message first.")
    if len(message) > svc.MAX_WISH:
        raise HTTPException(status_code=400, detail="Keep the message to %d characters." % svc.MAX_WISH)
    if not svc.key_is_ours(db, client_id, body.celebration):
        raise HTTPException(status_code=404, detail="Celebration not found")
    wish = models.DBCelebrationWish(client_id=client_id, celebration=body.celebration, author=me, author_name=name,
                                    message=message)
    db.add(wish)
    # The birthday person is told when somebody writes to them, so a wish is not left unread for a day.
    parts = body.celebration.split(":")
    if parts[0] == "birthday" and ("e:%s" % parts[1]) != me:
        from app.core.notifications import notify_employee
        notify_employee(db, client_id, int(parts[1]), "%s wished you a happy birthday 🎉" % name, message, svc.LINK)
    db.commit()
    return {"id": wish.id}


@router.delete("/api/celebrations/wishes/{wish_id}")
def remove_wish(wish_id: int, request: Request, db: Session = Depends(get_db)):
    """Take a message down: its writer may, and so may HR and the Master."""
    client_id, me, _ = _viewer(request, db)
    wish = db.query(models.DBCelebrationWish).filter(models.DBCelebrationWish.id == wish_id,
                                                     models.DBCelebrationWish.client_id == client_id).first()
    if not wish:
        raise HTTPException(status_code=404, detail="Message not found")
    if wish.author != me and not is_hr_or_master(request, db):
        raise HTTPException(status_code=403, detail="You can only take down your own message.")
    db.delete(wish)
    db.commit()
    return {"message": "Message removed"}


# HR's own: the days it wants everybody told about, on top of the birthdays and India's festivals.

def _special_dict(h):
    return {"id": h.id, "date": h.date, "name": h.name, "message": h.message or "", "emoji": h.emoji or "",
            "yearly": bool(h.yearly)}


@router.get("/api/celebrations/special-days")
def list_special_days(request: Request, db: Session = Depends(get_read_db)):
    client = require_hr_or_master(request, db)
    rows = db.query(models.DBSpecialDay).filter(models.DBSpecialDay.client_id == client.id).order_by(models.DBSpecialDay.date).all()
    return [_special_dict(h) for h in rows]


@router.post("/api/celebrations/special-days")
def add_special_day(body: SpecialDayIn, request: Request, db: Session = Depends(get_db)):
    """Add a day to celebrate. One for today is announced to everybody at once; any other is announced on the day."""
    client = require_hr_or_master(request, db)
    day = svc.parse_day(body.date)
    if not day or len((body.date or "").strip()) != 10:
        raise HTTPException(status_code=400, detail="Pick the date.")
    name = " ".join((body.name or "").split())
    if not name:
        raise HTTPException(status_code=400, detail="Give the day a name.")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Keep the name to 100 characters.")
    message = " ".join((body.message or "").split())
    if len(message) > 300:
        raise HTTPException(status_code=400, detail="Keep the message to 300 characters.")
    emoji = (body.emoji or "").strip()
    if len(emoji) > 8:
        raise HTTPException(status_code=400, detail="Use a single emoji.")
    if db.query(models.DBSpecialDay.id).filter(models.DBSpecialDay.client_id == client.id, models.DBSpecialDay.date == day.isoformat(),
                                                models.DBSpecialDay.name == name).first():
        raise HTTPException(status_code=400, detail="%s is already added for that day." % name)
    row = models.DBSpecialDay(client_id=client.id, date=day.isoformat(), name=name, message=message, emoji=emoji,
                              yearly=bool(body.yearly), created_by=getattr(client, "email", "") or "")
    db.add(row)
    db.flush()
    today = date.today()
    announced = 0
    todays = [c for c in svc.celebrations_on(db, client.id, today) if c["kind"] == "special" and c["special_id"] == row.id]
    if todays:
        announced = svc.announce(db, client.id, todays, company=client.company_name or "")
        row.announced_on = today.isoformat()
    log_audit(db, client.id, "special_day_added", "special_day", row.id, name, day.isoformat(), request)
    out = _special_dict(row)
    db.commit()
    return {**out, "announced": announced}


@router.delete("/api/celebrations/special-days/{day_id}")
def remove_special_day(day_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_hr_or_master(request, db)
    row = db.query(models.DBSpecialDay).filter(models.DBSpecialDay.id == day_id, models.DBSpecialDay.client_id == client.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Special day not found")
    prefix = "special:%d:" % row.id
    for table in (models.DBCelebrationReaction, models.DBCelebrationWish):
        db.query(table).filter(table.client_id == client.id, table.celebration.like(prefix + "%")).delete(synchronize_session=False)
    log_audit(db, client.id, "special_day_removed", "special_day", row.id, row.name, row.date, request)
    db.delete(row)
    db.commit()
    return {"message": "Special day removed"}
