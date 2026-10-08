"""The rules and workings behind the crm endpoints."""
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, func as sqlfunc, or_

from app import models

from app.constants.crm import EMD_MODES, EST_TRANSITIONS, LEAD_SOURCES
from app.core.currency import compute_invoice_totals, line_net_amount, money, parse_tax_rate, unit_rate
from app.core.dates import _days_until, _parse_date
from app.core.gst import GST_STATES, state_from_gstin
from app.core.units import canonical_unit


def invoice_overdue_days(inv, today=None) -> int:
    """Days past the due date for an unsettled invoice; 0 when not overdue."""
    if inv.status in ("Paid", "Draft", "Void"):
        return 0
    if (inv.due or 0) <= 0:
        return 0
    due = _parse_date(inv.due_date)
    if not due:
        return 0
    today = today or datetime.now().date()
    return max(0, (today - due).days)


def contact_dict(c):
    return {"id": c.id, "name": c.name, "email": c.email or "", "phone_number": c.phone_number or "",
            "contact_person": c.contact_person or "", "gstin": c.gstin or "",
            "address": c.address or "", "city": c.city or "", "state": c.state or "",
            "pincode": c.pincode or ""}


def _contact_tax_fields(c, body, only_blank=False, clear=False):
    """What a customer is for tax: GSTIN, address, state, PIN. A client's
    GSTIN could not be entered anywhere, so no bill could carry it and no
    e-invoice could be made - the columns were there, the form was not."""
    gstin = (body.get("gstin") or "").strip().upper()
    if gstin and (len(gstin) != 15 or not state_from_gstin(gstin)):
        raise HTTPException(400, "A GSTIN is fifteen characters and starts with a state code.")
    pin = (body.get("pincode") or "").strip()
    if pin and not re.match(r"^\d{6}$", pin):
        raise HTTPException(400, "A PIN is six digits.")
    for field, value in (("gstin", gstin), ("address", (body.get("address") or "").strip()),
                         ("city", (body.get("city") or "").strip()),
                         ("state", (body.get("state") or "").strip() or
                          (GST_STATES.get(gstin[:2], "") if gstin else "")),
                         ("pincode", pin), ("contact_person", (body.get("contact_person") or "").strip())):
        if not value:
            if clear and field in body:
                setattr(c, field, "")       # an edit that empties a field empties it
            continue
        if only_blank and (getattr(c, field) or ""):
            continue
        setattr(c, field, value)


def standard_unit(value):
    """The unit in the app's own spelling when it is one it knows ("cu.m" is
    cum), else as typed - a lump sum or a unit peculiar to one tender is kept
    rather than turned into something it is not."""
    raw = (value or "").strip()
    return canonical_unit(raw, default="") or raw


def next_item_code(db, client_id=None, kind=None, taken=None) -> str:
    """Kept for callers that still name a tenant and a kind.

    Codes are no longer per tenant or per kind - one code is one item across
    the whole system - so both arguments are ignored.
    """
    return issue_item_code(db, taken)


def next_customer_code(db, client_id) -> str:
    highest = 0
    for row in db.query(models.DBContact).filter(
            models.DBContact.client_id == client_id).all():
        match = re.match(r"^CUST-0*(\d+)$", (row.code or "").upper())
        if match:
            highest = max(highest, int(match.group(1)))
    return "CUST-%04d" % (highest + 1)


def customer_to_dict(db, contact, with_counts=False):
    row = {
        "id": contact.id, "code": contact.code or "", "name": contact.name or "",
        "contact_person": contact.contact_person or "", "email": contact.email or "",
        "phone_number": contact.phone_number or "", "gstin": contact.gstin or "",
        "pan": getattr(contact, "pan", "") or "",
        "address": contact.address or "", "city": contact.city or "",
        "state": contact.state or "", "pincode": contact.pincode or "",
        "notes": contact.notes or "",
        "is_active": bool(contact.is_active) if contact.is_active is not None else True,
        "created_at": contact.created_at or "",
    }
    if with_counts:
        # By the link where a job has one, and by name where it does not. A
        # job raised from the jobs screen only ever carried the customer's
        # name, so counting the link alone reported nought projects against
        # customers who plainly had several - the column read as broken.
        row["projects"] = db.query(models.DBJob).filter(
            models.DBJob.client_id == contact.client_id,
            or_(models.DBJob.contact_id == contact.id,
                and_(models.DBJob.contact_id.is_(None),
                     sqlfunc.lower(models.DBJob.customer_name)
                     == (contact.name or "").lower()))).count()
    return row


