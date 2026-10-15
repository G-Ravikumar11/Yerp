"""Read a supplier's quote (a PDF, a photo, or pasted text) into the enquiry's quote form. Nothing is saved: the buyer
checks what was read, fixes it and saves it with the normal "record quote" button.

Pasted text, photos and PDFs with text are read by Groq; only a scanned PDF needs the Claude key. The model only matches what the paper says to the
enquiry's own lines; every line it returns is checked here against those lines, and any it cannot match is listed apart.

    POST /api/ai/rfqs/{rfq_id}/read-quote        (multipart: file, or text)
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.ai import guard, inputs
from app.ai.llm_client import ask_json
from app.core.auth import require_erp_read
from app.db import get_db
from app.services.procurement import _rfq_lines, rfq_or_404

router = APIRouter()

ACTION_KEY = "ai_quote_read"
READABLE = inputs.READABLE
MAX_BYTES = inputs.MAX_BYTES

SYSTEM = (
    "You read a supplier's price quotation for a construction company and match it to the company's enquiry lines. "
    "Report only what the quotation says. If a rate, tax or term is not stated, use null. Never calculate or guess. "
    "Rates are per unit in rupees, without symbols or commas."
)


def build_prompt(lines, text: str) -> str:
    listing = "\n".join('  {"rfq_line_id": %d, "item_code": "%s", "description": "%s", "uom": "%s", "qty": %s}' % (
        l.id, l.item_code or "", (l.description or "").replace('"', "'"), l.uom or "", l.qty or 0) for l in lines)
    return ("The enquiry's lines are:\n[\n%s\n]\n\nRead the quotation%s and return a JSON object with:\n"
            '  "supplier_name": who issued it (text or null)\n  "quote_ref": their quotation number (text or null)\n'
            '  "quote_date": YYYY-MM-DD or null\n  "valid_until": YYYY-MM-DD or null\n'
            '  "delivery_days": number of days or null\n  "payment_terms": text or null\n  "freight": a lump-sum freight in rupees or null\n'
            '  "lines": for each enquiry line the quotation prices, {"rfq_line_id": the id above, "rate": number, "tax_percent": number or null, "remarks": text}\n'
            '  "unmatched": a list of items on the quotation that match none of the enquiry lines, each as text\n'
            '  "confidence": from 0 to 1\n') % (listing, (" below" if text else "")) + (("\nQuotation text:\n" + text[:12000]) if text else "")


def clean(read: dict, valid_ids: set) -> dict:
    """Keep only lines that name a real enquiry line and have a usable rate; everything else is reported, not used."""
    kept, dropped = [], []
    seen = set()
    for l in read.get("lines") or []:
        if not isinstance(l, dict):
            continue
        try:
            lid, rate = int(l.get("rfq_line_id")), float(l.get("rate"))
        except (TypeError, ValueError):
            dropped.append(str(l)[:80])
            continue
        if lid not in valid_ids or rate <= 0 or lid in seen:
            dropped.append(str(l)[:80])
            continue
        seen.add(lid)
        tax = l.get("tax_percent")
        kept.append({"rfq_line_id": lid, "rate": rate, "tax_percent": float(tax) if isinstance(tax, (int, float)) else None,
                     "remarks": str(l.get("remarks") or "")[:200]})
    freight = read.get("freight")
    days = read.get("delivery_days")
    return {"supplier_name": read.get("supplier_name") or "", "quote_ref": read.get("quote_ref") or "",
            "quote_date": read.get("quote_date") or "", "valid_until": read.get("valid_until") or "",
            "delivery_days": int(days) if isinstance(days, (int, float)) else 0,
            "payment_terms": read.get("payment_terms") or "", "freight": float(freight) if isinstance(freight, (int, float)) else 0.0,
            "lines": kept, "unmatched": [str(x)[:120] for x in (read.get("unmatched") or [])] + dropped,
            "confidence": read.get("confidence") if isinstance(read.get("confidence"), (int, float)) else None}


@router.post("/api/ai/rfqs/{rfq_id}/read-quote")
def read_quote(rfq_id: int, request: Request, file: Optional[UploadFile] = File(None), text: str = Form(""),
                     db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    rfq = rfq_or_404(db, client.id, rfq_id)
    lines = _rfq_lines(db, rfq.id)
    attachments, text = inputs.take(file, text, "quotation")
    prompt = build_prompt(lines, text)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Quote read %s" % rfq.number, rfq.number or "",
                               lambda: ask_json(SYSTEM, prompt, attachments, smart=True, max_tokens=3000))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message}
    out = clean(result.data, {l.id for l in lines})
    out.update({"available": True, "model": result.model, "low_confidence": out["confidence"] is not None and out["confidence"] < 0.7,
                "lines_priced": len(out["lines"]), "lines_in_enquiry": len(lines)})
    return out


# --- checking a quote against the supplier's own quotation ---------------------------------------------------------
#
# As an RA bill is checked against its hard copy: the model only READS the supplier's document; what agrees and what
# differs is plain arithmetic here, so every difference shown is one anyone can check against the paper.

def _same(a, b, pct=0.005, floor=0.01):
    return a is not None and b is not None and abs(a - b) <= max(floor, abs(b) * pct)


def compare_quote(read: dict, lines, entered: dict, quote) -> dict:
    """read: what clean() made of the document. entered: {rfq_line_id: (rate, tax_percent)} as saved in the app.
    Returns one row per enquiry item and the terms, each marked agrees / differs / only_entered / only_paper."""
    paper = {l["rfq_line_id"]: l for l in read.get("lines") or []}
    rows, differs = [], 0
    for l in lines:
        e, p = entered.get(l.id), paper.get(l.id)
        row = {"rfq_line_id": l.id, "item": l.description or "", "uom": l.uom or "", "qty": l.qty or 0,
               "entered_rate": e[0] if e else None, "paper_rate": p["rate"] if p else None,
               "entered_tax": e[1] if e else None, "paper_tax": p["tax_percent"] if p else None}
        if e and p:
            ok = _same(p["rate"], e[0]) and (p["tax_percent"] is None or _same(p["tax_percent"], e[1], 0, 0.01))
            row["status"] = "agrees" if ok else "differs"
        elif e:
            row["status"] = "only_entered"            # entered in the app, not found on their quotation
        elif p:
            row["status"] = "only_paper"              # on their quotation, not entered in the app
        else:
            row["status"] = "not_quoted"
        differs += row["status"] in ("differs", "only_entered", "only_paper")
        rows.append(row)
    terms = []
    for label, ours, theirs in (("Transport to site", quote.freight or 0, read.get("freight") or None),
                                ("Delivery (days)", quote.delivery_days or 0, read.get("delivery_days") or None)):
        if theirs is None:
            continue
        ok = _same(float(theirs), float(ours))
        terms.append({"item": label, "entered": ours, "paper": theirs, "status": "agrees" if ok else "differs"})
        differs += not ok
    if read.get("quote_ref") and quote.quote_ref and read["quote_ref"].replace(" ", "").lower() != quote.quote_ref.replace(" ", "").lower():
        terms.append({"item": "Quotation no.", "entered": quote.quote_ref, "paper": read["quote_ref"], "status": "differs"})
        differs += 1
    return {"rows": rows, "terms": terms, "differences": differs, "agrees": differs == 0 and any(r["status"] == "agrees" for r in rows),
            "unmatched": read.get("unmatched") or []}


@router.post("/api/ai/rfqs/{rfq_id}/quotes/{quote_id}/check")
def check_quote_against_document(rfq_id: int, quote_id: int, request: Request, db: Session = Depends(get_db)):
    """Read the supplier's own quotation kept with this quote, and compare it item by item with what was entered."""
    from app import models
    from app.core.files import _file_or_404, file_bytes
    from fastapi import HTTPException
    client = require_erp_read(request, db)
    rfq = rfq_or_404(db, client.id, rfq_id)
    quote = db.query(models.DBRfqQuote).filter(models.DBRfqQuote.id == quote_id, models.DBRfqQuote.rfq_id == rfq.id).first()
    if quote is None:
        raise HTTPException(404, "That quote is not on this enquiry.")
    doc = db.query(models.DBFile).filter(models.DBFile.client_id == client.id, models.DBFile.attached_type == "rfq_quote",
                                         models.DBFile.attached_id == quote.id).order_by(models.DBFile.id.desc()).first()
    if doc is None:
        raise HTTPException(409, "Attach %s's quotation first; there is nothing to check against yet." % quote.supplier_name)
    f = _file_or_404(db, client.id, doc.id, bytes_too=True)
    data = file_bytes(db, f)
    if not data:
        raise HTTPException(404, "The quotation file has no content.")
    lines = _rfq_lines(db, rfq.id)
    attachments, text = inputs.read_bytes(data, f.name or "", f.content_type or "", "", "quotation")
    result = guard.run_feature(db, request, client, ACTION_KEY, "Quote check %s (%s)" % (rfq.number, quote.supplier_name),
                               rfq.number or "", lambda: ask_json(SYSTEM, build_prompt(lines, text), attachments, smart=True, max_tokens=3000))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message}
    read = clean(result.data, {l.id for l in lines})
    entered = {ql.rfq_line_id: (ql.rate, ql.tax_percent or 0) for ql in db.query(models.DBRfqQuoteLine).filter(
        models.DBRfqQuoteLine.quote_id == quote.id).all() if (ql.rate or 0) > 0}
    out = compare_quote(read, lines, entered, quote)
    out.update({"available": True, "confidence": read.get("confidence"), "model": result.model,
                "low_confidence": read.get("confidence") is not None and read["confidence"] < 0.7})
    return out
