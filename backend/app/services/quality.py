"""The rules and workings behind the quality endpoints."""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_

from app import models

from app.constants.quality import (
    CUBE_AGES, CUBE_DECISIONS, CUBE_SPREAD, NCR_LABELS, NCR_ROOT_CAUSE_FROM, QC_CHECKLISTS, QC_WORK_TYPES,
)
from app.core.audit import log_audit


def grade_fck(grade):
    m = re.search(r"(\d{2,3})", grade or "")
    return float(m.group(1)) if m else 25.0


def _qc_job(db, client_id, job_id):
    return job_or_404(db, client_id, job_id)


def job_names(db, client_id, ids):
    """{job id: (project name, site address)} for the projects a list refers to."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = db.query(models.DBJob.id, models.DBJob.name, models.DBJob.site_address).filter(
        models.DBJob.client_id == client_id, models.DBJob.id.in_(ids)).all()
    return {r[0]: (r[1] or "", r[2] or "") for r in rows}


def unique_number(db, model, client_id, stem):
    """The next INS-0001 / CT-0001 / NCR-0001: one past the highest in use, never a count - a
    count hands out a number twice once a record has been deleted."""
    best = 0
    for (n,) in db.query(model.number).filter(model.client_id == client_id).all():
        m = re.search(r"(\d+)$", n or "")
        if m:
            best = max(best, int(m.group(1)))
    return "%s-%04d" % (stem, best + 1)


def qc_log(db, client_id, action, kind, rec, details, actor, request=None, name=""):
    """One line of the trail for a status change. Added to the session; the caller commits."""
    log_audit(db, client_id, action, entity_type=kind, entity_id=rec.id,
              entity_name=name or getattr(rec, "number", "") or getattr(rec, "name", "") or "",
              details=(details or "")[:1000], request=request, user_name=actor)


def history(db, client_id, kind, rec_id):
    rows = db.query(models.DBAuditLog).filter(
        models.DBAuditLog.client_id == client_id, models.DBAuditLog.entity_type == kind,
        models.DBAuditLog.entity_id == rec_id).order_by(models.DBAuditLog.id.desc()).limit(200).all()
    return [{"at": str(r.created_at or "")[:19], "who": r.user_name or "", "action": r.action or "",
             "details": r.details or ""} for r in rows]


def clean_date(value, what="date", required=False):
    v = (value or "").strip()[:10]
    if not v:
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return ""
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "The %s as a date: 2026-09-30." % what)
    return v


# ---- checklists --------------------------------------------------------------------------------

def checklist_templates(db, client_id, job_id=0, manage=False):
    """Every checklist this company can start from: the standard ones, with its own - for the whole
    company or for this project - replacing a standard list of the same name. `manage` also returns
    the switched-off ones and every project's, for the screen that edits them."""
    out = {}
    for name, items in QC_CHECKLISTS.items():
        out[name] = {"id": None, "name": name, "work_type": QC_WORK_TYPES.get(name, ""), "builtin": True,
                     "job_id": None, "spec_ref": "", "is_active": True,
                     "items": [{"item": x, "criteria": ""} for x in items]}
    rows = db.query(models.DBQcChecklist).filter(models.DBQcChecklist.client_id == client_id).order_by(
        models.DBQcChecklist.id).all()
    if manage:
        extra = [checklist_dict(c) for c in rows]
        shadowed = {c["name"] for c in extra if c["job_id"] is None and c["is_active"]}
        return [t for n, t in out.items() if n not in shadowed] + extra
    # The company's own lists first, then this project's, so a project's list wins.
    for c in [c for c in rows if c.job_id is None] + [c for c in rows if job_id and c.job_id == job_id]:
        if not c.is_active:
            out.pop(c.name, None)
        else:
            out[c.name] = checklist_dict(c)
    return list(out.values())


