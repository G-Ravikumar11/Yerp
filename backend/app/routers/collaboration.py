"""The collaboration endpoints."""
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import CHAT_MAX_BODY
from app.core.config import logger
from app.core.files import file_dict, store_file
from app.schemas.collaboration import (
    MessageEditIn, MessageIn, NoticesReadIn, ReactionIn, TaskEditIn, TaskIn, ThreadEditIn, ThreadIn,
)
from app.services.collaboration import (
    _last_read,
    _mark_read,
    chat_people,
    find_mentions,
    meeting_rooms,
    signaling,
    thread_or_404,
)
from app.services.chat_work import (
    CATEGORIES, EMOJI, PRIORITIES, TASK_STATUSES, chat_scope, clean_members, due_notices, history, keys, link_target,
    messages_out, names_of, need_office_or_own, notice_dict, now, post_message, task_out, tell, thread_files, thread_for,
    thread_out, trail, unread_notices, participants,
)
from app.services.projects import job_or_404


router = APIRouter()


@router.get("/meeting")
async def meeting_page(request: Request):
    query = request.url.query
    return RedirectResponse("/next/meeting" + ("?" + query if query else ""))


@router.websocket("/ws/meeting/{room_id}")
async def meeting_websocket(websocket: WebSocket, room_id: str):
    sess = websocket.session
    if not (sess.get("client_id") or sess.get("employee_id") or sess.get("portal_user_id")):
        await websocket.close(code=1008)
        return
    user_id = websocket.query_params.get("user_id", str(uuid.uuid4())[:8])[:40]
    display_name = websocket.query_params.get("name", "Guest")[:60]
    here = signaling.connections.get(room_id, [])
    if (any(c["user_id"] == user_id for c in here) or len(here) >= 20
            or (not here and len(signaling.connections) >= 200)):
        await websocket.close(code=1008)
        return

    await signaling.connect(websocket, room_id, user_id)
    room = meeting_rooms[room_id]

    # Host assignment logic
    if not room.get("host"):
        room["host"] = user_id
    
    is_host = room["host"] == user_id

    # Waiting room logic
    if room.get("locked") and not is_host:
        room["waiting"][user_id] = {"name": display_name, "ws": websocket}
        await signaling.send_to(room_id, user_id, {"type": "waiting"})
        await signaling.send_to(room_id, room["host"], {
            "type": "join-request",
            "user_id": user_id,
            "name": display_name
        })
        # Keep connection open but don't join yet
    else:
        # Join immediately
        room["participants"][user_id] = {"joined_at": datetime.utcnow().isoformat(), "name": display_name}
        participants = signaling.get_participants(room_id)
        
        await signaling.send_to(room_id, user_id, {
            "type": "welcome",
            "user_id": user_id,
            "is_host": is_host,
            "host_id": room["host"],
            "participants": [p for p in participants if p != user_id]
        })
        
        await signaling.broadcast(room_id, {
            "type": "user-joined",
            "user_id": user_id,
            "name": display_name,
            "participants": participants
        }, exclude_user=user_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            # Host controls
            if msg_type == "admit-user" and room["host"] == user_id:
                target_id = data.get("target")
                if target_id in room["waiting"]:
                    del room["waiting"][target_id]
                    room["participants"][target_id] = {"joined_at": datetime.utcnow().isoformat(), "name": data.get("name")}
                    await signaling.send_to(room_id, target_id, {
                        "type": "welcome",
                        "user_id": target_id,
                        "is_host": False,
                        "host_id": room["host"],
                        "participants": [p for p in signaling.get_participants(room_id) if p != target_id]
                    })
                    await signaling.broadcast(room_id, {
                        "type": "user-joined",
                        "user_id": target_id,
                        "name": data.get("name"),
                        "participants": signaling.get_participants(room_id)
                    }, exclude_user=target_id)
            
            elif msg_type == "deny-user" and room["host"] == user_id:
                target_id = data.get("target")
                if target_id in room["waiting"]:
                    del room["waiting"][target_id]
                    await signaling.send_to(room_id, target_id, {"type": "denied"})
            
            elif msg_type == "mute-all" and room["host"] == user_id:
                await signaling.broadcast(room_id, {"type": "force-mute"}, exclude_user=user_id)
                
            elif msg_type == "remove-user" and room["host"] == user_id:
                await signaling.send_to(room_id, data.get("target"), {"type": "removed"})
                
            elif msg_type == "toggle-lock" and room["host"] == user_id:
                room["locked"] = data.get("locked", False)
                await signaling.broadcast(room_id, {"type": "room-locked", "locked": room["locked"]})

            # Meeting Features
            elif msg_type == "raise-hand":
                await signaling.broadcast(room_id, {
                    "type": "raise-hand",
                    "user_id": user_id,
                    "name": display_name
                }, exclude_user=user_id)
                
            elif msg_type == "caption":
                await signaling.broadcast(room_id, {
                    "type": "caption",
                    "user_id": user_id,
                    "name": display_name,
                    "text": data.get("text", "")
                }, exclude_user=user_id)

            # Standard WebRTC Signaling
            elif msg_type == "offer":
                await signaling.send_to(room_id, data.get("target"), {
                    "type": "offer",
                    "offer": data.get("offer"),
                    "from": user_id,
                    "name": display_name
                })
            elif msg_type == "answer":
                await signaling.send_to(room_id, data.get("target"), {
                    "type": "answer",
                    "answer": data.get("answer"),
                    "from": user_id
                })
            elif msg_type == "ice-candidate":
                await signaling.send_to(room_id, data.get("target"), {
                    "type": "ice-candidate",
                    "candidate": data.get("candidate"),
                    "from": user_id
                })
            elif msg_type == "chat":
                await signaling.broadcast(room_id, {
                    "type": "chat",
                    "from": user_id,
                    "name": display_name,
                    "message": data.get("message", "")
                })
            elif msg_type == "toggle-media":
                await signaling.broadcast(room_id, {
                    "type": "toggle-media",
                    "user_id": user_id,
                    "kind": data.get("kind"),
                    "muted": data.get("muted")
                }, exclude_user=user_id)
            elif msg_type == "screen-share-started":
                await signaling.broadcast(room_id, {
                    "type": "screen-share-started",
                    "user_id": user_id,
                    "name": display_name
                }, exclude_user=user_id)
            elif msg_type == "screen-share-stopped":
                await signaling.broadcast(room_id, {
                    "type": "screen-share-stopped",
                    "user_id": user_id
                }, exclude_user=user_id)

    except WebSocketDisconnect:
        signaling.disconnect(room_id, user_id)
        if user_id in room.get("participants", {}):
            participants = signaling.get_participants(room_id)
            await signaling.broadcast(room_id, {
                "type": "user-left",
                "user_id": user_id,
                "name": display_name,
                "participants": participants,
                "new_host": room.get("host")
            })
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        signaling.disconnect(room_id, user_id)
        participants = signaling.get_participants(room_id)
        await signaling.broadcast(room_id, {
            "type": "user-left",
            "user_id": user_id,
            "name": display_name,
            "participants": participants
        })


# ---- project chat ----------------------------------------------------------------------------
# Who sees what: the office sees every project; a member of staff sees the projects they are assigned to,
# and every call below checks that against the thread's project, not the screen.

def _day(value, what):
    v = (value or "").strip()[:10]
    if not v:
        return ""
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "The %s as a date: 2026-09-30." % what)
    return v


