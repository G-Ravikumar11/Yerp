"""Site stories: the site diary's photos, shown in the phone app the way stories are, site by site.

The rule that makes them different from anybody else's stories: a story does not go by itself. It stays in the row until
the Master, an account admin or a member of staff at the Master's access level has opened it, and leaves the row 24 hours
after that first opening. Until then nobody but one of those people can remove the photo, or the draft day it is on.

Only the row is what changes. The photo is the diary's: it stays on its day, on the record, whatever happens here.

Photos from before a company first used stories are not all brought up as stories at once: the row starts a week before
the first time anybody at the company opened it (the `stories_since` setting), and everything after that is a story.
"""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import models
from app.core import app_limits
from app.core.auth import current_member, session_person
from app.core.tenant_settings import put_setting, tenant_setting

STORY_HOURS = 24
BACK_DAYS = 7                 # how far back the row reaches the first time a company opens it
SINCE_KEY = "stories_since"
MOST = 400                    # the newest this many photos; a row with more than that is not being opened by anybody
STAMP = "%Y-%m-%d %H:%M:%S"


def _now():
    return datetime.now()


class Viewer:
    """Who is looking: the company, the member of staff (None for the company's own sign-in), and whether theirs is an
    opening that starts a story's 24 hours."""

    def __init__(self, request, db):
        from app.services.hr import employee_name
        self.client, self.emp = session_person(request, db)
        member = current_member(request, db) if self.emp is None else None
        if self.emp is not None:
            self.key, self.name = "employee:%d" % self.emp.id, employee_name(self.emp)
            self.admin = app_limits.free_staff(self.emp.permission_role)
        elif member is not None:
            self.key, self.name = "member:%d" % member.id, (member.name or member.email or "")
            self.admin = member.role in ("owner", "admin")
        else:
            self.key, self.name = "owner", (self.client.contact_name or "").strip() or "Master"
            self.admin = True


def started(db, client_id):
    """When this company's stories begin, or '' if nobody there has opened the row yet."""
    return tenant_setting(db, client_id, SINCE_KEY, "")


def start(db, client_id):
    """When this company's stories begin, set on the first asking. The caller commits."""
    since = started(db, client_id)
    if not since:
        since = (_now() - timedelta(days=BACK_DAYS)).strftime(STAMP)
        put_setting(db, client_id, SINCE_KEY, since)
    return since


def _openings(db, client_id, file_ids):
    """{file id: [(viewer, name, by_admin, when)]} for these photos."""
    out = {}
    ids = list(file_ids)
    for i in range(0, len(ids), 500):
        for v in db.query(models.DBStoryView).filter(models.DBStoryView.client_id == client_id,
                                                     models.DBStoryView.file_id.in_(ids[i:i + 500])).all():
            out.setdefault(v.file_id, []).append((v.viewer, v.viewer_name or "", bool(v.by_admin), v.viewed_at or ""))
    return out


def _first_admin(openings):
    """(when, name) of the first opening by the Master or an admin, or ('', '')."""
    by_admin = sorted((when, name) for _viewer, name, admin, when in openings if admin and when)
    return by_admin[0] if by_admin else ("", "")


def _seconds_left(opened_at, now):
    try:
        gone = datetime.strptime(opened_at, STAMP) + timedelta(hours=STORY_HOURS)
    except ValueError:
        return 0
    return int((gone - now).total_seconds())


def _photos(db, client_id, since, job_ids=None):
    """The diary photos that can be stories: (file, diary) rows, oldest first, without the pictures' bytes."""
    F, D = models.DBFile, models.DBSiteDiary
    q = db.query(F.id, F.name, F.caption, F.taken_on, F.uploaded_by_name, F.created_at,
                 D.id.label("diary_id"), D.job_id, D.diary_date, D.work_done).join(
        D, (D.id == F.attached_id) & (D.client_id == F.client_id)).filter(
        F.client_id == client_id, F.attached_type == "diary", F.content_type.like("image/%"), F.created_at >= since)
    if job_ids is not None:
        q = q.filter(D.job_id.in_(job_ids or [-1]))
    return list(reversed(q.order_by(F.id.desc()).limit(MOST).all()))


