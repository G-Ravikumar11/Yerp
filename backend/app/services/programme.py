"""A project's programme, worked out: its rows as the office's Excel schedule has them, with every date, day count,
number, roll-up and critical flag computed by app/services/programme_engine.py.

What a leaf keeps is what was typed (its start, and its working days or, with none, its finish); what is shown is what
the rules make of it. A parent keeps nothing of its own: its dates are its sub-items'.
"""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.services.programme_engine import (Calendar, Link, Row, format_predecessors, parse_predecessors, planned_percent,
                                           project_percent, schedule)
from app.services.projects import _d


def programme_calendar(db, client_id, job):
    """The project's working week and holidays, as the engine takes them and as the screen shows them."""
    c = db.query(models.DBScheduleCalendar).filter(models.DBScheduleCalendar.client_id == client_id,
                                                   models.DBScheduleCalendar.job_id == job.id).first()
    holidays = db.query(models.DBScheduleHoliday).filter(models.DBScheduleHoliday.client_id == client_id,
                                                         models.DBScheduleHoliday.job_id == job.id).order_by(
        models.DBScheduleHoliday.holiday_on).all()
    calendar_days = bool(c and c.calendar_days)
    weekly_off = sorted({int(x) for x in ((c.weekly_off if c else "7") or "").split(",") if x.strip().isdigit()
                         and 1 <= int(x) <= 7})
    cal = Calendar(calendar_days=calendar_days, weekly_off=frozenset(weekly_off),
                   holidays=frozenset(d for d in (_d(h.holiday_on) for h in holidays) if d))
    shown = {"calendar_days": calendar_days, "weekly_off": weekly_off,
             "holidays": [{"id": h.id, "date": h.holiday_on, "name": h.name} for h in holidays]}
    return cal, shown


def programme_inputs(db, client_id, job):
    """The rows and links as the engine takes them. A link from before links were kept on their own (an activity's
    single "depends on") counts as finish-to-start with no lag."""
    acts = db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.client_id == client_id,
                                                      models.DBScheduleActivity.job_id == job.id).all()
    latest = {}
    for p in db.query(models.DBScheduleProgress).filter(
            models.DBScheduleProgress.activity_id.in_([a.id for a in acts] or [0])).order_by(
            models.DBScheduleProgress.reported_on, models.DBScheduleProgress.id).all():
        latest[p.activity_id] = p.percent
    rows = [Row(id=a.id, parent_id=a.parent_id, order=a.display_order or 0, name=a.name or "",
                start=_d(a.planned_start), end=_d(a.planned_finish), days=a.duration_days, not_before=_d(a.not_before),
                milestone=bool(a.is_milestone), quantity=a.quantity or 0.0, rate=a.rate or 0.0,
                # rows drawn before amounts were kept carry their value as a weight
                amount=(a.amount or 0.0) or (a.weight or 0.0), qty_done=a.qty_done or 0.0, percent=latest.get(a.id),
                productivity=bool(a.productivity), output_per_day=a.output_per_day or 0.0, gangs=a.gangs or 0.0)
            for a in acts]
    links = [Link(ln.activity_id, ln.predecessor_id, ln.kind or "FS", ln.lag or 0)
             for ln in db.query(models.DBScheduleLink).filter(models.DBScheduleLink.client_id == client_id,
                                                              models.DBScheduleLink.job_id == job.id).all()]
    have = {(ln.predecessor, ln.successor) for ln in links}
    links += [Link(a.id, a.depends_on_id, "FS", 0) for a in acts
              if a.depends_on_id and (a.depends_on_id, a.id) not in have]
    return acts, rows, links


def programme_baseline(db, client_id, job):
    """The latest saved baseline: activity -> (start, finish, days), and what it was called."""
    b = db.query(models.DBScheduleBaseline).filter(models.DBScheduleBaseline.client_id == client_id,
                                                   models.DBScheduleBaseline.job_id == job.id).order_by(
        models.DBScheduleBaseline.id.desc()).first()
    if not b:
        return None, {}
    rows = db.query(models.DBScheduleBaselineRow).filter(models.DBScheduleBaselineRow.baseline_id == b.id).all()
    return b, {r.activity_id: (_d(r.start), _d(r.finish), r.days) for r in rows if _d(r.start) and _d(r.finish)}


