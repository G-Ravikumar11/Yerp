"""The invoicing endpoints."""
import io
import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.invoicing import (
    EWAY_DOC_TYPES,
    EWAY_MODES,
    EWAY_SUB_TYPES,
    EWAY_THRESHOLD,
    IRN_CANCEL_HOURS,
    VEHICLE_NO,
)
from app.core.audit import log_audit
from app.core.auth import get_client_user, require_erp_read, require_items_access, session_employee, wo_actor
from app.core.currency import (
    DEFAULT_CURRENCY,
    compute_invoice_totals,
    currency_symbol,
    esc,
    inr,
    line_net_amount,
    money,
    parse_tax_rate,
)
from app.core.dates import ack_datetime, days_after
from app.core.gst import GST_STATES, WORKS_CONTRACT_SAC, our_state, state_from_gstin
from app.core.notifications import default_from_email, notify_employee, send_email_background
from app.core.serials import invoice_prefix_for, next_sequence_number
from app.core.sheets import sheet_response
from app.documents.forms import _pre
from app.routers.employee_portal import employee_create_bill
from app.routers.stores import list_transfers
from app.schemas.invoicing import (
    CompanyGstIn,
    EwayCancelIn,
    EwayGeneratedIn,
    EwayIn,
    EwayVehicleIn,
    InvoiceCreate,
    PaymentCreate,
    RecurringIn,
    SendInvoiceEmail,
)
from app.services.approvals import get_approval_chain_history
from app.services.crm import invoice_overdue_days, norm_name, settled_on
from app.services.invoicing import (
    _eway_apply,
    _eway_set_lines,
    _month_key,
    _signed_qr_data,
    active_irn,
    apply_payment_status,
    einvoice_document,
    eway_dict,
    eway_lines,
    eway_or_404,
    eway_payload,
    eway_places,
    eway_problems,
    eway_totals,
    eway_validity,
    irn_dict,
    next_eway_number,
    parse_irn_input,
    payment_terms_for,
    qr_svg,
    recurring_to_dict,
    send_whatsapp_background,
    transfer_lines_for,
)
from app.services.procurement import resolve_order_id, resolve_po_line_id, supplier_payment_days
from app.services.projects import resolve_job_id
from app.services.subcontract_billing import release_gst_rows
from app.services.wallet_ai import require_credit
from app.validators.common import (
    validate_email_address,
    validate_invoice_dates,
    validate_line_items,
    validate_recurring,
)


router = APIRouter()


@router.get("/api/invoices")
def get_invoices(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).order_by(models.DBInvoice.id.desc()).all()
    today = datetime.now().date()
    result = []
    for inv in invoices:
        overdue_days = invoice_overdue_days(inv, today)
        result.append({
            "number": inv.number,
            "ref": inv.ref,
            "to": inv.to_contact,
            "email": inv.email,
            "phone_number": inv.phone_number,
            "date": inv.issue_date,
            "due_date": inv.due_date,
            "paid": inv.paid,
            "due": inv.due,
            "total": money((inv.paid or 0) + (inv.due or 0)),
            "status": inv.status,
            "sent": inv.sent,
            "tax_type": inv.tax_type,
            "currency": inv.currency or (client.currency if client else ""),
            "open_count": inv.open_count or 0,
            "last_opened": inv.last_opened or "",
            "is_overdue": overdue_days > 0,
            "days_overdue": overdue_days,
        })
    return result


