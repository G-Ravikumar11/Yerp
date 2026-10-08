"""Dates, financial years and working days."""
import calendar
from datetime import date, datetime, timedelta


def days_after(on, days):
    """The date `days` after `on` (a date or a timestamp string), or "" when
    `on` is not a date. When a bill falls due, from when it was signed."""
    try:
        d = datetime.strptime(str(on or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    return (d + timedelta(days=int(days or 0))).isoformat()


def _parse_date(value):
    """Parse a YYYY-MM-DD string, returning None when unusable."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def advance_date(from_date, frequency):
    """The next occurrence after `from_date`.

    Month arithmetic clamps to the end of a short month, so a template set to
    the 31st still runs in February instead of skipping it.
    """
    if frequency == "weekly":
        return from_date + timedelta(days=7)
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(frequency, 1)
    month_index = from_date.month - 1 + months
    year = from_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(from_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


DEFAULT_WORKING_DAYS = "1,2,3,4,5"          # Monday to Friday


def parse_working_days(raw):
    """ISO weekday numbers: Monday is 1, Sunday is 7.

    Anything unparseable falls back to a normal working week rather than an
    empty set, because an empty set would mean nobody is ever working and every
    day would silently look like a day off.
    """
    days = set()
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            n = int(part)
        except ValueError:
            continue
        if 1 <= n <= 7:
            days.add(n)
    return days or {1, 2, 3, 4, 5}


def financial_year_label(on_date=None):
    """2026-27, the Indian year the order belongs to."""
    d = datetime.now()
    if on_date:
        try:
            d = datetime.strptime(str(on_date)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    start = d.year if d.month >= 4 else d.year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def ageing_bucket(due_on, today=None):
    """Which column a debt belongs in.

    Not due is kept apart from nought to thirty on purpose: money that is not
    late yet is not a problem, and mixing the two makes a healthy ledger look
    like a chase list.
    """
    today = today or date.today()
    d = _parse_date(due_on)
    if not d:
        # No due date is not the same as not due - it cannot be chased on a
        # date, so it sits in the oldest bucket where somebody will see it.
        return "90+", None
    days = (today - d).days
    if days < 0:
        return "Not due", days
    if days <= 30:
        return "0-30", days
    if days <= 60:
        return "31-60", days
    if days <= 90:
        return "61-90", days
    return "90+", days


def _days_until(value):
    try:
        return (datetime.strptime(str(value)[:10], "%Y-%m-%d").date() - date.today()).days
    except (ValueError, TypeError):
        return None


def months_after(on, months):
    """The date `months` calendar months after `on`, or "" when it is not a
    date. The last day of a short month stands in for a day it lacks."""
    try:
        d = datetime.strptime(str(on or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    m = d.month - 1 + int(months or 0)
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def ack_datetime(text):
    t = (text or "").strip().split(".")[0].replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M:%S %p",
                "%d-%m-%Y %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None
