"""The payroll endpoints."""
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, selectinload

from app import models
from app.db import get_db, get_read_db

from app.constants.common import PAYROLL_EXCLUDED_STATUSES, PAYSLIP_META_FIELDS, PAYSLIP_PAY_INPUTS
from app.core.audit import log_audit
from app.core.queries import by_id, prime
from app.core.auth import require_payroll_editor, require_people_admin
from app.core.currency import esc, money
from app.core.dates import _parse_date
from app.core.notifications import default_from_email, send_email_background
from app.core.serials import next_sequence_number
from app.documents import payslip as payslip_sheet
from app.documents.letterhead import letterhead
from app.services.hr import ytd_totals
from app.schemas.invoicing import SendInvoiceEmail
from app.schemas.payroll import PayrollRunRequest, PayslipCreate
from app.services.email import TRACKING_PIXEL
from app.services.salary_structure import (BASES, COUNTS_AS, KINDS, attach_lines, components, default_counts_as, ensure_structure,
                                           structure_lines)
from app.services.payroll import compute_payslip_figures, find_overlapping_payslip, auto_payroll_enabled, generate_payroll, pay_period_days, set_auto_payroll
from app.services.wallet_ai import require_credit
from app.validators.common import validate_email_address


router = APIRouter()

REGISTER_LIMIT = 500          # payslips in one register download


@router.get("/api/payslips")
def get_payslips(request: Request, status: str = "", db: Session = Depends(get_read_db)):
    client = require_payroll_editor(request, db)
    query = db.query(models.DBPayslip).filter(models.DBPayslip.client_id == client.id)
    if status:
        query = query.filter(models.DBPayslip.status == status)
    payslips = query.order_by(models.DBPayslip.created_at.desc()).all()
    prime(db, models.DBEmployee, [p.employee_id for p in payslips])
    result = []
    for p in payslips:
        emp = by_id(db, models.DBEmployee, p.employee_id)
        result.append({
            "id": p.id, "number": p.number,
            "employee_id": p.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "",
            "employee_email": emp.email if emp else "",
            "period_start": p.period_start, "period_end": p.period_end,
            "pay_date": p.pay_date, "gross_pay": p.gross_pay,
            "tax_amount": p.tax_amount, "total_deductions": p.total_deductions,
            "net_pay": p.net_pay, "status": p.status, "sent": p.sent,
            "created_at": p.created_at,
        })
    return result


@router.post("/api/payslips")
def create_payslip(request: Request, body: PayslipCreate, allow_overlap: bool = False, db: Session = Depends(get_db)):
    client = require_payroll_editor(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == body.employee_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if body.period_start and body.period_end:
        p_start, p_end = _parse_date(body.period_start), _parse_date(body.period_end)
        if p_start and p_end and p_end < p_start:
            raise HTTPException(status_code=400, detail="Period end cannot be before period start")
    if not allow_overlap:
        clash = find_overlapping_payslip(db, client.id, emp.id, body.period_start, body.period_end)
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"Payslip {clash.number} already covers {clash.period_start} to {clash.period_end} for this employee",
            )

    ps_number = next_sequence_number(db, models.DBPayslip, client.id, "PS-")
    lines = structure_lines(db, client.id, emp) if body.use_structure is not False else None
    figures = compute_payslip_figures(emp, body.model_dump(), lines)

    ps = models.DBPayslip(
        client_id=client.id, employee_id=body.employee_id, number=ps_number,
        period_start=body.period_start, period_end=body.period_end, pay_date=body.pay_date,
        status="Draft", notes=body.notes, pay_frequency=emp.pay_frequency or "",
        **figures,
    )
    if lines is not None:
        attach_lines(ps, emp, lines)
    db.add(ps)
    log_audit(db, client.id, "payslip_created", "payslip", None, ps_number,
              f"{emp.first_name} {emp.last_name}: net {figures['net_pay']:.2f}", request)
    db.commit()
    db.refresh(ps)
    return {"id": ps.id, "number": ps.number, "gross_pay": ps.gross_pay, "net_pay": ps.net_pay, "message": "Payslip created"}


