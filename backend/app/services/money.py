"""The rules and workings behind the money endpoints."""
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models

from app.constants.money import AGEING_BUCKETS, COST_CATEGORIES, COST_CATEGORY_ALIASES, COST_CATEGORY_KEYS
from app.core.currency import DEFAULT_CURRENCY, inr, money
from app.core.tenant_settings import tenant_setting

# The day the money books are closed up to: nothing - a receipt, a payment, a transfer, a void - may be dated on or before
# it. Set by the Master alone, like the store's own lock.
MONEY_LOCK_KEY = "money_books_locked_upto"
# A payment may be entered for tomorrow at the latest (a cheque written tonight, dated in the morning); further ahead
# is a typing mistake that would sit in next year's books.
MAX_DAYS_AHEAD = 1


def _dmy(iso):
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return iso or ""


def money_locked_upto(db, client_id) -> str:
    """The day the money books are closed up to (YYYY-MM-DD), or "" when they are open."""
    v = str(tenant_setting(db, client_id, MONEY_LOCK_KEY, "") or "").strip()[:10]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else ""


def refuse_if_locked(db, client_id, on, doing="entered"):
    """409 when `on` falls in the closed period."""
    upto = money_locked_upto(db, client_id)
    day = (on or "")[:10]
    if upto and day and day <= upto:
        raise HTTPException(409, "The money books are closed up to %s, so nothing dated %s can be %s. "
                                 "The Master can reopen the period." % (_dmy(upto), _dmy(day), doing))


def entry_date(raw, label="The date"):
    """A money entry's date: a real YYYY-MM-DD day, today when left blank, and not more than a day ahead."""
    s = (raw or "").strip()[:10]
    if not s:
        return date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % label)
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s is not a date (use YYYY-MM-DD)." % label) from None
    if d > date.today() + timedelta(days=MAX_DAYS_AHEAD):
        raise HTTPException(400, "%s %s is still to come; money is entered on the day it moves." % (label, _dmy(s)))
    return d.isoformat()


def _cheque_key(reference):
    ref = re.sub(r"\s+", "", (reference or "")).upper()
    return (ref.lstrip("0") or "0") if ref.isdigit() else ref


def refuse_duplicate_cheque(db, client_id, account_id, reference):
    """A cheque is written once: a second live payment by the same cheque number from the same account is refused."""
    key = _cheque_key(reference)
    if not key:
        return
    q = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.mode == "Cheque",
        models.DBMoneyEntry.direction == "OUT", models.DBMoneyEntry.voided.is_(False),
        (models.DBMoneyEntry.account_id == account_id) if account_id else models.DBMoneyEntry.account_id.is_(None))
    for e in q.all():
        if _cheque_key(e.reference) == key:
            raise HTTPException(409, "Cheque %s is already entered as %s (%s to %s, %s). A cheque is paid once; "
                                     "if that entry is wrong, void it first."
                                     % ((reference or "").strip(), e.number, inr(e.amount), e.party_name or "",
                                        _dmy(e.paid_on or "")))


def base_currency(client) -> str:
    """The currency a business keeps its books in. Bills carry no currency of
    their own, so they are always this one."""
    return ((client.currency or "") or DEFAULT_CURRENCY).upper()


def invoices_by_currency(invoices, base: str) -> dict:
    """Group invoices by the currency they were issued in.

    Every report below reports one currency at a time. Adding GBP to INR needs
    an exchange rate we do not have, and inventing one puts a made-up figure in
    front of somebody making decisions with it - which is exactly how the sales
    pipeline once showed a total in the trillions.
    """
    groups = {}
    for inv in invoices:
        code = ((inv.currency or "") or base).upper() or base
        groups.setdefault(code, []).append(inv)
    return groups


def cost_category_of(raw) -> str:
    key = (raw or "").strip().lower()
    if key in COST_CATEGORY_KEYS:
        return key
    return COST_CATEGORY_ALIASES.get(key, "other")


