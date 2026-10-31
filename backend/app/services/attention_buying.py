"""Buying, in "What needs you": the orders billed ahead of their goods, the deliveries that are late, the indent lines
nobody is buying for, and the drawings waiting for approval. Each is one item in the dashboard's shape (kind, severity,
value, count, view, title, detail), added beside the list services/projects.py builds; the morning digest carries them
too, with what is owed both ways and the cash in the banks.
"""
from datetime import date, datetime
from decimal import Decimal

from app import models
from app.core.currency import inr, money

LIVE_PO = ("Approved", "Awaiting Approval")


def _names(rows, n=3):
    shown = ", ".join(rows[:n])
    return shown + (" and %d more" % (len(rows) - n) if len(rows) > n else "")


def _day(raw):
    try:
        return datetime.strptime((raw or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def buying_items(db, client_id, today=None):
    today = today or date.today()
    from app.services.procurement import AHEAD_OF_GOODS, OrderPrefetch, match_verdict
    items = []
    orders = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id,
                                                     models.DBPurchaseOrder.status.notin_(("Cancelled", "Rejected", "Draft"))).all()
    pre = OrderPrefetch(db, orders) if orders else None

    # --- billed ahead of the goods (the three-way match's exceptions) ------------------------------------------------
    ahead, at_stake, late = [], 0.0, []
    for po in orders:
        lines = pre.lines.get(po.id, [])
        got = pre.received(po.id)
        ordered = money(sum((l.qty or 0) * (l.price or 0) for l in lines))
        received = money(sum(got.get(l.id, 0.0) * (l.price or 0) for l in lines))
        billed = pre.billed(po.id)["value"]
        verdict, _note = match_verdict(ordered, received, billed)
        if verdict in AHEAD_OF_GOODS:
            ahead.append(po.number or "PO")
            at_stake += billed - received
        # --- late: past its needed-by date with goods still to come --------------------------------------------------
        due = _day(po.needed_by)
        if po.status in LIVE_PO and due and due < today and any((l.qty or 0) - got.get(l.id, 0.0) > 0.001 for l in lines):
            late.append((po.number or "PO", po.supplier_name or "", (today - due).days))
    if ahead:
        items.append({"kind": "billed_ahead", "severity": "money", "value": money(at_stake), "count": len(ahead), "view": "bills-view",
                      "title": "Billed ahead of the goods",
                      "detail": "%s billed %s more than has been received. Do not pay until it is explained." % (_names(ahead), inr(at_stake))})
    if late:
        late.sort(key=lambda x: -x[2])
        items.append({"kind": "late_deliveries", "severity": "action", "value": 0.0, "count": len(late), "view": "purchase-orders-view",
                      "title": "Late deliveries",
                      "detail": "%d order%s past the needed-by date with goods still to come; %s (%s) is %d days late." % (
                          len(late), "" if len(late) == 1 else "s", late[0][0], late[0][1] or "the supplier", late[0][2])})

    # --- indent lines the store cannot fill and nobody is buying for --------------------------------------------------
    short = _unbought_indents(db, client_id)
    if short:
        items.append({"kind": "indents_unbought", "severity": "action", "value": 0.0, "count": len(short), "view": "indents-view",
                      "title": "Indents nobody is buying for",
                      "detail": "%s: the store cannot give %s from stock, and no enquiry or order is out for it." % (
                          _names(sorted(set(n for n, _l in short))), "these lines" if len(short) > 1 else "this line")})

    # --- drawings waiting for approval -------------------------------------------------------------------------------
    waiting = db.query(models.DBDrawing).filter(models.DBDrawing.client_id == client_id, models.DBDrawing.status == "For approval").all()
    if waiting:
        items.append({"kind": "drawings_for_approval", "severity": "action", "value": 0.0, "count": len(waiting), "view": "drawings-view",
                      "title": "Drawings waiting for approval",
                      "detail": "%s %s for approval." % (_names([d.number or d.title or "A drawing" for d in waiting]),
                                                         "is" if len(waiting) == 1 else "are")})
    return items


def _unbought_indents(db, client_id):
    """[(indent number, line id)] for approved, open indent lines still short after the store's spare stock and what is
    already on an enquiry or order - the same figure the indent's own page shows."""
    from app.models.store_outward import DBStoreIndent
    from app.routers.store_outward import _shortfall, _spare_stock
    from app.services import store_outward as svc
    from app.services.buying_links import on_order
    indents = db.query(DBStoreIndent).filter(DBStoreIndent.client_id == client_id, DBStoreIndent.status.in_(("OPEN", "PARTIAL"))).all()
    if not indents:
        return []
    buying, _by_item = on_order(db, client_id)
    out = []
    for indent in indents:
        if indent.short_closed:
            continue
        lines = svc.indent_lines(db, indent)
        done = svc.indent_fulfilled(db, indent)
        spare = _spare_stock(db, indent, lines)
        for l in lines:
            f = _shortfall(l, done, spare, buying.get(l.id))
            if f["short"] is not None and Decimal(f["short"]) > 0:
                out.append((indent.number or "Indent", l.id))
    return out


def with_buying(payload, items):
    """The dashboard's attention payload with the buying items added, its summary counted again."""
    every = list(payload.get("items") or []) + list(items)
    summary = dict(payload.get("summary") or {})
    summary.update({"items": len(every),
                    "money_at_stake": money(sum(i["value"] for i in every if i["severity"] == "money")),
                    "needs_a_decision": len([i for i in every if i["severity"] == "action"]),
                    "looks_wrong": len([i for i in every if i["severity"] == "wrong"])})
    return {**payload, "items": every, "summary": summary}


def money_lines(db, client):
    """The digest's opening lines: owed to us, owed by us, and the cash in every account together."""
    from app.routers.money import all_accounts_book, payables_payload, receivables_payload
    owed_in = receivables_payload(db, client)["summary"]
    owed_out = payables_payload(db, client)["summary"]
    opening, entries = all_accounts_book(db, client.id)
    cash = money(opening + sum((e.amount if e.direction == "IN" else -e.amount) for e in entries))
    return ["Owed to us: %s (%s overdue)." % (inr(owed_in["owed"]), inr(owed_in["overdue"])),
            "We owe: %s (%s overdue)." % (inr(owed_out["owed"]), inr(owed_out["overdue"])),
            "Cash in all accounts: %s." % inr(cash)]
