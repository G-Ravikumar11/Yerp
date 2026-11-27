"""Store - the project's Item sheet, under /api/store/item-sheet: under every line of the project's BOQ (grouped by its
group codes), the store materials it needs, with HSN and unit from the item master. Made in the app or uploaded from the
Excel template; the Master approves it, and from then on purchase orders and indents for the project go by it
(services/item_sheet.py). The sheet also follows its materials through purchase and the store; the orders, receipts,
indents and issues raised from its screen are made by the usual routes, with their usual rights and approvals.

store.outward.view / store.inward.view read it; store.inward.post / store.outward.post (the storekeeper) make and send it
and add a new material to the item master from it; only the Master approves or sends it back."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.store_auth import store_actor
from app.db import get_db, get_read_db
from app.models.item_sheet import DBItemSheet, DBItemSheetMaterial
from app.services import item_sheet as svc

router = APIRouter(prefix="/api/store/item-sheet", tags=["store-item-sheet"])

VIEW = ("store.outward.view", "store.inward.view")
EDIT = ("store.inward.post", "store.outward.post")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MaterialIn(BaseModel):
    boq_key: str = ""
    item_code: str = ""
    qty: Optional[float] = None
    remarks: str = ""


class MaterialsIn(BaseModel):
    materials: List[MaterialIn]
    drop_orphans: bool = False           # also take off the materials of BOQ lines the BOQ no longer has


class NoteIn(BaseModel):
    note: str = ""


class NewItemIn(BaseModel):
    item_name: str
    units_of_measure: str
    hsn_code: str = ""
    make: str = ""


def _who(actor):
    return dict(user_type="employee" if actor.employee is not None else "client", user_name=actor.name)


def _problems(head, errors):
    """One message, a line per problem (the screen lists them), at most 30 of them."""
    more = ["... and %d more." % (len(errors) - 30)] if len(errors) > 30 else []
    return "\n".join([head] + errors[:30] + more)


def _master(actor):
    if actor.employee is not None:
        raise HTTPException(403, "Only the Master approves an Item sheet.")


def _orphan_keys(db, client_id, job_id, drop):
    """BOQ keys with materials on the sheet that the BOQ no longer has: kept as they are on a save, unless dropped."""
    if drop:
        return ()
    sheet = svc.sheet_of(db, client_id, job_id)
    keys = {l.key for l in svc.boq_lines(db, client_id, job_id)[0]}
    return tuple({m.boq_key for m in svc.materials_of(db, sheet) if m.boq_key not in keys})


@router.get("")
def list_sheets(request: Request, db: Session = Depends(get_read_db)):
    """Every project and where its Item sheet stands."""
    actor = store_actor(request, db, VIEW)
    cid = actor.client.id
    sheets = {s.job_id: s for s in db.query(DBItemSheet).filter(DBItemSheet.client_id == cid).all()}
    counts = dict(db.query(DBItemSheetMaterial.sheet_id, func.count(DBItemSheetMaterial.id))
                  .filter(DBItemSheetMaterial.sheet_id.in_([s.id for s in sheets.values()] or [0])).group_by(DBItemSheetMaterial.sheet_id).all())
    jobs = db.query(models.DBJob).filter(models.DBJob.client_id == cid).order_by(models.DBJob.id.desc()).all()
    out = []
    for j in jobs:
        s = sheets.get(j.id)
        if s is None and (j.status or "").lower() in ("closed", "completed", "cancelled"):
            continue
        out.append({"job_id": j.id, "code": j.number or "", "name": j.name or "", "status": s.status if s else None,
                    "approved": bool(s and s.approved_lines), "materials": counts.get(s.id, 0) if s else 0,
                    "updated_at": s.updated_at.isoformat(timespec="seconds") if s and s.updated_at else ""})
    return {"items": out, "is_master": actor.employee is None}


@router.get("/{job_id}")
def get_sheet(job_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    job = svc.job_of(db, actor.client.id, job_id)
    # A sheet saved in its first form (materials under a group code only) moves under the BOQ's lines the first time it is opened.
    if svc.adopt_old_lines(db, svc.sheet_of(db, actor.client.id, job.id), svc.boq_lines(db, actor.client.id, job.id)[0]):
        db.commit()
    return svc.sheet_dict(db, actor, job)


@router.put("/{job_id}")
def save_sheet(job_id: int, body: MaterialsIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    mats, errors = svc.check_rows(db, actor.client.id, job.id, [dict(m.model_dump(), row=n) for n, m in enumerate(body.materials, 1)])
    if errors:
        raise HTTPException(400, _problems("The sheet was not saved.", errors))
    svc.save_materials(db, actor.client.id, job.id, mats, actor.name, keep_keys=_orphan_keys(db, actor.client.id, job.id, body.drop_orphans))
    log_audit(db, actor.client.id, "store_item_sheet_saved", "job", job.id, job.name, "%d materials" % len(mats), request=request, **_who(actor))
    db.commit()
    return svc.sheet_dict(db, actor, job)


@router.get("/{job_id}/template.xlsx")
def download(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    actor = store_actor(request, db, VIEW)
    job = svc.job_of(db, actor.client.id, job_id)
    name = "item-sheet-%s.xlsx" % ("".join(ch if ch.isalnum() else "-" for ch in (job.number or job.name or str(job.id))).strip("-") or job.id)
    return Response(content=svc.workbook(db, actor, job), media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@router.post("/{job_id}/upload")
async def upload(job_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "The file is over 5 MB.")
    mats, errors = svc.check_rows(db, actor.client.id, job.id, svc.read_upload(content))
    if errors:
        raise HTTPException(400, _problems("Nothing was uploaded: %d problem%s in the file." % (len(errors), "" if len(errors) == 1 else "s"), errors))
    svc.save_materials(db, actor.client.id, job.id, mats, actor.name, keep_keys=_orphan_keys(db, actor.client.id, job.id, False))
    log_audit(db, actor.client.id, "store_item_sheet_uploaded", "job", job.id, job.name, "%d materials from %s" % (len(mats), file.filename or "a file"),
              request=request, **_who(actor))
    db.commit()
    return svc.sheet_dict(db, actor, job)


@router.post("/{job_id}/items")
def add_item(job_id: int, body: NewItemIn, request: Request, db: Session = Depends(get_db)):
    """A material not yet in the item master, added to it from the sheet as a stock item with the next item code."""
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    try:
        item = svc.new_item(db, actor.client.id, body.item_name, body.units_of_measure, body.hsn_code, body.make, actor.name)
        log_audit(db, actor.client.id, "item_created", "item", item.id, item.item_code, "%s (from the Item sheet of %s)" % (item.item_name, job.name),
                  request=request, **_who(actor))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This item has just been added by someone else. Search for it before adding it again.")
    from app.services.store_outward import base_uom_of
    return {"item": {"id": item.id, "code": item.item_code, "name": item.item_name, "base_uom": base_uom_of(db, item) or item.units_of_measure,
                     "uoms": [], "category": None, "hsn": item.hsn_code or ""},
            "message": "%s %s added to the item master." % (item.item_code, item.item_name)}


@router.post("/{job_id}/submit")
def submit(job_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    svc.submit(db, actor.client.id, job.id, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_submitted", "job", job.id, job.name, "", request=request, **_who(actor))
    db.commit()
    return svc.sheet_dict(db, actor, job)


@router.post("/{job_id}/approve")
def approve(job_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    _master(actor)
    job = svc.job_of(db, actor.client.id, job_id)
    svc.approve(db, actor.client.id, job.id, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_approved", "job", job.id, job.name, "", request=request, **_who(actor))
    db.commit()
    return svc.sheet_dict(db, actor, job)


@router.post("/{job_id}/send-back")
def send_back(job_id: int, body: NoteIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, VIEW)
    _master(actor)
    job = svc.job_of(db, actor.client.id, job_id)
    svc.send_back(db, actor.client.id, job.id, body.note)
    log_audit(db, actor.client.id, "store_item_sheet_sent_back", "job", job.id, job.name, body.note, request=request, **_who(actor))
    db.commit()
    return svc.sheet_dict(db, actor, job)


# --- the work each BOQ line is, and filling materials from norms ----------------------------------------------------------

class WorkLinkIn(BaseModel):
    boq_key: str
    work_item_id: Optional[int] = None    # None: go back to the work item the BOQ line names, if any


class WorkLinksIn(BaseModel):
    links: List[WorkLinkIn]


class FillIn(BaseModel):
    keys: Optional[List[str]] = None       # the BOQ lines to fill; None for all of them


@router.get("/{job_id}/work-items")
def work_items(job_id: int, request: Request, q: str = "", db: Session = Depends(get_read_db)):
    """Work items of the Item Master (what a BOQ line is), found by code or name, with how many materials their norms have."""
    from app.services.item_norms import norm_counts
    actor = store_actor(request, db, VIEW)
    svc.job_of(db, actor.client.id, job_id)
    query = db.query(models.DBItem).filter(models.DBItem.client_id == actor.client.id, models.DBItem.kind == "FG",
                                           models.DBItem.merged_into_id.is_(None), models.DBItem.is_active.isnot(False))
    term = (q or "").strip().replace("%", "").replace("_", "")
    if term:
        like = "%" + term + "%"
        query = query.filter((models.DBItem.item_code.ilike(like)) | (models.DBItem.item_name.ilike(like)))
    rows = query.order_by(models.DBItem.item_name).limit(30).all()
    counts = norm_counts(db, actor.client.id, [r.id for r in rows])
    return {"items": [svc.work_dict(r, "", counts) for r in rows]}


@router.put("/{job_id}/works")
def set_works(job_id: int, body: WorkLinksIn, request: Request, db: Session = Depends(get_db)):
    """Say which work item each of these BOQ lines is. It does not change the sheet's materials, so not its approval either."""
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    if not body.links or len(body.links) > 2000:
        raise HTTPException(400, "Give between 1 and 2000 lines.")
    for link in body.links:
        svc.set_line_work(db, actor.client.id, job.id, link.boq_key, link.work_item_id, actor.name)
    log_audit(db, actor.client.id, "store_item_sheet_works", "job", job.id, job.name, "%d BOQ lines" % len(body.links), request=request, **_who(actor))
    db.commit()
    return svc.sheet_dict(db, actor, job)


