"""A one-page standing of a contractor, for deciding whether to give them the next order.

The standing (papers, rating, money, charges) is worked out in plain code. The model only turns it into a short
paragraph. It suggests; the decision stays with a person.

    GET /api/ai/subcontracts/contractors/{contractor_id}/brief
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.ai import guard
from app.ai.llm_client import ask
from app import models
from app.core.auth import require_erp_read
from app.core.currency import inr, money
from app.db import get_db
from app.services.compliance import contractor_compliance, scorecard

router = APIRouter()

ACTION_KEY = "ai_contractor_brief"

SYSTEM = (
    "You help a construction company decide whether to award a subcontractor another order. You are given facts "
    "about them. Write at most six short sentences: how they stand on papers, quality and money, then one sentence on "
    "what to be careful of. Use only the facts given. Do not invent history, and do not tell the reader to award or "
    "refuse: say what the facts support."
)


def standing(db, client_id, contractor) -> dict:
    papers = contractor_compliance(db, client_id, contractor.id)
    score = scorecard(db, client_id, contractor.id)
    orders = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.client_id == client_id,
                                                        models.DBSubcontractOrder.contractor_id == contractor.id).all()
    bills = db.query(models.DBSubBill).filter(models.DBSubBill.client_id == client_id,
                                              models.DBSubBill.contractor_id == contractor.id,
                                              models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all()
    charges = db.query(models.DBBackCharge).filter(models.DBBackCharge.client_id == client_id,
                                                   models.DBBackCharge.contractor_id == contractor.id,
                                                   models.DBBackCharge.status != "CANCELLED").all()
    worth = money(sum(b.this_bill or 0 for b in bills))
    charged = money(sum(c.amount or 0 for c in charges))
    flags = []
    if not papers["ok"]:
        flags.append("papers missing or lapsed")
    if score["overall"] is not None and score["overall"] < 3:
        flags.append("rated below 3 of 5")
    if worth > 0 and charged / worth > 0.05:
        flags.append("back-charges above 5% of work certified")
    return {
        "contractor": contractor.company_name, "vendor_code": contractor.vendor_code or "",
        "papers_ok": papers["ok"], "paper_warnings": papers["warnings"], "score": score,
        "orders": len(orders), "work_certified": worth, "back_charged": charged,
        "back_charges_open": money(sum(c.amount or 0 for c in charges if c.status == "OPEN")),
        "certified_bills": len(bills), "flags": flags,
        "verdict": "careful" if flags else ("good" if score["overall"] and score["overall"] >= 4 else "ordinary"),
    }


def _facts(s: dict) -> str:
    rate = s["score"]
    return "\n".join([
        "contractor: %s" % s["contractor"],
        "papers in order: %s%s" % ("yes" if s["papers_ok"] else "no", (" (%s)" % "; ".join(s["paper_warnings"])) if s["paper_warnings"] else ""),
        "rating: %s of 5 from %d rating(s) - quality %s, speed %s, safety %s, discipline %s" % (
            rate["overall"], rate["count"], rate["quality"], rate["speed"], rate["safety"], rate["discipline"]) if rate["count"] else "rating: none yet",
        "orders given: %d; certified bills: %d; work certified: %s" % (s["orders"], s["certified_bills"], inr(s["work_certified"])),
        "charged back: %s (still open: %s)" % (inr(s["back_charged"]), inr(s["back_charges_open"])),
        "concerns: %s" % ("; ".join(s["flags"]) or "none"),
    ])


@router.get("/api/ai/subcontracts/contractors/{contractor_id}/brief")
def contractor_brief(contractor_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    contractor = db.query(models.DBContractor).filter(models.DBContractor.id == contractor_id,
                                                      models.DBContractor.client_id == client.id).first()
    if not contractor:
        raise HTTPException(404, "Contractor not found")
    s = standing(db, client.id, contractor)
    out = {"standing": s, "summary": None, "ai": guard.status()}
    if not out["ai"]["available"]:
        return out
    facts = _facts(s)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Contractor brief %s" % contractor.company_name,
                               contractor.company_name, lambda: ask(SYSTEM, facts, smart=False, max_tokens=450))
    if result.ok:
        out["summary"], out["model"] = result.text, result.model
    else:
        out["ai_message"] = result.message
    return out
