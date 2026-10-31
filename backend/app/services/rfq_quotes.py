"""A supplier's answer to an enquiry, however it came: typed in by the buyer, or sent by the supplier through his own
link. One way of saving it, so both are checked alike; and the supplier's own quotation document kept with it.
"""
import secrets
from datetime import datetime

from fastapi import HTTPException

from app import models
from app.core.currency import money, unit_rate
from app.core.files import store_file
from app.services.crm import norm_name
from app.services.procurement import _rfq_lines, comparative_statement

DOC_KIND = "quote_document"


def save_quote(db, rfq, body, source=""):
    """Record (or revise) a supplier's quote. `body` holds supplier_name, quote_ref, quote_date, delivery_days,
    payment_terms, freight, valid_until, notes and lines [{rfq_line_id, rate, tax_percent, remarks}]. Sent again by
    the same supplier, it replaces his last one: a revised quote is the same supplier changing his mind.
    Returns (quote, revised)."""
    if rfq.status != "OPEN":
        raise HTTPException(409, "%s is %s; its quotes are closed." % (rfq.number, rfq.status.lower()))
    get = body.get if isinstance(body, dict) else (lambda k, d=None: getattr(body, k, d))
    name = (get("supplier_name") or "").strip()
    if not name:
        raise HTTPException(400, "Whose quote is this?")
    raw_lines = [l if isinstance(l, dict) else l.model_dump() for l in (get("lines") or [])]
    if any(_num(l.get("rate")) < 0 for l in raw_lines) or _num(get("freight")) < 0:
        raise HTTPException(400, "A rate or freight cannot be negative.")
    valid_ids = {l.id for l in _rfq_lines(db, rfq.id)}
    lines = [l for l in raw_lines if _int(l.get("rfq_line_id")) in valid_ids and _num(l.get("rate")) > 0]
    if not lines:
        raise HTTPException(400, "The quote has no rates on it.")
    existing = next((q for q in db.query(models.DBRfqQuote).filter(models.DBRfqQuote.rfq_id == rfq.id).all()
                     if norm_name(q.supplier_name) == norm_name(name)), None)
    if existing:
        db.query(models.DBRfqQuoteLine).filter(models.DBRfqQuoteLine.quote_id == existing.id).delete()
        q = existing
    else:
        q = models.DBRfqQuote(rfq_id=rfq.id)
        db.add(q)
    q.supplier_name = name[:120]
    q.quote_ref = (get("quote_ref") or "").strip()[:80]
    q.quote_date = (get("quote_date") or datetime.now().strftime("%Y-%m-%d"))[:10]
    q.delivery_days = max(0, int(_num(get("delivery_days"))))
    q.payment_terms = (get("payment_terms") or "").strip()[:200]
    q.freight = money(_num(get("freight")))
    q.valid_until = (get("valid_until") or "").strip()[:10]
    q.notes = (get("notes") or "").strip()[:2000]
    q.source = source or q.source or ""
    db.flush()
    seen = set()
    for l in lines:
        lid = _int(l.get("rfq_line_id"))
        if lid in seen:
            continue
        seen.add(lid)
        tax = l.get("tax_percent")
        db.add(models.DBRfqQuoteLine(quote_id=q.id, rfq_line_id=lid, rate=unit_rate(_num(l.get("rate"))),
                                     tax_percent=_num(tax) if tax not in (None, "") else 0,
                                     remarks=(l.get("remarks") or "").strip()[:200]))
    db.flush()
    return q, bool(existing)


def keep_document(db, client_id, rfq, attached_type, attached_id, upload, data, by=""):
    """The supplier's own quotation, kept as he sent it (PDF, Word, Excel, a photo...)."""
    return store_file(db, client_id, upload, data, job_id=rfq.job_id, attached_type=attached_type,
                      attached_id=attached_id, kind=DOC_KIND, caption="Quotation for %s" % (rfq.number or ""), by=by)


def documents_of(db, client_id, attached_type, ids):
    """{id: {"id", "name", "size"}}: the latest document kept for each."""
    if not ids:
        return {}
    out = {}
    for f in db.query(models.DBFile.id, models.DBFile.attached_id, models.DBFile.name, models.DBFile.size).filter(
            models.DBFile.client_id == client_id, models.DBFile.attached_type == attached_type,
            models.DBFile.attached_id.in_(list(ids))).order_by(models.DBFile.id).all():
        out[f.attached_id] = {"id": f.id, "name": f.name or "quotation", "size": f.size or 0}
    return out


# --- links for suppliers --------------------------------------------------------------------------------------------

def new_token():
    return secrets.token_urlsafe(24)


def invite_status(inv):
    if inv.quote_id:
        return "quoted"
    if inv.document_id:
        return "document"            # sent his quotation without rates: to be read by the buyer
    if inv.opened_at:
        return "opened"
    return "sent"


def invite_dict(inv, base=""):
    return {"id": inv.id, "supplier_name": inv.supplier_name or "", "phone": inv.phone or "", "email": inv.email or "",
            "status": invite_status(inv), "opened_at": inv.opened_at or "", "submitted_at": inv.submitted_at or "",
            "quote_id": inv.quote_id, "document_id": inv.document_id, "message": inv.message or "",
            "created_at": inv.created_at or "", "created_by_name": inv.created_by_name or "",
            "emailed_at": getattr(inv, "emailed_at", "") or "", "reminders": getattr(inv, "reminders", 0) or 0,
            "link": "%s/next/quote?token=%s" % (base.rstrip("/"), inv.token)}


def invites_of(db, rfq_id):
    return db.query(models.DBRfqInvite).filter(models.DBRfqInvite.rfq_id == rfq_id).order_by(models.DBRfqInvite.id).all()


def statement_for_screen(db, client_id, rfq, base=""):
    """The comparative statement, with who entered each quote, the supplier's own document beside it, and the links
    sent for quotes and how far each has got."""
    st = comparative_statement(db, rfq)                 # its suppliers carry who entered each quote, and its orders
    # Each supplier's record with us - delivery, rejections, price, how fast they answer - beside their price.
    from app.services.supplier_scorecard import card_for, scorecards
    cards = scorecards(db, client_id)
    for s in st["suppliers"]:
        s["scorecard"] = card_for(cards, s["supplier_name"])
    docs = documents_of(db, client_id, "rfq_quote", [s["quote_id"] for s in st["suppliers"]])
    for s in st["suppliers"]:
        s["document"] = docs.get(s["quote_id"])
    invites = invites_of(db, rfq.id)
    inv_docs = documents_of(db, client_id, "rfq_invite", [i.id for i in invites if i.document_id])
    st["invites"] = [dict(invite_dict(i, base), document=inv_docs.get(i.id)) for i in invites]
    return st


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
