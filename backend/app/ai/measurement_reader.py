"""Read a handwritten or typed measurement sheet (photo, PDF or pasted text) into measurement-book rows.

Nothing is saved: the engineer checks the rows and adds them with the normal "record measurement" call. The model only
matches what the sheet says to the order's own items; every row is checked here against those items, and anything that
cannot be matched is listed apart.

    POST /api/ai/subcontracts/orders/{order_id}/read-measurements        (multipart: file, or text)
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.ai import guard, inputs
from app.ai.llm_client import ask_json
from app import models
from app.core.auth import require_erp_read
from app.db import get_db
from app.services.subcontract_billing import sub_order_or_404

router = APIRouter()

ACTION_KEY = "ai_measurement_read"

SYSTEM = (
    "You read a site measurement sheet for a civil-construction subcontract and match each line to the order's items. "
    "Report only what the sheet says. If a quantity or date is not legible or not present, use null. Never calculate "
    "or guess. Quantities are plain numbers in the item's own unit."
)


def build_prompt(items, text: str) -> str:
    listing = "\n".join('  {"item_id": %d, "activity_no": "%s", "description": "%s", "uom": "%s"}' % (
        i.id, i.activity_no or "", (i.item_description or i.item_code or "").replace('"', "'")[:80], i.uom or "") for i in items)
    return ("The order's items are:\n[\n%s\n]\n\nRead the measurement sheet%s and return a JSON object with:\n"
            '  "rows": for each measured line, {"item_id": the id above, "location": where on site (text or ""), "quantity": number, '
            '"measured_on": YYYY-MM-DD or null, "remarks": text}\n'
            '  "unmatched": lines on the sheet that match none of the items, each as text\n'
            '  "confidence": from 0 to 1\n') % (listing, " below" if text else "") + (("\nSheet text:\n" + text[:12000]) if text else "")


def clean(read: dict, valid_ids: set) -> dict:
    """Keep only rows that name a real item and carry a usable quantity; everything else is reported, not used."""
    rows, dropped = [], []
    for r in read.get("rows") or []:
        if not isinstance(r, dict):
            continue
        try:
            item_id, qty = int(r.get("item_id")), float(r.get("quantity"))
        except (TypeError, ValueError):
            dropped.append(str(r)[:80])
            continue
        if item_id not in valid_ids or qty == 0:
            dropped.append(str(r)[:80])
            continue
        on = r.get("measured_on")
        rows.append({"item_id": item_id, "location": str(r.get("location") or "")[:80], "quantity": qty,
                     "measured_on": on if isinstance(on, str) and len(on) == 10 else "", "remarks": str(r.get("remarks") or "")[:200]})
    conf = read.get("confidence")
    return {"rows": rows, "unmatched": [str(x)[:120] for x in (read.get("unmatched") or [])] + dropped,
            "confidence": conf if isinstance(conf, (int, float)) else None}


@router.post("/api/ai/subcontracts/orders/{order_id}/read-measurements")
def read_measurements(order_id: int, request: Request, file: Optional[UploadFile] = File(None), text: str = Form(""),
                      db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    order = sub_order_or_404(db, client.id, order_id)
    items = db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id,
                                                      models.DBSubcontractItem.is_header == False).all()  # noqa: E712
    attachments, text = inputs.take(file, text, "measurement sheet")
    prompt = build_prompt(items, text)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Measurement sheet %s" % order.wo_number, order.wo_number or "",
                               lambda: ask_json(SYSTEM, prompt, attachments, smart=True, max_tokens=3000))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message}
    out = clean(result.data, {i.id for i in items})
    out.update({"available": True, "model": result.model,
                "low_confidence": out["confidence"] is not None and out["confidence"] < 0.7})
    return out
