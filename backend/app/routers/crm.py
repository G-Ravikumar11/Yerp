"""The crm endpoints."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.crm import (
    EMD_MODES,
    EST_TRANSITIONS,
    LEAD_OPEN,
    LEAD_SOURCES,
    LEAD_STATUSES,
    OPEN_INVOICE_STATUSES,
    QUOTE_STATUSES,
    RATE_KINDS,
    SALES_STAGES,
)
from app.core.audit import log_audit
from app.core.auth import get_client_user, owned_or_404, require_erp_read, require_items_access, wo_actor
from app.core.currency import (
    DEFAULT_CURRENCY,
    compute_invoice_totals,
    currency_symbol,
    esc,
    inr,
    line_net_amount,
    money,
    totals_by_currency,
    unit_rate,
)
from app.core.dates import _days_until, _parse_date
from app.core.notifications import default_from_email, send_email_background
from app.core.serials import invoice_prefix_for, next_sequence_number
from app.core.sheets import sheet_response
from app.schemas.crm import (
    CustomerIn,
    EmdReturnIn,
    EstimateIn,
    EstimateItemIn,
    LeadActivityIn,
    LeadIn,
    LeadMoveIn,
    QuoteConvert,
    QuoteCreate,
    QuoteDecision,
    RateLineIn,
    SendQuoteEmail,
)
from app.services.crm import (
    _apply_lead,
    _contact_tax_fields,
    _log_lead,
    backfill_customer_codes,
    contact_dict,
    customer_to_dict,
    estimate_dict,
    estimate_or_404,
    get_quote_or_404,
    invoice_overdue_days,
    lead_dict,
    lead_or_404,
    next_customer_code,
    next_lead_number,
    quote_display_status,
    quote_to_dict,
    recost_estimate,
    sales_stage_for_invoice,
    sales_stage_for_quote,
    standard_unit,
    state_name_of,
)
from app.services.projects import resolve_job_id
from app.services.subcontract_orders import work_order_from_estimate, work_order_to_dict
from app.services.wallet_ai import require_credit
from app.validators.common import (
    clean_tax_ids,
    validate_email_address,
    validate_invoice_dates,
    validate_line_items,
    validate_quote_dates,
)


router = APIRouter()


@router.get("/api/contacts/search")
def search_contacts(request: Request, q: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBContact).filter(models.DBContact.client_id == client.id)
    if q:
        from sqlalchemy import or_
        query = query.filter(or_(
            models.DBContact.name.ilike(f"%{q}%"),
            models.DBContact.email.ilike(f"%{q}%")
        ))
    contacts = query.limit(10).all()
    return [contact_dict(c) for c in contacts]


@router.get("/api/contacts")
def list_contacts(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    contacts = db.query(models.DBContact).filter(models.DBContact.client_id == client.id).all()
    return [contact_dict(c) for c in contacts]


@router.post("/api/contacts")
def create_contact(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body or not body.get("name"):
        raise HTTPException(status_code=400, detail="Name required")
    existing = db.query(models.DBContact).filter(models.DBContact.name == body["name"], models.DBContact.client_id == client.id).first()
    if existing:
        if body.get("email") and not existing.email:
            existing.email = body["email"]
        if body.get("phone_number") and not existing.phone_number:
            existing.phone_number = body["phone_number"]
        _contact_tax_fields(existing, body, only_blank=True)
        db.commit()
        return contact_dict(existing)
    contact = models.DBContact(name=body["name"], email=body.get("email", ""), phone_number=body.get("phone_number", ""), client_id=client.id)
    _contact_tax_fields(contact, body)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact_dict(contact)


@router.put("/api/contacts/{contact_id}")
def update_contact(contact_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    contact = db.query(models.DBContact).filter(models.DBContact.id == contact_id, models.DBContact.client_id == client.id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if body:
        if "name" in body: contact.name = body["name"]
        if "email" in body: contact.email = body["email"]
        if "phone_number" in body: contact.phone_number = body["phone_number"]
        _contact_tax_fields(contact, body, clear=True)
        db.commit()
        db.refresh(contact)
    return contact_dict(contact)


@router.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    contact = db.query(models.DBContact).filter(models.DBContact.id == contact_id, models.DBContact.client_id == client.id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    return {"ok": True}


@router.get("/api/customers")
def list_customers(request: Request, q: str = "", db: Session = Depends(get_db)):
    # Reading is open to the tenancy: anyone starting a project has to pick
    # the customer it is for, and hiding the list would only mean retyping.
    client = require_items_access(request, db, None)
    backfill_customer_codes(db, client.id)
    query = db.query(models.DBContact).filter(models.DBContact.client_id == client.id)
    if q:
        query = query.filter(or_(models.DBContact.name.ilike("%" + q + "%"),
                                 models.DBContact.code.ilike("%" + q + "%"),
                                 models.DBContact.gstin.ilike("%" + q + "%")))
    rows = query.order_by(models.DBContact.id.desc()).limit(500).all()
    return {"customers": [customer_to_dict(db, c, with_counts=True) for c in rows]}


@router.post("/api/customers")
def create_customer(body: CustomerIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "customers.manage")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "A customer name is required")
    # Case-insensitive, because "Fairview Homes" and "FAIRVIEW HOMES" are one
    # customer and two rows would split their projects between them.
    clash = db.query(models.DBContact).filter(
        models.DBContact.client_id == client.id,
        sqlfunc.lower(models.DBContact.name) == name.lower()).first()
    if clash:
        raise HTTPException(409, "'" + name + "' is already on the customer list")

    gstin, pan = clean_tax_ids(body.gstin, body.pan)
    contact = models.DBContact(
        client_id=client.id, code=next_customer_code(db, client.id), name=name, pan=pan,
        contact_person=(body.contact_person or "").strip(),
        email=(body.email or "").strip(), phone_number=(body.phone_number or "").strip(),
        gstin=gstin, address=(body.address or "").strip(),
        city=(body.city or "").strip(), state=(body.state or "").strip() or state_name_of(gstin),
        pincode=(body.pincode or "").strip(), notes=(body.notes or "").strip(),
        is_active=True)
    db.add(contact)
    log_audit(db, client.id, "customer_created", "customer", None, name, "", request)
    db.commit()
    db.refresh(contact)
    return dict(customer_to_dict(db, contact), message=contact.code + " added.")


@router.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, body: CustomerIn, request: Request,
                    db: Session = Depends(get_db)):
    client = require_items_access(request, db, "customers.manage")
    contact = db.query(models.DBContact).filter(
        models.DBContact.id == customer_id,
        models.DBContact.client_id == client.id).first()
    if not contact:
        raise HTTPException(404, "Customer not found")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "A customer name is required")
    contact.name = name
    for field in ("contact_person", "email", "phone_number", "address",
                  "city", "state", "pincode", "notes"):
        setattr(contact, field, (getattr(body, field) or "").strip())
    contact.gstin, contact.pan = clean_tax_ids(body.gstin, body.pan)
    if not contact.state:
        contact.state = state_name_of(contact.gstin)
    db.commit()
    return dict(customer_to_dict(db, contact), message="Customer updated.")


# CUSTOMER DETAIL - everything about one customer in one place
@router.get("/api/contacts/{contact_id}/detail")
def customer_detail(contact_id: int, request: Request, db: Session = Depends(get_db)):
    """One customer's whole history: what they were quoted, what they were
    invoiced, what they have paid and what they still owe.

    Invoices and quotes reference a customer by the name written on them, not
    by a foreign key, so they are gathered by name. Matching is case-insensitive
    because "Bramley Works" and "bramley works" are the same company.
    """
    client = get_client_user(request, db)
    contact = db.query(models.DBContact).filter(
        models.DBContact.id == contact_id,
        models.DBContact.client_id == client.id,
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Customer not found")

    name = (contact.name or "").strip().lower()
    today = datetime.now().date()

    invoices = [i for i in db.query(models.DBInvoice).filter(
        models.DBInvoice.client_id == client.id
    ).order_by(models.DBInvoice.id.desc()).all()
        if (i.to_contact or "").strip().lower() == name]

    quotes = [q for q in db.query(models.DBQuote).filter(
        models.DBQuote.client_id == client.id
    ).order_by(models.DBQuote.id.desc()).all()
        if (q.to_contact or "").strip().lower() == name]

    payments = []
    if invoices:
        by_id = {i.id: i for i in invoices}
        payments = [{
            "invoice_number": by_id[p.invoice_id].number,
            "amount": p.amount, "paid_on": p.paid_on,
            "method": p.method, "reference": p.reference or "",
        } for p in db.query(models.DBPayment).filter(
            models.DBPayment.invoice_id.in_(list(by_id))
        ).order_by(models.DBPayment.id.desc()).all()]

    open_invoices = [i for i in invoices if i.status in OPEN_INVOICE_STATUSES]
    overdue = [i for i in open_invoices if invoice_overdue_days(i, today) > 0]

    def totals(rows, amount):
        return totals_by_currency(
            [{"currency": r.currency, "total": amount(r)} for r in rows],
            fallback=client.currency or DEFAULT_CURRENCY)

    return {
        "contact": {
            "id": contact.id, "name": contact.name or "",
            "email": contact.email or "", "phone_number": contact.phone_number or "",
        },
        "summary": {
            "invoice_count": len(invoices),
            "quote_count": len(quotes),
            "overdue_count": len(overdue),
            # Per currency, because a customer billed in two currencies has two
            # balances, not one meaningless sum.
            "billed": totals(invoices, lambda i: (i.paid or 0) + (i.due or 0)),
            "paid": totals(invoices, lambda i: i.paid or 0),
            "outstanding": totals(open_invoices, lambda i: i.due or 0),
        },
        "invoices": [{
            "number": i.number, "date": i.issue_date, "due_date": i.due_date,
            "status": i.status, "paid": i.paid or 0, "due": i.due or 0,
            "currency": i.currency or (client.currency or ""),
            "is_overdue": invoice_overdue_days(i, today) > 0,
            "days_overdue": invoice_overdue_days(i, today),
        } for i in invoices],
        "quotes": [{
            "number": q.number, "date": q.issue_date, "expiry_date": q.expiry_date,
            "status": quote_display_status(q), "title": q.title or "",
            "total": compute_invoice_totals(q.line_items, q.tax_type)[2],
            "currency": q.currency or (client.currency or ""),
            "invoice_number": q.invoice_number or "",
        } for q in quotes],
        "payments": payments,
    }


@router.get("/api/sales/pipeline")
def sales_pipeline(request: Request, db: Session = Depends(get_db)):
    """The money flow in one place, worked out from the documents themselves.

    Nothing is dragged between columns: send a quote, accept it, convert it,
    take the payment, and the card moves because the document moved.
    """
    client = require_items_access(request, db, "reports.view")
    today = datetime.now().date()

    buckets = {key: [] for key, _, _ in SALES_STAGES}
    lost = []

    for q in db.query(models.DBQuote).filter(
            models.DBQuote.client_id == client.id).all():
        stage = sales_stage_for_quote(q)
        _, _, total = compute_invoice_totals(q.line_items, q.tax_type)
        card = {
            "kind": "quote", "number": q.number, "to": q.to_contact or "",
            "title": q.title or "", "total": total,
            "currency": q.currency or (client.currency or ""),
            "date": q.issue_date or "", "due_or_expiry": q.expiry_date or "",
            "status": quote_display_status(q),
            "invoice_number": q.invoice_number or "",
        }
        if stage:
            buckets[stage].append(card)
        elif card["status"] in ("Declined", "Expired"):
            lost.append(card)

    for inv in db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client.id).all():
        stage = sales_stage_for_invoice(inv)
        if not stage:
            continue
        overdue_days = invoice_overdue_days(inv, today)
        buckets[stage].append({
            "kind": "invoice", "number": inv.number, "to": inv.to_contact or "",
            "title": inv.ref or "", "total": money((inv.paid or 0) + (inv.due or 0)),
            "outstanding": inv.due or 0,
            "currency": inv.currency or (client.currency or ""),
            "date": inv.issue_date or "", "due_or_expiry": inv.due_date or "",
            "status": inv.status or "", "is_overdue": overdue_days > 0,
            "days_overdue": overdue_days,
        })

    for rows in buckets.values():
        # Overdue first, then biggest, because that is the order you act in.
        rows.sort(key=lambda c: (not c.get("is_overdue"), -(c.get("total") or 0)))

    base = client.currency or DEFAULT_CURRENCY
    open_stages = ("drafted", "sent", "accepted")
    open_cards = [c for k in open_stages for c in buckets[k]]

    return {
        "stages": [{
            "key": key, "label": label, "hint": hint,
            "count": len(buckets[key]),
            "totals": totals_by_currency(buckets[key], fallback=base),
            # The board can be long; the columns say how many are not shown.
            "cards": buckets[key][:40],
            "shown": min(len(buckets[key]), 40),
        } for key, label, hint in SALES_STAGES],
        "lost": {"count": len(lost),
                 "totals": totals_by_currency(lost, fallback=base)},
        "pipeline": {"count": len(open_cards),
                     "totals": totals_by_currency(open_cards, fallback=base)},
        "outstanding": totals_by_currency(
            buckets["invoiced"], field="outstanding", fallback=base),
        "overdue_count": sum(1 for c in buckets["invoiced"] if c.get("is_overdue")),
        "base_currency": base,
    }


@router.get("/api/quotes")
def get_quotes(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    quotes = db.query(models.DBQuote).filter(
        models.DBQuote.client_id == client.id
    ).order_by(models.DBQuote.id.desc()).all()
    return [quote_to_dict(q, client, db) for q in quotes]


@router.get("/api/quotes/{number}")
def get_quote(number: str, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    return quote_to_dict(get_quote_or_404(db, client, number), client, db, detail=True)


@router.post("/api/quotes")
def create_quote(quote: QuoteCreate, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)

    validate_line_items(quote.line_items)
    validate_quote_dates(quote.issue_date, quote.expiry_date)

    subtotal, tax, total = compute_invoice_totals(quote.line_items, quote.tax_type)

    if quote.contact and quote.contact.strip():
        existing = db.query(models.DBContact).filter(
            models.DBContact.name == quote.contact, models.DBContact.client_id == client.id
        ).first()
        if existing:
            if quote.email and not existing.email:
                existing.email = quote.email
            if quote.phone_number and not existing.phone_number:
                existing.phone_number = quote.phone_number
        else:
            db.add(models.DBContact(
                name=quote.contact, email=quote.email or "",
                phone_number=quote.phone_number or "", client_id=client.id))

    if quote.quote_number and quote.quote_number.strip():
        number = quote.quote_number.strip()
    else:
        number = next_sequence_number(db, models.DBQuote, client.id, "QU-")

    clash = db.query(models.DBQuote).filter(
        models.DBQuote.client_id == client.id, models.DBQuote.number == number
    ).first()
    if clash:
        raise HTTPException(status_code=409, detail=f"Quote number {number} already exists")

    status = quote.status if quote.status in QUOTE_STATUSES else "Draft"
    db_quote = models.DBQuote(
        client_id=client.id,
        number=number,
        ref=quote.reference or "",
        to_contact=quote.contact,
        email=quote.email or "",
        phone_number=quote.phone_number or "",
        issue_date=quote.issue_date,
        expiry_date=quote.expiry_date,
        total=round(total, 2),
        status=status,
        sent="",
        tax_type=quote.tax_type,
        currency=(quote.currency or "").upper() or (client.currency or ""),
        job_id=resolve_job_id(db, client.id, quote.job_id),
        title=quote.title or "",
        summary=quote.summary or "",
        terms=quote.terms or "",
    )
    db.add(db_quote)
    db.flush()

    for item in quote.line_items:
        db.add(models.DBQuoteLineItem(
            quote_id=db_quote.id,
            name=item.name or "",
            description=item.description,
            qty=item.qty,
            price=item.price,
            disc=item.disc or 0.0,
            account=item.account,
            tax_rate=item.tax_rate,
        ))

    db.commit()
    db.refresh(db_quote)
    log_audit(db, client.id, "quote_created", "quote", db_quote.id, number,
              f"Total: {total:.2f}", request)
    db.commit()
    return quote_to_dict(db_quote, client, db, detail=True)


@router.put("/api/quotes/{number}")
def update_quote(number: str, quote: QuoteCreate, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    q = get_quote_or_404(db, client, number)
    if q.status == "Invoiced":
        raise HTTPException(status_code=400,
                            detail=f"Quote {number} has already been invoiced as {q.invoice_number}")

    validate_line_items(quote.line_items)
    validate_quote_dates(quote.issue_date, quote.expiry_date)
    subtotal, tax, total = compute_invoice_totals(quote.line_items, quote.tax_type)

    q.ref = quote.reference or ""
    q.to_contact = quote.contact
    q.email = quote.email or ""
    q.phone_number = quote.phone_number or ""
    q.issue_date = quote.issue_date
    q.expiry_date = quote.expiry_date
    q.tax_type = quote.tax_type
    q.currency = (quote.currency or "").upper() or q.currency
    q.title = quote.title or ""
    q.summary = quote.summary or ""
    q.terms = quote.terms or ""
    q.total = round(total, 2)
    if quote.status in QUOTE_STATUSES:
        q.status = quote.status

    db.query(models.DBQuoteLineItem).filter(models.DBQuoteLineItem.quote_id == q.id).delete()
    for item in quote.line_items:
        db.add(models.DBQuoteLineItem(
            quote_id=q.id,
            name=item.name or "",
            description=item.description,
            qty=item.qty,
            price=item.price,
            disc=item.disc or 0.0,
            account=item.account,
            tax_rate=item.tax_rate,
        ))

    log_audit(db, client.id, "quote_updated", "quote", q.id, q.number,
              f"Total: {total:.2f}", request)
    db.commit()
    db.refresh(q)
    return quote_to_dict(q, client, db, detail=True)


@router.delete("/api/quotes/{number}")
def delete_quote(number: str, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    q = get_quote_or_404(db, client, number)
    if q.status == "Invoiced":
        raise HTTPException(status_code=400,
                            detail=f"Quote {number} has been invoiced as {q.invoice_number} and cannot be deleted")
    db.query(models.DBQuoteLineItem).filter(models.DBQuoteLineItem.quote_id == q.id).delete()
    log_audit(db, client.id, "quote_deleted", "quote", q.id, q.number,
              f"Contact: {q.to_contact}", request)
    db.delete(q)
    db.commit()
    return {"message": "Quote deleted successfully"}


@router.post("/api/quotes/{number}/status")
def set_quote_status(number: str, body: QuoteDecision, request: Request, db: Session = Depends(get_db)):
    """Record the customer's answer."""
    client = get_client_user(request, db)
    q = get_quote_or_404(db, client, number)
    wanted = (body.status or "").strip().title()
    if wanted not in ("Accepted", "Declined", "Sent", "Draft"):
        raise HTTPException(status_code=400,
                            detail="Status must be one of: Draft, Sent, Accepted, Declined")
    if q.status == "Invoiced":
        raise HTTPException(status_code=400,
                            detail=f"Quote {number} has already been invoiced as {q.invoice_number}")
    q.status = wanted
    q.decided_at = (datetime.now().strftime("%Y-%m-%d")
                    if wanted in ("Accepted", "Declined") else "")
    log_audit(db, client.id, "quote_status_changed", "quote", q.id, q.number, wanted, request)
    db.commit()
    db.refresh(q)
    return quote_to_dict(q, client, db, detail=True)


