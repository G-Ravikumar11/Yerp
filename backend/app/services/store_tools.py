"""Store module - the tool register: tools by serial number, who holds each, what condition it came back in, and when it is next due for service,
with reminders for tools and returnable material that are overdue. The stock ledger still counts tools by quantity; nothing here moves stock."""
import logging
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core.scheduler import scheduled_job
from app.models.store_core import DBStore, DBStoreItemSettings
from app.models.store_extras import (
    TOOL_AVAILABLE, TOOL_IN_SERVICE, TOOL_ISSUED, TOOL_LOST, TOOL_RETIRED, DBStoreReminder, DBStoreTool, DBStoreToolEvent,
)

logger = logging.getLogger(__name__)
TOOL_CATEGORIES = ("TOOL", "RETURNABLE")
CONDITIONS = ("GOOD", "DAMAGED")
REMIND_EVERY = timedelta(days=7)
SERVICE_WARNING_DAYS = 7


def _text(raw, what, limit, required=False):
    out = " ".join((raw or "").split())
    if required and not out:
        raise HTTPException(400, "Give the %s." % what)
    if len(out) > limit:
        raise HTTPException(400, "Keep the %s to %d characters." % (what, limit))
    return out


def _date(raw, what, *, future_ok=True, required=False):
    if raw in (None, ""):
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return None
    if isinstance(raw, date):
        out = raw
    else:
        try:
            out = datetime.strptime(str(raw).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % what) from None
    if out.year < 2000 or out.year > 2100:
        raise HTTPException(400, "%s is not a sensible date." % what)
    if not future_ok and out > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)
    return out


def _event(db, actor, tool, event, note="", holder=""):
    db.add(DBStoreToolEvent(tool_id=tool.id, event=event, condition=tool.condition or "", holder_name=holder or "", note=note, by_name=actor.name))


def register(db, actor, item_id, store_id, serial_no, condition="GOOD", next_service=None, notes=""):
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != actor.client.id or item.kind != "RM":
        raise HTTPException(400, "That item is not a stock item of this company.")
    s = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
    if s is None or s.category not in TOOL_CATEGORIES:
        raise HTTPException(400, "Only items set up as a TOOL or a RETURNABLE are kept in the tool register.")
    store = db.get(DBStore, store_id) if store_id else None
    if store is None or store.client_id != actor.client.id:
        raise HTTPException(400, "That store does not exist.")
    serial = _text(serial_no, "serial number", 60, required=True)
    condition = (condition or "GOOD").strip().upper()
    if condition not in CONDITIONS:
        raise HTTPException(400, "The condition is GOOD or DAMAGED.")
    if db.query(DBStoreTool.id).filter(DBStoreTool.client_id == actor.client.id, DBStoreTool.item_id == item.id, DBStoreTool.serial_no.ilike(serial)).first():
        raise HTTPException(409, "%s serial %s is already in the register." % (item.item_name, serial))
    tool = DBStoreTool(client_id=actor.client.id, item_id=item.id, store_id=store.id, serial_no=serial, condition=condition, next_service=_date(next_service, "next service date"),
                       notes=_text(notes, "notes", 200), status=TOOL_AVAILABLE if condition == "GOOD" else TOOL_IN_SERVICE)
    db.add(tool)
    db.flush()
    _event(db, actor, tool, "REGISTERED", tool.notes)
    return tool


