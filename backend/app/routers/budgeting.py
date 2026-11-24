"""Project budgeting: our own cost for every BOQ line, against what the client's BOQ pays, and the profit between them."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import require_items_access, wo_actor
from app.core.currency import inr
from app.core.notifications import notify
from app.core.sheets import sheet_response
from app.db import get_db, get_read_db
from app.services.boq import boq_lines_of_job
from app.services.budgeting import (KIND_LABEL, MAX_ITEMS_PER_LINE, budget_view, replace_items, resolve_wastage, save_settings, suggest_items)
from app.services.earned_value import earned_value
from app.services.projects import job_or_404

router = APIRouter()


class BudgetItemIn(BaseModel):
    kind: str = "MATERIAL"
    description: str = ""
    uom: str = ""
    coefficient: float = 0.0
    rate: float = 0.0
    item_code: str = ""
    wastage_percent: float = 0.0          # the budget's own; the store's norm, where one is set, is used instead of it


class BudgetLineIn(BaseModel):
    items: List[BudgetItemIn] = []


class WastageAskIn(BaseModel):
    kind: str = "MATERIAL"
    item_code: str = ""
    wastage_percent: float = 0.0


class WastageAsksIn(BaseModel):
    items: List[WastageAskIn] = []


class BudgetSettingsIn(BaseModel):
    overhead_percent: float = 0.0
    contingency_percent: float = 0.0
    note: Optional[str] = ""


@router.get("/api/jobs/{job_id}/budget-control")
def job_budget_control(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The project's BOQ lines with how much of each is budgeted, given to contractors and left (services/budget_control.py)."""
    from app.services.budget_control import project_budget
    client = require_items_access(request, db, ("budget.view", "budget.edit"))
    return project_budget(db, client.id, job_or_404(db, client.id, job_id))


@router.get("/api/jobs/{job_id}/budget")
def job_budget(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, ("budget.view", "budget.edit"))
    return budget_view(db, client.id, job_or_404(db, client.id, job_id))


@router.put("/api/jobs/{job_id}/budget")
def job_budget_settings(job_id: int, body: BudgetSettingsIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, "budget.edit")
    job = job_or_404(db, client.id, job_id)
    save_settings(db, client.id, job.id, body.overhead_percent, body.contingency_percent, body.note, who)
    log_audit(db, client.id, "budget_settings", "job", job.id, job.number or "",
              "overheads %s%%, contingency %s%%" % (body.overhead_percent, body.contingency_percent), request)
    db.commit()
    return budget_view(db, client.id, job)


@router.put("/api/jobs/{job_id}/budget/lines/{key}")
def job_budget_line(job_id: int, key: str, body: BudgetLineIn, request: Request, db: Session = Depends(get_db)):
    """Replace what one BOQ line costs us, as the editor holds it. An empty list takes the line out of the budget."""
    client, actor_id, who = wo_actor(request, db, "budget.edit")
    job = job_or_404(db, client.id, job_id)
    line = next((l for l in boq_lines_of_job(db, client.id, job.id) if l.key == key), None)
    if line is None:
        raise HTTPException(404, "That line is not in this project's BOQ.")
    from app.services.budgeting import unit_costs
    was = unit_costs(db, client.id, job.id).get(key) or {"MATERIAL": 0.0, "LABOUR": 0.0, "OTHER": 0.0}
    replace_items(db, client.id, job.id, key, [i.dict() for i in body.items], who)
    db.flush()
    now = unit_costs(db, client.id, job.id).get(key) or {"MATERIAL": 0.0, "LABOUR": 0.0, "OTHER": 0.0}
    # Logged with the figures, not just a count: what one unit cost before and after, part by part.
    change = "; ".join("%s %s -> %s" % (k.lower(), inr(was[k]), inr(now[k])) for k in ("MATERIAL", "LABOUR", "OTHER")
                       if abs(was[k] - now[k]) > 0.004)
    label = ("%s %s" % (line.item_no or "", (line.description or "").split(chr(10))[0][:60])).strip()
    log_audit(db, client.id, "budget_line", "job", job.id, job.number or "",
              ("%s: %s by %s" % (label, change or "%d items, cost unchanged" % len(body.items), who))[:900], request)
    # The part a contractor is paid for, raised by staff: the Master is told, since a work order is checked against it.
    paid_before, paid_after = was["LABOUR"] + was["OTHER"], now["LABOUR"] + now["OTHER"]
    if actor_id is not None and paid_before > 0 and paid_after > paid_before + 0.004:
        notify(db, client.id, "budget_raised", "Budget raised on %s: %s" % (job.number or job.name or "a project", label),
               "%s raised labour + plant & other per unit from %s to %s." % (who, inr(paid_before), inr(paid_after)),
               view="budgeting", ref_type="job", ref_id=job.id)
    db.commit()
    return budget_view(db, client.id, job)


