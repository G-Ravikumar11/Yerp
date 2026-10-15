"""The programme endpoints: Planning & Progress as the office's Excel schedule has it.

    GET    /api/jobs/{job_id}/programme?as_of=YYYY-MM-DD     every row worked out (dates, days, numbering, roll-ups,
                                                             critical path, progress, planned progress on as_of)
    PATCH  /api/jobs/{job_id}/programme/rows                 {"changes": [{"id", "name" | "start" | "days" | ...}]}
    POST   /api/jobs/{job_id}/programme/rows                 {"anchor_id", "position": after | child | end, "rows"}
    POST   /api/jobs/{job_id}/programme/move                 {"id", "parent_id", "before_id"}  indent, outdent, drag
    POST   /api/jobs/{job_id}/programme/rows/{id}/duplicate
    DELETE /api/jobs/{job_id}/programme/rows/{id}            with everything under it
    POST   /api/jobs/{job_id}/programme/copy                 {"source_id", "targets": [{"name", "start" | "offset"}]}
    PUT    /api/jobs/{job_id}/programme/calendar             {"calendar_days", "weekly_off"}
    POST   /api/jobs/{job_id}/programme/holidays             {"date", "name"}
    POST   /api/jobs/{job_id}/programme/holidays/public      {"year"}  India's public holidays
    DELETE /api/jobs/{job_id}/programme/holidays/{id}
    POST   /api/jobs/{job_id}/programme/restore              {"rows", "links"}  undo and redo

Every change answers with the whole programme worked out again.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth import require_erp_read, wo_actor
from app.db import get_db
from app.schemas.programme import (ProgrammeAddIn, ProgrammeCalendarIn, ProgrammeCopyIn, ProgrammeEditIn,
                                   ProgrammeHolidayIn, ProgrammeMoveIn, ProgrammePublicHolidaysIn, ProgrammeRestoreIn)
from app.services.programme import (add_holiday, add_public_holidays, add_rows, copy_to_units, delete_holiday,
                                    delete_row, duplicate_row, edit_rows, move_row, programme_view, restore,
                                    set_calendar)
from app.services.projects import _d, job_or_404

router = APIRouter()


def _writer(request, db, job_id):
    client, _, _ = wo_actor(request, db)
    return client, job_or_404(db, client.id, job_id)


@router.get("/api/jobs/{job_id}/programme")
def job_programme(job_id: int, request: Request, as_of: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return programme_view(db, client, job_or_404(db, client.id, job_id), _d(as_of))


@router.patch("/api/jobs/{job_id}/programme/rows")
def programme_edit(job_id: int, body: ProgrammeEditIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    edit_rows(db, client, job, body.changes)
    return programme_view(db, client, job)


@router.post("/api/jobs/{job_id}/programme/rows")
def programme_add(job_id: int, body: ProgrammeAddIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    made = add_rows(db, client, job, body.anchor_id, body.position, body.rows)
    return {**programme_view(db, client, job), "made": made}


@router.post("/api/jobs/{job_id}/programme/move")
def programme_move(job_id: int, body: ProgrammeMoveIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    move_row(db, client, job, body.id, body.parent_id, body.before_id)
    return programme_view(db, client, job)


@router.post("/api/jobs/{job_id}/programme/rows/{row_id}/duplicate")
def programme_duplicate(job_id: int, row_id: int, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    made = duplicate_row(db, client, job, row_id)
    return {**programme_view(db, client, job), "made": [made]}


@router.delete("/api/jobs/{job_id}/programme/rows/{row_id}")
def programme_delete(job_id: int, row_id: int, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    n = delete_row(db, client, job, row_id)
    return {**programme_view(db, client, job), "message": "%d row%s deleted." % (n, "" if n == 1 else "s")}


@router.post("/api/jobs/{job_id}/programme/copy")
def programme_copy(job_id: int, body: ProgrammeCopyIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    made, dropped = copy_to_units(db, client, job, body.source_id, [t.model_dump() for t in body.targets])
    note = "%d unit%s added." % (len(made), "" if len(made) == 1 else "s")
    if dropped:
        note += " Links to rows outside the unit were not copied: %s." % "; ".join(dropped)
    return {**programme_view(db, client, job), "made": made, "dropped_links": dropped, "message": note}


@router.put("/api/jobs/{job_id}/programme/calendar")
def programme_calendar_set(job_id: int, body: ProgrammeCalendarIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    set_calendar(db, client, job, body.calendar_days, body.weekly_off)
    return programme_view(db, client, job)


@router.post("/api/jobs/{job_id}/programme/holidays")
def programme_holiday_add(job_id: int, body: ProgrammeHolidayIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    add_holiday(db, client, job, body.date, body.name)
    return programme_view(db, client, job)


@router.post("/api/jobs/{job_id}/programme/holidays/public")
def programme_holidays_public(job_id: int, body: ProgrammePublicHolidaysIn, request: Request,
                              db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    n = add_public_holidays(db, client, job, body.year)
    return {**programme_view(db, client, job), "message": "%d public holiday%s added for %d." % (n, "" if n == 1 else "s", body.year)}


@router.delete("/api/jobs/{job_id}/programme/holidays/{holiday_id}")
def programme_holiday_delete(job_id: int, holiday_id: int, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    delete_holiday(db, client, job, holiday_id)
    return programme_view(db, client, job)


@router.post("/api/jobs/{job_id}/programme/restore")
def programme_restore(job_id: int, body: ProgrammeRestoreIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    restore(db, client, job, body.rows, body.links)
    return programme_view(db, client, job)
