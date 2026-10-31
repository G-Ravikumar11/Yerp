"""The Bar Bending Schedule: every bar mark of a project, what it takes to cut and what it weighs.

Length and weight are worked out here, unrounded, and only shown rounded:
    total length (m) = number of bars x cutting length (mm) / 1000
    unit weight (kg/m) = diameter (mm) squared / 162
    total weight (kg) = total length x unit weight

A shape's cutting length comes from its dimensions and the bend deductions and hook allowances set for the company or the
project. It is stored on the entry when saved, so changing the rules later never moves a figure already on a schedule.
An approved entry changes only through someone who can approve, it then goes back for approval, and every version is kept.
  reading     anyone signed in to the company
  entries     site.record
  approving   site.signoff
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.sheets import sheet_response
from app.db import get_db, get_read_db
from app.documents import form_pdf
from app.documents.forms import _field_doc, form_pdf_response
from app.services.plant_checks import job_label, jobs_of
from app.services.projects import job_or_404

router = APIRouter()
ELEMENTS = ("Beam", "Column", "Slab", "Footing", "Wall", "Staircase", "Other")
GRADES = ("Fe415", "Fe415D", "Fe500", "Fe500D", "Fe550", "Fe550D", "Fe600")
# Multiples of the bar's diameter. A starting point only: engineers set their own for the company or for a project.
DEFAULT_RULES = {"bend_45": 1.0, "bend_90": 2.0, "bend_135": 3.0, "hook": 10.0}
# The dimensions each shape is drawn with (mm), and how its length is built: the plain sum, with each bend taken off.
SHAPES = {
    "Straight": {"dims": ["A"], "label": "Straight bar"},
    "L": {"dims": ["A", "B"], "label": "L bar (one 90 degree bend)"},
    "U": {"dims": ["A", "B", "C"], "label": "U bar (two 90 degree bends)"},
    "Crank": {"dims": ["A", "D"], "label": "Cranked bar (A overall, D crank height, two cranks)"},
    "Stirrup": {"dims": ["A", "B"], "label": "Rectangular stirrup (A, B outside legs, two 135 degree hooks)"},
    "Custom": {"dims": [], "label": "Any other shape (enter the cutting length)"},
}


class EntryIn(BaseModel):
    job_id: int
    block: str = ""
    floor: str = ""
    element: str = "Beam"
    member_ref: str = ""
    bar_mark: str = ""
    diameter_mm: float = 0
    grade: str = "Fe500D"
    shape: str = "Straight"
    dims: Dict[str, float] = {}
    cutting_length_mm: Optional[float] = None    # Custom shapes only
    num_bars: int = 0
    remarks: Optional[str] = ""
    reason: Optional[str] = ""                   # for an edit


class RulesIn(BaseModel):
    job_id: int = 0                              # 0: the company's own
    bend_45: float
    bend_90: float
    bend_135: float
    hook: float


class ApproveIn(BaseModel):
    ids: List[int]


def rules_for(db, client_id, job_id=0):
    """The project's rules if it has its own, otherwise the company's, otherwise the defaults."""
    S = models.DBSettings
    for key in (("bbs_rules:%d" % job_id) if job_id else None, "bbs_rules"):
        if not key:
            continue
        row = db.query(S).filter(S.client_id == client_id, S.key == key).first()
        if row and row.value:
            try:
                return {**DEFAULT_RULES, **json.loads(row.value)}
            except ValueError:
                pass
    return dict(DEFAULT_RULES)


def cutting_length(shape, dims, d, rules):
    """The straight length to cut, in millimetres, from a shape's dimensions."""
    if shape not in SHAPES or shape == "Custom":
        raise HTTPException(400, "That shape has no calculation: enter the cutting length.")
    for k in SHAPES[shape]["dims"]:
        if not (dims.get(k) or 0) > 0:
            raise HTTPException(400, "Dimension %s of the %s has to be above nought." % (k, SHAPES[shape]["label"].lower()))
    a, b, c = dims.get("A", 0), dims.get("B", 0), dims.get("C", 0)
    if shape == "Straight":
        length = a
    elif shape == "L":
        length = a + b - rules["bend_90"] * d
    elif shape == "U":
        length = a + b + c - 2 * rules["bend_90"] * d
    elif shape == "Crank":
        length = a + 2 * 0.42 * dims["D"] - 4 * rules["bend_45"] * d
    else:
        length = 2 * (a + b) - 3 * rules["bend_90"] * d - 2 * rules["bend_135"] * d + 2 * rules["hook"] * d
    if length <= 0:
        raise HTTPException(400, "The bends take up more than the bar: check the dimensions.")
    return length


