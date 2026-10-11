"""A short review for whoever has to certify a contractor's bill: what looks wrong, and a plain summary.

The flags come from plain code and always work, with or without an AI key. The model only writes the summary from
those flags and the bill's own figures; it is told not to add anything of its own.

    GET /api/ai/subcontracts/bills/{bill_id}/review
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai import guard
from app.ai.llm_client import ask
from app import models
from app.core.auth import require_erp_read
from app.core.currency import inr, money
from app.db import get_db
from app.services.subcontract_billing import sub_bill_dict, sub_bill_or_404

router = APIRouter()

ACTION_KEY = "ai_bill_review"

SYSTEM = (
    "You help a construction company's approver read a subcontractor's bill. You are given the bill's figures and a "
    "list of checks that were already worked out. Write a summary of at most five short sentences in plain English: "
    "what the bill is, then the most important concerns first. Use only the figures and checks you are given. Do not "
    "invent causes, advise paying or rejecting, or repeat every figure."
)


def find_flags(bill: dict, earlier_amounts: list) -> list:
    """Checks anyone could do by hand. Each flag: {level: stop|check|note, text}."""
    flags = []
    for l in bill.get("lines") or []:
        ordered = l.get("ordered_qty") or 0
        total = (l.get("previously_billed_qty") or 0) + (l.get("this_bill_qty") or 0)
        if ordered and total > ordered * 1.0001:
            flags.append({"level": "stop", "text": "%s is billed %s in total against %s ordered." % (
                l.get("description") or l.get("activity_no") or "An item", round(total, 2), round(ordered, 2))})
    for w in bill.get("compliance_warnings") or []:
        stop = "not on record" in w or "ran out" in w
        flags.append({"level": "stop" if stop else "check", "text": "Papers: " + w})
    hc = bill.get("hardcopy")
    if not hc:
        flags.append({"level": "check", "text": "No hard copy of this bill is attached."})
    elif hc.get("difference") is not None and abs(hc["difference"]) > 0.5:
        flags.append({"level": "check", "text": "The amount on the hard copy differs from this bill by %s." % inr(abs(hc["difference"]))})
    if earlier_amounts:
        average = sum(earlier_amounts) / len(earlier_amounts)
        if average > 0 and (bill.get("this_bill") or 0) > 2 * average:
            flags.append({"level": "check", "text": "This bill (%s) is more than twice the average of their earlier bills (%s)." % (
                inr(bill["this_bill"]), inr(average))})
    open_charges = bill.get("open_back_charges") or []
    if open_charges and bill.get("status") == "DRAFT":
        flags.append({"level": "check", "text": "%d back-charge(s) worth %s are open for this contractor and not on this bill." % (
            len(open_charges), inr(sum(c["amount"] for c in open_charges)))})
    work = bill.get("this_bill") or 0
    if work > 0 and (bill.get("net_payable") or 0) < 0.5 * work:
        flags.append({"level": "note", "text": "Deductions take the net payable below half the value of the work."})
    return flags


def _facts(bill: dict, flags: list) -> str:
    keys = ("number", "contractor", "project", "order", "status", "this_bill", "previously_billed", "gst_amount",
            "retention_amount", "advance_recovery", "other_deductions", "back_charges", "tds_amount", "net_payable")
    lines = ["%s: %s" % (k, bill.get(k)) for k in keys]
    lines.append("work items: %d" % len(bill.get("lines") or []))
    lines.append("checks:")
    lines += ["- [%s] %s" % (f["level"], f["text"]) for f in flags] or ["- none raised"]
    return "\n".join(lines)


@router.get("/api/ai/subcontracts/bills/{bill_id}/review")
def review_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    row = sub_bill_or_404(db, client.id, bill_id)
    bill = sub_bill_dict(db, row, detail=True)
    earlier = [money(b.this_bill or 0) for b in db.query(models.DBSubBill).filter(
        models.DBSubBill.contractor_id == row.contractor_id, models.DBSubBill.id < row.id,
        models.DBSubBill.status != "CANCELLED").all()]
    flags = find_flags(bill, earlier)
    out = {"flags": flags, "stop": any(f["level"] == "stop" for f in flags), "summary": None, "ai": guard.status()}
    if not out["ai"]["available"]:
        return out
    facts = _facts(bill, flags)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Bill review %s" % row.number, row.number or "",
                               lambda: ask(SYSTEM, facts, smart=False, max_tokens=400))
    if result.ok:
        out["summary"], out["model"] = result.text, result.model
    else:
        out["ai_message"] = result.message
    return out
