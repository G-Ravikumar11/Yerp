"""The drawings endpoints."""
import io
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
from app.core.files import file_bytes, store_file
from app.core.config import logger
from app.schemas.drawings import DrawingStatusIn, TakeoffSendIn
from app.services import purge, takeoff
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


@router.post("/api/drawings/{did}/takeoff")
def drawing_takeoff(did: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """The quantities on the current sheet and the material they take. Exact from a DXF, an estimate from a picture or PDF;
    nothing is saved. body: assumptions, kinds (layer name -> wall, slab, door, window, ignore), width_m (a picture's real width)."""
    client = require_erp_read(request, db)
    body = body or {}
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == did, models.DBDrawing.client_id == client.id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    cur = db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id, models.DBDrawingRevision.file_id.isnot(None)).order_by(
        models.DBDrawingRevision.id.desc()).first()
    f = db.query(models.DBFile).filter(models.DBFile.id == cur.file_id, models.DBFile.client_id == client.id).first() if cur else None
    if not f:
        raise HTTPException(409, "Add a revision with the drawing first: a DXF from AutoCAD, or a picture or PDF of the plan.")
    a = takeoff.clean_assumptions(body.get("assumptions"))
    name = (f.name or "").lower()
    head = {"drawing": "%s %s" % (d.number or "", d.title or ""), "revision": cur.revision, "assumptions": a}
    if name.endswith(".dwg") or name.endswith(".dxf"):
        data = file_bytes(db, f)
        if name.endswith(".dwg"):
            data = takeoff.dwg_to_dxf(data, key=(client.id, f.id))
            head["converted_from"] = "DWG"
        read = takeoff.read_dxf(data)
        kinds = {k: v for k, v in (body.get("kinds") or {}).items() if v in takeoff.KINDS}
        for row in read["layers"]:
            row["kind"] = kinds.get(row["name"], row["kind"])
        q = takeoff.cad_quantities(read["layers"], kinds, a)
        return {**head, **read, "quantities": q, "materials": takeoff.materials(q, a)}
    from app.ai.drawing_3d import _picture_of, drawing_to_3d
    trace = drawing_to_3d(did, request, db)
    if not trace.get("available"):
        raise HTTPException(409, trace.get("message") or "The plan could not be read.")
    width = body.get("width_m") or trace.get("width_m")
    try:
        width = float(width) if width else 0.0
    except (TypeError, ValueError):
        width = 0.0
    out = {**head, "source": "picture", "exact": False, "width_m": width or None, "width_read": trace.get("width_m"),
           "low_confidence": bool(trace.get("low_confidence")), "layers": []}
    if not width:
        return {**out, "needs_width": True, "quantities": {}, "materials": []}
    from PIL import Image
    try:
        w, h = Image.open(io.BytesIO(_picture_of(file_bytes(db, f), (f.content_type or "").lower()))).size
        aspect = h / w
    except Exception:
        raise HTTPException(400, "The sheet's proportions could not be read. Add the plan as a JPG or PNG.")
    q = takeoff.plan_quantities(trace, width, aspect)
    return {**out, "quantities": q, "materials": takeoff.materials(q, a)}


def _takeoff_source(db, client_id, did):
    """(drawing, its current revision's label): what a take-off sent on says it came from."""
    d = db.query(models.DBDrawing).filter(models.DBDrawing.id == did, models.DBDrawing.client_id == client_id).first()
    if not d:
        raise HTTPException(404, "Drawing not found")
    cur = db.query(models.DBDrawingRevision).filter(models.DBDrawingRevision.drawing_id == d.id,
                                                    models.DBDrawingRevision.file_id.isnot(None)).order_by(
        models.DBDrawingRevision.id.desc()).first()
    return d, (cur.revision if cur else "")


def _takeoff_lines(body, merge=False):
    """The lines sent, each with something named and a quantity; for an enquiry, the same material from several parts
    of the take-off (cement for masonry, plaster and slab) is asked for once."""
    out = {}
    for l in body.lines[:200]:
        text, uom = (l.description or "").strip()[:200], (l.uom or "").strip()[:20]
        qty = float(l.quantity or 0)
        if not text or qty <= 0:
            continue
        key = (text.lower(), uom.lower()) if merge else len(out)
        if key in out:
            out[key]["quantity"] += qty
        else:
            out[key] = {"description": text, "uom": uom, "quantity": qty, "item_code": (l.item_code or "").strip().upper()[:40]}
    if not out:
        raise HTTPException(400, "Tick at least one line with a quantity.")
    return list(out.values())


