"""The trial balance and the day book: the books as accounts reads them, before anything is sent to Tally.

Both are read from `tally.Books` - the same balanced vouchers (a list of ledger lines, debit positive, credit negative)
that the Tally export is made of - so what accounts checks here is exactly what Tally would be handed, and nothing is
kept twice. A voucher that did not balance is left out by `Books` with a warning; the warnings come through here too,
because a trial balance that silently dropped a voucher would be worse than none.

The trial balance is cumulative: a ledger's opening is everything booked before the period, then the period's debits and
credits, then the closing. With no start date the opening is nil and it runs from the first voucher.
"""
import re

from fastapi import HTTPException

from app.core.currency import money
from app.services import tally


def check_period(date_from, date_to):
    for d in (date_from, date_to):
        if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise HTTPException(400, "Dates as 2026-04-01.")
    if date_from and date_to and date_to < date_from:
        raise HTTPException(400, "The period ends before it starts.")
    return date_from or "", date_to or ""


def _dr_cr(net):
    """A signed balance as the debit and credit columns a trial balance shows: one of the two, never both."""
    return (money(net) if net > 0 else 0.0), (money(-net) if net < 0 else 0.0)


def trial_balance(db, client, date_from="", date_to=""):
    """Every ledger the books touch, with its opening, the period's debit and credit, and its closing; and whether the whole
    thing balances. Everything up to the end of the period is read once and split at the start date."""
    start = date_from or ""
    books = tally.Books(db, client, "", date_to)
    opening, debit, credit = {}, {}, {}
    vouchers = 0
    for v in books.vouchers:
        if v.get("action") == "Cancel":
            continue                              # a cancellation carries no lines: the voucher it cancels was never counted
        before = bool(start) and v["date"] < start
        vouchers += 0 if before else 1
        for line in v["lines"]:
            ledger, amount = line[0], line[1]
            if before:
                opening[ledger] = opening.get(ledger, 0.0) + amount
            elif amount > 0:
                debit[ledger] = debit.get(ledger, 0.0) + amount
            else:
                credit[ledger] = credit.get(ledger, 0.0) - amount

    rows = []
    for ledger in sorted(set(opening) | set(debit) | set(credit), key=lambda n: (books.ledgers.get(n, ("", False))[0], n.lower())):
        net_open = opening.get(ledger, 0.0)
        net_close = net_open + debit.get(ledger, 0.0) - credit.get(ledger, 0.0)
        open_dr, open_cr = _dr_cr(net_open)
        close_dr, close_cr = _dr_cr(net_close)
        rows.append({"ledger": ledger, "group": books.ledgers.get(ledger, ("", False))[0], "opening_dr": open_dr, "opening_cr": open_cr,
                     "debit": money(debit.get(ledger, 0.0)), "credit": money(credit.get(ledger, 0.0)),
                     "closing_dr": close_dr, "closing_cr": close_cr})

    def total(key, items=None):
        return money(sum(r[key] for r in (rows if items is None else items)))

    groups = []
    for name in dict.fromkeys(r["group"] for r in rows):
        mine = [r for r in rows if r["group"] == name]
        groups.append({"group": name, "ledgers": len(mine), **{k: total(k, mine) for k in ("opening_dr", "opening_cr", "debit", "credit", "closing_dr", "closing_cr")}})
    totals = {k: total(k) for k in ("opening_dr", "opening_cr", "debit", "credit", "closing_dr", "closing_cr")}
    # Each voucher balances on its own, so these agree by construction; they are checked and shown anyway, so that anything
    # that ever stopped being true (a voucher half written) shows here and not in the CA's Tally.
    difference = money(abs(totals["debit"] - totals["credit"]) + abs(totals["closing_dr"] - totals["closing_cr"])
                       + abs(totals["opening_dr"] - totals["opening_cr"]))
    books.date_from = start or "0000-00-00"       # what is left out is the period's, not everything since the first voucher
    return {"date_from": date_from, "date_to": date_to, "ledgers": rows, "groups": groups, "totals": totals, "vouchers": vouchers,
            "balanced": difference < 0.01, "difference": difference, "warnings": books.warnings, "left_out": books.left_out()}


def day_book(db, client, date_from, date_to):
    """The vouchers of a day (or a run of days), oldest first, each with its ledger lines, and what they add up to."""
    books = tally.Books(db, client, date_from, date_to)
    rows = books.rows()
    live = [v for v in rows if not v["cancelled"]]
    by_type = {}
    for v in live:
        t = by_type.setdefault(v["type"], {"type": v["type"], "count": 0, "amount": 0.0})
        t["count"] += 1
        t["amount"] = money(t["amount"] + v["amount"])
    debit = money(sum(l["debit"] for v in live for l in v["lines"]))
    credit = money(sum(l["credit"] for v in live for l in v["lines"]))
    return {"date_from": date_from, "date_to": date_to, "vouchers": rows, "warnings": books.warnings,
            "summary": {"count": len(live), "cancelled": len(rows) - len(live), "debit": debit, "credit": credit,
                        "types": sorted(by_type.values(), key=lambda t: t["type"])}}


def trial_balance_sheet(report, company):
    """(headers, rows, preamble, closing) for the workbook."""
    headers = ("Ledger", "Group", "Opening Dr", "Opening Cr", "Debit", "Credit", "Closing Dr", "Closing Cr")
    rows = [(r["ledger"], r["group"], r["opening_dr"] or "", r["opening_cr"] or "", r["debit"] or "", r["credit"] or "",
             r["closing_dr"] or "", r["closing_cr"] or "") for r in report["ledgers"]]
    t = report["totals"]
    preamble = [("TRIAL BALANCE", company or ""), ("Period", "%s to %s" % (report["date_from"] or "the first voucher", report["date_to"] or "today")), ()]
    closing = [(), ("Total", "", t["opening_dr"], t["opening_cr"], t["debit"], t["credit"], t["closing_dr"], t["closing_cr"]),
               ("Balanced" if report["balanced"] else "OUT OF BALANCE by %s" % report["difference"],)]
    return headers, rows, preamble, closing


def day_book_sheet(report, company):
    headers = ("Date", "Voucher", "Number", "Ledger", "Debit", "Credit", "Project", "Narration")
    rows = [(v["date"], v["type"] + (" (cancelled)" if v["cancelled"] else ""), v["number"], l["ledger"], l["debit"] or "", l["credit"] or "",
             v["project"], v["narration"]) for v in report["vouchers"] for l in (v["lines"] or [{"ledger": "", "debit": 0, "credit": 0}])]
    s = report["summary"]
    preamble = [("DAY BOOK", company or ""), ("Period", "%s to %s" % (report["date_from"], report["date_to"])), ()]
    closing = [(), ("Total", "", "", "", s["debit"], s["credit"]), ("Vouchers", s["count"])]
    return headers, rows, preamble, closing
