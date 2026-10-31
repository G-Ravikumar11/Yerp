"""The checks a subcontract has to pass before the business is committed to it, pays against it, or lets it go.

Each of these used to be a figure somebody could read and nothing more: a lapsed labour licence was a line of grey
text on the bill, a contractor given more of a BOQ line than the client ordered showed only on the tracker, a
retention release was owed the moment one person typed it. Here they are rules, in one place, each saying in words
what stands in the way and how to clear it.

Several can be overridden, and only by the Master, and only with a reason that is kept on the record: a lower
deduction certificate under section 197, a guarantee in hand in place of a licence being renewed. An approver who
is staff is told what is wrong and who can sign past it, never quietly let through.
"""
import math
import os
import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func

from app import models
from app.core.currency import format_money_plain, inr, money, unit_rate
from app.core.dates import _parse_date
from app.core.tenant_settings import tenant_setting

# The company's switch for refusing to approve, certify or pay a contractor whose required papers are missing or
# lapsed. On unless the Master turns it off in Settings > Approvals.
COMPLIANCE_BLOCKS_KEY = "contractor_compliance_blocks"

# How far ahead a bank guarantee's expiry is flagged.
BG_WARNING_DAYS = 30

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def _switch(name, default="1"):
    """A rule the test suite can switch off for the hundreds of tests that are about something else (it is switched
    back on in the tests that are about the rule itself)."""
    return (os.getenv(name, default) or default).strip().lower() not in ("0", "false", "no", "off")


def _today():
    return date.today()


def _iso(value):
    d = _parse_date(value or "")
    return d.isoformat() if d else ""


def _contractor(db, client_id, contractor_id):
    if not contractor_id:
        return None
    return db.query(models.DBContractor).filter(
        models.DBContractor.id == contractor_id, models.DBContractor.client_id == client_id).first()


# --- dates on an order ------------------------------------------------------------------------------------------

def checked_date(value, what):
    """A date as the forms send it (YYYY-MM-DD), or "" when none was given. Refused when it is not a date at all,
    rather than kept as text that prints, sorts and compares as nonsense."""
    text = (value or "").strip()
    if not text:
        return ""
    d = _parse_date(text)
    if d is None:
        raise HTTPException(400, "The %s should be a date (YYYY-MM-DD)." % what)
    return d.isoformat()


def check_order_dates(order):
    if order.commencement_date and order.completion_date and order.completion_date < order.commencement_date:
        raise HTTPException(400, "The completion date (%s) is before the commencement date (%s)."
                                 % (order.completion_date, order.commencement_date))


def owned_or_400(db, model, client_id, ident, what):
    """An id the form sent, checked to be one of this company's own. Another company's contractor or project on an
    order printed their PAN, GSTIN and address on ours."""
    if not ident:
        return None
    row = db.query(model).filter(model.id == ident, model.client_id == client_id).first()
    if row is None:
        raise HTTPException(400, "That %s is not on file." % what)
    return row.id


# --- TDS on contractors ----------------------------------------------------------------------------------------

def tds_enforced():
    return _switch("ENFORCE_STATUTORY_TDS")


def statutory_tds(con):
    """(rate, why) the Income Tax Act sets for paying this contractor, or (None, "") when there is nobody to ask about.

    Section 194C: 1% for an individual or HUF, 2% for anybody else. Section 206AA: 20% where the payee has given no
    PAN. The PAN says which it is - its fourth letter is P for a person and H for an HUF - so it is read from there
    rather than from the entity type typed on the form, which is free text.
    """
    if con is None:
        return None, ""
    pan = (con.pan or "").strip().upper()
    if not PAN_PATTERN.match(pan):
        return 20.0, "there is no valid PAN on file, so section 206AA applies"
    if pan[3] in ("P", "H"):
        return 1.0, "the PAN is an individual's or an HUF's (section 194C)"
    return 2.0, "the PAN is a firm's or a company's (section 194C)"


def tds_shortfall(db, order):
    """Words for an order that deducts less TDS than the law asks of this contractor, or None."""
    if not tds_enforced() or not order.contractor_id:
        return None
    con = _contractor(db, order.client_id, order.contractor_id)
    rate, why = statutory_tds(con)
    if rate is None or (order.tds_rate or 0) + 1e-9 >= rate:
        return None
    return "TDS on %s is %g%% - %s - but this order deducts %g%%." % (con.company_name, rate, why, order.tds_rate or 0)