def checklist_dict(c):
    try:
        items = json.loads(c.items or "[]")
    except ValueError:
        items = []
    return {"id": c.id, "name": c.name, "work_type": c.work_type or "", "builtin": False, "job_id": c.job_id,
            "spec_ref": c.spec_ref or "", "is_active": bool(c.is_active), "items": items}


def clean_checklist_items(items):
    out = []
    for x in items or []:
        text = ((x.get("item") if isinstance(x, dict) else str(x)) or "").strip()
        if not text:
            continue
        out.append({"item": text[:200], "criteria": ((x.get("criteria") if isinstance(x, dict) else "") or "").strip()[:300]})
    return out


# ---- inspections -------------------------------------------------------------------------------

def inspection_dict(i, names=None):
    try:
        items = json.loads(i.items or "[]")
    except ValueError:
        items = []
    bad = [x for x in items if x.get("result") == "not ok"]
    approval = i.approval_status or ""
    project, site = (names or {}).get(i.job_id, ("", ""))
    return {"id": i.id, "job_id": i.job_id, "project": project, "site": site, "number": i.number,
            "checklist": i.checklist, "location": i.location or "", "inspected_on": i.inspected_on or "",
            "inspected_by": i.inspected_by or "", "witnessed_by": i.witnessed_by or "",
            "items": items, "result": i.result, "remarks": i.remarks or "",
            "result_label": {"OPEN": "Pending", "PASSED": "Passed", "FAILED": "Failed"}.get(i.result, i.result),
            "failed_items": len(bad), "checked": len([x for x in items if x.get("result")]),
            "building": i.building or "", "floor_area": i.floor_area or "", "work_activity": i.work_activity or "",
            "assigned_to": i.assigned_to or "", "measurements": i.measurements or "",
            "approval_status": approval, "submitted_by": i.submitted_by or "", "submitted_on": i.submitted_on or "",
            "approved_by": i.approved_by or "", "approved_on": i.approved_on or "", "return_note": i.return_note or "",
            "reinspection_of": i.reinspection_of,
            # Editable until it is waiting on somebody's decision, or decided.
            "editable": i.result == "OPEN" and approval != "submitted"}


def _clean_items(items):
    out = []
    for x in items or []:
        text = (x.get("item") or "").strip() if isinstance(x, dict) else str(x).strip()
        if not text:
            continue
        d = x if isinstance(x, dict) else {}
        res = d.get("result") or ""
        out.append({"item": text[:200], "criteria": (d.get("criteria") or "").strip()[:300],
                    "result": res if res in ("ok", "not ok", "na") else "",
                    "measured": (d.get("measured") or "").strip()[:100], "remark": (d.get("remark") or "")[:300]})
    return out


def _inspection_or_404(db, client_id, iid):
    i = db.query(models.DBInspection).filter(models.DBInspection.id == iid,
                                             models.DBInspection.client_id == client_id).first()
    if not i:
        raise HTTPException(404, "Inspection not found")
    return i


def inspection_query(db, client_id, job_id=0, q="", status="", date_from="", date_to=""):
    M = models.DBInspection
    query = db.query(M).filter(M.client_id == client_id)
    if job_id:
        query = query.filter(M.job_id == job_id)
    if status:
        s = status.upper()
        if s == "PENDING":
            s = "OPEN"
        if s in ("OPEN", "PASSED", "FAILED"):
            query = query.filter(M.result == s)
        elif s == "SUBMITTED":
            query = query.filter(M.approval_status == "submitted")
    if date_from:
        query = query.filter(M.inspected_on >= date_from[:10])
    if date_to:
        query = query.filter(M.inspected_on <= date_to[:10])
    if q.strip():
        like = "%" + q.strip() + "%"
        query = query.filter(or_(M.number.ilike(like), M.checklist.ilike(like), M.location.ilike(like),
                                 M.work_activity.ilike(like), M.inspected_by.ilike(like),
                                 M.assigned_to.ilike(like), M.building.ilike(like)))
    return query