def job_money(db, client_id, job, pre=None):
    """One project's money, from every direction it moves in.

    Three quantities, kept apart on purpose because they answer different
    questions and mixing them is how a job looks fine until it is finished:

      incurred    - bills that have arrived, plus the hours worked on site
      committed   - purchase and subcontract orders placed but not yet billed
      forecast    - what the whole job is expected to cost by the end

    A purchase order drops out of `committed` the moment a bill references it,
    so the same spend is never counted in both.
    """
    pre = pre or preload_pnl_for_job(db, client_id, job.id)
    wos = pre["wos"].get(job.id, [])
    live_wos = [w for w in wos if (w.approval_status or "none") != "rejected"]
    wo_ids = [w.id for w in live_wos]

    sold = money(sum(w.total_value or 0 for w in live_wos))
    budgeted = money(sum(pre["bom"].get(i, 0.0) for i in wo_ids)) if wo_ids else 0.0

    # --- what has actually been incurred ---------------------------------
    bills = pre["bills"].get(job.id, [])
    real_bills = [b for b in bills
                  if (b.approval_status or "none") != "rejected"
                  and (b.status or "") != "Cancelled"]
    billed = money(sum(b.total or b.amount or 0 for b in real_bills))
    paid = money(sum(b.amount_paid or 0 for b in real_bills))
    awaiting = len([b for b in bills if (b.approval_status or "") == "pending"])

    attendance = pre["attendance"].get(job.id, [])
    rates = hourly_rates(db, client_id) if attendance else {}
    labour_hours = round(sum(a.total_hours or 0.0 for a in attendance), 2)
    staff_time = money(sum((a.total_hours or 0.0) * rates.get(a.employee_id, 0.0)
                           for a in attendance))

    # What the site has actually cost, taken from the project's profit
    # account so the two screens say the same thing: this one read only
    # supplier bills and clock-in hours, and a job with a contractor bill, a signed
    # diary and cement issued from the store showed nothing incurred at all.
    pnl = project_pnl(db, client_id, job, pre=pre)
    c = pnl["cost"]
    labour = money(c["labour"] + staff_time)
    incurred = money(c["incurred"] + staff_time)

    # --- what is promised on top of it -----------------------------------
    pos = pre["pos"].get(job.id, [])
    # Once a bill names the order, the spend is in `incurred`. Leaving the
    # order in as well counted it twice and made every project look worse the
    # closer it got to finishing.
    billed_po_ids = {b.purchase_order_id for b in real_bills if b.purchase_order_id}
    open_pos = [p for p in pos
                if (p.status or "") not in ("Cancelled", "Rejected", "Closed")
                and p.id not in billed_po_ids]
    committed = money(sum(p.total or 0 for p in open_pos))

    subs = pre["subs"].get(job.id, [])
    # A closed order has nothing left to bill: what it never did is no longer a commitment.
    live_subs = [x for x in subs if (x.status or "") not in ("CANCELLED", "AMENDED", "CLOSED")]
    # What the contractors have still to bill. Their bills are incurred already;
    # counting the whole order on top counted every rupee billed twice.
    contractor_billed = {}
    for b in pre["sub"].get(job.id, []):
        contractor_billed[b.order_id] = money(contractor_billed.get(b.order_id, 0.0) + (b.this_bill or 0))
    # Work a credit note took back is not billed any more, so the order has that much left to bill.
    credits = pre.get("credits") or {}
    for order_id, taxable in (credits.get("sub_order") or {}).items():
        if order_id in contractor_billed:
            contractor_billed[order_id] = money(contractor_billed[order_id] - taxable)
    subcontracted = money(sum(max(0.0, (x.gross_amount or x.net_order_value or 0)
                                  - contractor_billed.get(x.id, 0.0)) for x in live_subs))

    commitment = money(committed + subcontracted)

    # --- where it ends up -------------------------------------------------
    # Estimate at completion. Work still to come has usually not been ordered
    # yet, so where the budget is higher than everything known about, the
    # budget is the better forecast; past that point the known cost is.
    known = money(incurred + commitment)
    budget = money(job.budget or 0)
    # Two different budgets exist and they are not interchangeable. The BOM is
    # the estimate built line by line from what the work actually takes, so
    # where there is one it is the better answer; the figure typed on the
    # project form is the fallback for a job that never had a BOM.
    estimate = budgeted or budget
    forecast_cost = money(max(known, estimate)) if estimate else known

    # Percent complete measured by cost, which is what a contract with no
    # milestone schedule can actually be measured by.
    percent_complete = round(incurred / forecast_cost * 100, 1) if forecast_cost else 0.0
    cost_to_complete = money(forecast_cost - incurred)

    # --- the customer side ------------------------------------------------
    invoices = [i for i in pre["invoices"].get(job.id, []) if (i.status or "") != "Void"]
    # Certified RA bills are this business's invoices; counting only the
    # invoice module left every project "not yet invoiced".
    ra = pre["ra"].get(job.id, [])
    settled = pre["settled"]
    ra_received = money(sum(
        (b.net_payable or 0) if (b.status == "PAID" and not settled.get(("ra_bill", b.id)))
        else settled.get(("ra_bill", b.id), 0.0) for b in ra))
    taken_ra = (credits.get("client_job") or {}).get(job.id, {})
    taken_net = credits.get("client_bill") or {}
    invoiced = money(sum(invoice_total(i) for i in invoices) + sum(b.this_bill or 0 for b in ra)
                     - taken_ra.get("taxable", 0.0))
    received = money(sum(i.paid or 0 for i in invoices) + ra_received)
    # What the client still owes is what each bill asks for less what came in
    # against it - the bill's net payable carries its GST, retention and TDS,
    # so "billed less received" mixed a figure before tax with cash after it.
    owed = money(sum(max(0.0, invoice_total(i) - (i.paid or 0)) for i in invoices)
                 + sum(max(0.0, (b.net_payable or 0) - taken_net.get(b.id, {}).get("net", 0.0)
                           - settled.get(("ra_bill", b.id), 0.0))
                       for b in ra if b.status == "CERTIFIED"))

    contract_value = sold or money(job.quoted_value or 0)
    # Revenue earned by the work done, against revenue actually invoiced. A
    # job billed ahead of its progress is borrowing from its own future.
    earned = money(contract_value * percent_complete / 100) if contract_value else 0.0
    retention_percent = float(job.retention_percent or 0)
    # Released retention is no longer held: it is a claim of its own, owed
    # until it is received.
    rels = pre["released"].get(job.id, [])
    retention_held = money(sum(invoice_total(i) for i in invoices) * retention_percent / 100
                           + sum(b.retention_amount or 0 for b in ra) - taken_ra.get("retention", 0.0)
                           - sum(r.amount or 0 for r in rels))
    received = money(received + sum(settled.get(("retention_release", r.id), 0.0) for r in rels))
    owed = money(owed + sum(max(0.0, (r.net_amount or 0) - settled.get(("retention_release", r.id), 0.0))
                            for r in rels if r.status == "CERTIFIED"))

    # --- cost by heading --------------------------------------------------
    by_category = {key: 0.0 for key in COST_CATEGORY_KEYS}
    by_category["labour"] = labour
    stocked = pre.get("stocked") or {}
    for b in real_bills:
        key = cost_category_of(b.category)
        by_category[key] = money(by_category[key]
                                 + (b.total or b.amount or 0) * (1.0 - stocked.get(b.id, 0.0)))
    by_category["materials"] = money(by_category["materials"] + c["material_from_store"]
                                     - c["material_recovered_from_contractors"])
    by_category["subcontract"] = money(by_category["subcontract"] + c["subcontractors"] + subcontracted)
    by_category["plant"] = money(by_category["plant"] + c["plant"] + c["equipment"])
    # Expense vouchers charged to the site (diesel, transport, sundries) are in incurred, so in the headings too.
    by_category["other"] = money(by_category["other"] + c.get("site_expenses", 0.0))
    for p in open_pos:
        by_category["materials"] = money(by_category["materials"] + (p.total or 0))

    return {
        "job_id": job.id, "number": job.number or "", "name": job.name or "",
        "customer_name": job.customer_name or "", "status": job.status or "",
        "quoted_value": money(job.quoted_value), "budget": budget,
        "sold": sold, "contract_value": contract_value, "budgeted_cost": budgeted,

        "committed": committed, "subcontracted": subcontracted,
        "commitment": commitment,
        "labour": labour, "labour_hours": labour_hours,
        "billed": billed, "paid": paid, "unpaid": money(billed - paid),
        "bills_awaiting_approval": awaiting,

        "incurred": incurred,
        # Kept under its old name so nothing reading this breaks, but it is now
        # everything the job has committed the business to, not just its orders.
        "cost": money(incurred + commitment),
        "forecast_cost": forecast_cost,
        "cost_to_complete": cost_to_complete,
        "percent_complete": percent_complete,

        "invoiced": invoiced, "received": received,
        "outstanding": owed,
        "retention_percent": retention_percent,
        "retention_held": retention_held,
        "earned": earned,
        # Positive means invoiced ahead of the work; negative means work done
        # that nobody has been asked to pay for yet.
        "over_billed": money(invoiced - earned),

        "margin": money(contract_value - forecast_cost),
        "margin_percent": (round((contract_value - forecast_cost) / contract_value * 100, 1)
                           if contract_value else 0.0),
        "estimate": estimate,
        "budget_variance": money(estimate - forecast_cost) if estimate else 0.0,
        "over_budget": (money(forecast_cost - estimate)
                        if estimate and forecast_cost > estimate else 0.0),

        "categories": [
            {"key": key, "label": label, "amount": money(by_category[key])}
            for key, label in COST_CATEGORIES
        ],
        "work_orders": len(wos), "purchase_orders": len(pos),
        "bills": len(bills), "subcontracts": len(subs),
    }


