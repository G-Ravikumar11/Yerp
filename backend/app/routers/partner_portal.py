"""The partner portal endpoints."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import PORTAL_INVOICE_TYPES
from app.core.audit import log_audit, log_login
from app.core.auth import end_every_session
from app.core.currency import inr, money
from app.core.dates import _parse_date, days_after
from app.core.files import store_file
from app.core.notifications import notify
from app.core.security import (
    _portal_token_hash,
    hash_password,
    rate_limiter,
    upgrade_password_hash,
    validate_password_strength,
    verify_password,
)
from app.core.sheets import sheet_response
from app.documents.forms import (
    form_pdf_response,
    po_form_spec,
    statement_form_spec,
    sub_bill_form_spec,
    wo_form_spec,
)
from app.schemas.partner_portal import PortalLoginIn, PortalPasswordIn
from app.services.crm import norm_name
from app.services.partner_portal import (
    _portal_bills,
    _portal_ledger,
    _portal_orders,
    _portal_payments,
    _portal_signed_in,
    _portal_statement,
    get_portal_user,
)
from app.services.subcontract_billing import portal_party, retention_positions


router = APIRouter()


@router.get("/api/portal/invite")
def portal_invite_check(token: str = "", db: Session = Depends(get_db)):
    """Who the link is for, so the page can greet them before they choose a
    password - and say plainly when it has run out."""
    u = db.query(models.DBPortalUser).filter(
        models.DBPortalUser.invite_token_hash == _portal_token_hash(token)).first() if token else None
    if not u or not u.is_active or (u.invite_expires or "") < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        raise HTTPException(410, "This link has run out or been replaced. Ask the office for a new one.")
    client = db.query(models.DBClient).filter(models.DBClient.id == u.client_id).first()
    _, party = portal_party(db, u.client_id, u.party_type, u.party_id)
    return {"email": u.email, "name": u.name or "", "party": party,
            "company": (client.company_name or "") if client else ""}


@router.post("/api/portal/accept-invite")
def portal_accept_invite(body: PortalPasswordIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"portal_invite:{ip}", max_requests=10, window=300):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    portal_invite_check(body.token, db)
    u = db.query(models.DBPortalUser).filter(
        models.DBPortalUser.invite_token_hash == _portal_token_hash(body.token)).first()
    validate_password_strength(body.password)
    u.password_hash = hash_password(body.password)
    u.invite_token_hash, u.invite_expires = "", ""
    _portal_signed_in(request, db, u)
    return {"ok": True}


@router.post("/api/portal/login")
def portal_login(body: PortalLoginIn, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"portal_login:{ip}", max_requests=10, window=60):
        raise HTTPException(429, "Too many attempts. Try again in a minute.")
    email = (body.email or "").strip().lower()
    u = db.query(models.DBPortalUser).filter(sqlfunc.lower(models.DBPortalUser.email) == email).first()
    if not u or not u.password_hash or not verify_password(body.password, u.password_hash):
        log_login(db, u.client_id if u else None, email, "partner", "password", request, "failed")
        db.commit()
        raise HTTPException(401, "That email and password do not match.")
    upgrade_password_hash(u, "password_hash", body.password)
    if not u.is_active:
        raise HTTPException(403, "Your access has been removed. Ask the office if you need it back.")
    # The company and the party must both still be live before a session exists.
    client = db.query(models.DBClient).filter(models.DBClient.id == u.client_id).first()
    party, _ = portal_party(db, u.client_id, u.party_type, u.party_id)
    if not client or not client.is_active or not party or party.is_active is False:
        raise HTTPException(403, "This login is no longer open. Ask the office.")
    _portal_signed_in(request, db, u)
    return {"ok": True}


@router.post("/api/portal/logout")
def portal_logout(request: Request):
    end_every_session(request)
    return {"ok": True}


@router.get("/api/portal/me")
def portal_me(request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    return {"name": u.name or "", "email": u.email, "party_type": u.party_type, "party": name,
            "company": client.company_name or "", "company_logo": client.logo_url or "",
            "company_phone": client.phone_number or "", "company_email": client.email or ""}


@router.get("/api/portal/summary")
def portal_summary(request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    orders = _portal_orders(db, u, party, name)
    bills = _portal_bills(db, u, party, name)
    payments = _portal_payments(db, u, party, name)
    rows = _portal_ledger(db, u, name)
    balance = money(sum(r["billed"] - r["moved"] for r in rows))
    out = {
        "orders": len([o for o in orders if not o["superseded"]]),
        "order_value": money(sum(o["value"] for o in orders if not o["superseded"])),
        "bills_waiting": len([b for b in bills if b["status"] in ("SUBMITTED", "Draft")]),
        "passed_unpaid": money(sum(b["left"] for b in bills)),
        "paid_total": money(sum(p["amount"] for p in payments)),
        "last_payment": payments[0] if payments else None,
        "balance": balance,
    }
    if u.party_type == "contractor":
        mine = [p for p in retention_positions(db, u.client_id)
                if p["side"] == "contractor" and p.get("contractor_id") == party.id]
        out["retention_held"] = money(sum(p["balance"] for p in mine))
        out["retention"] = [{"order_number": p["order_number"], "held": p["held"], "released": p["released"],
                             "balance": p["balance"], "dlp_ends": p["dlp_ends"]} for p in mine]
    return out


@router.get("/api/portal/orders")
def portal_orders(request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    return {"orders": _portal_orders(db, u, party, name)}


@router.get("/api/portal/orders/{order_id}")
def portal_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    o = next((x for x in _portal_orders(db, u, party, name) if x["id"] == order_id), None)
    if not o:
        raise HTTPException(404, "Order not found")
    if u.party_type == "contractor":
        lines = [{"code": i.item_code or i.activity_no or "", "description": i.item_description or "",
                  "uom": i.uom or "", "qty": i.quantity or 0, "rate": money(i.unit_rate),
                  "amount": money(i.total_amount)}
                 for i in db.query(models.DBSubcontractItem).filter(
                     models.DBSubcontractItem.order_id == order_id).order_by(models.DBSubcontractItem.id).all()]
    else:
        lines = [{"code": i.item_code or "", "description": i.description or "", "uom": i.uom or "",
                  "qty": i.qty or 0, "rate": money(i.price), "amount": money((i.qty or 0) * (i.price or 0))}
                 for i in db.query(models.DBPurchaseOrderLineItem).filter(
                     models.DBPurchaseOrderLineItem.order_id == order_id).order_by(
                         models.DBPurchaseOrderLineItem.id).all()]
    return {"order": o, "lines": lines}


@router.get("/api/portal/bills")
def portal_bills(request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    return {"bills": _portal_bills(db, u, party, name)}


@router.post("/api/portal/bills/{bill_id}/accept")
def portal_accept_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """The gang signs the certificate of payment from their own login -
    "Accepted for Sub Contractor" - once it has been sent to them."""
    u, client, party, name = get_portal_user(request, db)
    if u.party_type != "contractor":
        raise HTTPException(404, "Bill not found")
    bill = db.query(models.DBSubBill).filter(models.DBSubBill.id == bill_id, models.DBSubBill.client_id == u.client_id,
                                             models.DBSubBill.contractor_id == party.id,
                                             models.DBSubBill.status.in_(("SUBMITTED", "CERTIFIED", "PAID"))).first()
    if not bill:
        raise HTTPException(404, "Bill not found")
    if bill.accepted_by_name:
        raise HTTPException(409, "%s was already accepted by %s." % (bill.number, bill.accepted_by_name))
    bill.accepted_by_name = ((getattr(u, "name", "") or "").strip() or name or "Sub contractor")[:120]
    bill.accepted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client.id, "sub_bill_accepted", "sub_bill", bill.id, bill.number or "",
              "Accepted from the partner portal by %s" % bill.accepted_by_name, request, user_type="portal",
              user_name=bill.accepted_by_name)
    db.commit()
    return {"ok": True, "message": "%s accepted. Thank you." % bill.number}


@router.get("/api/portal/payments")
def portal_payments(request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    return {"payments": _portal_payments(db, u, party, name)}


@router.get("/api/portal/statement")
def portal_statement(request: Request, date_from: str = "", date_to: str = "",
                     db: Session = Depends(get_db)):
    """Their account with us: each bill, each payment, and the balance -
    positive is what we owe them."""
    u, client, party, name = get_portal_user(request, db)
    return _portal_statement(db, u, name, date_from, date_to)


@router.get("/api/portal/statement.xlsx")
def portal_statement_export(request: Request, date_from: str = "", date_to: str = "",
                            db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    s = _portal_statement(db, u, name, date_from, date_to)
    return sheet_response(
        ("Date", "Entry", "Number", "Against", "Reference", "Billed", "Paid", "Balance"),
        [(r["date"], r["kind"], r["number"], r["against"], r["reference"], r["billed"], r["paid"],
          r["balance"]) for r in s["rows"]],
        "statement.xlsx",
        preamble=[("STATEMENT OF ACCOUNT", name), ("With", client.company_name or ""),
                  ("Period", "%s to %s" % (date_from or "the start", date_to or date.today().isoformat())),
                  ("Opening balance", s["opening"]), ()],
        closing=[(), ("Balance due to you" if s["closing"] >= 0 else "Balance due from you",
                      "", "", "", "", "", "", abs(s["closing"]))])


@router.post("/api/portal/invoices")
def portal_send_invoice(request: Request, file: UploadFile = File(...),
                        number: str = Form(...), issue_date: str = Form(""),
                        amount: float = Form(...), tax_amount: float = Form(0),
                        po_number: str = Form(""), note: str = Form(""),
                        db: Session = Depends(get_db)):
    """A supplier sends an invoice in. It lands in Supplier Bills as a draft,
    with the invoice attached, for the office to check against the goods
    received and accept - nothing is payable until somebody here has."""
    u, client, party, name = get_portal_user(request, db)
    if u.party_type != "supplier":
        raise HTTPException(403, "Your bills are drawn from the measurement book on site; the office raises them.")
    number = (number or "").strip()[:60]
    if not number:
        raise HTTPException(400, "Your invoice number.")
    if (amount or 0) <= 0 or (tax_amount or 0) < 0:
        raise HTTPException(400, "The invoice value before tax, and the GST on it.")
    on = (issue_date or date.today().isoformat())[:10]
    if not _parse_date(on):
        raise HTTPException(400, "Invoice date should be YYYY-MM-DD.")
    key = norm_name(name)
    if any(norm_name(b.vendor_name) == key and (b.number or "").strip().lower() == number.lower()
           for b in db.query(models.DBBill).filter(models.DBBill.client_id == u.client_id).all()
           if (b.status or "") != "Cancelled"):
        raise HTTPException(409, "Invoice %s is already with us." % number)
    ctype = (file.content_type or "").lower()
    if ctype not in PORTAL_INVOICE_TYPES:
        raise HTTPException(400, "Send the invoice as a PDF or a photo.")
    data = file.file.read()
    po = None
    if po_number.strip():
        po = next((p for p in db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.client_id == u.client_id,
            models.DBPurchaseOrder.number == po_number.strip()).all()
            if norm_name(p.supplier_name) == key), None)
        if not po:
            raise HTTPException(404, "%s is not one of your orders." % po_number.strip())
    amount, tax = money(amount), money(tax_amount or 0)
    b = models.DBBill(client_id=u.client_id, number=number, vendor_name=name, vendor_email=u.email,
                      issue_date=on, due_date=days_after(on, party.payment_days or 30),
                      amount=amount, tax_amount=tax, total=money(amount + tax), amount_paid=0.0,
                      status="Draft", category="Materials", reference=po.number if po else "",
                      notes=("Sent through the partner portal by %s on %s. %s" % (
                          u.name or u.email, date.today().isoformat(), (note or "").strip()[:300])).strip(),
                      job_id=po.job_id if po else None, purchase_order_id=po.id if po else None)
    db.add(b)
    db.flush()
    store_file(db, u.client_id, file, data, job_id=b.job_id, attached_type="bill", attached_id=b.id,
               kind="document", caption="Invoice %s from %s" % (number, name), by="%s (portal)" % (u.name or u.email))
    log_audit(db, u.client_id, "portal_invoice", "supplier_bill", b.id, number,
              "%s %s" % (name, inr(b.total)), request, user_type="partner", user_name=u.email)
    db.commit()
    notify(db, u.client_id, "portal_invoice", "%s sent invoice %s" % (name, number),
           "%s%s, through the partner portal. Check it and accept it in Supplier Bills." % (
               inr(b.total), (" against " + po.number) if po else ""),
           view="bills-view", ref_type="supplier_bill", ref_id=b.id, severity="action")
    return {"ok": True, "message": "Invoice %s received. The office will check it against the delivery." % number}


@router.get("/api/portal/orders/{order_id}/document.pdf")
def portal_order_pdf(order_id: int, request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    if not any(o["id"] == order_id for o in _portal_orders(db, u, party, name)):
        raise HTTPException(404, "Order not found")
    if u.party_type == "contractor":
        order = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == order_id,
                                                           models.DBSubcontractOrder.client_id == u.client_id).first()
        return form_pdf_response(wo_form_spec(db, client, order), order.wo_number)
    order = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.id == order_id,
                                                    models.DBPurchaseOrder.client_id == u.client_id).first()
    return form_pdf_response(po_form_spec(db, client, order), order.number)


@router.get("/api/portal/bills/{bill_id}/document.pdf")
def portal_bill_pdf(bill_id: int, request: Request, db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    if u.party_type != "contractor":
        raise HTTPException(404, "Your invoices are your own documents.")
    bill = db.query(models.DBSubBill).filter(models.DBSubBill.id == bill_id, models.DBSubBill.client_id == u.client_id,
                                             models.DBSubBill.contractor_id == party.id,
                                             models.DBSubBill.status.in_(("SUBMITTED", "CERTIFIED", "PAID"))).first()
    if not bill:
        raise HTTPException(404, "Bill not found")
    return form_pdf_response(sub_bill_form_spec(db, client, bill), bill.number)


@router.get("/api/portal/statement.pdf")
def portal_statement_pdf(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    u, client, party, name = get_portal_user(request, db)
    s = _portal_statement(db, u, name, date_from, date_to)
    return form_pdf_response(statement_form_spec(client, name, "Sub Contractor" if u.party_type == "contractor"
                                                 else "Supplier", s, date_from, date_to, db=db), "statement")
