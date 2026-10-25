"""The quality endpoints: inspections, concrete cube tests and non-conformances.

Who may do what - the rule is enforced here, not on the screen:
  site.record   writes the record: starts and edits an inspection, submits it, asks for a reinspection,
                registers cubes, enters results, flags one for review, raises an NCR, records the
                corrective work and asks for it to be verified.
  site.signoff  decides: approves or returns an inspection, accepts or rejects concrete, assigns an NCR,
                verifies and closes it, and keeps the checklists and acceptance criteria.
Every change of status is written to the audit trail.
"""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.documents import form_pdf
from app import models
from app.db import get_db, get_read_db

from app.constants.quality import CUBE_DECISIONS, NCR_ROOT_CAUSE_FROM, NCR_SEVERITIES
from app.core.auth import require_erp_read, wo_actor
from app.core.notifications import notify
from app.core.sheets import sheet_response
from app.documents.forms import _field_doc, _job_line, _pre, form_pdf_response
from app.schemas.quality import (
    ChecklistIn, CriteriaIn, CubeDecisionIn, CubeResultIn, CubeSetIn, InspectionIn, NcrAssignIn, NcrCloseIn,
    NcrIn, NcrVerifyIn, NcrWorkIn, NoteIn, RegisterInspectionIn,
)
from app.services.quality import (
    INSPECTION_SORTS, NCR_SORTS,
    _clean_items, _inspection_or_404, _qc_job,
    checklist_dict, checklist_templates, clean_checklist_items, clean_date,
    criteria_dict, criteria_map, cube_dict, cube_dicts, cube_or_404, evaluate, grade_fck, history,
    inspection_dict, inspection_query, job_names, ncr_dict, ncr_or_404, ncr_query, page_of, parse_ages,
    qc_log, schedule_for, sort_clause, unique_number,
)


router = APIRouter()


def _today():
    return date.today().isoformat()


# ---- the dashboard ---------------------------------------------------------------------------

def _all_cubes(db, client_id, job_id=0):
    q = db.query(models.DBCubeSet).filter(models.DBCubeSet.client_id == client_id)
    if job_id:
        q = q.filter(models.DBCubeSet.job_id == job_id)
    return cube_dicts(db, client_id, q.order_by(models.DBCubeSet.id.desc()).all())


def _cube_counts(rows):
    pending = [d for r in rows for d in r["due"] if d["overdue"] or d["today"]]
    return {"to_crush": len(pending), "overdue": len([d for d in pending if d["overdue"]]),
            "below_grade": sum(r["counted_below"] for r in rows),
            "for_review": len([r for r in rows if r["needs_review"]])}