# --- the contractor's papers -----------------------------------------------------------------------------------

def compliance_enforced(db, client_id):
    return _switch("REQUIRE_CONTRACTOR_COMPLIANCE") and \
        (tenant_setting(db, client_id, COMPLIANCE_BLOCKS_KEY, "1") or "1") != "0"


def compliance_problems(db, client_id, contractor_id):
    """What has lapsed among the papers a contractor holds. A document not on record is optional and stops nothing;
    one running out soon is a warning, not a reason to stop."""
    if not contractor_id or not compliance_enforced(db, client_id):
        return []
    from app.services.compliance import contractor_compliance
    verdict = contractor_compliance(db, client_id, contractor_id)
    if verdict["ok"]:
        return []
    return [w for w in verdict["warnings"] if "runs out in" not in w and "is not on record" not in w]


def compliance_gate(db, client_id, contractor_id, actor_id, reason, doing):
    """Stop `doing` for a contractor whose papers are not in order, unless it is the Master giving a reason.

    Returns the note to keep on the record when the Master signed past it, "" when nothing stood in the way."""
    problems = compliance_problems(db, client_id, contractor_id)
    if not problems:
        return ""
    con = _contractor(db, client_id, contractor_id)
    name = con.company_name if con else "This contractor"
    if actor_id is None and (reason or "").strip():
        return "%s despite: %s Reason: %s" % (doing[0].upper() + doing[1:], " ".join(problems), reason.strip())
    raise HTTPException(409, "%s cannot be %s yet: %s Put the documents on file under Compliance, %s." % (
        name, doing, " ".join(problems),
        "or give a reason to go ahead regardless" if actor_id is None
        else "or ask the Master, who can go ahead with a reason"))


def registration_missing(con):
    """What a contractor's registration form still lacks before it can be approved: they are paid on what it says."""
    missing = []
    if not PAN_PATTERN.match((con.pan or "").strip().upper()):
        missing.append("a valid PAN")
    if not (con.bank_account or "").strip():
        missing.append("the bank account number")
    if not (con.bank_ifsc or "").strip():
        missing.append("the IFSC")
    return missing


# --- what has been billed on an order --------------------------------------------------------------------------

def billed_qty_by_item(db, order_id):
    """{item id: quantity billed on live bills, less what credit notes took back}."""
    from app.services.credit_notes import credited_qty_by_item
    rows = db.query(models.DBSubBillLine.item_id, func.coalesce(func.sum(models.DBSubBillLine.this_bill_qty), 0.0)).join(
        models.DBSubBill, models.DBSubBill.id == models.DBSubBillLine.sub_bill_id).filter(
        models.DBSubBill.order_id == order_id, models.DBSubBill.status != "CANCELLED").group_by(
        models.DBSubBillLine.item_id).all()
    out = {item_id: float(qty or 0) for item_id, qty in rows if item_id}
    for item_id, qty in credited_qty_by_item(db, "contractor", order_id).items():
        if item_id in out:
            out[item_id] = max(0.0, out[item_id] - qty)
    return out


def closed_spend_by_budget(db, client_id, exclude_order_id=None):
    """{budget id: rupees} that closed orders actually spent - what was billed on them, not what was ordered."""
    q = db.query(models.DBSubcontractOrder.id).filter(
        models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractOrder.status == "CLOSED")
    if exclude_order_id:
        q = q.filter(models.DBSubcontractOrder.id != exclude_order_id)
    out = {}
    for (order_id,) in q.all():
        billed = billed_qty_by_item(db, order_id)
        for it in db.query(models.DBSubcontractItem).filter(
                models.DBSubcontractItem.order_id == order_id, models.DBSubcontractItem.budget_id.isnot(None)).all():
            spent = money(billed.get(it.id, 0.0) * (it.unit_rate or 0))
            if spent:
                out[it.budget_id] = money(out.get(it.budget_id, 0.0) + spent)
    return out


def closed_order_billed_value(db, order):
    """What a closed order is worth now: the work billed on it."""
    billed = billed_qty_by_item(db, order.id)
    return money(sum(billed.get(it.id, 0.0) * (it.unit_rate or 0) for it in db.query(models.DBSubcontractItem).filter(
        models.DBSubcontractItem.order_id == order.id).all()))


