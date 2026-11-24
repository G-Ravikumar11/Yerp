"""Store - the project's Item sheet, under /api/store/item-sheet: the materials a project will need, each under a BOQ group
code, with HSN and unit from the item master. Made in the app or uploaded from the Excel template; the Master approves it,
and from then on an indent for the project may ask only for what is on it (services/item_sheet.py).

store.outward.view / store.inward.view read it; store.inward.post / store.outward.post (the storekeeper) make and send it;
only the Master approves or sends it back."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.item_sheet import DBItemSheet, DBItemSheetLine
from app.services import item_sheet as svc

router = APIRouter(prefix="/api/store/item-sheet", tags=["store-item-sheet"])

VIEW = ("store.outward.view", "store.inward.view")
EDIT = ("store.inward.post", "store.outward.post")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class LineIn(BaseModel):
    group_code: str = ""
    item_code: str = ""
    qty: Optional[float] = None
    remarks: str = ""


class LinesIn(BaseModel):
    lines: List[LineIn]


class NoteIn(BaseModel):
    note: str = ""


def _who(actor):
    return dict(user_type="employee" if actor.employee is not None else "client", user_name=actor.name)


def _problems(head, errors):
    """One message, a line per problem (the screen lists them), at most 30 of them."""
    more = ["... and %d more." % (len(errors) - 30)] if len(errors) > 30 else []
    return "\n".join([head] + errors[:30] + more)


def _master(actor):
    if actor.employee is not None:
        raise HTTPException(403, "Only the Master approves an Item sheet.")


@router.get("")
def list_sheets(request: Request, db: Session = Depends(get_read_db)):
    """Every project and where its Item sheet stands."""
    actor = store_actor(request, db, VIEW)
    cid = actor.client.id
    sheets = {s.job_id: s for s in db.query(DBItemSheet).filter(DBItemSheet.client_id == cid).all()}
    counts = dict(db.query(DBItemSheetLine.sheet_id, func.count(DBItemSheetLine.id))
                  .filter(DBItemSheetLine.sheet_id.in_([s.id for s in sheets.values()] or [0])).group_by(DBItemSheetLine.sheet_id).all())
    jobs = db.query(models.DBJob).filter(models.DBJob.client_id == cid).order_by(models.DBJob.id.desc()).all()
    out = []
    for j in jobs:
        s = sheets.get(j.id)
        if s is None and (j.status or "").lower() in ("closed", "completed", "cancelled"):
            continue
        out.append({"job_id": j.id, "code": getattr(j, "number", "") or "", "name": j.name or "", "status": s.status if s else None,
                    "approved": bool(s and s.approved_lines), "lines": counts.get(s.id, 0) if s else 0,
                    "updated_at": s.updated_at.isoformat(timespec="seconds") if s and s.updated_at else ""})
    return {"items": out, "is_master": actor.employee is None}


@router.get("/{job_id}")
def get_sheet(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, VIEW)
    job = svc.job_of(db, actor.client.id, job_id)
    out = svc.sheet_dict(db, actor.client.id, job)
    out["is_master"] = actor.employee is None
    return out


@router.put("/{job_id}")
def save_sheet(job_id: int, body: LinesIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    lines, errors = svc.check_rows(db, actor.client.id, job.id, [dict(l.model_dump(), row=n) for n, l in enumerate(body.lines, 1)])
    if errors:
        raise HTTPException(400, _problems("The sheet was not saved.", errors))
    svc.save_lines(db, actor.client.id, job.id, lines, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_saved", "job", job.id, job.name, "%d lines" % len(lines), request=request, **_who(actor))
    db.commit()
    return get_sheet(job_id, request, db)


@router.get("/{job_id}/template.xlsx")
def download(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, VIEW)
    job = svc.job_of(db, actor.client.id, job_id)
    name = "item-sheet-%s.xlsx" % ("".join(ch if ch.isalnum() else "-" for ch in (getattr(job, "number", "") or job.name or str(job.id))).strip("-") or job.id)
    return Response(content=svc.workbook(db, actor.client.id, job), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@router.post("/{job_id}/upload")
async def upload(job_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "The file is over 5 MB.")
    lines, errors = svc.check_rows(db, actor.client.id, job.id, svc.read_upload(content))
    if errors:
        raise HTTPException(400, _problems("Nothing was uploaded: %d problem%s in the file." % (len(errors), "" if len(errors) == 1 else "s"), errors))
    svc.save_lines(db, actor.client.id, job.id, lines, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_uploaded", "job", job.id, job.name, "%d lines from %s" % (len(lines), file.filename or "a file"), request=request, **_who(actor))
    db.commit()
    return get_sheet(job_id, request, db)


@router.post("/{job_id}/submit")
def submit(job_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    svc.submit(db, actor.client.id, job.id, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_submitted", "job", job.id, job.name, "", request=request, **_who(actor))
    db.commit()
    return get_sheet(job_id, request, db)


@router.post("/{job_id}/approve")
def approve(job_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    _master(actor)
    job = svc.job_of(db, actor.client.id, job_id)
    svc.approve(db, actor.client.id, job.id, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_approved", "job", job.id, job.name, "", request=request, **_who(actor))
    db.commit()
    return get_sheet(job_id, request, db)


@router.post("/{job_id}/send-back")
def send_back(job_id: int, body: NoteIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    _master(actor)
    job = svc.job_of(db, actor.client.id, job_id)
    svc.send_back(db, actor.client.id, job.id, body.note)
    log_audit(db, actor.client.id, "store_item_sheet_sent_back", "job", job.id, job.name, body.note, request=request, **_who(actor))
    db.commit()
    return get_sheet(job_id, request, db)
