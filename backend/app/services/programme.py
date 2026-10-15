"""A project's programme, worked out: its rows as the office's Excel schedule has them, with every date, day count,
number, roll-up and critical flag computed by app/services/programme_engine.py.

What a leaf keeps is what was typed (its start, and its working days or, with none, its finish); what is shown is what
the rules make of it. A parent keeps nothing of its own: its dates are its sub-items'.
"""
from datetime import date

from app import models
from app.services.programme_engine import (Calendar, Link, Row, format_predecessors, planned_percent, project_percent,
                                           schedule)
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
            "id": rid, "parent_id": a.parent_id if a.parent_id in by_id else None, "wbs": p.wbs, "level": p.level,
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
        "rows": out,
    }