@router.post("/api/quotes/{number}/convert")
def convert_quote_to_invoice(number: str, request: Request,
                             body: Optional[QuoteConvert] = None,
                             db: Session = Depends(get_db)):
    """Turn an accepted quote into an invoice, carrying the lines across.

    The quote is kept and marked Invoiced rather than replaced - it is the
    record of what was agreed, and the link runs both ways.
    """
    client = get_client_user(request, db)
    q = get_quote_or_404(db, client, number)
    if body is None:
        body = QuoteConvert()
    if q.status == "Invoiced":
        raise HTTPException(status_code=409,
                            detail=f"Quote {number} was already invoiced as {q.invoice_number}")
    if q.status == "Declined":
        raise HTTPException(status_code=400, detail="A declined quote cannot be invoiced")
    if not q.line_items:
        raise HTTPException(status_code=400, detail="Quote has no line items")

    issue_date = body.issue_date or datetime.now().strftime("%Y-%m-%d")
    if body.due_date:
        due_date = body.due_date
    else:
        base = _parse_date(issue_date) or datetime.now().date()
        due_date = (base + timedelta(days=14)).strftime("%Y-%m-%d")
    validate_invoice_dates(issue_date, due_date)

    subtotal, tax, total = compute_invoice_totals(q.line_items, q.tax_type)
    inv_number = next_sequence_number(db, models.DBInvoice, client.id, invoice_prefix_for(db, client.id))

    invoice = models.DBInvoice(
        client_id=client.id,
        number=inv_number,
        ref=q.ref or q.number,
        to_contact=q.to_contact,
        email=q.email or "",
        phone_number=q.phone_number or "",
        issue_date=issue_date,
        due_date=due_date,
        paid=0.00,
        due=round(total, 2),
        status="Draft",
        sent="",
        tax_type=q.tax_type,
        currency=q.currency or (client.currency or ""),
        bank_details="",
        # The job follows the money. A quote won on Fairview becomes revenue on
        # Fairview, without anybody re-tagging it by hand.
        job_id=q.job_id,
    )
    db.add(invoice)
    db.flush()

    for li in q.line_items:
        db.add(models.DBLineItem(
            invoice_id=invoice.id,
            name=li.name or "",
            description=li.description,
            qty=li.qty,
            price=li.price,
            disc=li.disc or 0.0,
            account=li.account,
            tax_rate=li.tax_rate,
        ))

    q.status = "Invoiced"
    q.invoice_number = inv_number
    log_audit(db, client.id, "quote_converted", "quote", q.id, q.number,
              f"Invoice {inv_number}", request)
    db.commit()
    return {"message": "Quote converted to invoice",
            "invoice_number": inv_number, "quote_number": q.number}