@router.post("/api/payroll/run")
def run_payroll(request: Request, body: PayrollRunRequest, db: Session = Depends(get_db)):
    """Generate payslips for a whole pay period in one transaction.

    Replaces the browser looping one request per employee, which had no
    atomicity and silently swallowed per-employee failures.
    """
    client = require_payroll_editor(request, db)
    if not body.period_start or not body.period_end or not body.pay_date:
        raise HTTPException(status_code=400, detail="Period start, period end and pay date are all required")
    p_start, p_end = _parse_date(body.period_start), _parse_date(body.period_end)
    if not p_start or not p_end:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")
    if p_end < p_start:
        raise HTTPException(status_code=400, detail="Period end cannot be before period start")

    result = generate_payroll(db, client.id, body.period_start, body.period_end, body.pay_date,
                              employee_ids=body.employee_ids, include_attendance_hours=body.include_attendance_hours,
                              skip_existing=body.skip_existing)
    created, skipped, warnings = result["created"], result["skipped"], result["warnings"]
    total_net, total_gross = result["total_net"], result["total_gross"]
    log_audit(db, client.id, "payroll_run", "payslip", None, f"{body.period_start}..{body.period_end}",
              f"{len(created)} payslips, net {total_net:.2f}", request)
    db.commit()
    return {
        "message": f"Generated {len(created)} payslip(s)",
        "created": created, "skipped": skipped, "warnings": warnings,
        "total_gross": money(total_gross), "total_net": money(total_net),
        "period_start": body.period_start, "period_end": body.period_end, "pay_date": body.pay_date,
    }


@router.get("/api/payroll/auto")
def get_auto_payroll(request: Request, db: Session = Depends(get_read_db)):
    """Whether payslips are drafted by themselves when a month ends."""
    client = require_payroll_editor(request, db)
    return {"enabled": auto_payroll_enabled(db, client.id)}


@router.put("/api/payroll/auto")
def put_auto_payroll(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """The Master (or HR) turns the automatic monthly payroll on or off."""
    client = require_payroll_editor(request, db)
    require_people_admin(request, db)
    enabled = bool((body or {}).get("enabled"))
    set_auto_payroll(db, client.id, enabled)
    log_audit(db, client.id, "payroll_auto_changed", "settings", None, "auto_payroll",
              "Automatic payroll turned " + ("on" if enabled else "off"), request)
    db.commit()
    return {"enabled": enabled, "message": "Automatic payroll is " + ("on" if enabled else "off")}


def _component_out(c):
    return {"id": c.id, "name": c.name, "kind": c.kind, "basis": c.basis, "percent": c.percent or 0.0,
            "counts_as": c.counts_as or default_counts_as(c.kind), "is_active": bool(c.is_active), "sort_order": c.sort_order}


def _component_values(body, current=None):
    """The fields of one component, checked. `current` is what it already is, for an edit that names only some of them."""
    cur = current or {}
    name = (body.get("name", cur.get("name")) or "").strip()
    kind = body.get("kind", cur.get("kind", "earning"))
    basis = body.get("basis", cur.get("basis", "percent"))
    if not name or len(name) > 60:
        raise HTTPException(status_code=400, detail="Give the component a name of up to 60 characters.")
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="A component is an earning or a deduction.")
    if basis not in BASES:
        raise HTTPException(status_code=400, detail="A component is a percentage of the monthly salary, or typed by hand on each payslip.")
    try:
        percent = float(body.get("percent", cur.get("percent", 0)) or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="The percentage must be a number.")
    if basis == "percent" and not 0 <= percent <= 100:
        raise HTTPException(status_code=400, detail="The percentage must be between 0 and 100.")
    counts_as = body.get("counts_as", cur.get("counts_as")) or default_counts_as(kind)
    if counts_as not in COUNTS_AS[kind]:
        counts_as = default_counts_as(kind)
    return {"name": name, "kind": kind, "basis": basis, "percent": percent if basis == "percent" else 0.0,
            "counts_as": counts_as, "is_active": bool(body.get("is_active", cur.get("is_active", True)))}


@router.get("/api/salary-structure")
def get_salary_structure(request: Request, db: Session = Depends(get_db)):
    """What a month's pay is made of. Given its starting list the first time it is asked for."""
    client = require_payroll_editor(request, db)
    ensure_structure(db, client.id)
    db.commit()
    return {"base": "the employee's monthly salary", "components": [_component_out(c) for c in components(db, client.id)]}


