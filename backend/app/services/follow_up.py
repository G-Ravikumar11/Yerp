"""Quality and safety items followed up: an NCR, an incident or a work permit has an owner on the staff and a due date,
and the owner is reminded every day from the day before it is due until it is closed.

  NCR        due on its target date; open until closed or rejected.
  incident   due on the date its corrective action is to be done by; open until closed.
  permit     due when it runs out (valid to); a permit still live after that is the owner's to close, so the
             reminders start once it has run out - a permit runs a shift, not days.

The bell is told once when an item goes overdue. Reminders go in the owner's own notices (and to their phone): this
is the company's own staff, never anybody outside it.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core.config import logger
from app.core.notifications import notify, notify_employee
from app.core.scheduler import scheduled_job

LIVE = ("active", "onboarding", "offboarding")      # on the staff: somebody who has left is never given a follow-up

KINDS = {
    "ncr": {"model": models.DBNcr, "label": "NCR", "view": "quality-view", "link": "/next/projects/quality?ncr=%d",
            "due": lambda r: (r.target_date or "")[:10], "open": lambda r: (r.status or "OPEN") not in ("CLOSED", "REJECTED"),
            "what": lambda r: r.description or r.location or ""},
    "incident": {"model": models.DBSafetyIncident, "label": "Incident", "view": "safety-view", "link": "/next/projects/safety",
                 "due": lambda r: (r.due_date or "")[:10], "open": lambda r: r.status == "OPEN",
                 "what": lambda r: "%s: %s" % (r.kind or "", r.description or "")},
    "permit": {"model": models.DBWorkPermit, "label": "Permit", "view": "safety-view", "link": "/next/projects/safety",
               "due": lambda r: (r.valid_to or "")[:10], "open": lambda r: r.status == "ACTIVE",
               "what": lambda r: "%s at %s" % (r.kind or "", r.location or "the site")},
}


def _when(kind, row, today, now):
    """'due tomorrow' | 'due today' | 'overdue since ...' - or None when no reminder is owed today."""
    due = KINDS[kind]["due"](row)
    if not due:
        return None
    if kind == "permit":
        # Live until its time runs out that day: only a permit past its time is followed up.
        return ("still open - it ran out at %s" % row.valid_to) if (row.valid_to or "") < now.strftime("%Y-%m-%d %H:%M") else None
    today_s = today.isoformat()
    if due < today_s:
        return "overdue since %s" % due
    if due == today_s:
        return "due today"
    if due == (today + timedelta(days=1)).isoformat():
        return "due tomorrow"
    return None


def owner_or_400(db, client_id, owner_id):
    """The active employee named as owner, or None to clear it."""
    if not owner_id:
        return None
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == int(owner_id), models.DBEmployee.client_id == client_id).first()
    if emp is None or (emp.status or "active") not in LIVE:
        raise HTTPException(400, "Choose somebody on the staff to see it through.")
    return emp


def tell_new_owner(db, client_id, kind, row, actor):
    k = KINDS[kind]
    due = k["due"](row)
    notify_employee(db, client_id, row.owner_id, "%s %s is yours to see through" % (k["label"], row.number),
                    "%s%s. Given to you by %s." % (k["what"](row)[:300], (" Due %s" % due) if due else "", actor or "the office"),
                    link=k["link"] % row.id if "%d" in k["link"] else k["link"])


@scheduled_job("quality_safety_follow_up")
def job_follow_up(db, now):
    """Every open item with an owner: reminded once a day from the day before it is due; the bell told once when late."""
    now = now if isinstance(now, datetime) else datetime.now()
    today = now.date()
    reminded = told = 0
    for kind, k in KINDS.items():
        M = k["model"]
        for row in db.query(M).filter(M.owner_id.isnot(None)).all():
            if not k["open"](row):
                continue
            when = _when(kind, row, today, now)
            if not when or (row.reminded_on or "") == today.isoformat():
                continue
            link = k["link"] % row.id if "%d" in k["link"] else k["link"]
            text = "%s %s is %s: %s" % (k["label"], row.number, when, k["what"](row)[:300])
            notify_employee(db, row.client_id, row.owner_id, "%s %s: %s" % (k["label"], row.number, when), text, link=link)
            row.reminded_on = today.isoformat()
            reminded += 1
            late = when.startswith("overdue") or kind == "permit"
            if late and not row.overdue_told:
                from app.services.hr import employee_name
                emp = db.get(models.DBEmployee, row.owner_id)
                notify(db, row.client_id, "qc_failed" if kind == "ncr" else "safety_incident",
                       "%s %s is overdue" % (k["label"], row.number),
                       "%s Owner: %s." % (text, employee_name(emp) if emp else "-"), view=k["view"], ref_type=kind, ref_id=row.id,
                       severity="action")
                row.overdue_told = 1
                told += 1
        db.commit()
    logger.info("follow-up: %d reminders, %d overdue notices", reminded, told)
    return "%d reminders, %d overdue notices" % (reminded, told)


def summary(row, kind):
    return {"kind": kind, "id": row.id, "number": row.number, "owner_id": row.owner_id, "due_date": KINDS[kind]["due"](row)}
