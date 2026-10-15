"""Supplier quotes through a link: the buyer asks, the supplier answers on his own phone, no login.

For the buyer (signed in):
    GET    /api/rfqs/{id}/statement                      the comparison, with documents and links
    POST   /api/rfqs/{id}/invites                        a link for one supplier
    DELETE /api/rfqs/{id}/invites/{invite_id}            take a link back
    POST   /api/rfqs/{id}/quotes/{quote_id}/document     keep the supplier's quotation file with his quote

For the supplier (the link's token is the only key):
    GET  /api/vendor-quote/{token}                       what is asked, and his answer so far
    POST /api/vendor-quote/{token}/read                  his quotation file read into rates (AI), nothing saved
    POST /api/vendor-quote/{token}                       his answer: rates, his file, or both

A link shows nothing but this enquiry's items and quantities, and takes nothing but this supplier's answer. It stops
taking answers once the enquiry is awarded or cancelled.
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.ai import config as ai_config
from app.ai import guard, inputs
from app.ai.llm_client import ask_json
from app.ai.quote_reader import ACTION_KEY, SYSTEM, build_prompt, clean
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.notifications import notify
from app.core.security import rate_limiter
from app.db import get_db
from app.services.crm import norm_name
from app.services.procurement import _rfq_lines, rfq_or_404
from app.services.rfq_quotes import (invite_dict, invites_of, keep_document, new_token, save_quote,
                                     statement_for_screen)

router = APIRouter()


class InviteIn(BaseModel):
    supplier_name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --- the buyer ------------------------------------------------------------------------------------------------------

@router.get("/api/rfqs/{rfq_id}/statement")
def rfq_statement_for_screen(rfq_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return statement_for_screen(db, client.id, rfq_or_404(db, client.id, rfq_id))


@router.post("/api/rfqs/{rfq_id}/invites")
def invite_supplier(rfq_id: int, body: InviteIn, request: Request, db: Session = Depends(get_db)):
    """A link for one supplier. Asked again for the same supplier, the link he already has is given back."""
    client, _, actor_name = wo_actor(request, db, "purchase.manage")
    rfq = rfq_or_404(db, client.id, rfq_id)
    if rfq.status != "OPEN":
        raise HTTPException(409, "%s is %s; no more quotes are taken." % (rfq.number, rfq.status.lower()))
    name = (body.supplier_name or "").strip()
    if not name:
        raise HTTPException(400, "Which supplier is the link for?")
    inv = next((i for i in invites_of(db, rfq.id) if norm_name(i.supplier_name) == norm_name(name)), None)
    if inv is None:
        supplier = next((s for s in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client.id).all()
                         if norm_name(s.name) == norm_name(name)), None)
        inv = models.DBRfqInvite(client_id=client.id, rfq_id=rfq.id, token=new_token(), supplier_name=name[:120],
                                 phone=((body.phone or "").strip() or (supplier.phone if supplier else "") or "")[:30],
                                 email=((body.email or "").strip() or (supplier.email if supplier else "") or "")[:120],
                                 created_by_name=actor_name)
        db.add(inv)
        log_audit(db, client.id, "rfq_invite", "rfq", rfq.id, rfq.number, name, request)
        db.commit()
        db.refresh(inv)
    return {"invite": invite_dict(inv), "message": "Link ready for %s. Send it by WhatsApp or email." % inv.supplier_name}


@router.delete("/api/rfqs/{rfq_id}/invites/{invite_id}")
def withdraw_invite(rfq_id: int, invite_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "purchase.manage")
    rfq = rfq_or_404(db, client.id, rfq_id)
    inv = db.query(models.DBRfqInvite).filter(models.DBRfqInvite.id == invite_id, models.DBRfqInvite.rfq_id == rfq.id).first()
    if inv is None:
        raise HTTPException(404, "That link is not on this enquiry.")
    db.delete(inv)
    db.commit()
    return {"ok": True, "message": "The link for %s no longer works." % (inv.supplier_name or "the supplier")}


@router.post("/api/rfqs/{rfq_id}/quotes/{quote_id}/document")
def keep_quote_document(rfq_id: int, quote_id: int, request: Request, file: UploadFile = File(...),
                        db: Session = Depends(get_db)):
    """The supplier's quotation file, kept with his quote: whatever form it came in."""
    client, _, actor_name = wo_actor(request, db, "purchase.manage")
    rfq = rfq_or_404(db, client.id, rfq_id)
    q = db.query(models.DBRfqQuote).filter(models.DBRfqQuote.id == quote_id, models.DBRfqQuote.rfq_id == rfq.id).first()
    if q is None:
        raise HTTPException(404, "That quote is not on this enquiry.")
    f = keep_document(db, client.id, rfq, "rfq_quote", q.id, file, file.file.read(), actor_name)
    db.commit()
    return {"ok": True, "document": {"id": f.id, "name": f.name}, "message": "%s's quotation kept with the quote." % q.supplier_name}