def programme_view(db, client, job, as_of=None):
    """The programme for the screen: header, every row in order with its worked-out figures, and what went wrong."""
    as_of = as_of or date.today()
    cal, shown = programme_calendar(db, client.id, job)
    acts, rows, links = programme_inputs(db, client.id, job)
    prog = schedule(rows, links, cal)
    baseline, base_dates = programme_baseline(db, client.id, job)
    planned = planned_percent(prog, cal, as_of, base_dates)
    by_id = {a.id: a for a in acts}
    wbs = {i: p.wbs for i, p in prog.rows.items()}
    preds = {}
    for ln in links:
        if ln not in prog.broken_links:
            preds.setdefault(ln.successor, []).append((ln.predecessor, ln.kind, ln.lag))
    iso = lambda d: d.isoformat() if d else None
    out = []
    for rid in prog.order:
        a, p = by_id[rid], prog.rows[rid]
        b = base_dates.get(rid)
        out.append({
            "id": rid, "parent_id": a.parent_id if a.parent_id in by_id else None, "order": a.display_order or 0,
            "wbs": p.wbs, "level": p.level,
            "summary": p.summary, "name": a.name or "", "description": a.description or "", "boq_ref": a.boq_ref or "",
            "boq_key": a.boq_key or "", "uom": a.uom or "", "quantity": a.quantity or 0.0, "rate": a.rate or 0.0,
            "amount": a.amount or 0.0, "labour_required": a.labour_required or 0.0,
            "start": iso(p.start), "end": iso(p.end), "days": p.days,
            "typed": {"start": a.planned_start or "", "end": a.planned_finish or "", "days": a.duration_days},
            "not_before": a.not_before or "", "predecessors": format_predecessors(preds.get(rid, []), wbs),
            "milestone": bool(a.is_milestone), "productivity": bool(a.productivity),
            "output_per_day": a.output_per_day or 0.0, "gangs": a.gangs or 0.0, "qty_done": a.qty_done or 0.0,
            "percent": round(p.percent, 2), "planned_percent": round(planned[rid], 2),
            "critical": p.critical, "float_days": p.float_days, "problem": p.problem,
            "baseline": {"start": iso(b[0]), "end": iso(b[1]),
                         "slip_days": (p.end - b[1]).days if p.end else None} if b else None,
        })
    return {
        "job": {"id": job.id, "number": job.number or "", "name": job.name or "", "location": job.site_address or ""},
        "company": client.company_name or "",
        "calendar": shown,
        "start": iso(prog.start), "finish": iso(prog.finish), "duration": prog.duration,
        "as_of": as_of.isoformat(),
        "percent": round(project_percent(prog), 2), "planned_percent": round(planned["project"], 2),
        "baseline": {"id": baseline.id, "label": baseline.label, "saved_at": baseline.created_at} if baseline else None,
        "errors": prog.errors,
        "broken_links": [{"successor": ln.successor, "predecessor": ln.predecessor, "kind": ln.kind, "lag": ln.lag}
                         for ln in prog.broken_links],
        "links": [{"successor": ln.successor, "predecessor": ln.predecessor, "kind": ln.kind, "lag": ln.lag}
                  for ln in links],
        "rows": out,
    }


# --- changing the programme ------------------------------------------------------------------------------------------
#
# Every change is followed by the whole programme worked out again (programme_view), so the screen always shows what
# the server holds. A change that would make a loop of dependencies is refused and nothing of it is kept.

NUMBERS = ("quantity", "rate", "amount", "labour_required", "output_per_day", "gangs", "qty_done")
TEXTS = ("name", "description", "boq_ref", "uom")
FLAGS = {"milestone": "is_milestone", "productivity": "productivity"}


def job_rows(db, client_id, job):
    return db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.client_id == client_id,
                                                      models.DBScheduleActivity.job_id == job.id).all()


def _kids(acts):
    by_parent = {}
    for a in sorted(acts, key=lambda x: (x.display_order or 0, x.id)):
        by_parent.setdefault(a.parent_id if a.parent_id in {b.id for b in acts} else None, []).append(a)
    return by_parent


def subtree(acts, rid):
    """This row and every row under it, top first."""
    kids, out, todo = _kids(acts), [], [rid]
    by_id = {a.id: a for a in acts}
    while todo:
        i = todo.pop(0)
        if i in by_id:
            out.append(by_id[i])
            todo = [k.id for k in kids.get(i, [])] + todo
    return out


