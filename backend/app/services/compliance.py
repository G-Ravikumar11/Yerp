"""Whether a contractor is safe to pay, what has been charged back to them, and how they performed."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.constants.compliance import BACK_CHARGE_KINDS, DOC_KINDS, EXPIRY_WARNING_DAYS, RATING_FIELDS
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.serials import next_number

# The documents every contractor should hold before they are paid.
REQUIRED_KINDS = ("labour_licence", "pf", "esi", "insurance")


def doc_state(valid_to, today=None):
    """valid | expiring | expired, from a document's last valid day. No usable date counts as expired."""
    last = _parse_date(valid_to or "")
    if not last:
        return "expired"
    today = today or date.today()
    if last < today:
        return "expired"
    if last <= today + timedelta(days=EXPIRY_WARNING_DAYS):
        return "expiring"
    return "valid"


def doc_dict(d, today=None):
    last = _parse_date(d.valid_to or "")
    return {
        "id": d.id, "contractor_id": d.contractor_id, "kind": d.kind, "kind_label": DOC_KINDS.get(d.kind, d.kind),
        "number": d.number or "", "valid_from": d.valid_from or "", "valid_to": d.valid_to or "", "note": d.note or "",
        "state": doc_state(d.valid_to, today),
        "days_left": (last - (today or date.today())).days if last else None,
        "recorded_by": d.recorded_by_name or "",
    }


def contractor_compliance(db, client_id, contractor_id, today=None):
    """Every document the contractor holds, what is missing or lapsed, and a plain verdict.

    Of several documents of one kind, the one that runs longest counts: a renewed licence replaces the old one.
    """
    rows = db.query(models.DBComplianceDocument).filter(
        models.DBComplianceDocument.client_id == client_id,
        models.DBComplianceDocument.contractor_id == contractor_id).order_by(
            models.DBComplianceDocument.valid_to.desc()).all()
    docs = [doc_dict(d, today) for d in rows]
    best = {}
    for d in docs:
        best.setdefault(d["kind"], d)
    warnings, blocking = [], False
    for kind in REQUIRED_KINDS:
        d = best.get(kind)
        if d is None:
            warnings.append("%s is not on record." % DOC_KINDS[kind])
            blocking = True
        elif d["state"] == "expired":
            warnings.append("%s ran out on %s." % (DOC_KINDS[kind], d["valid_to"]))
            blocking = True
        elif d["state"] == "expiring":
            warnings.append("%s runs out in %d days (%s)." % (DOC_KINDS[kind], d["days_left"], d["valid_to"]))
    return {"documents": docs, "warnings": warnings, "ok": not blocking, "required": [
        {"kind": k, "label": DOC_KINDS[k], "state": (best[k]["state"] if k in best else "missing")} for k in REQUIRED_KINDS]}


def compliance_overview(db, client_id, today=None):
    out = []
    for c in db.query(models.DBContractor).filter(models.DBContractor.client_id == client_id,
                                                  models.DBContractor.is_active.is_(True)).order_by(
            models.DBContractor.company_name).all():
        status = contractor_compliance(db, client_id, c.id, today)
        out.append({"contractor_id": c.id, "contractor": c.company_name, "vendor_code": c.vendor_code or "",
                    "ok": status["ok"], "warnings": status["warnings"], "required": status["required"],
                    "score": scorecard(db, client_id, c.id)})
    return out


def back_charge_dict(db, b):
    bill = db.query(models.DBSubBill).get(b.applied_bill_id) if b.applied_bill_id else None
    con = db.query(models.DBContractor).get(b.contractor_id)
    return {"id": b.id, "number": b.number, "contractor_id": b.contractor_id, "contractor": con.company_name if con else "",
            "order_id": b.order_id, "kind": b.kind, "reason": b.reason, "amount": money(b.amount), "status": b.status,
            "applied_bill_id": b.applied_bill_id, "applied_bill": bill.number if bill else "",
            "raised_by": b.raised_by_name or "", "created_at": b.created_at, "applied_at": b.applied_at or ""}


def raise_back_charge(db, client_id, body, by_name):
    contractor = db.query(models.DBContractor).filter(models.DBContractor.id == body.contractor_id,
                                                      models.DBContractor.client_id == client_id).first()
    if not contractor:
        raise HTTPException(404, "Contractor not found")
    amount = money(body.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "A back-charge has to be for more than nothing.")
    if not (body.reason or "").strip():
        raise HTTPException(400, "Say what the back-charge is for, so the contractor can read it on their bill.")
    kind = body.kind if body.kind in BACK_CHARGE_KINDS else "Other"
    order = None
    if body.order_id:
        order = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == body.order_id,
                                                           models.DBSubcontractOrder.client_id == client_id).first()
        if not order or order.contractor_id != contractor.id:
            raise HTTPException(400, "That order is not this contractor's.")
    row = models.DBBackCharge(
        client_id=client_id, contractor_id=contractor.id, order_id=order.id if order else None,
        job_id=order.job_id if order else None, number=next_number(db, models.DBBackCharge, client_id, "BC"), kind=kind,
        reason=body.reason.strip(), amount=amount, status="OPEN", raised_by_name=by_name)
    db.add(row)
    db.flush()
    return row


def _taken_by(db, bill_id):
    return money(sum(b.amount or 0 for b in db.query(models.DBBackCharge).filter(
        models.DBBackCharge.applied_bill_id == bill_id, models.DBBackCharge.status == "APPLIED").all()))