@router.post("/api/jobs/{job_id}/budget/lines/{key}/wastage")
def job_budget_line_wastage(job_id: int, key: str, body: WastageAsksIn, request: Request, db: Session = Depends(get_read_db)):
    """Which wastage % each material of a line would be costed at as the editor holds it - the store's norm where one is set
    for the material on this BOQ line, else the figure typed - with the mismatch warning. Saves nothing."""
    client = require_items_access(request, db, ("budget.edit",))
    job = job_or_404(db, client.id, job_id)
    if len(body.items) > MAX_ITEMS_PER_LINE:
        raise HTTPException(400, "A line has at most %d items." % MAX_ITEMS_PER_LINE)
    if not any(l.key == key for l in boq_lines_of_job(db, client.id, job.id)):
        raise HTTPException(404, "That line is not in this project's BOQ.")
    return {"items": resolve_wastage(db, client.id, job.id, key, [i.dict() for i in body.items])}


@router.get("/api/budget/materials")
def budget_materials(request: Request, q: str = "", db: Session = Depends(get_read_db)):
    """Materials from the item master with the rate we last paid, to start a line's cost from."""
    client = require_items_access(request, db, "reports.view")
    return suggest_items(db, client.id, q)


@router.get("/api/jobs/{job_id}/budget/earned-value")
def job_earned_value(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    """Budget against actual by BOQ line and heading: planned value, earned value, actual cost, CPI and SPI."""
    client = require_items_access(request, db, ("budget.view", "budget.edit"))
    return earned_value(db, client.id, job_or_404(db, client.id, job_id))


@router.get("/api/jobs/{job_id}/budget/earned-value.xlsx")
def job_earned_value_export(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, ("budget.view", "budget.edit"))
    job = job_or_404(db, client.id, job_id)
    ev = earned_value(db, client.id, job)
    t = ev["total"]
    blank = lambda v: "" if v is None else v
    preamble = [("BUDGET AGAINST ACTUAL - EARNED VALUE", client.company_name or ""),
                ("Project", "%s %s" % (job.number or "", job.name or ""), "As of", ev["as_of"]),
                ("Budget", t["budget"], "Planned value", t["pv"], "Earned value", t["ev"], "Actual cost", t["ac"]),
                ("CPI", blank(t["cpi"]), "SPI", blank(t["spi"]), "Cost at completion", blank(t["eac"])), ()]
    heads = {h["key"]: h for h in ev["headings"]}
    rows = []
    for h in ev["headings"]:
        rows.append(("  " * h["level"] + (h["item_no"] + " " if h["item_no"] else "") + h["description"], "", h["budget"], h["planned_percent"],
                     h["done_percent"], h["pv"], h["ev"], h["ac"], h["variance"], blank(h["cpi"]), blank(h["spi"]), "OVER" if h["overrun"] else ""))
    rows.append(())
    for l in ev["lines"]:
        rows.append(((l["item_no"] + " " if l["item_no"] else "") + (l["description"] or "")[:120],
                     " > ".join(heads[k]["description"][:30] for k in l["path"] if k in heads), l["budget"], l["planned_percent"], l["done_percent"],
                     l["pv"], l["ev"], l["ac"], l["variance"], blank(l["cpi"]), blank(l["spi"]), "OVER" if l["overrun"] else ""))
    na = ev["not_against_a_line"]
    closing = [(), ("Cost not against a BOQ line", "", "", "", "", "", "", na["material"] + na["subcontract"]),
               ("Total", "", t["budget"], t["planned_percent"], t["done_percent"], t["pv"], t["ev"], t["ac"], t["variance"], blank(t["cpi"]), blank(t["spi"]))]
    return sheet_response(("Heading / line", "Under", "Budget", "Planned %", "Done %", "Planned value", "Earned value", "Actual cost",
                           "EV - AC", "CPI", "SPI", ""), rows, "earned_value_%s.xlsx" % (job.number or "project"), preamble=preamble, closing=closing)


@router.get("/api/jobs/{job_id}/budget.xlsx")
def job_budget_export(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, ("budget.view", "budget.edit"))
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
    # The materials behind the figures above, each with the wastage % it was costed at and where that came from, so the
    # sheet shows the same quantities as the screen and the store's reports. Only materials a wastage figure applies to: a
    # budget with none, and no norms, is the sheet it always was - one row per BOQ line.
    materials = [(r, i) for r in b["rows"] for i in r["items"]
                 if i["kind"] == "MATERIAL" and (i["store_norm_wastage_percent"] is not None or i["budgeting_wastage_percent"])]
    if materials:
        closing += [(), ("MATERIAL WASTAGE USED IN THIS BUDGET", "", "The Store Material Norm % is used where a norm is set for the material on the BOQ item; otherwise the budget's own %."),
                    ("Item", "Material", "Unit", "Qty per unit", "Budgeting wastage %", "Store Norm wastage %", "Effective wastage %", "Used from",
                     "Base quantity", "Wastage quantity", "Final quantity", "Mismatch")]
        closing += [(r["item_no"], i["description"], i["uom"], i["coefficient"], i["budgeting_wastage_percent"],
                     "Not configured" if i["store_norm_wastage_percent"] is None else i["store_norm_wastage_percent"], i["effective_wastage_percent"],
                     "Store Norm" if i["wastage_source"] == "STORE_NORM" else "Budgeting", i["base_quantity"], i["wastage_quantity"], i["final_quantity"],
                     i["mismatch_message"] or "") for r, i in materials]
    return sheet_response(
        ("Item", "Description", "Unit", "Quantity", "BOQ rate", "BOQ amount", "%s per unit" % KIND_LABEL["MATERIAL"],
         "%s per unit" % KIND_LABEL["LABOUR"], "%s per unit" % KIND_LABEL["OTHER"], "Material", "Labour", "Plant & other",
         "Overheads and contingency", "Budget cost", "Profit", "Margin %", "Budgeted"),
        rows, "budget_%s.xlsx" % (job.number or "project"), preamble=preamble, closing=closing)


# The project's Item sheet (services/item_sheet.py): every material the BOQ needs, from the budget, beside what has been
# indented, ordered, issued and is at site. HO QS, purchase and the store all read it.
ITEM_SHEET = ("budget.view", "budget.edit", "purchase.manage", "stores.manage", "stores.receive", "store.reports.view", "store.outward.view")


@router.get("/api/jobs/{job_id}/item-sheet")
def job_item_sheet(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    from app.services.item_sheet import item_sheet
    client = require_items_access(request, db, ITEM_SHEET)
    return item_sheet(db, client.id, job_or_404(db, client.id, job_id))


@router.get("/api/jobs/{job_id}/item-sheet.xlsx")
def job_item_sheet_export(job_id: int, request: Request, db: Session = Depends(get_read_db)):
    from app.services.item_sheet import item_sheet
    client = require_items_access(request, db, ITEM_SHEET)
    job = job_or_404(db, client.id, job_id)
    s = item_sheet(db, client.id, job)
    t = s["totals"] or {}
    preamble = [("ITEM SHEET - MATERIALS THE BOQ NEEDS", client.company_name or ""),
                ("Project", "%s %s" % (job.number or "", job.name or "")),
                ("Materials", t.get("items", 0), "To arrange", t.get("to_arrange", 0), "Budget value", t.get("value", 0),
                 "Value still to arrange", t.get("to_arrange_value", 0)),
                ("Required = BOQ quantity x quantity per unit in the budget x (1 + wastage %). To arrange = required - issued - at site - on its way.",),
                ()]
    rows = []
    for r in s["rows"]:
        rows.append((r["item_code"], r["item_name"] + ("" if r["in_master"] else "  (not in the item master)"), r["uom"], r["without_wastage"], r["required"],
                     r["indented"], r["ordered"], r["on_way"], r["issued"], r["at_site"], r["to_arrange"], r["value"], r["status"]))
        for l in r["lines"]:
            rows.append(("", "    %s%s" % (l["item_no"] + " " if l["item_no"] else "", l["description"][:100]), "%g %s x %g %s, %g%% wastage" % (
                l["boq_qty"], l["boq_unit"], l["per_unit"], l["budget_unit"], l["wastage_percent"]), "", l["required"], "", "", "", l["issued"], "", "", "", ""))
    return sheet_response(("Code", "Material / BOQ line", "Unit", "Without wastage", "Required", "Indented", "Ordered", "On its way", "Issued",
                           "At site", "To arrange", "Budget value", "Status"),
                          rows, "item_sheet_%s.xlsx" % (job.number or "project"), preamble=preamble)
