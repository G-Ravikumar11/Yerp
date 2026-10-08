"""The quality endpoints."""
import json
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.documents import form_pdf
from app import models
from app.db import get_db

from app.constants.quality import QC_CHECKLISTS
from app.core.auth import require_erp_read, wo_actor
from app.core.notifications import notify
from app.core.serials import next_number
from app.core.sheets import sheet_response
from app.documents.forms import _field_doc, _job_line, _pre, form_pdf_response
from app.schemas.quality import CubeResultIn, CubeSetIn, InspectionIn, NcrCloseIn, NcrIn
from app.services.quality import (
    _clean_items,
    _inspection_or_404,
    _qc_job,
    cube_dict,
    grade_fck,
    inspection_dict,
    ncr_dict,
)


router = APIRouter()


@router.get("/api/qc/checklists")
def qc_checklists(request: Request, db: Session = Depends(get_db)):
    require_erp_read(request, db)
    return {"checklists": QC_CHECKLISTS}


@router.get("/api/qc/inspections")
def list_inspections(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBInspection).filter(models.DBInspection.client_id == client.id)
    if job_id:
        q = q.filter(models.DBInspection.job_id == job_id)
    return {"inspections": [inspection_dict(i) for i in q.order_by(models.DBInspection.id.desc()).all()]}