def apply_back_charges(db, client_id, bill, ids, recost):
    """Take open back-charges off a draft bill. `recost` is recost_sub_bill, passed in so this module needs no bill code."""
    if (bill.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Back-charges go on a bill while it is still a draft.")
    wanted = set(ids or [])
    rows = db.query(models.DBBackCharge).filter(models.DBBackCharge.client_id == client_id,
                                                models.DBBackCharge.id.in_(wanted or {0})).all()
    if len(rows) != len(wanted):
        raise HTTPException(404, "One of those back-charges was not found.")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        if r.contractor_id != bill.contractor_id:
            raise HTTPException(400, "%s is another contractor's." % r.number)
        if r.status != "OPEN":
            raise HTTPException(409, "%s is already %s." % (r.number, r.status.lower()))
        r.status, r.applied_bill_id, r.applied_at = "APPLIED", bill.id, now
    db.flush()
    bill.back_charges = _taken_by(db, bill.id)
    recost(db, bill)
    if (bill.net_payable or 0) < 0:
        raise HTTPException(400, "Those back-charges take the bill below nothing.")
    return bill


def release_back_charge(db, charge, bill, recost):
    """Take an applied back-charge off a draft bill again, leaving it open for the next one."""
    if (bill.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "The bill has been sent; a back-charge stays on it.")
    charge.status, charge.applied_bill_id, charge.applied_at = "OPEN", None, ""
    db.flush()
    bill.back_charges = _taken_by(db, bill.id)
    recost(db, bill)
    return bill


def free_back_charges_of(db, bill_id):
    """A bill that is deleted or cancelled gives its back-charges back, so they are charged on the next one."""
    for r in db.query(models.DBBackCharge).filter(models.DBBackCharge.applied_bill_id == bill_id,
                                                  models.DBBackCharge.status == "APPLIED").all():
        r.status, r.applied_bill_id, r.applied_at = "OPEN", None, ""


def scorecard(db, client_id, contractor_id):
    rows = db.query(models.DBContractorRating).filter(models.DBContractorRating.client_id == client_id,
                                                      models.DBContractorRating.contractor_id == contractor_id).all()
    out = {"count": len(rows)}
    for f in RATING_FIELDS:
        out[f] = round(sum(getattr(r, f) or 0 for r in rows) / len(rows), 2) if rows else None
    out["overall"] = round(sum(out[f] for f in RATING_FIELDS) / len(RATING_FIELDS), 2) if rows else None
    return out


def add_rating(db, client_id, body, by_name):
    contractor = db.query(models.DBContractor).filter(models.DBContractor.id == body.contractor_id,
                                                      models.DBContractor.client_id == client_id).first()
    if not contractor:
        raise HTTPException(404, "Contractor not found")
    if body.bill_id:
        bill = db.query(models.DBSubBill).filter(models.DBSubBill.id == body.bill_id,
                                                 models.DBSubBill.client_id == client_id).first()
        if not bill or bill.contractor_id != contractor.id:
            raise HTTPException(400, "That bill is not this contractor's.")
    scores = {f: getattr(body, f) for f in RATING_FIELDS}
    if any(v < 1 or v > 5 for v in scores.values()):
        raise HTTPException(400, "Each score is from 1 (poor) to 5 (excellent).")
    row = models.DBContractorRating(client_id=client_id, contractor_id=contractor.id, bill_id=body.bill_id,
                                    note=(body.note or "").strip()[:300], rated_by_name=by_name, **scores)
    db.add(row)
    db.flush()
    return row


def settlement(db, client_id, order_id):
    """Where an order stands in money; once nothing is owed it is the no-dues statement the contractor signs."""
    order = db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id == order_id,
                                                       models.DBSubcontractOrder.client_id == client_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    bills = db.query(models.DBSubBill).filter(models.DBSubBill.order_id == order.id,
                                              models.DBSubBill.status != "CANCELLED").all()
    live = [b for b in bills if b.status in ("CERTIFIED", "PAID")]
    paid = money(sum(e.amount or 0 for e in db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.doc_type == "sub_bill",
        models.DBMoneyEntry.doc_id.in_([b.id for b in live] or [0]), models.DBMoneyEntry.voided.is_(False)).all()))
    charges = db.query(models.DBBackCharge).filter(models.DBBackCharge.client_id == client_id,
                                                   models.DBBackCharge.order_id == order.id,
                                                   models.DBBackCharge.status != "CANCELLED").all()
    open_charges = money(sum(c.amount or 0 for c in charges if c.status == "OPEN"))
    payable = money(sum(b.net_payable or 0 for b in live))
    held = money(sum(b.retention_amount or 0 for b in live))
    released = money(sum(r.amount or 0 for r in db.query(models.DBRetentionRelease).filter(
        models.DBRetentionRelease.client_id == client_id, models.DBRetentionRelease.sub_order_id == order.id,
        models.DBRetentionRelease.status != "CANCELLED").all()))
    advance_given = money(order.mobilization_advance_amount or 0)
    advance_back = money(sum(b.advance_recovery or 0 for b in live))
    owed = money(payable - paid)
    unfinished = [b for b in bills if b.status in ("DRAFT", "SUBMITTED")]
    return {
        "order_id": order.id, "order": order.wo_number or str(order.id),
        "bills": len(bills), "work_certified": money(sum(b.this_bill or 0 for b in live)),
        "certified_net": payable, "paid": paid, "still_to_pay": owed,
        "retention_held": held, "retention_released": released, "retention_balance": money(held - released),
        "advance_given": advance_given, "advance_recovered": advance_back,
        "advance_outstanding": money(advance_given - advance_back),
        "back_charges_applied": money(sum(c.amount or 0 for c in charges if c.status == "APPLIED")),
        "back_charges_open": open_charges, "open_bills": len(unfinished),
        "can_close": not (owed > 0.5 or open_charges > 0 or unfinished),
    }