@router.get("/{job_id}/work-suggestions")
def work_suggestions(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    """For BOQ lines with no work item, the one whose name clearly matches the line, to accept or not."""
    actor = store_actor(request, db, VIEW)
    job = svc.job_of(db, actor.client.id, job_id)
    return {"items": svc.suggest_works(db, actor.client.id, job.id)}


@router.post("/{job_id}/fill")
def fill(job_id: int, body: FillIn, request: Request, db: Session = Depends(get_read_db)):
    """The materials these BOQ lines would have from their work items' norms (or the same work on another sheet). Nothing is
    saved: the screen puts them in the editor, to look over and save."""
    actor = store_actor(request, db, EDIT)
    job = svc.job_of(db, actor.client.id, job_id)
    return svc.fill_from_norms(db, actor.client.id, job.id, body.keys)


@router.post("/{job_id}/lines/{boq_key}/save-norm")
def save_norm(job_id: int, boq_key: str, request: Request, db: Session = Depends(get_db)):
    """A BOQ line's saved materials, divided by its quantity, kept as the norm of its work item - for every later project."""
    from app.services.item_norms import check_rows, replace_norms
    actor = store_actor(request, db, EDIT)
    if actor.employee is not None:
        from app.core.permissions import permissions_for
        if "items.manage" not in permissions_for(actor.employee):
            raise HTTPException(403, "Saving a norm changes the Item Master: it needs the right to manage items.")
    job = svc.job_of(db, actor.client.id, job_id)
    work, rows = svc.line_norm_rows(db, actor.client.id, job.id, boq_key)
    values, errors = check_rows(db, actor.client.id, rows)
    if errors:
        raise HTTPException(400, _problems("The norm was not saved.", errors))
    replace_norms(db, actor.client.id, work, values, actor.name)
    log_audit(db, actor.client.id, "item_norms_saved", "item", work.id, work.item_code, "%d materials, from the Item sheet of %s" % (len(values), job.name),
              request=request, **_who(actor))
    db.commit()
    return {"message": "Saved as the norm of %s %s: %d material%s per %s." % (work.item_code, work.item_name, len(values), "" if len(values) == 1 else "s",
                                                                             work.units_of_measure or "unit"),
            "sheet": svc.sheet_dict(db, actor, job)}