# --- the BOQ -----------------------------------------------------------------------------------------------------

def _given_elsewhere(db, client_id, keys, order):
    """{boq key: quantity} given to contractors on other orders that are committed - approved, executed or, for a
    closed one, what was billed. The order this one revises is left out: the revision stands for it."""
    if not keys:
        return {}
    from app.services.boq import boq_items_naming, boq_shares_of
    rows = db.query(models.DBSubcontractItem, models.DBSubcontractOrder).join(
        models.DBSubcontractOrder, models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id).filter(
        models.DBSubcontractOrder.client_id == client_id,
        models.DBSubcontractOrder.id != order.id,
        models.DBSubcontractOrder.status.in_(("PROVISIONAL", "APPROVED", "EXECUTED", "CLOSED")),
        boq_items_naming(db, keys)).all()
    skip = {order.supersedes_id} if order.supersedes_id else set()
    # Another revision waiting for approval stands for its predecessor as well.
    skip |= {r[0] for r in db.query(models.DBSubcontractOrder.supersedes_id).filter(
        models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractOrder.id != order.id,
        models.DBSubcontractOrder.supersedes_id.isnot(None),
        models.DBSubcontractOrder.status.in_(("PROVISIONAL", "APPROVED", "EXECUTED", "CLOSED"))).all()}
    billed_cache = {}
    out = {}
    for it, o in rows:
        if o.id in skip:
            continue
        if o.status == "CLOSED":
            if o.id not in billed_cache:
                billed_cache[o.id] = billed_qty_by_item(db, o.id)
            qty = billed_cache[o.id].get(it.id, 0.0)
        else:
            qty = it.quantity or 0
        for key, share in boq_shares_of(it):
            if key in keys:
                out[key] = out.get(key, 0.0) + qty * share
    return out


def boq_breaches(db, order):
    """What approving this order would do to the project's BOQ, in words an approver can act on: lines given to
    contractors past the quantity the client ordered, and lines given at a higher rate than the client pays."""
    if not order.job_id:
        return []
    from app.services.boq import boq_line_label, boq_lines_of_job, boq_shares_of
    boq = {l.key: l for l in boq_lines_of_job(db, order.client_id, order.job_id)}
    if not boq:
        return []
    mine = {}
    rates = {}
    for it in db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id).all():
        if it.is_header:
            continue
        # A heading total gives each of its BOQ lines its share, all at the one contractor rate.
        for key, share in boq_shares_of(it):
            if key not in boq:
                continue
            mine[key] = mine.get(key, 0.0) + (it.quantity or 0) * share
            rates[key] = max(rates.get(key, 0.0), unit_rate(it.unit_rate or 0))
    given = _given_elsewhere(db, order.client_id, set(mine), order)
    out = []
    for key, qty in mine.items():
        line = boq[key]
        total = money(given.get(key, 0.0) + qty)
        if (line.quantity or 0) > 0 and total > money(line.quantity) + 0.0001:
            out.append("%s: %s would be given to contractors against %s in the BOQ" % (
                boq_line_label(line), total, money(line.quantity)))
        if (line.rate or 0) > 0 and rates.get(key, 0.0) > unit_rate(line.rate) + 0.0001:
            out.append("%s: the contractor's rate %s is above the client's %s - a loss on every unit" % (
                boq_line_label(line), rates[key], unit_rate(line.rate)))
    return out