def _row_or_404(acts, rid):
    for a in acts:
        if a.id == rid:
            return a
    raise HTTPException(404, "That row is not on this programme.")


def _place(acts, row, parent_id, before_id=None):
    """Put row under parent_id (None: the top), before the sibling before_id or at the end, and number the siblings."""
    row.parent_id = parent_id
    sibs = [a for a in _kids(acts).get(parent_id, []) if a.id != row.id]
    at = next((i for i, a in enumerate(sibs) if a.id == before_id), len(sibs))
    sibs.insert(at, row)
    for i, a in enumerate(sibs):
        a.display_order = i + 1


def _check_loops(db, client, job, touched):
    """Refuse what makes a loop of dependencies; nothing is kept (the caller's transaction is rolled back)."""
    db.flush()
    cal, _ = programme_calendar(db, client.id, job)
    _, rows, links = programme_inputs(db, client.id, job)
    prog = schedule(rows, links, cal)
    if any(ln.successor in touched or ln.predecessor in touched for ln in prog.broken_links):
        db.rollback()
        raise HTTPException(400, next(e for e in prog.errors if e.startswith("Circular")))


def add_rows(db, client, job, anchor_id, position, rows):
    """New rows after the anchor (same level), under it (as its last sub-items), or at the end of the programme."""
    acts = job_rows(db, client.id, job)
    anchor = _row_or_404(acts, anchor_id) if anchor_id else None
    if position == "child" and anchor is None:
        raise HTTPException(400, "Choose the row to add a sub-item under.")
    parent = anchor.id if position == "child" else (anchor.parent_id if anchor else None)
    sibs = [a for a in _kids(acts).get(parent, [])]
    before = None
    if position == "after" and anchor is not None:
        at = next(i for i, a in enumerate(sibs) if a.id == anchor.id)
        before = sibs[at + 1].id if at + 1 < len(sibs) else None
    made = []
    for spec in rows or [{}]:
        a = models.DBScheduleActivity(client_id=client.id, job_id=job.id, name=(spec.get("name") or "New activity")[:200])
        db.add(a)
        db.flush()
        acts.append(a)
        _place(acts, a, parent, before)
        made.append(a)
        if spec:
            edit_rows(db, client, job, [{"id": a.id, **{k: v for k, v in spec.items() if k != "name"}}], check=False)
    _check_loops(db, client, job, {a.id for a in made})
    db.commit()
    return [a.id for a in made]


def _typed_dates(db, client, job, a, values, cal):
    """Start, End and Days as typed on a leaf: End typed gives the Days; Days typed gives the End."""
    if "start" in values:
        a.planned_start = _date_text(values["start"], "Start")
    if "days" in values:
        v = values["days"]
        if v in (None, ""):
            a.duration_days = None
        else:
            try:
                n = int(float(v))
            except (TypeError, ValueError):
                raise HTTPException(400, "Days must be a whole number of working days.")
            if n < 0:
                raise HTTPException(400, "Days cannot be negative.")
            a.duration_days = n
    if "end" in values:
        a.planned_finish = _date_text(values["end"], "End")
        s, e = _d(a.planned_start), _d(a.planned_finish)
        if s and e:
            if e < s:
                raise HTTPException(400, "End cannot be before Start.")
            a.duration_days = cal.span(cal.snap(s), e)


def _date_text(v, label):
    if v in (None, ""):
        return ""
    d = _d(v)
    if not d:
        raise HTTPException(400, "%s must be a date (YYYY-MM-DD)." % label)
    return d.isoformat()


