"""The website's content in the database: one row per section, with a draft and a published version, and every publishing
kept as a numbered version that can be put back.

The first content is the text the site was built with, app/constants/website_content.json - the same as
frontend/src/features/site/data/content.ts, which the site still carries for the moment before this arrives (a test
keeps the two equal). Each company gets a row for every section it has not got yet, so a section added later is seeded
too, and nothing already there is ever overwritten.

Besides the words and pictures there is one section the site does not read as it is: `projects`, the card each project
shows on the website ({job id: {show, sector, location, scope, photos}}). Publishing writes it onto the projects
themselves, which is what /api/public/site reads, so a project too changes on the website only when it is published.
"""
import json
import os
import re
from datetime import datetime
from functools import lru_cache

from fastapi import HTTPException

from app import models

SEED_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "constants", "website_content.json")

# The sections, with the name the Website tab uses. (Look B, 25 Nov 2026: the slideshow and the opening line went into the
# opening's one framed photograph and its title block; the site list became the projects register.)
SECTIONS = (
    ("layout", "Page layout"),
    ("hero", "Opening"),
    ("clients", "Building for"),
    ("headings", "Section headings"),
    ("about", "About us"),
    ("capabilities", "What we build"),
    ("steps", "How we build"),
    ("sites", "Projects register"),
    ("sitePhotos", "Drawing sheets (photographs from site)"),
    ("projects", "Projects on the website"),
    ("timeline", "Our story"),
    ("safety", "Quality & safety"),
    ("credentials", "Credentials"),
    ("options", "Live figures"),
    ("enquiry", "Start a project"),
    ("plan", "Enquiry form choices"),
    ("company", "Contact details"),
    ("footer", "Footer"),
    ("seo", "Search & sharing"),
)
SECTION_KEYS = tuple(k for k, _ in SECTIONS)
# Kept here, not shown on the site as they are.
PRIVATE_KEYS = ("projects",)
# Where the first content of a section not in website_content.json comes from.
EXTRA_SEED = {"projects": {}}

PAGE_SECTIONS = ("hero", "about", "projects", "build", "process", "quality", "quote", "careers", "story")
# The first content, before Look B: a section still exactly as it was is given Look B's; one that was changed is upgraded.
V1_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "constants", "website_content_v1.json")
# The page's sections before Look B, and where each went.
V1_PAGE = {"proof": "hero", "credentials": "quality", "safety": "quality", "contact": "quote"}
IMAGE_PATH = "/api/public/site/images/"
MAX_TEXT, MAX_SECTION_BYTES, MAX_PROJECT_PHOTOS = 3000, 200_000, 6
# Keys whose value is a picture, and keys whose value is a link a visitor follows.
IMAGE_KEYS = {"img", "image"}
LINK_KEYS = {"url", "href", "linkedin", "facebook", "instagram", "youtube"}


@lru_cache(maxsize=1)
def _seed_text():
    with open(SEED_FILE, encoding="utf8") as f:
        seed = json.load(f)
    seed.update(EXTRA_SEED)
    missing = set(SECTION_KEYS) - set(seed)
    assert not missing, "website_content.json has no %s" % ", ".join(sorted(missing))
    return {k: json.dumps(seed[k], ensure_ascii=False) for k in SECTION_KEYS}


def seed():
    """The first content of every section, as a fresh copy."""
    return {k: json.loads(v) for k, v in _seed_text().items()}