def bill_boq_overbilling(db, bill):
    """Lines of this bill that take what contractors have been billed for, across every order, past the quantity in
    the project's BOQ - work the client will never pay for."""
    from app.services.boq import boq_items_naming, boq_line_label, boq_lines_of_job, boq_shares_of
    if not bill.job_id:
        return []
    boq = {l.key: l for l in boq_lines_of_job(db, bill.client_id, bill.job_id)}
    if not boq:
        return []
    items = {it.id: it for it in db.query(models.DBSubcontractItem).join(
        models.DBSubBillLine, models.DBSubBillLine.item_id == models.DBSubcontractItem.id).filter(
        models.DBSubBillLine.sub_bill_id == bill.id).all()}
    keys = {k for it in items.values() for k, _ in boq_shares_of(it) if k in boq}
    if not keys:
        return []
    totals = {}
    rows = db.query(models.DBSubcontractItem, models.DBSubcontractOrder).join(
        models.DBSubcontractOrder, models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id).filter(
        models.DBSubcontractOrder.client_id == bill.client_id, boq_items_naming(db, keys)).all()
    billed_cache = {}
    for it, o in rows:
        if o.id not in billed_cache:
            billed_cache[o.id] = billed_qty_by_item(db, o.id)
        for key, share in boq_shares_of(it):
            if key in keys:
                totals[key] = totals.get(key, 0.0) + billed_cache[o.id].get(it.id, 0.0) * share
    out = []
    for key in sorted(keys):
        line = boq[key]
        if (line.quantity or 0) > 0 and money(totals.get(key, 0.0)) > money(line.quantity) + 0.0001:
            out.append("%s: %s billed by contractors against %s in the BOQ" % (
                boq_line_label(line), money(totals[key]), money(line.quantity)))
    return out


# --- the mobilisation advance ----------------------------------------------------------------------------------

def advance_outstanding(db, order):
    """The part of the mobilisation advance paid to the contractor that no bill has taken back yet."""
    from app.services.crm import advance_paid
    paid = money(advance_paid(db, order.client_id, order.id))
    if paid <= 0:
        return 0.0
    recovered = money(sum((b.advance_recovery or 0) for b in db.query(models.DBSubBill).filter(
        models.DBSubBill.order_id == order.id, models.DBSubBill.status != "CANCELLED").all()))
    return money(max(0.0, paid - recovered))


# --- liquidated damages ----------------------------------------------------------------------------------------

def ld_due(db, order, bill):
    """The liquidated damages this bill should carry: the agreed share of the order value for every week (or part)
    the work has run past the completion date, up to the cap, less what earlier bills already took."""
    rate = order.ld_percent_per_week or 0
    due_on = _parse_date(order.completion_date or "")
    if rate <= 0 or due_on is None:
        return 0.0, ""
    as_of = _parse_date(order.actual_completion_date or "") or _parse_date(bill.period_to or "") \
        or _parse_date(bill.bill_date or "") or _today()
    late = (as_of - due_on).days
    if late <= 0:
        return 0.0, ""
    weeks = int(math.ceil(late / 7.0))
    value = money(order.gross_amount or 0)
    worked = money(value * rate / 100.0 * weeks)
    cap = money(value * (order.ld_cap_percent or 0) / 100.0) if (order.ld_cap_percent or 0) > 0 else value
    taken = money(sum((b.ld_amount or 0) for b in db.query(models.DBSubBill).filter(
        models.DBSubBill.order_id == order.id, models.DBSubBill.id != bill.id,
        models.DBSubBill.status != "CANCELLED").all()))
    amount = money(max(0.0, min(worked, cap) - taken))
    why = "%d day%s past the completion date of %s: %d week%s at %g%% of %s%s" % (
        late, "" if late == 1 else "s", due_on.isoformat(), weeks, "" if weeks == 1 else "s", rate,
        format_money_plain(value), (", capped at %g%%" % order.ld_cap_percent) if (order.ld_cap_percent or 0) > 0 else "")
    if taken:
        why += ", less %s taken on earlier bills" % format_money_plain(taken)
    return amount, why


# --- closing an order ------------------------------------------------------------------------------------------

def close_blockers(db, order):
    """What has to be finished before an order can be closed. The unrecovered advance is reported separately: the
    Master may close past it with a reason (it is then owed back by the contractor outside the bills)."""
    out = []
    open_bills = [b.number for b in db.query(models.DBSubBill).filter(
        models.DBSubBill.order_id == order.id, models.DBSubBill.status.in_(("DRAFT", "SUBMITTED"))).all()]
    if open_bills:
        out.append("%s %s still open - certify or cancel %s first." % (
            ", ".join(open_bills), "is" if len(open_bills) == 1 else "are", "it" if len(open_bills) == 1 else "them"))
    pending = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.supersedes_id == order.id,
        models.DBSubcontractOrder.status.in_(("DRAFT", "PROVISIONAL"))).first()
    if pending:
        out.append("%s is amending it - finish or cancel the revision first." % pending.wo_number)
    charges = db.query(models.DBBackCharge).filter(
        models.DBBackCharge.client_id == order.client_id, models.DBBackCharge.order_id == order.id,
        models.DBBackCharge.status == "OPEN").all()
    if charges:
        out.append("%s in back-charges on it %s open - take them on the final bill, or cancel them." % (
            inr(sum(c.amount or 0 for c in charges)), "is" if len(charges) == 1 else "are"))
    from app.services.subcontract_billing import sub_measured_to_date
    measured = sub_measured_to_date(db, order.id)
    billed = billed_qty_by_item(db, order.id)
    unbilled = [it for it in db.query(models.DBSubcontractItem).filter(
        models.DBSubcontractItem.order_id == order.id).all()
        if money(measured.get(it.id, 0.0)) > money(billed.get(it.id, 0.0)) + 0.0001]
    if unbilled:
        out.append("Work is measured and not billed on %s. Raise the final bill, or remove those entries." % ", ".join(
            (it.activity_no or (it.item_description or "")[:30]) for it in unbilled[:5]))
    return out