def weights(diameter, num_bars, cut_mm):
    total_m = num_bars * cut_mm / 1000.0
    unit = diameter * diameter / 162.0
    return {"total_length_m": total_m, "unit_weight_kg_m": unit, "total_weight_kg": total_m * unit}


def worked_out(db, client_id, body):
    """Every figure of an entry from what was sent, checked."""
    if not body.diameter_mm > 0:
        raise HTTPException(400, "The bar diameter has to be above nought.")
    if not body.num_bars > 0:
        raise HTTPException(400, "The number of bars has to be above nought.")
    if body.shape not in SHAPES:
        raise HTTPException(400, "The shape is one of: %s." % ", ".join(SHAPES))
    if body.shape == "Custom":
        cut = float(body.cutting_length_mm or 0)
        if not cut > 0:
            raise HTTPException(400, "The cutting length has to be above nought.")
    else:
        cut = cutting_length(body.shape, body.dims or {}, body.diameter_mm, rules_for(db, client_id, body.job_id))
    return {"cutting_length_mm": cut, **weights(body.diameter_mm, body.num_bars, cut)}


def entry_key(body):
    clean = lambda v: " ".join((v or "").lower().split())
    return "|".join([str(body.job_id), clean(body.block), clean(body.floor), clean(body.member_ref), clean(body.bar_mark)])


def entry_dict(e, jobs=None):
    return {"id": e.id, "job_id": e.job_id, "project": job_label(jobs, e.job_id) if jobs else "", "block": e.block or "", "floor": e.floor or "", "element": e.element or "", "member_ref": e.member_ref or "",
            "bar_mark": e.bar_mark or "", "diameter_mm": e.diameter_mm, "grade": e.grade or "", "shape": e.shape or "", "dims": json.loads(e.dims or "{}"), "num_bars": e.num_bars,
            "cutting_length_mm": e.cutting_length_mm, **weights(e.diameter_mm, e.num_bars, e.cutting_length_mm), "remarks": e.remarks or "", "status": e.status or "Draft", "revision": e.revision or 0,
            "approved_by": e.approved_by or "", "approved_at": e.approved_at or "", "created_by": e.created_by or ""}


def snapshot(db, e, reason, who):
    db.add(models.DBBbsRevision(client_id=e.client_id, entry_id=e.id, revision=e.revision or 0, snapshot=json.dumps(entry_dict(e)), reason=(reason or "").strip()[:500], changed_by=who))


def _apply(e, body, figures):
    e.job_id, e.block, e.floor, e.element, e.member_ref, e.bar_mark = body.job_id, body.block.strip()[:80], body.floor.strip()[:80], body.element, body.member_ref.strip()[:80], body.bar_mark.strip()[:40]
    e.diameter_mm, e.grade, e.shape, e.dims, e.num_bars = body.diameter_mm, body.grade, body.shape, json.dumps(body.dims or {}), body.num_bars
    e.cutting_length_mm, e.remarks, e.entry_key = figures["cutting_length_mm"], (body.remarks or "").strip(), entry_key(body)


def _check_text(body):
    if body.element not in ELEMENTS:
        raise HTTPException(400, "The structural element is one of: %s." % ", ".join(ELEMENTS))
    if body.grade not in GRADES:
        raise HTTPException(400, "The steel grade is one of: %s." % ", ".join(GRADES))
    for what, v in (("building or block", body.block), ("floor", body.floor), ("member reference", body.member_ref), ("bar mark", body.bar_mark)):
        if not (v or "").strip():
            raise HTTPException(400, "Give the %s." % what)


def _rows(db, client_id, job_id=0, floor="", element="", bar_mark="", diameter=0.0, block=""):
    E = models.DBBbsEntry
    q = db.query(E).filter(E.client_id == client_id)
    if job_id:
        q = q.filter(E.job_id == job_id)
    if floor:
        q = q.filter(E.floor == floor)
    if block:
        q = q.filter(E.block == block)
    if element:
        q = q.filter(E.element == element)
    if bar_mark:
        q = q.filter(E.bar_mark.ilike("%" + bar_mark.strip() + "%"))
    if diameter:
        q = q.filter(E.diameter_mm == diameter)
    return q.order_by(E.block, E.floor, E.element, E.member_ref, E.bar_mark).all()


def summary_of(rows):
    """Length and weight by diameter, and by floor and element."""
    by_dia, by_group = {}, {}
    for e in rows:
        w = weights(e.diameter_mm, e.num_bars, e.cutting_length_mm)
        d = by_dia.setdefault(e.diameter_mm, {"diameter_mm": e.diameter_mm, "bars": 0, "total_length_m": 0.0, "total_weight_kg": 0.0})
        g = by_group.setdefault((e.block or "", e.floor or "", e.element or ""), {"block": e.block or "", "floor": e.floor or "", "element": e.element or "", "bars": 0, "total_length_m": 0.0, "total_weight_kg": 0.0})
        for x in (d, g):
            x["bars"] += e.num_bars
            x["total_length_m"] += w["total_length_m"]
            x["total_weight_kg"] += w["total_weight_kg"]
    return {"by_diameter": sorted(by_dia.values(), key=lambda x: x["diameter_mm"]), "by_group": list(by_group.values()),
            "total_weight_kg": sum(x["total_weight_kg"] for x in by_dia.values()), "total_length_m": sum(x["total_length_m"] for x in by_dia.values()), "entries": len(rows)}


