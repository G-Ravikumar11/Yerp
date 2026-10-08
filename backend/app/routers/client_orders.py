"""The client orders endpoints."""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import BUDGET_REPORT_HEADERS
from app.constants.subcontract_orders import WO_COLUMNS, WO_HEADERS
from app.core.audit import log_audit
from app.core.auth import (
    get_client_user,
    require_erp_read,
    require_items_access,
    require_owner,
    require_workorder_access,
    session_employee,
    session_person,
)
from app.core.currency import inr, money, unit_rate
from app.core.files import drop_files_of, file_counts
from app.core.serials import allocate_po_number, next_sequence_number
from app.core.sheets import (
    WO_HEADER_ALIASES,
    map_headers_with,
    mapping_report,
    parse_sheet,
    read_sheet_rows,
    rows_from,
    sheet_note,
    sheet_response,
)
from app.schemas.client_orders import RaisePoIn, WoDecisionIn, WorkOrderIn
from app.services.approvals import (
    _person,
    decide_approval_step,
    owner_confirms_own,
    owner_label,
    start_approval,
)
from app.services.client_orders import budget_report, preload_work_orders
from app.services.hr import employee_name
from app.services.procurement import purchase_order_to_dict
from app.services.projects import job_or_404
from app.services.stores import material_required
from app.services.subcontract_orders import (
    cascade_delete_referrers,
    drop_alerts_about,
    erp_wo_delete_report,
    run_bulk_delete,
    sweep_referrers,
    wo_variations,
    work_order_or_404,
    work_order_statement,
    work_order_to_dict,
)
from app.validators.common import validate_work_order_sheet


router = APIRouter()


@router.post("/api/erp/work-orders/build")
def erp_build_work_order(body: WorkOrderIn, request: Request,
                         db: Session = Depends(get_db)):
    """A work order assembled from codes that already exist.

    The picker only offers finished goods from this tenant's own master, so
    the "code not found" failure a sheet produces cannot arise at all; what is
    left to check is quantities and prices.
    """
    client = require_workorder_access(request, db)
    job = job_or_404(db, client.id, body.job_id)
    if not body.lines:
        raise HTTPException(400, "Add at least one line")

    master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == client.id, models.DBItem.kind == "FG").all()}

    seen, lines = set(), []
    for index, line in enumerate(body.lines, start=1):
        code = (line.code or "").strip().upper()
        if not code:
            raise HTTPException(400, "Line %d: choose an item" % index)
        if code not in master:
            raise HTTPException(400, "Line %d: %s is not a finished goods code" % (index, code))
        if code in seen:
            raise HTTPException(400, "Line %d: %s is already on this order" % (index, code))
        seen.add(code)
        qty, rate = money(line.qty), unit_rate(line.rate)
        if qty <= 0:
            raise HTTPException(400, "Line %d: quantity must be more than zero" % index)
        if rate < 0:
            raise HTTPException(400, "Line %d: rate cannot be negative" % index)
        item = master[code]
        lines.append({"fg_code": code, "item_name": item.item_name,
                      "description": (line.description or item.description or "").strip(),
                      "qty": qty, "uom": item.units_of_measure,
                      "rate": rate, "amount": money(qty * rate)})

    total = money(sum(l["amount"] for l in lines))
    if total <= 0:
        # Every line priced at nothing. The order would be created, sit in the
        # list at zero, and measure and bill at zero for ever - so it is
        # refused here rather than discovered three screens later.
        raise HTTPException(
            400, "Every line is priced at zero, so this order is worth nothing. "
                 "Put a rate against each line before creating it.")
    wo = models.DBWorkOrder(
        client_id=client.id, job_id=job.id,
        number=next_sequence_number(db, models.DBWorkOrder, client.id, "WO-"),
        order_date=datetime.now().strftime("%Y-%m-%d"),
        reference=(body.reference or "").strip(), notes=(body.notes or "").strip(),
        status="Draft", total_value=total)
    db.add(wo)
    db.flush()
    for l in lines:
        db.add(models.DBWorkOrderLine(work_order_id=wo.id, **l))
        # Remember what this code was sold at, so the next order opens with a
        # rate already in it. An offer, not a rule: prices move on a contract
        # and whoever is pricing the next one can still change it.
        if l["rate"]:
            master[l["fg_code"]].last_rate = l["rate"]
    log_audit(db, client.id, "work_order_created", "work_order", wo.id, wo.number,
              "%s - %d line(s) - %s" % (job.number, len(lines), total), request)
    db.commit()
    db.refresh(wo)
    return {"ok": True, "work_order": work_order_to_dict(db, wo, detail=True),
            "message": "%s created with %d line(s)." % (wo.number, len(lines))}


