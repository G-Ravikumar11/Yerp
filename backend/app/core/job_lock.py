"""Job Lock: a project the Master has locked takes no change from anybody - the Master included - until the Master
unlocks it.

The rule is kept where every save passes, not in each of the hundreds of routes: before anything is written, each new,
changed or deleted record is followed up to the project it belongs to - its own job_id or project_id, or its parent's
(a BOQ line through its BOQ, a bill line through its bill, a store issue line through its issue), up to three steps - and
the save is refused if that project is locked. A screen added later is covered without anybody remembering to.

Left alone: what the server does by itself (the nightly jobs run outside any request), the records that only note that
something was read or sent, and the lock itself. Reading a locked project is never refused.
"""
from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app import models
from app.db.session import Base

# Writes that change nothing on the project (a message marked read, a document opened or sent), and people's own time
# and postings: a locked site must not leave anybody clocked in for ever or out of a day's pay, and HR still moves people.
QUIET_TABLES = {"project_thread_reads", "audit_logs", "attendance", "employee_sites", "department_sites", "notifications", "employee_notifications", "error_logs",
                "site_report_runs", "qc_cube_due_notices", "delay_alerts", "clock_refusals", "drawing_traces"}
QUIET_FIELDS = {"open_count", "last_opened", "sent", "viewed_at", "updated_at"}
LOCK_FIELDS = {"is_locked", "locked_at", "locked_by_name", "lock_reason"}
JOB_COLUMNS = ("job_id", "project_id", "current_job_id")
MAX_STEPS = 3


class LockedProject(HTTPException):
    def __init__(self, job):
        why = (": %s" % job.lock_reason) if job.lock_reason else ""
        super().__init__(423, "%s is locked by the Master%s. Nothing on it can be changed until the Master unlocks it." % (
            ("%s %s" % (job.number or "", job.name or "")).strip() or "This project", why))


# The locked projects' ids, kept in memory: few projects are ever locked, and asking on every save would add a trip to
# each one. Refreshed the moment the Master locks or unlocks (forget), and from the database at most a minute old.
_LOCKED = {"ids": None, "at": 0.0}
FRESH_S = 60


def forget():
    _LOCKED["ids"] = None


def _locked_ids(session):
    import time
    if _LOCKED["ids"] is None or time.time() - _LOCKED["at"] > FRESH_S:
        _LOCKED["ids"] = {i for (i,) in session.query(models.DBJob.id).filter(models.DBJob.is_locked.is_(True)).all()}
        _LOCKED["at"] = time.time()
    return _LOCKED["ids"]


def _in_request() -> bool:
    from app.core.middleware import REQUEST_DB
    return REQUEST_DB.get() is not None


def _table_of(name):
    return Base.metadata.tables.get(name)


def _jobs_of_row(session, table, values, steps):
    """The projects a row belongs to: its own project columns, then its parents', step by step."""
    found = set()
    if table.name == "jobs" and values.get("id"):
        found.add(values["id"])
    for col in JOB_COLUMNS:
        if col in table.c and values.get(col):
            found.add(values[col])
    if found or steps >= MAX_STEPS:
        return found
    for c in table.c:
        if not c.foreign_keys or not values.get(c.name):
            continue
        parent = list(c.foreign_keys)[0].column.table
        if parent.name in ("clients", "employees", "erp_items", "contractors", "suppliers", "users", "team_members"):
            continue
        row = session.execute(select(parent).where(parent.c.id == values[c.name])).mappings().first()
        if row is not None:
            found |= _jobs_of_row(session, parent, dict(row), steps + 1)
    return found


def _jobs_of(session, obj, deleted):
    state = inspect(obj)
    table = state.mapper.local_table
    if table is None or table.name in QUIET_TABLES:
        return set()
    if not deleted and state.persistent:
        changed = {a.key for a in state.attrs if a.history.has_changes()}
        if not changed or changed <= QUIET_FIELDS:
            return set()
        if table.name == "jobs" and changed <= LOCK_FIELDS | QUIET_FIELDS:
            return set()                               # locking or unlocking it is the one thing allowed
    values = {c.name: getattr(obj, state.mapper.get_property_by_column(c).key, None) for c in table.c
              if state.mapper.get_property_by_column(c) is not None}
    # Old values too: a record moved off a locked project is still a change on it.
    if state.persistent:
        for col in JOB_COLUMNS:
            if col in table.c:
                hist = state.attrs[state.mapper.get_property_by_column(table.c[col]).key].history
                for old in hist.deleted or ():
                    if old:
                        values.setdefault("_old_" + col, old)
    found = _jobs_of_row(session, table, values, 0)
    found |= {v for k, v in values.items() if k.startswith("_old_") and v}
    # A new child whose parent is set as an object, not yet as its id.
    for rel in state.mapper.relationships:
        if rel.direction.name != "MANYTOONE":
            continue
        parent = state.attrs[rel.key].loaded_value
        if parent is not None and not isinstance(parent, (list, tuple)) and hasattr(parent, "__table__"):
            for col in JOB_COLUMNS:
                if getattr(parent, col, None):
                    found.add(getattr(parent, col))
    return found


@event.listens_for(Session, "before_flush")
def _refuse_on_locked(session, flush_context, instances):
    if not _in_request():
        return
    pending = [(o, False) for o in session.new] + [(o, False) for o in session.dirty] + [(o, True) for o in session.deleted]
    if not pending:
        return
    with session.no_autoflush:
        locked = _locked_ids(session)
        if not locked:
            return
        for obj, deleted in pending:
            for job_id in _jobs_of(session, obj, deleted):
                if job_id in locked:
                    raise LockedProject(session.get(models.DBJob, job_id))
