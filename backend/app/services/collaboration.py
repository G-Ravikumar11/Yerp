"""The rules and workings behind the collaboration endpoints."""
import re
from collections import defaultdict
from datetime import datetime

from fastapi import HTTPException, WebSocket

from app import models

from app.constants.common import CHAT_MAX_BODY
from app.core.auth import get_employee_user, require_items_access
from app.core.notifications import notify


# VIDEO MEETINGS - WebRTC Signaling Server
meeting_rooms = defaultdict(lambda: {
    "participants": {},
    "host": None,
    "waiting": {},
    "locked": False,
    "created_at": datetime.utcnow().isoformat()
})


class MeetingSignaling:
    def __init__(self):
        self.connections = defaultdict(list)

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str):
        await websocket.accept()
        self.connections[room_id].append({
            "ws": websocket,
            "user_id": user_id
        })

    def disconnect(self, room_id: str, user_id: str):
        self.connections[room_id] = [
            c for c in self.connections[room_id] if c["user_id"] != user_id
        ]
        if room_id in meeting_rooms:
            meeting_rooms[room_id]["participants"].pop(user_id, None)
            meeting_rooms[room_id]["waiting"].pop(user_id, None)
            if not meeting_rooms[room_id]["participants"]:
                del meeting_rooms[room_id]
            elif meeting_rooms[room_id]["host"] == user_id:
                # Reassign host to the next participant if possible
                new_host = next(iter(meeting_rooms[room_id]["participants"].keys()), None)
                meeting_rooms[room_id]["host"] = new_host
                
        if not self.connections[room_id]:
            if room_id in self.connections:
                del self.connections[room_id]

    async def broadcast(self, room_id: str, message: dict, exclude_user: str = None):
        dead = []
        for conn in self.connections.get(room_id, []):
            if conn["user_id"] == exclude_user:
                continue
            try:
                await conn["ws"].send_json(message)
            except Exception:
                dead.append(conn)
        for d in dead:
            if d in self.connections.get(room_id, []):
                self.connections[room_id].remove(d)

    async def send_to(self, room_id: str, user_id: str, message: dict):
        for conn in self.connections.get(room_id, []):
            if conn["user_id"] == user_id:
                try:
                    await conn["ws"].send_json(message)
                except Exception:
                    pass
                return

    def get_participants(self, room_id: str):
        return list(meeting_rooms.get(room_id, {}).get("participants", {}).keys())


signaling = MeetingSignaling()


def chat_actor(request, db):
    """(tenant, who as "kind:id", display name) for whoever is signed in."""
    client = require_items_access(request, db, None)
    try:
        emp = get_employee_user(request, db)
        return client, "employee:%d" % emp.id, ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()
    except HTTPException:
        pass
    member_id = request.session.get("member_id")
    if member_id:
        m = db.query(models.DBTeamMember).filter(models.DBTeamMember.id == member_id).first()
        if m:
            return client, "member:%d" % m.id, (m.name or m.email or "Office")
    return client, "owner:%d" % client.id, (client.contact_name or client.company_name or "Master")


def chat_people(db, client_id):
    """Everybody who can be named in a thread."""
    c = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    out = [{"key": "owner:%d" % c.id, "name": c.contact_name or c.company_name or "Master", "role": "Master"}] if c else []
    out += [{"key": "member:%d" % m.id, "name": m.name or m.email, "role": "Office"}
            for m in db.query(models.DBTeamMember).filter(models.DBTeamMember.client_id == client_id,
                                                          models.DBTeamMember.is_active.is_(True)).all()]
    out += [{"key": "employee:%d" % e.id, "name": ("%s %s" % (e.first_name or "", e.last_name or "")).strip(),
             "role": e.job_title or "Staff"}
            for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id,
                                                        models.DBEmployee.status != "terminated").all()]
    return out


def find_mentions(body, people):
    """Who an "@Name" in the message means - the longest name that fits, so
    "@Ravi Kumar" is not taken for a "Ravi" who is somebody else."""
    text = (body or "").lower()
    hits = []
    for p in sorted(people, key=lambda p: -len(p["name"] or "")):
        name = (p["name"] or "").strip().lower()
        if name and re.search(r"@" + re.escape(name) + r"(?![\w])", text):
            hits.append(p)
            text = re.sub(r"@" + re.escape(name) + r"(?![\w])", " ", text)
    return hits


def thread_or_404(db, client_id, thread_id):
    t = db.query(models.DBProjectThread).filter(models.DBProjectThread.id == thread_id,
                                                models.DBProjectThread.client_id == client_id).first()
    if not t:
        raise HTTPException(404, "Thread not found")
    return t