@router.get("/api/bbs")
def list_entries(request: Request, job_id: int = 0, floor: str = "", element: str = "", bar_mark: str = "", diameter: float = 0, block: str = "", db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    jobs = jobs_of(db, client.id)
    rows = _rows(db, client.id, job_id, floor, element, bar_mark, diameter, block)
    return {"entries": [entry_dict(e, jobs) for e in rows], "summary": summary_of(rows), "elements": list(ELEMENTS), "grades": list(GRADES),
            "shapes": [{"value": k, "label": v["label"], "dims": v["dims"]} for k, v in SHAPES.items()]}


@router.post("/api/bbs/calculate")
def calculate(body: EntryIn, request: Request, db: Session = Depends(get_read_db)):
    """The figures for what is on the form, worked out by the same rules as saving it. Saves nothing."""
    client = require_erp_read(request, db)
    return worked_out(db, client.id, body)


@router.get("/api/bbs/rules")
def get_rules(request: Request, job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return rules_for(db, client.id, job_id)


@router.put("/api/bbs/rules")
def save_rules(body: RulesIn, request: Request, db: Session = Depends(get_db)):
    """Bends and hooks, in multiples of the diameter. Entries already saved keep the length they were saved with."""
    client, _, actor = wo_actor(request, db, "site.signoff")
    values = {"bend_45": body.bend_45, "bend_90": body.bend_90, "bend_135": body.bend_135, "hook": body.hook}
    if any(not 0 <= v <= 50 for v in values.values()):
        raise HTTPException(400, "Each rule is between 0 and 50 times the diameter.")
    if body.job_id:
        job_or_404(db, client.id, body.job_id)
    key = "bbs_rules:%d" % body.job_id if body.job_id else "bbs_rules"
    S = models.DBSettings
    row = db.query(S).filter(S.client_id == client.id, S.key == key).first()
    if not row:
        row = S(client_id=client.id, key=key, description="Bar bending: bend deductions and hook allowance")
        db.add(row)
    row.value = json.dumps(values)
    log_audit(db, client.id, "bbs.rules.changed", entity_type="bbs", entity_id=body.job_id or None, details=row.value, request=request, user_name=actor)
    db.commit()
    return {"ok": True, **values, "message": "Bar bending rules saved."}


@router.post("/api/bbs")
def create_entry(body: EntryIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.record")
    job_or_404(db, client.id, body.job_id)
    _check_text(body)
    figures = worked_out(db, client.id, body)
    E = models.DBBbsEntry
    if db.query(E).filter(E.client_id == client.id, E.entry_key == entry_key(body)).first():
        raise HTTPException(409, "Bar mark %s is already on %s, %s, %s." % (body.bar_mark, body.block, body.floor, body.member_ref))
    e = E(client_id=client.id, status="Draft", revision=0, created_by=actor)
    _apply(e, body, figures)
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Bar mark %s has just been added by someone else." % body.bar_mark)
    log_audit(db, client.id, "bbs.created", entity_type="bbs", entity_id=e.id, entity_name=e.bar_mark, details="%s %s" % (e.member_ref, e.element), request=request, user_name=actor)
    db.commit()
    return {"ok": True, "entry": entry_dict(e), "message": "Bar mark %s saved." % e.bar_mark}


def _entry(db, client_id, eid):
    e = db.query(models.DBBbsEntry).filter(models.DBBbsEntry.id == eid, models.DBBbsEntry.client_id == client_id).first()
    if not e:
        raise HTTPException(404, "Entry not found")
    return e


@router.put("/api/bbs/{eid}")
def update_entry(eid: int, body: EntryIn, request: Request, db: Session = Depends(get_db)):
    """A new version, with the last kept. An approved entry changes only through someone who can approve, and goes back for approval."""
    client, _, actor = wo_actor(request, db, "site.record")
    e = _entry(db, client.id, eid)
    if e.status == "Approved":
        wo_actor(request, db, "site.signoff")
        if not (body.reason or "").strip():
            raise HTTPException(400, "Say why an approved entry is changing - it goes on the record.")
    job_or_404(db, client.id, body.job_id)
    _check_text(body)
    figures = worked_out(db, client.id, body)
    E = models.DBBbsEntry
    if db.query(E).filter(E.client_id == client.id, E.entry_key == entry_key(body), E.id != e.id).first():
        raise HTTPException(409, "Bar mark %s is already on %s, %s, %s." % (body.bar_mark, body.block, body.floor, body.member_ref))
    snapshot(db, e, body.reason, actor)
    _apply(e, body, figures)
    e.revision = (e.revision or 0) + 1
    e.status, e.approved_by, e.approved_at = "Draft", "", ""
    log_audit(db, client.id, "bbs.revised", entity_type="bbs", entity_id=e.id, entity_name=e.bar_mark, details="Revision %d. %s" % (e.revision, body.reason or ""), request=request, user_name=actor)
    db.commit()
    return {"ok": True, "entry": entry_dict(e), "message": "Bar mark %s saved as revision %d." % (e.bar_mark, e.revision)}


@router.post("/api/bbs/approve")
def approve_entries(body: ApproveIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    if not body.ids:
        raise HTTPException(400, "Choose what to approve.")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    done = 0
    for eid in dict.fromkeys(body.ids):
        e = _entry(db, client.id, eid)
        if e.status != "Approved":
            e.status, e.approved_by, e.approved_at = "Approved", actor, now
            log_audit(db, client.id, "bbs.approved", entity_type="bbs", entity_id=e.id, entity_name=e.bar_mark, details="Revision %d" % (e.revision or 0), request=request, user_name=actor)
            done += 1
    db.commit()
    return {"ok": True, "approved": done, "message": "%d entr%s approved." % (done, "y" if done == 1 else "ies")}


@router.get("/api/bbs/{eid}/revisions")
def entry_revisions(eid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    e = _entry(db, client.id, eid)
    R = models.DBBbsRevision
    return {"revisions": [{"revision": r.revision, "reason": r.reason or "", "by": r.changed_by or "", "at": (r.changed_at or "")[:16], "entry": json.loads(r.snapshot or "{}")}
                          for r in db.query(R).filter(R.entry_id == e.id).order_by(R.id.desc()).all()]}


def _sheet_rows(rows, jobs):
    return [(job_label(jobs, e.job_id), e.block, e.floor, e.element, e.member_ref, e.bar_mark, e.diameter_mm, e.grade, e.shape, e.num_bars, round(e.cutting_length_mm, 1), round(w["total_length_m"], 3),
             round(w["unit_weight_kg_m"], 3), round(w["total_weight_kg"], 3), e.status, e.revision or 0, e.remarks or "") for e in rows for w in [weights(e.diameter_mm, e.num_bars, e.cutting_length_mm)]]


@router.get("/api/bbs/export.xlsx")
def export_sheet(request: Request, job_id: int = 0, floor: str = "", element: str = "", bar_mark: str = "", diameter: float = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return sheet_response(("Project", "Block", "Floor", "Element", "Member", "Bar mark", "Dia (mm)", "Grade", "Shape", "No. of bars", "Cutting length (mm)", "Total length (m)", "Unit weight (kg/m)", "Total weight (kg)", "Status", "Revision", "Remarks"),
                          _sheet_rows(_rows(db, client.id, job_id, floor, element, bar_mark, diameter), jobs_of(db, client.id)), "bar_bending_schedule.xlsx")


@router.get("/api/bbs/schedule.pdf")
def schedule_pdf(request: Request, job_id: int, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    rows = _rows(db, client.id, job_id)
    s = summary_of(rows)
    table = [[e.block or "", e.floor or "", e.member_ref or "", e.bar_mark or "", "%g" % e.diameter_mm, e.grade or "", str(e.num_bars), "%.0f" % e.cutting_length_mm, "%.2f" % w["total_length_m"], "%.2f" % w["total_weight_kg"]]
             for e in rows for w in [weights(e.diameter_mm, e.num_bars, e.cutting_length_mm)]]
    blocks = [{"type": "pairs", "rows": [("Project", ("%s %s" % (job.number or "", job.name or "")).strip()), ("Total weight (kg)", "%.2f" % s["total_weight_kg"])], "label_width": 40},
              {"type": "table", "columns": [("Block", 18, "L"), ("Floor", 18, "L"), ("Member", 22, "L"), ("Mark", 18, "L"), ("Dia", 12, "R"), ("Grade", 18, "L"), ("Nos", 12, "R"), ("Cut mm", 18, "R"), ("Len m", 22, "R"), ("Kg", 24, "R")], "rows": table}]
    name = "BBS-%s" % (job.number or job.id)
    return form_pdf_response(_field_doc(db, client, "BAR BENDING SCHEDULE", [("Date", form_pdf.date_text(datetime.now().strftime("%Y-%m-%d")))], blocks, [("Prepared By", ""), ("Checked By", ""), ("Approved By", "")], name), name)