INSPECTION_SORTS = {"number": "number", "date": "inspected_on", "result": "result", "checklist": "checklist",
                    "inspector": "inspected_by", "location": "location"}


def sort_clause(model, sorts, key, direction):
    col = getattr(model, sorts.get(key or "", "id"))
    return col.asc() if (direction or "desc").lower() == "asc" else col.desc()


# ---- concrete cubes ----------------------------------------------------------------------------

def parse_ages(text):
    ages = []
    for x in re.findall(r"\d+", text or ""):
        n = int(x)
        if 1 <= n <= 365 and n not in ages:
            ages.append(n)
    return sorted(ages)


def criteria_map(db, client_id, job_ids):
    """{(job, grade, age): row} of the criteria in force."""
    job_ids = {j for j in job_ids if j}
    if not job_ids:
        return {}
    rows = db.query(models.DBQcCriteria).filter(
        models.DBQcCriteria.client_id == client_id, models.DBQcCriteria.job_id.in_(job_ids),
        models.DBQcCriteria.is_active == True).all()  # noqa: E712
    return {(r.job_id, (r.grade or "").upper(), r.age_days): r for r in rows}


def evaluate(vals, crit):
    """Read the strengths against the criteria in force. No criteria is not a pass: it is a result
    nobody has yet said what to compare with."""
    if not crit or not (crit.min_mean or crit.min_single):
        return "no_criteria", 0.0, 0.0, ""
    avg = sum(vals) / len(vals) if vals else 0.0
    ok = avg >= (crit.min_mean or 0) and all(v >= (crit.min_single or 0) for v in vals)
    return ("meets" if ok else "below"), crit.min_mean or 0.0, crit.min_single or 0.0, crit.standard or ""


def schedule_for(s, cmap):
    ages = parse_ages(s.test_ages)
    if not ages:
        ages = sorted(a for (j, g, a) in cmap if j == s.job_id and g == (s.grade or "").upper()) or list(CUBE_AGES)
    return ages


def _verdict_text(evaluation, avg, cmin, csingle, ref):
    if evaluation == "meets":
        return "meets the criteria (%s N/mm2%s)" % (cmin, ", no cube under %s" % csingle if csingle else "")
    if evaluation == "below":
        return "below the criteria (needs %s N/mm2%s)" % (cmin, ", no cube under %s" % csingle if csingle else "")
    return "no approved criteria set for this grade and age"


def cube_verdict(s, results, cmap=None):
    """What the crushed cubes say, age by age, against the criteria in force."""
    cmap = cmap or {}
    out = {}
    for r in results:
        vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", r.strengths or "")]
        avg = round(sum(vals) / len(vals), 2) if vals else 0.0
        spread_ok = all(abs(v - avg) <= CUBE_SPREAD * avg for v in vals) if vals and avg else True
        if r.evaluation:
            ev, cmin, csingle, ref = r.evaluation, r.criteria_min or 0.0, r.criteria_single or 0.0, r.criteria_ref or ""
        else:
            ev, cmin, csingle, ref = evaluate(vals, cmap.get((s.job_id, (s.grade or "").upper(), r.age_days)))
        actual_age = None
        try:
            actual_age = (datetime.strptime(r.tested_on[:10], "%Y-%m-%d").date()
                          - datetime.strptime(s.cast_on[:10], "%Y-%m-%d").date()).days
        except (ValueError, TypeError):
            pass
        out[r.age_days] = {"age_days": r.age_days, "tested_on": r.tested_on or "", "strengths": vals,
                           "average": avg, "evaluation": ev, "ok": ev == "meets", "failed": ev == "below",
                           "spread_ok": spread_ok, "verdict": _verdict_text(ev, avg, cmin, csingle, ref),
                           "criteria_min": cmin, "criteria_single": csingle, "criteria_ref": ref,
                           "lab": r.lab or "", "remarks": r.remarks or "", "flagged": bool(r.flagged),
                           "actual_age": actual_age, "recorded_by": r.recorded_by_name or "", "id": r.id}
    return out