@router.get("/api/invoices/{number}")
def get_invoice(number: str, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.number == number, models.DBInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    settings_rows = db.query(models.DBSettings).filter(models.DBSettings.client_id == inv.client_id).all() if inv.client_id else []
    settings_map = {s.key: s.value for s in settings_rows}
    company = {
        "name": settings_map.get("company_name", "") or (client.company_name if client else ""),
        "email": settings_map.get("email", "") or (client.email if client else ""),
        "phone_number": settings_map.get("phone_number", "") or (client.phone_number if client else ""),
        "address": settings_map.get("company_address", "") or (client.address if client else ""),
        "website": settings_map.get("company_website", "") or (client.website if client else ""),
        "abn": settings_map.get("company_abn", "") or (client.abn if client else ""),
        "logo_url": client.logo_url if client else "",
    }
    subtotal, tax_total, grand_total = compute_invoice_totals(inv.line_items, inv.tax_type)
    overdue_days = invoice_overdue_days(inv)
    payments = db.query(models.DBPayment).filter(
        models.DBPayment.invoice_id == inv.id
    ).order_by(models.DBPayment.id.asc()).all()
    return {
        "id": inv.id,
        "number": inv.number,
        "ref": inv.ref,
        "to": inv.to_contact,
        "email": inv.email,
        "phone_number": inv.phone_number,
        "date": inv.issue_date,
        "due_date": inv.due_date,
        "paid": inv.paid,
        "due": inv.due,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "total": grand_total,
        "is_overdue": overdue_days > 0,
        "days_overdue": overdue_days,
        "payments": [{
            "id": p.id, "amount": p.amount, "paid_on": p.paid_on,
            "method": p.method, "reference": p.reference, "note": p.note,
        } for p in payments],
        "status": inv.status,
        "sent": inv.sent,
        "tax_type": inv.tax_type,
        "currency": inv.currency or (client.currency if client else ""),
        "bank_details": inv.bank_details or "",
        "tracking_id": inv.tracking_id,
        "open_count": inv.open_count or 0,
        "last_opened": inv.last_opened or "",
        "company": company,
        "line_items": [{
            "name": li.name or "",
            "description": li.description,
            "qty": li.qty,
            "price": li.price,
            "disc": li.disc,
            "account": li.account,
            "tax_rate": li.tax_rate,
            "tax_percent": round(parse_tax_rate(li.tax_rate) * 100, 4),
            "amount": money(line_net_amount(li.qty, li.price, li.disc)),
            "tax_amount": money(
                line_net_amount(li.qty, li.price, li.disc) * parse_tax_rate(li.tax_rate)
                if inv.tax_type == "exclusive" else
                (line_net_amount(li.qty, li.price, li.disc)
                 - line_net_amount(li.qty, li.price, li.disc) / (1 + parse_tax_rate(li.tax_rate))
                 if inv.tax_type == "inclusive" and parse_tax_rate(li.tax_rate) else 0)
            ),
        } for li in inv.line_items]
    }


@router.get("/api/next-invoice-number")
def get_next_invoice_number(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    return {"next_number": next_sequence_number(
        db, models.DBInvoice, client.id, invoice_prefix_for(db, client.id)),
        "payment_terms_days": payment_terms_for(db, client.id)}


@router.post("/api/invoices")
def create_invoice(invoice: InvoiceCreate, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)

    validate_line_items(invoice.line_items)
    validate_invoice_dates(invoice.issue_date, invoice.due_date)

    subtotal, tax, total = compute_invoice_totals(invoice.line_items, invoice.tax_type)

    # Auto-save contact (scoped to client)
    if invoice.contact and invoice.contact.strip():
        existing = db.query(models.DBContact).filter(models.DBContact.name == invoice.contact, models.DBContact.client_id == client.id).first()
        if existing:
            if invoice.email and not existing.email:
                existing.email = invoice.email
            if invoice.phone_number and not existing.phone_number:
                existing.phone_number = invoice.phone_number
        else:
            db.add(models.DBContact(name=invoice.contact, email=invoice.email or "", phone_number=invoice.phone_number or "", client_id=client.id))

    if invoice.invoice_number and invoice.invoice_number.strip() != "":
        number = invoice.invoice_number.strip()
    else:
        number = next_sequence_number(db, models.DBInvoice, client.id, invoice_prefix_for(db, client.id))

    clash = db.query(models.DBInvoice).filter(
        models.DBInvoice.client_id == client.id, models.DBInvoice.number == number
    ).first()
    if clash:
        raise HTTPException(status_code=409, detail=f"Invoice number {number} already exists")

    db_invoice = models.DBInvoice(
        client_id=client.id,
        number=number,
        ref=invoice.reference,
        to_contact=invoice.contact,
        email=invoice.email,
        phone_number=invoice.phone_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        paid=0.00,
        due=round(total, 2),
        status=invoice.status or "Draft",
        sent="",
        tax_type=invoice.tax_type,
        currency=(invoice.currency or "").upper() or (client.currency or ""),
        bank_details=invoice.bank_details or "",
        job_id=resolve_job_id(db, client.id, invoice.job_id),
    )
    db.add(db_invoice)
    db.flush()

    for item in invoice.line_items:
        db_line_item = models.DBLineItem(
            invoice_id=db_invoice.id,
            name=item.name or "",
            description=item.description,
            qty=item.qty,
            price=item.price,
            disc=item.disc or 0.0,
            account=item.account,
            tax_rate=item.tax_rate
        )
        db.add(db_line_item)

    db.commit()
    db.refresh(db_invoice)
    log_audit(db, client.id, "invoice_created", "invoice", db_invoice.id, number, f"Total: {total:.2f}", request)
    db.commit()

    return get_invoice(number, request, db)


@router.post("/api/invoices/{number}/send")
def send_invoice_email(number: str, background_tasks: BackgroundTasks, request: Request, payload: Optional[SendInvoiceEmail] = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if payload is None:
        payload = SendInvoiceEmail()
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.number == number, models.DBInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.approval_status and inv.approval_status not in ("none", "approved", ""):
        raise HTTPException(status_code=403, detail=f"Cannot send invoice: approval status is '{inv.approval_status}'. Wait for approval or resubmit.")
    if not inv.email:
        raise HTTPException(status_code=400, detail="Invoice has no email address associated with it")
    if not validate_email_address(inv.email):
        raise HTTPException(status_code=400, detail=f"Invalid email address: {inv.email}")

    user = request.session.get('user', {})
    from_email = default_from_email()
    if not from_email:
        raise HTTPException(status_code=400, detail="No sender email configured.")

    settings_rows = db.query(models.DBSettings).filter(models.DBSettings.client_id == inv.client_id).all()
    settings_map = {s.key: s.value for s in settings_rows}
    inv_client = db.query(models.DBClient).filter(models.DBClient.id == inv.client_id).first() if inv.client_id else None
    company_name = settings_map.get("company_name", "") or (inv_client.company_name if inv_client else "") or "Accounting Platform"
    company_email = settings_map.get("email", "") or (inv_client.email if inv_client else "")
    company_phone = settings_map.get("phone_number", "") or (inv_client.phone_number if inv_client else "")
    company_address = settings_map.get("company_address", "") or (inv_client.address if inv_client else "")
    company_abn = settings_map.get("company_abn", "") or (inv_client.abn if inv_client else "")
    company_website = settings_map.get("company_website", "") or (inv_client.website if inv_client else "")

    cur = (inv.currency or settings_map.get("currency") or (inv_client.currency if inv_client else "") or DEFAULT_CURRENCY).upper()
    cur_symbol = currency_symbol(cur)

    sender_name = os.getenv("FROM_NAME", "Y ERP")
    from_header = f"{company_name} <{from_email}>"
    subject = f"Invoice {inv.number} from {company_name}"

    logo_html = ""
    logo_data = payload.logo_data or ""
    if not logo_data and inv_client and inv_client.logo_url:
        logo_data = inv_client.logo_url
    if logo_data:
        logo_html = f'<div style="margin-bottom:24px;"><img src="{esc(logo_data)}" style="max-height:48px;max-width:200px;"></div>'

    line_items_html = ""
    if inv.line_items:
        rows = ""
        for li in inv.line_items:
            amount = li.qty * li.price
            disc_val = li.disc or 0
            if disc_val > 0:
                amount *= (1 - disc_val / 100)
            disc_html = f'<span style="display:inline-block;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">{disc_val:g}% off</span>' if disc_val > 0 else ''
            rows += f'''
                <div style="padding:16px 20px;border-bottom:1px solid #f1f5f9;">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
                    <div style="font-size:15px;font-weight:700;color:#1e293b;">{esc(li.name) or 'Item'}</div>
                    <div style="font-size:16px;font-weight:800;color:#0f172a;">{cur_symbol}{amount:.2f}</div>
                  </div>
                  {f'<div style="font-size:13px;color:#64748b;margin-bottom:8px;word-wrap:break-word;">{esc(li.description)}</div>' if li.description else ''}
                  <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;">
                    <span style="font-size:12px;color:#94a3b8;">Qty: <strong style="color:#475569;">{int(li.qty)}</strong></span>
                    <span style="font-size:12px;color:#94a3b8;">Price: <strong style="color:#475569;">{cur_symbol}{li.price:.2f}</strong></span>
                    {f'<span style="font-size:12px;color:#94a3b8;">Discount: {disc_html}</span>' if disc_val > 0 else ''}
                  </div>
                </div>'''

        line_items_html = f'''
            <div style="border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;margin-bottom:24px;">
              <div style="background-color:#f8fafc;padding:10px 20px;border-bottom:2px solid #e2e8f0;display:flex;justify-content:space-between;">
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;">Item</span>
                <span style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;">Amount</span>
              </div>
              {rows}
            </div>'''

    body = f"""Hello {esc(inv.to_contact)},

Please find the details of your invoice {inv.number} from {company_name or sender_name} below.

Invoice Number: {inv.number}
Issue Date: {inv.issue_date}
Due Date: {inv.due_date}

Line Items:
"""
    for li in inv.line_items:
        item_label = f"{li.name} - {li.description}" if li.name else li.description
        disc_text = f" (Disc: {li.disc}%)" if li.disc else ""
        body += f"  - {item_label} x{int(li.qty)} @ {cur_symbol}{li.price:.2f}{disc_text}\n"
    body += f"""
Total Amount Due: {cur_symbol}{inv.due:.2f}

Payment is due by {inv.due_date}. If you have any questions about this invoice, please reply to this email.

Thank you for your business!

Best regards,
{company_name}
{company_address or ''}
{company_email or ''}
{company_phone or ''}

Powered by Aniprotech"""

    html_body = f"""
    <!DOCTYPE html>
    <html>
      <body style="font-family: Arial, Helvetica, sans-serif; color: #1e293b; line-height: 1.6; margin: 0; padding: 0; background-color: #f1f5f9;">
        <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
          <div style="background: #ffffff; border-radius: 12px; overflow: hidden;">
            <!-- Header -->
            <div style="background-color: #0f172a; padding: 40px; text-align: center;">
              {logo_html}
              <h1 style="font-size: 32px; font-weight: 800; color: #ffffff; margin: 0 0 8px 0;">INVOICE</h1>
              <p style="font-size: 16px; color: #94a3b8; margin: 0; font-weight: 600;">{inv.number}</p>
              <div style="margin-top: 16px; display: inline-block; background-color: #0ea5e9; padding: 8px 20px; border-radius: 20px;">
                <span style="font-size: 14px; color: #ffffff; font-weight: 600;">Amount Due: {cur_symbol}{inv.due:.2f}</span>
              </div>
            </div>

            <!-- Company Details Bar -->
            {f'''
            <div style="background-color: #f8fafc; padding: 16px 40px; border-bottom: 1px solid #e2e8f0;">
              <div style="font-size: 13px; color: #475569;">
                <strong style="color: #1e293b;">{esc(company_name)}</strong>
                {f' &bull; {esc(company_address)}' if company_address else ''}
                {f' &bull; {esc(company_email)}' if company_email else ''}
                {f' &bull; {esc(company_phone)}' if company_phone else ''}
              </div>
            </div>
            ''' if company_name else ''}

            <!-- Body -->
            <div style="padding: 40px;">
              <p style="font-size: 16px; color: #1e293b; margin: 0 0 6px 0;">Hello <strong>{esc(inv.to_contact)}</strong>,</p>
              <p style="font-size: 14px; color: #64748b; margin: 0 0 32px 0;">Here's your invoice from <strong>{esc(company_name or sender_name)}</strong>. Please find the details below.</p>

              <!-- Invoice Details Cards -->
              <div style="margin-bottom: 32px;">
                <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
                  <tr>
                    <td style="background-color: #f1f5f9; border-radius: 10px; padding: 16px; text-align: center; width: 33%;">
                      <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; margin-bottom: 4px;">Issue Date</div>
                      <div style="font-size: 14px; font-weight: 600; color: #1e293b;">{inv.issue_date}</div>
                    </td>
                    <td style="width: 10px;"></td>
                    <td style="background-color: #f1f5f9; border-radius: 10px; padding: 16px; text-align: center; width: 33%;">
                      <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; margin-bottom: 4px;">Due Date</div>
                      <div style="font-size: 14px; font-weight: 600; color: #1e293b;">{inv.due_date}</div>
                    </td>
                    <td style="width: 10px;"></td>
                    <td style="background-color: #f1f5f9; border-radius: 10px; padding: 16px; text-align: center; width: 33%;">
                      <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; color: #64748b; margin-bottom: 4px;">Invoice #</div>
                      <div style="font-size: 14px; font-weight: 600; color: #1e293b;">{inv.number}</div>
                    </td>
                  </tr>
                </table>
              </div>

              <!-- Line Items -->
              {line_items_html}

              <!-- Total -->
              <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-top: 24px;">
                <tr>
                  <td style="background-color: #0f172a; border-radius: 12px; padding: 24px; text-align: right;">
                    <div style="font-size: 13px; color: #94a3b8; margin-bottom: 4px;">TOTAL AMOUNT</div>
                    <div style="font-size: 32px; font-weight: 800; color: #ffffff;">{cur_symbol}{inv.due:.2f}</div>
                  </td>
                </tr>
              </table>

              <!-- Payment Note -->
              <div style="margin-top: 32px; padding: 20px; background-color: #fefce8; border-radius: 10px; border-left: 4px solid #fcd34d;">
                <p style="font-size: 13px; color: #854d0e; margin: 0;"><strong>Payment Terms:</strong> Please pay by {inv.due_date}. For any questions, reply to this email.</p>
              </div>

              <!-- View and Pay Online -->
              <p style="margin-top: 20px;"><a href="{request.base_url}next/login" style="color: #0ea5e9; font-size: 14px; font-weight: 600;">View and pay online &rarr;</a></p>
            </div>

            <!-- Footer -->
            <div style="padding: 24px 40px; background-color: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center;">
              <p style="font-size: 13px; color: #94a3b8; margin: 0 0 4px 0;">Thank you for your business!</p>
              <p style="font-size: 12px; color: #64748b; margin: 0;">{company_name}</p>
              {f'<p style="font-size:11px;color:#94a3b8;margin:4px 0 0 0;">{esc(company_address)}</p>' if company_address else ''}
              <p style="font-size: 11px; color: #94a3b8; margin: 12px 0 0 0;">Powered by Aniprotech</p>
            </div>
          </div>
        </div>
        <img src="{request.base_url}api/track/open/{inv.tracking_id}" width="1" height="1" style="display:none;" alt="">
      </body>
    </html>
    """

    pdf_b64 = payload.pdf_data if payload.pdf_data else None
    pdf_filename = f"{inv.number}.pdf" if pdf_b64 else "invoice.pdf"

    # Metered before the send is queued; charging afterwards would mean a
    # refused charge still delivered the email.
    require_credit(db, client.id, "invoice_send", 1, inv.number)

    background_tasks.add_task(send_email_background, inv.email, subject, body, from_header, html_body, pdf_b64, pdf_filename, logo_data, client_id=client.id)

    # Re-sending a receipt must not walk a settled invoice back to unpaid.
    if inv.status not in ("Paid", "Partially Paid", "Void"):
        inv.status = "Sent"
    inv.sent = datetime.now().strftime("%Y-%m-%d")
    log_audit(db, client.id, "invoice_sent", "invoice", inv.id, inv.number, f"Sent to {inv.email}", request)
    db.commit()

    return {"message": "Email sending initiated via Gmail API", "status": "Sent", "sent_date": inv.sent}


@router.post("/api/invoices/{number}/send-whatsapp")
def send_invoice_whatsapp(number: str, background_tasks: BackgroundTasks, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.number == number, models.DBInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if not inv.phone_number:
        raise HTTPException(status_code=400, detail="Invoice has no phone number")

    inv_client = db.query(models.DBClient).filter(models.DBClient.id == inv.client_id).first() if inv.client_id else None
    ws_cur = (inv.currency or (inv_client.currency if inv_client else "") or DEFAULT_CURRENCY).upper()
    ws_sym = currency_symbol(ws_cur)
    message = f"Hello {inv.to_contact},\n\nPlease find the details of your invoice {inv.number} below:\n\nTotal Due: {ws_sym}{inv.due:.2f}\nDue Date: {inv.due_date}\n\nThank you for your business!"
    require_credit(db, client.id, "invoice_whatsapp", 1, inv.number)
    background_tasks.add_task(send_whatsapp_background, inv.phone_number, message)

    if inv.status == "Draft":
        inv.status = "Sent"
        inv.sent = datetime.now().strftime("%Y-%m-%d")
        db.commit()

    return {"message": "WhatsApp sending initiated", "status": inv.status}


@router.get("/api/invoices/{number}/open-stats")
def get_open_stats(number: str, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.number == number, models.DBInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "number": inv.number,
        "tracking_id": inv.tracking_id,
        "open_count": inv.open_count or 0,
        "last_opened": inv.last_opened or "",
    }


@router.get("/api/bills")
def list_bills(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    bills = db.query(models.DBBill).filter(models.DBBill.client_id == client.id).order_by(models.DBBill.id.desc()).all()
    submitters = {
        e.id: f"{e.first_name} {e.last_name}".strip()
        for e in db.query(models.DBEmployee).filter(
            models.DBEmployee.client_id == client.id).all()
    }
    return [{"id": b.id, "number": b.number, "vendor_name": b.vendor_name, "vendor_email": b.vendor_email or "",
             "issue_date": b.issue_date or "", "due_date": b.due_date or "", "amount": b.amount or 0.0,
             "tax_amount": b.tax_amount or 0.0, "total": b.total or 0.0, "amount_paid": b.amount_paid or 0.0,
             "status": b.status or "Draft", "category": b.category or "general", "reference": b.reference or "",
             "notes": b.notes or "",
             "approval_status": b.approval_status or "none",
             "current_step": b.current_approval_step or 0,
             "rejection_reason": b.rejection_reason or "",
             "submitted_by": b.submitted_by,
             "submitted_by_name": submitters.get(b.submitted_by, "")} for b in bills]


@router.post("/api/bills")
def create_bill(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("accounts.manage", "bills.pay"))
    if session_employee(request, db):
        return employee_create_bill(request, body, db)
    if not body:
        raise HTTPException(status_code=400, detail="Bill data required")
    existing = db.query(models.DBBill).filter(models.DBBill.number == body.get("number", ""), models.DBBill.client_id == client.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Bill number already exists")
    bill = models.DBBill(
        client_id=client.id,
        number=body.get("number", ""),
        vendor_name=body.get("vendor_name", ""),
        vendor_email=body.get("vendor_email", ""),
        issue_date=body.get("issue_date", ""),
        # No due date typed: the supplier's own terms, rather than filing the
        # bill as the oldest debt on the books from the day it arrives.
        due_date=body.get("due_date") or days_after(
            body.get("issue_date") or datetime.now().strftime("%Y-%m-%d"),
            supplier_payment_days(db, client.id, body.get("vendor_name") or "")),
        amount=body.get("amount", 0.0),
        tax_amount=body.get("tax_amount", 0.0),
        total=body.get("total", 0.0),
        status=body.get("status", "Draft"),
        category=body.get("category", "general"),
        reference=body.get("reference", ""),
        notes=body.get("notes", ""),
        job_id=resolve_job_id(db, client.id, body.get("job_id")),
        purchase_order_id=resolve_order_id(db, client.id, body.get("purchase_order_id")),
    )
    db.add(bill)
    db.flush()
    for li in (body.get("line_items") or [])[:50]:
        db.add(models.DBBillLineItem(
            bill_id=bill.id,
            description=(li.get("description") or "")[:500],
            po_line_id=resolve_po_line_id(db, bill.purchase_order_id,
                                          li.get("po_line_id")),
            qty=float(li.get("qty") or 1),
            price=float(li.get("price") or 0),
            tax_rate=li.get("tax_rate") or "0%"))
    db.commit()
    db.refresh(bill)
    log_audit(db, client.id, "bill_created", "bill", bill.id, bill.number, f"Vendor: {bill.vendor_name}, Total: {bill.total}", request)
    db.commit()
    return {"id": bill.id, "number": bill.number}


@router.get("/api/bills/{bill_id}")
def get_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    bill = db.query(models.DBBill).filter(models.DBBill.id == bill_id, models.DBBill.client_id == client.id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    line_items = db.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id == bill.id).all()
    return {
        "id": bill.id, "number": bill.number, "vendor_name": bill.vendor_name, "vendor_email": bill.vendor_email or "",
        "issue_date": bill.issue_date or "", "due_date": bill.due_date or "", "amount": bill.amount or 0.0,
        "tax_amount": bill.tax_amount or 0.0, "total": bill.total or 0.0, "amount_paid": bill.amount_paid or 0.0,
        "status": bill.status or "Draft", "category": bill.category or "general", "reference": bill.reference or "",
        "notes": bill.notes or "",
        "approval_status": bill.approval_status or "none",
        "current_step": bill.current_approval_step or 0,
        "rejection_reason": bill.rejection_reason or "",
        "submitted_by": bill.submitted_by,
        "approval_history": get_approval_chain_history("bill", bill.id, db),
        "line_items": [{"id": li.id, "description": li.description or "", "qty": li.qty or 1, "price": li.price or 0, "tax_rate": li.tax_rate or "20%"} for li in line_items]
    }


@router.put("/api/bills/{bill_id}")
def update_bill(bill_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("accounts.manage", "bills.pay"))
    bill = db.query(models.DBBill).filter(models.DBBill.id == bill_id, models.DBBill.client_id == client.id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if body and session_employee(request, db):
        # Staff correct a bill; they do not mark it paid or approved by
        # editing it, and they do not change one somebody is deciding on or
        # has already approved.
        body = {k: v for k, v in body.items() if k not in ("status", "amount_paid")}
        if bill.approval_status == "pending":
            raise HTTPException(409, "This bill is with an approver and cannot be changed.")
        if bill.approval_status == "approved" and any(
                k in body and money(body[k] or 0) != money(getattr(bill, k) or 0)
                for k in ("amount", "tax_amount", "total")):
            raise HTTPException(409, "This bill has been approved at its amount. "
                                     "Ask the approver to send it back before changing it.")
    if body:
        for field in ["number", "vendor_name", "vendor_email", "issue_date", "due_date", "amount", "tax_amount", "total", "amount_paid", "status", "category", "reference", "notes"]:
            if field in body:
                setattr(bill, field, body[field])
        if "job_id" in body:
            bill.job_id = resolve_job_id(db, client.id, body["job_id"])
        if "purchase_order_id" in body:
            bill.purchase_order_id = resolve_order_id(db, client.id, body["purchase_order_id"])
        db.commit()
        db.refresh(bill)
    return {"id": bill.id, "number": bill.number}


@router.delete("/api/bills/{bill_id}")
def delete_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    bill = db.query(models.DBBill).filter(models.DBBill.id == bill_id, models.DBBill.client_id == client.id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    # Money paid against it stays in the ledger and the bank book; deleting
    # the bill left those payments pointing at nothing, and voiding one then
    # failed because its bill could not be found.
    paid = money(settled_on(db, client.id, "supplier_bill", bill.id))
    if paid > 0:
        raise HTTPException(409, "%s has %s paid against it. Void those payments under "
                                 "Payments & Ledgers first, or keep the bill."
                                 % (bill.number or "This bill", inr(paid)))
    db.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id == bill.id).delete()
    log_audit(db, client.id, "bill_deleted", "bill", bill.id, bill.number, "", request)
    db.delete(bill)
    db.commit()
    return {"ok": True}


@router.post("/api/bills/{bill_id}/pay")
def mark_bill_paid(bill_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.pay")
    bill = db.query(models.DBBill).filter(models.DBBill.id == bill_id, models.DBBill.client_id == client.id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    # Staff pay what has been approved; a bill the owner entered themselves
    # carries no chain and is theirs to settle.
    if session_employee(request, db) and bill.submitted_by and bill.approval_status != "approved":
        raise HTTPException(status_code=403, detail="This bill has not been approved yet.")
    if bill.approval_status and bill.approval_status not in ("none", "approved", ""):
        raise HTTPException(status_code=403, detail=f"Cannot mark bill paid: approval status is '{bill.approval_status}'.")
    bill.amount_paid = bill.total or bill.amount or 0.0
    bill.status = "Paid"
    notify_employee(db, client.id, bill.submitted_by, "Paid",
                    f"{bill.number} has been paid.")
    log_audit(db, client.id, "bill_paid", "bill", bill.id, bill.number, f"Amount: {bill.amount_paid}", request)
    db.commit()
    return {"ok": True, "status": "Paid"}


@router.get("/api/next-bill-number")
def next_bill_number(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("bills.view_all", "bills.submit"))
    last = db.query(models.DBBill).filter(models.DBBill.client_id == client.id).order_by(models.DBBill.id.desc()).first()
    if last and last.number:
        try:
            num = int(last.number.replace("BILL-", "").replace("BILL", ""))
            return {"number": f"BILL-{num + 1:04d}"}
        except (ValueError, TypeError):
            pass
    return {"number": "BILL-0001"}


@router.delete("/api/invoices/{number}")
def delete_invoice(number: str, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.number == number, models.DBInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    db.query(models.DBLineItem).filter(models.DBLineItem.invoice_id == inv.id).delete()
    db.query(models.DBPayment).filter(models.DBPayment.invoice_id == inv.id).delete()
    log_audit(db, client.id, "invoice_deleted", "invoice", inv.id, inv.number, f"Contact: {inv.to_contact}", request)
    db.delete(inv)
    db.commit()
    return {"message": "Invoice deleted successfully"}


@router.post("/api/invoices/{number}/mark-paid")
def mark_invoice_paid(number: str, request: Request, db: Session = Depends(get_db)):
    """Settle the whole outstanding balance in one go, recording it in the ledger."""
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(models.DBInvoice.number == number, models.DBInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.approval_status and inv.approval_status not in ("none", "approved", ""):
        raise HTTPException(status_code=403, detail=f"Cannot mark invoice paid: approval status is '{inv.approval_status}'.")
    outstanding = money(inv.due or 0)
    if outstanding > 0:
        db.add(models.DBPayment(
            client_id=client.id, invoice_id=inv.id, amount=outstanding,
            paid_on=datetime.now().strftime("%Y-%m-%d"), method="manual",
            note="Marked as paid in full",
        ))
    inv.paid = money((inv.paid or 0) + outstanding)
    inv.due = 0.0
    inv.status = "Paid"
    log_audit(db, client.id, "invoice_marked_paid", "invoice", inv.id, inv.number, f"Amount: {inv.paid}", request)
    db.commit()
    return {"message": "Invoice marked as paid", "status": "Paid", "paid": inv.paid, "due": inv.due}


@router.post("/api/invoices/{number}/payments")
def record_invoice_payment(number: str, body: PaymentCreate, request: Request, db: Session = Depends(get_db)):
    """Record a part payment. Status moves Draft/Sent -> Partially Paid -> Paid."""
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(
        models.DBInvoice.number == number, models.DBInvoice.client_id == client.id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    amount = money(body.amount)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")
    outstanding = money(inv.due or 0)
    if outstanding <= 0:
        raise HTTPException(status_code=400, detail="This invoice has no outstanding balance")
    if amount > outstanding + 0.005:
        raise HTTPException(
            status_code=400,
            detail="Payment of %s exceeds the %s still owed." % (inr(amount), inr(outstanding)),
        )
    payment = models.DBPayment(
        client_id=client.id, invoice_id=inv.id, amount=amount,
        paid_on=body.paid_on or datetime.now().strftime("%Y-%m-%d"),
        method=body.method or "bank_transfer",
        reference=body.reference or "", note=body.note or "",
    )
    db.add(payment)
    inv.paid = money((inv.paid or 0) + amount)
    inv.due = money(outstanding - amount)
    apply_payment_status(inv)
    log_audit(db, client.id, "invoice_payment_recorded", "invoice", inv.id, inv.number,
              f"Amount: {amount:.2f}, remaining: {inv.due:.2f}", request)
    db.commit()
    return {
        "message": "Payment recorded", "status": inv.status,
        "paid": inv.paid, "due": inv.due, "payment_id": payment.id,
    }


@router.delete("/api/invoices/{number}/payments/{payment_id}")
def delete_invoice_payment(number: str, payment_id: int, request: Request, db: Session = Depends(get_db)):
    """Reverse a payment that was entered by mistake."""
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(
        models.DBInvoice.number == number, models.DBInvoice.client_id == client.id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    payment = db.query(models.DBPayment).filter(
        models.DBPayment.id == payment_id, models.DBPayment.invoice_id == inv.id
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    inv.paid = money(max(0.0, (inv.paid or 0) - (payment.amount or 0)))
    inv.due = money((inv.due or 0) + (payment.amount or 0))
    inv.status = "Partially Paid" if (inv.paid or 0) > 0.005 else ("Sent" if inv.sent else "Draft")
    db.delete(payment)
    log_audit(db, client.id, "invoice_payment_reversed", "invoice", inv.id, inv.number,
              f"Amount: {payment.amount:.2f}", request)
    db.commit()
    return {"message": "Payment reversed", "status": inv.status, "paid": inv.paid, "due": inv.due}


@router.put("/api/invoices/{number}")
def update_invoice(number: str, invoice: InvoiceCreate, request: Request, db: Session = Depends(get_db)):
    """Edit a draft/unsent invoice: replaces line items and recomputes totals."""
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(
        models.DBInvoice.number == number, models.DBInvoice.client_id == client.id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if (inv.paid or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail="This invoice already has payments against it. Reverse them before editing.",
        )
    validate_line_items(invoice.line_items)
    validate_invoice_dates(invoice.issue_date, invoice.due_date)

    if invoice.invoice_number and invoice.invoice_number.strip() and invoice.invoice_number.strip() != inv.number:
        new_number = invoice.invoice_number.strip()
        clash = db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client.id, models.DBInvoice.number == new_number
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail=f"Invoice number {new_number} already exists")
        inv.number = new_number

    subtotal, tax, total = compute_invoice_totals(invoice.line_items, invoice.tax_type)

    inv.ref = invoice.reference
    inv.to_contact = invoice.contact
    inv.email = invoice.email
    inv.phone_number = invoice.phone_number
    inv.issue_date = invoice.issue_date
    inv.due_date = invoice.due_date
    inv.tax_type = invoice.tax_type
    inv.due = total
    if invoice.currency:
        inv.currency = invoice.currency.upper()
    if invoice.bank_details is not None:
        inv.bank_details = invoice.bank_details
    if invoice.status:
        inv.status = invoice.status
    inv.job_id = resolve_job_id(db, client.id, invoice.job_id)

    db.query(models.DBLineItem).filter(models.DBLineItem.invoice_id == inv.id).delete()
    for item in invoice.line_items:
        db.add(models.DBLineItem(
            invoice_id=inv.id, name=item.name or "", description=item.description,
            qty=item.qty, price=item.price, disc=item.disc or 0.0,
            account=item.account, tax_rate=item.tax_rate,
        ))
    log_audit(db, client.id, "invoice_updated", "invoice", inv.id, inv.number, f"Total: {total:.2f}", request)
    db.commit()
    return get_invoice(inv.number, request, db)


@router.get("/api/recurring-invoices")
def list_recurring(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    rows = db.query(models.DBRecurringInvoice).filter(
        models.DBRecurringInvoice.client_id == client.id
    ).order_by(models.DBRecurringInvoice.id.desc()).all()
    return [recurring_to_dict(t) for t in rows]


@router.post("/api/recurring-invoices")
def create_recurring(body: RecurringIn, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    validate_line_items(body.line_items)
    terms = validate_recurring(body)

    t = models.DBRecurringInvoice(
        client_id=client.id, name=body.name or "", to_contact=body.contact,
        email=body.email or "", phone_number=body.phone_number or "",
        reference=body.reference or "", tax_type=body.tax_type,
        currency=(body.currency or "").upper() or (client.currency or ""),
        bank_details=body.bank_details or "", frequency=body.frequency,
        payment_terms_days=terms, next_run=body.next_run, end_date=body.end_date or "",
        is_active=bool(body.is_active), auto_send=bool(body.auto_send),
    )
    db.add(t)
    db.flush()
    for item in body.line_items:
        db.add(models.DBRecurringLineItem(
            recurring_id=t.id, name=item.name or "", description=item.description,
            qty=item.qty, price=item.price, disc=item.disc or 0.0,
            account=item.account, tax_rate=item.tax_rate,
        ))
    log_audit(db, client.id, "recurring_created", "recurring", t.id, t.name or t.to_contact,
              t.frequency, request)
    db.commit()
    db.refresh(t)
    return recurring_to_dict(t)


@router.put("/api/recurring-invoices/{rec_id}")
def update_recurring(rec_id: int, body: RecurringIn, request: Request,
                     db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    t = db.query(models.DBRecurringInvoice).filter(
        models.DBRecurringInvoice.id == rec_id,
        models.DBRecurringInvoice.client_id == client.id,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Recurring invoice not found")
    validate_line_items(body.line_items)
    terms = validate_recurring(body)

    t.name = body.name or ""
    t.to_contact = body.contact
    t.email = body.email or ""
    t.phone_number = body.phone_number or ""
    t.reference = body.reference or ""
    t.tax_type = body.tax_type
    t.currency = (body.currency or "").upper() or t.currency
    t.bank_details = body.bank_details or ""
    t.frequency = body.frequency
    t.payment_terms_days = terms
    t.next_run = body.next_run
    t.end_date = body.end_date or ""
    t.is_active = bool(body.is_active)
    t.auto_send = bool(body.auto_send)

    db.query(models.DBRecurringLineItem).filter(
        models.DBRecurringLineItem.recurring_id == t.id).delete()
    for item in body.line_items:
        db.add(models.DBRecurringLineItem(
            recurring_id=t.id, name=item.name or "", description=item.description,
            qty=item.qty, price=item.price, disc=item.disc or 0.0,
            account=item.account, tax_rate=item.tax_rate,
        ))
    log_audit(db, client.id, "recurring_updated", "recurring", t.id,
              t.name or t.to_contact, t.frequency, request)
    db.commit()
    db.refresh(t)
    return recurring_to_dict(t)


@router.delete("/api/recurring-invoices/{rec_id}")
def delete_recurring(rec_id: int, request: Request, db: Session = Depends(get_db)):
    """Stops future invoices. The ones already issued are real documents and
    are left exactly where they are."""
    client = get_client_user(request, db)
    t = db.query(models.DBRecurringInvoice).filter(
        models.DBRecurringInvoice.id == rec_id,
        models.DBRecurringInvoice.client_id == client.id,
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Recurring invoice not found")
    db.query(models.DBRecurringLineItem).filter(
        models.DBRecurringLineItem.recurring_id == t.id).delete()
    log_audit(db, client.id, "recurring_deleted", "recurring", t.id,
              t.name or t.to_contact, "", request)
    db.delete(t)
    db.commit()
    return {"message": "Recurring invoice stopped"}


@router.get("/api/invoices/{number}/reminders")
def invoice_reminders(number: str, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    inv = db.query(models.DBInvoice).filter(
        models.DBInvoice.number == number, models.DBInvoice.client_id == client.id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    rows = db.query(models.DBInvoiceReminder).filter(
        models.DBInvoiceReminder.invoice_id == inv.id
    ).order_by(models.DBInvoiceReminder.stage_days.asc()).all()
    return [{"stage_days": r.stage_days, "sent_to": r.sent_to, "sent_at": r.sent_at}
            for r in rows]


@router.get("/api/next-quote-number")
def get_next_quote_number(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    return {"next_number": next_sequence_number(db, models.DBQuote, client.id, "QU-")}


@router.get("/api/gst/settings")
def gst_settings(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    code = our_state(db, client.id)
    return {"gstin": client.gstin or "", "state_code": code,
            "state": GST_STATES.get(code, ""), "states": GST_STATES,
            "works_contract_sac": WORKS_CONTRACT_SAC}


@router.put("/api/gst/settings")
def set_gst_settings(body: CompanyGstIn, request: Request, db: Session = Depends(get_db)):
    """Our GSTIN. The state falls out of it, so it cannot disagree with it."""
    client = get_client_user(request, db)
    g = (body.gstin or "").strip().upper()
    if g and (len(g) != 15 or not g[:2].isdigit() or g[:2] not in GST_STATES):
        raise HTTPException(400, "A GSTIN is fifteen characters and starts with a "
                                 "state code - %s is not one." % (g[:2] or "that"))
    client.gstin = g
    client.state_code = state_from_gstin(g) or (body.state_code or "").strip()
    if client.state_code and client.state_code not in GST_STATES:
        raise HTTPException(400, "Not a GST state code: %s" % client.state_code)
    db.commit()
    return {"ok": True, "gstin": client.gstin, "state_code": client.state_code,
            "state": GST_STATES.get(client.state_code, "")}


@router.get("/api/gst/outward")
def gst_outward(request: Request, date_from: str = "", date_to: str = "",
                db: Session = Depends(get_db)):
    """What we charged, by month and rate, split the way GSTR-1 wants it.

    Outward supplies are the client's certified RA bills and the invoices.
    Grouped by month because that is how the return is filed, and by rate
    because that is how the return's tables are laid out.
    """
    client = require_items_access(request, db, "bills.view_all")
    rows = []
    for b in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client.id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        on = (b.certified_at or b.created_at or "")[:10]
        if date_from and on < date_from:
            continue
        if date_to and on > date_to:
            continue
        job = db.query(models.DBJob).filter(models.DBJob.id == b.job_id).first()
        taxable = money(b.this_bill)
        rows.append({
            "kind": "RA bill", "number": b.number or "", "date": on,
            "party": job.customer_name if job else "", "project": job.name if job else "",
            "place_of_supply": b.place_of_supply or "",
            "sac": WORKS_CONTRACT_SAC, "rate": b.tax_percent or 0,
            "taxable": taxable, "cgst": money(b.cgst_amount), "sgst": money(b.sgst_amount),
            "igst": money(b.igst_amount), "tax": money(b.tax_amount),
            "total": money(taxable + (b.tax_amount or 0)),
        })
    rows.extend(release_gst_rows(db, client.id, "client", date_from, date_to))
    irns = {r.doc_number: r.irn for r in db.query(models.DBEinvoiceIrn).filter(
        models.DBEinvoiceIrn.client_id == client.id, models.DBEinvoiceIrn.status == "ACTIVE").all()}
    for r in rows:
        r["irn"] = irns.get(r["number"], "")
    by_month, by_rate = {}, {}
    for r in rows:
        m = by_month.setdefault(_month_key(r["date"]), {
            "month": _month_key(r["date"]), "taxable": 0.0, "cgst": 0.0, "sgst": 0.0,
            "igst": 0.0, "tax": 0.0, "bills": 0})
        for k in ("taxable", "cgst", "sgst", "igst", "tax"):
            m[k] = money(m[k] + r[k])
        m["bills"] += 1
        rt = by_rate.setdefault(r["rate"], {"rate": r["rate"], "taxable": 0.0, "tax": 0.0})
        rt["taxable"] = money(rt["taxable"] + r["taxable"])
        rt["tax"] = money(rt["tax"] + r["tax"])
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {
        "supplies": rows,
        "by_month": sorted(by_month.values(), key=lambda m: m["month"], reverse=True),
        "by_rate": sorted(by_rate.values(), key=lambda r: r["rate"]),
        "summary": {
            "taxable": money(sum(r["taxable"] for r in rows)),
            "cgst": money(sum(r["cgst"] for r in rows)),
            "sgst": money(sum(r["sgst"] for r in rows)),
            "igst": money(sum(r["igst"] for r in rows)),
            "tax": money(sum(r["tax"] for r in rows)),
            "bills": len(rows),
            "missing_place_of_supply": len([r for r in rows if not r["place_of_supply"]]),
            "without_irn": len([r for r in rows if not r["irn"]]),
        },
    }


@router.get("/api/gst/inward")
def gst_inward(request: Request, date_from: str = "", date_to: str = "",
               db: Session = Depends(get_db)):
    """What we were charged - the input credit side. Subcontractor bills and
    supplier bills."""
    client = require_items_access(request, db, "bills.view_all")
    rows = []
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client.id).all()}
    for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client.id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        on = (b.certified_at or b.created_at or "")[:10]
        if date_from and on < date_from:
            continue
        if date_to and on > date_to:
            continue
        con = contractors.get(b.contractor_id)
        taxable = money(b.this_bill)
        rows.append({
            "kind": "Subcontractor bill", "number": b.number or "", "date": on,
            "party": con.company_name if con else "",
            "party_gstin": (con.gst_number or "") if con else "",
            "sac": WORKS_CONTRACT_SAC, "rate": b.gst_percent or 0,
            "taxable": taxable, "cgst": money(b.cgst_amount), "sgst": money(b.sgst_amount),
            "igst": money(b.igst_amount), "tax": money(b.gst_amount),
        })
    rows.extend(release_gst_rows(db, client.id, "contractor", date_from, date_to))
    # The supplier's GSTIN is on the supplier list; the bill only has a name.
    # Without it every supplier bill sat in the register with no GSTIN and
    # its tax in one lump - nothing to reconcile the input credit against.
    supplier_gstin = {norm_name(x.name): (x.gstin or "").strip().upper()
                      for x in db.query(models.DBSupplier).filter(
                          models.DBSupplier.client_id == client.id).all()}
    home = our_state(db, client.id)
    for b in db.query(models.DBBill).filter(
            models.DBBill.client_id == client.id).all():
        if (b.status or "") in ("Cancelled", "Rejected", "Draft"):
            continue
        on = (b.issue_date or b.created_at or "")[:10]
        if date_from and on < date_from:
            continue
        if date_to and on > date_to:
            continue
        gstin = supplier_gstin.get(norm_name(b.vendor_name), "")
        tax = money(b.tax_amount)
        taxable = money(b.amount)
        # Same state as us: CGST and SGST. Another state, or a supplier whose
        # state is not known: IGST, the side a mistake is cheaper on.
        intra = bool(home and gstin and state_from_gstin(gstin) == home)
        half = money(tax / 2.0) if intra else 0.0
        rows.append({
            "kind": "Supplier bill", "number": b.number or "", "date": on,
            "party": b.vendor_name or "", "party_gstin": gstin,
            "sac": "", "rate": round(tax / taxable * 100.0, 2) if taxable else 0,
            "taxable": taxable, "cgst": half, "sgst": money(tax - half) if intra else 0.0,
            "igst": 0.0 if intra else tax, "tax": tax,
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {
        "supplies": rows,
        "summary": {
            "taxable": money(sum(r["taxable"] for r in rows)),
            "tax": money(sum(r["tax"] for r in rows)),
            "cgst": money(sum(r["cgst"] for r in rows)),
            "sgst": money(sum(r["sgst"] for r in rows)),
            "igst": money(sum(r["igst"] for r in rows)),
            "bills": len(rows),
            # Input credit needs the supplier's GSTIN on the bill. Without it
            # the credit is at risk, so say how many are missing.
            "missing_party_gstin": len([r for r in rows if not r["party_gstin"]]),
        },
    }


@router.get("/api/gst/outward.xlsx")
def gst_outward_export(request: Request, date_from: str = "", date_to: str = "",
                       db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = gst_outward(request, date_from, date_to, db)
    rows = [(r["date"], r["number"], r["party"], r["project"], r["place_of_supply"],
             r["sac"], r["rate"], r["taxable"], r["cgst"], r["sgst"], r["igst"],
             r["tax"], r["total"]) for r in d["supplies"]]
    s = d["summary"]
    return sheet_response(
        ("Date", "Bill", "Client", "Project", "Place of supply", "SAC", "Rate %",
         "Taxable", "CGST", "SGST", "IGST", "Tax", "Total"),
        rows, "gst_outward.xlsx",
        preamble=[("OUTWARD SUPPLIES", client.company_name or ""),
                  ("GSTIN", client.gstin or "", "Period",
                   "%s to %s" % (date_from or "start", date_to or "today")), ()],
        closing=[(), ("Total", "", "", "", "", "", "", s["taxable"], s["cgst"],
                      s["sgst"], s["igst"], s["tax"])])


@router.get("/api/eway-places")
def eway_place_list(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return {"places": eway_places(db, client), "sub_types": EWAY_SUB_TYPES,
            "doc_types": EWAY_DOC_TYPES, "modes": EWAY_MODES, "threshold": EWAY_THRESHOLD}


@router.get("/api/eway-bills")
def list_eway_bills(request: Request, status: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBEwayBill).filter(models.DBEwayBill.client_id == client.id)
    if status:
        q = q.filter(models.DBEwayBill.status == status.upper())
    rows = [eway_dict(db, e) for e in q.order_by(models.DBEwayBill.id.desc()).all()]
    covered = {r["source_ref"] for r in rows if r["source_ref"] and r["status"] != "CANCELLED"}
    # Transfers heavy enough to need one and not yet covered.
    uncovered = []
    for t in list_transfers(request, db)["transfers"]:
        if t["value"] > EWAY_THRESHOLD and t["number"] not in covered:
            uncovered.append({"number": t["number"], "moved_on": t["moved_on"],
                              "from_store": t["from_store"], "to_store": t["to_store"],
                              "value": t["value"]})
    today = date.today().isoformat()
    return {"eway_bills": rows, "uncovered_transfers": uncovered,
            "summary": {"drafts": len([r for r in rows if r["status"] == "DRAFT"]),
                        "live": len([r for r in rows if r["status"] == "GENERATED"
                                     and (r["valid_upto"] or "")[:10] >= today]),
                        "expired": len([r for r in rows if r["expired"]]),
                        "uncovered": len(uncovered)}}


@router.post("/api/eway-bills")
def create_eway_bill(body: EwayIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, ("accounts.manage", "stores.manage"))
    e = models.DBEwayBill(client_id=client.id, number=next_eway_number(db, client.id),
                          created_by_name=actor_name, status="DRAFT",
                          doc_date=date.today().isoformat())
    lines = body.lines
    if (body.source_type or "") == "transfer":
        ref = (body.source_ref or "").strip()
        rows, from_transfer = transfer_lines_for(db, client.id, ref)
        if not rows:
            raise HTTPException(404, "No transfer %s." % ref)
        clash = db.query(models.DBEwayBill).filter(
            models.DBEwayBill.client_id == client.id, models.DBEwayBill.source_ref == ref,
            models.DBEwayBill.status != "CANCELLED").first()
        if clash:
            raise HTTPException(409, "%s already has %s." % (ref, clash.number))
        e.source_type, e.source_ref = "transfer", ref
        e.doc_type, e.sub_type = "CHL", "5"          # our own goods, on a delivery challan
        e.doc_no, e.doc_date = ref, (rows[0].moved_on or date.today().isoformat())[:10]
        lines = lines or from_transfer
    db.add(e)
    db.flush()
    _eway_apply(db, client, e, body)
    made = _eway_set_lines(db, client, e, lines or [])
    eway_totals(e, made)
    log_audit(db, client.id, "eway_bill_drawn", "eway_bill", e.id, e.number,
              "%s %s" % (e.source_ref or "manual", inr(e.total_value)), request)
    db.commit()
    return {"eway_bill": eway_dict(db, e, detail=True)}


@router.get("/api/eway-bills/{eid}")
def get_eway_bill(eid: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return {"eway_bill": eway_dict(db, eway_or_404(db, client.id, eid), detail=True)}


@router.put("/api/eway-bills/{eid}")
def update_eway_bill(eid: int, body: EwayIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, ("accounts.manage", "stores.manage"))
    e = eway_or_404(db, client.id, eid)
    if e.status != "DRAFT":
        raise HTTPException(409, "%s has been generated on the portal; change it there, then "
                                 "update the vehicle or cancel it here." % e.number)
    _eway_apply(db, client, e, body)
    made = _eway_set_lines(db, client, e, body.lines) if body.lines is not None else eway_lines(db, e)
    eway_totals(e, made)
    db.commit()
    return {"eway_bill": eway_dict(db, e, detail=True)}


@router.get("/api/eway-bills/{eid}/json")
def eway_bill_json(eid: int, request: Request, db: Session = Depends(get_db)):
    """The file for the portal's bulk generation."""
    client = require_erp_read(request, db)
    e = eway_or_404(db, client.id, eid)
    problems = eway_problems(db, e)
    if problems:
        raise HTTPException(409, "Not ready for the portal - still needed: " + "; ".join(problems) + ".")
    body = json.dumps(eway_payload(db, client, e), indent=2, ensure_ascii=False).encode("utf-8")
    name = re.sub(r"[^A-Za-z0-9]+", "_", e.number)
    return StreamingResponse(io.BytesIO(body), media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="ewaybill_%s.json"' % name})


@router.post("/api/eway-bills/{eid}/generated")
def eway_generated(eid: int, body: EwayGeneratedIn, request: Request, db: Session = Depends(get_db)):
    """The portal has issued it: its twelve-digit number and how long it runs."""
    client, _, actor_name = wo_actor(request, db, ("accounts.manage", "stores.manage"))
    e = eway_or_404(db, client.id, eid)
    no = re.sub(r"\D", "", body.ewb_no or "")
    if len(no) != 12:
        raise HTTPException(400, "An e-way bill number is twelve digits.")
    clash = db.query(models.DBEwayBill).filter(
        models.DBEwayBill.client_id == client.id, models.DBEwayBill.ewb_no == no,
        models.DBEwayBill.id != e.id).first()
    if clash:
        raise HTTPException(409, "%s is already recorded on %s." % (no, clash.number))
    e.ewb_no = no
    e.ewb_date = (body.ewb_date or date.today().isoformat())[:10]
    e.valid_upto = (body.valid_upto or "").strip() or eway_validity(e.ewb_date, e.distance_km, e.vehicle_type)
    e.status = "GENERATED"
    log_audit(db, client.id, "eway_bill_generated", "eway_bill", e.id, e.number, no, request)
    db.commit()
    return {"eway_bill": eway_dict(db, e, detail=True),
            "message": "%s recorded - valid to %s." % (no, e.valid_upto)}


@router.post("/api/eway-bills/{eid}/vehicle")
def eway_vehicle(eid: int, body: EwayVehicleIn, request: Request, db: Session = Depends(get_db)):
    """Part B: the lorry changed on the way, or was not known when it was drawn."""
    client, _, actor_name = wo_actor(request, db, ("accounts.manage", "stores.manage"))
    e = eway_or_404(db, client.id, eid)
    if e.status == "CANCELLED":
        raise HTTPException(409, "%s is cancelled." % e.number)
    v = re.sub(r"[\s\-]", "", body.vehicle_no or "").upper()
    if not VEHICLE_NO.match(v):
        raise HTTPException(400, "Write the vehicle number like TS09UB1234.")
    e.vehicle_history = ((e.vehicle_history or "") + "%s  %s -> %s  %s  (%s)\n" % (
        datetime.now().strftime("%Y-%m-%d %H:%M"), e.vehicle_no or "none", v,
        (body.reason or "").strip(), actor_name))
    e.vehicle_no = v
    db.commit()
    return {"eway_bill": eway_dict(db, e, detail=True)}


@router.post("/api/eway-bills/{eid}/cancel")
def eway_cancel(eid: int, body: EwayCancelIn, request: Request, db: Session = Depends(get_db)):
    """The portal allows cancelling within 24 hours of generation."""
    client, _, _ = wo_actor(request, db, ("accounts.manage", "stores.manage"))
    e = eway_or_404(db, client.id, eid)
    if not (body.reason or "").strip():
        raise HTTPException(400, "Say why it is being cancelled.")
    if e.status == "GENERATED" and e.ewb_date:
        try:
            made = datetime.strptime(e.ewb_date[:10], "%Y-%m-%d")
            if datetime.now() - made > timedelta(hours=48):
                raise HTTPException(409, "The portal only cancels an e-way bill within 24 hours of "
                                         "generating it. Let it expire unused instead.")
        except ValueError:
            pass
    e.status, e.cancel_reason = "CANCELLED", body.reason.strip()
    db.commit()
    return {"eway_bill": eway_dict(db, e, detail=True)}


@router.get("/api/einvoice/irns")
def list_irns(request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    rows = db.query(models.DBEinvoiceIrn).filter(models.DBEinvoiceIrn.client_id == client.id).order_by(
        models.DBEinvoiceIrn.id.desc()).limit(500).all()
    return {"irns": [irn_dict(r) for r in rows]}


@router.get("/api/einvoice/irns/{irn_id}/qr.svg")
def irn_qr(irn_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    row = db.query(models.DBEinvoiceIrn).filter(models.DBEinvoiceIrn.id == irn_id,
                                                models.DBEinvoiceIrn.client_id == client.id).first()
    if not row or not row.signed_qr:
        raise HTTPException(404, "No QR for that")
    return Response(content=qr_svg(row.signed_qr), media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.post("/api/einvoice/irns/{irn_id}/cancel")
def cancel_irn(irn_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Record that the IRN was cancelled on the portal. The portal cancels
    only within a day of registering; after that a mistake is put right
    with a credit note, and this refuses to pretend otherwise."""
    client, _, actor_name = wo_actor(request, db, "accounts.manage")
    row = db.query(models.DBEinvoiceIrn).filter(models.DBEinvoiceIrn.id == irn_id,
                                                models.DBEinvoiceIrn.client_id == client.id).first()
    if not row:
        raise HTTPException(404, "IRN not found")
    if row.status != "ACTIVE":
        raise HTTPException(409, "That IRN is already cancelled.")
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "The reason given on the portal - duplicate, data entry mistake, order cancelled.")
    if not irn_dict(row)["cancellable"]:
        raise HTTPException(409, "The portal cancels an IRN only within %d hours of registering it. "
                                 "Past that, correct the invoice with a credit note." % IRN_CANCEL_HOURS)
    row.status, row.cancel_reason = "CANCELLED", reason[:200]
    row.cancelled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client.id, "irn_cancelled", row.doc_type, row.doc_id, row.doc_number, reason, request)
    db.commit()
    return {"irn": irn_dict(row), "message": "IRN for %s recorded as cancelled." % row.doc_number}


@router.get("/api/einvoice/{doc_type}/{doc_id}")
def einvoice_status(doc_type: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """Everything the e-invoice box shows: whether the bill can go to the
    portal, what is missing if not, and the IRN if it has been."""
    client = require_erp_read(request, db)
    doc, payload, problems = einvoice_document(db, client, doc_type, doc_id)
    history = db.query(models.DBEinvoiceIrn).filter(
        models.DBEinvoiceIrn.client_id == client.id, models.DBEinvoiceIrn.doc_type == doc_type,
        models.DBEinvoiceIrn.doc_id == doc.id).order_by(models.DBEinvoiceIrn.id.desc()).all()
    return {"number": doc.number or "", "ready": not problems, "missing": problems,
            "payload": payload if not problems else None,
            "irn": next((irn_dict(h) for h in history if h.status == "ACTIVE"), None),
            "history": [irn_dict(h) for h in history if h.status != "ACTIVE"]}


@router.get("/api/einvoice/{doc_type}/{doc_id}/json")
def einvoice_file(doc_type: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    doc, payload, problems = einvoice_document(db, client, doc_type, doc_id)
    if problems:
        raise HTTPException(409, "Not ready for the portal - still needed: " + "; ".join(problems) + ".")
    name = re.sub(r"[^A-Za-z0-9]+", "_", doc.number or doc_type)
    return StreamingResponse(io.BytesIO(json.dumps([payload], indent=2, ensure_ascii=False).encode("utf-8")),
                             media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="einvoice_%s.json"' % name})


@router.post("/api/einvoice/{doc_type}/{doc_id}/irn")
def record_irn(doc_type: str, doc_id: int, request: Request, body: dict = None,
               db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "accounts.manage")
    doc, payload, problems = einvoice_document(db, client, doc_type, doc_id)
    if problems:
        raise HTTPException(409, "%s is not ready for the portal - still needed: %s."
                                 % (doc.number, "; ".join(problems)))
    f = parse_irn_input(body or {})
    irn = f["irn"].lower()
    if not re.match(r"^[0-9a-f]{64}$", irn):
        raise HTTPException(400, "An IRN is 64 characters, the digits 0-9 and letters a-f.")
    if not re.match(r"^\d{10,20}$", f["ack_no"]):
        raise HTTPException(400, "The acknowledgement number - the long number the portal gave with the IRN.")
    ack = ack_datetime(f["ack_date"])
    if not ack:
        raise HTTPException(400, "The acknowledgement date and time, as the portal gave it.")
    if not f["signed_qr"]:
        raise HTTPException(400, "The signed QR code (SignedQRCode). The printed invoice has to carry it.")
    qr = _signed_qr_data(f["signed_qr"])
    if qr is None:
        raise HTTPException(400, "That signed QR could not be read. Copy it whole - it is one long line "
                                 "with two dots in it.")
    wrong = []
    if qr.get("Irn") and str(qr["Irn"]).lower() != irn:
        wrong.append("the QR carries a different IRN")
    if qr.get("SellerGstin") and str(qr["SellerGstin"]).upper() != payload["SellerDtls"].get("Gstin", ""):
        wrong.append("it was registered by %s, not us" % qr["SellerGstin"])
    if qr.get("BuyerGstin") and str(qr["BuyerGstin"]).upper() != payload["BuyerDtls"].get("Gstin", ""):
        wrong.append("its buyer is %s, this bill's is %s" % (qr["BuyerGstin"], payload["BuyerDtls"].get("Gstin", "")))
    if qr.get("DocNo") and str(qr["DocNo"]).upper() != payload["DocDtls"]["No"].upper():
        wrong.append("it is invoice %s, this bill goes up as %s" % (qr["DocNo"], payload["DocDtls"]["No"]))
    try:
        if qr.get("TotInvVal") is not None and abs(float(qr["TotInvVal"]) - payload["ValDtls"]["TotInvVal"]) > 1:
            wrong.append("it is for %s, this bill is %s" % (inr(float(qr["TotInvVal"])),
                                                            inr(payload["ValDtls"]["TotInvVal"])))
    except (TypeError, ValueError):
        wrong.append("its value could not be read")
    if wrong:
        raise HTTPException(409, "That is not %s's registration: %s." % (doc.number, "; ".join(wrong)))
    if active_irn(db, client.id, doc_type, doc.id):
        raise HTTPException(409, "%s already has an IRN. Cancel that one first." % doc.number)
    other = db.query(models.DBEinvoiceIrn).filter(models.DBEinvoiceIrn.client_id == client.id,
                                                  models.DBEinvoiceIrn.irn == irn,
                                                  models.DBEinvoiceIrn.status == "ACTIVE").first()
    if other:
        raise HTTPException(409, "That IRN is already on %s." % other.doc_number)
    row = models.DBEinvoiceIrn(
        client_id=client.id, doc_type=doc_type, doc_id=doc.id, doc_number=doc.number or "", irn=irn,
        ack_no=f["ack_no"], ack_date=ack.strftime("%Y-%m-%d %H:%M:%S"), signed_qr=f["signed_qr"],
        signed_invoice=f["signed_invoice"][:200000], qr_data=json.dumps(qr)[:4000],
        ewb_no=re.sub(r"\D", "", f["ewb_no"])[:12], created_by_name=actor_name or "")
    db.add(row)
    db.flush()
    log_audit(db, client.id, "irn_recorded", doc_type, doc.id, doc.number, "IRN %s..., ack %s" % (irn[:12], f["ack_no"]),
              request)
    db.commit()
    return {"irn": irn_dict(row), "message": "IRN recorded on %s. The QR now prints on the bill." % doc.number}


@router.get("/api/gst/inward.xlsx")
def gst_inward_export(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    d = gst_inward(request, date_from, date_to, db)
    rows = [(r["date"], r["kind"], r["number"], r["party"], r.get("party_gstin", ""), r.get("sac", ""), r["rate"],
             r["taxable"], r["cgst"], r["sgst"], r["igst"], r["tax"]) for r in d["supplies"]]
    s = d["summary"]
    return sheet_response(("Date", "Kind", "Number", "Party", "GSTIN", "SAC/HSN", "Rate %", "Taxable", "CGST", "SGST",
                           "IGST", "Tax"), rows, "gst_inward.xlsx",
                          preamble=_pre(client, "GST - INPUT REGISTER", ("Period", "%s to %s" % (date_from or "start", date_to or "today"))),
                          closing=[(), ("Total", "", "", "", "", "", "", s["taxable"], s["cgst"], s["sgst"], s["igst"], s["tax"])])
