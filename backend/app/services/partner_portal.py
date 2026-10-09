"""The rules and workings behind the partner portal endpoints."""
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app import models

from app.core.audit import log_login
from app.core.currency import money
from app.services.crm import _ledger_rows, norm_name, settled_amounts
from app.services.subcontract_billing import portal_party


def get_portal_user(request: Request, db: Session):
    uid = request.session.get("portal_user_id")
    if not uid:
        raise HTTPException(401, "Not signed in")
    u = db.query(models.DBPortalUser).filter(models.DBPortalUser.id == uid).first()
    if not u or not u.is_active:
        request.session.pop("portal_user_id", None)
        raise HTTPException(401, "Your access has been removed. Ask the office if you need it back.")
    client = db.query(models.DBClient).filter(models.DBClient.id == u.client_id).first()
    if not client or not client.is_active:
        raise HTTPException(403, "Account disabled")
    party, name = portal_party(db, u.client_id, u.party_type, u.party_id)
    if not party or party.is_active is False:
        raise HTTPException(403, "Your company is no longer on %s's list. Ask the office."
                                 % (client.company_name or "the"))
    return u, client, party, name


def _portal_signed_in(request, db, u, method="password"):
    # One identity per browser: a portal session must never ride on top of
    # an office one, or the office's rights would answer for the partner.
    for k in ("client_id", "member_id", "employee_id", "employee_client_id"):
        request.session.pop(k, None)
    request.session["portal_user_id"] = u.id
    u.last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_login(db, u.client_id, u.email, "partner", method, request, "success")
    db.commit()


def _portal_ledger(db, u, party_name):
    key = norm_name(party_name)
    rows = [r for r in _ledger_rows(db, u.client_id)
            if r["party_type"] == u.party_type and norm_name(r["party"]) == key]
    rows.sort(key=lambda r: (r["date"] or "", 0 if r["billed"] else 1, r["number"] or ""))
    return rows


def _portal_payments(db, u, party, party_name):
    key = norm_name(party_name)
    out = []
    for e in db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == u.client_id,
            models.DBMoneyEntry.direction == "OUT",
            models.DBMoneyEntry.party_type == u.party_type,
            models.DBMoneyEntry.voided.is_(False)).order_by(
                models.DBMoneyEntry.paid_on.desc(), models.DBMoneyEntry.id.desc()).all():
        if e.party_id == party.id or norm_name(e.party_name) == key:
            out.append({"number": e.number or "", "paid_on": e.paid_on or "", "amount": money(e.amount),
                        "mode": e.mode or "", "reference": e.reference or "",
                        "against": e.doc_number or ("on account" if e.doc_type == "on_account" else "")})
    return out


def _portal_orders(db, u, party, party_name):
    if u.party_type == "contractor":
        jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == u.client_id).all()}
        return [{"id": o.id, "number": o.wo_number or "", "status": o.status or "",
                 "project": jobs[o.job_id].name if o.job_id in jobs else "",
                 "subject": o.subject or "", "value": money(o.net_order_value or o.gross_amount),
                 "from": o.commencement_date or "", "to": o.completion_date or "",
                 "retention_percent": o.retention_percent or 0, "superseded": o.status == "AMENDED"}
                for o in db.query(models.DBSubcontractOrder).filter(
                    models.DBSubcontractOrder.client_id == u.client_id,
                    models.DBSubcontractOrder.contractor_id == party.id,
                    models.DBSubcontractOrder.status.in_(("APPROVED", "EXECUTED", "AMENDED"))).order_by(
                        models.DBSubcontractOrder.id.desc()).all()]
    key = norm_name(party_name)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == u.client_id).all()}
    return [{"id": p.id, "number": p.number or "", "status": p.status or "",
             "project": jobs[p.job_id].name if p.job_id in jobs else "",
             "subject": p.reference or p.category or "", "value": money(p.total),
             "from": p.issue_date or "", "to": p.needed_by or "", "superseded": False}
            for p in db.query(models.DBPurchaseOrder).filter(
                models.DBPurchaseOrder.client_id == u.client_id,
                models.DBPurchaseOrder.status.in_(("Approved", "Closed"))).order_by(
                    models.DBPurchaseOrder.id.desc()).all()
            if norm_name(p.supplier_name) == key]


