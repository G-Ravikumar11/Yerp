"""Daily reminders: probation ending, contracts ending, and statutory documents expiring or expired.

Each reminder goes out on a few milestone days rather than every day, so a notice means something:

    probation     15, 7 and 1 days before the end date, and on the day           HR's bell and the person's manager
    contract      30, 15, 7 and 1 days before, on the day, and the day after      HR's bell and the person's manager
                  if they are still on the books
    documents     the requirement's own reminder window (30 days unless set),     the employee, and HR's bell
                  7 days before, on the day, then weekly for eight weeks after

HR's bell gets one notice per kind per day, listing everybody, rather than one per person.
"""
from datetime import datetime

from app import models
from app.core.config import logger
from app.constants.common import PAYROLL_EXCLUDED_STATUSES
from app.core.dates import _parse_date
from app.core.scheduler import daily_key, scheduled_job

PROBATION_DAYS = (15, 7, 1, 0)
CONTRACT_DAYS = (30, 15, 7, 1, 0, -1)
DOC_AFTER_WEEKS = 8


def _name(emp):
    return ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()


def _when(days):
    return "today" if days == 0 else "tomorrow" if days == 1 else "yesterday" if days == -1 else \
        "in %d days" % days if days > 0 else "%d days ago" % -days


def doc_due(days_left, window):
    """Whether a document expiring in `days_left` days (negative once expired) is reminded about today."""
    if days_left in (window, 7, 0):
        return True
    return days_left < 0 and -days_left % 7 == 0 and -days_left <= DOC_AFTER_WEEKS * 7


def due_today(db, client_id, today):
    """{"probation": [(emp, days)], "contract": [...], "documents": [(emp, request, days)]} for one company."""
    people = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id,
                                                models.DBEmployee.status.notin_(PAYROLL_EXCLUDED_STATUSES)).all()
    out = {"probation": [], "contract": [], "documents": []}
    if not people:
        return out
    for emp in people:
        for field, kind, days_set in (("probation_end_date", "probation", PROBATION_DAYS),
                                      ("contract_end_date", "contract", CONTRACT_DAYS)):
            end = _parse_date(getattr(emp, field, None) or "")
            if end and (end - today).days in days_set:
                out[kind].append((emp, (end - today).days))
    by_id = {e.id: e for e in people}
    R = models.DBDocumentRequest
    for req in db.query(R).filter(R.client_id == client_id, R.expires_on != "", R.expires_on.isnot(None),
                                  R.employee_id.in_(list(by_id))).all():
        expires = _parse_date(req.expires_on)
        if not expires:
            continue
        window = int(getattr(req.requirement, "expiry_reminder_days", None) or 30) if req.requirement else 30
        days = (expires - today).days
        if doc_due(days, window):
            out["documents"].append((by_id[req.employee_id], req, days))
    return out


def send(db, client_id, found):
    """Puts the day's reminders where they belong. Returns how many people were told about."""
    from app.core.notifications import notify, notify_employee
    told = 0
    for kind, title, view in (("probation", "Probation ending", "people"), ("contract", "Contract ending", "people")):
        items = found[kind]
        if not items:
            continue
        for emp, days in items:
            if emp.reports_to:
                notify_employee(db, client_id, emp.reports_to, "%s: %s" % (title, _name(emp)),
                                "%s's %s %s %s." % (_name(emp), kind, "ends" if days >= 0 else "ended", _when(days)),
                                link="/people/%d" % emp.id)
        listed = "; ".join("%s (%s)" % (_name(e), _when(d)) for e, d in sorted(items, key=lambda x: x[1]))
        action = "Confirm them, extend it, or let them go." if kind == "probation" else "Renew it or plan their last day."
        notify(db, client_id, "%s_ending" % kind, "%s: %d %s" % (title, len(items), "person" if len(items) == 1 else "people"),
               "%s. %s" % (listed, action), view=view, severity="action")
        told += len(items)
    docs = found["documents"]
    if docs:
        for emp, req, days in docs:
            verb = "expires" if days >= 0 else "expired"
            notify_employee(db, client_id, emp.id, "%s %s %s" % (req.name, verb, _when(days)),
                            "Upload the renewed %s so your record stays complete." % req.name, link="/me/documents")
        listed = "; ".join("%s - %s (%s %s)" % (_name(e), r.name, "expires" if d >= 0 else "expired", _when(d))
                           for e, r, d in sorted(docs, key=lambda x: x[2]))
        expired = sum(1 for _e, _r, d in docs if d < 0)
        notify(db, client_id, "documents_expiring", "%d document%s expiring or expired" % (len(docs), "" if len(docs) == 1 else "s"),
               listed + ".", view="people", severity="action" if expired else "info")
        told += len(docs)
    db.commit()
    return told


@scheduled_job("hr_reminders", daily_key)
def job_hr_reminders(db, now):
    today = now.date() if isinstance(now, datetime) else now
    done, failed = [], []
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        try:
            n = send(db, client.id, due_today(db, client.id, today))
        except Exception as exc:
            # One company's trouble must not leave everybody else without their reminders today.
            db.rollback()
            logger.exception("HR reminders failed for client %s", client.id)
            failed.append("%s: %s" % (client.id, exc))
            continue
        if n:
            done.append("%s:%d" % (client.id, n))
    summary = "reminders for " + (", ".join(done) if done else "nobody")
    if failed:
        raise RuntimeError("%s. Failed for %s" % (summary, "; ".join(failed)))      # recorded as a failed run, with what did get done
    return summary