def _thread_fields(db, sc, body, t=None):
    """Checked values for a thread's category, priority, people and link."""
    out = {}
    if body.category is not None:
        if body.category not in CATEGORIES:
            raise HTTPException(400, "Category is one of: %s." % ", ".join(CATEGORIES))
        out["category"] = body.category
    if body.priority is not None:
        if body.priority not in PRIORITIES:
            raise HTTPException(400, "Priority is one of: %s." % ", ".join(PRIORITIES))
        out["priority"] = body.priority
    if body.members is not None:
        out["members"] = ",".join(clean_members(db, sc.client.id, body.members))
    if body.link_type is not None:
        ref, rid = link_target(db, sc.client.id, body.link_type, body.link_ref)
        out["link_type"], out["link_ref"], out["link_id"] = body.link_type, ref if body.link_type else "", rid if body.link_type else None
    return out


@router.get("/api/chat/threads")
def chat_threads(request: Request, job_id: int = 0, q: str = "", category: str = "", priority: str = "",
                 status: str = "", member: str = "", date_from: str = "", date_to: str = "", unread: bool = False,
                 task_status: str = "", db: Session = Depends(get_db)):
    """The threads of one project, or of every project the reader is on, busiest first - narrowed by whatever is asked."""
    sc = chat_scope(request, db)
    T, M = models.DBProjectThread, models.DBProjectMessage
    query = db.query(T).filter(T.client_id == sc.client.id)
    if job_id:
        job_or_404(db, sc.client.id, job_id)
        sc.need(job_id)
        query = query.filter(T.job_id == job_id)
    elif sc.jobs is not None:
        query = query.filter(T.job_id.in_(sc.jobs or [-1]))
    if category:
        query = query.filter(T.category == category)
    if priority:
        query = query.filter(T.priority == priority)
    if status == "open":
        query = query.filter(T.closed.is_(False))
    elif status == "closed":
        query = query.filter(T.closed.is_(True))
    if member:
        query = query.filter((T.members.like("%" + member + "%")) | (T.started_by == member))
    if date_from:
        query = query.filter(T.last_message_at >= date_from[:10])
    if date_to:
        query = query.filter(T.last_message_at <= date_to[:10] + " 23:59:59")
    if task_status:
        ids = [i for (i,) in db.query(models.DBChatTask.thread_id).filter(models.DBChatTask.client_id == sc.client.id,
                                                                         models.DBChatTask.status == task_status).distinct().all()]
        query = query.filter(T.id.in_(ids or [-1]))
    if q.strip():
        like = "%" + q.strip() + "%"
        hit = [i for (i,) in db.query(M.thread_id).filter(M.client_id == sc.client.id, M.deleted.is_(False), M.body.ilike(like)).distinct().all()]
        query = query.filter(T.title.ilike(like) | T.description.ilike(like) | T.id.in_(hit or [-1]))
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == sc.client.id).all()}
    names = names_of(db, sc.client.id)
    rows = [thread_out(db, t, sc, jobs, names) for t in query.order_by(T.closed, T.last_message_at.desc()).limit(300).all()]
    if unread:
        rows = [r for r in rows if r["unread"]]
    return {"threads": rows, "me": sc.me, "unread": sum(r["unread"] for r in rows), "categories": list(CATEGORIES), "priorities": list(PRIORITIES)}


