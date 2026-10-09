"""A draft email to the supplier for a purchase order. Always returns a draft: the model improves the wording when
it is available, and a plain template is used when it is not. Nothing is sent; a person reads it and sends it.

    POST /api/ai/purchase-orders/{order_id}/draft-email
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from Ai_service import guard
from Ai_service.llm_client import ask_json
from app.core.auth import require_erp_read
from app.core.currency import inr
from app.db import get_db
from app.services.procurement import purchase_order_or_404, purchase_order_to_dict

router = APIRouter()

ACTION_KEY = "ai_po_email"

SYSTEM = (
    "You write short, polite, businesslike emails from a construction company to a material supplier, sending a "
    "purchase order. Use only the facts given: never invent prices, dates, terms or promises. Return JSON with "
    '"subject" and "body" (plain text, under 120 words, ending with the sender\'s company name).'
)


def plain_draft(po: dict, company: str) -> dict:
    lines = "\n".join("  - %s: %s %s" % (l["description"] or l["item_code"], l["qty"], l["uom"]) for l in po["line_items"][:15])
    needed = ("We need the material by %s.\n\n" % po["needed_by"]) if po["needed_by"] else ""
    body = ("Dear %s,\n\nPlease find our purchase order %s for %s attached.\n\n%s%sKindly confirm receipt and the delivery date.\n\n"
            "Regards,\n%s") % (po["supplier_name"] or "Sir/Madam", po["number"], inr(po["total"]), lines + "\n\n" if lines else "", needed, company)
    return {"subject": "Purchase order %s - %s" % (po["number"], company), "body": body}


@router.post("/api/ai/purchase-orders/{order_id}/draft-email")
def draft_email(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    po = purchase_order_to_dict(db, purchase_order_or_404(db, client.id, order_id))
    company = client.company_name or "Our company"
    draft = plain_draft(po, company)
    out = {"to": po["supplier_email"], "subject": draft["subject"], "body": draft["body"], "written_by_ai": False, "ai": guard.status()}
    if not out["ai"]["available"]:
        return out
    facts = "company: %s\nsupplier: %s\norder: %s\ntotal: %s\nneeded by: %s\nlines:\n%s" % (
        company, po["supplier_name"], po["number"], inr(po["total"]), po["needed_by"] or "not set",
        "\n".join("- %s, %s %s" % (l["description"] or l["item_code"], l["qty"], l["uom"]) for l in po["line_items"][:15]))
    result = guard.run_feature(db, request, client, ACTION_KEY, "PO email %s" % po["number"], po["number"],
                               lambda: ask_json(SYSTEM, facts, smart=False, max_tokens=500))
    if result.ok and isinstance(result.data.get("subject"), str) and isinstance(result.data.get("body"), str):
        out.update({"subject": result.data["subject"].strip(), "body": result.data["body"].strip(), "written_by_ai": True, "model": result.model})
    elif not result.ok:
        out["ai_message"] = result.message
    return out