def backfill_customer_codes(db, client_id) -> bool:
    """Give a code to customers who predate there being one.

    The contacts a business already had were names and phone numbers, from
    before a customer needed identifying on a contract. They are the same
    customers, so they are numbered into the same series rather than being
    left blank next to the ones added since.
    """
    missing = db.query(models.DBContact).filter(
        models.DBContact.client_id == client_id,
        or_(models.DBContact.code.is_(None), models.DBContact.code == "")
    ).order_by(models.DBContact.id).all()
    if not missing:
        return False
    for contact in missing:
        contact.code = next_customer_code(db, client_id)
        db.flush()
    db.commit()
    return True


def sales_stage_for_quote(q):
    """Where a quote sits. A quote that has become an invoice leaves the quote
    stages entirely - its invoice carries it from there."""
    status = quote_display_status(q)
    if status == "Invoiced":
        return None
    if status == "Accepted":
        return "accepted"
    if status in ("Declined", "Expired"):
        return None          # off the board; still counted as lost
    if status == "Sent":
        return "sent"
    return "drafted"


def sales_stage_for_invoice(inv):
    if (inv.status or "") == "Void":
        return None
    if (inv.due or 0) <= 0 and (inv.paid or 0) > 0:
        return "paid"
    if (inv.status or "") == "Draft":
        return "drafted"
    return "invoiced"


def quote_is_expired(q, today=None):
    """A quote past its expiry that nobody has answered is dead.

    Derived rather than stored: a background job to flip the column would be
    one more thing to run, and the answer is a date comparison.
    """
    if q.status not in ("Sent", "Draft"):
        return False
    expiry = _parse_date(q.expiry_date)
    if not expiry:
        return False
    return expiry < (today or datetime.now().date())


def quote_display_status(q, today=None):
    return "Expired" if quote_is_expired(q, today) else q.status


def quote_to_dict(q, client, db, detail=False):
    subtotal, tax_total, grand_total = compute_invoice_totals(q.line_items, q.tax_type)
    data = {
        "id": q.id,
        "number": q.number,
        "ref": q.ref or "",
        "to": q.to_contact,
        "email": q.email or "",
        "phone_number": q.phone_number or "",
        "date": q.issue_date,
        "expiry_date": q.expiry_date,
        "title": q.title or "",
        "summary": q.summary or "",
        "terms": q.terms or "",
        "subtotal": subtotal,
        "tax_total": tax_total,
        "total": grand_total,
        "status": quote_display_status(q),
        "stored_status": q.status,
        "is_expired": quote_is_expired(q),
        "sent": q.sent or "",
        "tax_type": q.tax_type,
        "currency": q.currency or (client.currency if client else ""),
        "invoice_number": q.invoice_number or "",
        "decided_at": q.decided_at or "",
    }
    if not detail:
        return data

    settings_rows = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == q.client_id).all() if q.client_id else []
    settings_map = {s.key: s.value for s in settings_rows}
    data["company"] = {
        "name": settings_map.get("company_name", "") or (client.company_name if client else ""),
        "email": settings_map.get("email", "") or (client.email if client else ""),
        "phone_number": settings_map.get("phone_number", "") or (client.phone_number if client else ""),
        "address": settings_map.get("company_address", "") or (client.address if client else ""),
        "website": settings_map.get("company_website", "") or (client.website if client else ""),
        "abn": settings_map.get("company_abn", "") or (client.abn if client else ""),
        "logo_url": client.logo_url if client else "",
    }
    data["line_items"] = [{
        "name": li.name or "",
        "description": li.description,
        "qty": li.qty,
        "price": li.price,
        "disc": li.disc,
        "account": li.account,
        "tax_rate": li.tax_rate,
        "tax_percent": round(parse_tax_rate(li.tax_rate) * 100, 4),
        "amount": money(line_net_amount(li.qty, li.price, li.disc)),
    } for li in q.line_items]
    return data