def cube_dict(db, s, results=None, cmap=None):
    if results is None:
        results = db.query(models.DBCubeResult).filter(models.DBCubeResult.set_id == s.id).order_by(
            models.DBCubeResult.age_days).all()
    if cmap is None:
        cmap = criteria_map(db, s.client_id, [s.job_id])
    v = cube_verdict(s, results, cmap)
    ages = schedule_for(s, cmap)
    today = date.today()
    try:
        cast = datetime.strptime((s.cast_on or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        cast = None
    due, schedule = [], []
    for age in sorted(set(ages) | set(v)):
        on = (cast + timedelta(days=age)) if cast else None
        done = age in v
        state = "tested" if done else ("overdue" if on and on < today else "due" if on and on == today else "upcoming")
        schedule.append({"age_days": age, "due_on": on.isoformat() if on else "", "state": state})
        if not done and on:
            due.append({"age_days": age, "due_on": on.isoformat(), "overdue": on < today, "today": on == today})
    res = list(v.values())
    stale = len(res) > (s.reviewed_results or 0)
    decided = s.acceptance in CUBE_DECISIONS and not stale
    reasons = []
    if any(r["failed"] for r in res):
        reasons.append("A result is below its acceptance criteria")
    if any(r["evaluation"] == "no_criteria" for r in res):
        reasons.append("No approved acceptance criteria are set for this grade and age")
    if any(not r["spread_ok"] for r in res):
        reasons.append("A cube is more than 15% off the average of its set (IS 516)")
    if any(r["flagged"] for r in res):
        reasons.append("Flagged for engineering review")
    complete = bool(res) and all(a in v for a in ages)
    if complete and not reasons:
        reasons.append("Every scheduled test is in; the engineer accepts the concrete, not one test")
    needs_review = bool(reasons) and not decided
    if not res:
        status = "awaiting results"
    elif decided:
        status = {"accepted": "accepted", "conditional": "accepted with conditions", "rejected": "rejected"}[s.acceptance]
    elif any(r["failed"] for r in res):
        status = "below grade"
    elif any(r["evaluation"] == "no_criteria" for r in res):
        status = "criteria not set"
    elif needs_review:
        status = "for engineering review"
    else:
        status = "awaiting results"
    final = res[-1] if res else None
    return {"id": s.id, "job_id": s.job_id, "number": s.number, "cast_on": s.cast_on or "",
            "location": s.location or "", "grade": s.grade, "fck": s.fck, "slump_mm": s.slump_mm or 0,
            "supplier": s.supplier or "", "docket": s.docket or "", "cast_by": s.cast_by or "",
            "remarks": s.remarks or "", "pour_ref": s.pour_ref or "", "cube_ids": s.cube_ids or "",
            "test_ages": ages, "schedule": schedule, "results": res, "due": due,
            "acceptance": s.acceptance if decided else "", "acceptance_note": s.acceptance_note if decided else "",
            "accepted_by": s.accepted_by if decided else "", "accepted_on": s.accepted_on if decided else "",
            "needs_review": needs_review, "review_reasons": reasons if needs_review else [],
            "counted_below": len([r for r in res if r["failed"]]) if (not decided or s.acceptance == "rejected") else 0,
            "latest_average": final["average"] if final else None, "status": status}


def cube_dicts(db, client_id, sets):
    """Many sets at once - the results and criteria are fetched once, not once per set."""
    sets = list(sets)
    if not sets:
        return []
    ids = [s.id for s in sets]
    by_set = {}
    for r in db.query(models.DBCubeResult).filter(models.DBCubeResult.set_id.in_(ids)).order_by(
            models.DBCubeResult.age_days).all():
        by_set.setdefault(r.set_id, []).append(r)
    cmap = criteria_map(db, client_id, [s.job_id for s in sets])
    return [cube_dict(db, s, by_set.get(s.id, []), cmap) for s in sets]


def criteria_dict(c):
    return {"id": c.id, "job_id": c.job_id, "grade": c.grade, "age_days": c.age_days, "min_mean": c.min_mean,
            "min_single": c.min_single or 0, "standard": c.standard or "", "approved_by": c.approved_by or "",
            "approved_on": c.approved_on or "", "is_active": bool(c.is_active)}


# ---- non-conformances --------------------------------------------------------------------------

def ncr_dict(n, names=None):
    today = date.today().isoformat()
    project, site = (names or {}).get(n.job_id, ("", ""))
    status = n.status or "OPEN"
    return {"id": n.id, "job_id": n.job_id, "project": project, "number": n.number, "raised_on": n.raised_on or "",
            "raised_by": n.raised_by or "", "location": n.location or "", "description": n.description or "",
            "severity": n.severity or "Minor", "responsible": n.responsible or "",
            "corrective_action": n.corrective_action or "", "target_date": n.target_date or "",
            "source_type": n.source_type or "", "source_id": n.source_id, "source_ref": n.source_ref or "",
            "status": status, "status_label": NCR_LABELS.get(status, status),
            "closed_on": n.closed_on or "", "closure_note": n.closure_note or "", "closed_by": n.closed_by or "",
            "root_cause": n.root_cause or "", "assigned_by": n.assigned_by or "", "assigned_on": n.assigned_on or "",
            "corrective_done": n.corrective_done or "", "corrective_on": n.corrective_on or "",
            "verification_result": n.verification_result or "", "verification_note": n.verification_note or "",
            "verified_by": n.verified_by or "", "verified_on": n.verified_on or "",
            "reinspection_ref": n.reinspection_ref or "",
            "needs_root_cause": (n.severity or "") in NCR_ROOT_CAUSE_FROM and not (n.root_cause or "").strip(),
            "overdue": status != "CLOSED" and bool(n.target_date) and n.target_date < today}


def ncr_query(db, client_id, job_id=0, q="", status="", date_from="", date_to="", severity=""):
    M = models.DBNcr
    query = db.query(M).filter(M.client_id == client_id)
    if job_id:
        query = query.filter(M.job_id == job_id)
    s = (status or "").upper()
    if s == "ACTIVE" or s == "NOT_CLOSED":
        query = query.filter(M.status != "CLOSED")
    elif s == "OVERDUE":
        query = query.filter(M.status != "CLOSED", M.target_date != "", M.target_date < date.today().isoformat())
    elif s:
        query = query.filter(M.status == s)
    if severity:
        query = query.filter(M.severity == severity)
    if date_from:
        query = query.filter(M.raised_on >= date_from[:10])
    if date_to:
        query = query.filter(M.raised_on <= date_to[:10])
    if q.strip():
        like = "%" + q.strip() + "%"
        query = query.filter(or_(M.number.ilike(like), M.location.ilike(like), M.description.ilike(like),
                                 M.responsible.ilike(like)))
    return query


NCR_SORTS = {"number": "number", "raised": "raised_on", "due": "target_date", "severity": "severity",
             "status": "status", "location": "location"}


def ncr_or_404(db, client_id, nid):
    n = db.query(models.DBNcr).filter(models.DBNcr.id == nid, models.DBNcr.client_id == client_id).first()
    if not n:
        raise HTTPException(404, "NCR not found")
    return n


def cube_or_404(db, client_id, sid):
    s = db.query(models.DBCubeSet).filter(models.DBCubeSet.id == sid, models.DBCubeSet.client_id == client_id).first()
    if not s:
        raise HTTPException(404, "Cube set not found")
    return s


def page_of(total, page, size):
    size = max(0, min(int(size or 0), 200))
    page = max(1, int(page or 1))
    return page, size, ((page - 1) * size if size else 0)


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.projects import job_or_404