def _empty_buckets():
    return {b: 0.0 for b in AGEING_BUCKETS}


def account_dict(a):
    return {"id": a.id, "name": a.name or "", "kind": a.kind or "Bank",
            "bank_name": a.bank_name or "", "account_no": a.account_no or "",
            "ifsc": a.ifsc or "", "opening_balance": money(a.opening_balance),
            "opening_date": a.opening_date or "", "is_active": bool(a.is_active),
            "job_id": a.job_id, "custodian_id": a.custodian_id, "imprest_amount": money(a.imprest_amount)}


def opening_day(account) -> str:
    """The day an account's opening balance stands on; entries before it are already inside that balance."""
    d = (account.opening_date or "")[:10] if account is not None else ""
    return d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else ""


def account_balance(db, client_id, account):
    q = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id,
        models.DBMoneyEntry.account_id == account.id,
        models.DBMoneyEntry.voided.is_(False))
    start = opening_day(account)
    if start:
        # The opening balance is the balance on the opening day: what moved before it is already in that figure, and
        # adding it again counted it twice.
        q = q.filter(models.DBMoneyEntry.paid_on >= start)
    live = q.all()
    return money((account.opening_balance or 0)
                 + sum(e.amount for e in live if e.direction == "IN")
                 - sum(e.amount for e in live if e.direction == "OUT"))


