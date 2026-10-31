"""The drawings endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func as sqlfunc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, get_read_db

from app.constants.common import DRAWING_STATUSES
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.files import store_file
from app.core.config import logger
from app.schemas.drawings import DrawingStatusIn
from app.services import purge
from app.services.drawing_rules import ever_gfc, is_later, log_status
from app.services.projects import drawing_dict


router = APIRouter()


@router.get("/api/drawings/{did}")
def get_drawing(did: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == did,
                                          models.DBDrawing.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    out = drawing_dict(db, d, detail=True)
    # Every status it has had, from the log: who moved it, when, from what to what.
    out["status_log"] = [{"at": a.created_at or "", "by": a.user_name or "", "change": a.details or ""}
                         for a in db.query(models.DBAuditLog).filter(models.DBAuditLog.client_id == client.id,
                                                                    models.DBAuditLog.entity_type == "drawing",
                                                                    models.DBAuditLog.entity_id == d.id,
                                                                    models.DBAuditLog.action == "drawing_status")
                         .order_by(models.DBAuditLog.id).all()]
    out["deletable"] = not ever_gfc(db, d)
    return {"drawing": out}


@router.post("/api/drawings/{did}/revisions")
def add_revision(did: int, request: Request, file: UploadFile = File(...),
                 revision: str = Form(...), status: str = Form("For information"),
                 received_on: str = Form(""), received_from: str = Form(""), remarks: str = Form(""),
                 db: Session = Depends(get_db)):
    """A new revision of the sheet. The one before it is superseded - kept,
    but never again the one anybody builds to. One recorded late, earlier than the current revision (R1 after R2), goes
    on the register superseded: the current one stays."""
    client, _, actor_name = wo_actor(request, db)
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == did,
                                          models.DBDrawing.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    rev = (revision or "").strip().upper()
    if not rev:
        raise HTTPException(400, "Which revision is it? R0, R1, A, B...")
    if db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id,
                                                 sqlfunc.upper(models.DBDrawingRevision.revision) == rev).first():
        raise HTTPException(409, "%s revision %s is already on the register." % (d.number, rev))
    status = status if status in DRAWING_STATUSES and status != "Superseded" else "For information"
    data = file.file.read()
    f = store_file(db, client.id, file, data, job_id=d.job_id, attached_type="drawing",
                   attached_id=d.id, kind="drawing", caption="%s rev %s" % (d.number, rev),
                   taken_on=received_on or date.today().isoformat(), by=actor_name)
    latest = is_later(rev, d.current_revision)
    if latest:
        db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id).update(
            {"status": "Superseded"}, synchronize_session=False)       # one statement, however many revisions there are
    db.add(models.DBDrawingRevision(drawing_id=d.id, revision=rev, file_id=f.id, status=status if latest else "Superseded",
                                    received_on=(received_on or date.today().isoformat())[:10],
                                    received_from=(received_from or "").strip(),
                                    remarks=(remarks or "").strip(), recorded_by_name=actor_name))
    log_audit(db, client.id, "drawing_revised", "drawing", d.id, d.number, rev if latest else "%s (earlier than %s, recorded superseded)" % (rev, d.current_revision), request)
    if not latest:
        db.commit()
        return {"drawing": drawing_dict(db, d, detail=True),
                "message": "%s revision %s is earlier than %s: it is on the register, superseded, and %s stays current." % (
                    d.number, rev, d.current_revision, d.current_revision)}
    log_status(db, client.id, d, d.status, status, request, revision=rev)
    d.current_revision, d.status = rev, status
    db.commit()
    return {"drawing": drawing_dict(db, d, detail=True),
            "message": "%s now at revision %s - %s." % (d.number, rev, status.lower())}


@router.post("/api/drawings/{did}/status")
def drawing_status(did: int, body: DrawingStatusIn, request: Request, db: Session = Depends(get_db)):
    """Approved, or released good for construction - on the current revision."""
    client, _, _ = wo_actor(request, db)
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == did,
                                          models.DBDrawing.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    if body.status not in DRAWING_STATUSES or body.status == "Superseded":
        raise HTTPException(400, "One of: " + ", ".join(s for s in DRAWING_STATUSES if s != "Superseded"))
    # The current revision by name - not the last one typed in, which may be an earlier revision recorded late.
    cur = db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id,
                                                   sqlfunc.upper(models.DBDrawingRevision.revision) == (d.current_revision or "").upper()).first()
    if not cur:
        raise HTTPException(409, "Add the first revision of the sheet before giving it a status.")
    log_status(db, client.id, d, d.status, body.status, request, revision=cur.revision)
    cur.status = d.status = body.status
    db.commit()
    return {"drawing": drawing_dict(db, d, detail=True)}


@router.delete("/api/drawings/{did}")
def delete_drawing(did: int, request: Request, db: Session = Depends(get_db)):
    """Take a sheet off the register with all its revisions and their files. Anyone who manages work orders may -
    it is recorded in the audit log with who did it."""
    client, _, _ = wo_actor(request, db)
    try:
        message = purge.delete_one(db, request, client, "drawing", did)
    except IntegrityError as exc:
        db.rollback()
        logger.warning("drawing %s could not be deleted: %s", did, exc)
        raise HTTPException(409, "This drawing is in use and could not be deleted.")
    return {"ok": True, "message": message}