def _portal_bills(db, u, party, party_name):
    settled = settled_amounts(db, u.client_id)
    if u.party_type == "contractor":
        out = []
        for b in db.query(models.DBSubBill).filter(
                models.DBSubBill.client_id == u.client_id,
                models.DBSubBill.contractor_id == party.id,
                models.DBSubBill.status.in_(("SUBMITTED", "CERTIFIED", "PAID"))).order_by(
                    models.DBSubBill.id.desc()).all():
            got = settled.get(("sub_bill", b.id), 0.0)
            if b.status == "PAID" and not got:
                got = money(b.net_payable)
            out.append({"id": b.id, "number": b.number or "", "status": b.status,
                        "pdf": "/api/portal/bills/%d/document.pdf" % b.id,
                        "accepted_by": getattr(b, "accepted_by_name", "") or "",
                        "accepted_at": (getattr(b, "accepted_at", "") or "")[:10],
                        "can_accept": not (getattr(b, "accepted_by_name", "") or ""),
                        "where": {"SUBMITTED": "with the engineer to certify", "CERTIFIED": "passed for payment",
                                  "PAID": "paid"}[b.status],
                        "date": (b.certified_at or b.created_at or "")[:10],
                        "claimed": money(b.this_bill), "retention": money(b.retention_amount),
                        "deductions": money((b.advance_recovery or 0) + (b.other_deductions or 0) + (b.back_charges or 0)),
                        "tds": money(b.tds_amount), "gst": money(b.gst_amount),
                        "net": money(b.net_payable), "paid": money(got),
                        "left": money(max(0.0, (b.net_payable or 0) - got)) if b.status != "SUBMITTED" else 0.0})
        # Their retention, once released, is a sum passed for payment like a bill.
        for r in db.query(models.DBRetentionRelease).filter(
                models.DBRetentionRelease.client_id == u.client_id,
                models.DBRetentionRelease.side == "contractor",
                models.DBRetentionRelease.contractor_id == party.id,
                models.DBRetentionRelease.status.in_(("CERTIFIED", "PAID"))).order_by(
                    models.DBRetentionRelease.id.desc()).all():
            got = settled.get(("retention_release", r.id), 0.0)
            out.append({"id": r.id, "number": r.number or "", "status": r.status,
                        "where": "paid" if r.status == "PAID" else "retention released - passed for payment",
                        "date": r.release_on or "", "claimed": money(r.amount), "retention": 0.0,
                        "deductions": 0.0, "tds": 0.0, "gst": money(r.gst_amount),
                        "net": money(r.net_amount), "paid": money(got),
                        "left": money(max(0.0, (r.net_amount or 0) - got))})
        return out
    key = norm_name(party_name)
    out = []
    for b in db.query(models.DBBill).filter(models.DBBill.client_id == u.client_id).order_by(
            models.DBBill.id.desc()).all():
        if norm_name(b.vendor_name) != key or (b.status or "") in ("Cancelled",):
            continue
        rejected = (b.status or "") == "Rejected" or (b.approval_status or "") == "rejected"
        where = ("sent back" if rejected else "received - being checked" if (b.status or "") == "Draft"
                 else "waiting for approval" if (b.approval_status or "") == "pending"
                 else "paid" if (b.status or "") == "Paid" else "accepted for payment")
        paid = money(max(b.amount_paid or 0, settled.get(("supplier_bill", b.id), 0.0)))
        out.append({"id": b.id, "number": b.number or "", "status": b.status or "", "where": where,
                    "date": b.issue_date or "", "due": b.due_date or "",
                    "claimed": money(b.amount), "gst": money(b.tax_amount), "net": money(b.total or b.amount),
                    "paid": paid, "left": 0.0 if rejected or (b.status or "") == "Draft"
                    else money(max(0.0, (b.total or b.amount or 0) - paid)),
                    "note": (b.rejection_reason or "") if rejected else ""})
    return out


def _portal_statement(db, u, name, date_from="", date_to=""):
    opening, balance, out = 0.0, 0.0, []
    for r in _portal_ledger(db, u, name):
        change = money(r["billed"] - r["moved"])
        if date_from and (r["date"] or "") < date_from:
            opening = balance = money(opening + change)
            continue
        if date_to and (r["date"] or "") > date_to:
            continue
        balance = money(balance + change)
        out.append({"date": r["date"] or "", "kind": r["kind"], "number": r["number"] or "",
                    "against": r.get("against", ""), "reference": r.get("reference", ""),
                    "billed": money(r["billed"]), "paid": money(r["moved"]), "balance": balance})
    return {"opening": opening, "rows": out, "closing": balance}