@router.get("/api/rfqs/{rfq_id}/quotes/{quote_id}/document-text")
def quote_document_text(rfq_id: int, quote_id: int, request: Request, db: Session = Depends(get_db)):
    """The supplier's quotation as text, to read beside the quote when it is a Word, Excel or other file a browser
    cannot show (a PDF or a photo is shown as it is)."""
    from app.ai import doc_text
    from app.core.files import _file_or_404, file_bytes
    client = require_erp_read(request, db)
    rfq = rfq_or_404(db, client.id, rfq_id)
    doc = db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "rfq_quote",
                                         models.DBFile.attached_id == quote_id).order_by(models.DBFile.id.desc()).first()
    if doc is None or not db.query(models.DBRfqQuote.id).filter(models.DBRfqQuote.id == quote_id, models.DBRfqQuote.rfq_id == rfq.id).first():
        raise HTTPException(404, "There is no quotation file with this quote.")
    f = _file_or_404(db, client.id, doc.id, bytes_too=True)
    data = file_bytes(db, f) or b""
    try:
        kind, text, picture = doc_text.to_text_or_picture(data, f.name or "", f.content_type or "")
    except doc_text.Unreadable as exc:
        raise HTTPException(400, str(exc))
    return {"id": f.id, "name": f.name or "", "kind": kind, "text": text, "shown_as_is": kind in ("pdf", "picture")}


# --- the supplier ---------------------------------------------------------------------------------------------------

def _invite(db, token, request, action, limit):
    ip = request.client.host if request.client else "?"
    if rate_limiter.is_rate_limited("vendor_quote:%s:%s" % (action, ip), max_requests=limit, window=600):
        raise HTTPException(429, "Too many tries. Wait a few minutes and try again.")
    inv = db.query(models.DBRfqInvite).filter(models.DBRfqInvite.token == (token or "")[:80]).first()
    if inv is None:
        raise HTTPException(404, "This link is not valid. Ask the company for a new one.")
    rfq = db.query(models.DBRfq).filter(models.DBRfq.id == inv.rfq_id).first()
    if rfq is None:
        raise HTTPException(404, "This enquiry is no longer open.")
    client = db.query(models.DBClient).filter(models.DBClient.id == inv.client_id).first()
    return inv, rfq, client


def _closed(rfq):
    if rfq.status != "OPEN":
        raise HTTPException(409, "This enquiry is closed (%s). Thank you - no more quotes are being taken." % rfq.status.lower())


@router.get("/api/vendor-quote/{token}")
def vendor_quote_page(token: str, request: Request, db: Session = Depends(get_db)):
    inv, rfq, client = _invite(db, token, request, "view", 120)
    if not inv.opened_at:
        inv.opened_at = _now()
        db.commit()
    job = db.query(models.DBJob).filter(models.DBJob.id == rfq.job_id).first() if rfq.job_id else None
    quote = db.query(models.DBRfqQuote).filter(models.DBRfqQuote.id == inv.quote_id).first() if inv.quote_id else None
    rates = {}
    if quote:
        rates = {l.rfq_line_id: {"rate": l.rate, "tax_percent": l.tax_percent, "remarks": l.remarks or ""}
                 for l in db.query(models.DBRfqQuoteLine).filter(models.DBRfqQuoteLine.quote_id == quote.id).all()}
    return {
        "company": (client.company_name if client else "") or "",
        "supplier_name": inv.supplier_name or "",
        "rfq": {"number": rfq.number or "", "title": rfq.title or "", "project": (job.name if job else "") or "",
                "site": (job.site_address if job else "") or "", "needed_by": rfq.needed_by or "", "notes": rfq.notes or ""},
        "open": rfq.status == "OPEN",
        "lines": [{"rfq_line_id": l.id, "item_code": l.item_code or "", "description": l.description or "", "uom": l.uom or "",
                   "qty": l.qty or 0, **({"rate": rates[l.id]["rate"], "tax_percent": rates[l.id]["tax_percent"],
                                          "remarks": rates[l.id]["remarks"]} if l.id in rates else {})}
                  for l in _rfq_lines(db, rfq.id)],
        "answer": ({"quote_ref": quote.quote_ref or "", "quote_date": quote.quote_date or "", "delivery_days": quote.delivery_days or 0,
                    "payment_terms": quote.payment_terms or "", "freight": quote.freight or 0, "valid_until": quote.valid_until or "",
                    "notes": quote.notes or ""} if quote else None),
        "submitted_at": inv.submitted_at or "",
        "document_sent": bool(inv.document_id) or bool(quote and db.query(models.DBFile.id).filter(
            models.DBFile.attached_type == "rfq_quote", models.DBFile.attached_id == quote.id).first()),
        "can_read": ai_config.enabled() and ai_config.configured(),
        "accept": inputs.ACCEPT,
    }


