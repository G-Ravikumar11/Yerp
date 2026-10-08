"""The rules and workings behind the invoicing endpoints."""
import base64
import json
import os
import re
from datetime import date, datetime, timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import models
from app.db import SessionLocal

from app.constants.common import REMINDER_LADDER
from app.constants.invoicing import (
    EWAY_DOC_TYPES,
    EWAY_MODES,
    EWAY_SUB_TYPES,
    EWAY_THRESHOLD,
    IRN_CANCEL_HOURS,
    UQC,
    VEHICLE_NO,
)
from app.core.config import logger
from app.core.currency import DEFAULT_CURRENCY, compute_invoice_totals, currency_symbol, esc, money
from app.core.dates import _parse_date, ack_datetime, advance_date
from app.core.gst import GST_STATES, WORKS_CONTRACT_SAC, state_from_gstin, state_from_pin
from app.core.scheduler import scheduled_job
from app.core.serials import invoice_prefix_for, next_sequence_number
from app.core.tenant_settings import tenant_setting
from app.core.units import canonical_unit
from app.schemas.invoicing import EwayLineIn


def apply_payment_status(inv):
    """Keep status/paid/due consistent after a payment changes."""
    total = money((inv.paid or 0) + (inv.due or 0))
    if (inv.due or 0) <= 0.005 and total > 0:
        inv.due = 0.0
        inv.status = "Paid"
    elif (inv.paid or 0) > 0.005:
        inv.status = "Partially Paid"
    return inv


def payment_terms_for(db, client_id):
    try:
        days = int(float(tenant_setting(db, client_id, "default_payment_terms", 14)))
    except (TypeError, ValueError):
        return 14
    return days if 0 <= days <= 365 else 14


def send_whatsapp_background(phone_number: str, message: str):
    with SessionLocal() as db:
        setting_id = db.query(models.DBSettings).filter(models.DBSettings.key == "WHATSAPP_PHONE_NUMBER_ID").first()
        phone_number_id = setting_id.value if setting_id else os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        setting_token = db.query(models.DBSettings).filter(models.DBSettings.key == "WHATSAPP_ACCESS_TOKEN").first()
        access_token = setting_token.value if setting_token else os.getenv("WHATSAPP_ACCESS_TOKEN")

    if not phone_number_id or not access_token:
        logger.warning("WhatsApp credentials missing")
        return

    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": phone_number, "type": "text", "text": {"body": message}}

    try:
        response = httpx.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"WhatsApp message sent to {phone_number}")
    except Exception as e:
        logger.error(f"Failed to send WhatsApp: {str(e)}")


def recurring_to_dict(t, db=None):
    return {
        "id": t.id,
        "name": t.name or "",
        "to": t.to_contact or "",
        "email": t.email or "",
        "phone_number": t.phone_number or "",
        "reference": t.reference or "",
        "frequency": t.frequency,
        "payment_terms_days": t.payment_terms_days or 14,
        "next_run": t.next_run or "",
        "end_date": t.end_date or "",
        "is_active": bool(t.is_active),
        "auto_send": bool(t.auto_send),
        "last_run": t.last_run or "",
        "last_invoice_number": t.last_invoice_number or "",
        "invoices_created": t.invoices_created or 0,
        "tax_type": t.tax_type,
        "currency": t.currency or "",
        "total": compute_invoice_totals(t.line_items, t.tax_type)[2],
        "line_items": [{
            "name": li.name or "", "description": li.description, "qty": li.qty,
            "price": li.price, "disc": li.disc, "account": li.account,
            "tax_rate": li.tax_rate,
        } for li in t.line_items],
    }


def issue_recurring_invoice(db, t, on_date):
    """Raise one invoice from a template and move the schedule on."""
    subtotal, tax, total = compute_invoice_totals(t.line_items, t.tax_type)
    number = next_sequence_number(db, models.DBInvoice, t.client_id, invoice_prefix_for(db, t.client_id))
    due = on_date + timedelta(days=t.payment_terms_days or 14)

    inv = models.DBInvoice(
        client_id=t.client_id, number=number, ref=t.reference or "",
        to_contact=t.to_contact, email=t.email or "", phone_number=t.phone_number or "",
        issue_date=on_date.strftime("%Y-%m-%d"), due_date=due.strftime("%Y-%m-%d"),
        paid=0.00, due=round(total, 2), status="Draft", sent="",
        tax_type=t.tax_type, currency=t.currency or "", bank_details=t.bank_details or "",
    )
    db.add(inv)
    db.flush()
    for li in t.line_items:
        db.add(models.DBLineItem(
            invoice_id=inv.id, name=li.name or "", description=li.description,
            qty=li.qty, price=li.price, disc=li.disc or 0.0,
            account=li.account, tax_rate=li.tax_rate,
        ))

    t.last_run = on_date.strftime("%Y-%m-%d")
    t.last_invoice_number = number
    t.invoices_created = (t.invoices_created or 0) + 1
    nxt = advance_date(on_date, t.frequency)
    t.next_run = nxt.strftime("%Y-%m-%d")
    # A template that has reached its end date stops rather than lingering.
    end = _parse_date(t.end_date)
    if end and nxt > end:
        t.is_active = False
    return inv


