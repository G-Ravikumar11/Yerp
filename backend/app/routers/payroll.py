"""The payroll endpoints."""
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import PAYROLL_EXCLUDED_STATUSES, PAYSLIP_META_FIELDS, PAYSLIP_PAY_INPUTS
from app.core.audit import log_audit
from app.core.auth import get_client_user
from app.core.currency import esc, money
from app.core.dates import _parse_date
from app.core.notifications import default_from_email, send_email_background
from app.core.serials import next_sequence_number
from app.routers.hr import employee_ytd
from app.schemas.invoicing import SendInvoiceEmail
from app.schemas.payroll import PayrollRunRequest, PayslipCreate
from app.services.email import TRACKING_PIXEL
from app.services.payroll import compute_payslip_figures, find_overlapping_payslip
from app.services.wallet_ai import require_credit
from app.validators.common import validate_email_address


router = APIRouter()


@router.get("/api/payslips")
def get_payslips(request: Request, status: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBPayslip).filter(models.DBPayslip.client_id == client.id)
    if status:
        query = query.filter(models.DBPayslip.status == status)
    payslips = query.order_by(models.DBPayslip.created_at.desc()).all()
    result = []
    for p in payslips:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == p.employee_id).first()
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
    client = get_client_user(request, db)
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
    figures = compute_payslip_figures(emp, body.model_dump())

    ps = models.DBPayslip(
        client_id=client.id, employee_id=body.employee_id, number=ps_number,
        period_start=body.period_start, period_end=body.period_end, pay_date=body.pay_date,
        status="Draft", notes=body.notes, pay_frequency=emp.pay_frequency or "",
        **figures,
    )
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
    client = get_client_user(request, db)
    if not body.period_start or not body.period_end or not body.pay_date:
        raise HTTPException(status_code=400, detail="Period start, period end and pay date are all required")
    p_start, p_end = _parse_date(body.period_start), _parse_date(body.period_end)
    if not p_start or not p_end:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")
    if p_end < p_start:
        raise HTTPException(status_code=400, detail="Period end cannot be before period start")

    # Anyone still on the books gets paid. New starters sit in "onboarding" and
    # leavers in "offboarding" - both are still owed a payslip; only terminated
    # staff are excluded.
    query = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status.notin_(PAYROLL_EXCLUDED_STATUSES),
    )
    if body.employee_ids:
        query = query.filter(models.DBEmployee.id.in_(body.employee_ids))
    employees = query.all()
    if not employees:
        raise HTTPException(status_code=400, detail="No payable employees match this payroll run")

    created, skipped, warnings, total_net, total_gross = [], [], [], 0.0, 0.0
    next_number = next_sequence_number(db, models.DBPayslip, client.id, "PS-")
    seq = int(next_number.split("-")[1])

    for emp in employees:
        clash = find_overlapping_payslip(db, client.id, emp.id, body.period_start, body.period_end)
        if clash:
            if body.skip_existing:
                skipped.append({
                    "employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
                    "reason": f"already covered by {clash.number}",
                })
                continue
            raise HTTPException(
                status_code=409,
                detail=f"{emp.first_name} {emp.last_name} already has payslip {clash.number} for this period",
            )

        hours = 0.0
        if body.include_attendance_hours:
            records = db.query(models.DBAttendance).filter(
                models.DBAttendance.employee_id == emp.id,
                models.DBAttendance.client_id == client.id,
                models.DBAttendance.date >= body.period_start,
                models.DBAttendance.date <= body.period_end,
            ).all()
            hours = round(sum(r.total_hours or 0 for r in records), 2)

        ot_hours = round(sum(
            log.hours or 0 for log in db.query(models.DBOvertimeLog).filter(
                models.DBOvertimeLog.employee_id == emp.id,
                models.DBOvertimeLog.client_id == client.id,
                models.DBOvertimeLog.date >= body.period_start,
                models.DBOvertimeLog.date <= body.period_end,
                models.DBOvertimeLog.status == "announced",
            ).all()
        ), 2)

        figures = compute_payslip_figures(emp, {
            "hours_worked": hours, "overtime_hours": ot_hours,
            "bonus": emp.bonus or 0, "allowances": emp.allowances or 0,
        })
        ps = models.DBPayslip(
            client_id=client.id, employee_id=emp.id, number=f"PS-{seq:04d}",
            period_start=body.period_start, period_end=body.period_end, pay_date=body.pay_date,
            status="Draft", pay_frequency=emp.pay_frequency or "", **figures,
        )
        seq += 1
        db.add(ps)
        total_net += figures["net_pay"]
        total_gross += figures["gross_pay"]
        created.append({
            "employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
            "number": ps.number, "gross_pay": figures["gross_pay"], "net_pay": figures["net_pay"],
        })
        # A zero-value payslip is almost always missing data (an hourly worker
        # with no attendance logged) rather than a genuine nil payment. Surface
        # it instead of quietly paying someone nothing.
        if figures["gross_pay"] <= 0:
            warnings.append({
                "employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
                "number": ps.number,
                "reason": "no salary and no hours recorded for this period - payslip is zero",
            })

    if created:
        # Priced per payslip; charged once for the batch so a part-run cannot
        # be billed twice.
        require_credit(db, client.id, "payroll_run", len(created),
                       f"{body.period_start}..{body.period_end}")
    log_audit(db, client.id, "payroll_run", "payslip", None, f"{body.period_start}..{body.period_end}",
              f"{len(created)} payslips, net {total_net:.2f}", request)
    db.commit()
    return {
        "message": f"Generated {len(created)} payslip(s)",
        "created": created, "skipped": skipped, "warnings": warnings,
        "total_gross": money(total_gross), "total_net": money(total_net),
        "period_start": body.period_start, "period_end": body.period_end, "pay_date": body.pay_date,
    }