@router.get("/api/chat/unread")
def chat_unread(request: Request, db: Session = Depends(get_db)):
    """For the badge on the menu: messages I have not opened, and notices I have not read."""
    sc = chat_scope(request, db)
    total = 0
    q = db.query(models.DBProjectThread).filter(models.DBProjectThread.client_id == sc.client.id,
                                                models.DBProjectThread.closed.is_(False))
    if sc.jobs is not None:
        q = q.filter(models.DBProjectThread.job_id.in_(sc.jobs or [-1]))
    for t in q.all():
        total += db.query(models.DBProjectMessage).filter(
            models.DBProjectMessage.thread_id == t.id, models.DBProjectMessage.author != sc.me,
            models.DBProjectMessage.deleted.is_(False),
            models.DBProjectMessage.id > _last_read(db, t.id, sc.me)).count()
    return {"unread": total, "notices": unread_notices(db, sc)}


@router.get("/api/chat/people")
def chat_people_list(request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    return {"people": chat_people(db, sc.client.id), "me": sc.me, "my_name": sc.name}


@router.post("/api/chat/threads")
def start_thread(body: ThreadIn, request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    job_or_404(db, sc.client.id, body.job_id)
    sc.need(body.job_id)
    title = (body.title or "").strip()[:140]
    if not title:
        raise HTTPException(400, "What is it about? A thread needs a subject - \"Raft pour, grid A-C\".")
    fields = _thread_fields(db, sc, body)
    t = models.DBProjectThread(client_id=sc.client.id, job_id=body.job_id, title=title, started_by=sc.me,
                               started_by_name=sc.name, last_message_at=now(), description=(body.description or "").strip()[:2000],
                               **fields)
    db.add(t)
    db.flush()
    trail(db, sc, "chat.thread.started", t, "%s, %s priority" % (t.category, t.priority), request)
    tell(db, sc.client.id, keys(t.members), sc.me, "update", "%s added you to %s" % (sc.name, t.title), (t.description or "")[:200], t.id)
    if (body.body or "").strip() or body.file_ids:
        post_message(db, sc, t, body.body, body.file_ids, None, request)
    db.commit()
    return {"thread": thread_out(db, t, sc)}


@router.put("/api/chat/threads/{thread_id}")
def edit_thread(thread_id: int, body: ThreadEditIn, request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    t = thread_for(db, sc, thread_id)
    need_office_or_own(sc, t.started_by, "this thread")
    changed = []
    if body.title is not None:
        title = body.title.strip()[:140]
        if not title:
            raise HTTPException(400, "A thread needs a subject.")
        if title != t.title:
            t.title = title
            changed.append("title")
    if body.description is not None and body.description.strip() != (t.description or ""):
        t.description = body.description.strip()[:2000]
        changed.append("description")
    before = set(keys(t.members))
    for k, v in _thread_fields(db, sc, body, t).items():
        if getattr(t, k) != v:
            setattr(t, k, v)
            changed.append(k.replace("_", " "))
    added = [k for k in keys(t.members) if k not in before]
    if added:
        tell(db, sc.client.id, added, sc.me, "update", "%s added you to %s" % (sc.name, t.title), "", t.id)
    if changed:
        trail(db, sc, "chat.thread.updated", t, "Changed " + ", ".join(changed), request)
    db.commit()
    return {"thread": thread_out(db, t, sc)}


@router.get("/api/chat/threads/{thread_id}")
def read_thread(thread_id: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    """The thread, its messages, tasks, files and history. Opening it marks it read."""
    sc = chat_scope(request, db)
    t = thread_for(db, sc, thread_id)
    q = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.thread_id == t.id)
    if after:
        q = q.filter(models.DBProjectMessage.id > after)
    msgs = q.order_by(models.DBProjectMessage.id).limit(500).all()
    if msgs:
        _mark_read(db, t.id, sc.me, msgs[-1].id)
        db.commit()
    names = names_of(db, sc.client.id)
    tasks = db.query(models.DBChatTask).filter(models.DBChatTask.thread_id == t.id).order_by(models.DBChatTask.id.desc()).all()
    return {"thread": thread_out(db, t, sc, names=names), "messages": messages_out(db, msgs, sc), "me": sc.me,
            "tasks": [task_out(x, names, sc) for x in tasks], "files": thread_files(db, t),
            "history": history(db, sc.client.id, t.id)}


@router.post("/api/chat/threads/{thread_id}/messages")
def post_message_endpoint(thread_id: int, body: MessageIn, request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    t = thread_for(db, sc, thread_id)
    m = post_message(db, sc, t, body.body, body.file_ids, body.parent_id, request)
    db.commit()
    return {"message": messages_out(db, [m], sc)[0]}


def _own_message(db, sc, message_id):
    m = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.id == message_id,
                                                 models.DBProjectMessage.client_id == sc.client.id).first()
    if not m:
        raise HTTPException(404, "Message not found")
    t = thread_for(db, sc, m.thread_id)
    return m, t


@router.put("/api/chat/messages/{message_id}")
def edit_message(message_id: int, body: MessageEditIn, request: Request, db: Session = Depends(get_db)):
    """Only whoever wrote it, and only while the thread is open. It shows as edited."""
    sc = chat_scope(request, db)
    m, t = _own_message(db, sc, message_id)
    if m.author != sc.me:
        raise HTTPException(403, "Only whoever wrote a message can edit it.")
    if m.deleted:
        raise HTTPException(409, "That message was removed.")
    if t.closed:
        raise HTTPException(409, "This thread is closed. Reopen it to carry on.")
    text = (body.body or "").strip()
    if not text and not m.file_ids:
        raise HTTPException(400, "A message cannot be left empty - remove it instead.")
    if len(text) > CHAT_MAX_BODY:
        raise HTTPException(400, "That is a long message - keep it under %d characters." % CHAT_MAX_BODY)
    if text != (m.body or ""):
        m.body, m.edited_at = text, now()
        m.mentions = ",".join(p["key"] for p in find_mentions(text, chat_people(db, sc.client.id)) if p["key"] != sc.me)
        trail(db, sc, "chat.message.edited", t, "Message %d edited" % m.id, request)
    db.commit()
    return {"message": messages_out(db, [m], sc)[0]}


@router.delete("/api/chat/messages/{message_id}")
def remove_message(message_id: int, request: Request, db: Session = Depends(get_db)):
    """Your own message can be taken back; it stays as "removed" so the replies around it still make sense."""
    sc = chat_scope(request, db)
    m, t = _own_message(db, sc, message_id)
    if m.author != sc.me:
        raise HTTPException(403, "Only whoever wrote a message can remove it.")
    m.deleted = True
    trail(db, sc, "chat.message.removed", t, "Message %d removed" % m.id, request)
    db.commit()
    return {"message": messages_out(db, [m], sc)[0]}


@router.post("/api/chat/messages/{message_id}/reactions")
def react(message_id: int, body: ReactionIn, request: Request, db: Session = Depends(get_db)):
    """Put an emoji on a message, or take yours off again."""
    sc = chat_scope(request, db)
    m, t = _own_message(db, sc, message_id)
    if body.emoji not in EMOJI:
        raise HTTPException(400, "Pick one of the reactions offered.")
    if m.deleted:
        raise HTTPException(409, "That message was removed.")
    R = models.DBChatReaction
    have = db.query(R).filter(R.message_id == m.id, R.reader == sc.me, R.emoji == body.emoji).first()
    if have:
        db.delete(have)
    else:
        db.add(R(message_id=m.id, reader=sc.me, emoji=body.emoji))
    db.commit()
    return {"message": messages_out(db, [m], sc)[0]}


@router.post("/api/chat/threads/{thread_id}/files")
def chat_upload(thread_id: int, request: Request, file: UploadFile = File(...),
                thumb: Optional[UploadFile] = File(None), caption: str = Form(""), db: Session = Depends(get_db)):
    """A photo or a document put up in a thread, for the next message to carry. Checked as every upload is:
    the type, the size, and that it is this company's thread on a project the sender is on."""
    sc = chat_scope(request, db)
    t = thread_for(db, sc, thread_id)
    if t.closed:
        raise HTTPException(409, "This thread is closed. Reopen it to carry on.")
    data = file.file.read()
    small = thumb.file.read() if thumb is not None else None
    ctype = (file.content_type or "").lower()
    f = store_file(db, sc.client.id, file, data, job_id=t.job_id, attached_type="thread", attached_id=t.id,
                   kind="photo" if ctype.startswith("image/") else "document",
                   taken_on=date.today().isoformat(), by=sc.name, thumb=small)
    if caption.strip():
        f.caption = caption.strip()[:200]
    db.commit()
    return {"file": file_dict(f)}


# ---- tasks -----------------------------------------------------------------------------------

def _assignee(db, sc, key):
    if not key:
        return "", ""
    names = names_of(db, sc.client.id)
    if key not in names:
        raise HTTPException(400, "That person is not in this company.")
    return key, names[key]


@router.post("/api/chat/threads/{thread_id}/tasks")
def make_task(thread_id: int, body: TaskIn, request: Request, db: Session = Depends(get_db)):
    """An action item, usually from a message: what, who, by when."""
    sc = chat_scope(request, db)
    t = thread_for(db, sc, thread_id)
    msg = None
    if body.message_id:
        msg = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.id == body.message_id,
                                                       models.DBProjectMessage.thread_id == t.id).first()
        if not msg or msg.deleted:
            raise HTTPException(400, "That message is not in this thread.")
    title = (body.title or "").strip() or ((msg.body if msg else "") or "").strip()[:120]
    if not title:
        raise HTTPException(400, "What is to be done?")
    if body.priority not in PRIORITIES:
        raise HTTPException(400, "Priority is one of: %s." % ", ".join(PRIORITIES))
    due = _day(body.due_date, "due date")
    if due and due < date.today().isoformat():
        raise HTTPException(400, "The due date is already past.")
    who, who_name = _assignee(db, sc, body.assignee)
    desc = (body.description or "").strip()[:2000] or ((msg.body or "")[:2000] if msg else "")
    task = models.DBChatTask(client_id=sc.client.id, job_id=t.job_id, thread_id=t.id, message_id=msg.id if msg else None,
                             title=title[:200], description=desc, assignee=who, assignee_name=who_name, due_date=due,
                             priority=body.priority, created_by=sc.me, created_by_name=sc.name, created_at=now(), updated_at=now())
    db.add(task)
    db.flush()
    trail(db, sc, "chat.task.created", t, "%s%s%s" % (task.title, " -> " + who_name if who_name else "", " by " + due if due else ""), request)
    tell(db, sc.client.id, [who], sc.me, "assigned", "%s gave you a task: %s" % (sc.name, task.title),
         "Due %s" % due if due else "", t.id, task.id)
    db.commit()
    return {"task": task_out(task, sc=sc)}


@router.get("/api/chat/tasks")
def list_tasks(request: Request, job_id: int = 0, thread_id: int = 0, status: str = "", mine: bool = False,
               db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    q = db.query(models.DBChatTask).filter(models.DBChatTask.client_id == sc.client.id)
    if sc.jobs is not None:
        q = q.filter(models.DBChatTask.job_id.in_(sc.jobs or [-1]))
    if job_id:
        q = q.filter(models.DBChatTask.job_id == job_id)
    if thread_id:
        q = q.filter(models.DBChatTask.thread_id == thread_id)
    if status:
        q = q.filter(models.DBChatTask.status == status)
    if mine:
        q = q.filter(models.DBChatTask.assignee == sc.me)
    names = names_of(db, sc.client.id)
    return {"tasks": [task_out(x, names, sc) for x in q.order_by(models.DBChatTask.id.desc()).limit(300).all()]}


@router.put("/api/chat/tasks/{task_id}")
def edit_task(task_id: int, body: TaskEditIn, request: Request, db: Session = Depends(get_db)):
    """The assignee moves it along; whoever made it, and the office, can change anything."""
    sc = chat_scope(request, db)
    x = db.query(models.DBChatTask).filter(models.DBChatTask.id == task_id, models.DBChatTask.client_id == sc.client.id).first()
    if not x:
        raise HTTPException(404, "Task not found")
    t = thread_for(db, sc, x.thread_id)
    owner = sc.office or x.created_by == sc.me
    if not (owner or x.assignee == sc.me):
        raise HTTPException(403, "Only whoever it is for, whoever made it, or the office can change a task.")
    notes = []
    if body.status is not None and body.status != x.status:
        if body.status not in TASK_STATUSES:
            raise HTTPException(400, "Status is one of: %s." % ", ".join(TASK_STATUSES))
        if body.status == "Closed" and not owner:
            raise HTTPException(403, "Only whoever made the task, or the office, closes it.")
        notes.append("%s -> %s" % (x.status, body.status))
        x.status = body.status
    if any(v is not None for v in (body.title, body.description, body.assignee, body.due_date, body.priority)) and not owner:
        raise HTTPException(403, "Only whoever made the task, or the office, can change what it says or who it is for.")
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(400, "What is to be done?")
        x.title = body.title.strip()[:200]
    if body.description is not None:
        x.description = body.description.strip()[:2000]
    if body.priority is not None:
        if body.priority not in PRIORITIES:
            raise HTTPException(400, "Priority is one of: %s." % ", ".join(PRIORITIES))
        x.priority = body.priority
    if body.due_date is not None:
        x.due_date = _day(body.due_date, "due date")
    if body.assignee is not None and body.assignee != x.assignee:
        x.assignee, x.assignee_name = _assignee(db, sc, body.assignee)
        notes.append("now for %s" % (x.assignee_name or "nobody"))
        tell(db, sc.client.id, [x.assignee], sc.me, "assigned", "%s gave you a task: %s" % (sc.name, x.title), "", t.id, x.id)
    x.updated_at = now()
    if notes:
        trail(db, sc, "chat.task.updated", t, "%s: %s" % (x.title, "; ".join(notes)), request)
        tell(db, sc.client.id, [x.created_by, x.assignee], sc.me, "update", "Task %s: %s" % (x.status.lower(), x.title), "; ".join(notes), t.id, x.id)
    db.commit()
    return {"task": task_out(x, sc=sc)}


# ---- notices ---------------------------------------------------------------------------------

@router.get("/api/chat/notices")
def my_notices(request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    due_notices(db, sc)
    rows = db.query(models.DBChatNotice).filter(models.DBChatNotice.client_id == sc.client.id,
                                                models.DBChatNotice.recipient == sc.me).order_by(
        models.DBChatNotice.id.desc()).limit(60).all()
    return {"notices": [notice_dict(n) for n in rows], "unread": unread_notices(db, sc)}


@router.post("/api/chat/notices/read")
def read_notices(body: NoticesReadIn, request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    q = db.query(models.DBChatNotice).filter(models.DBChatNotice.client_id == sc.client.id,
                                             models.DBChatNotice.recipient == sc.me, models.DBChatNotice.is_read.is_(False))
    if body.ids:
        q = q.filter(models.DBChatNotice.id.in_([int(i) for i in body.ids]))
    for n in q.all():
        n.is_read = True
    db.commit()
    return {"unread": unread_notices(db, sc)}


@router.post("/api/chat/threads/{thread_id}/{action}")
def close_thread(thread_id: int, action: str, request: Request, db: Session = Depends(get_db)):
    sc = chat_scope(request, db)
    if action not in ("close", "reopen"):
        raise HTTPException(404, "Not found")
    t = thread_for(db, sc, thread_id)
    t.closed = action == "close"
    trail(db, sc, "chat.thread.closed" if t.closed else "chat.thread.reopened", t, "", request)
    tell(db, sc.client.id, participants(db, t), sc.me, "update", "%s %s \"%s\"" % (sc.name, "closed" if t.closed else "reopened", t.title), "", t.id)
    db.commit()
    return {"thread": thread_out(db, t, sc),
            "message": "\"%s\" %s." % (t.title, "closed" if t.closed else "reopened")}