def edit_rows(db, client, job, changes, check=True):
    """Each change: {"id", and any of name, description, boq_ref, uom, quantity, rate, amount, labour_required,
    start, end, days, not_before, predecessors, milestone, productivity, output_per_day, gangs, qty_done}."""
    acts = job_rows(db, client.id, job)
    by_id = {a.id: a for a in acts}
    kids = _kids(acts)
    cal, _ = programme_calendar(db, client.id, job)
    view = None
    touched = set()
    for ch in changes:
        a = by_id.get(ch.get("id"))
        if a is None:
            raise HTTPException(404, "That row is not on this programme.")
        touched.add(a.id)
        heading = bool(kids.get(a.id))
        for k in TEXTS:
            if k in ch:
                text = str(ch[k] or "").strip()
                if k == "name" and not text:
                    raise HTTPException(400, "A row needs a name.")
                setattr(a, k, text[:4000] if k == "description" else text[:200])
        for k in NUMBERS:
            if k in ch:
                try:
                    v = float(ch[k] or 0)
                except (TypeError, ValueError):
                    raise HTTPException(400, "%s must be a number." % k.replace("_", " ").capitalize())
                if v < 0:
                    raise HTTPException(400, "%s cannot be negative." % k.replace("_", " ").capitalize())
                setattr(a, k, v)
        for k, col in FLAGS.items():
            if k in ch:
                setattr(a, col, bool(ch[k]))
        if "not_before" in ch:
            a.not_before = _date_text(ch["not_before"], "Not earlier than")
        if any(k in ch for k in ("start", "end", "days")):
            if heading:
                raise HTTPException(400, "%s takes its dates from its sub-items." % (a.name or "A heading"))
            _typed_dates(db, client, job, a, ch, cal)
        if "predecessors" in ch:
            if heading:
                raise HTTPException(400, "%s takes its dates from its sub-items; link a sub-item instead." % (a.name or "A heading"))
            if view is None:
                view = programme_view(db, client, job)
            wbs = {r["wbs"]: r["id"] for r in view["rows"]}
            found, problems = parse_predecessors(str(ch["predecessors"] or ""), wbs)
            if problems:
                raise HTTPException(400, " ".join(problems))
            db.query(models.DBScheduleLink).filter(models.DBScheduleLink.activity_id == a.id).delete(
                synchronize_session=False)
            a.depends_on_id = None
            for pred, kind, lag in found:
                if pred == a.id:
                    raise HTTPException(400, "A row cannot wait on itself.")
                db.add(models.DBScheduleLink(client_id=client.id, job_id=job.id, activity_id=a.id, predecessor_id=pred,
                                             kind=kind, lag=lag))
    if check:
        _check_loops(db, client, job, touched)
        db.commit()


def move_row(db, client, job, rid, parent_id, before_id):
    """Indent, outdent, drag: the row, with everything under it, goes under parent_id before before_id."""
    acts = job_rows(db, client.id, job)
    row = _row_or_404(acts, rid)
    if parent_id is not None:
        _row_or_404(acts, parent_id)
        if parent_id in {a.id for a in subtree(acts, rid)}:
            raise HTTPException(400, "A row cannot go under itself or under one of its own sub-items.")
    old_parent = row.parent_id
    _place(acts, row, parent_id, before_id)
    for i, a in enumerate([a for a in _kids(acts).get(old_parent, []) if a.id != rid]):
        a.display_order = i + 1
    _check_loops(db, client, job, {a.id for a in subtree(acts, rid)})
    db.commit()


def _copy_tree(db, client, job, acts, source, shift_days=0, name=None):
    """A copy of source and everything under it; the links among them come too. Returns (map old id -> new row,
    links that pointed outside and were left behind)."""
    rows = subtree(acts, source.id)
    ids = {a.id for a in rows}
    made = {}
    shift = lambda text: ((_d(text) + timedelta(days=shift_days)).isoformat() if _d(text) and shift_days else (text or ""))
    for a in rows:
        b = models.DBScheduleActivity(
            client_id=client.id, job_id=job.id, name=a.name, description=a.description, boq_ref=a.boq_ref, boq_key="",
            uom=a.uom, quantity=a.quantity, rate=a.rate, amount=a.amount, labour_required=a.labour_required,
            planned_start=shift(a.planned_start), planned_finish=shift(a.planned_finish), duration_days=a.duration_days,
            not_before=shift(a.not_before), is_milestone=a.is_milestone, productivity=a.productivity,
            output_per_day=a.output_per_day, gangs=a.gangs, weight=a.weight, display_order=a.display_order)
        db.add(b)
        db.flush()
        made[a.id] = b
    for a in rows:
        made[a.id].parent_id = made[a.parent_id].id if a.parent_id in made else None
    if name:
        made[source.id].name = name[:200]
    left_out = []
    links = db.query(models.DBScheduleLink).filter(models.DBScheduleLink.activity_id.in_(list(ids))).all()
    implicit = [(a.depends_on_id, a.id) for a in rows if a.depends_on_id]
    for pred, succ, kind, lag in [(ln.predecessor_id, ln.activity_id, ln.kind, ln.lag) for ln in links] + \
            [(p, s, "FS", 0) for p, s in implicit]:
        if pred in ids:
            db.add(models.DBScheduleLink(client_id=client.id, job_id=job.id, activity_id=made[succ].id,
                                         predecessor_id=made[pred].id, kind=kind, lag=lag))
        else:
            left_out.append((succ, pred))
    return made, left_out


