"""Read the scanned hard copy of a contractor's bill and compare it with the bill drawn up in the app.

The model only READS: it returns the figures it can see on the paper, each with a confidence. The comparison is plain
code (`compare`), so a mismatch is always arithmetic anyone can check, never the model's opinion.

    POST /api/ai/subcontracts/bills/{bill_id}/hard-copy-check
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from Ai_service import guard
from Ai_service.llm_client import Attachment, AiResult, ask_json
from app.core.auth import require_erp_read
from app.core.currency import money
from app.core.files import _file_or_404, file_bytes
from app.db import get_db
from app.services.subcontract_billing import sub_bill_dict, sub_bill_or_404

router = APIRouter()

ACTION_KEY = "ai_hard_copy_check"
READABLE = ("application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif")

SYSTEM = (
    "You read a scanned paper bill from a civil-construction subcontractor in India. Report only what is printed or "
    "written on it. Never calculate, correct or guess a figure: if one is not legible or not present, use null. "
    "Amounts are in rupees without symbols or commas."
)

PROMPT = """Read this contractor's bill and return a JSON object with these keys:
  "work_value": the value of the work claimed in THIS bill before tax (number or null)
  "gst": the GST amount charged (number or null)
  "retention": retention held back (number or null)
  "tds": TDS deducted (number or null)
  "other_deductions": advances, recoveries or other deductions combined (number or null)
  "net_payable": the net amount payable (number or null)
  "lines": a list of the work items billed, each {"description": text, "quantity": number or null, "rate": number or null, "amount": number or null}
  "confidence": your confidence that the figures above are read correctly, from 0 to 1
  "notes": anything on the paper that looks altered, unclear, cut off or inconsistent, in one short sentence ("" if none)"""

HEADLINES = (
    ("work_value", "this_bill", "Value of work"),
    ("gst", "gst_amount", "GST"),
    ("retention", "retention_amount", "Retention"),
    ("tds", "tds_amount", "TDS"),
    ("net_payable", "net_payable", "Net payable"),
)


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def compare(read: dict, bill: dict) -> dict:
    """Plain comparison of what the paper says with what the bill says. Tolerance: one rupee, or half a percent."""
    mismatches, agreed = [], []
    for key, bill_key, label in HEADLINES:
        paper, ours = _num(read.get(key)), money(bill.get(bill_key) or 0)
        if paper is None:
            continue
        tolerance = max(1.0, abs(ours) * 0.005)
        row = {"item": label, "paper": money(paper), "bill": ours, "difference": money(ours - paper)}
        (agreed if abs(ours - paper) <= tolerance else mismatches).append(row)

    # Work items: each bill line should have a line on the paper with the same quantity and amount.
    paper_lines = [l for l in (read.get("lines") or []) if isinstance(l, dict)]
    unused = list(range(len(paper_lines)))
    only_bill = []
    for l in bill.get("lines") or []:
        if not (l.get("this_bill_qty") or l.get("amount")):
            continue
        hit = None
        for i in unused:
            p = paper_lines[i]
            pq, pa = _num(p.get("quantity")), _num(p.get("amount"))
            if pa is not None and abs(pa - (l.get("amount") or 0)) <= max(1.0, abs(l.get("amount") or 0) * 0.005):
                hit = i
                break
            if pq is not None and abs(pq - (l.get("this_bill_qty") or 0)) <= 0.01 and pq:
                hit = i
                break
        if hit is None:
            only_bill.append({"description": l.get("description"), "quantity": l.get("this_bill_qty"), "amount": l.get("amount")})
        else:
            unused.remove(hit)
    only_paper = [{"description": paper_lines[i].get("description"), "quantity": paper_lines[i].get("quantity"),
                   "amount": paper_lines[i].get("amount")} for i in unused]
    return {"mismatches": mismatches, "agreed": agreed, "only_on_bill": only_bill, "only_on_paper": only_paper,
            "agrees": not mismatches and not only_bill and not only_paper and bool(agreed)}


def read_hard_copy(data: bytes, media_type: str) -> AiResult:
    return ask_json(SYSTEM, PROMPT, [Attachment(data, media_type)], smart=True, max_tokens=3000)


@router.post("/api/ai/subcontracts/bills/{bill_id}/hard-copy-check")
def hard_copy_check(bill_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    bill = sub_bill_or_404(db, client.id, bill_id)
    if not bill.scan_file_id:
        raise HTTPException(409, "Attach the hard copy of this bill first; there is nothing to read yet.")
    f = _file_or_404(db, client.id, bill.scan_file_id, bytes_too=True)
    media = (f.content_type or "").lower()
    if media not in READABLE:
        raise HTTPException(400, "The attached file is not a PDF or a picture the AI can read.")
    data = file_bytes(db, f)
    if not data:
        raise HTTPException(404, "The attached file has no content.")
    result = guard.run_feature(db, request, client, ACTION_KEY, "Hard-copy check %s" % bill.number, bill.number or "",
                               lambda: read_hard_copy(data, media))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message}
    read = result.data
    out = compare(read, sub_bill_dict(db, bill, detail=True))
    confidence = _num(read.get("confidence"))
    out.update({"available": True, "read": read, "confidence": confidence, "notes": read.get("notes") or "",
                "low_confidence": confidence is not None and confidence < 0.7, "model": result.model})
    return out
