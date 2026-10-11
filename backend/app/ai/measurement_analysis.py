"""Read an order's measurement book for things that look wrong, and say what it shows in a few plain sentences.

The findings are plain code (`find_findings`) and work with or without an AI key. The model only words the summary from
those findings and the totals it is given.

    GET /api/ai/subcontracts/orders/{order_id}/measurement-analysis
"""
from datetime import datetime
from statistics import median

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai import guard
from app.ai.llm_client import ask
from app import models
from app.core.auth import require_erp_read
from app.core.currency import money
from app.db import get_db
from app.services.subcontract_billing import sub_order_or_404

router = APIRouter()

ACTION_KEY = "ai_measurement_analysis"

SYSTEM = (
    "You help a site engineer read a subcontract order's measurement book. You are given totals and a list of checks "
    "already worked out. Write at most five short sentences in plain English: how far the work has got, then the most "
    "important concerns first. Use only what you are given. Do not invent causes or advise paying or rejecting."
)


def _date(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def find_findings(items: list, entries: list, start: str, end: str, today) -> dict:
    """items: [{id, label, uom, quantity, rate, tolerance}]; entries: [{id, item_id, quantity, location, measured_on, kind}].
    Returns {findings: [{level, text}], rows: [per item], measured_value, ordered_value, time_percent, work_percent}."""
    findings, rows = [], []
    work = [e for e in entries if not e.get("kind")]
    by_item = {}
    for e in work:
        by_item.setdefault(e["item_id"], []).append(e)

    first, last = _date(start), _date(end)
    time_pct = None
    if first and last and last > first:
        time_pct = max(0.0, min(100.0, (today - first).days * 100.0 / (last - first).days))

    ordered_value = measured_value = 0.0
    for it in items:
        es = by_item.get(it["id"], [])
        measured = sum(e["quantity"] or 0 for e in es)
        ordered = it["quantity"] or 0
        rate = it["rate"] or 0
        ordered_value += ordered * rate
        measured_value += measured * rate
        pct = measured * 100.0 / ordered if ordered else None
        rows.append({"item_id": it["id"], "label": it["label"], "uom": it["uom"], "ordered": money(ordered),
                     "measured": money(measured), "percent": round(pct, 1) if pct is not None else None})
        allowed = ordered * (1 + (it["tolerance"] or 0) / 100.0)
        if ordered and measured > allowed + 1e-9:
            findings.append({"level": "stop", "text": "%s is measured %s against %s ordered (%s%% over). The order needs amending before more is measured." % (
                it["label"], money(measured), money(ordered), round((measured - ordered) * 100.0 / ordered, 1))})
        elif ordered and pct >= 95:
            findings.append({"level": "note", "text": "%s is %s%% measured: almost all of the ordered quantity." % (it["label"], round(pct, 1))})
        if not es and time_pct is not None and time_pct >= 50:
            findings.append({"level": "check", "text": "%s has nothing measured though %s%% of the order's time has passed." % (it["label"], round(time_pct))})
        qtys = [e["quantity"] for e in es if (e["quantity"] or 0) > 0]
        if len(qtys) >= 4:
            m = median(qtys)
            for e in es:
                if m > 0 and (e["quantity"] or 0) > 3 * m:
                    findings.append({"level": "check", "text": "%s: an entry of %s on %s is more than three times the usual %s. Check it was not mistyped." % (
                        it["label"], money(e["quantity"]), e.get("measured_on") or "an unknown date", money(m))})
        seen = {}
        for e in es:
            key = (e.get("location") or "", e.get("measured_on") or "", round(e["quantity"] or 0, 4))
            if e.get("location") and key in seen and (e["quantity"] or 0) != 0:
                findings.append({"level": "check", "text": "%s: %s measured twice on %s at %s. It may have been entered twice." % (
                    it["label"], money(e["quantity"]), e.get("measured_on") or "the same day", e["location"])})
            seen[key] = True
        for e in es:
            d = _date(e.get("measured_on"))
            if not e.get("measured_on"):
                findings.append({"level": "note", "text": "%s has an entry of %s with no date." % (it["label"], money(e["quantity"]))})
            elif d and d > today:
                findings.append({"level": "check", "text": "%s has an entry dated %s, which is in the future." % (it["label"], e["measured_on"])})
            elif d and first and d < first:
                findings.append({"level": "note", "text": "%s has an entry dated %s, before the order started on %s." % (it["label"], e["measured_on"], start)})
            if (e["quantity"] or 0) < 0 and ordered and abs(e["quantity"]) > ordered * 0.2:
                findings.append({"level": "check", "text": "%s has a correction of %s, over a fifth of the ordered quantity." % (it["label"], money(e["quantity"]))})

    work_pct = measured_value * 100.0 / ordered_value if ordered_value else None
    if work_pct is not None and time_pct is not None:
        if time_pct - work_pct >= 25:
            findings.append({"level": "check", "text": "Work is behind: %s%% of the order's value is measured with %s%% of the time gone." % (round(work_pct), round(time_pct))})
        elif work_pct - time_pct >= 25:
            findings.append({"level": "note", "text": "Work is ahead of time: %s%% of the value is measured with %s%% of the time gone." % (round(work_pct), round(time_pct))})
    order = {"stop": 0, "check": 1, "note": 2}
    findings.sort(key=lambda f: order[f["level"]])
    return {"findings": findings, "rows": rows, "measured_value": money(measured_value), "ordered_value": money(ordered_value),
            "time_percent": round(time_pct, 1) if time_pct is not None else None,
            "work_percent": round(work_pct, 1) if work_pct is not None else None}


@router.get("/api/ai/subcontracts/orders/{order_id}/measurement-analysis")
def measurement_analysis(order_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    order = sub_order_or_404(db, client.id, order_id)
    items = [{"id": i.id, "label": ((i.activity_no + " ") if i.activity_no else "") + (i.item_description or i.item_code or "Item")[:60],
              "uom": i.uom or "", "quantity": i.quantity or 0, "rate": i.unit_rate or 0, "tolerance": i.tolerance_percent or 0}
             for i in db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id,
                                                               models.DBSubcontractItem.is_header == False).all()]  # noqa: E712
    entries = [{"id": m.id, "item_id": m.item_id, "quantity": m.quantity or 0, "location": m.location or "",
                "measured_on": m.measured_on or "", "kind": m.kind or ""}
               for m in db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id == order.id).all()]
    out = find_findings(items, entries, order.commencement_date, order.completion_date, datetime.now().date())
    out.update({"order": order.wo_number or "", "entries": len(entries)})
    facts = ("Order %s. Ordered value %s, measured value %s (%s%% of value; %s%% of time passed). Checks:\n%s" % (
        order.wo_number, out["ordered_value"], out["measured_value"], out["work_percent"], out["time_percent"],
        "\n".join("- [%s] %s" % (f["level"], f["text"]) for f in out["findings"]) or "- none"))
    result = guard.run_feature(db, request, client, ACTION_KEY, "Measurement analysis %s" % order.wo_number, order.wo_number or "",
                               lambda: ask(SYSTEM, facts, smart=False, max_tokens=500))
    out.update({"available": result.ok, "summary": result.text if result.ok else "", "reason": result.reason,
                "message": result.message})
    return out