@lru_cache(maxsize=1)
def _v1_text():
    try:
        with open(V1_FILE, encoding="utf8") as f:
            return {k: json.dumps(v, ensure_ascii=False, sort_keys=True) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        return {}


def _same(a, b):
    return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def _fill(value, shape):
    """`value` with whatever `shape` has that it lacks: a field added since it was saved gets its first content. What is
    there stays as it is. A list's entries are each filled from the list's first entry, with its fields blanked."""
    if isinstance(shape, dict) and isinstance(value, dict):
        out = dict(value)
        for k, v in shape.items():
            out[k] = _fill(out[k], v) if k in out else v
        return out
    if isinstance(shape, list) and isinstance(value, list) and shape and isinstance(shape[0], dict):
        blank = {k: (False if isinstance(v, bool) else [] if isinstance(v, list) else {} if isinstance(v, dict)
                     else None if v is None or isinstance(v, (int, float)) else "") for k, v in shape[0].items()}
        return [_fill(x, blank) if isinstance(x, dict) else x for x in value]
    return value


def upgrade(key, value):
    """A section as saved before Look B, in Look B's shape. A section still exactly as first seeded takes Look B's content;
    one the company changed keeps what it said, moved into the new fields."""
    first = seed()[key] if key in SECTION_KEYS else None
    if value is None or first is None:
        return first
    old = _v1_text().get(key)
    if old is not None and json.dumps(value, ensure_ascii=False, sort_keys=True) == old:
        return first
    if key == "layout" and isinstance(value, list):
        order, shown = [], {}
        for row in value:
            if not isinstance(row, dict):
                continue
            sid = V1_PAGE.get(row.get("id"), row.get("id"))
            if sid in PAGE_SECTIONS:
                if sid not in order:
                    order.append(sid)
                shown[sid] = shown.get(sid, False) or bool(row.get("shown"))
        order += [s for s in PAGE_SECTIONS if s not in order]
        return [{"id": s, "shown": shown.get(s, True)} for s in order]
    if key == "hero" and isinstance(value, dict) and "kicker" not in value:
        return _fill({"title": value.get("title") or first["title"], "accent": "", "sub": value.get("sub") or first["sub"]}, first)
    if key == "sites" and isinstance(value, list) and any(isinstance(g, dict) and "names" in g for g in value):
        rows = []
        for g in value:
            if not isinstance(g, dict):
                continue
            where = (g.get("where") or "").lower()
            state = "AP" if "andhra" in where else "TS" if "telangana" in where else ""
            for name in g.get("names") or []:
                rows.append({"site": name, "client": "APTIDCO housing" if "aptidco" in (g.get("group") or "").lower() else "",
                             "town": name if state == "AP" else (g.get("group") or ""), "state": state, "work": "", "status": "Ongoing"})
        return rows
    if key == "sitePhotos" and isinstance(value, list):
        value = [{"img": p.get("img", ""), "site": p.get("site", ""), "ref": "", "block": "", "stage": "", "shown": p.get("text", "")}
                 if isinstance(p, dict) and "text" in p else p for p in value]
    if key == "safety" and isinstance(value, list):
        codes = [x.get("code", "") for x in first]
        value = [dict({"code": codes[i] if i < len(codes) else ""}, **p) if isinstance(p, dict) and "code" not in p else p
                 for i, p in enumerate(value)]
    if key == "capabilities" and isinstance(value, list):
        value = [dict(p, line=p.get("id") == "civil") if isinstance(p, dict) and "line" not in p else p for p in value]
    if key == "credentials" and isinstance(value, list):
        # The safety record has its own box now, counted live.
        value = [c for c in value if not (isinstance(c, dict) and c.get("label") == "Safety record")]
    if key == "headings" and isinstance(value, dict):
        value = dict(value)
        if "quality" not in value and isinstance(value.get("safety"), dict):
            value["quality"] = value["safety"]
        value = {k: v for k, v in value.items() if k in first}
    return _fill(value, first)


def _upgraded(key, text):
    """The section's stored text in Look B's shape - or the first content, if it will not go into it."""
    value = upgrade(key, _load(text, None))
    try:
        check(None, None, key, value, deep=False)
    except HTTPException:
        value = seed()[key]
    return json.dumps(value, ensure_ascii=False)


def ensure_sections(db, client_id):
    """Give the company a row for each section it lacks, draft and published both the first content, and put any saved before
    Look B into its shape. True if anything changed."""
    S = models.DBWebsiteSection
    rows = db.query(S).filter(S.client_id == client_id).all()
    have = {r.key for r in rows}
    text = _seed_text()
    added = [S(client_id=client_id, key=k, draft=text[k], published=text[k], updated_by="First content",
               published_by="First content") for k in SECTION_KEYS if k not in have]
    db.add_all(added)
    moved = False
    for r in rows:
        if r.key not in SECTION_KEYS or r.key == "projects":
            continue
        for which in ("draft", "published"):
            now = getattr(r, which)
            new = _upgraded(r.key, now)
            if not _same(_load(now, None), json.loads(new)):
                setattr(r, which, new)
                moved = True
    if added or moved:
        db.flush()
    return bool(added) or moved


def seed_all(db):
    """At start-up: every company that has been set up gets its sections."""
    added = False
    for (cid,) in db.query(models.DBClient.id).filter(models.DBClient.is_onboarded.is_(True)).all():
        added = ensure_sections(db, cid) or added
    if added:
        db.commit()


def _rows(db, client_id):
    S = models.DBWebsiteSection
    return {r.key: r for r in db.query(S).filter(S.client_id == client_id, S.key.in_(SECTION_KEYS)).all()}


def _load(text, fallback):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


def _version(db, client_id, which):
    """Every section's `which` version ("draft" or "published"), the first content where a company has no row yet."""
    out = seed()
    for key, row in _rows(db, client_id).items():
        # Read in Look B's shape, should a row saved before it not have been put into it yet.
        out[key] = _load(getattr(row, which), out[key]) if key == "projects" else json.loads(_upgraded(key, getattr(row, which)))
    return out


def published(db, client_id):
    """What visitors see, section by section."""
    out = _version(db, client_id, "published")
    return {k: v for k, v in out.items() if k not in PRIVATE_KEYS}


def draft(db, client_id):
    """The draft of every section, as the preview shows it."""
    out = _version(db, client_id, "draft")
    return {k: v for k, v in out.items() if k not in PRIVATE_KEYS}


def published_projects(db, client_id):
    return _version(db, client_id, "published").get("projects") or {}


def draft_projects(db, client_id):
    return _version(db, client_id, "draft").get("projects") or {}


def sections(db, client_id):
    """Every section for the Website tab: its name, both versions, and whether the draft has changes not yet published."""
    rows = _rows(db, client_id)
    first = seed()
    out = []
    for key, label in SECTIONS:
        r = rows.get(key)
        d = _load(r.draft, first[key]) if r else first[key]
        p = _load(r.published, first[key]) if r else first[key]
        out.append({
            "key": key, "label": label, "draft": d, "published": p, "unpublished_changes": d != p,
            "updated_at": r.updated_at if r else "", "updated_by": r.updated_by if r else "",
            "published_at": r.published_at if r else "", "published_by": r.published_by if r else "",
        })
    return out


# CHECKING WHAT IS SAVED. A section keeps the shape it was built with (the first content), every picture is one of the
# site's own or one uploaded here, and every link goes to a web address - never a script.

def _bad(where, what):
    raise HTTPException(400, "%s: %s" % (where, what))


def _check_text(where, value):
    if len(value) > MAX_TEXT:
        _bad(where, "keep it under %d characters" % MAX_TEXT)


def _check_image(where, value):
    if value == "":
        return
    if value.startswith("site/") and ".." not in value and re.fullmatch(r"[A-Za-z0-9/_.\-]+", value):
        return
    if re.fullmatch(re.escape(IMAGE_PATH) + r"\d+", value):
        return
    _bad(where, "choose a picture from the website's pictures")


def _check_link(where, value):
    if value == "" or re.match(r"^https?://[^\s<>\"']+$", value, re.I) or re.fullmatch(r"site/[A-Za-z0-9/_.\-]+", value):
        return
    _bad(where, "a link must be a web address starting with https://")


def _like(where, value, shape, key=""):
    """`value` has the shape of `shape`: the same kinds of thing at the same places. A list's items are each checked
    against the list's first item; an empty list in the first content takes any list of plain objects and text."""
    if isinstance(shape, bool):
        if not isinstance(value, bool):
            _bad(where, "should be yes or no")
    elif shape is None or isinstance(shape, (int, float)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            _bad(where, "should be a number, or left empty")
    elif isinstance(shape, str):
        if not isinstance(value, str):
            _bad(where, "should be text")
        _check_text(where, value)
        if key in IMAGE_KEYS:
            _check_image(where, value)
        if key in LINK_KEYS:
            _check_link(where, value)
    elif isinstance(shape, list):
        if not isinstance(value, list):
            _bad(where, "should be a list")
        if len(value) > 60:
            _bad(where, "at most 60 entries")
        for i, item in enumerate(value):
            _like("%s, entry %d" % (where, i + 1), item, shape[0] if shape else _free(item), key)
    elif isinstance(shape, dict):
        if not isinstance(value, dict):
            _bad(where, "should be a set of fields")
        for k, v in value.items():
            if k in shape:
                _like(where, v, shape[k], k)
            elif k == "link" and isinstance(v, dict):         # a policy may link to a document
                _like(where, v, {"label": "", "href": ""}, k)
            elif k == "ledeEmpty" and isinstance(v, str):
                _check_text(where, v)
            else:
                _bad(where, "%s is not one of its fields" % k)


def _free(item):
    """The shape of an entry in a list that starts empty: a line of text (the clients), or a set of text fields (the story's
    milestones) - pictures and links among them, checked as such."""
    if isinstance(item, str):
        return ""
    if isinstance(item, dict) and all(isinstance(v, str) for v in item.values()):
        return {k: "" for k in item}
    _bad("Entry", "should be a line of text or a set of text fields")


def _check_layout(value):
    if not isinstance(value, list) or not all(isinstance(x, dict) and set(x) == {"id", "shown"} for x in value):
        _bad("Page layout", "each section needs its name and whether it is shown")
    ids = [x["id"] for x in value]
    if sorted(ids) != sorted(PAGE_SECTIONS):
        _bad("Page layout", "every section of the page must be listed once")
    if not all(isinstance(x["shown"], bool) for x in value):
        _bad("Page layout", "shown should be yes or no")


def _check_projects(db, client_id, value):
    if not isinstance(value, dict):
        _bad("Projects", "should be a set of projects")
    J, F = models.DBJob, models.DBFile
    for key, card in value.items():
        if not str(key).isdigit():
            _bad("Projects", "unknown project")
        job = db.query(J.id).filter(J.client_id == client_id, J.id == int(key)).first()
        if not job:
            _bad("Projects", "project %s is not one of ours" % key)
        if not isinstance(card, dict) or set(card) - {"show", "sector", "location", "scope", "photos"}:
            _bad("Projects", "each project has: shown, sector, place, scope and photos")
        _like("Projects", card.get("show", False), False)
        for field, most in (("sector", 60), ("location", 80), ("scope", 600)):
            v = card.get(field, "")
            if not isinstance(v, str) or len(v) > most:
                _bad("Projects", "%s: at most %d characters" % (field, most))
        photos = card.get("photos")
        if photos is not None:
            if not isinstance(photos, list) or len(photos) > MAX_PROJECT_PHOTOS or not all(isinstance(p, int) for p in photos):
                _bad("Projects", "at most %d photos" % MAX_PROJECT_PHOTOS)
            found = db.query(F.id).filter(F.client_id == client_id, F.id.in_(photos or [0]), F.job_id == int(key),
                                          F.kind == "photo", F.attached_type == "job").count()
            if found != len(set(photos)):
                _bad("Projects", "a photo chosen is not one of that project's photos")


def check(db, client_id, key, value, deep=True):
    """Refuse what is not this section's shape. `deep`: also check what it names in the records (a project's photos)."""
    if key not in SECTION_KEYS:
        raise HTTPException(404, "There is no such section of the website.")
    if len(json.dumps(value)) > MAX_SECTION_BYTES:
        _bad(dict(SECTIONS)[key], "too long")
    if key == "layout":
        _check_layout(value)
    elif key == "projects":
        if deep:
            _check_projects(db, client_id, value)
        elif not isinstance(value, dict):
            _bad("Projects", "should be a set of projects")
    else:
        _like(dict(SECTIONS)[key], value, seed()[key])


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_draft(db, client_id, key, value, by):
    """Keep `value` as the section's draft. Visitors see nothing of it until it is published. A field it leaves out is given
    its first content, so what is kept always has the section's whole shape."""
    if key in SECTION_KEYS and key not in ("projects", "layout"):
        value = _fill(value, seed()[key])
    check(db, client_id, key, value)
    ensure_sections(db, client_id)
    row = _rows(db, client_id)[key]
    row.draft = json.dumps(value, ensure_ascii=False)
    row.updated_at, row.updated_by = _now(), by
    return row


def discard_draft(db, client_id, key, by):
    """Put the section's draft back to what is published."""
    if key not in SECTION_KEYS:
        raise HTTPException(404, "There is no such section of the website.")
    ensure_sections(db, client_id)
    row = _rows(db, client_id)[key]
    row.draft = row.published
    row.updated_at, row.updated_by = _now(), by


def _apply_projects(db, client_id, cards):
    """Each project's card onto the project, which is what the website reads. A project without a card is left as it is."""
    J = models.DBJob
    ids = [int(k) for k in cards if str(k).isdigit()]
    for job in db.query(J).filter(J.client_id == client_id, J.id.in_(ids or [0])).all():
        card = cards.get(str(job.id)) or {}
        job.show_on_website = bool(card.get("show"))
        job.website_sector = (card.get("sector") or "")[:60]
        job.website_location = (card.get("location") or "")[:80]
        job.website_scope = (card.get("scope") or "")[:600]


def publish(db, client_id, by, note=""):
    """Make every draft live, and keep this publishing as the next numbered version. Returns the version."""
    ensure_sections(db, client_id)
    rows = _rows(db, client_id)
    now = _now()
    for row in rows.values():
        # A draft saved before a check was tightened is checked again on its way out.
        check(db, client_id, row.key, _load(row.draft, seed()[row.key]))
    V = models.DBWebsiteVersion
    last = db.query(V.number).filter(V.client_id == client_id).order_by(V.number.desc()).first()
    number = last[0] if last else 0
    if not last:
        # The first publishing: the website as it stood before it is kept as version 1, so it can always be put back.
        before = {k: _load(r.published, None) for k, r in rows.items()}
        before["projects"] = _all_cards(db, client_id, before.get("projects") or {})
        number += 1
        db.add(V(client_id=client_id, number=number, content=json.dumps(before, ensure_ascii=False),
                 note="The website before anything was published from here", published_at=now, published_by="As built"))
    for row in rows.values():
        if row.published != row.draft:
            row.published, row.published_at, row.published_by = row.draft, now, by
    content = {k: _load(r.published, None) for k, r in rows.items()}
    _apply_projects(db, client_id, content.get("projects") or {})
    # Every project's card as it now stands, so putting this version back puts the projects back too.
    content["projects"] = _all_cards(db, client_id, content.get("projects") or {})
    version = V(client_id=client_id, number=number + 1, content=json.dumps(content, ensure_ascii=False),
                note=(note or "")[:200], published_at=now, published_by=by)
    db.add(version)
    db.flush()
    return version


def _all_cards(db, client_id, cards):
    """Every project's card: the one given where there is one (it carries the photos chosen), else what the project holds."""
    J = models.DBJob
    out = {}
    for j in db.query(J).filter(J.client_id == client_id, J.status != "cancelled").all():
        given = cards.get(str(j.id))
        out[str(j.id)] = given if isinstance(given, dict) else {
            "show": bool(j.show_on_website), "sector": j.website_sector or "", "location": j.website_location or "",
            "scope": j.website_scope or ""}
    return out


def versions(db, client_id, limit=50):
    V = models.DBWebsiteVersion
    return [{"id": v.id, "number": v.number, "note": v.note, "published_at": v.published_at, "published_by": v.published_by}
            for v in db.query(V).filter(V.client_id == client_id).order_by(V.number.desc()).limit(limit).all()]


def restore(db, client_id, version_id, by):
    """Put an earlier version back on the website: it becomes the draft of every section it holds and is published again,
    as a new version. Nothing is lost: the version it replaces stays in the history."""
    V = models.DBWebsiteVersion
    old = db.query(V).filter(V.client_id == client_id, V.id == version_id).first()
    if not old:
        raise HTTPException(404, "That version is not in the history.")
    content = _load(old.content, {})
    ensure_sections(db, client_id)
    rows = _rows(db, client_id)
    for key, value in content.items():
        if key in rows and value is not None:
            # A version from before Look B is put back in Look B's shape.
            rows[key].draft = json.dumps(value, ensure_ascii=False) if key == "projects" else _upgraded(key, json.dumps(value))
            rows[key].updated_at, rows[key].updated_by = _now(), by
    return publish(db, client_id, by, note="Restored version %d" % old.number)


def image_in_use(db, client_id, fid, which="published"):
    """Whether a picture uploaded here is used in the website's `which` version."""
    return ("%s%d\"" % (IMAGE_PATH, fid)) in json.dumps(_version(db, client_id, which))


def programme_done(db, client_id, job):
    """How much of the project is done, as a whole number per cent, from its programme: each activity's progress times its
    share of the job, as the programme rolls it up. None when the project has no programme."""
    from datetime import date
    from app.services.projects import ScheduleContext
    try:
        ctx = ScheduleContext(db, client_id, job.id)
        if not ctx.acts:
            return None
        weight, today = ctx.weight or {}, date.today()
        done = sum(weight.get(a.id, 0) * ctx.actual(a, today) for a in ctx.leaves)
        return max(0, min(100, int(round(done))))
    except Exception:
        return None


def overview(db, client_id):
    """What the Website tab's overview counts from the records: the website's enquiries this week, and the photographs on
    the projects shown."""
    from datetime import timedelta
    week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    L, J, F = models.DBLead, models.DBJob, models.DBFile
    enquiries = db.query(L.id).filter(L.client_id == client_id, L.source == "Website enquiry", L.created_at >= week).count()
    shown = [j for (j,) in db.query(J.id).filter(J.client_id == client_id, J.show_on_website.is_(True)).all()]
    photos = db.query(F.id).filter(F.client_id == client_id, F.job_id.in_(shown or [0]), F.kind == "photo",
                                   F.attached_type == "job").count() if shown else 0
    return {"enquiries_this_week": enquiries, "project_photos": photos}
