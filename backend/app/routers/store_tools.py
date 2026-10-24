"""Store module - the tool register, under /api/store/tools: tools by serial number, giving one out and taking it back, damage, service, loss, and
the reminders for what is overdue. store.outward.view reads; store.outward.create registers, gives out, takes back and services a tool; writing one off
(lost or retired) needs store.outward.approve, so the person who handed it out does not also write it off."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.permissions import permissions_for
from app.core.store_auth import store_actor
from app.db import get_db
from app.models.store_core import DBStore, DBStoreUserAssignment
from app.models.store_extras import DBStoreTool
from app.services import store_tools as svc
from app.services.stock_ledger import assert_store_access

router = APIRouter(prefix="/api/store/tools", tags=["store-tools"])
WRITE_OFFS, WRITE_OFF_RIGHT = ("lose", "retire"), "store.outward.approve"


class RegisterIn(BaseModel):
    item_id: int
    store_id: int
    serial_no: str
    condition: str = "GOOD"
    next_service: Optional[str] = None
    notes: str = ""


class ActionIn(BaseModel):
    holder_name: str = ""
    project_id: Optional[int] = None
    due_back: Optional[str] = None
    issue_id: Optional[int] = None
    condition: str = "GOOD"
    next_service: Optional[str] = None
    note: str = ""


def _visible(db, actor):
    if actor.employee is None or "store.admin" in permissions_for(actor.employee):
        return None
    return {r for (r,) in db.query(DBStoreUserAssignment.store_id).filter(DBStoreUserAssignment.employee_id == actor.employee.id, DBStoreUserAssignment.is_active.is_(True)).all()}


def _tool(db, actor, tool_id):
    tool = db.get(DBStoreTool, tool_id)
    if tool is None or tool.client_id != actor.client.id:
        raise HTTPException(404, "Tool not found")
    assert_store_access(actor.user, tool.store_id)
    return tool


@router.get("")
def list_tools(request: Request, status: str = "", store_id: int = 0, q: str = "", db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    query = db.query(DBStoreTool).filter(DBStoreTool.client_id == actor.client.id)
    seen = _visible(db, actor)
    if seen is not None:
        query = query.filter(DBStoreTool.store_id.in_(seen or {0}))
    if store_id:
        assert_store_access(actor.user, store_id)
        query = query.filter(DBStoreTool.store_id == store_id)
    if status:
        query = query.filter(DBStoreTool.status == status.strip().upper())
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("%", "").replace("_", "") + "%"
        ids = [i for (i,) in db.query(models.DBItem.id).filter(models.DBItem.client_id == actor.client.id, models.DBItem.item_name.ilike(like) | models.DBItem.item_code.ilike(like)).all()]
        query = query.filter(DBStoreTool.serial_no.ilike(like) | DBStoreTool.holder_name.ilike(like) | DBStoreTool.item_id.in_(ids or [0]))
    rows = query.order_by(DBStoreTool.id.desc()).limit(500).all()
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_([r.item_id for r in rows] or [0])).all()}
    stores = {s.id: s for s in db.query(DBStore).filter(DBStore.client_id == actor.client.id).all()}
    return {"items": [svc.tool_dict(db, r, items.get(r.item_id), stores.get(r.store_id)) for r in rows]}


@router.post("")
def register_tool(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.create")
    assert_store_access(actor.user, body.store_id)
    try:
        tool = svc.register(db, actor, body.item_id, body.store_id, body.serial_no, body.condition, body.next_service, body.notes)
        log_audit(db, actor.client.id, "store_tool_registered", "store_tool", tool.id, tool.serial_no, "", request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return svc.tool_dict(db, tool, detail=True)


@router.post("/remind")
def remind(request: Request, db: Session = Depends(get_db)):
    """Send the reminders now: overdue returnables and tools, and tools due for service (each repeated weekly, not daily)."""
    actor = store_actor(request, db, "store.outward.create")
    return {"mentioned": svc.send_reminders(db, actor.client.id)}


@router.get("/{tool_id}")
def get_tool(tool_id: int, request: Request, db: Session = Depends(get_db)):
    actor = store_actor(request, db, "store.outward.view")
    return svc.tool_dict(db, _tool(db, actor, tool_id), detail=True)


@router.post("/{tool_id}/{action}")
def act(tool_id: int, action: str, body: ActionIn, request: Request, db: Session = Depends(get_db)):
    """assign (give it out), receive (take it back, with its condition), service-out, service-done, lose, retire."""
    fn = svc.ACTIONS.get(action)
    if fn is None:
        raise HTTPException(404, "There is no such action.")
    actor = store_actor(request, db, WRITE_OFF_RIGHT if action in WRITE_OFFS else "store.outward.create")
    tool = _tool(db, actor, tool_id)
    try:
        if action == "assign":
            fn(db, actor, tool, body.holder_name, body.project_id, body.due_back, body.issue_id, body.note)
        elif action == "receive":
            fn(db, actor, tool, body.condition, body.note)
        elif action == "service-done":
            fn(db, actor, tool, body.next_service, body.note)
        else:
            fn(db, actor, tool, body.note)
        log_audit(db, actor.client.id, "store_tool_" + action.replace("-", "_"), "store_tool", tool.id, tool.serial_no, tool.status, request=request,
                  user_type="employee" if actor.employee is not None else "client", user_name=actor.name)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return svc.tool_dict(db, tool, detail=True)