@router.post("/api/salary-structure")
def add_salary_component(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = require_payroll_editor(request, db)
    ensure_structure(db, client.id)
    values = _component_values(body or {})
    last = max([c.sort_order or 0 for c in components(db, client.id)] or [0])
    row = models.DBPayComponent(client_id=client.id, sort_order=last + 1, **values)
    db.add(row)
    log_audit(db, client.id, "salary_component_added", "salary_structure", None, row.name, "", request)
    db.commit()
    return {"message": "%s added" % row.name, "component": _component_out(row)}


@router.post("/api/salary-structure/reorder")
def reorder_salary_structure(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = require_payroll_editor(request, db)
    rows = {c.id: c for c in components(db, client.id)}
    ids = [i for i in (body or {}).get("ids", []) if i in rows]
    if len(ids) != len(rows):
        raise HTTPException(status_code=400, detail="Send every component once, in the order wanted.")
    for order, i in enumerate(ids, start=1):
        rows[i].sort_order = order
    db.commit()
    return {"message": "Order saved"}


@router.put("/api/salary-structure/{component_id}")
def update_salary_component(component_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = require_payroll_editor(request, db)
    row = db.query(models.DBPayComponent).filter(models.DBPayComponent.id == component_id,
                                                 models.DBPayComponent.client_id == client.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Component not found")
    values = _component_values(body or {}, _component_out(row))
    for key, val in values.items():
        setattr(row, key, val)
    log_audit(db, client.id, "salary_component_changed", "salary_structure", row.id, row.name,
              "%s %s%%" % (row.basis, row.percent), request)
    db.commit()
    return {"message": "%s saved" % row.name, "component": _component_out(row)}


@router.delete("/api/salary-structure/{component_id}")
def delete_salary_component(component_id: int, request: Request, db: Session = Depends(get_db)):
    """Payslips already made keep their own lines, so removing a component changes only the ones made from now on."""
    client = require_payroll_editor(request, db)
    row = db.query(models.DBPayComponent).filter(models.DBPayComponent.id == component_id,
                                                 models.DBPayComponent.client_id == client.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Component not found")
    log_audit(db, client.id, "salary_component_removed", "salary_structure", row.id, row.name, "", request)
    db.delete(row)
    db.commit()
    return {"message": "%s removed" % row.name}


@router.get("/api/payslips/register.xlsx")
def download_payroll_register(request: Request, ids: str = "", db: Session = Depends(get_read_db)):
    """Many payslips in one Excel sheet, a row each, with every column. `ids` is the payslips to include, comma
    separated; none given means every payslip. Declared ahead of the payslip routes so it is not read as an id."""
    client = require_payroll_editor(request, db)
    query = db.query(models.DBPayslip).filter(models.DBPayslip.client_id == client.id)
    if ids.strip():
        try:
            wanted = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="ids must be payslip ids separated by commas")
        query = query.filter(models.DBPayslip.id.in_(wanted))
    slips = query.options(selectinload(models.DBPayslip.lines)).order_by(
        models.DBPayslip.period_end, models.DBPayslip.number).limit(REGISTER_LIMIT + 1).all()
    if not slips:
        raise HTTPException(status_code=404, detail="No payslips to put in the register")
    if len(slips) > REGISTER_LIMIT:
        raise HTTPException(status_code=400, detail="At most %d payslips at a time: narrow it by month first." % REGISTER_LIMIT)
    rows = db.query(models.DBEmployee, models.DBDepartment.name).outerjoin(
        models.DBDepartment, models.DBDepartment.id == models.DBEmployee.department_id).filter(
        models.DBEmployee.id.in_({p.employee_id for p in slips})).all()
    by_emp = {emp.id: (emp, name or "") for emp, name in rows}
    payloads = [payslip_payload(db, client, p, light=True, row=by_emp.get(p.employee_id)) for p in slips]
    months = sorted({(p.period_end or p.period_start or "")[:7] for p in slips} - {""})
    span = months[0] if len(months) == 1 else ("%s to %s" % (months[0], months[-1]) if months else "")
    content = payslip_sheet.register_workbook(payloads, letterhead(db, client)["name"], span)
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Payroll_register_%s.xlsx"' % (span or "all")})


def _payslip_or_404(db, client, ps_id):
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    return ps


@router.get("/api/payslips/{ps_id}")
def get_payslip(ps_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_payroll_editor(request, db)
    return payslip_payload(db, client, _payslip_or_404(db, client, ps_id))


def _download(content, media_type, number, ext):
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (number or "payslip"))
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": 'attachment; filename="Payslip_%s.%s"' % (safe, ext)})


@router.get("/api/payslips/{ps_id}/pdf")
def download_payslip_pdf(ps_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The payslip as a PDF, with every column of the sheet."""
    client = require_payroll_editor(request, db)
    if not payslip_sheet.form_pdf.PDF_AVAILABLE:
        raise HTTPException(503, "The PDF library is not installed on this server; the Excel file is still available.")
    p = payslip_payload(db, client, _payslip_or_404(db, client, ps_id))
    return _download(payslip_sheet.pdf_bytes(p), "application/pdf", p["number"], "pdf")


@router.get("/api/payslips/{ps_id}/xlsx")
def download_payslip_xlsx(ps_id: int, request: Request, db: Session = Depends(get_read_db)):
    """The payslip as an Excel workbook, with every column of the sheet."""
    client = require_payroll_editor(request, db)
    p = payslip_payload(db, client, _payslip_or_404(db, client, ps_id))
    return _download(payslip_sheet.workbook(p), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", p["number"], "xlsx")


def payslip_payload(db, client, ps, light=False, row=None):
    """A payslip with its employee and the day counts. `light` leaves out the company's head and the year to date,
    which a register of many payslips does not need; `row` is the employee and department name when already read."""
    # The employee with their department's name in one read, the totals straight from the payslips: this page made
    # fourteen round trips to the database, several of them the same lookup twice.
    if row is None and not light:
        row = db.query(models.DBEmployee, models.DBDepartment.name).outerjoin(
            models.DBDepartment, models.DBDepartment.id == models.DBEmployee.department_id).filter(
            models.DBEmployee.id == ps.employee_id).first()
    emp, dept_name = (row[0], row[1] or "") if row else (None, "")
    settings_rows = [] if light else db.query(models.DBSettings.key, models.DBSettings.value).filter(models.DBSettings.client_id == client.id).all()
    settings_map = {k: v for k, v in settings_rows}
    ytd = ytd_totals(db, client.id, ps.employee_id, (ps.period_end or ps.pay_date or "")[:4]) if emp and not light else {}
    return {
        "id": ps.id, "number": ps.number,
        "employee_id": ps.employee_id,
        "ytd": ytd,
        "employee": {
            "full_name": f"{emp.first_name} {emp.last_name}" if emp else "",
            "employee_id": emp.employee_id if emp else "",
            "email": emp.email if emp else "",
            "job_title": emp.job_title if emp else "",
            "level": emp.level if emp else "",
            "department_name": dept_name, "bank_name": emp.bank_name if emp else "",
            "bank_account": emp.bank_account if emp else "", "tax_id": emp.tax_id if emp else "",
            "pay_frequency": emp.pay_frequency if emp else "",
            "start_date": emp.start_date if emp else "", "work_location": emp.work_location if emp else "",
            "uan_no": emp.uan_no or "", "esi_no": emp.esi_no or "",
            "aadhaar_masked": ("XXXX XXXX " + emp.aadhaar_no[-4:]) if emp.aadhaar_no else "",
        } if emp else {},
        "days": pay_period_days(db, client.id, emp, ps),
        "period_start": ps.period_start, "period_end": ps.period_end, "pay_date": ps.pay_date,
        "hours_worked": ps.hours_worked, "overtime_hours": ps.overtime_hours, "overtime_rate": ps.overtime_rate,
        "basic_salary": ps.basic_salary, "overtime_pay": ps.overtime_pay,
        "bonus": ps.bonus, "allowances": ps.allowances, "gross_pay": ps.gross_pay,
        "tax_amount": ps.tax_amount, "insurance": ps.insurance, "retirement": ps.retirement,
        "other_deductions": ps.other_deductions, "total_deductions": ps.total_deductions,
        # A standing deduction on the employee record is inside the total but
        # was never one of the shown lines, so a payslip did not add up.
        # Derived rather than stored, so payslips already issued reconcile too.
        "standing_deduction": money(
            (ps.total_deductions or 0) - (ps.tax_amount or 0) - (ps.insurance or 0)
            - (ps.retirement or 0) - (ps.other_deductions or 0)),
        "net_pay": ps.net_pay, "status": ps.status, "sent": ps.sent, "notes": ps.notes,
        # The pay as the company's salary structure made it, line by line; empty for a payslip made without one.
        "monthly_salary": (emp.salary or 0) if emp else 0,
        "lines": [{"id": l.id, "name": l.name, "kind": l.kind, "basis": l.basis, "percent": l.percent,
                   "counts_as": l.counts_as, "amount": l.amount} for l in ps.lines],
        "company": {
            "name": settings_map.get("company_name", "") or (client.company_name or ""),
            "address": settings_map.get("company_address", "") or (client.address or ""),
            "email": settings_map.get("email", "") or (client.email or ""),
            "phone": settings_map.get("phone_number", "") or (client.phone_number or ""),
            "abn": settings_map.get("company_abn", "") or (client.abn or ""),
            "logo_url": client.logo_url or "",
        },
    }


@router.put("/api/payslips/{ps_id}")
def update_payslip(ps_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Edit a payslip and re-derive gross/net.

    Previously the totals were frozen while the components were editable, so an
    edited payslip reported a net figure that no longer matched its own lines.
    """
    client = require_payroll_editor(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if ps.status == "Paid":
        raise HTTPException(status_code=409, detail="A paid payslip cannot be edited")
    body = body or {}
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == ps.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    for key in PAYSLIP_META_FIELDS:
        if key in body and body[key] is not None:
            setattr(ps, key, body[key])

    if body.get("reapply_structure"):
        fresh = structure_lines(db, client.id, emp)
        if fresh is None:
            raise HTTPException(status_code=400, detail="The salary structure does not apply to this employee: it needs a monthly salary.")
        attach_lines(ps, emp, fresh)
    lines = list(ps.lines) or None
    if lines and body.get("lines") and not body.get("reapply_structure"):
        by_id = {line.id: line for line in lines}
        for item in body["lines"]:
            try:
                line, amount = by_id[int(item.get("id"))], float(item.get("amount"))
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Each line needs the id of one of this payslip's lines and an amount.")
            if amount < 0:
                raise HTTPException(status_code=400, detail="%s cannot be a negative amount." % line.name)
            line.amount = money(amount)

    inputs = {key: getattr(ps, key) for key in PAYSLIP_PAY_INPUTS}
    for key in PAYSLIP_PAY_INPUTS:
        if key in body and body[key] is not None:
            inputs[key] = body[key]
    if lines:
        # The lines own the basic pay, allowances, PF, insurance and other deductions. The tax follows the new gross
        # unless it was given.
        inputs["tax_amount"] = body.get("tax_amount")

    for key, val in compute_payslip_figures(emp, inputs, lines).items():
        setattr(ps, key, val)

    log_audit(db, client.id, "payslip_updated", "payslip", ps.id, ps.number, f"Net: {ps.net_pay:.2f}", request)
    db.commit()
    return {
        "message": "Payslip updated",
        "gross_pay": ps.gross_pay, "total_deductions": ps.total_deductions, "net_pay": ps.net_pay,
    }


@router.post("/api/payslips/{ps_id}/mark-paid")
def mark_payslip_paid(ps_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_payroll_editor(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    ps.status = "Paid"
    ps.pay_date = ps.pay_date or datetime.now().strftime("%Y-%m-%d")
    log_audit(db, client.id, "payslip_marked_paid", "payslip", ps.id, ps.number, f"Net: {ps.net_pay}", request)
    db.commit()
    return {"message": "Payslip marked as paid"}


@router.post("/api/payslips/{ps_id}/unmark-paid")
def unmark_payslip_paid(ps_id: int, request: Request, db: Session = Depends(get_db)):
    """Undo a mark-as-paid entered by mistake."""
    client = require_payroll_editor(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    ps.status = "Sent" if ps.sent else "Draft"
    log_audit(db, client.id, "payslip_unmarked_paid", "payslip", ps.id, ps.number, "", request)
    db.commit()
    return {"message": "Payslip reopened", "status": ps.status}


@router.delete("/api/payslips/{ps_id}")
def delete_payslip(ps_id: int, request: Request, force: bool = False, db: Session = Depends(get_db)):
    client = require_payroll_editor(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if ps.status == "Paid" and not force:
        raise HTTPException(
            status_code=409,
            detail="This payslip is marked as paid. Reopen it first, or pass force=true to delete anyway.",
        )
    log_audit(db, client.id, "payslip_deleted", "payslip", ps.id, ps.number, f"Net: {ps.net_pay}", request)
    db.delete(ps)
    db.commit()
    return {"message": "Payslip deleted"}


@router.post("/api/payslips/{ps_id}/send")
def send_payslip_email(ps_id: int, request: Request, background_tasks: BackgroundTasks, payload: Optional[SendInvoiceEmail] = None, db: Session = Depends(get_db)):
    if payload is None:
        payload = SendInvoiceEmail()
    client = require_payroll_editor(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == ps.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not emp.email or not validate_email_address(emp.email):
        raise HTTPException(status_code=400, detail="Invalid employee email address")

    settings_rows = db.query(models.DBSettings).filter(models.DBSettings.client_id == client.id).all()
    settings_map = {s.key: s.value for s in settings_rows}
    company_name = settings_map.get("company_name", "") or client.company_name or "Billing"
    company_email = settings_map.get("email", "") or client.email or ""
    company_phone = settings_map.get("phone_number", "") or client.phone_number or ""
    company_address = settings_map.get("company_address", "") or client.address or ""

    from_email = default_from_email()
    sender_name = os.getenv("FROM_NAME", "Y ERP")
    from_header = f"{sender_name} <{from_email}>"
    subject = f"Payslip {ps.number} from {company_name}"

    logo_data = client.logo_url or ""
    logo_html = f'<div style="margin-bottom:24px;"><img src="{esc(logo_data)}" style="max-height:48px;max-width:200px;"></div>' if logo_data else ""

    body_text = f"""Hello {esc(emp.first_name)},

Please find your payslip {ps.number} for the period {ps.period_start} to {ps.period_end}.

Pay Date: {ps.pay_date}
Gross Pay: \u00a3{ps.gross_pay:.2f}
Tax: \u00a3{ps.tax_amount:.2f}
Total Deductions: \u00a3{ps.total_deductions:.2f}
Net Pay: \u00a3{ps.net_pay:.2f}

Best regards,
{company_name}
{company_address}
{company_email}
{company_phone}"""

    html_body = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,Helvetica,sans-serif;color:#1e293b;margin:0;padding:0;background-color:#f1f5f9;">
<div style="max-width:600px;margin:0 auto;padding:40px 20px;">
<div style="background:#fff;border-radius:12px;overflow:hidden;">
<div style="background-color:#0f172a;padding:40px;text-align:center;">
{logo_html}
<h1 style="font-size:32px;font-weight:800;color:#fff;margin:0 0 8px 0;">PAYSLIP</h1>
<p style="font-size:16px;color:#94a3b8;margin:0;">{esc(ps.number)}</p>
<div style="margin-top:16px;display:inline-block;background-color:#0ea5e9;padding:8px 20px;border-radius:20px;">
<span style="font-size:14px;color:#fff;font-weight:600;">Net Pay: &pound;{ps.net_pay:.2f}</span>
</div>
</div>
<div style="background-color:#f8fafc;padding:16px 40px;border-bottom:1px solid #e2e8f0;">
<div style="font-size:13px;color:#475569;"><strong style="color:#1e293b;">{esc(company_name)}</strong>{f' &bull; {esc(company_address)}' if company_address else ''}{f' &bull; {esc(company_email)}' if company_email else ''}</div>
</div>
<div style="padding:40px;">
<p style="font-size:16px;color:#1e293b;margin:0 0 6px 0;">Hello <strong>{esc(emp.first_name)}</strong>,</p>
<p style="font-size:14px;color:#64748b;margin:0 0 24px 0;">Here's your payslip from <strong>{esc(company_name)}</strong> for the period {esc(ps.period_start)} to {esc(ps.period_end)}.</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:24px;">
<tr>
<td style="background-color:#f1f5f9;border-radius:10px;padding:16px;text-align:center;width:33%;">
<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:4px;">Period Start</div>
<div style="font-size:14px;font-weight:600;">{ps.period_start}</div>
</td>
<td style="width:10px;"></td>
<td style="background-color:#f1f5f9;border-radius:10px;padding:16px;text-align:center;width:33%;">
<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:4px;">Period End</div>
<div style="font-size:14px;font-weight:600;">{ps.period_end}</div>
</td>
<td style="width:10px;"></td>
<td style="background-color:#f1f5f9;border-radius:10px;padding:16px;text-align:center;width:33%;">
<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;margin-bottom:4px;">Pay Date</div>
<div style="font-size:14px;font-weight:600;">{ps.pay_date}</div>
</td>
</tr>
</table>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:24px;">
<tr style="background-color:#f8fafc;"><th style="padding:10px 16px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;border-bottom:2px solid #e2e8f0;">Description</th><th style="padding:10px 16px;text-align:right;font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;border-bottom:2px solid #e2e8f0;">Amount</th></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;font-size:14px;">Basic Salary</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;font-weight:600;font-size:14px;">&pound;{ps.basic_salary:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;font-size:14px;">Overtime Pay</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;font-weight:600;font-size:14px;">&pound;{ps.overtime_pay:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;font-size:14px;">Bonus</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;font-weight:600;font-size:14px;">&pound;{ps.bonus:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;font-size:14px;">Allowances</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;font-weight:600;font-size:14px;">&pound;{ps.allowances:.2f}</td></tr>
<tr style="font-weight:700;background-color:#f0fdf4;"><td style="padding:12px 16px;font-size:14px;">Gross Pay</td><td style="padding:12px 16px;text-align:right;color:#16a34a;font-size:14px;">&pound;{ps.gross_pay:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">Tax</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">-&pound;{ps.tax_amount:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">Insurance</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">-&pound;{ps.insurance:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">Retirement</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">-&pound;{ps.retirement:.2f}</td></tr>
<tr><td style="padding:10px 16px;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">Other Deductions</td><td style="padding:10px 16px;text-align:right;border-bottom:1px solid #f1f5f9;color:#dc2626;font-size:14px;">-&pound;{ps.other_deductions:.2f}</td></tr>
<tr style="font-weight:700;background-color:#fef2f2;"><td style="padding:12px 16px;font-size:14px;">Total Deductions</td><td style="padding:12px 16px;text-align:right;color:#dc2626;font-size:14px;">-&pound;{ps.total_deductions:.2f}</td></tr>
</table>
<div style="background-color:#0f172a;border-radius:12px;padding:24px;text-align:right;">
<div style="font-size:13px;color:#94a3b8;margin-bottom:4px;">NET PAY</div>
<div style="font-size:32px;font-weight:800;color:#10b981;">&pound;{ps.net_pay:.2f}</div>
</div>
</div>
<div style="padding:24px 40px;background-color:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
<p style="font-size:13px;color:#94a3b8;margin:0;">Thank you for your hard work!</p>
<p style="font-size:12px;color:#64748b;margin:4px 0 0 0;">{esc(company_name)}</p>
<p style="font-size:11px;color:#94a3b8;margin:12px 0 0 0;"><a href="mailto:{from_email}?subject=unsubscribe" style="color:#94a3b8;">Unsubscribe</a> from these notifications</p>
</div>
</div>
</div><img src="{request.base_url}api/payslip/track/open/{ps.tracking_id}" width="1" height="1" style="display:none;" alt="">
</body></html>
"""

    pdf_b64 = payload.pdf_data if payload.pdf_data else None
    pdf_filename = f"{ps.number}.pdf" if pdf_b64 else "payslip.pdf"

    require_credit(db, client.id, "payslip_send", 1, ps.number)

    background_tasks.add_task(send_email_background, emp.email, subject, body_text, from_header, html_body, pdf_b64, pdf_filename, logo_data, client_id=client.id)
    ps.status = "Sent" if ps.status == "Draft" else ps.status
    ps.sent = datetime.now().strftime("%Y-%m-%d")
    db.commit()
    return {"message": "Payslip email sent", "status": ps.status}


@router.get("/api/payslip/track/open/{tracking_id}")
def track_payslip_open(tracking_id: str, db: Session = Depends(get_db)):
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.tracking_id == tracking_id).first()
    if ps:
        ps.open_count = (ps.open_count or 0) + 1
        ps.last_opened = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.commit()
    response = Response(content=TRACKING_PIXEL, media_type="image/gif")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response