# --- retention released to a contractor -------------------------------------------------------------------------

def retention_blockers(db, client_id, pos, stage, today=None):
    """Why a contractor's retention should not be released yet: the defects period still running (for the release
    at its end), back-charges not yet taken from them, advance not yet recovered, or a quality issue on the site in
    their name still open."""
    today = today or _today()
    out = []
    order = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id == pos["order_id"], models.DBSubcontractOrder.client_id == client_id).first()
    if order is None:
        return out
    if stage == "End of defects period" and pos.get("dlp_ends") and pos["dlp_ends"] > today.isoformat():
        out.append("The defects period on %s runs to %s." % (order.wo_number, pos["dlp_ends"]))
    charges = db.query(models.DBBackCharge).filter(
        models.DBBackCharge.client_id == client_id, models.DBBackCharge.status == "OPEN",
        models.DBBackCharge.contractor_id == order.contractor_id).all()
    charges = [c for c in charges if c.order_id in (None, order.id)]
    if charges:
        out.append("%s in back-charges %s still open (%s)." % (
            inr(sum(c.amount or 0 for c in charges)), "is" if len(charges) == 1 else "are",
            ", ".join(c.number for c in charges[:5])))
    owed = advance_outstanding(db, order)
    if owed > 0:
        out.append("%s of the mobilisation advance has not been recovered." % inr(owed))
    con = _contractor(db, client_id, order.contractor_id)
    if con and order.job_id and (con.company_name or "").strip():
        name = con.company_name.strip().lower()
        ncrs = [n.number for n in db.query(models.DBNcr).filter(
            models.DBNcr.client_id == client_id, models.DBNcr.job_id == order.job_id,
            models.DBNcr.status.notin_(("CLOSED", "REJECTED"))).all() if name in (n.responsible or "").lower()]
        if ncrs:
            out.append("Quality issues in their name are open on the site: %s." % ", ".join(ncrs[:5]))
    return out


# --- bank guarantees -------------------------------------------------------------------------------------------

def bg_state(validity, returned_at="", today=None):
    """returned | expired | expiring | valid | undated."""
    if returned_at:
        return "returned"
    d = _parse_date(validity or "")
    if d is None:
        return "undated"
    today = today or _today()
    if d < today:
        return "expired"
    if (d - today).days <= BG_WARNING_DAYS:
        return "expiring"
    return "valid"


def bank_guarantee_rows(db, client_id, today=None):
    """Every guarantee a live or closed order carries, with where it stands."""
    today = today or _today()
    orders = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.client_id == client_id,
        models.DBSubcontractOrder.bank_guarantee_applicable.is_(True),
        models.DBSubcontractOrder.status.in_(("PROVISIONAL", "APPROVED", "EXECUTED", "CLOSED"))).order_by(
        models.DBSubcontractOrder.bank_guarantee_validity).all()
    rows = []
    for o in orders:
        con = _contractor(db, client_id, o.contractor_id)
        job = db.query(models.DBJob).filter(models.DBJob.id == o.job_id).first() if o.job_id else None
        d = _parse_date(o.bank_guarantee_validity or "")
        rows.append({
            "order_id": o.id, "wo_number": o.wo_number or "", "status": o.status,
            "contractor": con.company_name if con else "",
            "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "number": o.bank_guarantee_number or "", "bank": o.bank_guarantee_bank or "",
            "amount": money(o.bank_guarantee_amount), "valid_to": o.bank_guarantee_validity or "",
            "days_left": (d - today).days if d else None,
            "returned_at": o.bank_guarantee_returned_at or "",
            "state": bg_state(o.bank_guarantee_validity, o.bank_guarantee_returned_at, today),
        })
    return rows


