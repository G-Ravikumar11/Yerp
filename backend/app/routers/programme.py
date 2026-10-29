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
import re

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.auth import require_erp_read, wo_actor
from app.db import get_db, get_read_db
from app.schemas.programme import (ProgrammeAddIn, ProgrammeBaselineIn, ProgrammeCalendarIn, ProgrammeCopyIn, ProgrammeEditIn,
                                   ProgrammeFromBoqIn, ProgrammeHolidayIn, ProgrammeImportIn, ProgrammeMoveIn, ProgrammePublicHolidaysIn, ProgrammeRestoreIn)
from app.services.programme import (add_holiday, add_public_holidays, add_rows, copy_to_units, delete_holiday,
                                    delete_row, duplicate_row, edit_rows, move_row, programme_view, restore, save_baseline,
                                    set_calendar)
from app.services.programme_boq import draw_from_boq, programme_boq
from app.services.programme_excel import export_xlsx
from app.services.programme_pdf import programme_pdf
from app.services.programme_sheet import apply_import, parse_sheet
from app.services.projects import _d, job_or_404

router = APIRouter()


def _writer(request, db, job_id):
    client, _, _ = wo_actor(request, db)
    return client, job_or_404(db, client.id, job_id)


@router.get("/api/jobs/{job_id}/programme")
def job_programme(job_id: int, request: Request, as_of: str = "", db: Session = Depends(get_read_db)):
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


@router.get("/api/jobs/{job_id}/programme/boq")
def programme_boq_tree(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The project's BOQ as a tree to pick from, with what is already on the programme from each line."""
    client = require_erp_read(request, db)
    return programme_boq(db, client, job_or_404(db, client.id, job_id))


@router.post("/api/jobs/{job_id}/programme/from-boq")
def programme_from_boq(job_id: int, body: ProgrammeFromBoqIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    made, message, warnings = draw_from_boq(db, client, job, body.picks, body.anchor_id, body.position, body.start)
    db.commit()
    return {**programme_view(db, client, job), "made": made, "message": message, "warnings": warnings}


@router.post("/api/jobs/{job_id}/programme/baseline")
def programme_save_baseline(job_id: int, body: ProgrammeBaselineIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    b = save_baseline(db, client, job, body.label, actor_name)
    return {**programme_view(db, client, job), "message": "Baseline \"%s\" saved: planned %% is measured against it from now on." % b.label}


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

@router.get("/api/jobs/{job_id}/programme/export")
def programme_export(job_id: int, request: Request, db: Session = Depends(get_db)):
    """The programme as the office's Excel schedule, with live formulas."""
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    body = export_xlsx(programme_view(db, client, job))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", "Programme_%s" % (job.number or job.id))
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="%s.xlsx"' % name})


@router.post("/api/jobs/{job_id}/programme/import")
async def programme_import_preview(job_id: int, request: Request, file: UploadFile = File(...), sheet: str = Form(""),
                                   db: Session = Depends(get_db)):
    """Read a schedule sheet - the GH or the APTIDCO / finishing-works layout, or one this app exported - without
    saving: the rows come back for a look, the save is the confirm call."""
    _writer(request, db, job_id)
    return parse_sheet(await file.read(), sheet)


@router.post("/api/jobs/{job_id}/programme/import/confirm")
def programme_import_confirm(job_id: int, body: ProgrammeImportIn, request: Request, db: Session = Depends(get_db)):
    client, job = _writer(request, db, job_id)
    n, links, message = apply_import(db, client, job, body.nodes, body.calendar)
    return {**programme_view(db, client, job), "message": message, "made": n, "links": links}

@router.get("/api/jobs/{job_id}/programme/pdf")
def programme_print(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The programme on A3 landscape: the header block, the columns and the bar chart fitted to the page."""
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    body = programme_pdf(programme_view(db, client, job))
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", "Programme_%s" % (job.number or job.id))
    return Response(body, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="%s.pdf"' % name})