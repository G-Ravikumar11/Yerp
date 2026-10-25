"""The calendar's holidays: India's public ones, and the days the business marks off itself."""
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import holidays

from app import models
from app.core.audit import log_audit
from app.core.auth import get_client_user, require_owner
from app.db import get_db, get_read_db

router = APIRouter()

FIRST_YEAR, LAST_YEAR = 2000, 2100
MAX_DAYS = 366      # one range may mark up to a year's worth of days


class HolidayIn(BaseModel):
    date: str
    # The last day, when it is a run of days. Left out, it is the one day.
    end_date: Optional[str] = None
    name: str


@lru_cache(maxsize=32)
def holidays_for(year):
    """One year's list. Working the moving festivals out takes about a second, and a
    year's holidays never change, so each year is worked out once per process."""
    return tuple({"date": d.isoformat(), "name": name} for d, name in sorted(holidays.India(years=year).items()))


def _check_year(year):
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise HTTPException(status_code=400, detail="Pick a year between %d and %d" % (FIRST_YEAR, LAST_YEAR))


def _custom_dict(h):
    return {"date": h.date, "name": h.name, "custom": True, "id": h.id}


@router.get("/api/calendar/holidays")
def public_holidays(request: Request, year: int = 0, db: Session = Depends(get_read_db)):
    """One year's holidays in date order (this year when none is given): India's public
    holidays, and the days this business has marked off itself, which carry `custom` and an `id`.

    The moving festivals (Diwali, Holi, the Eids...) come from the `holidays`
    package rather than a list kept here, so each year's dates do not need
    typing in by hand.
    """
    client = get_client_user(request, db)
    year = year or datetime.now().year
    _check_year(year)
    own = db.query(models.DBCustomHoliday).filter(
        models.DBCustomHoliday.client_id == client.id,
        models.DBCustomHoliday.date.like("%d-%%" % year)).all()
    merged = [{**h, "custom": False} for h in holidays_for(year)] + [_custom_dict(h) for h in own]
    return sorted(merged, key=lambda h: (h["date"], h["custom"]))


def _day(raw, what):
    try:
        day = datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Pick the %s date" % what)
    _check_year(day.year)
    return day


@router.post("/api/calendar/holidays")
def add_holiday(body: HolidayIn, request: Request, db: Session = Depends(get_db)):
    """Mark a day, or a run of days from `date` to `end_date`, as holidays for the whole business.
    Every employee has them off. A day already marked is left as it is."""
    client = get_client_user(request, db)
    require_owner(request, db)
    first = _day(body.date, "first" if body.end_date else "")
    last = _day(body.end_date, "last") if body.end_date else first
    if last < first:
        raise HTTPException(status_code=400, detail="The last day cannot be before the first")
    count = (last - first).days + 1
    if count > MAX_DAYS:
        raise HTTPException(status_code=400, detail="Mark up to %d days at a time" % MAX_DAYS)
    name = " ".join((body.name or "").split())
    if not name:
        raise HTTPException(status_code=400, detail="Give the holiday a name")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Keep the name to 100 characters")
    days = [(first + timedelta(days=i)).isoformat() for i in range(count)]
    taken = {h.date: h.name for h in db.query(models.DBCustomHoliday).filter(
        models.DBCustomHoliday.client_id == client.id, models.DBCustomHoliday.date.in_(days)).all()}
    if len(taken) == len(days):
        only = next(iter(taken.items()))
        raise HTTPException(status_code=400, detail=(
            "%s is already marked as a holiday: %s" % (first.strftime("%d %b %Y"), only[1]) if len(days) == 1
            else "Every one of those days is already marked as a holiday"))
    made = [models.DBCustomHoliday(client_id=client.id, date=d, name=name, created_by=getattr(client, "email", "") or "")
            for d in days if d not in taken]
    db.add_all(made)
    db.flush()
    log_audit(db, client.id, "holiday_added", "holiday", made[0].id, name,
              first.isoformat() if len(made) == 1 else "%s to %s (%d days)" % (first.isoformat(), last.isoformat(), len(made)), request)
    out = {"added": len(made), "skipped": len(taken), "holidays": [_custom_dict(h) for h in made]}
    db.commit()
    return out


@router.delete("/api/calendar/holidays/{holiday_id}")
def remove_holiday(holiday_id: int, request: Request, db: Session = Depends(get_db)):
    """Take a day the business marked as a holiday back to an ordinary day."""
    client = get_client_user(request, db)
    require_owner(request, db)
    row = db.query(models.DBCustomHoliday).filter(
        models.DBCustomHoliday.id == holiday_id, models.DBCustomHoliday.client_id == client.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Holiday not found")
    log_audit(db, client.id, "holiday_removed", "holiday", row.id, row.name, row.date, request)
    db.delete(row)
    db.commit()
    return {"message": "Holiday removed"}