def _files_for(db, client_id, ids):
    if not ids:
        return []
    rows = db.query(models.DBFile.id, models.DBFile.name, models.DBFile.content_type,
                    models.DBFile.size, models.DBFile.attached_type, models.DBFile.attached_id).filter(
        models.DBFile.client_id == client_id, models.DBFile.id.in_(ids)).all()
    return [{"id": r.id, "name": r.name or "", "size": r.size or 0,
             "is_image": (r.content_type or "").startswith("image/"),
             "url": "/api/files/%d" % r.id, "thumb_url": "/api/files/%d/thumb" % r.id} for r in rows]


def message_dict(db, m, me=""):
    ids = [int(x) for x in (m.file_ids or "").split(",") if x.strip().isdigit()]
    return {"id": m.id, "thread_id": m.thread_id, "author": m.author, "author_name": m.author_name or "",
            "mine": m.author == me, "body": "" if m.deleted else (m.body or ""), "deleted": bool(m.deleted),
            "files": [] if m.deleted else _files_for(db, m.client_id, ids),
            "mentions": [x for x in (m.mentions or "").split(",") if x],
            "created_at": m.created_at or ""}


def _last_read(db, thread_id, me):
    r = db.query(models.DBThreadRead).filter(models.DBThreadRead.thread_id == thread_id,
                                             models.DBThreadRead.reader == me).first()
    return r.last_read_id if r else 0


def _mark_read(db, thread_id, me, upto):
    r = db.query(models.DBThreadRead).filter(models.DBThreadRead.thread_id == thread_id,
                                             models.DBThreadRead.reader == me).first()
    if not r:
        db.add(models.DBThreadRead(thread_id=thread_id, reader=me, last_read_id=upto))
    elif upto > (r.last_read_id or 0):
        r.last_read_id = upto


def thread_dict(db, t, me, jobs=None):
    msgs = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.thread_id == t.id)
    last = msgs.order_by(models.DBProjectMessage.id.desc()).first()
    seen = _last_read(db, t.id, me)
    unread = msgs.filter(models.DBProjectMessage.id > seen, models.DBProjectMessage.author != me,
                         models.DBProjectMessage.deleted.is_(False)).count()
    job = (jobs or {}).get(t.job_id) or db.query(models.DBJob).filter(models.DBJob.id == t.job_id).first()
    return {"id": t.id, "job_id": t.job_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "title": t.title or "", "started_by_name": t.started_by_name or "", "closed": bool(t.closed),
            "messages": msgs.filter(models.DBProjectMessage.deleted.is_(False)).count(), "unread": unread,
            "last": ({"author_name": last.author_name, "body": ("" if last.deleted else (last.body or ""))[:120]
                      or ("a photo" if last.file_ids else ""), "at": last.created_at} if last else None),
            "last_message_at": t.last_message_at or t.created_at or "", "created_at": t.created_at or ""}


def _post_message(db, client, t, me, name, body, file_ids, request):
    body = (body or "").strip()
    if len(body) > CHAT_MAX_BODY:
        raise HTTPException(400, "That is a long message - keep it under %d characters, or attach it." % CHAT_MAX_BODY)
    ids = []
    for fid in (file_ids or [])[:10]:
        f = db.query(models.DBFile).filter(models.DBFile.id == int(fid), models.DBFile.client_id == client.id).first()
        # Only a file put up in this thread goes in its messages - never one
        # pulled across from another record by its number.
        if not f or f.attached_type != "thread" or f.attached_id != t.id:
            raise HTTPException(400, "That photo was not uploaded to this thread.")
        ids.append(f.id)
    if not body and not ids:
        raise HTTPException(400, "Write something, or attach a photo.")
    if t.closed:
        raise HTTPException(409, "This thread is closed. Reopen it to carry on.")
    mentioned = find_mentions(body, chat_people(db, client.id))
    m = models.DBProjectMessage(client_id=client.id, thread_id=t.id, author=me, author_name=name, body=body,
                                file_ids=",".join(str(i) for i in ids),
                                mentions=",".join(p["key"] for p in mentioned if p["key"] != me))
    db.add(m)
    db.flush()
    t.last_message_at = m.created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _mark_read(db, t.id, me, m.id)
    db.commit()
    names = [p["name"] for p in mentioned if p["key"] != me]
    if names:
        job = db.query(models.DBJob).filter(models.DBJob.id == t.job_id).first()
        notify(db, client.id, "chat_mention", "%s mentioned %s" % (name, ", ".join(names)),
               "In \"%s\" on %s: %s" % (t.title, job.name if job else "the project", body[:160]),
               view="chat-view", ref_type="thread", ref_id=t.id, severity="action")
    return m
