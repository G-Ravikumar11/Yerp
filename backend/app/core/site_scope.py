"""A member of staff put on particular sites works on those sites.

HR assigns people to projects (Employees > Sites). Everything the staff portal books already honours that, but the Projects
portal's own screens - the site diary, the schedule, workers and their papers, safety records, quality records, drawings -
looked records up by number and the company only, so a person assigned to one project could read and change another's by
asking for it (the menu never offered it, but the server did not refuse).

The rule is applied once, where every lookup passes, instead of in each of the hundred or so routes: while a request is
for a member of staff who is limited to certain sites, every query for a project, or for a record that belongs to one,
is narrowed to those sites. That covers lists, a single record by its number, counts, exports and PDFs alike, and a record
that is out of reach is simply not found (404), which does not give away that it exists.

Who is limited is decided by `accessible_job_ids_for` (services/employee_portal.py), the rule the staff portal already
uses: head office and anyone with the company-wide rights (reports, billing, bills, work orders) see every project; a
person assigned to sites, or managing projects, or leading a crew, sees those; a person assigned to nothing sees
everything (HR's "none ticked means every site"). The owner, and the Master's colleagues, are never limited.
"""
from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from app import models
from app.core.auth import ACTING_EMPLOYEE
from app.core.cache import cached_read

# Records that belong to a project (job_id), and the Projects portal screens that show them. A record with no project
# (a checklist template, a file kept on no site) is the company's and stays visible.
SCOPED = (
    models.DBSiteDiary, models.DBScheduleActivity, models.DBScheduleLink, models.DBScheduleTask, models.DBScheduleBaseline,
    models.DBScheduleCalendar, models.DBScheduleHoliday, models.DBWorkerScreening, models.DBSafetyIncident,
    models.DBToolboxTalk, models.DBWorkPermit, models.DBEquipmentCheck, models.DBDrawing, models.DBCubeSet,
    models.DBInspection, models.DBNcr, models.DBQcChecklist, models.DBQcCriteria, models.DBFile,
)
BUSY = "site_scope_busy"


def allowed_jobs(session, emp):
    """None for no limit, else the set of project ids this person may use. Worked out once a short while, not per query."""
    from app.services.employee_portal import accessible_job_ids_for
    session.info[BUSY] = True                       # working it out reads projects and assignments: not narrowed itself
    try:
        got = cached_read(("site-scope", emp.id), lambda: accessible_job_ids_for(session, emp), ttl=30)
    finally:
        session.info.pop(BUSY, None)
    return got


def out_of_reach(session, client_id, job_id):
    """True when the project exists in this company but this member of staff is not put on it. Asked only after a lookup
    found nothing, so a screen can say why ("you are not assigned to that site") instead of "not found"."""
    if ACTING_EMPLOYEE.get() is None or not job_id:
        return False
    session.info[BUSY] = True
    try:
        return session.query(models.DBJob.id).filter(models.DBJob.id == job_id, models.DBJob.client_id == client_id).first() is not None
    finally:
        session.info.pop(BUSY, None)


@event.listens_for(Session, "do_orm_execute")
def _narrow_to_sites(state):
    if not state.is_select or state.session.info.get(BUSY):
        return
    emp = ACTING_EMPLOYEE.get()
    if emp is None:                                 # the owner, a colleague, or no one signed in: nothing to narrow
        return
    allowed = allowed_jobs(state.session, emp)
    if allowed is None:
        return
    ids = sorted(allowed) or [0]
    # Only for the records this query reads (a query for invoices carries none of this): the rule is cheap to apply, not to build.
    touched = {m.class_ for m in state.all_mappers}
    rules = []
    if models.DBJob in touched:
        rules.append(with_loader_criteria(models.DBJob, models.DBJob.id.in_(ids), include_aliases=True))
    rules += [with_loader_criteria(m, or_(m.job_id.is_(None), m.job_id.in_(ids)), include_aliases=True) for m in SCOPED if m in touched]
    if rules:
        state.statement = state.statement.options(*rules)
