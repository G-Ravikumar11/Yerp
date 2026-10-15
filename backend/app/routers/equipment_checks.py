"""Equipment checks: the company's inspection checklists for tools, extinguishers and electrical boards."""
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.core.auth import require_erp_read, wo_actor
from app.core.serials import next_number
from app.core.sheets import sheet_response
from app.db import get_db
from app.documents import form_pdf
from app.documents.forms import _field_doc, _job_line, _pre, form_pdf_response
from app.schemas.safety import CheckIn, CheckSignoffIn
from app.services.equipment_checks import (check_dict, clean_items, clean_readings, clean_signoffs, forms_catalogue,
                                           latest_ids, summarise, template_of)
from app.services.projects import job_or_404

router = APIRouter()


def _day_or_400(text, what):
    try:
        return datetime.strptime((text or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s: a date as year-month-day." % what)


def _check_rows(db, client, job_id=0, form_type=""):
    """Every inspection of the business, newest first, and which of them is the latest of its equipment."""
    rows = db.query(models.DBEquipmentCheck).filter(models.DBEquipmentCheck.client_id == client.id).order_by(
        models.DBEquipmentCheck.inspection_date.desc(), models.DBEquipmentCheck.id.desc()).all()
    current = latest_ids(rows)
    jobs = {j.id: ("%s %s" % (j.number or "", j.name or "")).strip() for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id).all()}
    shown = [c for c in rows if (not job_id or c.job_id == job_id) and (not form_type or c.form_type == form_type)]
    files = db.query(models.DBFile.id, models.DBFile.attached_id, models.DBFile.caption).filter(
        models.DBFile.client_id == client.id, models.DBFile.attached_type == "equipment_check",
        models.DBFile.attached_id.in_([c.id for c in shown] or [0])).order_by(models.DBFile.id.asc()).all()
    return [check_dict(c, files, c.id in current, jobs.get(c.job_id, "")) for c in shown]


def _one(db, client, cid):
    row = next((c for c in _check_rows(db, client) if c["id"] == cid), None)
    if not row:
        raise HTTPException(404, "Inspection not found")
    return row


@router.get("/api/safety/checks")
def check_list(request: Request, job_id: int = 0, form_type: str = "", db: Session = Depends(get_db)):
    """The inspections for one project, or every project, with the forms to fill and what is due."""
    client = require_erp_read(request, db)
    checks = _check_rows(db, client, job_id, form_type)
    return {"checks": checks, "forms": forms_catalogue(), "summary": summarise(checks)}


@router.post("/api/safety/checks")
def check_record(body: CheckIn, request: Request, db: Session = Depends(get_db)):
    """Record one inspection: every item answered, the readings, and whoever has signed it so far."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    job = job_or_404(db, client.id, body.job_id)
    tpl = template_of(body.form_type)
    equipment_no = (body.equipment_no or "").strip()
    if not equipment_no:
        raise HTTPException(400, "Write the %s." % tpl["equipment_label"].rstrip(".").lower())
    today = date.today()
    inspected = _day_or_400(body.inspection_date or today.isoformat(), "Inspection date")
    if inspected > today:
        raise HTTPException(400, "An inspection cannot be dated in the future.")
    nxt = (body.next_inspection_date or "").strip()
    if nxt:
        if _day_or_400(nxt, "Next inspection date") <= inspected:
            raise HTTPException(400, "The next inspection has to fall after this one.")
    elif body.form_type != "electrical":
        raise HTTPException(400, "Say when the next inspection is due.")
    ext = (body.extinguisher_type or "").strip()
    if body.form_type == "extinguisher" and ext not in tpl["extinguisher_types"]:
        raise HTTPException(400, "Type of extinguisher: " + ", ".join(tpl["extinguisher_types"]))
    items = clean_items(tpl, [i.model_dump() for i in body.items])
    readings = clean_readings(tpl, body.readings)
    c = models.DBEquipmentCheck(
        client_id=client.id, job_id=job.id, number=next_number(db, models.DBEquipmentCheck, client.id, "CHK"),
        form_type=body.form_type, equipment_no=equipment_no[:80], specs=(body.specs or "").strip()[:200],
        location=(body.location or "").strip()[:160], extinguisher_type=ext if body.form_type == "extinguisher" else "",
        board_type=(body.board_type or "").strip()[:120] if body.form_type == "electrical" else "",
        contractor_name=(body.contractor_name or "").strip()[:160], inspection_date=inspected.isoformat(),
        next_inspection_date=nxt[:10], items=json.dumps(items), readings=json.dumps(readings),
        signoffs=json.dumps(clean_signoffs(tpl, body.signoffs)), recorded_by=actor_name)
    db.add(c)
    db.commit()
    return {"check": _one(db, client, c.id)}


@router.post("/api/safety/checks/{cid}/signoff")
def check_signoff(cid: int, body: CheckSignoffIn, request: Request, db: Session = Depends(get_db)):
    """A signature on the foot of the form: by name and date. The client / PMC review is Accepted or Rejected, and an
    inspection that found a fault cannot be accepted."""
    client, _, _ = wo_actor(request, db, "site.record")
    c = db.query(models.DBEquipmentCheck).filter(models.DBEquipmentCheck.id == cid,
                                                 models.DBEquipmentCheck.client_id == client.id).first()
    if not c:
        raise HTTPException(404, "Inspection not found")
    tpl = template_of(c.form_type)
    name = (body.name or "").strip()[:120]
    if not name:
        raise HTTPException(400, "Whose signature is it?")
    on = (body.date or date.today().isoformat())[:10]
    _day_or_400(on, "Date")
    if body.role == "review":
        if not tpl["review"]:
            raise HTTPException(400, "This checklist has no client / PMC review.")
        if body.decision not in ("accepted", "rejected"):
            raise HTTPException(400, "Accepted or Rejected?")
        if body.decision == "accepted" and check_dict(c)["result"] == "fail":
            raise HTTPException(400, "This inspection found a fault, so it cannot be accepted. Reject it, put the fault "
                                     "right and inspect again.")
        c.decision, c.decision_by, c.decision_on = body.decision, name, on
    else:
        if body.role not in {s["role"] for s in tpl["signoffs"]}:
            raise HTTPException(400, "No such sign-off on this checklist.")
        signed = json.loads(c.signoffs or "{}")
        signed[body.role] = {"name": name, "date": on}
        c.signoffs = json.dumps(signed)
    db.commit()
    return {"check": _one(db, client, c.id)}


@router.delete("/api/safety/checks/{cid}")
def check_remove(cid: int, request: Request, db: Session = Depends(get_db)):
    """Take an inspection off the record, with its photographs."""
    client, _, _ = wo_actor(request, db, "site.signoff")
    c = db.query(models.DBEquipmentCheck).filter(models.DBEquipmentCheck.id == cid,
                                                 models.DBEquipmentCheck.client_id == client.id).first()
    if not c:
        raise HTTPException(404, "Inspection not found")
    db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "equipment_check",
                                   models.DBFile.attached_id == c.id).delete(synchronize_session=False)
    db.delete(c)
    db.commit()
    return {"message": "%s taken off the record." % c.number}


@router.get("/api/safety/checks.xlsx")
def checks_xlsx(request: Request, job_id: int = 0, form_type: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    checks = _check_rows(db, client, job_id, form_type)
    due = {"overdue": "Overdue", "soon": "Due soon", "ok": "", "": ""}
    decided = {"accepted": "Accepted", "rejected": "Rejected"}
    rows = [(c["number"], c["form_label"], c["equipment_no"], c["location"], c["project"], c["inspection_date"],
             c["next_inspection_date"], due[c["due_state"]], "Fault found" if c["result"] == "fail" else "Passed",
             ", ".join(c["failed"]), decided.get(c["decision"], "Awaiting" if c["has_review"] else "-"),
             c["recorded_by"]) for c in checks]
    return sheet_response(("No.", "Checklist", "Equipment", "Where", "Project", "Inspected", "Next due", "Due",
                           "Result", "Items with a fault", "Client / PMC", "Recorded by"), rows, "equipment_checks.xlsx",
                          preamble=_pre(client, "EQUIPMENT AND SAFETY INSPECTIONS"))


def _reading(d, spec):
    value = d["readings"].get(spec["key"])
    return "%g %s" % (value, spec["unit"]) if value else "-"


@router.get("/api/safety/checks/{cid}/document.pdf")
def check_pdf(cid: int, request: Request, db: Session = Depends(get_db)):
    """The checklist as the company's paper form: header, every item with its Yes / No, the readings and the signatures."""
    client = require_erp_read(request, db)
    d = _one(db, client, cid)
    tpl = template_of(d["form_type"])
    project, _ = _job_line(db, d["job_id"])
    pairs = [("Project", project or "-"), ("Contractor", d["contractor_name"] or "-"),
             (tpl["equipment_label"], d["equipment_no"]), ("Location", d["location"] or "-")]
    if d["specs"]:
        pairs.append((tpl["specs_label"] or "Specs", d["specs"]))
    if d["extinguisher_type"]:
        pairs.append(("Type", d["extinguisher_type"]))
    if d["board_type"]:
        pairs.append(("Type of electrical board", d["board_type"]))
    pairs += [("Inspection date", form_pdf.date_text(d["inspection_date"])),
              ("Next inspection date", form_pdf.date_text(d["next_inspection_date"]) or "-")]
    blocks = [{"type": "pairs", "cols": 2, "rows": pairs}]
    columns = [("#", 10, "C"), ("Check item", 92, "L"), ("Yes", 13, "C"), ("No", 13, "C"), ("N/A", 13, "C"),
               ("Remarks", 49, "L")]
    sections = []
    for it in d["items"]:
        if not sections or sections[-1][0] != it["section"]:
            sections.append((it["section"], []))
        sections[-1][1].append(it)
    for name, its in sections:
        if name:
            blocks.append({"type": "band", "text": name.upper()})
        blocks.append({"type": "table", "columns": columns, "rows": [
            [it["key"], it["label"], "X" if it["answer"] == "yes" else "", "X" if it["answer"] == "no" else "",
             "X" if it["answer"] == "na" else "", it["remarks"] + (" (photo kept)" if it["photos"] else "")]
            for it in its]})
    if tpl["readings"]:
        blocks.append({"type": "pairs", "rows": [(r["label"], _reading(d, r)) for r in tpl["readings"]], "label_width": 60})
    found = "No fault found." if d["result"] == "pass" else "FAULT FOUND at item(s): %s%s" % (
        ", ".join(d["failed"]) or "-", "; wheel rated below the machine speed" if d["rpm_wrong"] else "")
    blocks.append({"type": "text", "style": "bold", "text": found})
    if tpl["review"]:
        decision = {"accepted": "ACCEPTED", "rejected": "REJECTED", "": "Awaiting review"}[d["decision"]]
        blocks.append({"type": "pairs", "rows": [(tpl["review"]["label"], decision)], "label_width": 60})
    sig = []
    for s in tpl["signoffs"]:
        got = d["signoffs"].get(s["role"]) or {}
        sig.append((s["label"], ("%s  %s" % (got.get("name", ""), form_pdf.date_text(got.get("date", "")))).strip()))
    if tpl["review"]:
        sig.append((tpl["review"]["signoff_label"],
                    ("%s  %s" % (d["decision_by"], form_pdf.date_text(d["decision_on"]))).strip()))
    wm = "FAULT FOUND - DO NOT USE" if d["result"] == "fail" else ""
    return form_pdf_response(_field_doc(db, client, tpl["title"],
                                        [("Doc Ref", tpl["doc_ref"]), ("Inspection No", d["number"])],
                                        blocks, sig, tpl["doc_ref"] + "  " + d["number"], wm), d["number"])