class AdvanceDoc:
    """A subcontract order, seen as the mobilisation advance it promises the
    contractor - what a payment of the advance is recorded against."""

    def __init__(self, order):
        self.id = order.id
        self.number = "%s advance" % (order.wo_number or "Order")
        self.status = order.status
        self.order = order


def _doc_for(db, client_id, doc_type, doc_id):
    """The bill an entry settles, what it is worth, and who it is with."""
    if doc_type == "sub_advance":
        o = sub_order_or_404(db, client_id, doc_id)
        if o.status not in ("APPROVED", "EXECUTED"):
            raise HTTPException(409, "%s is %s. The advance is paid on an approved order."
                                     % (o.wo_number, (o.status or "").lower()))
        if not (o.mobilization_advance_amount or 0):
            raise HTTPException(409, "%s carries no mobilisation advance." % o.wo_number)
        con = db.query(models.DBContractor).filter(
            models.DBContractor.id == o.contractor_id).first() if o.contractor_id else None
        return (AdvanceDoc(o), money(o.mobilization_advance_amount), "OUT", "contractor",
                (con.company_name if con else ""), o.contractor_id, o.job_id)
    if doc_type == "ra_bill":
        b = ra_bill_or_404(db, client_id, doc_id)
        if b.status not in ("CERTIFIED", "PAID"):
            raise HTTPException(409, "%s is %s. Money is received against a certified bill."
                                     % (b.number, (b.status or "").lower()))
        job = db.query(models.DBJob).filter(models.DBJob.id == b.job_id).first()
        return (b, money((b.net_payable or 0) - bill_credited_net(db, "client", b.id)), "IN", "client",
                (job.customer_name if job else ""), None, b.job_id)
    if doc_type == "sub_bill":
        b = sub_bill_or_404(db, client_id, doc_id)
        if b.status not in ("CERTIFIED", "PAID"):
            raise HTTPException(409, "%s is %s. A contractor is paid against a certified bill."
                                     % (b.number, (b.status or "").lower()))
        con = db.query(models.DBContractor).filter(
            models.DBContractor.id == b.contractor_id).first() if b.contractor_id else None
        return (b, money((b.net_payable or 0) - bill_credited_net(db, "contractor", b.id)), "OUT", "contractor",
                (con.company_name if con else ""), b.contractor_id, b.job_id)
    if doc_type == "supplier_bill":
        b = db.query(models.DBBill).filter(
            models.DBBill.id == doc_id, models.DBBill.client_id == client_id).first()
        if not b:
            raise HTTPException(404, "Bill not found")
        if (b.approval_status or "none") not in ("none", "approved", ""):
            raise HTTPException(409, "%s is %s approval, so it cannot be paid yet."
                                     % (b.number, b.approval_status))
        if (b.status or "") in ("Cancelled", "Rejected", "Draft"):
            # A draft is a bill nobody has accepted yet; paying it would put
            # money in the ledger against something the ledger does not hold.
            raise HTTPException(409, "%s is %s. Accept the bill before paying it."
                                     % (b.number, (b.status or "").lower()))
        sup = next((s for s in db.query(models.DBSupplier).filter(
            models.DBSupplier.client_id == client_id).all()
            if norm_name(s.name) == norm_name(b.vendor_name)), None)
        return (b, money(b.total or b.amount or 0), "OUT", "supplier", b.vendor_name or "",
                (sup.id if sup else None), b.job_id)
    if doc_type == "retention_release":
        r = release_or_404(db, client_id, doc_id)
        if r.status not in ("CERTIFIED", "PAID"):
            raise HTTPException(409, "%s is %s." % (r.number, (r.status or "").lower()))
        party_type, party, party_id = release_party(db, r)
        return (r, money(r.net_amount), "IN" if r.side == "client" else "OUT",
                party_type, party, party_id, r.job_id)
    raise HTTPException(400, "Unknown document type: %s" % doc_type)


def already_settled(db, client_id, doc_type, doc, worth):
    """What has been paid or received on a bill so far.

    The ledger's entries, and for a bill marked paid before the ledger kept its payments (no entry behind it) what the
    mark said: paying such a bill again from the ledger paid it twice - a 1.18 lakh supplier bill marked paid on the
    Bills screen could be paid another 1.18 lakh under Payments & Ledgers."""
    got = settled_on(db, client_id, doc_type, doc.id)
    if doc_type in ("ra_bill", "sub_bill") and (doc.status or "") == "PAID" and not got:
        return worth
    if doc_type == "supplier_bill":
        return max(got, money(doc.amount_paid or 0))
    return got