@router.post("/api/vendor-quote/{token}/read")
def vendor_quote_read(token: str, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """His quotation, read into rates against the enquiry's items. Nothing is saved: he checks the rates and sends them."""
    inv, rfq, client = _invite(db, token, request, "read", 10)
    _closed(rfq)
    lines = _rfq_lines(db, rfq.id)
    attachments, text = inputs.take(file, "", "quotation")
    result = guard.run_feature(db, request, client, ACTION_KEY, "Quote read %s (%s)" % (rfq.number, inv.supplier_name),
                               rfq.number or "", lambda: ask_json(SYSTEM, build_prompt(lines, text), attachments, smart=True, max_tokens=3000))
    if not result.ok:
        return {"available": False, "message": "Your file could not be read automatically. Type the rates below, or just send the file "
                                               "and the company will read it."}
    out = clean(result.data, {l.id for l in lines})
    out.update({"available": True, "lines_priced": len(out["lines"]), "lines_in_enquiry": len(lines),
                "low_confidence": out["confidence"] is not None and out["confidence"] < 0.7})
    return out


@router.post("/api/vendor-quote/{token}")
def vendor_quote_send(token: str, request: Request, quote: str = Form("{}"), file: Optional[UploadFile] = File(None),
                      db: Session = Depends(get_db)):
    """His answer: the rates he typed (or checked after his file was read), his quotation file, or both. Sent again, it
    replaces the last one until the enquiry is closed."""
    inv, rfq, client = _invite(db, token, request, "send", 20)
    _closed(rfq)
    try:
        body = json.loads(quote or "{}")
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "The quote could not be read. Reload the page and try again.")
    body["supplier_name"] = inv.supplier_name
    has_rates = any(_positive(l.get("rate")) for l in (body.get("lines") or []) if isinstance(l, dict))
    data = file.file.read() if file is not None and file.filename else b""
    if not has_rates and not data:
        raise HTTPException(400, "Type at least one rate, or attach your quotation.")
    if data:
        # the file must be one that can be read, so the buyer is never sent something he cannot open
        inputs.read_bytes(data, file.filename, file.content_type or "", "", "quotation")
    inv.message = (body.get("message") or "").strip()[:1000]
    what = []
    if has_rates:
        q, revised = save_quote(db, rfq, body, source="vendor")
        inv.quote_id = q.id
        what.append("revised quote" if revised else "quote")
        if data:
            keep_document(db, inv.client_id, rfq, "rfq_quote", q.id, file, data, by=inv.supplier_name)
    elif data:
        f = keep_document(db, inv.client_id, rfq, "rfq_invite", inv.id, file, data, by=inv.supplier_name)
        inv.document_id = f.id
        what.append("quotation document (rates to be read)")
    inv.submitted_at = _now()
    db.commit()
    notify(db, inv.client_id, "quote_received", "%s sent a %s for %s" % (inv.supplier_name, what[0], rfq.number),
           "%s - %s%s" % (rfq.number, rfq.title or "", (". Message: " + inv.message) if inv.message else ""),
           view="store/enquiries?id=%d" % rfq.id, ref_type="rfq", ref_id=rfq.id)
    return {"ok": True, "message": "Thank you. Your %s has reached %s. You can change it here until they decide." % (
        what[0], (client.company_name if client else "") or "the company")}


def _positive(v):
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False