@router.post("/api/quotes/{number}/send")
def send_quote_email(number: str, background_tasks: BackgroundTasks, request: Request,
                     payload: Optional[SendQuoteEmail] = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if payload is None:
        payload = SendQuoteEmail()
    q = get_quote_or_404(db, client, number)
    if not q.email:
        raise HTTPException(status_code=400, detail="Quote has no email address associated with it")
    if not validate_email_address(q.email):
        raise HTTPException(status_code=400, detail=f"Invalid email address: {q.email}")

    from_email = default_from_email()
    if not from_email:
        raise HTTPException(status_code=400, detail="No sender email configured.")

    settings_rows = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == q.client_id).all()
    settings_map = {s.key: s.value for s in settings_rows}
    q_client = db.query(models.DBClient).filter(
        models.DBClient.id == q.client_id).first() if q.client_id else None
    company_name = (settings_map.get("company_name", "")
                    or (q_client.company_name if q_client else "") or "Accounting Platform")
    company_email = settings_map.get("email", "") or (q_client.email if q_client else "")
    company_phone = settings_map.get("phone_number", "") or (q_client.phone_number if q_client else "")
    company_address = settings_map.get("company_address", "") or (q_client.address if q_client else "")

    cur = (q.currency or settings_map.get("currency")
           or (q_client.currency if q_client else "") or DEFAULT_CURRENCY).upper()
    cur_symbol = currency_symbol(cur)

    logo_data = payload.logo_data or ""
    if not logo_data and q_client and q_client.logo_url:
        logo_data = q_client.logo_url
    logo_html = (f'<div style="margin-bottom:24px;"><img src="{esc(logo_data)}" '
                 f'style="max-height:48px;max-width:200px;"></div>') if logo_data else ""

    subtotal, tax_total, total = compute_invoice_totals(q.line_items, q.tax_type)

    rows = ""
    for li in q.line_items:
        amount = line_net_amount(li.qty, li.price, li.disc)
        disc_val = li.disc or 0
        rows += f"""
            <div style="padding:16px 20px;border-bottom:1px solid #f1f5f9;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
                <div style="font-size:15px;font-weight:700;color:#1e293b;">{esc(li.name) or 'Item'}</div>
                <div style="font-size:16px;font-weight:800;color:#0f172a;">{cur_symbol}{amount:.2f}</div>
              </div>
              {f'<div style="font-size:13px;color:#64748b;margin-bottom:8px;word-wrap:break-word;">{esc(li.description)}</div>' if li.description else ''}
              <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;">
                <span style="font-size:12px;color:#94a3b8;">Qty: <strong style="color:#475569;">{li.qty:g}</strong></span>
                <span style="font-size:12px;color:#94a3b8;">Price: <strong style="color:#475569;">{cur_symbol}{li.price:.2f}</strong></span>
                {f'<span style="font-size:12px;color:#94a3b8;">Discount: {disc_val:g}%</span>' if disc_val > 0 else ''}
              </div>
            </div>"""

    subject = f"Quote {q.number} from {company_name}"

    body = f"""Hello {q.to_contact},

Please find our quote {q.number} from {company_name} below.

Quote Number: {q.number}
Issue Date: {q.issue_date}
Valid Until: {q.expiry_date}
"""
    if q.title:
        body += f"For: {q.title}\n"
    body += "\nItems:\n"
    for li in q.line_items:
        item_label = f"{li.name} - {li.description}" if li.name else li.description
        disc_text = f" (Disc: {li.disc}%)" if li.disc else ""
        body += f"  - {item_label} x{li.qty:g} @ {cur_symbol}{li.price:.2f}{disc_text}\n"
    body += f"""
Total: {cur_symbol}{total:.2f}

This quote is valid until {q.expiry_date}. Reply to this email to accept it or
ask us anything about it.

Best regards,
{company_name}
{company_address or ''}
{company_email or ''}
{company_phone or ''}

Powered by Aniprotech"""

    html_body = f"""
    <!DOCTYPE html>
    <html>
      <body style="font-family: Arial, Helvetica, sans-serif; color:#1e293b; line-height:1.6; margin:0; padding:0; background-color:#f1f5f9;">
        <div style="max-width:600px; margin:0 auto; padding:40px 20px;">
          <div style="background:#ffffff; border-radius:12px; overflow:hidden;">
            <div style="background-color:#0f172a; padding:40px; text-align:center;">
              {logo_html}
              <div style="font-size:13px;letter-spacing:2px;text-transform:uppercase;color:#94a3b8;">Quote</div>
              <div style="font-size:30px;font-weight:800;color:#ffffff;margin-top:6px;">{esc(q.number)}</div>
              {f'<div style="font-size:15px;color:#cbd5e1;margin-top:8px;">{esc(q.title)}</div>' if q.title else ''}
            </div>
            <div style="padding:32px 28px;">
              <p style="margin:0 0 18px;font-size:15px;">Hello {esc(q.to_contact)},</p>
              <p style="margin:0 0 24px;font-size:15px;color:#475569;">
                {esc(q.summary) if q.summary else f'Thank you for your interest. Here is our quote from {esc(company_name)}.'}
              </p>

              <div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap;">
                <div style="flex:1;min-width:150px;background:#f8fafc;border-radius:10px;padding:14px 16px;">
                  <div style="font-size:11px;text-transform:uppercase;color:#94a3b8;font-weight:700;">Issued</div>
                  <div style="font-size:15px;font-weight:700;color:#0f172a;">{esc(q.issue_date)}</div>
                </div>
                <div style="flex:1;min-width:150px;background:#fff7ed;border-radius:10px;padding:14px 16px;">
                  <div style="font-size:11px;text-transform:uppercase;color:#c2823a;font-weight:700;">Valid until</div>
                  <div style="font-size:15px;font-weight:700;color:#9a3412;">{esc(q.expiry_date)}</div>
                </div>
              </div>

              <div style="border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;margin-bottom:24px;">
                <div style="background-color:#f8fafc;padding:10px 20px;border-bottom:2px solid #e2e8f0;display:flex;justify-content:space-between;">
                  <span style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;">Item</span>
                  <span style="font-size:11px;font-weight:700;text-transform:uppercase;color:#64748b;">Amount</span>
                </div>
                {rows}
              </div>

              <div style="background:#0f172a;border-radius:10px;padding:20px 24px;margin-bottom:24px;">
                <div style="display:flex;justify-content:space-between;color:#94a3b8;font-size:13px;margin-bottom:6px;">
                  <span>Subtotal</span><span>{cur_symbol}{subtotal:.2f}</span>
                </div>
                <div style="display:flex;justify-content:space-between;color:#94a3b8;font-size:13px;margin-bottom:10px;">
                  <span>Tax</span><span>{cur_symbol}{tax_total:.2f}</span>
                </div>
                <div style="display:flex;justify-content:space-between;color:#ffffff;font-size:20px;font-weight:800;border-top:1px solid #334155;padding-top:12px;">
                  <span>Total</span><span>{cur_symbol}{total:.2f}</span>
                </div>
              </div>

              {f'<div style="border-left:3px solid #e2e8f0;padding:4px 0 4px 14px;color:#64748b;font-size:13px;margin-bottom:24px;white-space:pre-wrap;">{esc(q.terms)}</div>' if q.terms else ''}

              <p style="margin:0;font-size:14px;color:#475569;">
                Happy with this? Just reply to this email to accept, and we will raise the invoice.
              </p>
            </div>
            <div style="background:#f8fafc;padding:22px 28px;text-align:center;border-top:1px solid #e2e8f0;">
              <div style="font-size:14px;font-weight:700;color:#0f172a;">{esc(company_name)}</div>
              <div style="font-size:12px;color:#64748b;margin-top:4px;">
                {esc(company_address or '')}{' &middot; ' if company_address and company_email else ''}{esc(company_email or '')}{' &middot; ' if company_phone else ''}{esc(company_phone or '')}
              </div>
              <div style="font-size:11px;color:#94a3b8;margin-top:12px;">Powered by Aniprotech</div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    pdf_b64 = payload.pdf_data if payload.pdf_data else None
    pdf_filename = f"{q.number}.pdf" if pdf_b64 else "quote.pdf"

    # Charged before the send is queued, so a refused charge cannot still
    # deliver the email.
    require_credit(db, client.id, "quote_send", 1, q.number)

    background_tasks.add_task(send_email_background, q.email, subject, body,
                              f"{company_name} <{from_email}>", html_body, pdf_b64,
                              pdf_filename, logo_data, client_id=client.id)

    # Re-sending must not walk an answered quote back to merely Sent.
    if q.status in ("Draft", "Sent"):
        q.status = "Sent"
    q.sent = datetime.now().strftime("%Y-%m-%d")
    log_audit(db, client.id, "quote_sent", "quote", q.id, q.number, f"Sent to {q.email}", request)
    db.commit()
    return {"message": "Email sending initiated via Gmail API",
            "status": q.status, "sent_date": q.sent}


@router.get("/api/estimates")
def list_estimates(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rows = [estimate_dict(db, e) for e in db.query(models.DBEstimate).filter(
        models.DBEstimate.client_id == client.id).order_by(
            models.DBEstimate.id.desc()).limit(300).all()]
    decided = [r for r in rows if r["status"] in ("WON", "LOST")]
    won = [r for r in rows if r["status"] == "WON"]
    return {
        "estimates": rows,
        "summary": {
            "open": len([r for r in rows if r["status"] in ("DRAFT", "SUBMITTED")]),
            "out_for_decision": money(sum(r["quoted_total"] for r in rows
                                          if r["status"] == "SUBMITTED")),
            "won_value": money(sum(r["quoted_total"] for r in won)),
            # Strike rate by count, which is what an estimator is judged on.
            "strike_rate": (round(len(won) / len(decided) * 100, 1) if decided else 0.0),
        },
    }


@router.post("/api/estimates")
def create_estimate(body: EstimateIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    if not (body.title or "").strip():
        raise HTTPException(400, "Give the tender a name.")
    est = models.DBEstimate(
        client_id=client.id, job_id=owned_or_404(db, models.DBJob, client.id, body.job_id, "Project"),
        number=next_sequence_number(db, models.DBEstimate, client.id, "EST-"),
        title=body.title.strip(), customer_name=(body.customer_name or "").strip(),
        tender_reference=(body.tender_reference or "").strip(), due_on=(body.due_on or ""),
        status="DRAFT", overhead_percent=money(body.overhead_percent or 0),
        profit_percent=money(body.profit_percent or 0),
        notes=(body.notes or "").strip(), prepared_by_name=actor_name)
    db.add(est)
    db.commit()
    db.refresh(est)
    return {"ok": True, "estimate": estimate_dict(db, est, detail=True),
            "message": "%s opened." % est.number}


@router.get("/api/estimates/{est_id}")
def get_estimate(est_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return estimate_dict(db, estimate_or_404(db, client.id, est_id), detail=True)


@router.put("/api/estimates/{est_id}")
def update_estimate(est_id: int, body: EstimateIn, request: Request,
                    db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    est = estimate_or_404(db, client.id, est_id)
    if (est.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "A submitted tender is the price somebody was given. "
                                 "Reopen it to change it.")
    est.title = (body.title or est.title).strip()
    est.customer_name = (body.customer_name or "").strip()
    est.tender_reference = (body.tender_reference or "").strip()
    est.due_on = body.due_on or ""
    if body.job_id is not None:
        est.job_id = owned_or_404(db, models.DBJob, client.id, body.job_id, "Project")
    if body.overhead_percent is not None:
        est.overhead_percent = money(body.overhead_percent)
    if body.profit_percent is not None:
        est.profit_percent = money(body.profit_percent)
    est.notes = (body.notes or "").strip()
    recost_estimate(db, est)
    db.commit()
    db.refresh(est)
    return {"ok": True, "estimate": estimate_dict(db, est, detail=True)}


@router.post("/api/estimates/{est_id}/items")
def add_estimate_item(est_id: int, body: EstimateItemIn, request: Request,
                      db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    est = estimate_or_404(db, client.id, est_id)
    if (est.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Reopen the tender to change its items.")
    if not (body.description or "").strip():
        raise HTTPException(400, "Describe the item.")
    n = db.query(models.DBEstimateItem).filter(
        models.DBEstimateItem.estimate_id == est.id).count()
    item = models.DBEstimateItem(
        estimate_id=est.id, item_no=(body.item_no or str(n + 1)).strip(),
        fg_code=(body.fg_code or "").strip().upper(),
        description=body.description.strip(), uom=standard_unit(body.uom),
        quantity=money(body.quantity), cost_rate=unit_rate(body.cost_rate or 0),
        overhead_percent=body.overhead_percent, profit_percent=body.profit_percent,
        display_order=n)
    db.add(item)
    db.flush()
    recost_estimate(db, est)
    db.commit()
    return {"ok": True, "estimate": estimate_dict(db, est, detail=True)}


@router.put("/api/estimates/{est_id}/items/{item_id}")
def update_estimate_item(est_id: int, item_id: int, body: EstimateItemIn,
                         request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    est = estimate_or_404(db, client.id, est_id)
    if (est.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Reopen the tender to change its items.")
    item = db.query(models.DBEstimateItem).filter(
        models.DBEstimateItem.id == item_id,
        models.DBEstimateItem.estimate_id == est.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    item.item_no = (body.item_no or item.item_no or "").strip()
    item.fg_code = (body.fg_code or "").strip().upper()
    item.description = (body.description or item.description).strip()
    item.uom = standard_unit(body.uom)
    item.quantity = money(body.quantity)
    # A typed cost rate only sticks if there is no analysis - the analysis
    # is the truth when it exists.
    has_analysis = db.query(models.DBRateAnalysis).filter(
        models.DBRateAnalysis.estimate_item_id == item.id).count() > 0
    if body.cost_rate is not None and not has_analysis:
        item.cost_rate = unit_rate(body.cost_rate)
    item.overhead_percent = body.overhead_percent
    item.profit_percent = body.profit_percent
    recost_estimate(db, est)
    db.commit()
    return {"ok": True, "estimate": estimate_dict(db, est, detail=True)}


@router.delete("/api/estimates/{est_id}/items/{item_id}")
def delete_estimate_item(est_id: int, item_id: int, request: Request,
                         db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    est = estimate_or_404(db, client.id, est_id)
    if (est.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Reopen the tender to change its items.")
    db.query(models.DBRateAnalysis).filter(
        models.DBRateAnalysis.estimate_item_id == item_id).delete()
    db.query(models.DBEstimateItem).filter(
        models.DBEstimateItem.id == item_id,
        models.DBEstimateItem.estimate_id == est.id).delete()
    recost_estimate(db, est)
    db.commit()
    return {"ok": True, "estimate": estimate_dict(db, est, detail=True)}


@router.put("/api/estimates/{est_id}/items/{item_id}/analysis")
def set_rate_analysis(est_id: int, item_id: int, body: dict, request: Request,
                      db: Session = Depends(get_db)):
    """Replace the build-up for one item. The whole list, every time - a
    rate analysis is read as one thing and edited as one thing."""
    client, _, _ = wo_actor(request, db, "billing.manage")
    est = estimate_or_404(db, client.id, est_id)
    if (est.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Reopen the tender to change its rates.")
    item = db.query(models.DBEstimateItem).filter(
        models.DBEstimateItem.id == item_id,
        models.DBEstimateItem.estimate_id == est.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    db.query(models.DBRateAnalysis).filter(
        models.DBRateAnalysis.estimate_item_id == item.id).delete()
    for i, raw in enumerate((body.get("lines") or [])[:60]):
        l = RateLineIn(**raw)
        if not (l.description or "").strip() or not l.quantity_per_unit:
            continue
        db.add(models.DBRateAnalysis(
            estimate_item_id=item.id,
            kind=(l.kind or "MATERIAL").upper() if (l.kind or "").upper() in RATE_KINDS else "OTHER",
            item_code=(l.item_code or "").strip().upper(),
            description=l.description.strip(), uom=(l.uom or "").strip(),
            quantity_per_unit=l.quantity_per_unit, rate=unit_rate(l.rate),
            wastage_percent=money(l.wastage_percent or 0), display_order=i))
    db.flush()
    recost_estimate(db, est)
    db.commit()
    return {"ok": True, "estimate": estimate_dict(db, est, detail=True)}


@router.post("/api/estimates/{est_id}/{action}")
def act_on_estimate(est_id: int, action: str, request: Request, body: dict = None,
                    db: Session = Depends(get_db)):
    """Submit, win, lose, withdraw, reopen.

    Winning is the handoff the whole module exists for: the priced schedule
    becomes a work order, line for line, and the estimate remembers which
    one so the two can be laid side by side when the job is over.
    """
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    est = estimate_or_404(db, client.id, est_id)
    move = (action or "").upper()
    allowed = EST_TRANSITIONS.get(est.status or "DRAFT", {})
    if move not in allowed:
        raise HTTPException(409, "A %s tender cannot be %s."
                                 % ((est.status or "draft").lower(), move.lower()))
    body = body or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    made = None

    if move == "SUBMIT":
        recost_estimate(db, est)
        if not est.quoted_total:
            raise HTTPException(409, "There is nothing priced on this tender.")
    elif move == "WIN":
        if not est.job_id:
            job = models.DBJob(
                client_id=client.id,
                number=next_sequence_number(db, models.DBJob, client.id, "JOB-"),
                name=est.title or "Won tender", customer_name=est.customer_name or "",
                status="won", quoted_value=est.quoted_total or 0,
                budget=est.cost_total or 0, reference=est.tender_reference or "")
            db.add(job)
            db.flush()
            est.job_id = job.id
        made = work_order_from_estimate(db, client, est, request)
        est.work_order_id = made.id
        est.decided_at = now
    elif move == "LOSE":
        est.lost_reason = (body.get("reason") or "").strip()
        est.decided_at = now
    elif move == "REOPEN":
        est.decided_at = ""
        est.lost_reason = ""

    was, est.status = est.status, allowed[move]
    est.updated_at = now
    log_audit(db, client.id, "estimate_%s" % move.lower(), "estimate", est.id,
              est.number or "", "%s -> %s" % (was, est.status), request)
    db.commit()
    db.refresh(est)
    out = {"ok": True, "estimate": estimate_dict(db, est, detail=True),
           "message": "%s is now %s." % (est.number, est.status.lower())}
    if made is not None:
        out["work_order"] = work_order_to_dict(db, made)
        out["message"] = ("%s won. %s drawn up from it, line for line - place it "
                          "when the client's order arrives." % (est.number, made.number))
    return out


@router.get("/api/estimates/{est_id}/export.xlsx")
def export_estimate(est_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    e = estimate_dict(db, estimate_or_404(db, client.id, est_id), detail=True)
    preamble = [("TENDER ESTIMATE", client.company_name or ""),
                ("No", e["number"], "Status", e["status"]),
                ("Title", e["title"]), ("Client", e["customer_name"]),
                ("Reference", e["tender_reference"], "Due", e["due_on"]),
                ("Overhead", "%s%%" % e["overhead_percent"], "Profit", "%s%%" % e["profit_percent"]),
                ()]
    headers = ("Item", "Description", "UOM", "Qty", "Cost rate", "Quoted rate",
               "Cost", "Quoted")
    rows = [(i["item_no"], i["description"], i["uom"], i["quantity"], i["cost_rate"],
             i["quoted_rate"], i["cost_amount"], i["quoted_amount"]) for i in e["items"]]
    closing = [(), ("Cost", "", "", "", "", "", e["cost_total"]),
               ("Quoted", "", "", "", "", "", "", e["quoted_total"]),
               ("Margin", "", "", "", "", "", "", e["margin_amount"],
                "%s%%" % e["margin_percent"])]
    return sheet_response(headers, rows, "estimate_%s.xlsx" % e["number"],
                          preamble=preamble, closing=closing)


@router.get("/api/leads")
def list_leads(request: Request, status: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBLead).filter(models.DBLead.client_id == client.id)
    rows = [lead_dict(db, l) for l in q.order_by(models.DBLead.id.desc()).all()]
    db.commit()           # outcomes synced from estimates are kept
    if status:
        rows = [r for r in rows if r["status"] == status.upper()]
    decided = [r for r in rows if r["status"] in ("WON", "LOST")]
    won = [r for r in decided if r["status"] == "WON"]
    live = [r for r in rows if r["status"] in LEAD_OPEN]
    return {"leads": rows, "statuses": list(LEAD_STATUSES), "sources": list(LEAD_SOURCES),
            "emd_modes": list(EMD_MODES), "summary": {
                "live": len(live),
                "pipeline_value": money(sum(r["estimated_value"] for r in live)),
                "due_this_week": len([r for r in live if r["days_to_bid"] is not None
                                      and 0 <= r["days_to_bid"] <= 7]),
                "hit_rate": round(len(won) / len(decided) * 100, 1) if decided else 0.0,
                "won_value": money(sum(r["our_price"] or r["estimated_value"] for r in won)),
                "emd_out": money(sum(r["emd_amount"] for r in rows if r["emd_outstanding"])),
                "emd_out_count": len([r for r in rows if r["emd_outstanding"]])}}


@router.post("/api/leads")
def create_lead(body: LeadIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    l = models.DBLead(client_id=client.id, number=next_lead_number(db, client.id), status="NEW")
    _apply_lead(l, body)
    if not l.owner_name:
        l.owner_name = actor_name
    db.add(l)
    db.flush()
    _log_lead(db, client.id, l, "Status", "Tender entered.", actor_name)
    db.commit()
    return {"ok": True, "lead": lead_dict(db, l), "message": "%s entered." % l.number}


@router.put("/api/leads/{lead_id}")
def update_lead(lead_id: int, body: LeadIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "billing.manage")
    l = lead_or_404(db, client.id, lead_id)
    _apply_lead(l, body)
    db.commit()
    return {"ok": True, "lead": lead_dict(db, l)}


@router.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    l = lead_or_404(db, client.id, lead_id)
    d = lead_dict(db, l)
    d["activities"] = [{"id": a.id, "kind": a.kind, "note": a.note or "", "next_action": a.next_action or "",
                        "next_on": a.next_on or "", "by": a.by_name or "", "at": a.created_at}
                       for a in db.query(models.DBLeadActivity).filter(
                           models.DBLeadActivity.lead_id == l.id).order_by(
                               models.DBLeadActivity.id.desc()).all()]
    db.commit()
    return d


@router.post("/api/leads/{lead_id}/status")
def move_lead(lead_id: int, body: LeadMoveIn, request: Request, db: Session = Depends(get_db)):
    """Along the pipeline. A lost tender says who won it and at what, because
    that is the only way next year's rates learn anything."""
    client, _, actor_name = wo_actor(request, db, "billing.manage")
    l = lead_or_404(db, client.id, lead_id)
    to = (body.status or "").upper()
    if to not in LEAD_STATUSES:
        raise HTTPException(400, "Status is one of: " + ", ".join(LEAD_STATUSES))
    if l.estimate_id and to in ("WON", "LOST", "SUBMITTED"):
        raise HTTPException(409, "This tender's outcome follows its estimate. Decide it on the estimate.")
    if to == "LOST":
        if not (body.lost_reason or "").strip():
            raise HTTPException(400, "Why was it lost? Price, eligibility, time - the next bid needs to know.")
        l.lost_reason = body.lost_reason.strip()
        l.winning_bidder = (body.winning_bidder or "").strip()
        l.winning_price = money(body.winning_price or 0)
    if to == "DROPPED" and not (body.note or "").strip():
        raise HTTPException(400, "Say why it was dropped.")
    was, l.status = l.status, to
    l.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log_lead(db, client.id, l, "Status", "%s -> %s. %s" % (was, to, (body.note or body.lost_reason or "").strip()),
              actor_name)
    db.commit()
    return {"ok": True, "lead": lead_dict(db, l), "message": "%s %s." % (l.number, to.lower())}