def pay_in_full(db, request, doc_type, doc, worth, body, note=""):
    """Pay (or receive) what is still owed on a bill, through the ledger and the bank book - never by a flag on the
    bill: a bill marked paid with no entry behind it left the cash book short of money that had gone out, the bill
    payable again, and the bill deletable as if nothing had been paid on it."""
    from app.routers.money import record_money
    from app.schemas.money import MoneyIn
    body = body or {}
    outstanding = money(worth - already_settled(db, doc.client_id, doc_type, doc, worth))
    if outstanding <= 0:
        raise HTTPException(409, "%s is already fully settled." % (doc.number or "This bill"))
    return record_money(MoneyIn(
        doc_type=doc_type, doc_id=doc.id, amount=outstanding,
        mode=(body.get("mode") or "Bank transfer"), reference=(body.get("reference") or ""),
        account_id=body.get("account_id"), paid_on=(body.get("paid_on") or ""),
        note=(note or body.get("note") or body.get("comments") or "")), request, db)


def _settle_doc(db, client_id, doc_type, doc, worth, on):
    """Move the bill to paid when it is fully settled, back when it is not."""
    got = settled_on(db, client_id, doc_type, doc.id)
    full = got >= worth - 0.009
    if doc_type in ("ra_bill", "sub_bill", "retention_release"):
        if full and doc.status == "CERTIFIED":
            doc.status, doc.paid_at = "PAID", on
        elif not full and doc.status == "PAID":
            doc.status, doc.paid_at = "CERTIFIED", ""
    elif doc_type == "supplier_bill":
        doc.amount_paid = got
        doc.status = "Paid" if full else ("Partially Paid" if got > 0 else
                                          ("Approved" if (doc.approval_status or "") == "approved"
                                           else "Awaiting Payment"))
    return got


def next_money_number(db, client_id, direction, stem=None):
    """The next voucher number in its own series: RCT- for money in, PMT- for money out, CON- for a transfer between
    our own accounts. Read from the highest number in the series, so a transfer's two legs do not push the receipts
    and payments along."""
    stem = stem or ("RCT-" if direction == "IN" else "PMT-")
    top = 0
    for (number,) in db.query(models.DBMoneyEntry.number).filter(
            models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.number.like(stem + "%")).all():
        tail = (number or "")[len(stem):]
        if tail.isdigit():
            top = max(top, int(tail))
    return "%s%04d" % (stem, top + 1)


def money_entry_dict(e, accounts=None):
    acc = (accounts or {}).get(e.account_id)
    return {"id": e.id, "number": e.number or "", "direction": e.direction,
            "party_type": e.party_type or "", "party_name": e.party_name or "",
            "doc_type": e.doc_type or "", "doc_id": e.doc_id, "doc_number": e.doc_number or "",
            "job_id": e.job_id, "account_id": e.account_id,
            "account": acc.name if acc else "", "amount": money(e.amount),
            "paid_on": e.paid_on or "", "mode": e.mode or "", "reference": e.reference or "",
            "note": e.note or "", "voided": bool(e.voided), "void_reason": e.void_reason or "",
            "recorded_by_name": e.recorded_by_name or "", "created_at": e.created_at or "",
            "head": e.head or "", "pair_id": e.pair_id, "cleared_on": e.cleared_on or ""}


def _doc_for_any(db, client_id, doc_type, doc_id):
    """As _doc_for, without refusing a bill for its status - voiding must
    always be able to find what it settled."""
    if doc_type == "sub_advance":
        o = sub_order_or_404(db, client_id, doc_id)
        return AdvanceDoc(o), money(o.mobilization_advance_amount)
    if doc_type == "ra_bill":
        b = ra_bill_or_404(db, client_id, doc_id)
        return b, money((b.net_payable or 0) - bill_credited_net(db, "client", b.id))
    if doc_type == "sub_bill":
        b = sub_bill_or_404(db, client_id, doc_id)
        return b, money((b.net_payable or 0) - bill_credited_net(db, "contractor", b.id))
    if doc_type == "retention_release":
        r = release_or_404(db, client_id, doc_id)
        return r, money(r.net_amount)
    if doc_type != "supplier_bill":
        # Anything else used to be looked up as a supplier bill and fell over on the missing row.
        raise HTTPException(400, "Unknown document type: %s" % doc_type)
    b = db.query(models.DBBill).filter(models.DBBill.id == doc_id,
                                       models.DBBill.client_id == client_id).first()
    if not b:
        raise HTTPException(404, "Bill not found")
    return b, money(b.total or b.amount or 0)


