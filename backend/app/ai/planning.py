"""AI in the Planning area: draft a programme, suggest the day's tasks, flag delays, answer questions about the plan.

The model reads and writes words; plain code decides. Every suggestion is checked against the project's own records
before it is shown (only real work order lines, real activities, real dates), and nothing is saved until a person
presses the button that saves it. The delay findings are plain code and work with no key.

    POST /api/ai/planning/jobs/{job_id}/draft            {"work_order_id", "start", "finish"}   a proposed programme, not saved
    POST /api/ai/planning/jobs/{job_id}/draft/apply      {"work_order_id", "activities": [...]}  saves it, after a person checks it
    POST /api/ai/planning/jobs/{job_id}/day-plan         {"on": "YYYY-MM-DD"}                    suggested tasks for a day, not saved
    GET  /api/ai/planning/jobs/{job_id}/review                                                   delay findings, with a short summary
    POST /api/ai/planning/jobs/{job_id}/ask              {"question": "..."}                     an answer from the plan's own figures
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.ai import guard
from app.ai.llm_client import ask, ask_json
from app.core.auth import require_erp_read, wo_actor
from app.core.currency import money
from app.db import get_db
from app.services.projects import _d, job_or_404, schedule_day, schedule_view
from app.services.subcontract_orders import work_order_or_404

router = APIRouter()

KEY_DRAFT, KEY_DAY, KEY_REVIEW, KEY_ASK = "ai_plan_draft", "ai_plan_day", "ai_plan_review", "ai_plan_ask"
MAX_TASKS = 8

DRAFT_SYSTEM = (
    "You are a construction planner. You are given the lines of a priced work order and the dates the work must fit "
    "between. Put the lines in a sensible order of work and give each a start and finish inside those dates, longer "
    "for bigger or heavier lines. A line may follow another (after_line_id) when it cannot start before that one "
    "finishes. Use only the line ids given. Reply with {\"activities\": [{\"line_id\": 1, \"start\": \"YYYY-MM-DD\", "
    "\"finish\": \"YYYY-MM-DD\", \"after_line_id\": null}]}. Include every line once."
)
DAY_SYSTEM = (
    "You help a site engineer plan one day. You are given the activities running that day, those overdue and those "
    "starting soon, with how far each is. Suggest at most eight short, concrete tasks for the day (what to do, with "
    "numbers only if they appear in what you are given), putting overdue and behind work first. Each task names the "
    "activity id it belongs to. Reply with {\"tasks\": [{\"text\": \"...\", \"activity_id\": 1}]}."
)
REVIEW_SYSTEM = (
    "You help a project manager read a programme. You are given the project's progress and a list of delay checks "
    "already worked out. Write at most five short sentences in plain English: where the project stands, then the most "
    "important delays first and what each puts at risk. Use only what you are given; do not invent causes."
)
ASK_SYSTEM = (
    "You answer a project manager's question about one project's programme. You are given its activities with planned "
    "and actual progress, forecast finish dates and tasks. Answer only from them, in plain English, in at most six "
    "short sentences, quoting the figures you rely on. If the data cannot answer it, say so. Never invent a figure. "
    "You cannot change the plan."
)


def _off(result):
    return {"available": False, "reason": result.reason, "message": result.message}


# --- draft a programme from a work order ------------------------------------------------------------------------

def _span(start, finish):
    s, f = _d(start), _d(finish)
    if not s or not f or f <= s:
        raise HTTPException(400, "Give the span the work runs across.")
    return s, f


def _open_lines(db, job, wo):
    """The order's lines that are not yet on the programme."""
    have = {a.work_order_line_id for a in db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.job_id == job.id).all()}
    lines = db.query(models.DBWorkOrderLine).filter(models.DBWorkOrderLine.work_order_id == wo.id).order_by(models.DBWorkOrderLine.id).all()
    lines = [l for l in lines if l.id not in have]
    if not lines:
        raise HTTPException(409, "Every line of %s is already on the schedule." % wo.number)
    return lines


def _label(l):
    return (l.description or l.item_name or l.fg_code or "").split("\n")[0][:200]


