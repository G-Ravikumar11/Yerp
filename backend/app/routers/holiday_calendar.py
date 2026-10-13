"""The calendar's public holidays."""
from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

import holidays

from app.core.auth import get_client_user
from app.db import get_db

router = APIRouter()

FIRST_YEAR, LAST_YEAR = 2000, 2100


@lru_cache(maxsize=32)
def holidays_for(year):
    """One year's list. Working the moving festivals out takes about a second, and a
    year's holidays never change, so each year is worked out once per process."""
    return tuple({"date": d.isoformat(), "name": name} for d, name in sorted(holidays.India(years=year).items()))


@router.get("/api/calendar/holidays")
def public_holidays(request: Request, year: int = 0, db: Session = Depends(get_db)):
    """India's public holidays for one year, in date order (this year when none is given).

    The moving festivals (Diwali, Holi, the Eids...) come from the `holidays`
    package rather than a list kept here, so each year's dates do not need
    typing in by hand.
    """
    get_client_user(request, db)
    year = year or datetime.now().year
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise HTTPException(status_code=400, detail="Pick a year between %d and %d" % (FIRST_YEAR, LAST_YEAR))
    return list(holidays_for(year))