@router.post("/api/qc/inspections")
def create_inspection(body: InspectionIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = _qc_job(db, client.id, body.job_id)
    items = body.items
    if items is None:
        if body.checklist not in QC_CHECKLISTS:
            raise HTTPException(400, "Pick a checklist, or give the items to check.")
        items = [{"item": x, "result": "", "remark": ""} for x in QC_CHECKLISTS[body.checklist]]
    i = models.DBInspection(client_id=client.id, job_id=job.id,
                            number=next_number(db, models.DBInspection, client.id, "INS"),
                            checklist=(body.checklist or "Custom").strip(), location=(body.location or "").strip(),
                            inspected_on=(body.inspected_on or date.today().isoformat())[:10],
                            inspected_by=actor_name, witnessed_by=(body.witnessed_by or "").strip(),
                            items=json.dumps(_clean_items(items)), remarks=(body.remarks or "").strip())
    db.add(i)
    db.commit()
    return {"inspection": inspection_dict(i)}


@router.put("/api/qc/inspections/{iid}")
def update_inspection(iid: int, body: InspectionIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "site.record")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "OPEN":
        raise HTTPException(409, "%s is %s - it is the record now." % (i.number, i.result.lower()))
    if body.items is not None:
        i.items = json.dumps(_clean_items(body.items))
    for f in ("location", "witnessed_by", "remarks"):
        v = getattr(body, f)
        if v is not None:
            setattr(i, f, v.strip())
    if body.inspected_on:
        i.inspected_on = body.inspected_on[:10]
    db.commit()
    return {"inspection": inspection_dict(i)}


@router.post("/api/qc/inspections/{iid}/close")
def close_inspection(iid: int, request: Request, db: Session = Depends(get_db)):
    """Passed when nothing on it is "not ok", failed otherwise - every item
    has to have been looked at first."""
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    i = _inspection_or_404(db, client.id, iid)
    if i.result != "OPEN":
        raise HTTPException(409, "%s is already %s." % (i.number, i.result.lower()))
    d = inspection_dict(i)
    unchecked = [x["item"] for x in d["items"] if not x["result"]]
    if unchecked:
        raise HTTPException(409, "Not looked at yet: %s." % "; ".join(unchecked[:3]))
    i.result = "FAILED" if d["failed_items"] else "PASSED"
    db.commit()
    out = {"inspection": inspection_dict(i)}
    if i.result == "FAILED":
        notify(db, client.id, "qc_failed",
               "%s failed at %s" % (i.number, i.location or i.checklist),
               "; ".join(x["item"] for x in d["items"] if x["result"] == "not ok")[:400],
               view="quality-view", ref_type="inspection", ref_id=i.id, severity="wrong")
    return out


@router.get("/api/qc/cubes")
def list_cubes(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBCubeSet).filter(models.DBCubeSet.client_id == client.id)
    if job_id:
        q = q.filter(models.DBCubeSet.job_id == job_id)
    rows = [cube_dict(db, s) for s in q.order_by(models.DBCubeSet.id.desc()).all()]
    return {"cubes": rows, "summary": {
        "sets": len(rows), "below": len([r for r in rows if r["status"] == "below grade"]),
        "due": len([d for r in rows for d in r["due"] if d["overdue"] or d["today"]])}}


@router.post("/api/qc/cubes")
def create_cube_set(body: CubeSetIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = _qc_job(db, client.id, body.job_id)
    grade = (body.grade or "M25").strip().upper()
    if not re.match(r"^M\d{2,3}$", grade):
        raise HTTPException(400, "The grade as it is written: M20, M25, M30...")
    s = models.DBCubeSet(client_id=client.id, job_id=job.id, number=next_number(db, models.DBCubeSet, client.id, "CT"),
                         cast_on=(body.cast_on or date.today().isoformat())[:10], location=(body.location or "").strip(),
                         grade=grade, fck=grade_fck(grade), slump_mm=body.slump_mm or 0,
                         supplier=(body.supplier or "").strip(), docket=(body.docket or "").strip(),
                         cast_by=actor_name, remarks=(body.remarks or "").strip())
    db.add(s)
    db.commit()
    return {"cube_set": cube_dict(db, s)}


@router.post("/api/qc/cubes/{sid}/results")
def add_cube_result(sid: int, body: CubeResultIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.record")
    s = db.query(models.DBCubeSet).filter(models.DBCubeSet.id == sid,
                                          models.DBCubeSet.client_id == client.id).first()
    if not s:
        raise HTTPException(404, "Cube set not found")
    vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", body.strengths or "")]
    if not vals or any(v <= 0 or v > 150 for v in vals):
        raise HTTPException(400, "The crushing strengths in N/mm2, one per cube: 31.2, 29.8, 30.5")
    if not 1 <= body.age_days <= 90:
        raise HTTPException(400, "Age in days - 7 or 28 as a rule.")
    if db.query(models.DBCubeResult).filter(models.DBCubeResult.set_id == s.id,
                                            models.DBCubeResult.age_days == body.age_days).first():
        raise HTTPException(409, "%s already has its %d-day result." % (s.number, body.age_days))
    db.add(models.DBCubeResult(set_id=s.id, age_days=body.age_days,
                               tested_on=(body.tested_on or date.today().isoformat())[:10],
                               strengths=", ".join("%g" % v for v in vals),
                               average=round(sum(vals) / len(vals), 2), lab=(body.lab or "").strip(),
                               recorded_by_name=actor_name))
    db.commit()
    d = cube_dict(db, s)
    got = [r for r in d["results"] if r["age_days"] == body.age_days][0]
    if not got["ok"]:
        notify(db, client.id, "qc_failed", "%s %s at %d days: %s N/mm2" % (s.number, s.grade, body.age_days, got["average"]),
               "%s, cast %s. %s." % (s.location or "", s.cast_on, got["verdict"].capitalize()),
               view="quality-view", ref_type="cube_set", ref_id=s.id, severity="wrong")
    return {"cube_set": d}


@router.get("/api/qc/ncrs")
def list_ncrs(request: Request, job_id: int = 0, status: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBNcr).filter(models.DBNcr.client_id == client.id)
    if job_id:
        q = q.filter(models.DBNcr.job_id == job_id)
    if status:
        q = q.filter(models.DBNcr.status == status.upper())
    rows = [ncr_dict(n) for n in q.order_by(models.DBNcr.id.desc()).all()]
    return {"ncrs": rows, "summary": {"open": len([r for r in rows if r["status"] == "OPEN"]),
                                      "overdue": len([r for r in rows if r["overdue"]]),
                                      "major_open": len([r for r in rows if r["status"] == "OPEN"
                                                         and r["severity"] == "Major"])}}


@router.post("/api/qc/ncrs")
def raise_ncr(body: NcrIn, request: Request, db: Session = Depends(get_db)):
    """By hand, or from a failed inspection or a set of cubes below grade -
    which fills in what went wrong from the record."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    job_id, location, desc = body.job_id, (body.location or "").strip(), (body.description or "").strip()
    if body.source_type == "inspection" and body.source_id:
        i = _inspection_or_404(db, client.id, body.source_id)
        d = inspection_dict(i)
        job_id = i.job_id
        location = location or i.location
        desc = desc or "%s (%s) failed: %s" % (i.number, i.checklist, "; ".join(
            x["item"] + (" - " + x["remark"] if x["remark"] else "") for x in d["items"] if x["result"] == "not ok"))
    elif body.source_type == "cube_set" and body.source_id:
        s = db.query(models.DBCubeSet).filter(models.DBCubeSet.id == body.source_id,
                                              models.DBCubeSet.client_id == client.id).first()
        if not s:
            raise HTTPException(404, "Cube set not found")
        d = cube_dict(db, s)
        job_id = s.job_id
        location = location or s.location
        low = [r for r in d["results"] if not r["ok"]]
        desc = desc or "%s %s cast %s: %s" % (s.number, s.grade, s.cast_on, "; ".join(
            "%d-day average %s N/mm2 (%s)" % (r["age_days"], r["average"], r["verdict"]) for r in low))
    if not job_id:
        raise HTTPException(400, "Which project is it on?")
    job = _qc_job(db, client.id, job_id)
    if not desc:
        raise HTTPException(400, "Say what is not as specified.")
    n = models.DBNcr(client_id=client.id, job_id=job.id, number=next_number(db, models.DBNcr, client.id, "NCR"),
                     raised_on=date.today().isoformat(), raised_by=actor_name, location=location[:200],
                     description=desc[:3000], severity="Major" if body.severity == "Major" else "Minor",
                     responsible=(body.responsible or "").strip(), corrective_action=(body.corrective_action or "").strip(),
                     target_date=(body.target_date or "")[:10], source_type=body.source_type or "manual",
                     source_id=body.source_id)
    db.add(n)
    db.commit()
    notify(db, client.id, "qc_failed", "%s raised - %s" % (n.number, n.location or job.name),
           n.description[:300], view="quality-view", ref_type="ncr", ref_id=n.id,
           severity="wrong" if n.severity == "Major" else "action")
    return {"ncr": ncr_dict(n)}


@router.post("/api/qc/ncrs/{nid}/close")
def close_ncr(nid: int, body: NcrCloseIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    n = db.query(models.DBNcr).filter(models.DBNcr.id == nid, models.DBNcr.client_id == client.id).first()
    if not n:
        raise HTTPException(404, "NCR not found")
    if n.status == "CLOSED":
        raise HTTPException(409, "%s is already closed." % n.number)
    if not (body.closure_note or "").strip():
        raise HTTPException(400, "Say what was done to put it right.")
    n.status, n.closed_on, n.closed_by = "CLOSED", date.today().isoformat(), actor_name
    n.closure_note = body.closure_note.strip()
    db.commit()
    return {"ncr": ncr_dict(n)}


@router.get("/api/qc/inspections.xlsx")
def inspections_export(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = list_inspections(request, job_id, db)
    rows = [(i["number"], i["inspected_on"], i["checklist"], i["location"], i["inspected_by"], i["witnessed_by"],
             i.get("result") or "open", i.get("remarks", "")) for i in d["inspections"]]
    return sheet_response(("No.", "Date", "Checklist", "Location", "Inspected by", "Witnessed by", "Result", "Remarks"),
                          rows, "inspections.xlsx", preamble=_pre(client, "QUALITY INSPECTIONS"))


@router.get("/api/qc/cubes.xlsx")
def cubes_export(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = list_cubes(request, job_id, db)
    rows = []
    for c in d["cubes"]:
        res = {r.get("age_days"): r for r in c.get("results") or []}
        def avg(age):
            r = res.get(age)
            return r.get("average") or r.get("avg_strength") or r.get("strength") or "" if r else ""
        rows.append((c["number"], c["cast_on"], c["location"], c["grade"], c.get("fck", ""), c.get("supplier", ""),
                     c.get("docket", ""), avg(7), avg(28), c.get("verdict") or c.get("status", "")))
    return sheet_response(("Set", "Cast on", "Pour", "Grade", "fck", "Supplier", "Docket", "7-day", "28-day", "Result"),
                          rows, "cube_tests.xlsx", preamble=_pre(client, "CUBE TEST REGISTER"))


@router.get("/api/qc/ncrs.xlsx")
def ncrs_export(request: Request, job_id: int = 0, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = list_ncrs(request, job_id, "", db)
    keys = ["number", "raised_on", "location", "description", "severity", "responsible", "target_date", "status"]
    rows = [tuple(n.get(k, "") for k in keys) for n in d["ncrs"]]
    return sheet_response(("No.", "Raised", "Location", "Description", "Severity", "Responsible", "Target", "Status"),
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
                                              ("Result", d.get("result") or "Open")]},
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
                                        [("NCR No", d["number"]), ("Status", d["status"]),
                                         ("Target", form_pdf.date_text(d["target_date"]) or "-")],
                                        blocks, sig, d["number"], "OVERDUE" if d.get("overdue") else ""), d["number"])