@router.post("/api/leads/{lead_id}/activities")
def add_lead_activity(lead_id: int, body: LeadActivityIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "billing.manage")
    l = lead_or_404(db, client.id, lead_id)
    if not (body.note or "").strip():
        raise HTTPException(400, "What happened?")
    kind = body.kind if body.kind in ("Call", "Visit", "Meeting", "Note", "Email") else "Note"
    _log_lead(db, client.id, l, kind, body.note.strip(), actor_name,
              (body.next_action or "").strip(), (body.next_on or "").strip())
    db.commit()
    return {"ok": True, "message": "Noted on %s." % l.number}


@router.post("/api/leads/{lead_id}/estimate")
def estimate_lead(lead_id: int, request: Request, db: Session = Depends(get_db)):
    """Price it: an estimate opened from the tender, carrying its name, its
    client, its reference and its bid date."""
    client, actor_id, actor_name = wo_actor(request, db, "billing.manage")
    l = lead_or_404(db, client.id, lead_id)
    if l.estimate_id:
        raise HTTPException(409, "%s already has an estimate." % l.number)
    if l.status in ("WON", "LOST", "DROPPED"):
        raise HTTPException(409, "%s is %s." % (l.number, l.status.lower()))
    est = models.DBEstimate(
        client_id=client.id, number=next_sequence_number(db, models.DBEstimate, client.id, "EST-"),
        title=l.title, customer_name=l.customer_name or "", tender_reference=l.tender_reference or "",
        due_on=l.bid_due_on or "", status="DRAFT", overhead_percent=0, profit_percent=0,
        notes="From tender %s. %s" % (l.number, l.notes or ""), prepared_by_name=actor_name)
    db.add(est)
    db.flush()
    l.estimate_id, l.status = est.id, "ESTIMATING"
    _log_lead(db, client.id, l, "Status", "Estimate %s opened." % est.number, actor_name)
    db.commit()
    return {"ok": True, "estimate_id": est.id, "lead": lead_dict(db, l),
            "message": "%s opened for %s. Build the rates there." % (est.number, l.number)}


