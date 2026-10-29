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