@router.get("/api/qc/summary")
def qc_summary(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    """The four numbers at the top of the page, from what is stored, for one project or all of them."""
    client = require_erp_read(request, db)
    M = models.DBInspection
    failed = db.query(M).filter(M.client_id == client.id, M.result == "FAILED")
    waiting = db.query(M).filter(M.client_id == client.id, M.result == "OPEN", M.approval_status == "submitted")
    if job_id:
        failed, waiting = failed.filter(M.job_id == job_id), waiting.filter(M.job_id == job_id)
    cubes = _cube_counts(_all_cubes(db, client.id, job_id))
    return {"inspections_failed": failed.count(), "inspections_awaiting_approval": waiting.count(),
            "cubes_to_crush": cubes["to_crush"], "cubes_overdue": cubes["overdue"],
            "below_grade": cubes["below_grade"], "cubes_for_review": cubes["for_review"],
            "ncrs_open": ncr_query(db, client.id, job_id, status="not_closed").count(),
            "ncrs_overdue": ncr_query(db, client.id, job_id, status="overdue").count()}


# ---- checklists and criteria -----------------------------------------------------------------

@router.get("/api/qc/checklists")
def qc_checklists(request: Request, job_id: int = 0, manage: bool = False, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    templates = checklist_templates(db, client.id, job_id, manage=manage)
    return {"checklists": {t["name"]: [x["item"] for x in t["items"]] for t in templates if t["is_active"]},
            "templates": templates}


def _checklist_fields(body):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "Give the checklist a name.")
    items = clean_checklist_items(body.items)
    if not items:
        raise HTTPException(400, "A checklist needs at least one item to check.")
    return name[:120], items


def _checklist_or_404(db, client_id, cid):
    c = db.query(models.DBQcChecklist).filter(models.DBQcChecklist.id == cid,
                                              models.DBQcChecklist.client_id == client_id).first()
    if not c:
        raise HTTPException(404, "Checklist not found")
    return c


@router.post("/api/qc/checklists")
def create_checklist(body: ChecklistIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    name, items = _checklist_fields(body)
    if body.job_id:
        _qc_job(db, client.id, body.job_id)
    dup = db.query(models.DBQcChecklist).filter(
        models.DBQcChecklist.client_id == client.id, models.DBQcChecklist.name == name,
        models.DBQcChecklist.job_id == (body.job_id or None)).first()
    if dup:
        raise HTTPException(409, "There is already a checklist called \"%s\" here - edit that one." % name)
    c = models.DBQcChecklist(client_id=client.id, job_id=body.job_id or None, name=name,
                             work_type=(body.work_type or "").strip()[:60], spec_ref=(body.spec_ref or "").strip()[:200],
                             items=json.dumps(items), is_active=body.is_active is not False, created_by=actor)
    db.add(c)
    db.flush()
    qc_log(db, client.id, "qc.checklist.created", "qc_checklist", c, "%s, %d items" % (name, len(items)), actor, request)
    db.commit()
    return {"checklist": checklist_dict(c)}


@router.put("/api/qc/checklists/{cid}")
def update_checklist(cid: int, body: ChecklistIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    c = _checklist_or_404(db, client.id, cid)
    name, items = _checklist_fields(body)
    clash = db.query(models.DBQcChecklist).filter(
        models.DBQcChecklist.client_id == client.id, models.DBQcChecklist.name == name,
        models.DBQcChecklist.job_id == (body.job_id or None), models.DBQcChecklist.id != c.id).first()
    if clash:
        raise HTTPException(409, "There is already a checklist called \"%s\" here." % name)
    c.name, c.items, c.job_id = name, json.dumps(items), body.job_id or None
    c.work_type, c.spec_ref = (body.work_type or "").strip()[:60], (body.spec_ref or "").strip()[:200]
    c.is_active = body.is_active is not False
    qc_log(db, client.id, "qc.checklist.updated", "qc_checklist", c, "%s, %d items" % (name, len(items)), actor, request)
    db.commit()
    return {"checklist": checklist_dict(c)}


@router.delete("/api/qc/checklists/{cid}")
def delete_checklist(cid: int, request: Request, db: Session = Depends(get_db)):
    """An inspection already started keeps its own copy of the items, so removing a list changes nothing past."""
    client, _, actor = wo_actor(request, db, "site.signoff")
    c = _checklist_or_404(db, client.id, cid)
    qc_log(db, client.id, "qc.checklist.deleted", "qc_checklist", c, c.name, actor, request)
    db.delete(c)
    db.commit()
    return {"message": "Checklist removed"}


@router.get("/api/qc/criteria")
def list_criteria(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBQcCriteria).filter(models.DBQcCriteria.client_id == client.id)
    if job_id:
        q = q.filter(models.DBQcCriteria.job_id == job_id)
    rows = q.order_by(models.DBQcCriteria.job_id, models.DBQcCriteria.grade, models.DBQcCriteria.age_days).all()
    names = job_names(db, client.id, [r.job_id for r in rows])
    return {"criteria": [dict(criteria_dict(r), project=names.get(r.job_id, ("", ""))[0]) for r in rows]}


def _criteria_fields(body):
    grade = (body.grade or "").strip().upper()
    if not re.match(r"^M\d{2,3}$", grade):
        raise HTTPException(400, "The grade as it is written: M20, M25, M30...")
    if not 1 <= body.age_days <= 365:
        raise HTTPException(400, "The age in days the test is made at - 7, 28, 56...")
    if not 0 < body.min_mean <= 150:
        raise HTTPException(400, "The strength the average must reach, in N/mm2.")
    single = body.min_single or 0
    if single < 0 or single > body.min_mean:
        raise HTTPException(400, "The lowest single cube allowed cannot be above the average required.")
    if not (body.standard or "").strip():
        raise HTTPException(400, "Say where the criterion comes from - the specification clause or the standard.")
    return grade, single


def _criteria_log(db, client_id, action, c, actor, request):
    qc_log(db, client_id, action, "qc_criteria", c,
           "%s at %d days: average %s N/mm2, single %s (%s)" % (c.grade, c.age_days, c.min_mean, c.min_single or 0, c.standard),
           actor, request, name="%s @ %dd" % (c.grade, c.age_days))


@router.post("/api/qc/criteria")
def create_criteria(body: CriteriaIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    _qc_job(db, client.id, body.job_id)
    grade, single = _criteria_fields(body)
    dup = db.query(models.DBQcCriteria).filter(
        models.DBQcCriteria.client_id == client.id, models.DBQcCriteria.job_id == body.job_id,
        models.DBQcCriteria.grade == grade, models.DBQcCriteria.age_days == body.age_days,
        models.DBQcCriteria.is_active == True).first()  # noqa: E712
    if dup:
        raise HTTPException(409, "%s at %d days already has its criteria on this project - change that row." % (grade, body.age_days))
    c = models.DBQcCriteria(client_id=client.id, job_id=body.job_id, grade=grade, age_days=body.age_days,
                            min_mean=body.min_mean, min_single=single, standard=body.standard.strip()[:200],
                            approved_by=actor, approved_on=_today())
    db.add(c)
    db.flush()
    _criteria_log(db, client.id, "qc.criteria.set", c, actor, request)
    db.commit()
    return {"criteria": criteria_dict(c)}


def _criteria_or_404(db, client_id, cid):
    c = db.query(models.DBQcCriteria).filter(models.DBQcCriteria.id == cid, models.DBQcCriteria.client_id == client_id).first()
    if not c:
        raise HTTPException(404, "Criteria not found")
    return c


@router.put("/api/qc/criteria/{cid}")
def update_criteria(cid: int, body: CriteriaIn, request: Request, db: Session = Depends(get_db)):
    """Results already recorded keep the criteria they were read against; this changes only what comes next."""
    client, _, actor = wo_actor(request, db, "site.signoff")
    c = _criteria_or_404(db, client.id, cid)
    grade, single = _criteria_fields(body)
    c.grade, c.age_days, c.min_mean, c.min_single = grade, body.age_days, body.min_mean, single
    c.standard, c.approved_by, c.approved_on = body.standard.strip()[:200], actor, _today()
    _criteria_log(db, client.id, "qc.criteria.changed", c, actor, request)
    db.commit()
    return {"criteria": criteria_dict(c)}


@router.delete("/api/qc/criteria/{cid}")
def delete_criteria(cid: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    c = _criteria_or_404(db, client.id, cid)
    _criteria_log(db, client.id, "qc.criteria.removed", c, actor, request)
    db.delete(c)
    db.commit()
    return {"message": "Criteria removed"}


# ---- inspections -----------------------------------------------------------------------------

def _inspection_rows(db, client_id, job_id, q, status, date_from, date_to, sort, dir, page, page_size):
    query = inspection_query(db, client_id, job_id, q, status, date_from, date_to)
    total = query.count()
    M = models.DBInspection
    query = query.order_by(sort_clause(M, INSPECTION_SORTS, sort, dir), M.id.desc())
    page, size, off = page_of(total, page, page_size)
    if size:
        query = query.offset(off).limit(size)
    rows = query.all()
    names = job_names(db, client_id, [r.job_id for r in rows])
    return [inspection_dict(i, names) for i in rows], total, page, size


@router.get("/api/qc/inspections")
def list_inspections(request: Request, job_id: int = 0, q: str = "", status: str = "", date_from: str = "",
                     date_to: str = "", sort: str = "", dir: str = "desc", page: int = 1, page_size: int = 0,
                     db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    rows, total, page, size = _inspection_rows(db, client.id, job_id, q, status, date_from, date_to, sort, dir, page, page_size)
    return {"inspections": rows, "total": total, "page": page, "page_size": size}


@router.get("/api/qc/inspections/{iid}")
def get_inspection(iid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    i = _inspection_or_404(db, client.id, iid)
    d = inspection_dict(i, job_names(db, client.id, [i.job_id]))
    M = models.DBInspection
    again = db.query(M).filter(M.client_id == client.id, M.reinspection_of == i.id).order_by(M.id.desc()).first()
    first = db.query(M).filter(M.id == i.reinspection_of, M.client_id == client.id).first() if i.reinspection_of else None
    d["reinspection_number"] = again.number if again else ""
    d["reinspection_result"] = again.result if again else ""
    d["reinspection_of_number"] = first.number if first else ""
    d["ncrs"] = [{"id": n.id, "number": n.number, "status": n.status} for n in db.query(models.DBNcr).filter(
        models.DBNcr.client_id == client.id, models.DBNcr.source_type == "inspection",
        models.DBNcr.source_id == i.id).all()]
    return {"inspection": d, "history": history(db, client.id, "inspection", i.id)}


@router.post("/api/qc/inspections")
def create_inspection(body: InspectionIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = _qc_job(db, client.id, body.job_id)
    items = body.items
    name = (body.checklist or "").strip()
    if items is None:
        templates = {t["name"]: t for t in checklist_templates(db, client.id, job.id)}
        if name not in templates:
            raise HTTPException(400, "Pick a checklist, or give the items to check.")
        items = [{"item": x["item"], "criteria": x.get("criteria", ""), "result": "", "remark": ""}
                 for x in templates[name]["items"]]
    if not _clean_items(items):
        raise HTTPException(400, "The inspection has nothing to check.")
    on = clean_date(body.inspected_on, "inspection date") or _today()
    if on > _today():
        raise HTTPException(400, "An inspection cannot be dated in the future.")
    i = models.DBInspection(client_id=client.id, job_id=job.id, number=unique_number(db, models.DBInspection, client.id, "INS"),
                            checklist=(name or "Custom")[:120], location=(body.location or "").strip()[:200],
                            inspected_on=on, inspected_by=actor_name, witnessed_by=(body.witnessed_by or "").strip()[:120],
                            items=json.dumps(_clean_items(items)), remarks=(body.remarks or "").strip(),
                            building=(body.building or "").strip()[:120], floor_area=(body.floor_area or "").strip()[:120],
                            work_activity=(body.work_activity or "").strip()[:200],
                            assigned_to=(body.assigned_to or "").strip()[:120], measurements=(body.measurements or "").strip())
    db.add(i)
    db.flush()
    qc_log(db, client.id, "qc.inspection.created", "inspection", i, "%s at %s" % (i.checklist, i.location or job.name), actor_name, request)
    db.commit()
    return {"inspection": inspection_dict(i, job_names(db, client.id, [i.job_id]))}


def _may(request, db, permission):
    """Whether the person asking holds a right - asked, not enforced."""
    try:
        wo_actor(request, db, permission)
        return True
    except HTTPException as exc:
        if exc.status_code == 403:
            return False
        raise


REGISTER_STATUSES = ("Pending", "Passed", "Failed", "Awaiting Approval")


@router.post("/api/qc/inspections/register")
def register_inspection(body: RegisterInspectionIn, request: Request, db: Session = Depends(get_db)):
    """Put an inspection that has been carried out on the record: what was looked at, by whom, what was found and what
    it came to. Recording is for whoever records; a final Passed or Failed is the decision of whoever signs off, so
    anybody else sends it for approval instead. Every check on the form is made here as well as on the screen."""
    client, _, actor = wo_actor(request, db, "site.record")
    job = _qc_job(db, client.id, body.job_id)
    activity = (body.work_activity or "").strip()
    inspector = (body.inspector or "").strip()
    if not activity:
        raise HTTPException(400, "Which activity or work item was inspected?")
    if not inspector:
        raise HTTPException(400, "Who carried out the inspection?")
    on = clean_date(body.inspected_on, "inspection date", required=True)
    if on > _today():
        raise HTTPException(400, "An inspection cannot be dated in the future.")
    status = (body.status or "Pending").strip()
    if status not in REGISTER_STATUSES:
        raise HTTPException(400, "Status is one of: %s." % ", ".join(REGISTER_STATUSES))
    outcome = (body.result or "").strip().title()
    if outcome not in ("", "Pass", "Fail"):
        raise HTTPException(400, "The result is Pass or Fail.")
    name = (body.checklist or "").strip()
    items = body.items
    if items is None:
        templates = {t["name"]: t for t in checklist_templates(db, client.id, job.id)}
        if name not in templates:
            raise HTTPException(400, "Pick a checklist, or give the items to check.")
        items = [{"item": x["item"], "criteria": x.get("criteria", ""), "result": "", "remark": ""} for x in templates[name]["items"]]
    items = _clean_items(items)
    if not items:
        raise HTTPException(400, "The inspection has nothing to check.")
    defects = (body.defects or "").strip()
    bad = [x for x in items if x["result"] == "not ok"]
    unchecked = [x["item"] for x in items if not x["result"]]
    if outcome and unchecked:
        raise HTTPException(409, "Not looked at yet: %s." % "; ".join(unchecked[:3]))
    if outcome == "Pass" and bad:
        raise HTTPException(409, "It cannot pass with a check marked not ok: %s." % bad[0]["item"])
    if outcome == "Fail" and not bad:
        if not defects:
            raise HTTPException(400, "A failed inspection needs the defect found - mark the check that failed, or describe it.")
        items.append({"item": "Defect found", "criteria": "", "result": "not ok", "measured": "", "remark": defects[:300]})
    if status in ("Passed", "Failed", "Awaiting Approval") and not outcome:
        raise HTTPException(400, "Say whether it passed or failed before giving it that status.")
    if (status == "Passed" and outcome != "Pass") or (status == "Failed" and outcome != "Fail"):
        raise HTTPException(409, "The status %s does not match the result %s." % (status, outcome))
    if status in ("Passed", "Failed") and not _may(request, db, "site.signoff"):
        raise HTTPException(403, "Only somebody who signs off site work records a final result - choose Awaiting Approval and it goes to them.")
    # The same inspection sent twice - a double click, a retry - is one record.
    M = models.DBInspection
    twin = db.query(M).filter(M.client_id == client.id, M.job_id == job.id, M.work_activity == activity,
                              M.checklist == (name or "Custom"), M.inspected_on == on, M.inspected_by == inspector,
                              M.created_at >= (datetime.now() - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")).first()
    if twin:
        raise HTTPException(409, "%s was registered a moment ago - it is the same inspection." % twin.number)
    i = M(client_id=client.id, job_id=job.id, number=unique_number(db, M, client.id, "INS"), checklist=(name or "Custom")[:120],
          location=(body.location or "").strip()[:200], inspected_on=on, inspected_by=inspector[:120],
          witnessed_by=(body.witnessed_by or "").strip()[:120], items=json.dumps(items), remarks=defects,
          building=(body.building or "").strip()[:120], floor_area=(body.floor_area or "").strip()[:120],
          work_activity=activity[:200], assigned_to=inspector[:120])
    db.add(i)
    db.flush()
    qc_log(db, client.id, "qc.inspection.registered", "inspection", i, "%s: %s, %s" % (activity, outcome or "no result yet", status), actor, request)
    if status == "Awaiting Approval":
        i.approval_status, i.submitted_by, i.submitted_on = "submitted", actor, _today()
        qc_log(db, client.id, "qc.inspection.submitted", "inspection", i, "%d not ok" % len(bad), actor, request)
    elif status in ("Passed", "Failed"):
        i.result = "PASSED" if status == "Passed" else "FAILED"
        i.approval_status, i.approved_by, i.approved_on = "approved", actor, _today()
        qc_log(db, client.id, "qc.inspection." + i.result.lower(), "inspection", i, "Registered with its result", actor, request)
    db.commit()
    if status == "Awaiting Approval":
        notify(db, client.id, "qc_failed", "%s is waiting for approval" % i.number, "%s at %s, registered by %s." % (activity, i.location or job.name, actor),
               view="quality-view", ref_type="inspection", ref_id=i.id, severity="action")
    elif i.result == "FAILED":
        notify(db, client.id, "qc_failed", "%s failed at %s" % (i.number, i.location or activity), (defects or bad[0]["item"] if bad else defects)[:400],
               view="quality-view", ref_type="inspection", ref_id=i.id, severity="wrong")
    return {"inspection": inspection_dict(i, job_names(db, client.id, [i.job_id]))}


@router.put("/api/qc/inspections/{iid}")
def update_inspection(iid: int, body: InspectionIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.record")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "OPEN":
        raise HTTPException(409, "%s is %s - it is the record now." % (i.number, i.result.lower()))
    if i.approval_status == "submitted":
        raise HTTPException(409, "%s is with the approver - it can be edited again if it is returned." % i.number)
    if body.items is not None:
        items = _clean_items(body.items)
        if not items:
            raise HTTPException(400, "The inspection has nothing to check.")
        i.items = json.dumps(items)
    for f in ("location", "witnessed_by", "remarks", "building", "floor_area", "work_activity", "assigned_to", "measurements"):
        v = getattr(body, f)
        if v is not None:
            setattr(i, f, v.strip())
    if body.inspected_on:
        on = clean_date(body.inspected_on, "inspection date")
        if on > _today():
            raise HTTPException(400, "An inspection cannot be dated in the future.")
        i.inspected_on = on
    qc_log(db, client.id, "qc.inspection.edited", "inspection", i, "", actor, request)
    db.commit()
    return {"inspection": inspection_dict(i, job_names(db, client.id, [i.job_id]))}


def _unlooked(i):
    d = inspection_dict(i)
    return d, [x["item"] for x in d["items"] if not x["result"]]


@router.post("/api/qc/inspections/{iid}/submit")
def submit_inspection(iid: int, request: Request, db: Session = Depends(get_db)):
    """The inspector hands the walked checklist to whoever approves it. Locked until it comes back."""
    client, _, actor = wo_actor(request, db, "site.record")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "OPEN":
        raise HTTPException(409, "%s is already %s." % (i.number, i.result.lower()))
    if i.approval_status == "submitted":
        raise HTTPException(409, "%s is already with the approver." % i.number)
    d, unchecked = _unlooked(i)
    if unchecked:
        raise HTTPException(409, "Not looked at yet: %s." % "; ".join(unchecked[:3]))
    i.approval_status, i.submitted_by, i.submitted_on, i.return_note = "submitted", actor, _today(), ""
    qc_log(db, client.id, "qc.inspection.submitted", "inspection", i,
           "%d item%s not ok" % (d["failed_items"], "" if d["failed_items"] == 1 else "s"), actor, request)
    db.commit()
    notify(db, client.id, "qc_failed", "%s is waiting for approval" % i.number,
           "%s at %s, submitted by %s." % (i.checklist, i.location or "site", actor),
           view="quality-view", ref_type="inspection", ref_id=i.id, severity="action")
    return {"inspection": inspection_dict(i, job_names(db, client.id, [i.job_id]))}


@router.post("/api/qc/inspections/{iid}/return")
def return_inspection(iid: int, body: NoteIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "OPEN" or i.approval_status != "submitted":
        raise HTTPException(409, "%s is not waiting for approval." % i.number)
    if not (body.note or "").strip():
        raise HTTPException(400, "Say what the inspector is to look at again.")
    i.approval_status, i.return_note = "returned", body.note.strip()[:1000]
    qc_log(db, client.id, "qc.inspection.returned", "inspection", i, i.return_note, actor, request)
    db.commit()
    return {"inspection": inspection_dict(i, job_names(db, client.id, [i.job_id]))}


@router.post("/api/qc/inspections/{iid}/close")
def close_inspection(iid: int, request: Request, db: Session = Depends(get_db)):
    """The decision: passed when nothing on it is "not ok", failed otherwise - every item has to have
    been looked at first. A passed reinspection also moves the NCRs raised on the one it re-checks."""
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "OPEN":
        raise HTTPException(409, "%s is already %s." % (i.number, i.result.lower()))
    d, unchecked = _unlooked(i)
    if unchecked:
        raise HTTPException(409, "Not looked at yet: %s." % "; ".join(unchecked[:3]))
    i.result = "FAILED" if d["failed_items"] else "PASSED"
    i.approval_status, i.approved_by, i.approved_on = "approved", actor_name, _today()
    moved = []
    if i.result == "PASSED" and i.reinspection_of:
        for n in db.query(models.DBNcr).filter(models.DBNcr.client_id == client.id, models.DBNcr.source_type == "inspection",
                                               models.DBNcr.source_id == i.reinspection_of,
                                               models.DBNcr.status.in_(("ASSIGNED", "UNDER_CORRECTION"))).all():
            n.status, n.reinspection_ref = "REINSPECTION", i.number
            moved.append(n.number)
            qc_log(db, client.id, "qc.ncr.reinspection", "ncr", n, "Reinspection %s passed - awaiting verification" % i.number, actor_name, request)
    qc_log(db, client.id, "qc.inspection." + i.result.lower(), "inspection", i,
           "%d not ok" % d["failed_items"] + ("; NCRs to verify: " + ", ".join(moved) if moved else ""), actor_name, request)
    db.commit()
    out = {"inspection": inspection_dict(i, job_names(db, client.id, [i.job_id]))}
    if i.result == "FAILED":
        notify(db, client.id, "qc_failed",
               "%s failed at %s" % (i.number, i.location or i.checklist),
               "; ".join(x["item"] for x in d["items"] if x["result"] == "not ok")[:400],
               view="quality-view", ref_type="inspection", ref_id=i.id, severity="wrong")
    return out


@router.post("/api/qc/inspections/{iid}/reinspect")
def request_reinspection(iid: int, request: Request, db: Session = Depends(get_db)):
    """After corrective work: a fresh checklist for the same place, linked to the one that failed."""
    client, _, actor = wo_actor(request, db, "site.record")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "FAILED":
        raise HTTPException(409, "Only a failed inspection is re-inspected - %s is %s." % (i.number, i.result.lower()))
    M = models.DBInspection
    pending = db.query(M).filter(M.client_id == client.id, M.reinspection_of == i.id, M.result == "OPEN").first()
    if pending:
        raise HTTPException(409, "%s is already open as the reinspection of %s." % (pending.number, i.number))
    try:
        old = json.loads(i.items or "[]")
    except ValueError:
        old = []
    fresh = [{"item": x.get("item", ""), "criteria": x.get("criteria", ""), "result": "", "remark": ""} for x in old]
    j = models.DBInspection(client_id=client.id, job_id=i.job_id, number=unique_number(db, M, client.id, "INS"),
                            checklist=i.checklist, location=i.location, inspected_on=_today(), inspected_by=actor,
                            witnessed_by=i.witnessed_by, items=json.dumps(_clean_items(fresh)),
                            remarks="Reinspection of %s." % i.number, building=i.building, floor_area=i.floor_area,
                            work_activity=i.work_activity, assigned_to=i.assigned_to, reinspection_of=i.id)
    db.add(j)
    db.flush()
    qc_log(db, client.id, "qc.inspection.reinspection_requested", "inspection", i, "Reinspection %s opened" % j.number, actor, request)
    qc_log(db, client.id, "qc.inspection.created", "inspection", j, "Reinspection of %s" % i.number, actor, request)
    db.commit()
    return {"inspection": inspection_dict(j, job_names(db, client.id, [j.job_id]))}


# ---- cube tests ------------------------------------------------------------------------------

CUBE_SORTS = {"number": lambda c: c["number"], "cast": lambda c: c["cast_on"], "grade": lambda c: c["grade"],
              "location": lambda c: c["location"].lower(), "status": lambda c: c["status"]}


def _filter_cubes(rows, q, status, date_from, date_to, sort, dir):
    s = (status or "").lower()
    if s == "to_crush":
        rows = [r for r in rows if any(d["overdue"] or d["today"] for d in r["due"])]
    elif s == "below_grade":
        rows = [r for r in rows if r["counted_below"]]
    elif s == "review":
        rows = [r for r in rows if r["needs_review"]]
    elif s:
        rows = [r for r in rows if r["status"] == s.replace("_", " ")]
    if date_from:
        rows = [r for r in rows if r["cast_on"] >= date_from[:10]]
    if date_to:
        rows = [r for r in rows if r["cast_on"] <= date_to[:10]]
    if q.strip():
        n = q.strip().lower()
        rows = [r for r in rows if n in " ".join((r["number"], r["location"], r["grade"], r["pour_ref"], r["cube_ids"],
                                                   r["supplier"], r["docket"])).lower()]
    key = CUBE_SORTS.get(sort or "")
    if key:
        rows = sorted(rows, key=key, reverse=(dir or "").lower() != "asc")
    return rows


@router.get("/api/qc/cubes")
def list_cubes(request: Request, job_id: int = 0, q: str = "", status: str = "", date_from: str = "",
               date_to: str = "", sort: str = "", dir: str = "desc", page: int = 1, page_size: int = 0,
               db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    every = _all_cubes(db, client.id, job_id)
    counts = _cube_counts(every)
    rows = _filter_cubes(every, q, status, date_from, date_to, sort, dir)
    total = len(rows)
    page, size, off = page_of(total, page, page_size)
    if size:
        rows = rows[off:off + size]
    names = job_names(db, client.id, [r["job_id"] for r in rows])
    for r in rows:
        r["project"] = names.get(r["job_id"], ("", ""))[0]
    return {"cubes": rows, "total": total, "page": page, "page_size": size,
            "summary": {"sets": len(every), "below": counts["below_grade"], "due": counts["to_crush"],
                        "overdue": counts["overdue"], "for_review": counts["for_review"]}}


@router.get("/api/qc/cubes/{sid}")
def get_cube(sid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    s = cube_or_404(db, client.id, sid)
    d = cube_dict(db, s)
    d["project"] = job_names(db, client.id, [s.job_id]).get(s.job_id, ("", ""))[0]
    d["ncrs"] = [{"id": n.id, "number": n.number, "status": n.status, "source_ref": n.source_ref or ""} for n in
                 db.query(models.DBNcr).filter(models.DBNcr.client_id == client.id, models.DBNcr.source_type == "cube_set",
                                               models.DBNcr.source_id == s.id).all()]
    return {"cube_set": d, "history": history(db, client.id, "cube_set", s.id)}


@router.post("/api/qc/cubes")
def create_cube_set(body: CubeSetIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = _qc_job(db, client.id, body.job_id)
    grade = (body.grade or "M25").strip().upper()
    if not re.match(r"^M\d{2,3}$", grade):
        raise HTTPException(400, "The grade as it is written: M20, M25, M30...")
    cast = clean_date(body.cast_on, "casting date") or _today()
    if cast > _today():
        raise HTTPException(400, "Cubes cannot be cast in the future.")
    if body.slump_mm and not 0 <= body.slump_mm <= 300:
        raise HTTPException(400, "Slump in millimetres - 75 to 150 is usual.")
    given = parse_ages(body.test_ages)
    if (body.test_ages or "").strip() and not given:
        raise HTTPException(400, "The ages to test at, in days: 7, 28.")
    s = models.DBCubeSet(client_id=client.id, job_id=job.id, number=unique_number(db, models.DBCubeSet, client.id, "CT"),
                         cast_on=cast, location=(body.location or "").strip()[:200], grade=grade, fck=grade_fck(grade),
                         slump_mm=body.slump_mm or 0, supplier=(body.supplier or "").strip()[:120],
                         docket=(body.docket or "").strip()[:60], cast_by=actor_name, remarks=(body.remarks or "").strip(),
                         pour_ref=(body.pour_ref or "").strip()[:80], cube_ids=(body.cube_ids or "").strip()[:200])
    # The schedule the project asked for: what it has set criteria for, else what the caller gave, else 7 and 28.
    s.test_ages = ",".join(str(a) for a in (given or schedule_for(s, criteria_map(db, client.id, [job.id]))))
    db.add(s)
    db.flush()
    qc_log(db, client.id, "qc.cube.registered", "cube_set", s, "%s cast %s, tests at %s days" % (grade, cast, s.test_ages), actor_name, request)
    db.commit()
    return {"cube_set": cube_dict(db, s)}


@router.post("/api/qc/cubes/{sid}/results")
def add_cube_result(sid: int, body: CubeResultIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    s = cube_or_404(db, client.id, sid)
    vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", body.strengths or "")]
    if not vals or any(v <= 0 or v > 150 for v in vals):
        raise HTTPException(400, "The crushing strengths in N/mm2, one per cube: 31.2, 29.8, 30.5")
    if not 1 <= body.age_days <= 365:
        raise HTTPException(400, "Age in days - 7 or 28 as a rule.")
    on = clean_date(body.tested_on, "testing date") or _today()
    if on > _today():
        raise HTTPException(400, "A test cannot be dated in the future.")
    if s.cast_on and on < s.cast_on:
        raise HTTPException(400, "The test date is before the cubes were cast (%s)." % s.cast_on)
    if db.query(models.DBCubeResult).filter(models.DBCubeResult.set_id == s.id,
                                            models.DBCubeResult.age_days == body.age_days).first():
        raise HTTPException(409, "%s already has its %d-day result." % (s.number, body.age_days))
    cmap = criteria_map(db, client.id, [s.job_id])
    ev, cmin, csingle, ref = evaluate(vals, cmap.get((s.job_id, (s.grade or "").upper(), body.age_days)))
    r = models.DBCubeResult(set_id=s.id, age_days=body.age_days, tested_on=on,
                            strengths=", ".join("%g" % v for v in vals), average=round(sum(vals) / len(vals), 2),
                            lab=(body.lab or "").strip()[:120], recorded_by_name=actor_name,
                            remarks=(body.remarks or "").strip(), flagged=bool(body.flag_review),
                            evaluation=ev, criteria_min=cmin, criteria_single=csingle, criteria_ref=ref)
    db.add(r)
    db.flush()
    said = {"meets": "meets the criteria", "below": "BELOW the criteria", "no_criteria": "no criteria set"}[ev]
    qc_log(db, client.id, "qc.cube.result", "cube_set", s, "%d days: %s N/mm2 average, %s" % (body.age_days, r.average, said), actor_name, request)
    db.commit()
    d = cube_dict(db, s)
    got = [x for x in d["results"] if x["age_days"] == body.age_days][0]
    if got["evaluation"] != "meets":
        notify(db, client.id, "qc_failed", "%s %s at %d days: %s N/mm2" % (s.number, s.grade, body.age_days, got["average"]),
               "%s, cast %s. %s." % (s.location or "", s.cast_on, got["verdict"].capitalize()),
               view="quality-view", ref_type="cube_set", ref_id=s.id, severity="wrong" if ev == "below" else "action")
    return {"cube_set": d}


@router.post("/api/qc/cubes/{sid}/flag")
def flag_cube_for_review(sid: int, body: NoteIn, request: Request, db: Session = Depends(get_db)):
    """Anyone who records can send a set to the engineer, whatever the numbers say."""
    client, _, actor = wo_actor(request, db, "site.record")
    s = cube_or_404(db, client.id, sid)
    last = db.query(models.DBCubeResult).filter(models.DBCubeResult.set_id == s.id).order_by(
        models.DBCubeResult.age_days.desc()).first()
    if not last:
        raise HTTPException(409, "%s has no result yet to send for review." % s.number)
    if not (body.note or "").strip():
        raise HTTPException(400, "Say what the engineer is to look at.")
    last.flagged = True
    last.remarks = ((last.remarks + "\n") if last.remarks else "") + "Flagged by %s: %s" % (actor, body.note.strip())
    s.acceptance, s.reviewed_results = "", 0          # an earlier decision no longer covers this
    qc_log(db, client.id, "qc.cube.flagged", "cube_set", s, body.note.strip(), actor, request)
    db.commit()
    notify(db, client.id, "qc_failed", "%s needs engineering review" % s.number, body.note.strip()[:300],
           view="quality-view", ref_type="cube_set", ref_id=s.id, severity="action")
    return {"cube_set": cube_dict(db, s)}


@router.post("/api/qc/cubes/{sid}/decision")
def decide_cube(sid: int, body: CubeDecisionIn, request: Request, db: Session = Depends(get_db)):
    """The engineer's assessment of the concrete as a whole. Only here does a set become accepted."""
    client, _, actor = wo_actor(request, db, "site.signoff")
    s = cube_or_404(db, client.id, sid)
    if body.decision not in CUBE_DECISIONS:
        raise HTTPException(400, "Accepted, accepted with conditions, or rejected.")
    d = cube_dict(db, s)
    if not d["results"]:
        raise HTTPException(409, "%s has no result to assess." % s.number)
    note = (body.note or "").strip()
    below = any(r["failed"] for r in d["results"])
    if body.decision == "accepted" and below:
        raise HTTPException(409, "A result is below its criteria - accept it with conditions, or reject, and say why.")
    if (body.decision != "accepted" or d["review_reasons"]) and not note:
        raise HTTPException(400, "Record the basis of the decision - what was assessed and why.")
    s.acceptance, s.acceptance_note = body.decision, note[:2000]
    s.accepted_by, s.accepted_on, s.reviewed_results = actor, _today(), len(d["results"])
    qc_log(db, client.id, "qc.cube.decision", "cube_set", s, "%s. %s" % (CUBE_DECISIONS[body.decision], note), actor, request)
    db.commit()
    return {"cube_set": cube_dict(db, s)}


# ---- non-conformances ------------------------------------------------------------------------

def _ncr_source(db, client, body):
    """What the NCR is raised against: fills in what went wrong from the record."""
    job_id, location, desc, ref = body.job_id, (body.location or "").strip(), (body.description or "").strip(), (body.source_ref or "").strip()
    if body.source_type == "inspection" and body.source_id:
        i = _inspection_or_404(db, client.id, body.source_id)
        if i.result != "FAILED":
            raise HTTPException(409, "%s has not failed - an NCR is raised against a failed inspection." % i.number)
        d = inspection_dict(i)
        job_id = i.job_id
        location = location or i.location
        desc = desc or "%s (%s) failed: %s" % (i.number, i.checklist, "; ".join(
            x["item"] + (" - " + x["remark"] if x["remark"] else "") for x in d["items"] if x["result"] == "not ok"))
    elif body.source_type == "cube_set" and body.source_id:
        s = cube_or_404(db, client.id, body.source_id)
        d = cube_dict(db, s)
        if not d["results"]:
            raise HTTPException(409, "%s has no result to raise an NCR on." % s.number)
        low = [r for r in d["results"] if r["failed"]]
        if ref:
            low = [r for r in d["results"] if str(r["age_days"]) == ref] or low
        elif low:
            ref = str(low[0]["age_days"])
        job_id = s.job_id
        location = location or s.location
        what = "; ".join("%d-day average %s N/mm2 (%s)" % (r["age_days"], r["average"], r["verdict"]) for r in low)
        desc = desc or "%s %s cast %s: %s" % (s.number, s.grade, s.cast_on, what or "; ".join(d["review_reasons"]) or "needs engineering review")
    elif body.source_type in ("inspection", "cube_set"):
        raise HTTPException(400, "Which %s is it raised against?" % ("inspection" if body.source_type == "inspection" else "cube set"))
    return job_id, location, desc, ref


def _no_duplicate(db, client_id, job_id, source_type, source_id, ref, desc):
    """One issue, one NCR: refused when the same source - or, by hand, the same words - is already reported."""
    M = models.DBNcr
    q = db.query(M).filter(M.client_id == client_id)
    if source_type in ("inspection", "cube_set") and source_id:
        q = q.filter(M.source_type == source_type, M.source_id == source_id)
        if source_type == "cube_set" and ref:
            q = q.filter(M.source_ref == ref)
        hit = q.first()
        if hit:
            raise HTTPException(409, "%s already covers this (%s)." % (hit.number, hit.status.lower().replace("_", " ")))
    else:
        for n in q.filter(M.job_id == job_id, M.status != "CLOSED").all():
            if (n.description or "").strip().lower() == desc.strip().lower():
                raise HTTPException(409, "%s already reports exactly this and is still open." % n.number)


@router.get("/api/qc/ncrs")
def list_ncrs(request: Request, job_id: int = 0, status: str = "", q: str = "", date_from: str = "",
              date_to: str = "", severity: str = "", sort: str = "", dir: str = "desc", page: int = 1,
              page_size: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    M = models.DBNcr
    query = ncr_query(db, client.id, job_id, q, status, date_from, date_to, severity)
    total = query.count()
    page, size, off = page_of(total, page, page_size)
    query = query.order_by(sort_clause(M, NCR_SORTS, sort, dir), M.id.desc())
    if size:
        query = query.offset(off).limit(size)
    rows = query.all()
    names = job_names(db, client.id, [n.job_id for n in rows])
    live = ncr_query(db, client.id, job_id, status="not_closed")
    return {"ncrs": [ncr_dict(n, names) for n in rows], "total": total, "page": page, "page_size": size,
            "summary": {"open": live.count(), "overdue": ncr_query(db, client.id, job_id, status="overdue").count(),
                        "major_open": live.filter(M.severity.in_(("Major", "Critical"))).count()}}


@router.get("/api/qc/ncrs/{nid}")
def get_ncr(nid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    n = ncr_or_404(db, client.id, nid)
    d = ncr_dict(n, job_names(db, client.id, [n.job_id]))
    d["evidence"] = db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "ncr",
                                                   models.DBFile.attached_id == n.id).count()
    d["source_number"] = ""
    src = {"inspection": models.DBInspection, "cube_set": models.DBCubeSet}.get(n.source_type)
    if src and n.source_id:
        s = db.query(src).filter(src.id == n.source_id, src.client_id == client.id).first()
        d["source_number"] = s.number if s else ""
    return {"ncr": d, "history": history(db, client.id, "ncr", n.id)}


@router.post("/api/qc/ncrs")
def raise_ncr(body: NcrIn, request: Request, db: Session = Depends(get_db)):
    """By hand, or from a failed inspection or a set of cubes below grade - which fills in what went
    wrong from the record. One issue gets one NCR."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    job_id, location, desc, ref = _ncr_source(db, client, body)
    if not job_id:
        raise HTTPException(400, "Which project is it on?")
    job = _qc_job(db, client.id, job_id)
    if not desc:
        raise HTTPException(400, "Say what is not as specified.")
    sev = (body.severity or "Minor").strip().title()
    if sev not in NCR_SEVERITIES:
        raise HTTPException(400, "Severity is Minor, Major or Critical.")
    target = clean_date(body.target_date, "due date")
    if target and target < _today():
        raise HTTPException(400, "The due date is already past.")
    _no_duplicate(db, client.id, job.id, body.source_type or "", body.source_id, ref, desc)
    n = models.DBNcr(client_id=client.id, job_id=job.id, number=unique_number(db, models.DBNcr, client.id, "NCR"),
                     raised_on=_today(), raised_by=actor_name, location=location[:200], description=desc[:3000],
                     severity=sev, responsible=(body.responsible or "").strip()[:120],
                     corrective_action=(body.corrective_action or "").strip(), target_date=target,
                     source_type=body.source_type or "manual", source_id=body.source_id, source_ref=ref,
                     root_cause=(body.root_cause or "").strip())
    db.add(n)
    db.flush()
    qc_log(db, client.id, "qc.ncr.raised", "ncr", n, "%s: %s" % (sev, desc[:200]), actor_name, request)
    db.commit()
    notify(db, client.id, "qc_failed", "%s raised - %s" % (n.number, n.location or job.name),
           n.description[:300], view="quality-view", ref_type="ncr", ref_id=n.id,
           severity="wrong" if sev != "Minor" else "action")
    return {"ncr": ncr_dict(n, job_names(db, client.id, [n.job_id]))}


def _live(n, *allowed):
    if n.status == "CLOSED":
        raise HTTPException(409, "%s is closed." % n.number)
    if allowed and n.status not in allowed:
        raise HTTPException(409, "%s is %s - this is not the step it is at." % (n.number, n.status.lower().replace("_", " ")))


@router.post("/api/qc/ncrs/{nid}/assign")
def assign_ncr(nid: int, body: NcrAssignIn, request: Request, db: Session = Depends(get_db)):
    """Puts a named person or contractor on putting it right, by a date."""
    client, _, actor = wo_actor(request, db, "site.signoff")
    n = ncr_or_404(db, client.id, nid)
    _live(n, "OPEN", "ASSIGNED", "UNDER_CORRECTION")
    who = (body.responsible or "").strip()
    if not who:
        raise HTTPException(400, "Who is to put it right?")
    target = clean_date(body.target_date, "due date", required=True)
    if target < _today():
        raise HTTPException(400, "The due date is already past.")
    if body.severity:
        sev = body.severity.strip().title()
        if sev not in NCR_SEVERITIES:
            raise HTTPException(400, "Severity is Minor, Major or Critical.")
        n.severity = sev
    n.responsible, n.target_date, n.assigned_by, n.assigned_on = who[:120], target, actor, _today()
    if (body.corrective_action or "").strip():
        n.corrective_action = body.corrective_action.strip()
    if body.root_cause is not None:
        n.root_cause = body.root_cause.strip()
    if n.status == "OPEN":
        n.status = "ASSIGNED"
    qc_log(db, client.id, "qc.ncr.assigned", "ncr", n, "To %s by %s" % (who, target), actor, request)
    db.commit()
    return {"ncr": ncr_dict(n, job_names(db, client.id, [n.job_id]))}


@router.post("/api/qc/ncrs/{nid}/work")
def record_ncr_work(nid: int, body: NcrWorkIn, request: Request, db: Session = Depends(get_db)):
    """What was actually done to put it right, as the person who did it records it."""
    client, _, actor = wo_actor(request, db, "site.record")
    n = ncr_or_404(db, client.id, nid)
    _live(n, "ASSIGNED", "UNDER_CORRECTION")
    done = (body.corrective_done or "").strip()
    if not done:
        raise HTTPException(400, "Say what was done.")
    n.corrective_done, n.corrective_on, n.status = done[:3000], _today(), "UNDER_CORRECTION"
    if body.root_cause is not None:
        n.root_cause = body.root_cause.strip()
    qc_log(db, client.id, "qc.ncr.corrective_recorded", "ncr", n, done[:300], actor, request)
    db.commit()
    return {"ncr": ncr_dict(n, job_names(db, client.id, [n.job_id]))}


@router.post("/api/qc/ncrs/{nid}/request-verification")
def request_ncr_verification(nid: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.record")
    n = ncr_or_404(db, client.id, nid)
    _live(n, "UNDER_CORRECTION")
    if not (n.corrective_done or "").strip():
        raise HTTPException(409, "Record the corrective work before asking for it to be verified.")
    if (n.severity or "") in NCR_ROOT_CAUSE_FROM:
        if not (n.root_cause or "").strip():
            raise HTTPException(409, "A %s NCR needs its root cause before it can be verified." % n.severity.lower())
        evidence = db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "ncr",
                                                  models.DBFile.attached_id == n.id).count()
        if not evidence:
            raise HTTPException(409, "Attach the photographs or papers that show the work done, then ask for verification.")
    n.status, n.verification_result, n.verification_note = "REINSPECTION", "", ""
    qc_log(db, client.id, "qc.ncr.verification_requested", "ncr", n, "", actor, request)
    db.commit()
    notify(db, client.id, "qc_failed", "%s is ready to verify" % n.number, (n.corrective_done or "")[:300],
           view="quality-view", ref_type="ncr", ref_id=n.id, severity="action")
    return {"ncr": ncr_dict(n, job_names(db, client.id, [n.job_id]))}


@router.post("/api/qc/ncrs/{nid}/verify")
def verify_ncr(nid: int, body: NcrVerifyIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    n = ncr_or_404(db, client.id, nid)
    _live(n, "REINSPECTION")
    if body.result not in ("verified", "rejected"):
        raise HTTPException(400, "Verified or rejected.")
    note = (body.note or "").strip()
    if body.result == "rejected" and not note:
        raise HTTPException(400, "Say what is still not right.")
    n.verification_result, n.verification_note, n.verified_by, n.verified_on = body.result, note[:2000], actor, _today()
    if body.result == "rejected":
        n.status = "UNDER_CORRECTION"
    qc_log(db, client.id, "qc.ncr." + body.result, "ncr", n, note, actor, request)
    db.commit()
    return {"ncr": ncr_dict(n, job_names(db, client.id, [n.job_id]))}


@router.post("/api/qc/ncrs/{nid}/close")
def close_ncr(nid: int, body: NcrCloseIn, request: Request, db: Session = Depends(get_db)):
    """Only after the correction has been verified, and only by somebody who signs off."""
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    n = ncr_or_404(db, client.id, nid)
    if n.status == "CLOSED":
        raise HTTPException(409, "%s is already closed." % n.number)
    if n.verification_result != "verified" or n.status != "REINSPECTION":
        raise HTTPException(409, "%s has not been verified yet - verify the correction first." % n.number)
    if not (body.closure_note or "").strip():
        raise HTTPException(400, "Say what was done to put it right.")
    n.status, n.closed_on, n.closed_by = "CLOSED", _today(), actor_name
    n.closure_note = body.closure_note.strip()
    qc_log(db, client.id, "qc.ncr.closed", "ncr", n, n.closure_note[:300], actor_name, request)
    db.commit()
    return {"ncr": ncr_dict(n, job_names(db, client.id, [n.job_id]))}


# ---- registers and forms ---------------------------------------------------------------------

@router.get("/api/qc/inspections.xlsx")
def inspections_export(request: Request, job_id: int = 0, q: str = "", status: str = "", date_from: str = "",
                       date_to: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rows, _, _, _ = _inspection_rows(db, client.id, job_id, q, status, date_from, date_to, "date", "desc", 1, 0)
    rows = [(i["number"], i["project"], i["inspected_on"], i["checklist"], i["location"], i["inspected_by"],
             i["witnessed_by"], i["result_label"], i.get("remarks", "")) for i in rows]
    return sheet_response(("No.", "Project", "Date", "Checklist", "Location", "Inspected by", "Witnessed by", "Result", "Remarks"),
                          rows, "inspections.xlsx", preamble=_pre(client, "QUALITY INSPECTIONS"))


@router.get("/api/qc/cubes.xlsx")
def cubes_export(request: Request, job_id: int = 0, q: str = "", status: str = "", date_from: str = "",
                 date_to: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rows = []
    for c in _filter_cubes(_all_cubes(db, client.id, job_id), q, status, date_from, date_to, "cast", "desc"):
        res = {r["age_days"]: r for r in c["results"]}
        rows.append((c["number"], c["cast_on"], c["location"], c["pour_ref"], c["grade"], c["cube_ids"], c["supplier"], c["docket"],
                     res[7]["average"] if 7 in res else "", res[28]["average"] if 28 in res else "",
                     res[28]["criteria_min"] if 28 in res else "", c["status"]))
    return sheet_response(("Sample", "Cast on", "Pour", "Pour ref", "Grade", "Cubes", "Supplier", "Docket", "7-day", "28-day", "28-day criterion", "Status"),
                          rows, "cube_tests.xlsx", preamble=_pre(client, "CUBE TEST REGISTER"))


@router.get("/api/qc/ncrs.xlsx")
def ncrs_export(request: Request, job_id: int = 0, q: str = "", status: str = "", date_from: str = "",
                date_to: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    found = ncr_query(db, client.id, job_id, q, status, date_from, date_to).order_by(models.DBNcr.id.desc()).all()
    names = job_names(db, client.id, [n.job_id for n in found])
    keys = ["number", "project", "raised_on", "location", "description", "severity", "responsible", "target_date", "status_label"]
    rows = [tuple(ncr_dict(n, names).get(k, "") for k in keys) for n in found]
    return sheet_response(("No.", "Project", "Raised", "Location", "Description", "Severity", "Responsible", "Due", "Status"),
                          rows, "ncrs.xlsx", preamble=_pre(client, "NON-CONFORMANCE REGISTER"))


@router.get("/api/qc/inspections/{iid}/document.pdf")
def inspection_pdf(iid: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    i = db.query(models.DBInspection).filter(models.DBInspection.id == iid, models.DBInspection.client_id == client.id).first()
    if not i:
        raise HTTPException(404, "Inspection not found")
    d = inspection_dict(i)
    project, site = _job_line(db, i.job_id)
    marks = {"ok": "OK", "pass": "OK", "yes": "OK", "fail": "NOT OK", "no": "NOT OK", "na": "N/A", "": "-"}
    rows = [[str(n), it.get("item", ""), marks.get(str(it.get("result") or "").lower(), str(it.get("result") or "-")).upper(),
             it.get("remark", "")] for n, it in enumerate(d.get("items") or [], 1)]
    blocks = [
        {"type": "pairs", "cols": 2, "rows": [("Project", project), ("Location", d["location"] or "-"),
                                              ("Inspected on", form_pdf.date_text(d["inspected_on"])),
                                              ("Result", d["result_label"])]},
        {"type": "table", "columns": [("#", 6, "C"), ("Check", 106, "L"), ("Result", 20, "C"), ("Remark", 50, "L")],
         "rows": rows},
        {"type": "pairs", "rows": [("Remarks", d.get("remarks") or "-")], "label_width": 30},
    ]
    sig = [("Inspected By", d["inspected_by"] or ""), ("Witnessed By", d["witnessed_by"] or ""),
           ("Quality Engineer", ""), ("Client's Engineer", "")]
    return form_pdf_response(_field_doc(db, client, "INSPECTION REPORT",
                                        [("Report No", d["number"]), ("Checklist", d["checklist"]),
                                         ("Date", form_pdf.date_text(d["inspected_on"]))], blocks, sig, d["number"]),
                             d["number"])


@router.get("/api/qc/ncrs/{nid}/document.pdf")
def ncr_pdf(nid: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    n = db.query(models.DBNcr).filter(models.DBNcr.id == nid, models.DBNcr.client_id == client.id).first()
    if not n:
        raise HTTPException(404, "NCR not found")
    d = ncr_dict(n)
    project, site = _job_line(db, n.job_id)
    blocks = [
        {"type": "pairs", "cols": 2, "rows": [("Project", project), ("Location", d["location"] or "-"),
                                              ("Raised on", form_pdf.date_text(d["raised_on"])), ("Raised by", d["raised_by"] or "-"),
                                              ("Severity", d["severity"] or "-"), ("Responsible", d["responsible"] or "-")]},
        {"type": "band", "text": "NON-CONFORMANCE"},
        {"type": "text", "text": d["description"] or "-"},
        {"type": "pairs", "rows": [("Corrective action", d["corrective_action"] or "To be agreed"),
                                   ("Target date", form_pdf.date_text(d["target_date"]) or "-"),
                                   ("Closed", ("%s - %s" % (form_pdf.date_text(d["closed_on"]), d["closure_note"]))
                                    if d["status"] == "CLOSED" else "Open")], "label_width": 42},
    ]
    sig = [("Raised By", d["raised_by"] or ""), ("Responsible", d["responsible"] or ""), ("Quality Engineer", ""),
           ("Closed By", d.get("closed_by") or "")]
    return form_pdf_response(_field_doc(db, client, "NON-CONFORMANCE REPORT",
                                        [("NCR No", d["number"]), ("Status", d["status_label"]),
                                         ("Target", form_pdf.date_text(d["target_date"]) or "-")],
                                        blocks, sig, d["number"], "OVERDUE" if d.get("overdue") else ""), d["number"])