@router.get("/api/payslips/{ps_id}")
def get_payslip(ps_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == ps.employee_id).first()
    settings_rows = db.query(models.DBSettings).filter(models.DBSettings.client_id == client.id).all()
    settings_map = {s.key: s.value for s in settings_rows}
    dept_name = ""
    if emp and emp.department_id:
        dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == emp.department_id).first()
        dept_name = dept.name if dept else ""
    ytd = employee_ytd(ps.employee_id, request, (ps.period_end or ps.pay_date or "")[:4], db) if emp else {}
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
        } if emp else {},
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
    client = get_client_user(request, db)
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

    inputs = {key: getattr(ps, key) for key in PAYSLIP_PAY_INPUTS}
    for key in PAYSLIP_PAY_INPUTS:
        if key in body and body[key] is not None:
            inputs[key] = body[key]

    for key, val in compute_payslip_figures(emp, inputs).items():
        setattr(ps, key, val)

    log_audit(db, client.id, "payslip_updated", "payslip", ps.id, ps.number, f"Net: {ps.net_pay:.2f}", request)
    db.commit()
    return {
        "message": "Payslip updated",
        "gross_pay": ps.gross_pay, "total_deductions": ps.total_deductions, "net_pay": ps.net_pay,
    }


@router.post("/api/payslips/{ps_id}/mark-paid")
def mark_payslip_paid(ps_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
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
    client = get_client_user(request, db)
    ps = db.query(models.DBPayslip).filter(models.DBPayslip.id == ps_id, models.DBPayslip.client_id == client.id).first()
    if not ps:
        raise HTTPException(status_code=404, detail="Payslip not found")
    ps.status = "Sent" if ps.sent else "Draft"
    log_audit(db, client.id, "payslip_unmarked_paid", "payslip", ps.id, ps.number, "", request)
    db.commit()
    return {"message": "Payslip reopened", "status": ps.status}


@router.delete("/api/payslips/{ps_id}")
def delete_payslip(ps_id: int, request: Request, force: bool = False, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
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
    client = get_client_user(request, db)
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
