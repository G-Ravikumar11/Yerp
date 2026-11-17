"""Owners and due dates for NCRs, incidents and work permits (services/follow_up.py).

    GET /api/follow-up/people                  the staff an item can be given to
    PUT /api/follow-up/{kind}/{item_id}        set its owner, and its due date (an NCR's target date, an incident's due
                                               date; a permit is due when it runs out and has no other)
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_items_access, wo_actor
from app.db import get_db, get_read_db
from app.services import follow_up
from app.services.hr import employee_name

router = APIRouter()


class FollowUpIn(BaseModel):
    owner_id: Optional[int] = None
    due_date: Optional[str] = None


@router.get("/api/follow-up/people")
def follow_up_people(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, ("site.signoff", "site.record"))
    live = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id,
                                             models.DBEmployee.status.in_(follow_up.LIVE)).all()
    return {"people": sorted(({"id": e.id, "name": employee_name(e), "designation": getattr(e, "designation", "") or ""} for e in live),
                             key=lambda p: p["name"].lower())}


@router.put("/api/follow-up/{kind}/{item_id}")
def set_follow_up(kind: str, item_id: int, body: FollowUpIn, request: Request, db: Session = Depends(get_db)):
    if kind not in follow_up.KINDS:
        raise HTTPException(404, "Owners are set on NCRs, incidents and permits.")
    client, _, actor = wo_actor(request, db, "site.signoff")
    k = follow_up.KINDS[kind]
    M = k["model"]
    row = db.query(M).filter(M.id == item_id, M.client_id == client.id).first()
    if row is None:
        raise HTTPException(404, "%s not found" % k["label"])
    if not k["open"](row):
        raise HTTPException(409, "%s %s is closed." % (k["label"], row.number))
    emp = follow_up.owner_or_400(db, client.id, body.owner_id)
    if body.due_date is not None and kind != "permit":
        due = (body.due_date or "").strip()[:10]
        if due:
            try:
                date.fromisoformat(due)
            except ValueError:
                raise HTTPException(400, "The due date should be a date.")
            if due < date.today().isoformat() and due != k["due"](row):
                raise HTTPException(400, "The due date is already past.")
        if kind == "ncr":
            if not due and row.target_date:
                raise HTTPException(400, "An NCR keeps its due date once it has one.")
            row.target_date = due
        else:
            row.due_date = due
    changed_owner = (emp.id if emp else None) != row.owner_id
    row.owner_id = emp.id if emp else None
    if changed_owner or body.due_date is not None:
        row.reminded_on, row.overdue_told = "", 0           # a new owner or date starts the reminders afresh
    log_audit(db, client.id, "follow_up_set", kind, row.id, row.number or "",
              "Owner %s, due %s" % (employee_name(emp) if emp else "none", k["due"](row) or "-"), request)
    if changed_owner and emp is not None:
        follow_up.tell_new_owner(db, client.id, kind, row, actor)
    db.commit()
    return {"ok": True, **follow_up.summary(row, kind), "owner_name": employee_name(emp) if emp else "",
            "message": ("%s %s is %s's to see through%s." % (k["label"], row.number, employee_name(emp),
                                                            (", due %s" % k["due"](row)) if k["due"](row) else ""))
            if emp else "%s %s has no owner now." % (k["label"], row.number)}
