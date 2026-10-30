"""Project budgeting: our own cost for every BOQ line, against what the client's BOQ pays, and the profit between them."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import require_items_access, wo_actor
from app.core.sheets import sheet_response
from app.db import get_db, get_read_db
from app.services.boq import boq_lines_of_job
from app.services.budgeting import (KIND_LABEL, budget_view, replace_items, save_settings, suggest_items)
from app.services.projects import job_or_404

router = APIRouter()


class BudgetItemIn(BaseModel):
    kind: str = "MATERIAL"
    description: str = ""
    uom: str = ""
    coefficient: float = 0.0
    rate: float = 0.0
    item_code: str = ""


class BudgetLineIn(BaseModel):
    items: List[BudgetItemIn] = []


class BudgetSettingsIn(BaseModel):
    overhead_percent: float = 0.0
    contingency_percent: float = 0.0
    note: Optional[str] = ""


@router.get("/api/jobs/{job_id}/budget")
def job_budget(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "reports.view")
    return budget_view(db, client.id, job_or_404(db, client.id, job_id))


@router.put("/api/jobs/{job_id}/budget")
def job_budget_settings(job_id: int, body: BudgetSettingsIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    save_settings(db, client.id, job.id, body.overhead_percent, body.contingency_percent, body.note, who)
    log_audit(db, client.id, "budget_settings", "job", job.id, job.number or "",
              "overheads %s%%, contingency %s%%" % (body.overhead_percent, body.contingency_percent), request)
    db.commit()
    return budget_view(db, client.id, job)


@router.put("/api/jobs/{job_id}/budget/lines/{key}")
def job_budget_line(job_id: int, key: str, body: BudgetLineIn, request: Request, db: Session = Depends(get_db)):
    """Replace what one BOQ line costs us, as the editor holds it. An empty list takes the line out of the budget."""
    client, _, who = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    if not any(l.key == key for l in boq_lines_of_job(db, client.id, job.id)):
        raise HTTPException(404, "That line is not in this project's BOQ.")
    replace_items(db, client.id, job.id, key, [i.dict() for i in body.items], who)
    log_audit(db, client.id, "budget_line", "job", job.id, job.number or "", "%s: %d items" % (key, len(body.items)), request)
    db.commit()
    return budget_view(db, client.id, job)


@router.get("/api/budget/materials")
def budget_materials(request: Request, q: str = "", db: Session = Depends(get_read_db)):
    """Materials from the item master with the rate we last paid, to start a line's cost from."""
    client = require_items_access(request, db, "reports.view")
    return suggest_items(db, client.id, q)


@router.get("/api/jobs/{job_id}/budget.xlsx")
def job_budget_export(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "reports.view")
    job = job_or_404(db, client.id, job_id)
    b = budget_view(db, client.id, job)
    t = b["total"]
    preamble = [
        ("PROJECT BUDGET AGAINST BOQ", client.company_name or ""),
        ("Project", "%s %s" % (job.number or "", job.name or "")),
        ("Overheads %", b["overhead_percent"], "Contingency %", b["contingency_percent"]),
        ("BOQ value", t["boq_value"], "Budget cost", t["cost"], "Profit", t["profit"], "Margin %", t["margin"] if t["margin"] is not None else ""),
        (),
    ]
    rows = [(r["item_no"], r["description"], r["uom"], r["quantity"], r["rate"], r["revenue"],
             r["unit_material"], r["unit_labour"], r["unit_other"], r["material"], r["labour"], r["other"],
             r["overheads"] + r["contingency"], r["cost"], "" if r["profit"] is None else r["profit"],
             "" if r["margin"] is None else r["margin"], "Yes" if r["budgeted"] else "No") for r in b["rows"]]
    closing = [("Total", "", "", "", "", t["boq_value"], "", "", "", t["material"], t["labour"], t["other"],
                t["overheads"] + t["contingency"], t["cost"], t["profit"], t["margin"] if t["margin"] is not None else "", "")]
    return sheet_response(
        ("Item", "Description", "Unit", "Quantity", "BOQ rate", "BOQ amount", "%s per unit" % KIND_LABEL["MATERIAL"],
         "%s per unit" % KIND_LABEL["LABOUR"], "%s per unit" % KIND_LABEL["OTHER"], "Material", "Labour", "Plant & other",
         "Overheads and contingency", "Budget cost", "Profit", "Margin %", "Budgeted"),
        rows, "budget_%s.xlsx" % (job.number or "project"), preamble=preamble, closing=closing)
