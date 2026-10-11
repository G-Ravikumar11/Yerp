"""Ask a question about an order's measurement book and get an answer worked out from what is in it.

The model is given the order's own totals and entries and told to answer from them alone; it changes nothing.

    POST /api/ai/subcontracts/orders/{order_id}/ask-book        {"question": "..."}
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from Ai_service import guard
from Ai_service.llm_client import ask
from app import models
from app.core.auth import require_erp_read
from app.core.currency import money
from app.db import get_db
from app.services.subcontract_billing import sub_order_or_404

router = APIRouter()

ACTION_KEY = "ai_measurement_ask"
MAX_ENTRIES = 400

SYSTEM = (
    "You answer a site engineer's question about one subcontract order's measurement book. You are given the order's "
    "items with ordered and measured quantities, and its entries. Answer only from them, in plain English, in at most "
    "six short sentences, quoting the figures you rely on. If the data cannot answer it, say so. Never invent a "
    "figure. You cannot change the book."
)


def build_facts(order, items, entries) -> str:
    label = {i.id: ((i.activity_no + " ") if i.activity_no else "") + (i.item_description or i.item_code or "Item")[:50] for i in items}
    measured = {}
    for e in entries:
        if not e.kind:
            measured[e.item_id] = measured.get(e.item_id, 0) + (e.quantity or 0)
    lines = ["Order %s, from %s to %s." % (order.wo_number, order.commencement_date or "?", order.completion_date or "?"), "Items:"]
    for i in items:
        lines.append("- %s: ordered %s %s, measured %s, rate %s" % (label[i.id], money(i.quantity or 0), i.uom or "", money(measured.get(i.id, 0)), money(i.unit_rate or 0)))
    lines.append("Entries (%d, newest first%s):" % (len(entries), ", first %d shown" % MAX_ENTRIES if len(entries) > MAX_ENTRIES else ""))
    for e in entries[:MAX_ENTRIES]:
        tag = " | HOLD" if e.kind == "hold" else " | RELEASE" if e.kind == "release" else ""
        lines.append("- %s | %s | %s | %s%s%s" % (e.measured_on or "undated", label.get(e.item_id, "?"), money(e.quantity or 0), e.location or "-", tag,
                                                 (" | " + e.remarks) if e.remarks else ""))
    return "\n".join(lines)


@router.post("/api/ai/subcontracts/orders/{order_id}/ask-book")
def ask_book(order_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    order = sub_order_or_404(db, client.id, order_id)
    question = str(body.get("question") or "").strip()[:500]
    if not question:
        raise HTTPException(400, "Type a question about this book.")
    items = db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id,
                                                      models.DBSubcontractItem.is_header == False).all()  # noqa: E712
    entries = db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id == order.id).order_by(
        models.DBSubMeasurement.id.desc()).all()
    prompt = "%s\n\nQuestion: %s" % (build_facts(order, items, entries), question)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Measurement book question %s" % order.wo_number, order.wo_number or "",
                               lambda: ask(SYSTEM, prompt, smart=False, max_tokens=600))
    if not result.ok:
        return {"available": False, "reason": result.reason, "message": result.message, "answer": ""}
    return {"available": True, "answer": result.text, "message": ""}