def clean_draft(proposed, lines, s, f) -> list:
    """What the model proposed, brought back to what is true: only the order's open lines, each once, dates inside the
    span, never finishing before it starts, following only a line already placed. A line it missed or got wrong is laid
    end to end after the last one, so the result always covers every line."""
    by_id = {l.id: l for l in lines}
    out, placed = [], set()
    for p in proposed if isinstance(proposed, list) else []:
        if not isinstance(p, dict):
            continue
        try:
            lid = int(p.get("line_id"))
        except (TypeError, ValueError):
            continue
        a, b = _d(p.get("start")), _d(p.get("finish"))
        if lid not in by_id or lid in placed or not a or not b:
            continue
        a, b = max(s, min(a, f)), max(s, min(b, f))
        if b < a:
            a, b = b, a
        after = p.get("after_line_id")
        try:
            after = int(after) if after is not None else None
        except (TypeError, ValueError):
            after = None
        out.append({"line_id": lid, "start": a, "finish": b, "after_line_id": after if after in placed else None})
        placed.add(lid)
    cur = max([o["finish"] for o in out] or [s - timedelta(days=1)]) + timedelta(days=1)
    for l in lines:
        if l.id in placed:
            continue
        a = min(cur, f)
        out.append({"line_id": l.id, "start": a, "finish": f if l is lines[-1] else a, "after_line_id": out[-1]["line_id"] if out else None})
        placed.add(l.id)
        cur = min(f, a + timedelta(days=1))
    return [{"line_id": o["line_id"], "name": _label(by_id[o["line_id"]]), "weight": money(by_id[o["line_id"]].amount),
             "start": o["start"].isoformat(), "finish": o["finish"].isoformat(), "after_line_id": o["after_line_id"]} for o in out]


def _lines_facts(lines, s, f):
    rows = ["Work must fit between %s and %s." % (s, f), "Lines:"]
    for l in lines:
        rows.append("- id %d: %s | qty %s %s | value %s" % (l.id, _label(l), money(l.qty or 0), l.uom or "", money(l.amount or 0)))
    return "\n".join(rows)


