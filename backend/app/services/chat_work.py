"""Project chat beyond the plain thread: who may see what, replies and reactions, tasks made from messages,
a notice for each person, and the dictionaries the screen is given."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.constants.common import CHAT_MAX_BODY
from app.core.audit import log_audit
from app.core.auth import get_employee_user, require_items_access
from app.core.notifications import notify
from app.services.collaboration import (
    _files_for, _last_read, _mark_read, chat_people, find_mentions, thread_or_404,
)
from app.services.hr import employee_site_ids

CATEGORIES = ("General", "Site Progress", "Materials", "Quality", "Safety", "Design", "Approvals")
PRIORITIES = ("Low", "Normal", "High", "Urgent")
TASK_STATUSES = ("Open", "In Progress", "Blocked", "Resolved", "Closed")
LINK_TYPES = {"progress": "Site progress", "delivery": "Material delivery", "quality": "Quality inspection",
              "safety": "Safety observation", "design": "Design clarification", "approval": "Approval request"}
EMOJI = ("👍", "👎", "✅", "❗", "❓", "🎉", "👀", "🙏")
MAX_MEMBERS = 50


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Scope:
    """Who is asking and which projects they may see. `jobs` is None for the office, who see every project."""

    def __init__(self, client, me, name, jobs, office):
        self.client, self.me, self.name, self.jobs, self.office = client, me, name, jobs, office

    def may(self, job_id):
        return self.jobs is None or job_id in self.jobs

    def need(self, job_id):
        if not self.may(job_id):
            raise HTTPException(403, "You are not on this project.")


def chat_scope(request, db):
    client = require_items_access(request, db, None)
    emp = None
    try:
        emp = get_employee_user(request, db)
    except HTTPException:
        pass
    if emp is not None:
        ids = employee_site_ids(db, emp)
        name = ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()
        return Scope(client, "employee:%d" % emp.id, name, None if ids is None else set(ids), False)
    member_id = request.session.get("member_id")
    if member_id:
        m = db.query(models.DBTeamMember).filter(models.DBTeamMember.id == member_id).first()
        if m:
            return Scope(client, "member:%d" % m.id, m.name or m.email or "Office", None, True)
    return Scope(client, "owner:%d" % client.id, client.contact_name or client.company_name or "Master", None, True)


def thread_for(db, sc, thread_id):
    t = thread_or_404(db, sc.client.id, thread_id)
    sc.need(t.job_id)
    return t


def keys(csv):
    return [x for x in (csv or "").split(",") if x]


def clean_members(db, client_id, raw, me=""):
    """Only people this company has - never a key typed in from outside."""
    have = {p["key"]: p for p in chat_people(db, client_id)}
    out = []
    for k in raw or []:
        if k in have and k not in out:
            out.append(k)
    if len(out) > MAX_MEMBERS:
        raise HTTPException(400, "A thread is for up to %d people." % MAX_MEMBERS)
    return out


def trail(db, sc, action, thread, details="", request=None):
    log_audit(db, sc.client.id, action, entity_type="chat_thread", entity_id=thread.id, entity_name=thread.title or "",
              details=(details or "")[:1000], request=request, user_name=sc.name)


def history(db, client_id, thread_id):
    rows = db.query(models.DBAuditLog).filter(
        models.DBAuditLog.client_id == client_id, models.DBAuditLog.entity_type == "chat_thread",
        models.DBAuditLog.entity_id == thread_id).order_by(models.DBAuditLog.id.desc()).limit(100).all()
    return [{"at": str(r.created_at or "")[:19], "who": r.user_name or "", "action": r.action or "", "details": r.details or ""} for r in rows]


# ---- notices ---------------------------------------------------------------------------------

def tell(db, client_id, recipients, me, kind, title, body="", thread_id=None, task_id=None, dedupe=""):
    """A line for each person other than whoever caused it. Added to the session; the caller commits."""
    for r in dict.fromkeys(recipients):
        if not r or r == me:
            continue
        if dedupe and db.query(models.DBChatNotice.id).filter(models.DBChatNotice.recipient == r,
                                                             models.DBChatNotice.dedupe == dedupe).first():
            continue
        db.add(models.DBChatNotice(client_id=client_id, recipient=r, kind=kind, title=title[:200], body=(body or "")[:500],
                                   thread_id=thread_id, task_id=task_id, dedupe=dedupe, created_at=now()))


def participants(db, t):
    authors = [a for (a,) in db.query(models.DBProjectMessage.author).filter(
        models.DBProjectMessage.thread_id == t.id).distinct().all()]
    return list(dict.fromkeys(keys(t.members) + [t.started_by] + authors))


def due_notices(db, sc):
    """A reminder, once a day, for each task of mine that is due tomorrow or already late."""
    today = date.today()
    soon = (today + timedelta(days=1)).isoformat()
    mine = db.query(models.DBChatTask).filter(
        models.DBChatTask.client_id == sc.client.id, models.DBChatTask.assignee == sc.me,
        models.DBChatTask.status.notin_(("Resolved", "Closed")), models.DBChatTask.due_date != "",
        models.DBChatTask.due_date <= soon).all()
    for t in mine:
        late = t.due_date < today.isoformat()
        tell(db, sc.client.id, [sc.me], "", "due", ("Overdue: " if late else "Due soon: ") + t.title,
             "Due %s" % t.due_date, t.thread_id, t.id, dedupe="due:%d:%s" % (t.id, today.isoformat()))
    if mine:
        db.commit()


def notice_dict(n):
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body or "", "thread_id": n.thread_id,
            "task_id": n.task_id, "read": bool(n.is_read), "created_at": n.created_at or ""}


def unread_notices(db, sc):
    return db.query(models.DBChatNotice).filter(models.DBChatNotice.client_id == sc.client.id,
                                                models.DBChatNotice.recipient == sc.me,
                                                models.DBChatNotice.is_read.is_(False)).count()


# ---- dictionaries ----------------------------------------------------------------------------

def names_of(db, client_id):
    return {p["key"]: p["name"] for p in chat_people(db, client_id)}


def thread_out(db, t, sc, jobs=None, names=None):
    msgs = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.thread_id == t.id)
    live = msgs.filter(models.DBProjectMessage.deleted.is_(False))
    last = msgs.order_by(models.DBProjectMessage.id.desc()).first()
    seen = _last_read(db, t.id, sc.me)
    unread = live.filter(models.DBProjectMessage.id > seen, models.DBProjectMessage.author != sc.me).count()
    job = (jobs or {}).get(t.job_id) or db.query(models.DBJob).filter(models.DBJob.id == t.job_id).first()
    names = names or names_of(db, sc.client.id)
    open_tasks = db.query(models.DBChatTask).filter(models.DBChatTask.thread_id == t.id,
                                                    models.DBChatTask.status.notin_(("Resolved", "Closed"))).count()
    return {"id": t.id, "job_id": t.job_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "title": t.title or "", "description": t.description or "", "category": t.category or "General",
            "priority": t.priority or "Normal", "started_by": t.started_by, "started_by_name": t.started_by_name or "",
            "closed": bool(t.closed), "messages": live.count(), "unread": unread, "open_tasks": open_tasks,
            "members": [{"key": k, "name": names.get(k, "Former member")} for k in keys(t.members)],
            "link": {"type": t.link_type, "label": LINK_TYPES.get(t.link_type, ""), "ref": t.link_ref or "", "id": t.link_id} if t.link_type else None,
            "last": ({"author_name": last.author_name, "body": ("" if last.deleted else (last.body or ""))[:120] or ("a photo" if last.file_ids else ""), "at": last.created_at} if last else None),
            "last_message_at": t.last_message_at or t.created_at or "", "created_at": t.created_at or "",
            "can_edit": sc.office or t.started_by == sc.me}


def messages_out(db, msgs, sc):
    if not msgs:
        return []
    by_id = {m.id: m for m in msgs}
    parent_ids = {m.parent_id for m in msgs if m.parent_id and m.parent_id not in by_id}
    if parent_ids:
        for p in db.query(models.DBProjectMessage).filter(models.DBProjectMessage.id.in_(parent_ids)).all():
            by_id[p.id] = p
    reacts = {}
    for r in db.query(models.DBChatReaction).filter(models.DBChatReaction.message_id.in_([m.id for m in msgs])).all():
        reacts.setdefault(r.message_id, {}).setdefault(r.emoji, []).append(r.reader)
    names = names_of(db, sc.client.id)
    out = []
    for m in msgs:
        ids = [int(x) for x in (m.file_ids or "").split(",") if x.strip().isdigit()]
        p = by_id.get(m.parent_id) if m.parent_id else None
        out.append({
            "id": m.id, "thread_id": m.thread_id, "author": m.author, "author_name": m.author_name or "",
            "mine": m.author == sc.me, "body": "" if m.deleted else (m.body or ""), "deleted": bool(m.deleted),
            "files": [] if m.deleted else _files_for(db, m.client_id, ids), "mentions": keys(m.mentions),
            "mention_names": [names.get(k, "") for k in keys(m.mentions)],
            "parent": ({"id": p.id, "author_name": p.author_name or "", "body": "" if p.deleted else (p.body or "")[:100], "deleted": bool(p.deleted)} if p else None),
            "reactions": [{"emoji": e, "count": len(who), "mine": sc.me in who, "who": [names.get(w, "") for w in who][:8]} for e, who in reacts.get(m.id, {}).items()],
            "edited": bool(m.edited_at), "created_at": m.created_at or ""})
    return out


def task_out(t, names=None, sc=None):
    today = date.today().isoformat()
    return {"id": t.id, "job_id": t.job_id, "thread_id": t.thread_id, "message_id": t.message_id, "title": t.title or "",
            "description": t.description or "", "assignee": t.assignee or "", "assignee_name": t.assignee_name or "",
            "due_date": t.due_date or "", "priority": t.priority or "Normal", "status": t.status or "Open",
            "created_by_name": t.created_by_name or "", "created_at": t.created_at or "", "updated_at": t.updated_at or "",
            "overdue": bool(t.due_date) and t.due_date < today and (t.status or "Open") not in ("Resolved", "Closed"),
            "mine": bool(sc) and t.assignee == sc.me}


def thread_files(db, t):
    rows = db.query(models.DBFile).filter(models.DBFile.client_id == t.client_id, models.DBFile.attached_type == "thread",
                                          models.DBFile.attached_id == t.id).order_by(models.DBFile.id.desc()).all()
    return [{"id": f.id, "name": f.name or "", "size": f.size or 0, "caption": f.caption or "",
             "is_image": (f.content_type or "").startswith("image/"), "is_pdf": (f.content_type or "") == "application/pdf",
             "url": "/api/files/%d" % f.id, "thumb_url": "/api/files/%d/thumb" % f.id,
             "by": f.uploaded_by_name or "", "on": (f.created_at or "")[:10]} for f in rows]


def link_target(db, client_id, link_type, ref):
    """A quality reference that names a real record is linked to it; anything else is kept as written."""
    ref = (ref or "").strip()[:80]
    if link_type and link_type not in LINK_TYPES:
        raise HTTPException(400, "Link to site progress, a material delivery, a quality inspection, a safety observation, a design clarification or an approval.")
    rid = None
    if link_type == "quality" and ref:
        for stem, model in (("INS-", models.DBInspection), ("NCR-", models.DBNcr), ("CT-", models.DBCubeSet)):
            if ref.upper().startswith(stem):
                row = db.query(model).filter(model.client_id == client_id, model.number == ref.upper()).first()
                if not row:
                    raise HTTPException(400, "%s is not a record in this company." % ref)
                rid = row.id
                ref = ref.upper()
    return ref, rid


def post_message(db, sc, t, body, file_ids, parent_id=None, request=None):
    body = (body or "").strip()
    if len(body) > CHAT_MAX_BODY:
        raise HTTPException(400, "That is a long message - keep it under %d characters, or attach it." % CHAT_MAX_BODY)
    ids = []
    for fid in (file_ids or [])[:10]:
        f = db.query(models.DBFile).filter(models.DBFile.id == int(fid), models.DBFile.client_id == sc.client.id).first()
        if not f or f.attached_type != "thread" or f.attached_id != t.id:
            raise HTTPException(400, "That file was not uploaded to this thread.")
        ids.append(f.id)
    if not body and not ids:
        raise HTTPException(400, "Write something, or attach a photo or document.")
    if t.closed:
        raise HTTPException(409, "This thread is closed. Reopen it to carry on.")
    parent = None
    if parent_id:
        parent = db.query(models.DBProjectMessage).filter(models.DBProjectMessage.id == parent_id,
                                                          models.DBProjectMessage.thread_id == t.id).first()
        if not parent:
            raise HTTPException(400, "The message you are replying to is not in this thread.")
    people = chat_people(db, sc.client.id)
    mentioned = [p for p in find_mentions(body, people) if p["key"] != sc.me]
    m = models.DBProjectMessage(client_id=sc.client.id, thread_id=t.id, author=sc.me, author_name=sc.name, body=body,
                                file_ids=",".join(str(i) for i in ids), mentions=",".join(p["key"] for p in mentioned),
                                parent_id=parent.id if parent else None, created_at=now())
    db.add(m)
    db.flush()
    t.last_message_at = m.created_at
    _mark_read(db, t.id, sc.me, m.id)
    who = {p["key"] for p in mentioned}
    snippet = body[:160] or "sent a file"
    if mentioned:
        job = db.query(models.DBJob).filter(models.DBJob.id == t.job_id).first()
        notify(db, sc.client.id, "chat_mention", "%s mentioned %s" % (sc.name, ", ".join(p["name"] for p in mentioned)),
               "In \"%s\" on %s: %s" % (t.title, job.name if job else "the project", body[:160]),
               view="chat-view", ref_type="thread", ref_id=t.id, severity="action")
    tell(db, sc.client.id, [p["key"] for p in mentioned], sc.me, "mention", "%s mentioned you in %s" % (sc.name, t.title), snippet, t.id)
    if parent and parent.author not in who:
        tell(db, sc.client.id, [parent.author], sc.me, "reply", "%s replied to you in %s" % (sc.name, t.title), snippet, t.id)
        who.add(parent.author)
    tell(db, sc.client.id, [r for r in participants(db, t) if r not in who], sc.me, "message", "%s in %s" % (sc.name, t.title), snippet, t.id)
    return m


def need_office_or_own(sc, owner_key, what):
    if not (sc.office or owner_key == sc.me):
        raise HTTPException(403, "Only whoever started it, or the office, can change %s." % what)
