"""A recommendation on an enquiry's supplier quotes: who to award, and why.

The figures (landed cost per supplier, the lowest rate per line, what a split award would save) already come from the
comparative statement, which is plain code. Here, plain code adds flags (a quote that is incomplete, out of date, much
dearer on a line than the best) and the model words a recommendation from them. A person awards; nothing is awarded here.

    GET /api/ai/rfqs/{rfq_id}/recommend
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai import guard
from app.ai.llm_client import ask
from app.core.auth import require_erp_read
from app.core.currency import inr
from app.db import get_db
from app.services.procurement import comparative_statement, rfq_or_404

router = APIRouter()

ACTION_KEY = "ai_quote_recommend"
BIG_SPREAD = 25.0         # a line where the dearest quote is 25% above the cheapest is worth a question

SYSTEM = (
    "You help a construction company's buyer choose between supplier quotes. You are given each supplier's landed "
    "cost (basic, tax and freight), delivery and payment terms, and checks already worked out. Recommend who to award "
    "in at most five short sentences: name the supplier, give the reasons that matter (price, completeness, delivery, "
    "terms), and say what to confirm before awarding. Use only the numbers given. Never invent a price or term."
)


def find_flags(statement: dict, today=None) -> list:
    today = (today or date.today()).isoformat()
    flags = []
    suppliers = statement.get("suppliers") or []
    if len(suppliers) < 2:
        flags.append({"level": "check", "text": "Only %d quote(s) so far; a comparison needs at least two." % len(suppliers)})
    for s in suppliers:
        if not s["complete"]:
            flags.append({"level": "check", "text": "%s quoted only %d of the lines, so their total is not comparable." % (s["supplier_name"], s["lines_quoted"])})
        if s.get("valid_until") and s["valid_until"] < today:
            flags.append({"level": "stop", "text": "%s's quote expired on %s." % (s["supplier_name"], s["valid_until"])})
    for l in statement.get("lines") or []:
        if l["spread_percent"] >= BIG_SPREAD and len(l["offers"]) > 1:
            flags.append({"level": "check", "text": "%s: the dearest quote is %s%% above the cheapest (%s by %s)." % (
                l["description"], l["spread_percent"], inr(l["lowest_rate"]), l["lowest"])})
    l1 = statement.get("l1")
    split = statement.get("lowest_per_line_basic") or 0
    l1_basic = next((s["basic"] for s in suppliers if s["supplier_name"] == l1), 0)
    if l1 and split and l1_basic - split > 0.5:
        flags.append({"level": "note", "text": "Taking the cheapest rate on every line from different suppliers would cost %s less in basic value than awarding %s alone." % (inr(l1_basic - split), l1)})
    return flags


def _facts(statement: dict, flags: list) -> str:
    lines = ["enquiry: %s %s" % (statement["rfq"]["number"], statement["rfq"]["title"]), "lines: %d" % len(statement["lines"])]
    for s in statement["suppliers"]:
        lines.append("supplier %s: landed %s (basic %s, tax %s, freight %s), %s, delivery %s days, payment: %s, valid until %s%s" % (
            s["supplier_name"], inr(s["landed"]), inr(s["basic"]), inr(s["tax"]), inr(s["freight"]), s.get("rank") or "not ranked",
            s["delivery_days"] or "not stated", s["payment_terms"] or "not stated", s["valid_until"] or "not stated",
            "" if s["complete"] else ", INCOMPLETE"))
    lines.append("checks:")
    lines += ["- [%s] %s" % (f["level"], f["text"]) for f in flags] or ["- none raised"]
    return "\n".join(lines)


@router.get("/api/ai/rfqs/{rfq_id}/recommend")
def recommend(rfq_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    statement = comparative_statement(db, rfq_or_404(db, client.id, rfq_id))
    flags = find_flags(statement)
    out = {"l1": statement["l1"], "l1_landed": statement["l1_landed"], "flags": flags, "recommendation": None, "ai": guard.status()}
    if not statement["suppliers"] or not out["ai"]["available"]:
        return out
    facts = _facts(statement, flags)
    result = guard.run_feature(db, request, client, ACTION_KEY, "Quote recommendation %s" % statement["rfq"]["number"],
                               statement["rfq"]["number"], lambda: ask(SYSTEM, facts, smart=True, max_tokens=500))
    if result.ok:
        out["recommendation"], out["model"] = result.text, result.model
    else:
        out["ai_message"] = result.message
    return out