@router.post("/api/ai/planning/jobs/{job_id}/draft")
def draft_programme(job_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    wo = work_order_or_404(db, client.id, int(body.get("work_order_id") or 0))
    if wo.job_id != job.id:
        raise HTTPException(400, "%s is not on this project." % wo.number)
    s, f = _span(body.get("start"), body.get("finish"))
    lines = _open_lines(db, job, wo)
    result = guard.run_feature(db, request, client, KEY_DRAFT, "Draft programme %s" % wo.number, wo.number or "",
                               lambda: ask_json(DRAFT_SYSTEM, _lines_facts(lines, s, f), smart=False, max_tokens=2500))
    if not result.ok:
        return {**_off(result), "activities": []}
    return {"available": True, "message": "", "work_order_id": wo.id,
            "activities": clean_draft((result.data or {}).get("activities"), lines, s, f)}


@router.post("/api/ai/planning/jobs/{job_id}/draft/apply")
def apply_draft(job_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Saves a programme a person has looked at. It is checked again here, so a hand-edited request cannot slip past."""
    client, _, _ = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    wo = work_order_or_404(db, client.id, int(body.get("work_order_id") or 0))
    if wo.job_id != job.id:
        raise HTTPException(400, "%s is not on this project." % wo.number)
    rows = body.get("activities")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "There is nothing to add.")
    lines = _open_lines(db, job, wo)
    dates = [d for r in rows if isinstance(r, dict) for d in (_d(r.get("start")), _d(r.get("finish"))) if d]
    if not dates:
        raise HTTPException(400, "Give the dates of each activity.")
    checked = clean_draft(rows, lines, min(dates), max(dates))
    n = db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.job_id == job.id).count()
    made = {}
    for i, c in enumerate(checked):
        a = models.DBScheduleActivity(client_id=client.id, job_id=job.id, code="A%d" % ((n + i + 1) * 10), name=c["name"],
                                      planned_start=c["start"], planned_finish=c["finish"], weight=c["weight"],
                                      work_order_line_id=c["line_id"], depends_on_id=made.get(c["after_line_id"]), display_order=n + i)
        db.add(a)
        db.flush()
        made[c["line_id"]] = a.id
    db.commit()
    return {"ok": True, "schedule": schedule_view(db, client.id, job), "message": "%d activities added from %s." % (len(checked), wo.number)}


# --- suggest the day's tasks -------------------------------------------------------------------------------------

def _day_facts(day) -> str:
    rows = ["Project %s %s, day %s. Done %s%% against %s%% planned." % (day["job"]["number"], day["job"]["name"], day["date"],
                                                                         day["summary"]["done_percent"], day["summary"]["planned_percent"])]
    for title, key in (("Running today", "today"), ("Overdue", "overdue"), ("Starting soon", "soon")):
        rows.append(title + ":")
        for a in day[key]:
            rows.append("- id %d: %s %s | %s to %s | %s%% done, %s%% planned%s" % (
                a["id"], a["code"], a["name"], a["planned_start"], a["planned_finish"], a["actual_percent"], a["planned_percent"],
                " | %s days late" % a["days_late"] if a.get("days_late") else ""))
    if day["tasks"]:
        rows.append("Tasks already set for the day: " + "; ".join(t["text"] for t in day["tasks"]))
    return "\n".join(rows)


def clean_tasks(proposed, day) -> list:
    """Only tasks with words, under an activity the day's plan names (or none), not repeating one already set."""
    ids = {a["id"] for key in ("today", "overdue", "soon") for a in day[key]}
    names = {a["id"]: ((a["code"] + " ") if a["code"] else "") + a["name"] for key in ("today", "overdue", "soon") for a in day[key]}
    have = {t["text"].strip().lower() for t in day["tasks"]}
    out = []
    for p in proposed if isinstance(proposed, list) else []:
        if not isinstance(p, dict):
            continue
        text = str(p.get("text") or "").strip()[:300]
        if not text or text.lower() in have:
            continue
        try:
            aid = int(p.get("activity_id"))
        except (TypeError, ValueError):
            aid = None
        aid = aid if aid in ids else None
        have.add(text.lower())
        out.append({"text": text, "activity_id": aid, "activity": names.get(aid, "")})
    return out[:MAX_TASKS]


@router.post("/api/ai/planning/jobs/{job_id}/day-plan")
def day_plan(job_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    on = body.get("on") or ""
    d = _d(on) if on else date.today()
    if d is None:
        raise HTTPException(400, "Give the date as YYYY-MM-DD.")
    day = schedule_day(db, client.id, job, d)
    if not (day["today"] or day["overdue"] or day["soon"]):
        return {"available": True, "message": "Nothing is running, overdue or starting soon on the programme for this day.", "date": day["date"], "tasks": []}
    result = guard.run_feature(db, request, client, KEY_DAY, "Day plan %s" % job.number, job.number or "",
                               lambda: ask_json(DAY_SYSTEM, _day_facts(day), smart=False, max_tokens=1200))
    if not result.ok:
        return {**_off(result), "date": day["date"], "tasks": []}
    return {"available": True, "message": "", "date": day["date"], "tasks": clean_tasks((result.data or {}).get("tasks"), day)}


# --- delay findings and a summary --------------------------------------------------------------------------------

def find_delays(view, day, today) -> list:
    """Plain checks on the programme. Each is {"level": stop|check|note, "text", "activity_id"}."""
    out = []
    rows = {a["id"]: a for a in view["activities"]}

    def add(level, text, aid=None):
        out.append({"level": level, "text": text, "activity_id": aid})

    for a in rows.values():
        who = ("%s %s" % (a["code"], a["name"])).strip()
        if a["state"] == "late":
            add("stop", "%s should have finished on %s and is %s%% done." % (who, a["planned_finish"], a["actual_percent"]), a["id"])
        elif a["state"] == "behind":
            add("check", "%s is %s%% done against %s%% planned." % (who, a["actual_percent"], a["planned_percent"]), a["id"])
        pred = rows.get(a["depends_on_id"])
        if pred and a["actual_percent"] < 100 and pred["slip_days"] > 0 and a["state"] != "late":
            add("check", "%s waits on %s, which is forecast %d days late, so it will start late too." % (who, pred["code"] or pred["name"], pred["slip_days"]), a["id"])
    for a in day["soon"]:
        pred = rows.get(rows.get(a["id"], {}).get("depends_on_id"))
        if pred and pred["actual_percent"] < 100:
            add("check", "%s %s starts in %d days but %s is only %s%% done." % (a["code"], a["name"], a["starts_in"], pred["code"] or pred["name"], pred["actual_percent"]), a["id"])
    for a in day["today"]:
        stale = a["updated_on"]
        if _d(stale) and (today - _d(stale)).days >= 7:
            add("note", "%s %s has had no progress reported since %s." % (a["code"], a["name"], stale), a["id"])
        elif not stale and a["planned_percent"] > 0 and a["actual_percent"] == 0:
            add("note", "%s %s is running but no progress has been reported." % (a["code"], a["name"]), a["id"])
    s = view["summary"]
    if s["slip_days"] > 0:
        add("stop" if s["slip_days"] >= 14 else "check", "The project is forecast to finish on %s, %d days after the planned %s." % (s["forecast_finish"], s["slip_days"], s["planned_finish"]))
    order = {"stop": 0, "check": 1, "note": 2}
    return sorted(out, key=lambda f: order[f["level"]])


def _plan_facts(view) -> str:
    s = view["summary"]
    rows = ["Project %s %s. Done %s%% against %s%% planned; planned finish %s, forecast %s (%d days %s)." % (
        view["job"]["number"], view["job"]["name"], s["actual_percent"], s["planned_percent"], s["planned_finish"] or "?",
        s["forecast_finish"] or "?", abs(s["slip_days"]), "late" if s["slip_days"] > 0 else "early or on time"), "Activities:"]
    for a in view["activities"]:
        rows.append("- %s %s | %s to %s | %s | %s%% done, %s%% planned | forecast %s | after %s | %s" % (
            a["code"], a["name"], a["planned_start"], a["planned_finish"], a["state"], a["actual_percent"], a["planned_percent"],
            a["forecast_finish"] or "?", a["depends_on"] or "-", a["progress_from"]))
    return "\n".join(rows)


@router.get("/api/ai/planning/jobs/{job_id}/review")
def review_plan(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    view = schedule_view(db, client.id, job)
    today = date.today()
    findings = find_delays(view, schedule_day(db, client.id, job, today), today)
    out = {"available": False, "reason": "", "message": "", "summary": "", "findings": findings, "progress": view["summary"]}
    if not view["activities"]:
        out["message"] = "There is no programme on this project yet."
        return out
    prompt = "%s\n\nChecks already worked out:\n%s" % (_plan_facts(view), "\n".join("- [%s] %s" % (f["level"], f["text"]) for f in findings) or "- none")
    result = guard.run_feature(db, request, client, KEY_REVIEW, "Programme review %s" % job.number, job.number or "",
                               lambda: ask(REVIEW_SYSTEM, prompt, smart=False, max_tokens=500))
    if result.ok:
        out.update(available=True, summary=result.text)
    else:
        out.update(reason=result.reason, message=result.message)
    return out


@router.post("/api/ai/planning/jobs/{job_id}/ask")
def ask_plan(job_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    question = str(body.get("question") or "").strip()[:500]
    if not question:
        raise HTTPException(400, "Type a question about the plan.")
    view = schedule_view(db, client.id, job)
    if not view["activities"]:
        return {"available": True, "answer": "There is no programme on this project yet.", "message": ""}
    prompt = "%s\n\nQuestion: %s" % (_plan_facts(view), question)
    result = guard.run_feature(db, request, client, KEY_ASK, "Plan question %s" % job.number, job.number or "",
                               lambda: ask(ASK_SYSTEM, prompt, smart=False, max_tokens=600))
    if not result.ok:
        return {**_off(result), "answer": ""}
    return {"available": True, "answer": result.text, "message": ""}