def row(db, viewer):
    """The stories row for this person: sites that have a story, each with its photos oldest first. The caller commits
    (the first asking sets when the company's stories begin)."""
    from app.services.employee_portal import accessible_job_ids_for
    client = viewer.client
    since = start(db, client.id)
    allowed = accessible_job_ids_for(db, viewer.emp) if viewer.emp is not None else None
    photos = _photos(db, client.id, since, allowed)
    openings = _openings(db, client.id, [p.id for p in photos])
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id, models.DBJob.id.in_({p.job_id for p in photos} or {-1})).all()}
    now = _now()
    sites = {}
    for p in photos:
        seen_by = openings.get(p.id, [])
        opened_at, opened_by = _first_admin(seen_by)
        left = _seconds_left(opened_at, now) if opened_at else None
        if left is not None and left <= 0:
            continue                                   # opened by the Master or an admin more than 24 hours ago: gone from the row
        job = jobs.get(p.job_id)
        if job is None:
            continue
        site = sites.setdefault(job.id, {"job_id": job.id, "number": job.number or "", "name": job.name or "", "stories": []})
        site["stories"].append({
            "id": p.id, "url": "/api/files/%d" % p.id, "thumb_url": "/api/files/%d/thumb" % p.id,
            "diary_id": p.diary_id, "diary_date": p.diary_date or "", "caption": p.caption or "",
            "work_done": (p.work_done or "")[:240], "by": p.uploaded_by_name or "", "at": p.created_at or "",
            "seen": any(v == viewer.key for v, _n, _a, _w in seen_by),
            "opened_at": opened_at, "opened_by": opened_by, "leaves_in_s": left,
        })
    out = list(sites.values())
    for s in out:
        s["unseen"] = len([x for x in s["stories"] if not x["seen"]])
        s["unopened"] = len([x for x in s["stories"] if not x["opened_at"]])
        s["latest"] = s["stories"][-1]["at"]
    # Sites with something this person has not looked at come first, the newest first within each.
    out.sort(key=lambda s: s["latest"], reverse=True)
    out.sort(key=lambda s: s["unseen"] == 0)
    return {"sites": out, "admin": viewer.admin, "hours": STORY_HOURS,
            "unseen": sum(s["unseen"] for s in out)}


def seen(db, viewer, file_id):
    """This person has opened this story. The first opening by the Master or an admin starts its 24 hours. The caller commits."""
    from app.services.employee_portal import employee_can_access_job
    client = viewer.client
    F, D = models.DBFile, models.DBSiteDiary
    hit = db.query(F.id, D.job_id).join(D, (D.id == F.attached_id) & (D.client_id == F.client_id)).filter(
        F.id == file_id, F.client_id == client.id, F.attached_type == "diary", F.content_type.like("image/%")).first()
    if hit is None or (viewer.emp is not None and not employee_can_access_job(db, viewer.emp, hit.job_id)):
        raise HTTPException(404, "Story not found")
    mine = db.query(models.DBStoryView).filter(models.DBStoryView.file_id == file_id,
                                               models.DBStoryView.viewer == viewer.key).first()
    if mine is None:
        try:
            with db.begin_nested():
                db.add(models.DBStoryView(client_id=client.id, file_id=file_id, viewer=viewer.key, viewer_name=viewer.name[:120],
                                          by_admin=viewer.admin, viewed_at=_now().strftime(STAMP)))
        except IntegrityError:
            pass                                       # the same opening, sent twice at once: the first stands
    opened_at, opened_by = _first_admin(_openings(db, client.id, [file_id]).get(file_id, []))
    return {"ok": True, "id": file_id, "opened_at": opened_at, "opened_by": opened_by,
            "leaves_in_s": max(0, _seconds_left(opened_at, _now())) if opened_at else None}


def waiting(db, client_id, file_ids):
    """Which of these photos are stories the Master or an admin has not opened yet."""
    since = started(db, client_id)
    ids = [i for i in file_ids if i]
    if not since or not ids:
        return set()                                   # the company has never used stories: nothing is held
    F = models.DBFile
    live = {i for (i,) in db.query(F.id).filter(F.client_id == client_id, F.id.in_(ids), F.attached_type == "diary",
                                                 F.content_type.like("image/%"), F.created_at >= since).all()}
    opened = {fid for fid, seen_by in _openings(db, client_id, live).items() if _first_admin(seen_by)[0]}
    return live - opened


def keep_until_opened(request, db, client_id, file_ids, what="That photo"):
    """Refuse to remove a story the Master or an admin has not opened yet, unless it is one of them removing it."""
    held = waiting(db, client_id, file_ids)
    if held and not Viewer(request, db).admin:
        if len(held) == 1:
            raise HTTPException(409, "%s is a site story the Master has not opened yet. It stays until it has been seen." % what)
        raise HTTPException(409, "%s has %d site stories the Master has not opened yet. They stay until they have been seen."
                                 % (what, len(held)))