@router.post("/api/erp/work-orders/analyse")
async def erp_wo_analyse(request: Request, file: UploadFile = File(...),
                         sheet: str = Form(""), db: Session = Depends(get_db)):
    """Read a work-order sheet and price it, without saving anything."""
    client = require_workorder_access(request, db)
    header, body = await read_sheet_rows(file, sheet)
    mapping, unmapped = map_headers_with(header, WO_HEADER_ALIASES)
    if "fg_code" not in mapping.values():
        raise HTTPException(400, "No item code column found. Expected something "
                                 "headed 'FG Code', 'Item Code' or 'SKU'." + sheet_note())

    master = {i.item_code.upper(): i for i in db.query(models.DBItem).filter(
        models.DBItem.client_id == client.id, models.DBItem.kind == "FG").all()}

    lines, seen, repairs = [], {}, []
    for row in rows_from(header, body, mapping):
        line = row["_line"]
        code = (row.get("fg_code") or "").strip().upper()
        qty, rate = money(row.get("qty") or 0), unit_rate(row.get("rate") or 0)
        problems = []

        if not code:
            problems.append({"field": "code", "message": "An item code is required", "fix": None})
        elif code not in master:
            # The gate: an unknown code cannot be priced, delivered or costed.
            near = [c for c in master if c.startswith(code[:3])][:1]
            problems.append({"field": "code",
                             "message": "Not in the item master. Add this finished goods code first.",
                             "fix": near[0] if near else None})
        elif code in seen:
            problems.append({"field": "code",
                             "message": "Already on line %d. Combine the quantities." % seen[code],
                             "fix": None})
        else:
            seen[code] = line
        if qty <= 0:
            problems.append({"field": "qty", "message": "Quantity must be more than zero", "fix": None})
        if rate < 0:
            problems.append({"field": "rate", "message": "Rate cannot be negative", "fix": None})

        item = master.get(code)
        if item and not (row.get("description") or "").strip():
            row["description"] = item.description or item.item_name
            repairs.append({"line": line, "field": "description", "from": "",
                            "to": row["description"], "note": "taken from the item master"})

        lines.append({"_line": line, "code": code,
                      "item_name": item.item_name if item else (row.get("item_name") or ""),
                      "description": (row.get("description") or "").strip(),
                      "uom": item.units_of_measure if item else (row.get("uom") or ""),
                      "qty": qty, "rate": rate, "amount": money(qty * rate),
                      "_problems": problems})

    blocked = [l for l in lines if l["_problems"]]
    return {
        "ok": not blocked,
        "mapping": mapping_report(header, mapping),
        "unmapped_headers": unmapped,
        "lines": lines, "repairs": repairs,
        "choices": sorted([{"code": i.item_code, "name": i.item_name,
                            "uom": i.units_of_measure} for i in master.values()],
                          key=lambda x: x["code"]),
        "summary": {"total": len(lines), "ready": len(lines) - len(blocked),
                    "blocked": len(blocked),
                    "value": money(sum(l["amount"] for l in lines if not l["_problems"]))},
    }


@router.get("/api/erp/work-orders/template")
def erp_wo_template(request: Request, db: Session = Depends(get_db)):
    require_workorder_access(request, db)
    return sheet_response(WO_HEADERS,
                          [["FG0001", "20MM LMS PVC ISI CONDUIT", "Supply", "5000", "Meters", "62.00"]],
                          "work_order_template.xlsx")


@router.post("/api/erp/work-orders/validate")
async def erp_wo_validate(request: Request, file: UploadFile = File(...),
                          sheet: str = Form(""), db: Session = Depends(get_db)):
    client = require_workorder_access(request, db)
    rows = await parse_sheet(file, WO_COLUMNS, WO_HEADER_ALIASES, sheet)
    return validate_work_order_sheet(db, client.id, rows)


