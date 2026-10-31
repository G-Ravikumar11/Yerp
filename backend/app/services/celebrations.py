"""Birthdays and special days: who is celebrating when, and telling everybody on the day.

A birthday comes from the date of birth HR (or the employee) has entered; only the day and the month are ever shown.
A special day is either a festival - India's public holidays, worked out by the `holidays` package - or one HR added.
Each celebration has a key that its reactions and wishes hang from: birthday:<employee>:<year>, festival:<date> or
special:<id>:<year>.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.config import logger
from app.core.notifications import notify, notify_employee
from app.core.scheduler import scheduled_job

# The few emoji a person can react with: enough to be warm, few enough to read at a glance.
REACTION_EMOJIS = ("🎂", "🎉", "🥳", "👏", "❤️", "🙏", "😊", "🎁")
MAX_WISH = 300
UPCOMING_DAYS = 30
LINK = "/celebrations"


def parse_day(raw):
    try:
        return datetime.strptime((raw or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def clean_birth_date(value):
    """A real date in the past, as YYYY-MM-DD; or nothing."""
    value = (value or "").strip()
    if not value:
        return ""
    day = parse_day(value)
    if not day or len(value) != 10:
        raise HTTPException(status_code=400, detail="Date of birth must be a date, like 1996-05-14.")
    if day >= date.today() or day.year < 1900:
        raise HTTPException(status_code=400, detail="Date of birth must be a day in the past.")
    return day.isoformat()


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _falls_on(born, day):
    """Whether a birthday (or a yearly day) kept as `born` is on `day`. 29 February is kept on the 28th in other years."""
    if born.month == 2 and born.day == 29 and not _leap(day.year):
        return day.month == 2 and day.day == 28
    return (born.month, born.day) == (day.month, day.day)


def _is_staff(e):
    return (e.status or "active") not in PAYROLL_EXCLUDED_STATUSES


def _name(e):
    return ("%s %s" % (e.first_name, e.last_name)).strip()


def festivals_on(day):
    from app.routers.holiday_calendar import holidays_for
    return [h["name"] for h in holidays_for(day.year) if h["date"] == day.isoformat()]


def celebrations_on(db, client_id, day, staff=None, special=None):
    """Everything to celebrate on `day`, birthdays first. `staff` and `special` are the company's people and its own
    special days, when already read."""
    if staff is None:
        staff = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
    if special is None:
        special = db.query(models.DBSpecialDay).filter(models.DBSpecialDay.client_id == client_id).order_by(models.DBSpecialDay.id).all()
    out = []
    for e in sorted(staff, key=lambda e: (e.first_name or "", e.last_name or "")):
        born = parse_day(e.date_of_birth)
        if born and _is_staff(e) and _falls_on(born, day):
            out.append({"key": "birthday:%d:%d" % (e.id, day.year), "kind": "birthday", "date": day.isoformat(),
                        "title": "%s's birthday" % _name(e), "emoji": "🎂", "message": "", "employee_id": e.id,
                        "employee_name": _name(e), "job_title": e.job_title or ""})
    for h in special:
        when = parse_day(h.date)
        if when and (_falls_on(when, day) if h.yearly else when == day):
            out.append({"key": "special:%d:%d" % (h.id, day.year), "kind": "special", "date": day.isoformat(), "title": h.name,
                        "emoji": h.emoji or "🎉", "message": h.message or "", "special_id": h.id})
    names = festivals_on(day)
    if names:
        # One festival key a day: two on the same date share their reactions and messages.
        out.append({"key": "festival:%s" % day.isoformat(), "kind": "festival", "date": day.isoformat(),
                    "title": " / ".join(names), "emoji": "🪔", "message": ""})
    return out


def upcoming(db, client_id, today, days=UPCOMING_DAYS):
    staff = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
    special = db.query(models.DBSpecialDay).filter(models.DBSpecialDay.client_id == client_id).order_by(models.DBSpecialDay.id).all()
    rows = []
    for i in range(1, days + 1):
        day = today + timedelta(days=i)
        for c in celebrations_on(db, client_id, day, staff, special):
            rows.append({**c, "days_away": i})
    return rows


def key_is_ours(db, client_id, key):
    """Whether a celebration key names something in this company, so nobody reacts to another company's day."""
    parts = (key or "").split(":")
    try:
        if parts[0] == "birthday" and len(parts) == 3 and parts[2].isdigit():
            return bool(db.query(models.DBEmployee.id).filter(models.DBEmployee.id == int(parts[1]),
                                                              models.DBEmployee.client_id == client_id).first())
        if parts[0] == "special" and len(parts) == 3 and parts[2].isdigit():
            return bool(db.query(models.DBSpecialDay.id).filter(models.DBSpecialDay.id == int(parts[1]),
                                                                models.DBSpecialDay.client_id == client_id).first())
        if parts[0] == "festival" and len(parts) == 2:
            return parse_day(parts[1]) is not None
    except ValueError:
        pass
    return False


def announce(db, client_id, celebrations, staff=None, company=""):
    """Tell everybody about these celebrations: a greeting for the birthday person, a notice for each colleague, and
    the office bell for the Master. Returns how many notices went out. The caller commits."""
    if not celebrations:
        return 0
    if staff is None:
        staff = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
    people = [e for e in staff if _is_staff(e)]
    sent = 0
    for c in celebrations:
        if c["kind"] == "birthday":
            first = (c["employee_name"].split() or [""])[0]
            for e in people:
                if e.id == c["employee_id"]:
                    notify_employee(db, client_id, e.id, "Happy Birthday, %s! 🎂" % first,
                                    "Everyone at %s wishes you a wonderful day and a great year ahead." % (company or "the company"), LINK)
                else:
                    notify_employee(db, client_id, e.id, "It's %s's birthday today 🎂" % c["employee_name"],
                                    "Say happy birthday with a reaction or a message.", LINK)
                sent += 1
        else:
            body = c["message"] or "Wishing everybody a happy %s." % c["title"]
            for e in people:
                notify_employee(db, client_id, e.id, "%s %s" % (c["emoji"], c["title"]), body, LINK)
                sent += 1
        notify(db, client_id, "celebration", "%s %s" % (c["emoji"], c["title"]),
               "Birthday of %s." % c["employee_name"] if c["kind"] == "birthday" else (c["message"] or c["title"]), view="celebrations")
    return sent


@scheduled_job("celebrations")
def job_celebrations(db, now):
    """Each morning: tell everybody about whatever is being celebrated today. A special day HR added for today was
    already announced when it was added, and is not told twice."""
    today = now.date()
    by_client = {}
    for e in db.query(models.DBEmployee).all():
        if e.client_id:
            by_client.setdefault(e.client_id, []).append(e)
    sent = 0
    for client_id, staff in by_client.items():
        todays = [c for c in celebrations_on(db, client_id, today, staff)
                  if not (c["kind"] == "special" and _announced_today(db, c["special_id"], today))]
        if not todays:
            continue
        client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
        try:
            sent += announce(db, client_id, todays, staff, (client.company_name if client else "") or "")
            db.commit()
        except Exception:
            logger.exception("Celebrations for company %s were not announced", client_id)
            db.rollback()
    return "%d notice(s)" % sent


def _announced_today(db, special_id, today):
    row = db.query(models.DBSpecialDay.announced_on).filter(models.DBSpecialDay.id == special_id).first()
    return bool(row) and row[0] == today.isoformat()
