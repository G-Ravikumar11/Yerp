"""Document control under /api/doc-control: transmittals, RFIs and submittals (services/doc_control.py)."""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.auth import require_erp_read, wo_actor
from app.db import get_db, get_read_db
from app.models.doc_control import DBDocControl
from app.services import doc_control as svc

router = APIRouter()


class ItemIn(BaseModel):
    drawing_id: Optional[int] = None
    description: Optional[str] = ""


class DocIn(BaseModel):
    kind: str
    subject: str
    to_party: str
    to_email: Optional[str] = ""
    job_id: Optional[int] = None
    details: Optional[str] = ""
    purpose: Optional[str] = ""
    revision: Optional[str] = ""
    due_date: Optional[str] = ""
    items: List[ItemIn] = []


class ReplyIn(BaseModel):
    reply: str
    response: Optional[str] = ""


@router.get("/api/doc-control")
def list_docs(request: Request, kind: str = "", job_id: int = 0, show: str = "open", db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    q = db.query(DBDocControl).filter(DBDocControl.client_id == client.id)
    if kind:
        q = q.filter(DBDocControl.kind == kind.upper())
    if job_id:
        q = q.filter(DBDocControl.job_id == job_id)
    every = q.order_by(DBDocControl.id.desc()).limit(1000).all()
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    rows = [svc.doc_dict(db, d, jobs) for d in every]
    shown = [r for r in rows if (show == "all") or (show == "open" and r["status"] in svc.WAITING)
             or (show == "replied" and r["status"] not in svc.WAITING + svc.DONE) or (show == "closed" and r["status"] in svc.DONE)]
    summary = {}
    for k in svc.KINDS:
        mine = [r for r in rows if r["kind"] == k]
        summary[k] = {"open": len([r for r in mine if r["status"] in svc.WAITING]), "overdue": len([r for r in mine if r["overdue"]])}
    return {"items": shown, "summary": summary, "purposes": list(svc.PURPOSES)}


@router.post("/api/doc-control")
def raise_doc(body: DocIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db)
    d = svc.create(db, client, actor_id, actor_name, body.model_dump(), request)
    return {"ok": True, "item": svc.doc_dict(db, d, items=True), "message": "%s %s raised." % (svc.KINDS[d.kind][1], d.number)}


@router.get("/api/doc-control/{doc_id}")
def get_doc(doc_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return {"item": svc.doc_dict(db, svc.doc_or_404(db, client.id, doc_id), items=True)}


@router.post("/api/doc-control/{doc_id}/reply")
def reply_doc(doc_id: int, body: ReplyIn, request: Request, db: Session = Depends(get_db)):
    """The party's reply: acknowledged, answered, approved (with comments) or rejected."""
    client, _, actor_name = wo_actor(request, db)
    d = svc.respond(db, client, svc.doc_or_404(db, client.id, doc_id), actor_name, body.reply, body.response, request)
    return {"ok": True, "item": svc.doc_dict(db, d, items=True), "message": "%s %s." % (d.number, d.status.replace("_", " ").lower())}


@router.post("/api/doc-control/{doc_id}/resubmit")
def resubmit_doc(doc_id: int, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db)
    n = svc.resubmit(db, client, actor_id, actor_name, svc.doc_or_404(db, client.id, doc_id), request)
    return {"ok": True, "item": svc.doc_dict(db, n, items=True), "message": "%s resubmitted as revision %s." % (n.number, n.revision)}


@router.post("/api/doc-control/{doc_id}/close")
def close_doc(doc_id: int, request: Request, body: Optional[dict] = None, db: Session = Depends(get_db)):
    """Closed once dealt with, or cancelled (with a reason) when it should never have gone."""
    client, _, _ = wo_actor(request, db)
    d = svc.doc_or_404(db, client.id, doc_id)
    if d.status in svc.DONE:
        raise HTTPException(409, "%s is %s already." % (d.number, d.status.lower()))
    cancel = bool((body or {}).get("cancel"))
    reason = ((body or {}).get("reason") or "").strip()
    if cancel and len(reason) < 3:
        raise HTTPException(400, "Say why it is cancelled.")
    d.status = "CANCELLED" if cancel else "CLOSED"
    d.closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cancel:
        d.response = (d.response + "\n" if d.response else "") + "Cancelled: " + reason
    from app.core.audit import log_audit
    log_audit(db, client.id, "doc_control_" + d.status.lower(), "doc_control", d.id, d.number, reason, request)
    db.commit()
    return {"ok": True, "item": svc.doc_dict(db, d, items=True), "message": "%s %s." % (d.number, d.status.lower())}


@router.post("/api/doc-control/{doc_id}/remind")
def remind_doc(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Email the party a reminder now."""
    client, _, _ = wo_actor(request, db)
    d = svc.doc_or_404(db, client.id, doc_id)
    if d.status not in svc.WAITING:
        raise HTTPException(409, "%s has had its reply." % d.number)
    ok, why = svc.remind(db, client, d)
    db.commit()
    if not ok:
        raise HTTPException(502, "The reminder was not sent: %s." % why)
    return {"ok": True, "item": svc.doc_dict(db, d, items=True), "message": "Reminder sent to %s." % d.to_email}