@router.post("/api/erp/work-orders")
async def erp_wo_upload(request: Request, file: UploadFile = File(...),
                        job_id: int = Form(...), sheet: str = Form(""),
                        db: Session = Depends(get_db)):
    client = require_workorder_access(request, db)
    job = job_or_404(db, client.id, job_id)

    rows = await parse_sheet(file, WO_COLUMNS, WO_HEADER_ALIASES, sheet)
    result = validate_work_order_sheet(db, client.id, rows)
    if not result["ok"]:
        return {**result, "work_order": None,
                "message": "Nothing was saved. Fix the errors and try again."}

    wo = models.DBWorkOrder(
        client_id=client.id, job_id=job.id,
        number=next_sequence_number(db, models.DBWorkOrder, client.id, "WO-"),
        order_date=datetime.now().strftime("%Y-%m-%d"),
        status="Draft", total_value=result["total_value"])
    db.add(wo)
    db.flush()
    for l in result["lines"]:
        db.add(models.DBWorkOrderLine(work_order_id=wo.id, **l))

    log_audit(db, client.id, "work_order_created", "work_order", wo.id, wo.number,
              f"{job.number} · {len(result['lines'])} line(s) · {result['total_value']}", request)
    db.commit()
    db.refresh(wo)
    return {**result, "work_order": work_order_to_dict(db, wo, detail=True),
            "message": f"{wo.number} created with {len(result['lines'])} line(s)."}


@router.get("/api/erp/work-orders")
def erp_list_work_orders(request: Request, job_id: int = 0,
                         db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    query = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.client_id == client.id)
    if job_id:
        query = query.filter(models.DBWorkOrder.job_id == job_id)
    orders = query.order_by(models.DBWorkOrder.id.desc()).limit(300).all()
    pre = preload_work_orders(db, client.id, orders)
    rows = [work_order_to_dict(db, w, pre=pre) for w in orders]
    counts = file_counts(db, client.id, "work_order", [r["id"] for r in rows])
    for r in rows:
        r["files"] = counts.get(r["id"], {"files": 0, "drawings": 0, "photos": 0})
    return {"work_orders": rows, "summary": {
        "count": len(rows),
        "awaiting_approval": len([r for r in rows if r["approval_status"] == "pending"]),
        "total_value": money(sum(r["total_value"] for r in rows)),
        "total_margin": money(sum(r["margin"] for r in rows if r["budgeted"])),
    }}