@scheduled_job("recurring_invoices")
def job_recurring_invoices(db, now):
    """Raise whatever is due today.

    Catches up if the app was down: a template whose date has passed is issued
    for each period it missed, rather than silently losing months.
    """
    today = now.date()
    issued = 0
    templates = db.query(models.DBRecurringInvoice).filter(
        models.DBRecurringInvoice.is_active == True,          # noqa: E712
        models.DBRecurringInvoice.next_run != "",
        models.DBRecurringInvoice.next_run <= today.strftime("%Y-%m-%d"),
    ).all()
    for t in templates:
        guard = 0
        while t.is_active and guard < 60:
            due_on = _parse_date(t.next_run)
            if not due_on or due_on > today:
                break
            end = _parse_date(t.end_date)
            if end and due_on > end:
                t.is_active = False
                break
            if not t.line_items:
                break
            issue_recurring_invoice(db, t, due_on)
            issued += 1
            guard += 1
    db.commit()
    return f"{issued} invoice(s) raised"


def reminder_stage_for(days_overdue):
    """The highest rung reached, so a gap in ticks does not skip a chase."""
    reached = [d for d in REMINDER_LADDER if days_overdue >= d]
    return max(reached) if reached else None


@scheduled_job("overdue_reminders")
def job_overdue_reminders(db, now):
    """Chase invoices that have gone past their due date.

    A paid, part-paid or void invoice is never chased, and each rung of the
    ladder goes out at most once per invoice.
    """
    today = now.date()
    sent = 0
    candidates = db.query(models.DBInvoice).filter(
        models.DBInvoice.status.notin_(["Paid", "Void", "Draft"]),
        models.DBInvoice.due > 0,
        models.DBInvoice.due_date != "",
    ).all()

    for inv in candidates:
        due_date = _parse_date(inv.due_date)
        if not due_date or due_date >= today:
            continue
        stage = reminder_stage_for((today - due_date).days)
        if stage is None or not inv.email or not validate_email_address(inv.email):
            continue

        already = db.query(models.DBInvoiceReminder).filter(
            models.DBInvoiceReminder.invoice_id == inv.id,
            models.DBInvoiceReminder.stage_days == stage,
        ).first()
        if already:
            continue

        settings_rows = db.query(models.DBSettings).filter(
            models.DBSettings.client_id == inv.client_id).all()
        settings_map = {s.key: s.value for s in settings_rows}
        inv_client = db.query(models.DBClient).filter(
            models.DBClient.id == inv.client_id).first()
        company = (settings_map.get("company_name", "")
                   or (inv_client.company_name if inv_client else "") or "Accounts")
        cur = currency_symbol((inv.currency or DEFAULT_CURRENCY).upper())
        days = (today - due_date).days

        subject = f"Reminder: invoice {inv.number} is {days} day(s) overdue"
        text_body = (
            f"Hello {inv.to_contact},\n\n"
            f"Invoice {inv.number} for {cur}{inv.due:.2f} was due on {inv.due_date} "
            f"and is now {days} day(s) overdue.\n\n"
            "If you have already paid, please ignore this note.\n\n"
            f"Kind regards,\n{company}\n"
        )
        html_body = f"""
        <!DOCTYPE html><html><body style="font-family:Arial,Helvetica,sans-serif;background:#f1f5f9;margin:0;padding:0;">
          <div style="max-width:520px;margin:0 auto;padding:40px 20px;">
            <div style="background:#fff;border-radius:12px;overflow:hidden;">
              <div style="background:#0f172a;padding:28px;text-align:center;">
                <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#94a3b8;">Payment reminder</div>
                <div style="font-size:24px;font-weight:800;color:#fff;margin-top:6px;">{esc(inv.number)}</div>
              </div>
              <div style="padding:26px;">
                <p style="margin:0 0 16px;font-size:15px;">Hello {esc(inv.to_contact)},</p>
                <p style="margin:0 0 18px;font-size:15px;color:#475569;">
                  Invoice <strong>{esc(inv.number)}</strong> for
                  <strong>{cur}{inv.due:.2f}</strong> was due on
                  <strong>{esc(inv.due_date)}</strong>, which is {days} day(s) ago.
                </p>
                <p style="margin:0;font-size:13px;color:#64748b;">
                  If you have already paid, please ignore this note.
                </p>
              </div>
              <div style="background:#f8fafc;padding:18px;text-align:center;border-top:1px solid #e2e8f0;">
                <div style="font-size:13px;font-weight:700;color:#0f172a;">{esc(company)}</div>
              </div>
            </div>
          </div>
        </body></html>
        """

        from_email = default_from_email()
        # Recorded before sending, and the unique index means a second worker
        # racing this cannot send the same rung twice.
        db.add(models.DBInvoiceReminder(
            client_id=inv.client_id, invoice_id=inv.id,
            stage_days=stage, sent_to=inv.email,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue

        send_email_background(
            inv.email, subject, text_body, f"{company} <{from_email}>",
            html_body, None, "", "", client_id=inv.client_id,
        )
        sent += 1

    return f"{sent} reminder(s) sent"


def _month_key(d):
    return (d or "")[:7]


def _pin_from(text):
    m = re.search(r"\b(\d{6})\b", text or "")
    return m.group(1) if m else ""


def _addr_lines(text):
    parts = [p.strip() for p in re.split(r"[\n,]", text or "") if p.strip()]
    one = ", ".join(parts[:2])[:100]
    two = ", ".join(parts[2:4])[:100]
    return one, two, (parts[-1][:50] if parts else "")


def einvoice_buyer(db, client_id, job):
    """The contact the project points at, else a contact of the same name."""
    c = None
    if job and job.contact_id:
        c = db.query(models.DBContact).filter(models.DBContact.id == job.contact_id,
                                              models.DBContact.client_id == client_id).first()
    if not c and job and job.customer_name:
        c = next((x for x in db.query(models.DBContact).filter(
            models.DBContact.client_id == client_id).all()
            if norm_name(x.name) == norm_name(job.customer_name)), None)
    return c


def einvoice_parties(db, client, job, place_of_supply, problems):
    """The seller and buyer blocks of an e-invoice. Whatever the portal would
    refuse is named in `problems` instead of being sent."""
    buyer = einvoice_buyer(db, client.id, job)

    seller_gstin = (client.gstin or "").strip().upper()
    if not seller_gstin:
        problems.append("our GSTIN (Money > GST)")
    our_address = company_address(db, client)
    seller_pin = _pin_from(our_address)
    if not seller_pin:
        problems.append("a six-digit PIN in our address (Settings > Company details)")
    s1, s2, sloc = _addr_lines(our_address)

    b_gstin = (buyer.gstin or "").strip().upper() if buyer else ""
    if not buyer:
        problems.append("the client as a contact on the project (so their GSTIN and address are on file)")
    elif not b_gstin:
        problems.append("the client's GSTIN on their contact")
    b_addr = ""
    if buyer:
        b_addr = ", ".join(x for x in (buyer.address or "", getattr(buyer, "city", "") or "") if x)
    b_pin = (getattr(buyer, "pincode", "") or "").strip() if buyer else ""
    b_pin = b_pin if re.match(r"^\d{6}$", b_pin) else _pin_from(b_addr)
    if buyer and not b_pin:
        problems.append("a six-digit PIN on the client's contact")
    if not place_of_supply:
        problems.append("the state the site is in (Projects > place of supply)")
    b1, b2, bloc = _addr_lines(b_addr)
    seller = {"Gstin": seller_gstin, "LglNm": (client.company_name or "")[:100],
              "Addr1": s1 or (client.company_name or "")[:100], "Addr2": s2 or None,
              "Loc": sloc or "-", "Pin": int(seller_pin) if seller_pin else None,
              "Stcd": seller_gstin[:2] if seller_gstin else None}
    buyer_block = {"Gstin": b_gstin,
                   "LglNm": ((buyer.name if buyer else job.customer_name if job else "") or "")[:100],
                   "Pos": place_of_supply or None, "Addr1": b1 or "-", "Addr2": b2 or None,
                   "Loc": bloc or "-", "Pin": int(b_pin) if b_pin else None,
                   "Stcd": b_gstin[:2] if b_gstin else None}
    # Leave optional keys out rather than send nulls the portal rejects.
    return ({k: v for k, v in seller.items() if v is not None},
            {k: v for k, v in buyer_block.items() if v is not None})


def einvoice_doc_number(number):
    """The portal takes sixteen characters; RA numbers built from order
    numbers run longer, so the invoice carries a shortened form and the full
    number rides along as a reference."""
    number = re.sub(r"[^A-Za-z0-9/\-]", "", number or "")
    if len(number) > 16:
        number = number[-16:].lstrip("/-")
    return number


def einvoice_payload(db, client, bill):
    """(payload, problems). The payload is only worth sending when the list
    of problems is empty."""
    problems = []
    if bill.status not in ("CERTIFIED", "PAID"):
        problems.append("the bill is %s - only a certified bill is invoiced" % (bill.status or "").lower())
    job = db.query(models.DBJob).filter(models.DBJob.id == bill.job_id).first()
    seller, buyer = einvoice_parties(db, client, job, bill.place_of_supply, problems)
    number = einvoice_doc_number(bill.number)

    lines = db.query(models.DBRABillLine).filter(
        models.DBRABillLine.ra_bill_id == bill.id).order_by(
            models.DBRABillLine.display_order, models.DBRABillLine.id).all()
    lines = [l for l in lines if (l.amount or 0) > 0]
    if not lines:
        problems.append("at least one line with work on it")

    # The invoice is for the work measured; retention and recoveries are settled in payment, not taken off its value.
    deductions = 0.0
    gross = money(sum(l.amount or 0 for l in lines)) or 1.0
    rate = bill.tax_percent or 0
    intra = bool(bill.cgst_amount or bill.sgst_amount) and not bill.igst_amount
    items, used_disc, used = [], 0.0, {"ass": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0}
    for i, l in enumerate(lines, start=1):
        last = i == len(lines)
        tot = money(l.amount)
        disc = money(deductions - used_disc) if last else money(deductions * tot / gross)
        used_disc = money(used_disc + disc)
        ass = money(tot - disc)
        if last:
            # The last line takes the rounding, so the totals are exactly the
            # bill's - the figures the client's accounts will match against.
            taxable = money(bill.this_bill - deductions)
            ass = money(taxable - used["ass"])
            cg = money((bill.cgst_amount or 0) - used["cgst"])
            sg = money((bill.sgst_amount or 0) - used["sgst"])
            ig = money((bill.igst_amount or 0) - used["igst"])
        else:
            tax = money(ass * rate / 100.0)
            cg = money(tax / 2.0) if intra else 0.0
            sg = money(tax - cg) if intra else 0.0
            ig = 0.0 if intra else tax
        for k, v in (("ass", ass), ("cgst", cg), ("sgst", sg), ("igst", ig)):
            used[k] = money(used[k] + v)
        items.append({
            "SlNo": str(i), "PrdDesc": ((l.fg_code or "") + " " + (l.description or "").split("\n")[0]).strip()[:300],
            "IsServc": "Y", "HsnCd": WORKS_CONTRACT_SAC,
            "Qty": round(l.this_bill_qty or 0, 3), "Unit": UQC.get(canonical_unit(l.uom) or "", "OTH"),
            "UnitPrice": round(l.rate or 0, 3), "TotAmt": tot, "Discount": disc,
            "AssAmt": ass, "GstRt": rate, "IgstAmt": ig, "CgstAmt": cg, "SgstAmt": sg,
            "TotItemVal": money(ass + cg + sg + ig)})

    on = (bill.certified_at or bill.created_at or "")[:10]
    try:
        doc_date = datetime.strptime(on, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        doc_date = datetime.now().strftime("%d/%m/%Y")
    total_tax = money(used["cgst"] + used["sgst"] + used["igst"])
    payload = {
        "Version": "1.1",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "N", "IgstOnIntra": "N"},
        "DocDtls": {"Typ": "INV", "No": number, "Dt": doc_date},
        "SellerDtls": seller,
        "BuyerDtls": buyer,
        "ItemList": items,
        "ValDtls": {"AssVal": used["ass"], "CgstVal": used["cgst"], "SgstVal": used["sgst"],
                    "IgstVal": used["igst"], "TotInvVal": money(used["ass"] + total_tax)},
        "RefDtls": {"InvRm": ("RA bill %s against %s" % (bill.number, job.name if job else ""))[:100]},
    }
    if money(payload["ValDtls"]["TotInvVal"]) != money(bill.this_bill - deductions + (bill.tax_amount or 0)):
        problems.append("the tax on the bill does not add up - redraw the bill")
    return payload, problems


def next_eway_number(db, client_id):
    n = db.query(models.DBEwayBill).filter(models.DBEwayBill.client_id == client_id).count() + 1
    return "EWB-%04d" % n


def eway_places(db, client):
    """Where goods leave from and arrive at: the company's own address, and
    each project's site - with the PIN and state the portal needs."""
    gstin = (client.gstin or "").strip().upper()
    home = company_address(db, client)
    out = [{"key": "company", "name": client.company_name or "Head office", "gstin": gstin,
            "address": home, "pincode": _pin_from(home),
            "state": state_from_gstin(gstin) or state_from_pin(home), "job_id": None}]
    for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).order_by(
            models.DBJob.id.desc()).all():
        if (j.status or "") == "cancelled":
            continue
        out.append({"key": "job-%d" % j.id, "name": "%s %s" % (j.number or "", j.name or ""),
                    "gstin": gstin, "address": j.site_address or "",
                    "pincode": _pin_from(j.site_address),
                    "state": (j.state_code or "").strip() or state_from_pin(j.site_address),
                    "job_id": j.id})
    return out


def eway_totals(e, lines):
    """Taxable value and the tax on it, split the way the two states say."""
    taxable = money(sum(l.taxable or 0 for l in lines))
    tax = money(sum((l.taxable or 0) * (l.tax_rate or 0) / 100.0 for l in lines))
    intra = bool(e.from_state and e.to_state and e.from_state == e.to_state)
    half = money(tax / 2.0) if intra else 0.0
    e.taxable_value = taxable
    e.cgst = half
    e.sgst = money(tax - half) if intra else 0.0
    e.igst = 0.0 if intra else tax
    e.total_value = money(taxable + tax)


def eway_validity(ewb_date, distance_km, vehicle_type="R"):
    """Valid to the end of the day this many days on: one day for every 200 km
    (20 km for over-dimensional cargo), a day at the least."""
    try:
        start = datetime.strptime((ewb_date or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return ""
    per_day = 20 if vehicle_type == "O" else 200
    km = max(0, int(distance_km or 0))
    days = max(1, -(-km // per_day)) if km else 1
    return (start + timedelta(days=days)).isoformat() + " 23:59"


def eway_line_dict(l):
    return {"id": l.id, "item_code": l.item_code or "", "product_name": l.product_name or "",
            "hsn": l.hsn or "", "qty": l.qty or 0, "unit": l.unit or "",
            "taxable": money(l.taxable), "tax_rate": l.tax_rate or 0}


def eway_lines(db, e):
    return db.query(models.DBEwayBillLine).filter(
        models.DBEwayBillLine.eway_bill_id == e.id).order_by(
            models.DBEwayBillLine.display_order, models.DBEwayBillLine.id).all()


def eway_dict(db, e, detail=False):
    today = date.today().isoformat()
    expiring = bool(e.status == "GENERATED" and e.valid_upto and e.valid_upto[:10] <= today)
    out = {"id": e.id, "number": e.number, "source_type": e.source_type or "manual",
           "source_ref": e.source_ref or "", "job_id": e.job_id,
           "status": e.status or "DRAFT", "doc_type": e.doc_type, "doc_no": e.doc_no or "",
           "doc_date": e.doc_date or "", "supply_type": e.supply_type or "O",
           "sub_type": e.sub_type or "5",
           "sub_type_label": EWAY_SUB_TYPES.get(e.sub_type or "", e.sub_type_desc or ""),
           "from": {"name": e.from_name or "", "gstin": e.from_gstin or "",
                    "address": e.from_address or "", "place": e.from_place or "",
                    "pincode": e.from_pincode or "", "state": e.from_state or "",
                    "state_name": GST_STATES.get(e.from_state or "", "")},
           "to": {"name": e.to_name or "", "gstin": e.to_gstin or "",
                  "address": e.to_address or "", "place": e.to_place or "",
                  "pincode": e.to_pincode or "", "state": e.to_state or "",
                  "state_name": GST_STATES.get(e.to_state or "", "")},
           "distance_km": e.distance_km or 0, "trans_mode": e.trans_mode or "1",
           "vehicle_no": e.vehicle_no or "", "vehicle_type": e.vehicle_type or "R",
           "transporter_id": e.transporter_id or "", "transporter_name": e.transporter_name or "",
           "trans_doc_no": e.trans_doc_no or "", "trans_doc_date": e.trans_doc_date or "",
           "taxable_value": money(e.taxable_value), "cgst": money(e.cgst), "sgst": money(e.sgst),
           "igst": money(e.igst), "total_value": money(e.total_value),
           "ewb_no": e.ewb_no or "", "ewb_date": e.ewb_date or "", "valid_upto": e.valid_upto or "",
           "expired": expiring, "cancel_reason": e.cancel_reason or "",
           "needed": money(e.total_value) > EWAY_THRESHOLD,
           "created_by_name": e.created_by_name or "", "created_at": e.created_at or ""}
    if detail:
        lines = eway_lines(db, e)
        out["lines"] = [eway_line_dict(l) for l in lines]
        out["vehicle_history"] = [x for x in (e.vehicle_history or "").split("\n") if x]
        out["problems"] = eway_problems(db, e, lines)
    return out


def eway_problems(db, e, lines=None):
    """What the portal would refuse, in words."""
    lines = lines if lines is not None else eway_lines(db, e)
    p = []
    if not (e.from_gstin or "").strip():
        p.append("our GSTIN (Settings > Company details)")
    for side, pin, state in (("from", e.from_pincode, e.from_state), ("to", e.to_pincode, e.to_state)):
        if not re.match(r"^[1-9][0-9]{5}$", pin or ""):
            p.append("a six-digit PIN for where it goes %s" % side)
        if not state or state not in GST_STATES:
            p.append("the state it goes %s" % side)
    if not (e.doc_no or "").strip():
        p.append("the challan or invoice number")
    elif len(re.sub(r"[^A-Za-z0-9/\-]", "", e.doc_no)) > 16:
        p.append("a document number of sixteen characters or fewer")
    if not e.doc_date:
        p.append("the document date")
    if (e.distance_km or 0) > 4000:
        p.append("a distance under 4,000 km")
    if e.vehicle_no and (e.trans_mode or "1") == "1" and not VEHICLE_NO.match(e.vehicle_no):
        p.append("a vehicle number written like TS09UB1234")
    if not lines:
        p.append("at least one item")
    for i, l in enumerate(lines, start=1):
        if not re.match(r"^[0-9]{4,8}$", l.hsn or ""):
            p.append("the HSN code on line %d (%s)" % (i, l.product_name or l.item_code or "item"))
        if not (l.qty or 0) > 0:
            p.append("a quantity on line %d" % i)
    return p


def eway_payload(db, client, e):
    """One bill in the NIC bulk-generation format."""
    lines = eway_lines(db, e)
    fmt = lambda d: (datetime.strptime(d[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if d else "")
    f1, f2, _ = _addr_lines(e.from_address)
    t1, t2, _ = _addr_lines(e.to_address)
    intra = bool(e.from_state and e.from_state == e.to_state)
    items = []
    for i, l in enumerate(lines, start=1):
        rate = l.tax_rate or 0
        items.append({
            "itemNo": i, "productName": (l.product_name or l.item_code or "")[:100],
            "productDesc": (l.product_name or "")[:100], "hsnCode": int(l.hsn) if (l.hsn or "").isdigit() else 0,
            "quantity": round(l.qty or 0, 3), "qtyUnit": UQC.get(canonical_unit(l.unit) or "", "OTH"),
            "taxableAmount": money(l.taxable),
            "sgstRate": rate / 2.0 if intra else 0, "cgstRate": rate / 2.0 if intra else 0,
            "igstRate": 0 if intra else rate, "cessRate": 0, "cessNonAdvol": 0})
    bill = {
        "userGstin": (client.gstin or "").upper(), "supplyType": e.supply_type or "O",
        "subSupplyType": int(e.sub_type or 5),
        "subSupplyDesc": (e.sub_type_desc or "")[:20] if (e.sub_type or "") == "8" else "",
        "docType": e.doc_type or "CHL",
        "docNo": re.sub(r"[^A-Za-z0-9/\-]", "", e.doc_no or "")[:16], "docDate": fmt(e.doc_date),
        "fromGstin": e.from_gstin or "URP", "fromTrdName": (e.from_name or "")[:100],
        "fromAddr1": f1 or "-", "fromAddr2": f2, "fromPlace": (e.from_place or "")[:50],
        "fromPincode": int(e.from_pincode) if (e.from_pincode or "").isdigit() else 0,
        "fromStateCode": int(e.from_state or 0), "actFromStateCode": int(e.from_state or 0),
        "toGstin": e.to_gstin or "URP", "toTrdName": (e.to_name or "")[:100],
        "toAddr1": t1 or "-", "toAddr2": t2, "toPlace": (e.to_place or "")[:50],
        "toPincode": int(e.to_pincode) if (e.to_pincode or "").isdigit() else 0,
        "toStateCode": int(e.to_state or 0), "actToStateCode": int(e.to_state or 0),
        "transactionType": 1,
        "totalValue": money(e.taxable_value), "cgstValue": money(e.cgst), "sgstValue": money(e.sgst),
        "igstValue": money(e.igst), "cessValue": 0, "cessNonAdvolValue": 0, "otherValue": 0,
        "totInvValue": money(e.total_value),
        "transMode": int(e.trans_mode or 1), "transDistance": int(e.distance_km or 0),
        "transporterName": (e.transporter_name or "")[:100], "transporterId": e.transporter_id or "",
        "transDocNo": e.trans_doc_no or "", "transDocDate": fmt(e.trans_doc_date),
        "vehicleNo": (e.vehicle_no or "").upper(), "vehicleType": e.vehicle_type or "R",
        "itemList": items,
    }
    return {"version": "1.0.0621", "billLists": [bill]}


def _eway_apply(db, client, e, body):
    places = {p["key"]: p for p in eway_places(db, client)}
    for side in ("from", "to"):
        key = getattr(body, side + "_key") or ""
        if key and key in places:
            pl = places[key]
            setattr(e, side + "_name", pl["name"])
            setattr(e, side + "_gstin", pl["gstin"])
            setattr(e, side + "_address", pl["address"])
            setattr(e, side + "_pincode", pl["pincode"])
            setattr(e, side + "_state", pl["state"])
            setattr(e, side + "_place", (_addr_lines(pl["address"])[2] or pl["name"])[:50])
            if side == "to" and pl["job_id"]:
                e.job_id = pl["job_id"]
        for f in ("name", "gstin", "address", "pincode", "state"):
            v = getattr(body, "%s_%s" % (side, f))
            if v is not None:
                v = v.strip()
                if f == "gstin":
                    v = v.upper()
                setattr(e, "%s_%s" % (side, f), v)
        if getattr(body, side + "_address") is not None:
            setattr(e, side + "_place", (_addr_lines(getattr(e, side + "_address"))[2] or "")[:50])
        if not getattr(e, side + "_state") and getattr(e, side + "_gstin"):
            setattr(e, side + "_state", state_from_gstin(getattr(e, side + "_gstin")))
        if not getattr(e, side + "_state"):
            setattr(e, side + "_state", state_from_pin(getattr(e, side + "_address") or getattr(e, side + "_pincode") or ""))
    e.supply_type = body.supply_type if body.supply_type in ("O", "I") else "O"
    if body.sub_type:
        if body.sub_type not in EWAY_SUB_TYPES:
            raise HTTPException(400, "Not a sub-supply type the portal knows: %s" % body.sub_type)
        e.sub_type = body.sub_type
    e.sub_type_desc = (body.sub_type_desc or "").strip()[:20]
    if body.doc_type:
        if body.doc_type not in EWAY_DOC_TYPES:
            raise HTTPException(400, "Not a document type the portal knows: %s" % body.doc_type)
        e.doc_type = body.doc_type
    if body.doc_no:
        e.doc_no = body.doc_no.strip()
    if body.doc_date:
        e.doc_date = body.doc_date[:10]
    e.distance_km = max(0, int(body.distance_km or 0))
    e.trans_mode = body.trans_mode if body.trans_mode in EWAY_MODES else "1"
    e.vehicle_no = re.sub(r"[\s\-]", "", (body.vehicle_no or "")).upper()
    e.vehicle_type = body.vehicle_type if body.vehicle_type in ("R", "O") else "R"
    e.transporter_id = (body.transporter_id or "").strip().upper()
    e.transporter_name = (body.transporter_name or "").strip()
    e.trans_doc_no = (body.trans_doc_no or "").strip()
    e.trans_doc_date = (body.trans_doc_date or "")[:10]


def _eway_set_lines(db, client, e, lines):
    db.query(models.DBEwayBillLine).filter(models.DBEwayBillLine.eway_bill_id == e.id).delete()
    made = []
    for i, l in enumerate(lines or []):
        if not ((l.item_code or "").strip() or (l.product_name or "").strip()):
            continue
        item = db.query(models.DBItem).filter(models.DBItem.item_code == (l.item_code or "").strip()).first() \
            if (l.item_code or "").strip() else None
        row = models.DBEwayBillLine(
            eway_bill_id=e.id, item_code=(l.item_code or "").strip(),
            product_name=(l.product_name or (item.item_name if item else "") or "").strip(),
            hsn=re.sub(r"\D", "", (l.hsn or (item.hsn_code if item else "") or "")),
            qty=max(0.0, float(l.qty or 0)),
            unit=canonical_unit(l.unit or (item.units_of_measure if item else ""), default="") or (l.unit or ""),
            taxable=money(max(0.0, float(l.taxable or 0))),
            tax_rate=max(0.0, min(28.0, float(l.tax_rate or 0))), display_order=i)
        db.add(row)
        made.append(row)
    db.flush()
    return made


def eway_or_404(db, client_id, eid):
    e = db.query(models.DBEwayBill).filter(models.DBEwayBill.id == eid,
                                           models.DBEwayBill.client_id == client_id).first()
    if not e:
        raise HTTPException(404, "E-way bill not found")
    return e


def transfer_lines_for(db, client_id, number):
    """The lines of a store transfer, priced at what they cost, with HSN."""
    rows = db.query(models.DBStockMovement).filter(
        models.DBStockMovement.client_id == client_id,
        models.DBStockMovement.kind == "TRANSFER_OUT",
        models.DBStockMovement.source_ref == number).all()
    out = []
    for m in rows:
        item = db.query(models.DBItem).filter(models.DBItem.item_code == m.item_code).first()
        out.append(EwayLineIn(item_code=m.item_code, product_name=m.item_name or (item.item_name if item else ""),
                              hsn=(item.hsn_code if item else ""), qty=money(-m.quantity), unit=m.uom or "",
                              taxable=money(-(m.value or 0)), tax_rate=0))
    return rows, out


def einvoice_release_payload(db, client, r):
    """A retention release claimed from the client, as an e-invoice: one
    line, the retention given back, at the rate the release was taxed at."""
    problems = []
    if r.side != "client":
        problems.append("a contractor's release is their invoice to us, not ours")
    if r.status not in ("CERTIFIED", "PAID"):
        problems.append("the release is %s" % (r.status or "").lower())
    job = db.query(models.DBJob).filter(models.DBJob.id == r.job_id).first()
    seller, buyer = einvoice_parties(db, client, job, r.place_of_supply, problems)
    ass = money(r.amount)
    try:
        doc_date = datetime.strptime((r.release_on or "")[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        doc_date = datetime.now().strftime("%d/%m/%Y")
    payload = {
        "Version": "1.1",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "N", "IgstOnIntra": "N"},
        "DocDtls": {"Typ": "INV", "No": einvoice_doc_number(r.number), "Dt": doc_date},
        "SellerDtls": seller, "BuyerDtls": buyer,
        "ItemList": [{"SlNo": "1", "PrdDesc": ("Retention released - %s" % (r.stage or "")).strip()[:300],
                      "IsServc": "Y", "HsnCd": WORKS_CONTRACT_SAC, "Qty": 1, "Unit": "OTH",
                      "UnitPrice": ass, "TotAmt": ass, "Discount": 0, "AssAmt": ass,
                      "GstRt": r.gst_percent or 0, "IgstAmt": money(r.igst_amount),
                      "CgstAmt": money(r.cgst_amount), "SgstAmt": money(r.sgst_amount),
                      "TotItemVal": money(r.net_amount)}],
        "ValDtls": {"AssVal": ass, "CgstVal": money(r.cgst_amount), "SgstVal": money(r.sgst_amount),
                    "IgstVal": money(r.igst_amount), "TotInvVal": money(r.net_amount)},
        "RefDtls": {"InvRm": ("Retention released, %s" % (job.name if job else ""))[:100]},
    }
    return payload, problems


def einvoice_document(db, client, doc_type, doc_id):
    """(the bill, its e-invoice payload, what is missing)."""
    if doc_type == "ra_bill":
        doc = ra_bill_or_404(db, client.id, doc_id)
        payload, problems = einvoice_payload(db, client, doc)
    elif doc_type == "retention_release":
        doc = release_or_404(db, client.id, doc_id)
        payload, problems = einvoice_release_payload(db, client, doc)
    else:
        raise HTTPException(404, "Not a document that is e-invoiced")
    return doc, payload, problems


def _signed_qr_data(token):
    """What a signed QR says: the JWT's payload, whose "data" is the invoice
    summary the portal registered. None when it is not one."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    try:
        raw = parts[1] + "=" * (-len(parts[1]) % 4)
        body = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


def _pick(obj, *names):
    low = {str(k).lower(): v for k, v in (obj or {}).items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return v
    return None


def parse_irn_input(body):
    """The IRN, acknowledgement and signed QR - from the portal's response
    pasted whole, or from the fields typed in one by one."""
    raw = body.get("response")
    src = {}
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "That is not the portal's response. Paste the JSON it gave back, "
                                     "or fill in the IRN, acknowledgement and QR below.")
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if isinstance(raw, dict):
        # Some responses carry the result inside: {"Status": 1, "Data": "{...}"}.
        inner = _pick(raw, "Data", "Result")
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except ValueError:
                inner = None
        src = inner if isinstance(inner, dict) and _pick(inner, "Irn") else raw
    got = {
        "irn": _pick(src, "Irn") or body.get("irn"),
        "ack_no": _pick(src, "AckNo", "AckNum") or body.get("ack_no"),
        "ack_date": _pick(src, "AckDt", "AckDate") or body.get("ack_date"),
        "signed_qr": _pick(src, "SignedQRCode", "SignedQrCode") or body.get("signed_qr"),
        "signed_invoice": _pick(src, "SignedInvoice") or body.get("signed_invoice"),
        "ewb_no": _pick(src, "EwbNo") or body.get("ewb_no"),
    }
    return {k: (str(v).strip() if v is not None else "") for k, v in got.items()}


def irn_dict(row):
    ack = ack_datetime(row.ack_date)
    try:
        qr = json.loads(row.qr_data or "{}")
    except ValueError:
        qr = {}
    return {"id": row.id, "doc_type": row.doc_type, "doc_id": row.doc_id, "doc_number": row.doc_number or "",
            "irn": row.irn or "", "ack_no": row.ack_no or "", "ack_date": row.ack_date or "",
            "ewb_no": row.ewb_no or "", "status": row.status or "ACTIVE",
            "cancel_reason": row.cancel_reason or "", "cancelled_at": row.cancelled_at or "",
            "created_by_name": row.created_by_name or "", "created_at": row.created_at or "",
            "qr_url": "/api/einvoice/irns/%d/qr.svg" % row.id,
            "registered": {"doc_no": qr.get("DocNo", ""), "doc_date": qr.get("DocDt", ""),
                           "value": qr.get("TotInvVal"), "buyer_gstin": qr.get("BuyerGstin", "")},
            "cancellable": bool(row.status == "ACTIVE" and ack and
                                datetime.now() - ack <= timedelta(hours=IRN_CANCEL_HOURS))}


def active_irn(db, client_id, doc_type, doc_id):
    return db.query(models.DBEinvoiceIrn).filter(
        models.DBEinvoiceIrn.client_id == client_id, models.DBEinvoiceIrn.doc_type == doc_type,
        models.DBEinvoiceIrn.doc_id == doc_id, models.DBEinvoiceIrn.status == "ACTIVE").first()


def irn_brief(db, client_id, doc_type, doc_id):
    row = active_irn(db, client_id, doc_type, doc_id)
    return irn_dict(row) if row else None


def refuse_cancel_with_irn(db, client_id, doc_type, doc):
    """A bill registered on the portal is cancelled there first. Cancelling
    it here alone would leave a live IRN for an invoice the books no longer
    have - and the client's GSTR-2B would still show it."""
    row = active_irn(db, client_id, doc_type, doc.id)
    if row:
        raise HTTPException(409, "%s has IRN %s... on the e-invoice portal. Cancel the IRN first "
                                 "(within %d hours of registering it), or raise a credit note."
                                 % (doc.number, row.irn[:12], IRN_CANCEL_HOURS))


def qr_svg(text, size=180):
    """The QR as one SVG path - a signed QR is a thousand characters, and
    drawn a square at a time it came to half a megabyte."""
    from reportlab.graphics.barcode import qrencoder
    q = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)
    q.addData(text)
    q.make()
    n, quiet = q.getModuleCount(), 4
    parts = []
    for r in range(n):
        c = 0
        while c < n:
            if q.isDark(r, c):
                start = c
                while c < n and q.isDark(r, c):
                    c += 1
                parts.append("M%d %dh%dv1h-%dz" % (start + quiet, r + quiet, c - start, c - start))
            else:
                c += 1
    total = n + 2 * quiet
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
            'shape-rendering="crispEdges"><rect width="%d" height="%d" fill="#fff"/>'
            '<path fill="#000" d="%s"/></svg>' % (total, total, size, size, total, total, "".join(parts)))


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.notifications import default_from_email, send_email_background
from app.documents.letterhead import company_address
from app.services.client_billing import ra_bill_or_404
from app.services.crm import norm_name
from app.services.subcontract_billing import release_or_404
from app.validators.common import validate_email_address