def material_recovered_by_job(db, client_id, job_id=None):
    """Recovered on a certified or paid contractor bill - credited back to the
    project, because that material's cost is already in the contractor's bill."""
    q = db.query(models.DBMaterialRecovery.job_id, models.DBMaterialRecovery.amount).join(
        models.DBSubBill, models.DBSubBill.id == models.DBMaterialRecovery.sub_bill_id).filter(
        models.DBMaterialRecovery.client_id == client_id,
        models.DBSubBill.status.in_(("CERTIFIED", "PAID")))
    if job_id:
        q = q.filter(models.DBMaterialRecovery.job_id == job_id)
    out = {}
    for jid, amount in q.all():
        if jid:
            out[jid] = money(out.get(jid, 0.0) + (amount or 0))
    return out


DEAD_INVOICE = ("Draft", "Void", "Cancelled")
DEAD_SUPPLIER_BILL = ("Draft", "Cancelled", "Rejected")


def owed_to_us_rows(db, client, today=None):
    """Everything a customer owes us, one row each, aged the one way: invoices, certified client RA bills (less what
    credit notes took back and what has come in) and certified retention releases. Each row carries its currency and
    its bucket from core.dates.ageing_bucket - a missing due date is aged as the oldest, so somebody sees it."""
    from app.constants.client_billing import RA_CREDIT_DAYS
    from app.core.dates import ageing_bucket, days_after
    from app.services.credit_notes import credit_totals_by_bill
    from app.services.crm import settled_amounts
    today = today or date.today()
    base = base_currency(client)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    rows = []
    for inv in db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all():
        if (inv.status or "") in DEAD_INVOICE + ("Paid",):
            continue
        outstanding = money(inv.due)
        if outstanding <= 0:
            continue
        bucket, days = ageing_bucket(inv.due_date, today)
        job = jobs.get(inv.job_id)
        rows.append({
            "id": inv.id, "number": inv.number or "", "kind": "Invoice", "contact_id": None,
            "customer": inv.to_contact or "", "project": job.name if job else "", "job_id": inv.job_id,
            "issue_date": inv.issue_date or "", "due_date": inv.due_date or "",
            "total": invoice_total(inv), "paid": money(inv.paid), "outstanding": outstanding,
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0, "status": inv.status or "",
            "currency": ((inv.currency or "") or base).upper() or base,
        })
    # A client RA bill that has been certified and not paid is owed to us just as an invoice is - due a month after
    # the signature. What has already been received against it, and what a credit note took back, come off.
    settled = settled_amounts(db, client.id)
    ra_credits = credit_totals_by_bill(db, client.id, "client")
    for r in db.query(models.DBRABill).filter(models.DBRABill.client_id == client.id,
                                              models.DBRABill.status == "CERTIFIED").all():
        received = settled.get(("ra_bill", r.id), 0.0)
        worth = money((r.net_payable or 0) - ra_credits.get(r.id, {}).get("net", 0.0))
        outstanding = money(worth - received)
        if outstanding <= 0:
            continue
        due = days_after(r.certified_at, RA_CREDIT_DAYS)
        bucket, days = ageing_bucket(due or r.certified_at, today)
        job = jobs.get(r.job_id)
        rows.append({
            "id": r.id, "number": r.number or "", "kind": "RA bill",
            "customer": job.customer_name if job else "", "contact_id": job.contact_id if job else None, "project": job.name if job else "", "job_id": r.job_id,
            "issue_date": (r.certified_at or "")[:10], "due_date": due or (r.certified_at or "")[:10],
            "total": worth, "paid": money(received), "outstanding": outstanding, "doc_type": "ra_bill",
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0, "status": r.status or "",
            "currency": base,
        })
    # Retention released and claimed is owed like any certified bill.
    for rel in db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.client_id == client.id, models.DBRetentionRelease.side == "client",
            models.DBRetentionRelease.status == "CERTIFIED").all():
        received = settled.get(("retention_release", rel.id), 0.0)
        outstanding = money((rel.net_amount or 0) - received)
        if outstanding <= 0:
            continue
        due = days_after(rel.release_on, RA_CREDIT_DAYS)
        bucket, days = ageing_bucket(due or rel.release_on, today)
        job = jobs.get(rel.job_id)
        rows.append({
            "id": rel.id, "number": rel.number or "", "kind": "Retention release",
            "customer": job.customer_name if job else "", "contact_id": job.contact_id if job else None, "project": job.name if job else "", "job_id": rel.job_id,
            "issue_date": rel.release_on or "", "due_date": due or rel.release_on or "",
            "total": money(rel.net_amount), "paid": money(received), "outstanding": outstanding,
            "doc_type": "retention_release",
            "bucket": bucket, "days_overdue": days if (days or 0) > 0 else 0, "status": rel.status or "",
            "currency": base,
        })
    return rows


def _supplier_bill_live(b):
    return (b.status or "") not in DEAD_SUPPLIER_BILL and (b.approval_status or "none") != "rejected"


