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
