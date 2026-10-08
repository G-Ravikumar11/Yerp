"""The rules and workings behind the quality endpoints."""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models

from app.constants.quality import CUBE_AGES, EARLY_SHARE


def grade_fck(grade):
    m = re.search(r"(\d{2,3})", grade or "")
    return float(m.group(1)) if m else 25.0


def _qc_job(db, client_id, job_id):
    return job_or_404(db, client_id, job_id)


def inspection_dict(i):
    try:
        items = json.loads(i.items or "[]")
    except ValueError:
        items = []
    bad = [x for x in items if x.get("result") == "not ok"]
    return {"id": i.id, "job_id": i.job_id, "number": i.number, "checklist": i.checklist,
            "location": i.location or "", "inspected_on": i.inspected_on or "",
            "inspected_by": i.inspected_by or "", "witnessed_by": i.witnessed_by or "",
            "items": items, "result": i.result, "remarks": i.remarks or "",
            "failed_items": len(bad), "checked": len([x for x in items if x.get("result")])}


def _clean_items(items):
    out = []
    for x in items or []:
        text = (x.get("item") or "").strip() if isinstance(x, dict) else str(x).strip()
        if not text:
            continue
        res = (x.get("result") or "") if isinstance(x, dict) else ""
        out.append({"item": text[:200], "result": res if res in ("ok", "not ok", "na") else "",
                    "remark": ((x.get("remark") or "") if isinstance(x, dict) else "")[:300]})
    return out


def _inspection_or_404(db, client_id, iid):
    i = db.query(models.DBInspection).filter(models.DBInspection.id == iid,
                                             models.DBInspection.client_id == client_id).first()
    if not i:
        raise HTTPException(404, "Inspection not found")
    return i


def cube_verdict(s, results):
    """What the crushed cubes say, age by age."""
    out = {}
    for r in results:
        vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", r.strengths or "")]
        avg = round(sum(vals) / len(vals), 2) if vals else 0.0
        # IS 516: a cube more than 15% off the set's average makes the set doubtful.
        spread_ok = all(abs(v - avg) <= 0.15 * avg for v in vals) if vals and avg else True
        if r.age_days >= 28:
            ok = avg >= (s.fck or 0)
            verdict = "meets %s" % s.grade if ok else "below %s" % s.grade
        else:
            want = round(EARLY_SHARE * (s.fck or 0), 1)
            ok = avg >= want
            verdict = "on course" if ok else "low for %d days (expected about %s)" % (r.age_days, want)
        out[r.age_days] = {"age_days": r.age_days, "tested_on": r.tested_on or "", "strengths": vals,
                           "average": avg, "ok": ok, "spread_ok": spread_ok, "verdict": verdict,
                           "lab": r.lab or ""}
    return out


def cube_dict(db, s):
    results = db.query(models.DBCubeResult).filter(models.DBCubeResult.set_id == s.id).order_by(
        models.DBCubeResult.age_days).all()
    v = cube_verdict(s, results)
    due = []
    today = date.today()
    try:
        cast = datetime.strptime((s.cast_on or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        cast = None
    for age in CUBE_AGES:
        if age not in v and cast:
            on = cast + timedelta(days=age)
            due.append({"age_days": age, "due_on": on.isoformat(), "overdue": on < today, "today": on == today})
    final = v.get(28)
    return {"id": s.id, "job_id": s.job_id, "number": s.number, "cast_on": s.cast_on or "",
            "location": s.location or "", "grade": s.grade, "fck": s.fck, "slump_mm": s.slump_mm or 0,
            "supplier": s.supplier or "", "docket": s.docket or "", "cast_by": s.cast_by or "",
            "results": list(v.values()), "due": due,
            "status": ("below grade" if final and not final["ok"] else "meets grade" if final
                       else "awaiting results")}


def ncr_dict(n):
    today = date.today().isoformat()
    return {"id": n.id, "job_id": n.job_id, "number": n.number, "raised_on": n.raised_on or "",
            "raised_by": n.raised_by or "", "location": n.location or "", "description": n.description or "",
            "severity": n.severity or "Minor", "responsible": n.responsible or "",
            "corrective_action": n.corrective_action or "", "target_date": n.target_date or "",
            "source_type": n.source_type or "", "source_id": n.source_id, "status": n.status,
            "closed_on": n.closed_on or "", "closure_note": n.closure_note or "", "closed_by": n.closed_by or "",
            "overdue": n.status == "OPEN" and bool(n.target_date) and n.target_date < today}


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.projects import job_or_404