def assign(db, actor, tool, holder_name, project_id=None, due_back=None, issue_id=None, note=""):
    if tool.status != TOOL_AVAILABLE:
        raise HTTPException(409, "That tool is %s, so it cannot be given out." % tool.status.lower().replace("_", " "))
    holder = _text(holder_name, "name of who is taking it", 80, required=True)
    if project_id and not db.query(models.DBJob.id).filter(models.DBJob.id == project_id, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(400, "That project does not exist.")
    due = _date(due_back, "due back date")
    if due is not None and due < date.today():
        raise HTTPException(400, "The due back date is in the past.")
    tool.status, tool.holder_name, tool.project_id, tool.due_back, tool.issue_id = TOOL_ISSUED, holder, project_id or None, due, issue_id or None
    _event(db, actor, tool, "ISSUED", _text(note, "note", 200), holder)
    db.flush()


def receive(db, actor, tool, condition="GOOD", note=""):
    if tool.status != TOOL_ISSUED:
        raise HTTPException(409, "That tool is not out, so there is nothing to take back.")
    condition = (condition or "GOOD").strip().upper()
    if condition not in CONDITIONS:
        raise HTTPException(400, "The condition is GOOD or DAMAGED.")
    note = _text(note, "note", 200)
    if condition == "DAMAGED" and not note:
        raise HTTPException(400, "Say what is wrong with the damaged tool.")
    holder = tool.holder_name
    tool.condition = condition
    tool.status = TOOL_AVAILABLE if condition == "GOOD" else TOOL_IN_SERVICE
    tool.holder_name, tool.project_id, tool.due_back, tool.issue_id = "", None, None, None
    _event(db, actor, tool, "RETURNED", note, holder)
    db.flush()


def service_out(db, actor, tool, note=""):
    if tool.status != TOOL_AVAILABLE:
        raise HTTPException(409, "Only a tool that is in the store can be sent for service.")
    tool.status = TOOL_IN_SERVICE
    _event(db, actor, tool, "SERVICE_OUT", _text(note, "note", 200))
    db.flush()


def service_done(db, actor, tool, next_service=None, note=""):
    if tool.status != TOOL_IN_SERVICE:
        raise HTTPException(409, "That tool is not out for service.")
    tool.status, tool.condition, tool.last_service = TOOL_AVAILABLE, "GOOD", date.today()
    tool.next_service = _date(next_service, "next service date")
    _event(db, actor, tool, "SERVICE_DONE", _text(note, "note", 200))
    db.flush()


def lose(db, actor, tool, note=""):
    if tool.status in (TOOL_LOST, TOOL_RETIRED):
        raise HTTPException(409, "That tool is already %s." % tool.status.lower())
    note = _text(note, "note", 200)
    if len(note) < 3:
        raise HTTPException(400, "Say what happened to it.")
    holder = tool.holder_name
    tool.status = TOOL_LOST
    _event(db, actor, tool, "LOST", note, holder)
    db.flush()


def retire(db, actor, tool, note=""):
    if tool.status in (TOOL_ISSUED, TOOL_RETIRED):
        raise HTTPException(409, "A tool that is %s cannot be retired." % ("out" if tool.status == TOOL_ISSUED else "already retired"))
    tool.status, tool.holder_name, tool.due_back = TOOL_RETIRED, "", None
    _event(db, actor, tool, "RETIRED", _text(note, "note", 200))
    db.flush()


ACTIONS = {"assign": assign, "receive": receive, "service-out": service_out, "service-done": service_done, "lose": lose, "retire": retire}


def tool_dict(db, tool, item=None, store=None, detail=False):
    item = item or db.get(models.DBItem, tool.item_id)
    store = store or db.get(DBStore, tool.store_id)
    today = date.today()
    out = {"id": tool.id, "item_id": tool.item_id, "item_code": item.item_code if item else "", "item_name": item.item_name if item else "", "store_id": tool.store_id,
           "store_code": store.code if store else "", "serial_no": tool.serial_no, "status": tool.status, "condition": tool.condition or "GOOD", "holder_name": tool.holder_name or "",
           "project_id": tool.project_id, "due_back": tool.due_back.isoformat() if tool.due_back else "",
           "overdue_days": max(0, (today - tool.due_back).days) if tool.due_back and tool.status == TOOL_ISSUED else 0,
           "last_service": tool.last_service.isoformat() if tool.last_service else "", "next_service": tool.next_service.isoformat() if tool.next_service else "",
           "service_due": bool(tool.next_service and tool.next_service <= today + timedelta(days=SERVICE_WARNING_DAYS) and tool.status in (TOOL_AVAILABLE, TOOL_ISSUED)),
           "notes": tool.notes or ""}
    if detail:
        out["events"] = [{"event": e.event, "condition": e.condition or "", "holder": e.holder_name or "", "note": e.note or "", "by": e.by_name or "", "at": e.at.isoformat(timespec="seconds") if e.at else ""}
                         for e in db.query(DBStoreToolEvent).filter(DBStoreToolEvent.tool_id == tool.id).order_by(DBStoreToolEvent.id.desc()).all()]
    return out


# --- reminders -------------------------------------------------------------------------------------------------------------

def _due_for_reminder(db, client_id, kind, ref_ids):
    """The ids among `ref_ids` not reminded about in the last week; they are stamped as reminded now."""
    now = datetime.now()
    have = {r.ref_id: r for r in db.query(DBStoreReminder).filter(DBStoreReminder.client_id == client_id, DBStoreReminder.kind == kind, DBStoreReminder.ref_id.in_(list(ref_ids) or [0])).all()}
    fresh = []
    for ref in ref_ids:
        row = have.get(ref)
        if row is None:
            db.add(DBStoreReminder(client_id=client_id, kind=kind, ref_id=ref, last_sent_at=now))
            fresh.append(ref)
        elif now - (row.last_sent_at or now) >= REMIND_EVERY:
            row.last_sent_at = now
            fresh.append(ref)
    return fresh


def send_reminders(db, client_id):
    """Tell the company about returnable material and tools that are overdue and tools due for service, each once a week until dealt with.
    Returns how many things were mentioned."""
    from app.core.notifications import notify
    from app.services import store_outward
    today = date.today()
    lines, count = [], 0

    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.kind == "RM").all()}
    overdue = [r for r in store_outward.get_outstanding_returnables(db, client_id=client_id) if r.item_id in items and r.overdue_days > 0]
    for ref in _due_for_reminder(db, client_id, "RETURN_OVERDUE", [r.issue_line_id for r in overdue]):
        r = next(x for x in overdue if x.issue_line_id == ref)
        lines.append("- %s x %s is %d day%s overdue to come back" % (store_outward.s3(r.qty_outstanding).rstrip("0").rstrip("."), items[r.item_id].item_name, r.overdue_days, "" if r.overdue_days == 1 else "s"))
        count += 1

    tools = db.query(DBStoreTool).filter(DBStoreTool.client_id == client_id).all()
    late = [t for t in tools if t.status == TOOL_ISSUED and t.due_back and t.due_back < today]
    for ref in _due_for_reminder(db, client_id, "TOOL_RETURN_OVERDUE", [t.id for t in late]):
        t = next(x for x in late if x.id == ref)
        lines.append("- %s %s (held by %s) is %d day%s overdue" % (items[t.item_id].item_name if t.item_id in items else "Tool", t.serial_no, t.holder_name, (today - t.due_back).days, "" if (today - t.due_back).days == 1 else "s"))
        count += 1
    service = [t for t in tools if t.next_service and t.next_service <= today + timedelta(days=SERVICE_WARNING_DAYS) and t.status in (TOOL_AVAILABLE, TOOL_ISSUED)]
    for ref in _due_for_reminder(db, client_id, "TOOL_SERVICE_DUE", [t.id for t in service]):
        t = next(x for x in service if x.id == ref)
        lines.append("- %s %s is due for service on %s" % (items[t.item_id].item_name if t.item_id in items else "Tool", t.serial_no, t.next_service.isoformat()))
        count += 1
    db.commit()
    if lines:
        notify(db, client_id, "store_overdue", "%d thing%s to chase in the stores" % (count, "" if count == 1 else "s"), "\n".join(lines[:12]), view="dashboard-view", severity="action")
    return count


@scheduled_job("store_reminders")
def job_store_reminders(db, now):
    sent = 0
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        try:
            sent += send_reminders(db, client.id)
        except Exception as exc:
            db.rollback()
            logger.error("Store reminders for %s failed: %s", client.id, exc)
    return "%d reminder(s)" % sent