def get_quote_or_404(db, client, number):
    q = db.query(models.DBQuote).filter(
        models.DBQuote.number == number, models.DBQuote.client_id == client.id
    ).first()
    if not q:
        raise HTTPException(status_code=404, detail="Quote not found")
    return q


def estimate_or_404(db, client_id, est_id):
    row = db.query(models.DBEstimate).filter(
        models.DBEstimate.id == est_id,
        models.DBEstimate.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Estimate not found")
    return row


def recost_estimate_item(db, item, est):
    """Cost from the analysis if there is one, then margin on top.

    Overhead is applied to cost and profit to the result, in that order,
    because overhead is a cost the business carries and profit is what is
    left after every cost - pricing them the other way round quietly
    understates the margin.
    """
    lines = db.query(models.DBRateAnalysis).filter(
        models.DBRateAnalysis.estimate_item_id == item.id).all()
    if lines:
        total = 0.0
        for l in lines:
            base = (l.quantity_per_unit or 0) * (l.rate or 0)
            l.amount_per_unit = money(base * (1 + (l.wastage_percent or 0) / 100.0))
            total += l.amount_per_unit
        item.cost_rate = unit_rate(total)
    oh = item.overhead_percent if item.overhead_percent is not None else (est.overhead_percent or 0)
    pf = item.profit_percent if item.profit_percent is not None else (est.profit_percent or 0)
    with_oh = (item.cost_rate or 0) * (1 + oh / 100.0)
    item.quoted_rate = unit_rate(with_oh * (1 + pf / 100.0))
    item.cost_amount = money((item.quantity or 0) * (item.cost_rate or 0))
    item.quoted_amount = money((item.quantity or 0) * item.quoted_rate)
    return item


def recost_estimate(db, est):
    items = db.query(models.DBEstimateItem).filter(
        models.DBEstimateItem.estimate_id == est.id).all()
    for it in items:
        recost_estimate_item(db, it, est)
    est.cost_total = money(sum(i.cost_amount or 0 for i in items))
    est.quoted_total = money(sum(i.quoted_amount or 0 for i in items))
    est.margin_amount = money(est.quoted_total - est.cost_total)
    est.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return est


def estimate_dict(db, est, detail=False):
    job = db.query(models.DBJob).filter(models.DBJob.id == est.job_id).first()
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == est.work_order_id).first() if est.work_order_id else None
    row = {
        "id": est.id, "number": est.number or "", "title": est.title or "",
        "customer_name": est.customer_name or "",
        "tender_reference": est.tender_reference or "", "due_on": est.due_on or "",
        "job_id": est.job_id, "project": job.name if job else "",
        "status": est.status or "DRAFT",
        "overhead_percent": est.overhead_percent or 0,
        "profit_percent": est.profit_percent or 0,
        "cost_total": money(est.cost_total), "quoted_total": money(est.quoted_total),
        "margin_amount": money(est.margin_amount),
        "margin_percent": (round(est.margin_amount / est.quoted_total * 100, 1)
                           if est.quoted_total else 0.0),
        "work_order_id": est.work_order_id, "work_order": wo.number if wo else "",
        "decided_at": est.decided_at or "", "lost_reason": est.lost_reason or "",
        "notes": est.notes or "", "prepared_by_name": est.prepared_by_name or "",
        "editable": (est.status or "DRAFT") == "DRAFT",
        "actions": sorted(EST_TRANSITIONS.get(est.status or "DRAFT", {}).keys()),
        "item_count": db.query(models.DBEstimateItem).filter(
            models.DBEstimateItem.estimate_id == est.id).count(),
        "created_at": est.created_at or "",
    }
    if detail:
        row["items"] = []
        for it in db.query(models.DBEstimateItem).filter(
                models.DBEstimateItem.estimate_id == est.id).order_by(
                    models.DBEstimateItem.display_order, models.DBEstimateItem.id).all():
            row["items"].append({
                "id": it.id, "item_no": it.item_no or "", "fg_code": it.fg_code or "",
                "description": it.description or "", "uom": it.uom or "",
                "quantity": money(it.quantity), "cost_rate": unit_rate(it.cost_rate),
                "overhead_percent": it.overhead_percent,
                "profit_percent": it.profit_percent,
                "quoted_rate": unit_rate(it.quoted_rate),
                "cost_amount": money(it.cost_amount), "quoted_amount": money(it.quoted_amount),
                "analysis": [{
                    "id": a.id, "kind": a.kind or "MATERIAL", "item_code": a.item_code or "",
                    "description": a.description or "", "uom": a.uom or "",
                    "quantity_per_unit": a.quantity_per_unit or 0, "rate": unit_rate(a.rate),
                    "wastage_percent": a.wastage_percent or 0,
                    "amount_per_unit": unit_rate(a.amount_per_unit),
                } for a in db.query(models.DBRateAnalysis).filter(
                    models.DBRateAnalysis.estimate_item_id == it.id).order_by(
                        models.DBRateAnalysis.display_order, models.DBRateAnalysis.id).all()],
            })
    return row


