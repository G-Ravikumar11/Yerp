"""The drawings endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import DRAWING_STATUSES
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.files import store_file
from app.schemas.drawings import DrawingStatusIn
from app.services.projects import drawing_dict


router = APIRouter()


@router.get("/api/drawings/{did}")
def get_drawing(did: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == did,
                                          models.DBDrawing.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    return {"drawing": drawing_dict(db, d, detail=True)}


@router.post("/api/drawings/{did}/revisions")
def add_revision(did: int, request: Request, file: UploadFile = File(...),
                 revision: str = Form(...), status: str = Form("For information"),
                 received_on: str = Form(""), received_from: str = Form(""), remarks: str = Form(""),
                 db: Session = Depends(get_db)):
    """A new revision of the sheet. The one before it is superseded - kept,
    but never again the one anybody builds to."""
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
    for old in db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id).all():
        old.status = "Superseded"
    db.add(models.DBDrawingRevision(drawing_id=d.id, revision=rev, file_id=f.id, status=status,
                                    received_on=(received_on or date.today().isoformat())[:10],
                                    received_from=(received_from or "").strip(),
                                    remarks=(remarks or "").strip(), recorded_by_name=actor_name))
    d.current_revision, d.status = rev, status
    log_audit(db, client.id, "drawing_revised", "drawing", d.id, d.number, rev, request)
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
    cur = db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id).order_by(
        models.DBDrawingRevision.id.desc()).first()
    if not cur:
        raise HTTPException(409, "Add the first revision of the sheet before giving it a status.")
    cur.status = d.status = body.status
    db.commit()
    return {"drawing": drawing_dict(db, d, detail=True)}
