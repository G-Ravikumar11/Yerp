"""Plain checks for what a form sends, shared by the Projects screens: a real date, a sensible number, a time of day.

Each raises a 400 that says what was wrong in the words a person would use, so the screen can show it as it is.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException


def day(raw, what, *, required=False, not_future=False, default_today=False, ahead_days=None):
    """A date as YYYY-MM-DD, or "" when it may be left blank. A date that is not a real one (31/02/2026, "yesterday") is refused."""
    text = (raw or "").strip()[:10]
    if not text:
        if default_today:
            return date.today().isoformat()
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return ""
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "The %s is not a date (use year-month-day, like 2026-10-31)." % what) from None
    if parsed.year < 2000 or parsed.year > 2100:
        raise HTTPException(400, "The %s does not look right: %s." % (what, text))
    if not_future and parsed > date.today():
        raise HTTPException(400, "The %s cannot be in the future." % what)
    if ahead_days is not None and parsed > date.today() + timedelta(days=ahead_days):
        raise HTTPException(400, "The %s cannot be more than %d days ahead." % (what, ahead_days))
    return parsed.isoformat()


def span(start, end, what="end date"):
    """An end date that comes before the start is a mistake."""
    if start and end and end < start:
        raise HTTPException(400, "The %s is before the start date." % what)


def between(value, what, low, high, *, unit="", blank_ok=True):
    """A number inside a range. Left out (None, or "" when blank_ok) it is passed through as None."""
    if value in (None, ""):
        if blank_ok:
            return None
        raise HTTPException(400, "Give the %s." % what)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "The %s must be a number." % what) from None
    if number != number or number < low or number > high:
        raise HTTPException(400, "The %s must be between %g and %g%s." % (what, low, high, (" " + unit) if unit else ""))
    return number


def clock(raw, what="time"):
    """A time of day as HH:MM (24 hours), or "" when left blank."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text[:5], "%H:%M").strftime("%H:%M")
    except ValueError:
        raise HTTPException(400, "The %s is not a time (use hours:minutes, like 14:30)." % what) from None