def duplicate_row(db, client, job, rid):
    acts = job_rows(db, client.id, job)
    source = _row_or_404(acts, rid)
    made, _ = _copy_tree(db, client, job, acts, source, name="%s (copy)" % (source.name or "Row"))
    top = made[source.id]
    acts = job_rows(db, client.id, job)
    sibs = _kids(acts).get(source.parent_id, [])
    at = next(i for i, a in enumerate(sibs) if a.id == source.id)
    nxt = next((a.id for a in sibs[at + 1:] if a.id != top.id), None)
    _place(acts, next(a for a in acts if a.id == top.id), source.parent_id, nxt)
    db.commit()
    return top.id


def copy_to_units(db, client, job, source_id, targets):
    """The same set of activities for other units: each target is a copy of the source and everything under it, renamed,
    starting on its own date (or moved by an offset in days). Links inside the copy come with it; links to rows
    outside it do not, and are listed so they can be added again."""
    acts = job_rows(db, client.id, job)
    source = _row_or_404(acts, source_id)
    view = programme_view(db, client, job)
    src = next(r for r in view["rows"] if r["id"] == source.id)
    names = {r["id"]: "%s %s" % (r["wbs"], r["name"]) for r in view["rows"]}
    made_ids, dropped = [], []
    for t in targets:
        if not (t.get("name") or "").strip():
            raise HTTPException(400, "Each unit needs a name.")
        start = _d(t.get("start"))
        if start and not src["start"]:
            raise HTTPException(400, "%s has no dates yet; give an offset in days instead." % (source.name or "The row"))
        offset = (start - _d(src["start"])).days if start else int(t.get("offset") or 0)
        made, left_out = _copy_tree(db, client, job, acts, source, offset, t["name"].strip())
        made_ids.append(made[source.id].id)
        dropped += ["%s on %s" % (t["name"].strip(), names.get(p, p)) for _s, p in left_out]
    acts = job_rows(db, client.id, job)
    sibs = _kids(acts).get(source.parent_id, [])
    at = next(i for i, a in enumerate(sibs) if a.id == source.id)
    nxt = next((a.id for a in sibs[at + 1:] if a.id not in made_ids), None)
    for rid in made_ids:
        _place(acts, next(a for a in acts if a.id == rid), source.parent_id, nxt)
    db.commit()
    return made_ids, sorted(set(dropped))


def delete_row(db, client, job, rid):
    """The row and everything under it, with their links, tasks and progress."""
    from app.services import purge
    acts = job_rows(db, client.id, job)
    row = _row_or_404(acts, rid)
    ids = [a.id for a in subtree(acts, rid)]
    parent = row.parent_id
    purge.purge(db, "schedule_activities", ids)
    rest = [a for a in job_rows(db, client.id, job) if a.parent_id == parent]
    for i, a in enumerate(sorted(rest, key=lambda x: (x.display_order or 0, x.id))):
        a.display_order = i + 1
    db.commit()
    return len(ids)


# --- the project's working week and holidays -------------------------------------------------------------------------

def set_calendar(db, client, job, calendar_days, weekly_off):
    off = sorted({int(w) for w in weekly_off or [] if str(w).isdigit() and 1 <= int(w) <= 7})
    if not calendar_days and len(off) == 7:
        raise HTTPException(400, "At least one day of the week has to be a working day.")
    c = db.query(models.DBScheduleCalendar).filter(models.DBScheduleCalendar.client_id == client.id,
                                                   models.DBScheduleCalendar.job_id == job.id).first()
    if c is None:
        c = models.DBScheduleCalendar(client_id=client.id, job_id=job.id)
        db.add(c)
    c.calendar_days = bool(calendar_days)
    c.weekly_off = ",".join(str(w) for w in off)
    c.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()