def norm_name(value):
    """The name as it is compared: case, spacing and full stops do not make
    two suppliers."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def supplier_dict(s):
    return {"id": s.id, "code": s.code or "", "name": s.name or "",
            "contact_person": s.contact_person or "", "phone": s.phone or "",
            "email": s.email or "", "gstin": s.gstin or "", "pan": s.pan or "",
            "state_code": s.state_code or "", "state": GST_STATES.get(s.state_code or "", ""),
            "address": s.address or "", "bank_name": s.bank_name or "",
            "bank_account": s.bank_account or "", "bank_ifsc": s.bank_ifsc or "",
            "payment_days": s.payment_days or 0, "supplies": s.supplies or "",
            "is_active": bool(s.is_active)}


def settled_amounts(db, client_id):
    """{(doc_type, doc_id): amount} over every live entry, in one query."""
    out = {}
    for doc_type, doc_id, amount in db.query(
            models.DBMoneyEntry.doc_type, models.DBMoneyEntry.doc_id,
            models.DBMoneyEntry.amount).filter(
            models.DBMoneyEntry.client_id == client_id,
            models.DBMoneyEntry.voided.is_(False),
            models.DBMoneyEntry.doc_id.isnot(None)).all():
        key = (doc_type, doc_id)
        out[key] = money(out.get(key, 0.0) + (amount or 0))
    return out


def settled_on(db, client_id, doc_type, doc_id):
    return money(sum(e.amount or 0 for e in db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id,
        models.DBMoneyEntry.doc_type == doc_type,
        models.DBMoneyEntry.doc_id == doc_id,
        models.DBMoneyEntry.voided.is_(False)).all()))


def advance_paid(db, client_id, order_id):
    """What has actually been handed over as the mobilisation advance."""
    return settled_on(db, client_id, "sub_advance", order_id)


def _advance_set_off_row(party_type, party, on, bill):
    """The part of a bill that went to pay back a mobilisation advance.

    A bill's net payable already has the recovery taken off, so counting the
    bill at its net alone left the advance looking wholly unpaid for ever: a
    gang paid a 78,000 advance, with 7,800 of it taken back, showed as owing
    all 78,000. The recovery is value the party earned and settled against
    the advance, so it goes on their account beside the bill."""
    back = money(bill.advance_recovery or 0)
    if back <= 0:
        return []
    return [{"party_type": party_type, "party": party, "date": on,
             "kind": "Advance set off", "number": bill.number,
             "doc_type": "advance_set_off", "doc_id": bill.id,
             "billed": back, "moved": 0.0, "job_id": bill.job_id}]


def _ledger_rows(db, client_id):
    """Every bill and every movement of money, each tagged to a party.

    Bills are what a party is owed or owes; entries are what has moved. A
    bill marked paid before this ledger existed, with no entry behind it, is
    counted as settled on the day it was marked - otherwise every old party
    would show a balance nobody owes.
    """
    rows = []
    settled = settled_amounts(db, client_id)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client_id).all()}

    for b in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client_id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        job = jobs.get(b.job_id)
        party = job.customer_name if job else ""
        on = (b.certified_at or b.created_at or "")[:10]
        rows.append({"party_type": "client", "party": party, "date": on, "kind": "RA bill",
                     "number": b.number, "doc_type": "ra_bill", "doc_id": b.id,
                     "billed": money(b.net_payable), "moved": 0.0, "job_id": b.job_id})
        rows.extend(_advance_set_off_row("client", party, on, b))
        if b.status == "PAID" and not settled.get(("ra_bill", b.id)):
            rows.append({"party_type": "client", "party": party, "date": (b.paid_at or on)[:10],
                         "kind": "Received (marked paid)", "number": b.number, "doc_type": "ra_bill",
                         "doc_id": b.id, "billed": 0.0, "moved": money(b.net_payable),
                         "job_id": b.job_id})

    for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client_id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        con = contractors.get(b.contractor_id)
        party = con.company_name if con else ""
        on = (b.certified_at or b.created_at or "")[:10]
        rows.append({"party_type": "contractor", "party": party, "date": on, "kind": "Their RA bill",
                     "number": b.number, "doc_type": "sub_bill", "doc_id": b.id,
                     "billed": money(b.net_payable), "moved": 0.0, "job_id": b.job_id})
        rows.extend(_advance_set_off_row("contractor", party, on, b))
        if b.status == "PAID" and not settled.get(("sub_bill", b.id)):
            rows.append({"party_type": "contractor", "party": party, "date": (b.paid_at or on)[:10],
                         "kind": "Paid (marked paid)", "number": b.number, "doc_type": "sub_bill",
                         "doc_id": b.id, "billed": 0.0, "moved": money(b.net_payable),
                         "job_id": b.job_id})

    for b in db.query(models.DBBill).filter(models.DBBill.client_id == client_id).all():
        if (b.status or "") in ("Draft", "Cancelled", "Rejected"):
            continue
        if (b.approval_status or "none") == "rejected":
            continue
        on = (b.issue_date or b.created_at or "")[:10]
        rows.append({"party_type": "supplier", "party": b.vendor_name or "", "date": on,
                     "kind": "Their bill", "number": b.number or "", "doc_type": "supplier_bill",
                     "doc_id": b.id, "billed": money(b.total or b.amount or 0), "moved": 0.0,
                     "job_id": b.job_id})
        pre_ledger = money((b.amount_paid or 0) - settled.get(("supplier_bill", b.id), 0.0))
        if pre_ledger > 0.009:
            rows.append({"party_type": "supplier", "party": b.vendor_name or "", "date": on,
                         "kind": "Paid (marked paid)", "number": b.number or "",
                         "doc_type": "supplier_bill", "doc_id": b.id, "billed": 0.0,
                         "moved": pre_ledger, "job_id": b.job_id})

    rows.extend(release_ledger_rows(db, client_id))

    for e in db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == client_id,
            models.DBMoneyEntry.voided.is_(False)).all():
        rows.append({"party_type": e.party_type or "other", "party": e.party_name or "",
                     "date": e.paid_on or "", "kind": ("Received" if e.direction == "IN" else "Paid")
                     + ((" - " + e.mode) if e.mode else ""),
                     "number": e.number, "doc_type": e.doc_type, "doc_id": e.doc_id,
                     "against": e.doc_number or ("on account" if e.doc_type == "on_account" else ""),
                     "billed": 0.0, "moved": money(e.amount), "job_id": e.job_id,
                     "reference": e.reference or ""})
    return rows


def lead_or_404(db, client_id, lead_id):
    l = db.query(models.DBLead).filter(models.DBLead.id == lead_id,
                                       models.DBLead.client_id == client_id).first()
    if not l:
        raise HTTPException(404, "Tender not found")
    return l


def sync_lead_from_estimate(db, lead):
    """The estimate's outcome is the tender's outcome. Read on the way out,
    so a win recorded on the estimate is never contradicted here."""
    if not lead.estimate_id:
        return
    est = db.query(models.DBEstimate).filter(models.DBEstimate.id == lead.estimate_id).first()
    if not est:
        return
    mapped = {"DRAFT": "ESTIMATING", "SUBMITTED": "SUBMITTED", "WON": "WON", "LOST": "LOST"}.get(est.status)
    if mapped and lead.status not in ("DROPPED",) and lead.status != mapped:
        lead.status = mapped
    lead.our_price = money(est.quoted_total or lead.our_price or 0)
    if est.status == "WON" and est.job_id and not lead.job_id:
        lead.job_id = est.job_id


def lead_dict(db, l):
    sync_lead_from_estimate(db, l)
    est = db.query(models.DBEstimate).filter(models.DBEstimate.id == l.estimate_id).first() if l.estimate_id else None
    due = _days_until(l.bid_due_on)
    emd_out = bool(l.emd_amount) and bool(l.emd_paid_on) and not l.emd_returned_on
    return {"id": l.id, "number": l.number, "title": l.title or "", "customer_name": l.customer_name or "",
            "contact_person": l.contact_person or "", "phone": l.phone or "", "email": l.email or "",
            "location": l.location or "", "source": l.source or "",
            "tender_reference": l.tender_reference or "", "estimated_value": money(l.estimated_value),
            "site_visit_on": l.site_visit_on or "", "prebid_on": l.prebid_on or "",
            "bid_due_on": l.bid_due_on or "", "days_to_bid": due,
            "emd_amount": money(l.emd_amount), "emd_mode": l.emd_mode or "",
            "emd_reference": l.emd_reference or "", "emd_paid_on": l.emd_paid_on or "",
            "emd_returned_on": l.emd_returned_on or "", "emd_outstanding": emd_out,
            "status": l.status, "lost_reason": l.lost_reason or "",
            "winning_bidder": l.winning_bidder or "", "winning_price": money(l.winning_price),
            "our_price": money(l.our_price), "estimate_id": l.estimate_id,
            "estimate_number": est.number if est else "", "job_id": l.job_id,
            "owner_name": l.owner_name or "", "notes": l.notes or "",
            "created_at": l.created_at or ""}


def _apply_lead(l, body):
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "Name the tender - the work and where it is.")
    for label, v in (("estimated value", body.estimated_value), ("EMD", body.emd_amount)):
        if (v or 0) < 0:
            raise HTTPException(400, "The %s cannot be negative." % label)
    l.title = title
    l.customer_name = (body.customer_name or "").strip()
    l.contact_person = (body.contact_person or "").strip()
    l.phone, l.email = (body.phone or "").strip(), (body.email or "").strip()
    l.location = (body.location or "").strip()
    l.source = body.source if body.source in LEAD_SOURCES else (body.source or "").strip()
    l.tender_reference = (body.tender_reference or "").strip()
    l.estimated_value = money(body.estimated_value or 0)
    l.site_visit_on = (body.site_visit_on or "").strip()
    l.prebid_on = (body.prebid_on or "").strip()
    l.bid_due_on = (body.bid_due_on or "").strip()
    l.emd_amount = money(body.emd_amount or 0)
    l.emd_mode = body.emd_mode if body.emd_mode in EMD_MODES else ""
    l.emd_reference = (body.emd_reference or "").strip()
    l.emd_paid_on = (body.emd_paid_on or "").strip()
    l.owner_name = (body.owner_name or "").strip()
    l.notes = (body.notes or "").strip()
    l.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_lead(db, client_id, lead, kind, note, by, next_action="", next_on=""):
    db.add(models.DBLeadActivity(client_id=client_id, lead_id=lead.id, kind=kind, note=note,
                                 next_action=next_action, next_on=next_on, by_name=by))


def next_lead_number(db, client_id):
    n = db.query(models.DBLead).filter(models.DBLead.client_id == client_id).count()
    return "TND-%04d" % (n + 1)


def state_name_of(gstin):
    code = state_from_gstin(gstin or "")
    return GST_STATES.get(code, "") if code else ""


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.items import issue_item_code
from app.services.subcontract_billing import release_ledger_rows
