"""The collaboration endpoints."""
import os
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.config import frontend_path, logger
from app.core.files import file_dict, store_file
from app.schemas.collaboration import MessageIn, ThreadIn
from app.services.collaboration import (
    _last_read,
    _mark_read,
    _post_message,
    chat_actor,
    chat_people,
    meeting_rooms,
    message_dict,
    signaling,
    thread_dict,
    thread_or_404,
)
from app.services.projects import job_or_404


router = APIRouter()


@router.get("/meeting", response_class=HTMLResponse)
async def meeting_page(request: Request):
    if not (request.session.get("client_id") or request.session.get("employee_id")
            or request.session.get("portal_user_id")):
        return RedirectResponse("/login.html")
    html_path = os.path.join(frontend_path, "meeting.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Meeting page not found</h1>", status_code=404)


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


@router.get("/api/chat/threads")
def chat_threads(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    """The threads - one project's, or every project's with the busiest
    first. Each with the reader's own unread count."""
    client, me, _ = chat_actor(request, db)
    q = db.query(models.DBProjectThread).filter(models.DBProjectThread.client_id == client.id)
    if job_id:
        job_or_404(db, client.id, job_id)
        q = q.filter(models.DBProjectThread.job_id == job_id)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    rows = [thread_dict(db, t, me, jobs) for t in q.order_by(
        models.DBProjectThread.closed, models.DBProjectThread.last_message_at.desc()).limit(300).all()]
    return {"threads": rows, "me": me, "unread": sum(r["unread"] for r in rows)}


@router.get("/api/chat/unread")
def chat_unread(request: Request, db: Session = Depends(get_db)):
    """For the badge on the menu: messages to me I have not opened."""
    client, me, _ = chat_actor(request, db)
    total = 0
    for t in db.query(models.DBProjectThread).filter(models.DBProjectThread.client_id == client.id,
                                                     models.DBProjectThread.closed.is_(False)).all():
        total += db.query(models.DBProjectMessage).filter(
            models.DBProjectMessage.thread_id == t.id, models.DBProjectMessage.author != me,
            models.DBProjectMessage.deleted.is_(False),
            models.DBProjectMessage.id > _last_read(db, t.id, me)).count()
    return {"unread": total}


@router.get("/api/chat/people")
def chat_people_list(request: Request, db: Session = Depends(get_db)):
    client, me, name = chat_actor(request, db)
    return {"people": chat_people(db, client.id), "me": me, "my_name": name}


@router.post("/api/chat/threads")
def start_thread(body: ThreadIn, request: Request, db: Session = Depends(get_db)):
    client, me, name = chat_actor(request, db)
    job_or_404(db, client.id, body.job_id)
    title = (body.title or "").strip()[:140]
    if not title:
        raise HTTPException(400, "What is it about? A thread needs a subject - \"Raft pour, grid A-C\".")
    t = models.DBProjectThread(client_id=client.id, job_id=body.job_id, title=title, started_by=me,
                               started_by_name=name, last_message_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    db.add(t)
    db.flush()
    if (body.body or "").strip() or body.file_ids:
        _post_message(db, client, t, me, name, body.body, body.file_ids, request)
    else:
        db.commit()
    return {"thread": thread_dict(db, t, me)}


@router.get("/api/chat/threads/{thread_id}")
def read_thread(thread_id: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    """The thread's messages - all of them, or only those after `after` for
    a screen that is already showing the rest. Opening it marks it read."""
    client, me, _ = chat_actor(request, db)
    t = thread_or_404(db, client.id, thread_id)
    q = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.thread_id == t.id)
    if after:
        q = q.filter(models.DBProjectMessage.id > after)
    msgs = q.order_by(models.DBProjectMessage.id).limit(500).all()
    if msgs:
        _mark_read(db, t.id, me, msgs[-1].id)
        db.commit()
    return {"thread": thread_dict(db, t, me), "messages": [message_dict(db, m, me) for m in msgs], "me": me}


@router.post("/api/chat/threads/{thread_id}/messages")
def post_message(thread_id: int, body: MessageIn, request: Request, db: Session = Depends(get_db)):
    client, me, name = chat_actor(request, db)
    t = thread_or_404(db, client.id, thread_id)
    m = _post_message(db, client, t, me, name, body.body, body.file_ids, request)
    return {"message": message_dict(db, m, me)}


@router.delete("/api/chat/messages/{message_id}")
def remove_message(message_id: int, request: Request, db: Session = Depends(get_db)):
    """Your own message can be taken back; it stays as "removed" so the
    replies around it still make sense."""
    client, me, _ = chat_actor(request, db)
    m = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.id == message_id,
                                                 models.DBProjectMessage.client_id == client.id).first()
    if not m:
        raise HTTPException(404, "Message not found")
    if m.author != me:
        raise HTTPException(403, "Only whoever wrote a message can remove it.")
    m.deleted = True
    db.commit()
    return {"message": message_dict(db, m, me)}


@router.post("/api/chat/threads/{thread_id}/files")
def chat_upload(thread_id: int, request: Request, file: UploadFile = File(...),
                thumb: Optional[UploadFile] = File(None), db: Session = Depends(get_db)):
    """A photo or a document put up in a thread, for the next message to
    carry. Anybody in the conversation can, not only those who may file
    drawings - the site engineer with the photo of the crack most of all."""
    client, me, name = chat_actor(request, db)
    t = thread_or_404(db, client.id, thread_id)
    if t.closed:
        raise HTTPException(409, "This thread is closed. Reopen it to carry on.")
    data = file.file.read()
    small = thumb.file.read() if thumb is not None else None
    ctype = (file.content_type or "").lower()
    f = store_file(db, client.id, file, data, job_id=t.job_id, attached_type="thread", attached_id=t.id,
                   kind="photo" if ctype.startswith("image/") else "document",
                   taken_on=date.today().isoformat(), by=name, thumb=small)
    db.commit()
    return {"file": file_dict(f)}


@router.post("/api/chat/threads/{thread_id}/{action}")
def close_thread(thread_id: int, action: str, request: Request, db: Session = Depends(get_db)):
    client, me, name = chat_actor(request, db)
    if action not in ("close", "reopen"):
        raise HTTPException(404, "Not found")
    t = thread_or_404(db, client.id, thread_id)
    t.closed = action == "close"
    db.commit()
    return {"thread": thread_dict(db, t, me),
            "message": "\"%s\" %s." % (t.title, "closed" if t.closed else "reopened")}
