"""The rules and workings behind the money endpoints."""
from fastapi import HTTPException

from app import models

from app.constants.money import AGEING_BUCKETS, COST_CATEGORIES, COST_CATEGORY_ALIASES, COST_CATEGORY_KEYS
from app.core.currency import DEFAULT_CURRENCY, money


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
    # supplier bills and clock-in hours, and a job with a gang bill, a signed
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
    live_subs = [x for x in subs if (x.status or "") not in ("CANCELLED", "AMENDED")]
    # What the gangs have still to bill. Their bills are incurred already;
    # counting the whole order on top counted every rupee billed twice.
    gang_billed = {}
    for b in pre["sub"].get(job.id, []):
        gang_billed[b.order_id] = money(gang_billed.get(b.order_id, 0.0) + (b.this_bill or 0))
    subcontracted = money(sum(max(0.0, (x.gross_amount or x.net_order_value or 0)
                                  - gang_billed.get(x.id, 0.0)) for x in live_subs))

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
    invoiced = money(sum(invoice_total(i) for i in invoices) + sum(b.this_bill or 0 for b in ra))
    received = money(sum(i.paid or 0 for i in invoices) + ra_received)
    # What the client still owes is what each bill asks for less what came in
    # against it - the bill's net payable carries its GST, retention and TDS,
    # so "billed less received" mixed a figure before tax with cash after it.
    owed = money(sum(max(0.0, invoice_total(i) - (i.paid or 0)) for i in invoices)
                 + sum(max(0.0, (b.net_payable or 0) - settled.get(("ra_bill", b.id), 0.0))
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
                           + sum(b.retention_amount or 0 for b in ra)
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
                                     - c["material_recovered_from_gangs"])
    by_category["subcontract"] = money(by_category["subcontract"] + c["subcontractors"] + subcontracted)
    by_category["plant"] = money(by_category["plant"] + c["plant"] + c["equipment"])
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
            "opening_date": a.opening_date or "", "is_active": bool(a.is_active)}


def account_balance(db, client_id, account):
    live = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id,
        models.DBMoneyEntry.account_id == account.id,
        models.DBMoneyEntry.voided.is_(False)).all()
    return money((account.opening_balance or 0)
                 + sum(e.amount for e in live if e.direction == "IN")
                 - sum(e.amount for e in live if e.direction == "OUT"))


class AdvanceDoc:
    """A subcontract order, seen as the mobilisation advance it promises the
    gang - what a payment of the advance is recorded against."""

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
        return b, money(b.net_payable), "IN", "client", (job.customer_name if job else ""), None, b.job_id
    if doc_type == "sub_bill":
        b = sub_bill_or_404(db, client_id, doc_id)
        if b.status not in ("CERTIFIED", "PAID"):
            raise HTTPException(409, "%s is %s. A contractor is paid against a certified bill."
                                     % (b.number, (b.status or "").lower()))
        con = db.query(models.DBContractor).filter(
            models.DBContractor.id == b.contractor_id).first() if b.contractor_id else None
        return (b, money(b.net_payable), "OUT", "contractor",
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


def next_money_number(db, client_id, direction):
    stem = "RCT-" if direction == "IN" else "PMT-"
    n = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id,
        models.DBMoneyEntry.direction == direction).count()
    return "%s%04d" % (stem, n + 1)


def money_entry_dict(e, accounts=None):
    acc = (accounts or {}).get(e.account_id)
    return {"id": e.id, "number": e.number or "", "direction": e.direction,
            "party_type": e.party_type or "", "party_name": e.party_name or "",
            "doc_type": e.doc_type or "", "doc_id": e.doc_id, "doc_number": e.doc_number or "",
            "job_id": e.job_id, "account_id": e.account_id,
            "account": acc.name if acc else "", "amount": money(e.amount),
            "paid_on": e.paid_on or "", "mode": e.mode or "", "reference": e.reference or "",
            "note": e.note or "", "voided": bool(e.voided), "void_reason": e.void_reason or "",
            "recorded_by_name": e.recorded_by_name or "", "created_at": e.created_at or ""}


def _doc_for_any(db, client_id, doc_type, doc_id):
    """As _doc_for, without refusing a bill for its status - voiding must
    always be able to find what it settled."""
    if doc_type == "sub_advance":
        o = sub_order_or_404(db, client_id, doc_id)
        return AdvanceDoc(o), money(o.mobilization_advance_amount)
    if doc_type == "ra_bill":
        b = ra_bill_or_404(db, client_id, doc_id)
        return b, money(b.net_payable)
    if doc_type == "sub_bill":
        b = sub_bill_or_404(db, client_id, doc_id)
        return b, money(b.net_payable)
    if doc_type == "retention_release":
        r = release_or_404(db, client_id, doc_id)
        return r, money(r.net_amount)
    b = db.query(models.DBBill).filter(models.DBBill.id == doc_id,
                                       models.DBBill.client_id == client_id).first()
    return b, money(b.total or b.amount or 0)


def material_recovered_by_job(db, client_id, job_id=None):
    """Recovered on a certified or paid gang bill - credited back to the
    project, because that material's cost is already in the gang's bill."""
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


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.client_billing import ra_bill_or_404
from app.services.crm import norm_name, settled_on
from app.services.projects import hourly_rates, invoice_total, preload_pnl_for_job, project_pnl
from app.services.subcontract_billing import release_or_404, release_party, sub_bill_or_404, sub_order_or_404
