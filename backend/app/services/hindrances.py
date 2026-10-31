"""The hindrance register: what held the work up on a site, whose risk it was, what it cost in days and when the client was told.

A delay is argued months later from this register, not from memory, so each entry is dated, numbered per site and kept with the
diary it was raised from. A day's diary already says what held the work up and how many hours it rained; raising a hindrance from
it starts from those words instead of typing them again.
"""
import re
from datetime import date, datetime

from fastapi import HTTPException

from app import models
from app.constants.projects import HINDRANCE_CAUSES, HINDRANCE_PARTIES, HINDRANCE_STATUSES
from app.core import checks
from app.core.currency import money

# Words in a diary's "held up by" that say what the cause was, first match wins. Rain comes last: "rain" also appears in "drain".
CAUSE_WORDS = (
    ("Drawings or details awaited", r"drawing|detail|gfc|design"),
    ("Client decision awaited", r"decision|client.*(approv|confirm|instruct)|awaiting (approval|confirmation|instruction)"),
    ("Site or front not handed over", r"front|hand ?over|handed over|access|encroach"),
    ("Payment held up", r"payment|bill|fund"),
    ("Utility shifting", r"utility|electric pole|cable|pipeline shift|ht line|transformer"),
    ("Change in scope", r"scope|variation|extra item|revised"),
    ("Statutory approval", r"permit|permission|noc|municipal|ghmc|police|authority"),
    ("Plant breakdown", r"breakdown|broke down|jcb|mixer|crane|machine|pump"),
    ("Material shortage", r"material|cement|steel|sand|aggregate|brick|shortage|not delivered|supply"),
    ("Labour shortage", r"labour|labor|mason|worker|crew|gang|strike"),
    ("Rain / weather", r"\brain|\bwet|weather|storm|flood|waterlog"),
)
# Whose risk each cause usually is. A suggestion the form starts from; the person raising it decides.
USUAL_PARTY = {
    "Rain / weather": "Neither (force majeure)", "Drawings or details awaited": "Client", "Client decision awaited": "Client",
    "Site or front not handed over": "Client", "Payment held up": "Client", "Utility shifting": "Client", "Change in scope": "Client",
    "Statutory approval": "Client", "Material shortage": "Contractor", "Labour shortage": "Contractor", "Plant breakdown": "Contractor",
}
CLOSED = ("Closed", "Rejected")