def bank_guarantee_missing(order):
    """What a guarantee the order says it carries still lacks before the order goes for approval."""
    if not order.bank_guarantee_applicable:
        return []
    out = []
    if money(order.bank_guarantee_amount or 0) <= 0:
        out.append("the bank guarantee amount")
    if not _parse_date(order.bank_guarantee_validity or ""):
        out.append("the date the bank guarantee is valid to")
    elif order.completion_date and order.bank_guarantee_validity < order.completion_date:
        out.append("a bank guarantee valid at least to the completion date (%s; it runs out on %s)" % (
            order.completion_date, order.bank_guarantee_validity))
    return out


# --- what needs looking at -------------------------------------------------------------------------------------

def subcontract_attention(db, client_id, today=None):
    """The subcontract side of the Monday-morning list: guarantees about to lapse, advances paid and never taken
    back, and contractors with live orders whose papers have lapsed."""
    today = today or _today()
    items = []
    bgs = [r for r in bank_guarantee_rows(db, client_id, today)
           if r["state"] in ("expired", "expiring") and r["status"] != "CLOSED"]
    if bgs:
        expired = [r for r in bgs if r["state"] == "expired"]
        items.append({
            "kind": "bank_guarantees", "severity": "wrong" if expired else "action",
            "value": money(sum(r["amount"] for r in bgs)), "count": len(bgs), "view": "registers-view",
            "title": "Bank guarantees lapsing",
            "detail": "%d guarantee%s on live orders %s - have %s extended before %s." % (
                len(bgs), "" if len(bgs) == 1 else "s",
                "ha%s run out or run%s out within %d days" % ("ve" if len(bgs) > 1 else "s", "" if len(bgs) > 1 else "s",
                                                             BG_WARNING_DAYS),
                "them" if len(bgs) > 1 else "it", "they run out" if len(bgs) > 1 else "it runs out"),
        })
    owed_orders = []
    for o in db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client_id,
            models.DBSubcontractOrder.mobilization_advance_amount > 0,
            models.DBSubcontractOrder.status.in_(("APPROVED", "EXECUTED", "CLOSED"))).all():
        late = o.status == "CLOSED" or (o.completion_date and o.completion_date < today.isoformat())
        if not late:
            continue
        owed = advance_outstanding(db, o)
        if owed > 0:
            owed_orders.append((o, owed))
    if owed_orders:
        items.append({
            "kind": "advance_unrecovered", "severity": "money",
            "value": money(sum(x for _, x in owed_orders)), "count": len(owed_orders), "view": "subcontracts-view",
            "title": "Advances not recovered",
            "detail": "%s of mobilisation advance is still with contractors on %d order%s that %s finished: %s." % (
                inr(sum(x for _, x in owed_orders)), len(owed_orders), "" if len(owed_orders) == 1 else "s",
                "are" if len(owed_orders) > 1 else "is", ", ".join(o.wo_number for o, _ in owed_orders[:4])),
        })
    if compliance_enforced(db, client_id):
        live = {r[0] for r in db.query(models.DBSubcontractOrder.contractor_id).filter(
            models.DBSubcontractOrder.client_id == client_id,
            models.DBSubcontractOrder.status.in_(("APPROVED", "EXECUTED"))).all() if r[0]}
        lapsed = [cid for cid in live if compliance_problems(db, client_id, cid)]
        if lapsed:
            names = [c.company_name for c in db.query(models.DBContractor).filter(
                models.DBContractor.id.in_(lapsed)).all()]
            items.append({
                "kind": "contractor_papers", "severity": "wrong", "value": 0.0, "count": len(lapsed),
                "view": "compliance-view", "title": "Contractors who cannot be paid",
                "detail": "%d contractor%s on live orders %s papers missing or lapsed, so %s bills cannot be certified "
                          "or paid: %s." % (len(lapsed), "" if len(lapsed) == 1 else "s",
                                            "have" if len(lapsed) > 1 else "has", "their",
                                            ", ".join(sorted(names)[:4])),
            })
    return items