@router.get("/api/erp/work-orders/{wo_id}")
def erp_get_work_order(wo_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return work_order_to_dict(db, work_order_or_404(db, client.id, wo_id), detail=True)


@router.post("/api/erp/work-orders/{wo_id}/submit")
def erp_wo_submit(wo_id: int, request: Request, body: dict = None,
                  db: Session = Depends(get_db)):
    """Send a work order up the same approval chain as everything else.

    Refused before it is budgeted: approving an order without knowing what it
    costs is approving a number, not a margin.
    """
    client = require_workorder_access(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    if (wo.approval_status or "") == "approved":
        return {"ok": True, "status": "approved", "chain": [], "message": wo.number + " is already approved."}
    if not db.query(models.DBBomLine).filter(
            models.DBBomLine.work_order_id == wo.id).count():
        raise HTTPException(
            409, "Allocate the budget first - there is no cost to approve against.")

    staff = session_employee(request, db)
    submitted_by = staff.id if staff else (body or {}).get("submitted_by")
    if not submitted_by:
        emp = db.query(models.DBEmployee).filter(
            models.DBEmployee.client_id == client.id,
            models.DBEmployee.email == client.email).first()
        submitted_by = emp.id if emp else None
    actor = employee_name(staff) if staff else (client.contact_name or client.email)
    if not submitted_by:
        # The owner, with no staff record of their own: it waits for the
        # owner's own sign-off rather than approving itself.
        return owner_confirms_own(db, client.id, wo, "work_order", request, actor)
    return start_approval(db, client.id, wo, "work_order", submitted_by, request, actor=actor)


@router.post("/api/erp/work-orders/{wo_id}/decide")
def erp_wo_decide(wo_id: int, body: WoDecisionIn, request: Request, db: Session = Depends(get_db)):
    """Approve or send back a client work order from its own row - the step
    it is waiting at, by the person it is waiting with (or the owner)."""
    client, emp = session_person(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    if (wo.approval_status or "") != "pending":
        raise HTTPException(409, wo.number + " is not waiting for approval.")
    step = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "work_order", models.DBApprovalChain.entity_id == wo.id,
        models.DBApprovalChain.step == (wo.current_approval_step or 0),
        models.DBApprovalChain.status == "pending").first()
    if step is None:
        raise HTTPException(409, "No step is waiting on this order.")
    if emp is not None and step.approver_id != emp.id:
        raise HTTPException(403, "%s is waiting with %s." % (
            wo.number, owner_label(db, client.id) if step.approver_id is None else _person(db, step.approver_id)))
    decision = (body.decision or "").strip().lower()
    note = (body.note or "").strip()
    if decision == "approve" and not note:
        note = "Approved"
    actor = employee_name(emp) if emp else (client.contact_name or client.email)
    out = decide_approval_step(db, step, decision, note, request, client.id, actor=actor)
    db.refresh(wo)
    return dict(out, work_order=work_order_to_dict(db, wo))


@router.get("/api/erp/work-orders/{wo_id}/delete-preview")
def erp_delete_work_order_preview(wo_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    require_owner(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    rep = erp_wo_delete_report(db, client, wo)
    return {"numbers": [wo.number], "counts": rep["counts"], "blockers": [], "warnings": rep["warnings"],
            "can_delete": True}


@router.delete("/api/erp/work-orders/{wo_id}")
def erp_delete_work_order(wo_id: int, request: Request, db: Session = Depends(get_db)):
    """The owner's alone. Takes the order and everything that hangs off it - its
    measurements, RA bills, variations and budget - away from every screen. An
    order with money received against it is refused."""
    client = get_client_user(request, db)
    require_owner(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    rep = erp_wo_delete_report(db, client, wo)
    drop = lambda q: q.delete(synchronize_session=False)
    bill_ids = [b.id for b in rep["bills"]]
    var_ids = rep["variation_ids"]
    meas_ids = [m.id for m in db.query(models.DBMeasurement.id).filter(models.DBMeasurement.work_order_id == wo.id).all()]
    rel_ids = [r.id for r in db.query(models.DBRetentionRelease.id).filter(models.DBRetentionRelease.work_order_id == wo.id).all()]
    cascade_delete_referrers(db, "work_orders", [wo.id])
    if meas_ids:
        drop(db.query(models.DBMeasurementDimension).filter(models.DBMeasurementDimension.measurement_id.in_(meas_ids)))
        drop_files_of(db, "measurement", meas_ids)
    if bill_ids:
        drop(db.query(models.DBRABillLine).filter(models.DBRABillLine.ra_bill_id.in_(bill_ids)))
        drop(db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.doc_type == "ra_bill", models.DBMoneyEntry.doc_id.in_(bill_ids)))
        drop_alerts_about(db, "ra_bill", bill_ids)
    drop(db.query(models.DBMeasurement).filter(models.DBMeasurement.work_order_id == wo.id))
    drop(db.query(models.DBRABill).filter(models.DBRABill.work_order_id == wo.id))
    if var_ids:
        drop(db.query(models.DBVariationLine).filter(models.DBVariationLine.variation_order_id.in_(var_ids)))
        drop_files_of(db, "variation", var_ids)
    drop(db.query(models.DBVariationOrder).filter(models.DBVariationOrder.work_order_id == wo.id))
    if rel_ids:
        drop(db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.doc_type == "retention_release", models.DBMoneyEntry.doc_id.in_(rel_ids)))
    if bill_ids:
        drop(db.query(models.DBEinvoiceIrn).filter(
            models.DBEinvoiceIrn.doc_type == "ra_bill", models.DBEinvoiceIrn.doc_id.in_(bill_ids)))
    drop(db.query(models.DBRetentionRelease).filter(models.DBRetentionRelease.work_order_id == wo.id))
    line_ids = [l.id for l in db.query(models.DBWorkOrderLine.id).filter(models.DBWorkOrderLine.work_order_id == wo.id).all()]
    sweep_referrers(db, {"work_order_lines": line_ids})
    drop(db.query(models.DBWorkOrderLine).filter(models.DBWorkOrderLine.work_order_id == wo.id))
    drop(db.query(models.DBBomLine).filter(models.DBBomLine.work_order_id == wo.id))
    drop(db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "work_order", models.DBApprovalChain.entity_id == wo.id))
    drop_files_of(db, "work_order", [wo.id])
    # Records that only mention the order stay, and simply no longer point at it.
    for model in (models.DBStockMovement, models.DBStockIssue, models.DBSiteDiary, models.DBEstimate, models.DBRfq):
        db.query(model).filter(model.work_order_id == wo.id).update({"work_order_id": None}, synchronize_session=False)
    sweep_referrers(db, {"work_orders": [wo.id], "ra_bills": bill_ids, "measurements": meas_ids, "variation_orders": var_ids})
    log_audit(db, client.id, "work_order_deleted", "work_order", wo.id, wo.number, "Deleted with %s" % ", ".join(
        "%d %s" % (n, k) for k, n in rep["counts"].items() if n), request)
    db.delete(wo)
    db.commit()
    return {"ok": True, "message": "%s deleted%s." % (wo.number, " everywhere" if any(rep["counts"].values()) else "")}


@router.get("/api/erp/work-orders/{wo_id}/budget-report")
def erp_budget_report(wo_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return budget_report(db, client, work_order_or_404(db, client.id, wo_id))


@router.get("/api/erp/work-orders/{wo_id}/budget-report.xlsx")
def erp_budget_report_xlsx(wo_id: int, request: Request, db: Session = Depends(get_db)):
    """The same report as a workbook, which is where it gets worked on.

    The header block is written above the table rather than into it, so the
    rows underneath stay a rectangle somebody can sort and filter.
    """
    client = require_erp_read(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    report = budget_report(db, client, wo)

    rows = []
    for group in report["groups"]:
        if not group["lines"]:
            rows.append([group["fg_code"], "-  not budgeted", "", "", "",
                         group["qty"], ""])
            continue
        for material in group["lines"]:
            rows.append([group["fg_code"], material["description"], material["qty"],
                         material["uom"], material["rate"], material["wo_qty"],
                         material["amount"]])

    preamble = [
        [report["title"], "", "", "", "", "", report["company"]],
        ["Print Out Date: " + report["printed_at"]],
        ["Fiscal Year: " + report["fiscal_year"]],
        ["Sale order No: " + report["sale_order_no"]],
        ["Project: " + report["project"]],
        [],
    ]
    closing = [
        [],
        ["", "Order value", report["totals"]["value"]],
        ["", "Budgeted cost", report["totals"]["cost"]],
        ["", "Margin", report["totals"]["margin"]],
    ]
    return sheet_response(BUDGET_REPORT_HEADERS, rows,
                          "budget_entry_report_%s.xlsx" % wo.number,
                          preamble=preamble, closing=closing, branded="logo")


@router.post("/api/erp/work-orders/{wo_id}/place-order")
def erp_place_order(wo_id: int, request: Request, db: Session = Depends(get_db)):
    """A draft becomes a placed order.

    Kept as its own step because the moment an order is placed is the moment
    those prices are committed to a customer, and that should be somebody
    pressing a button rather than a side effect of uploading a file.
    """
    client = require_workorder_access(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    # An order placed before placing needed approval ("Placed", never
    # signed) is sent now; only one approved or already waiting is refused.
    if (wo.approval_status or "none") in ("approved", "pending"):
        raise HTTPException(409, wo.number + " is already " + (
            "approved" if wo.approval_status == "approved" else "waiting for approval") + ".")
    if not db.query(models.DBWorkOrderLine).filter(
            models.DBWorkOrderLine.work_order_id == wo.id).count():
        raise HTTPException(409, "There is nothing on this order to place.")
    # Committing prices to a client is signed off like every other order:
    # placing it sends it up the approval route, and it is placed when the
    # last signature is on. The owner placing their own is approved as placed.
    result = erp_wo_submit(wo_id, request, None, db)
    db.refresh(wo)
    if (wo.approval_status or "") == "approved":
        log_audit(db, client.id, "work_order_placed", "work_order", wo.id, wo.number,
                  "Order placed, value %s" % wo.total_value, request)
        db.commit()
        message = wo.number + " placed."
    else:
        message = "%s sent for approval%s. It is placed once approved." % (
            wo.number, (" - with " + work_order_to_dict(db, wo)["waiting_on"]) if work_order_to_dict(db, wo)["waiting_on"] else "")
    return {"ok": True, "work_order": work_order_to_dict(db, wo), "message": message,
            "approval": result if isinstance(result, dict) else {}}


@router.get("/api/erp/work-orders/{wo_id}/export.xlsx")
def erp_work_order_xlsx(wo_id: int, request: Request, db: Session = Depends(get_db)):
    """One work order: what was sold, and the budget behind it if there is one."""
    client = require_erp_read(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    detail = work_order_to_dict(db, wo, detail=True)

    rows = [[l["fg_code"], l["item_name"], l["description"], l["uom"],
             l["qty"], l["rate"], l["amount"]] for l in detail.get("lines", [])]
    closing = [[], ["", "", "", "", "", "Order value", detail["total_value"]]]
    varied = wo_variations(db, wo, datetime.now().strftime("%Y-%m-%d"))
    if varied:
        closing += [[], ["VARIATIONS AGREED ON THIS ORDER", "", "", "", "", "", "%d agreed" % len(varied["variations"])],
                    ["Ref", "Agreed", "What changed", "", "", "", "Value"]]
        closing += [[x["number"], x["date"], (x["reason"] + (" - " if x["reason"] else "") + x["what"]).strip(), "", "", "", x["value"]]
                    for x in varied["variations"]]
        closing += [["", "", "Order value as first placed", "", "", "", varied["original"]],
                    ["", "", "Order value as varied", "", "", "", varied["varied"]]]
    if detail.get("budgeted"):
        closing += [["", "", "", "", "", "Budgeted cost", detail["budget_cost"]],
                    ["", "", "", "", "", "Margin", detail["margin"]]]
        closing += [[], ["Budget - materials consumed"],
                    ["FG Code", "RM Code", "Description", "UOM", "Qty", "Rate", "Amount"]]
        closing += [[b["fg_code"], b["rm_code"], b["rm_name"], b["uom"],
                     b["qty"], b["rate"], b["amount"]] for b in detail.get("bom", [])]

    return sheet_response(
        ["FG Code", "Item Name", "Description", "UOM", "Qty", "Rate", "Amount"],
        rows, "work_order_%s.xlsx" % re.sub(r"[^A-Za-z0-9]+", "_", wo.number or ""),
        preamble=[["Work Order", "", "", "", "", "", client.company_name or ""],
                  ["No: " + (wo.number or "") + "   (" + (wo.status or "") + ")"],
                  ["Job: " + detail.get("job_name", "")],
                  ["Customer: " + detail.get("customer_name", "")],
                  ["Reference: " + (wo.reference or "")],
                  []],
        closing=closing)


@router.get("/api/erp/work-orders/{wo_id}/statement")
def erp_work_order_statement(wo_id: int, request: Request,
                             db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return work_order_statement(db, client, work_order_or_404(db, client.id, wo_id))


@router.get("/api/erp/work-orders/{wo_id}/statement.xlsx")
def erp_work_order_statement_xlsx(wo_id: int, request: Request,
                                  db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    s = work_order_statement(db, client, wo)
    o, p, m = s["order"], s["progress"], s["money"]

    preamble = [
        ("WORK ORDER STATEMENT", client.company_name or ""),
        ("Order", wo.number or "", "Status", wo.status or ""),
        ("Project", s["work_order"].get("job_name", "") or ""),
        (),
        ("Original order value", o["original_value"]),
        ("Variations agreed", o["variations_agreed"]),
        ("Revised order value", o["revised_value"]),
        ("Variations asked for, not agreed", o["variations_pending"]),
        (),
        ("Measured to date", p["measured_value"], "Complete", "%s%%" % p["percent_complete"]),
        ("Left to build", p["left_to_build"]),
        ("Built past the order, not yet varied", p["over_run_not_yet_varied"]),
        (),
        ("Claimed on bills", m["claimed"]),
        ("Certified", m["certified"]),
        ("Paid", m["paid"]),
        ("Certified, awaiting payment", m["awaiting_payment"]),
        ("Measured but not billed", m["measured_not_billed"]),
        ("Retention held", m["retention_held"]),
        ("TDS deducted", m["tds_deducted"]),
        (),
    ]
    headers = ("Item", "Description", "UOM", "Ordered", "Rate", "Ordered value",
               "Measured", "Measured value", "Billed", "Billed value",
               "Unbilled", "Unbilled value", "% measured")
    rows = [(l["fg_code"], l["description"], l["uom"], l["ordered_qty"], l["rate"],
             l["ordered_value"], l["measured_qty"], l["measured_value"],
             l["billed_qty"], l["billed_value"], l["unbilled_qty"],
             l["unbilled_value"], l["percent_measured"]) for l in s["lines"]]
    closing = [(), ("Totals", "", "", "", "", o["revised_value"], "",
                    p["measured_value"], "", m["claimed"], "", m["measured_not_billed"])]
    return sheet_response(headers, rows,
                          "statement_%s.xlsx" % (wo.number or "order").replace("/", "-"),
                          preamble=preamble, closing=closing)


@router.get("/api/erp/work-orders/{wo_id}/requisition")
def material_requisition(wo_id: int, request: Request,
                         db: Session = Depends(get_db)):
    """What still has to be bought for this order. Asking does not buy it."""
    client = require_erp_read(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    rows = material_required(db, client.id, wo)
    short = [r for r in rows if not r["covered"]]
    return {
        "work_order": work_order_to_dict(db, wo),
        "lines": rows,
        "summary": {
            "items": len(rows),
            "to_buy": len(short),
            "value": money(sum(r["amount"] for r in short)),
            "already_covered": len(rows) - len(short),
        },
    }


@router.post("/api/erp/work-orders/{wo_id}/raise-po")
def raise_po_from_bom(wo_id: int, body: RaisePoIn, request: Request,
                      db: Session = Depends(get_db)):
    """Draw up the purchase order the budget already implies.

    It arrives as a draft, priced and quantified, for somebody to check and
    approve - the point is not to spend money automatically, it is that
    nobody should retype a schedule the app already holds.
    """
    client = require_items_access(request, db, ("purchase.manage", "workorders.manage"))
    raiser = session_employee(request, db)
    wo = work_order_or_404(db, client.id, wo_id)
    if not (body.supplier_name or "").strip():
        raise HTTPException(400, "Who is this order with?")

    rows = [r for r in material_required(db, client.id, wo) if not r["covered"]]
    if body.item_codes:
        wanted = {str(c).strip().upper() for c in body.item_codes}
        rows = [r for r in rows if r["item_code"].upper() in wanted]
    if not rows:
        raise HTTPException(
            409, "Nothing on this order still needs buying. The budget is "
                 "covered by what is in the store and what is already on order.")

    amount = money(sum(r["amount"] for r in rows))
    order = models.DBPurchaseOrder(
        client_id=client.id, job_id=wo.job_id,
        number=allocate_po_number(db, client.id),
        supplier_name=body.supplier_name.strip(),
        supplier_email=(body.supplier_email or "").strip(),
        issue_date=datetime.now().strftime("%Y-%m-%d"),
        needed_by=(body.needed_by or ""),
        amount=amount, tax_amount=0.0, total=amount,
        status="Draft", category="material",
        submitted_by=raiser.id if raiser else None, approval_status="none",
        reference=wo.number or "",
        notes="Raised from the budget for %s" % (wo.number or "this order"))
    db.add(order)
    db.flush()
    for r in rows:
        db.add(models.DBPurchaseOrderLineItem(
            order_id=order.id, description=r["item_name"] or r["item_code"],
            item_code=r["item_code"], uom=r["uom"],
            qty=r["to_buy"], price=r["rate"], tax_rate="18%"))
    log_audit(db, client.id, "po_raised_from_bom", "purchase_order", order.id,
              order.number or "", "%s - %d line(s) - %s"
              % (wo.number, len(rows), inr(amount)), request)
    db.commit()
    db.refresh(order)
    return {"ok": True, "order": purchase_order_to_dict(db, order),
            "message": "%s drawn up for %s - %d item%s, %s. Check it before "
                       "approving." % (order.number, body.supplier_name.strip(),
                                       len(rows), "" if len(rows) == 1 else "s",
                                       inr(amount))}


@router.post("/api/erp/work-orders/bulk-delete")
def erp_bulk_delete(body: dict, request: Request, db: Session = Depends(get_db)):
    return run_bulk_delete(body.get("ids"), lambda i: erp_delete_work_order(i, request, db), db)