@router.post("/api/leads/{lead_id}/emd-returned")
def emd_returned(lead_id: int, body: EmdReturnIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "billing.manage")
    l = lead_or_404(db, client.id, lead_id)
    if not l.emd_amount or not l.emd_paid_on:
        raise HTTPException(409, "No EMD was paid on %s." % l.number)
    if l.emd_returned_on:
        raise HTTPException(409, "The EMD on %s came back on %s." % (l.number, l.emd_returned_on))
    l.emd_returned_on = (body.returned_on or datetime.now().strftime("%Y-%m-%d"))[:10]
    _log_lead(db, client.id, l, "Status", "EMD of %s returned. %s" % (inr(l.emd_amount), body.note or ""), actor_name)
    db.commit()
    return {"ok": True, "message": "EMD on %s marked returned." % l.number}


@router.get("/api/leads-emd")
def emd_register(request: Request, db: Session = Depends(get_db)):
    """Every earnest money deposit paid and not yet back - the oldest first,
    because an EMD on a tender lost a year ago is money forgotten."""
    client = require_erp_read(request, db)
    rows = []
    for l in db.query(models.DBLead).filter(models.DBLead.client_id == client.id,
                                            models.DBLead.emd_amount > 0).all():
        d = lead_dict(db, l)
        if not d["emd_paid_on"]:
            continue
        held = _days_until(d["emd_paid_on"])
        d["days_held"] = -held if held is not None else None
        rows.append(d)
    db.commit()
    out = [r for r in rows if r["emd_outstanding"]]
    out.sort(key=lambda r: -(r["days_held"] or 0))
    return {"emds": out, "returned": [r for r in rows if not r["emd_outstanding"]],
            "summary": {"out": money(sum(r["emd_amount"] for r in out)), "count": len(out),
                        "on_decided_tenders": money(sum(r["emd_amount"] for r in out
                                                        if r["status"] in ("WON", "LOST", "DROPPED")))}}