def _day(raw):
    try:
        return datetime.strptime((raw or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def guess_cause(words):
    text = (words or "").lower()
    for cause, pattern in CAUSE_WORDS:
        if re.search(pattern, text):
            return cause
    return "Other"


def hindrance_or_404(db, client_id, hid):
    h = db.query(models.DBHindrance).filter(models.DBHindrance.id == hid, models.DBHindrance.client_id == client_id).first()
    if not h:
        raise HTTPException(404, "Hindrance not found")
    return h


def running_days(h, today=None):
    """Calendar days it has held the work up: from its first day to its last, or to today while it is still going on."""
    start = _day(h.from_date)
    end = _day(h.to_date) or (today or date.today())
    if not start or end < start:
        return 0
    return (end - start).days + 1


def hindrance_dict(h, names=None, today=None):
    names = names or {}
    return {"id": h.id, "job_id": h.job_id, "number": h.number or "", "activity_id": h.activity_id, "activity": names.get(h.activity_id, ""),
            "diary_id": h.diary_id, "cause": h.cause or "", "description": h.description or "", "from_date": h.from_date or "",
            "to_date": h.to_date or "", "ongoing": not h.to_date, "running_days": running_days(h, today),
            "responsibility": h.responsibility or "", "impact_days": money(h.impact_days or 0), "notice_date": h.notice_date or "",
            "status": h.status or "Open", "open": (h.status or "Open") not in CLOSED,
            # The client's risk and not yet told in writing: the notice is what a claim fails on, so it is called out.
            "notice_due": (h.responsibility or "") == "Client" and not h.notice_date and (h.status or "Open") not in CLOSED,
            "created_by_name": h.created_by_name or "", "created_at": h.created_at or ""}


def activity_names(db, job_id):
    rows = db.query(models.DBScheduleActivity.id, models.DBScheduleActivity.code, models.DBScheduleActivity.name).filter(
        models.DBScheduleActivity.job_id == job_id).all()
    return {i: ((c or "") + " " + (n or "")).strip() for i, c, n in rows}


def register(db, client_id, job, activity_id=None):
    """The site's hindrances, latest first, with what they add up to by whose risk they were."""
    q = db.query(models.DBHindrance).filter(models.DBHindrance.client_id == client_id, models.DBHindrance.job_id == job.id)
    if activity_id:
        q = q.filter(models.DBHindrance.activity_id == activity_id)
    names = activity_names(db, job.id)
    rows = [hindrance_dict(h, names) for h in q.order_by(models.DBHindrance.from_date.desc(), models.DBHindrance.id.desc()).all()]
    counted = [r for r in rows if r["status"] != "Rejected"]
    by_party = {p: money(sum(r["impact_days"] for r in counted if r["responsibility"] == p)) for p in HINDRANCE_PARTIES}
    return {"hindrances": rows,
            "summary": {"total": len(rows), "open": sum(1 for r in rows if r["open"]), "ongoing": sum(1 for r in rows if r["ongoing"] and r["open"]),
                        "impact_days": money(sum(r["impact_days"] for r in counted)), "client_days": by_party["Client"],
                        "notice_due": sum(1 for r in rows if r["notice_due"]), "by_party": by_party},
            "choices": {"causes": list(HINDRANCE_CAUSES), "parties": list(HINDRANCE_PARTIES), "statuses": list(HINDRANCE_STATUSES)}}


def next_number(db, job_id):
    used = [n for (n,) in db.query(models.DBHindrance.number).filter(models.DBHindrance.job_id == job_id).all()]
    top = max([int(m.group(1)) for m in (re.match(r"H-(\d+)$", n or "") for n in used) if m] or [0])
    return "H-%03d" % (top + 1)


def apply_hindrance(db, client_id, job, h, body, creating):
    """Check what the form sent and put it on the hindrance. On a change, whatever was left out stays as it was."""
    def given(field):
        return getattr(body, field) is not None

    if creating or given("cause"):
        cause = (body.cause or "").strip()
        if cause not in HINDRANCE_CAUSES:
            raise HTTPException(400, "Choose what held the work up from the list.")
        h.cause = cause
    if given("description"):
        h.description = (body.description or "").strip()[:2000]
    if creating or given("from_date"):
        h.from_date = checks.day(body.from_date, "date it started", required=True, not_future=True)
    if given("to_date"):
        h.to_date = checks.day(body.to_date, "date it ended", not_future=True)
    checks.span(h.from_date, h.to_date, "date it ended")
    if given("responsibility"):
        party = (body.responsibility or "").strip()
        if party and party not in HINDRANCE_PARTIES:
            raise HTTPException(400, "Choose whose risk it was from the list.")
        h.responsibility = party
    if given("notice_date"):
        h.notice_date = checks.day(body.notice_date, "date the client was told", not_future=True)
        if h.notice_date and h.from_date and h.notice_date < h.from_date:
            raise HTTPException(400, "The client cannot have been told before it started.")
    if given("impact_days"):
        h.impact_days = money(checks.between(body.impact_days, "days it cost", 0, 3650, unit="days") or 0)
    elif creating:
        # Not said: the days it ran, when it is over. While it is still going on it stays 0 until someone says what it cost.
        h.impact_days = float(running_days(h)) if h.to_date else 0.0
    if given("status"):
        status = (body.status or "").strip()
        if status not in HINDRANCE_STATUSES:
            raise HTTPException(400, "Choose a status from the list.")
        h.status = status
    elif creating:
        h.status = "Notified" if h.notice_date else "Open"
    if h.status == "Closed" and not h.to_date:
        raise HTTPException(400, "Give the date it ended before closing it.")
    if given("activity_id"):
        if body.activity_id:
            a = db.query(models.DBScheduleActivity.id).filter(models.DBScheduleActivity.id == body.activity_id,
                                                              models.DBScheduleActivity.job_id == job.id).first()
            if not a:
                raise HTTPException(400, "That activity is not on this site's programme.")
        h.activity_id = body.activity_id or None
    if creating and body.diary_id:
        d = db.query(models.DBSiteDiary.id).filter(models.DBSiteDiary.id == body.diary_id, models.DBSiteDiary.client_id == client_id,
                                                   models.DBSiteDiary.job_id == job.id).first()
        if not d:
            raise HTTPException(400, "That diary is not one of this site's.")
        h.diary_id = body.diary_id


def draft_from_diary(db, client_id, diary):
    """A hindrance as the day's diary describes it: what held the work up, or the rain, on that day; whose risk it usually is."""
    held = (diary.holdups or "").strip()
    rain = float(diary.rain_hours or 0)
    hours = float(diary.working_hours or 8) or 8.0
    cause = guess_cause(held) if held else ("Rain / weather" if rain > 0 else "Other")
    if cause == "Rain / weather" and rain > 0:
        # The share of the working day lost, to the half day: 3 hours of an 8 hour day is half a day.
        days = min(1.0, round(rain / hours * 2) / 2) or 0.5
        words = held or "%g hours of rain on %s." % (rain, diary.diary_date)
    else:
        days, words = 1.0, held
    already = db.query(models.DBHindrance).filter(models.DBHindrance.client_id == client_id,
                                                  models.DBHindrance.diary_id == diary.id).all()
    names = activity_names(db, diary.job_id)
    return {"draft": {"job_id": diary.job_id, "diary_id": diary.id, "cause": cause, "description": words, "from_date": diary.diary_date or "",
                      "to_date": diary.diary_date or "", "responsibility": USUAL_PARTY.get(cause, ""), "impact_days": days,
                      "notice_date": "", "status": "Open", "activity_id": None},
            "has_cause": bool(held or rain > 0),
            "already": [hindrance_dict(h, names) for h in already]}


def register_sheet(db, client, job):
    """The register as a workbook: one row a hindrance, and the days added up by whose risk they were."""
    reg = register(db, client.id, job)
    headers = ("No.", "Cause", "Description", "Activity", "From", "To", "Days it ran", "Days lost", "Whose risk", "Client told on",
               "Status", "Raised by")
    rows = [(r["number"], r["cause"], r["description"], r["activity"], r["from_date"], r["to_date"] or "still going on", r["running_days"],
             r["impact_days"], r["responsibility"] or "-", r["notice_date"] or ("NOT YET" if r["notice_due"] else "-"), r["status"],
             r["created_by_name"]) for r in sorted(reg["hindrances"], key=lambda r: (r["from_date"], r["number"]))]
    preamble = [("HINDRANCE REGISTER", client.company_name or ""),
                ("Site", "%s %s" % (job.number or "", job.name or ""), "Printed", date.today().isoformat()), ()]
    s = reg["summary"]
    closing = [(), ("Days lost, by whose risk (rejected ones left out)",)]
    closing += [(p, s["by_party"][p]) for p in HINDRANCE_PARTIES]
    closing += [("All", s["impact_days"]), ("Open", s["open"]), ("Client's risk, not yet told in writing", s["notice_due"])]
    return headers, rows, preamble, closing
