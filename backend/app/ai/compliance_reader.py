"""Read a contractor's licence, registration or insurance paper (photo, PDF or pasted text) into the "add a paper" form.

Nothing is saved: the person checks what was read and saves it with the normal "add paper" button. The kind is checked
against the fixed list, dates are checked as dates, and the holder named on the paper is compared with the contractor.

    POST /api/ai/subcontracts/contractors/{contractor_id}/read-document        (multipart: file, or text)
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.ai import guard, inputs
from app.ai.llm_client import ask_json
from app.constants.compliance import DOC_KINDS
from app.core.auth import require_erp_read
from app.db import get_db
from app.services.subcontract_orders import contractor_or_404

router = APIRouter()

ACTION_KEY = "ai_document_read"

SYSTEM = (
    "You read a compliance paper held by a construction subcontractor in India: a labour licence, PF or ESI "
    "registration, an insurance policy, or a construction-workers' registration. Report only what the paper says. "
    "If something is not present, use null. Never guess a date or number."
)


def build_prompt(text: str) -> str:
    kinds = ", ".join('"%s" (%s)' % (k, v) for k, v in DOC_KINDS.items())
    return ('Read this paper%s and return a JSON object with:\n  "kind": one of %s\n  "number": the licence, registration or policy number (text or null)\n'
            '  "holder_name": who it is issued to (text or null)\n  "valid_from": YYYY-MM-DD or null\n  "valid_to": the expiry date, YYYY-MM-DD or null\n'
            '  "confidence": from 0 to 1\n') % (" below" if text else "", kinds) + (("\nPaper text:\n" + text[:12000]) if text else "")


def _date(s):
    try:
        return datetime.strptime(str(s or "")[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in ("and", "the", "pvt", "ltd", "private", "limited", "m", "s")}


def clean(read: dict, contractor_name: str) -> dict:
    kind = read.get("kind") if read.get("kind") in DOC_KINDS else "other"
    holder = str(read.get("holder_name") or "")[:120]
    warnings = []
    if holder and contractor_name and not (_words(holder) & _words(contractor_name)):
        warnings.append("The paper is issued to %s, which does not look like %s." % (holder, contractor_name))
    valid_to, valid_from = _date(read.get("valid_to")), _date(read.get("valid_from"))
    if not valid_to:
        warnings.append("No expiry date could be read. Enter it before saving.")
    elif valid_from and valid_to < valid_from:
        warnings.append("The expiry date is before the start date. Check both.")
    conf = read.get("confidence")
    return {"kind": kind, "number": str(read.get("number") or "")[:60], "holder_name": holder, "valid_from": valid_from,
            "valid_to": valid_to, "warnings": warnings, "confidence": conf if isinstance(conf, (int, float)) else None}


@router.post("/api/ai/subcontracts/contractors/{contractor_id}/read-document")
def read_document(contractor_id: int, request: Request, file: Optional[UploadFile] = File(None), text: str = Form(""),
                  db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    con = contractor_or_404(db, client.id, contractor_id)
    attachments, text = inputs.take(file, text, "paper")
    prompt = build_prompt(text)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Paper read %s" % con.company_name, con.company_name or "",
                               lambda: ask_json(SYSTEM, prompt, attachments, smart=True, max_tokens=800))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message}
    out = clean(result.data, con.company_name or "")
    out.update({"available": True, "model": result.model,
                "low_confidence": out["confidence"] is not None and out["confidence"] < 0.7})
    return out