def _taxable(b):
    """A supplier bill before its GST: what it cost. The GST is input credit, not an expense."""
    return money(b.amount if b.amount else max(0.0, (b.total or 0) - (b.tax_amount or 0)))


def profit_and_loss(db, client, date_from="", date_to=""):
    """Profit and loss on the accrual basis: earned when billed, spent when billed to us - not when the money moved.

    Revenue: certified (and paid) client RA bills at their value of work, less what credit notes took back; invoices
    that went out (not drafts, voids or cancellations); sundry receipts booked under an income head.
    Expenses: supplier bills accepted (not drafts, cancelled, rejected) at their value before GST; certified
    subcontractor bills at their value of work less credit notes; expense vouchers (diesel, rent, site cash).
    Bills are in the books' currency; an invoice in another currency is reported in its own block."""
    from app.services.credit_notes import credit_totals_by_bill
    base = base_currency(client)

    def inside(on):
        on = (on or "")[:10]
        if date_from and (not on or on < date_from):
            return False
        if date_to and (not on or on > date_to):
            return False
        return True

    books = {}

    def block(cur):
        return books.setdefault(cur, {"revenue": {}, "expenses": {},
                                      "revenue_by_source": {"client_bills": 0.0, "invoices": 0.0, "other_income": 0.0},
                                      "expenses_by_source": {"supplier_bills": 0.0, "subcontractor_bills": 0.0,
                                                             "expense_vouchers": 0.0}})

    def add(cur, side, source, on, amount):
        if not amount or not inside(on):
            return
        b = block(cur)
        m = on[:7] if on and len(on) >= 7 else "Unknown"
        b[side][m] = b[side].get(m, 0.0) + amount
        b[side + "_by_source"][source] = money(b[side + "_by_source"][source] + amount)

    block(base)
    ra_credits = credit_totals_by_bill(db, client.id, "client")
    for r in db.query(models.DBRABill).filter(models.DBRABill.client_id == client.id,
                                              models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        add(base, "revenue", "client_bills", (r.certified_at or r.created_at or "")[:10],
            money((r.this_bill or 0) - ra_credits.get(r.id, {}).get("taxable", 0.0)))
    for inv in db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all():
        if (inv.status or "") in DEAD_INVOICE or (inv.approval_status or "none") == "rejected":
            continue
        add(((inv.currency or "") or base).upper() or base, "revenue", "invoices", (inv.issue_date or "")[:10],
            invoice_total(inv))
    sub_credits = credit_totals_by_bill(db, client.id, "contractor")
    for s in db.query(models.DBSubBill).filter(models.DBSubBill.client_id == client.id,
                                               models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        add(base, "expenses", "subcontractor_bills", (s.certified_at or s.created_at or "")[:10],
            money((s.this_bill or 0) - sub_credits.get(s.id, {}).get("taxable", 0.0)))
    for b in db.query(models.DBBill).filter(models.DBBill.client_id == client.id).all():
        if _supplier_bill_live(b):
            add(base, "expenses", "supplier_bills", (b.issue_date or b.created_at or "")[:10], _taxable(b))
    for e in db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.client_id == client.id,
                                                  models.DBMoneyEntry.voided.is_(False),
                                                  models.DBMoneyEntry.doc_type.in_(("expense", "income"))).all():
        if e.doc_type == "expense":
            add(base, "expenses", "expense_vouchers", (e.paid_on or "")[:10], money(e.amount))
        else:
            add(base, "revenue", "other_income", (e.paid_on or "")[:10], money(e.amount))

    def figures(b):
        rev, exp = b["revenue"], b["expenses"]
        months = sorted(set(rev) | set(exp))
        total_revenue, total_expenses = money(sum(rev.values())), money(sum(exp.values()))
        return {
            "months": months,
            "revenue": [money(rev.get(m, 0)) for m in months],
            "expenses": [money(exp.get(m, 0)) for m in months],
            "profit": [money(rev.get(m, 0) - exp.get(m, 0)) for m in months],
            "total_revenue": total_revenue, "total_expenses": total_expenses,
            "net_profit": money(total_revenue - total_expenses),
            "revenue_by_source": b["revenue_by_source"], "expenses_by_source": b["expenses_by_source"],
        }

    report = figures(books[base])
    report.update({"currency": base, "basis": "accrual", "period": {"from": date_from or "", "to": date_to or ""},
                   "other_currencies": [dict(figures(books[c]), currency=c) for c in sorted(books) if c != base]})
    return report


def balance_sheet(db, client):
    """What the business holds and owes today, from the same books as every other money screen.

    Assets: the balance of every bank account and cash box (and money entered against no account), invoice receipts
    (kept on the invoices, outside the bank book), what customers owe (the party ledger and unpaid invoices), retention
    the clients still hold, and advances paid on account. Liabilities: what is owed to suppliers and subcontractors,
    the retention held from subcontractors, and advances received. Equity is assets less liabilities, so the sheet
    balances by construction; the profit to date is shown beside it, and the rest is capital and what the books do
    not hold (GST, TDS, loans, fixed assets)."""
    from app.services.credit_notes import credit_totals_by_bill
    from app.services.crm import _ledger_rows, norm_name
    base = base_currency(client)

    accounts = db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client.id).all()
    bank = money(sum(account_balance(db, client.id, a) for a in accounts))
    loose = money(sum((e.amount or 0) * (1 if e.direction == "IN" else -1) for e in db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.voided.is_(False),
        models.DBMoneyEntry.account_id.is_(None), models.DBMoneyEntry.doc_type != "contra").all()))

    invoices = [i for i in db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()
                if (i.status or "") not in DEAD_INVOICE and (i.approval_status or "none") != "rejected"]
    groups = invoices_by_currency(invoices, base)

    # Party balances, netted per party as the ledger keeps them: a positive client balance is owed to us, a negative
    # one is an advance they paid; the other way round for suppliers and subcontractors.
    parties = {}
    for r in _ledger_rows(db, client.id):
        key = (r["party_type"], norm_name(r["party"]))
        parties[key] = parties.get(key, 0.0) + (r["billed"] or 0) - (r["moved"] or 0)
    owed_to_us = money(sum(v for (t, _), v in parties.items() if t == "client" and v > 0))
    advances_received = money(-sum(v for (t, _), v in parties.items() if t == "client" and v < 0))
    we_owe = money(sum(v for (t, _), v in parties.items() if t != "client" and v > 0))
    advances_paid = money(-sum(v for (t, _), v in parties.items() if t != "client" and v < 0))

    def released(side):
        return money(sum(r.amount or 0 for r in db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.client_id == client.id, models.DBRetentionRelease.side == side,
            models.DBRetentionRelease.status.in_(("CERTIFIED", "PAID"))).all()))

    ra_credits = credit_totals_by_bill(db, client.id, "client")
    held_by_clients = money(max(0.0, sum(
        (b.retention_amount or 0) - ra_credits.get(b.id, {}).get("retention", 0.0)
        for b in db.query(models.DBRABill).filter(models.DBRABill.client_id == client.id,
                                                  models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all())
        - released("client")))
    sub_credits = credit_totals_by_bill(db, client.id, "contractor")
    held_from_contractors = money(max(0.0, sum(
        (b.retention_amount or 0) - sub_credits.get(b.id, {}).get("retention", 0.0)
        for b in db.query(models.DBSubBill).filter(models.DBSubBill.client_id == client.id,
                                                   models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all())
        - released("contractor")))
    profit = profit_and_loss(db, client)

    def figures(inv_list, cur):
        in_base = cur == base
        collected = money(sum(i.paid or 0 for i in inv_list))
        invoiced_owed = money(sum(max(0.0, i.due or 0) for i in inv_list))
        assets = {"cash_collected": collected, "accounts_receivable": invoiced_owed}
        liabilities = {}
        if in_base:
            assets.update({"bank_and_cash": money(bank + loose), "bank_accounts": bank, "not_in_any_account": loose,
                           "accounts_receivable": money(invoiced_owed + owed_to_us),
                           "retention_receivable": held_by_clients, "advances_paid": advances_paid})
            liabilities = {"accounts_payable": we_owe, "retention_payable": held_from_contractors,
                           "advances_received": advances_received}
        else:
            liabilities = {"accounts_payable": 0.0}
        total_assets = money(collected + sum(v for k, v in assets.items()
                                             if k not in ("cash_collected", "bank_accounts", "not_in_any_account")))
        total_liabilities = money(sum(liabilities.values()))
        equity_total = money(total_assets - total_liabilities)
        p = profit if in_base else next((o for o in profit["other_currencies"] if o["currency"] == cur), None)
        to_date = p["net_profit"] if p else 0.0
        return {
            "assets": assets, "liabilities": liabilities,
            "equity": {"retained_earnings": equity_total, "profit_to_date": to_date,
                       "capital_and_other": money(equity_total - to_date)},
            "total_assets": total_assets, "total_liabilities": total_liabilities, "total_equity": equity_total,
            "balances": True,
            "note": "Equity is assets less liabilities, so the two sides always agree. Profit to date is the accrual "
                    "profit and loss; the rest is capital and what these books do not hold (GST, TDS, loans, fixed assets).",
        }

    report = figures(groups.get(base, []), base)
    report["currency"] = base
    report["other_currencies"] = [dict(figures(groups[c], c), currency=c) for c in sorted(groups) if c != base]
    return report


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.client_billing import ra_bill_or_404
from app.services.crm import norm_name, settled_on
from app.services.projects import hourly_rates, invoice_total, preload_pnl_for_job, project_pnl
from app.services.subcontract_billing import release_or_404, release_party, sub_bill_or_404, sub_order_or_404
from app.services.credit_notes import bill_credited_net