@router.post("/api/drawings/{did}/takeoff/boq")
def takeoff_to_boq(did: int, body: TakeoffSendIn, request: Request, db: Session = Depends(get_db)):
    """The take-off's quantities added to the end of the project's BOQ, under a heading naming the drawing and its
    revision, unpriced: the QS prices them in the BOQ. Sent once per revision of a drawing."""
    from app.schemas.boq import ProjectBoqLineIn
    from app.services.boq import boq_revision_of, boq_save_lines
    from app.services.projects import job_or_404
    client, _, actor_name = wo_actor(request, db)
    d, revision = _takeoff_source(db, client.id, did)
    lines = _takeoff_lines(body)
    job = job_or_404(db, client.id, d.job_id)
    boq = db.query(models.DBBoq).filter(models.DBBoq.client_id == client.id, models.DBBoq.job_id == d.job_id).first()
    if boq is None:
        raise HTTPException(409, "%s has no BOQ yet. Open it under Projects, BOQ, then send the quantities again." % job.name)
    rev = boq_revision_of(db, boq)
    if rev.status != "OPEN":
        raise HTTPException(409, "%s of %s is issued. Start a new revision to add to it." % (rev.label or "R%d" % rev.rev_no, boq.number))
    heading = "Take-off from drawing %s rev %s" % (d.number or "", revision or "-")
    have = db.query(models.DBBoqLine).filter(models.DBBoqLine.revision_id == rev.id).order_by(models.DBBoqLine.display_order,
                                                                                               models.DBBoqLine.id).all()
    if any(l.kind == "section" and (l.description or "").strip().lower() == heading.lower() for l in have):
        raise HTTPException(409, "%s is already on %s. Change the lines there." % (heading, boq.number))
    rows = [ProjectBoqLineIn(key=l.key, kind=l.kind, item_no=l.item_no or "", group_code=l.group_code or "",
                             description=l.description or "", uom=l.uom or "", quantity=l.quantity or 0, rate=l.rate or 0,
                             item_code=l.item_code or "", remarks=l.remarks or "", material=l.material or "",
                             rate_only=bool(l.rate_only)) for l in have]
    rows.append(ProjectBoqLineIn(kind="section", description=heading))
    rows += [ProjectBoqLineIn(kind="item", description=l["description"], uom=l["uom"], quantity=l["quantity"], rate=0,
                              item_code=l["item_code"], remarks="From the take-off of %s rev %s: check before pricing" % (
                                  d.number or "", revision or "-")) for l in lines]
    boq_save_lines(db, boq, rev, rows, False, client.id)
    log_audit(db, client.id, "boq_from_takeoff", "boq", boq.id, boq.number, "%s: %d line(s)" % (heading, len(lines)), request)
    db.commit()
    return {"ok": True, "boq_id": boq.id, "job_id": d.job_id,
            "message": "%d line%s added to %s under \"%s\", unpriced. Price them in the BOQ." % (
                len(lines), "" if len(lines) == 1 else "s", boq.number, heading)}


@router.post("/api/drawings/{did}/takeoff/enquiry")
def takeoff_to_enquiry(did: int, body: TakeoffSendIn, request: Request, db: Session = Depends(get_db)):
    """An enquiry to suppliers for the take-off's materials, on the drawing's project. It opens like any other enquiry:
    suppliers are added and asked from there."""
    from app.services.procurement import _make_rfq, rfq_dict
    client, actor_id, actor_name = wo_actor(request, db, "purchase.manage")
    d, revision = _takeoff_source(db, client.id, did)
    lines = _takeoff_lines(body, merge=True)
    r = _make_rfq(db, client, actor_name, "Materials from drawing %s rev %s" % (d.number or "", revision or "-"), d.job_id,
                  body.needed_by, "Quantities from the take-off of %s %s, rev %s. Rules of thumb with wastage: checked by "
                  "the engineer before ordering." % (d.number or "", d.title or "", revision or "-"),
                  [{"description": l["description"], "uom": l["uom"], "qty": round(l["quantity"], 2), "item_code": l["item_code"]}
                   for l in lines])
    r.created_by_id = actor_id
    log_audit(db, client.id, "rfq_from_takeoff", "rfq", r.id, r.number, "%s rev %s: %d line(s)" % (d.number, revision, len(lines)), request)
    db.commit()
    return {"ok": True, "rfq": rfq_dict(db, r), "message": "%s opened with %d item%s. Add the suppliers to ask." % (
        r.number, len(lines), "" if len(lines) == 1 else "s")}


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