def add_holiday(db, client, job, on, name):
    d = _d(on)
    if not d:
        raise HTTPException(400, "Give the holiday's date (YYYY-MM-DD).")
    exists = db.query(models.DBScheduleHoliday).filter(models.DBScheduleHoliday.client_id == client.id,
                                                       models.DBScheduleHoliday.job_id == job.id,
                                                       models.DBScheduleHoliday.holiday_on == d.isoformat()).first()
    if not exists:
        db.add(models.DBScheduleHoliday(client_id=client.id, job_id=job.id, holiday_on=d.isoformat(),
                                        name=(name or "").strip()[:120]))
    db.commit()


def add_public_holidays(db, client, job, year):
    """India's public holidays for a year (the same list the calendar shows), skipping those already there."""
    import holidays as holiday_lists
    if not 2000 <= int(year) <= 2100:
        raise HTTPException(400, "Choose a year between 2000 and 2100.")
    have = {h.holiday_on for h in db.query(models.DBScheduleHoliday).filter(
        models.DBScheduleHoliday.client_id == client.id, models.DBScheduleHoliday.job_id == job.id).all()}
    added = 0
    for d, name in sorted(holiday_lists.India(years=int(year)).items()):
        if d.isoformat() not in have:
            db.add(models.DBScheduleHoliday(client_id=client.id, job_id=job.id, holiday_on=d.isoformat(), name=name[:120]))
            added += 1
    db.commit()
    return added


def delete_holiday(db, client, job, hid):
    n = db.query(models.DBScheduleHoliday).filter(models.DBScheduleHoliday.id == hid,
                                                  models.DBScheduleHoliday.client_id == client.id,
                                                  models.DBScheduleHoliday.job_id == job.id).delete(synchronize_session=False)
    if not n:
        raise HTTPException(404, "That holiday is not on this project.")
    db.commit()


# --- undo and redo: the programme put back as it was -----------------------------------------------------------------

SNAPSHOT_FIELDS = ("name", "description", "boq_ref", "uom", "quantity", "rate", "amount", "labour_required",
                   "not_before", "productivity", "output_per_day", "gangs", "qty_done")


def restore(db, client, job, rows, links):
    """The programme as it was in a snapshot the screen kept: rows added since go, rows deleted since come back with
    their own numbers (their day tasks and progress do not), every row's fields and the links are as they were."""
    acts = job_rows(db, client.id, job)
    by_id = {a.id: a for a in acts}
    keep = {int(r["id"]) for r in rows}
    gone = [a.id for a in acts if a.id not in keep]
    if gone:
        from app.services import purge
        purge.purge(db, "schedule_activities", gone)
    taken = {i for (i,) in db.query(models.DBScheduleActivity.id).filter(models.DBScheduleActivity.id.in_(list(keep))).all()}
    for r in rows:
        rid = int(r["id"])
        if rid in taken and rid not in by_id:
            raise HTTPException(409, "The programme has changed since; reload it before undoing.")
        a = by_id.get(rid)
        if a is None:
            a = models.DBScheduleActivity(id=rid, client_id=client.id, job_id=job.id)
            db.add(a)
            by_id[rid] = a
        for k in SNAPSHOT_FIELDS:
            if k in r:
                setattr(a, k, r[k])
        a.is_milestone = bool(r.get("milestone"))
        a.planned_start = r.get("typed_start") or ""
        a.planned_finish = r.get("typed_end") or ""
        a.duration_days = r.get("typed_days")
        a.display_order = r.get("order") or 0
        a.depends_on_id = None
    db.flush()
    for r in rows:
        p = r.get("parent_id")
        by_id[int(r["id"])].parent_id = int(p) if p and int(p) in keep else None
    db.query(models.DBScheduleLink).filter(models.DBScheduleLink.client_id == client.id,
                                           models.DBScheduleLink.job_id == job.id).delete(synchronize_session=False)
    for ln in links:
        s, p = int(ln["successor"]), int(ln["predecessor"])
        if s in keep and p in keep and s != p:
            db.add(models.DBScheduleLink(client_id=client.id, job_id=job.id, activity_id=s, predecessor_id=p,
                                         kind=(ln.get("kind") or "FS").upper(), lag=int(ln.get("lag") or 0)))
    db.commit()
