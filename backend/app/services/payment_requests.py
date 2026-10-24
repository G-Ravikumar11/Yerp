"""Payments that wait for a signature before they are made.

A bill approved is a bill owed, not a bill to be paid today. What goes out is the accounts head's call, and a large
payment the MD's too: accounts raise a payment request, the accounts head checks it, the MD releases it when it is over
the limit, and only a released request is paid. The Master pays without asking - the Master is who would be asked.
Nobody checks their own request.

Off until the company turns it on, so nothing changes for a business that does not work this way.
"""
from datetime import datetime

from fastapi import HTTPException

from app import models
from app.core.currency import inr, money
from app.core.permissions import employee_can
from app.core.tenant_settings import tenant_setting
from app.constants.money import EXPENSE_HEADS, PARTY_TYPES

ON_KEY, FREE_KEY, MD_KEY = "payment_approval", "payment_free_below", "payment_md_above"
OPEN = ("PENDING", "AWAITING_MD", "APPROVED")          # asked for and not yet paid, refused or withdrawn
STATUS_LABEL = {"PENDING": "With the accounts head", "AWAITING_MD": "With the MD", "APPROVED": "Approved - to pay",
                "PAID": "Paid", "REJECTED": "Rejected", "CANCELLED": "Withdrawn"}


def _num(value, default):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def approval_rules(db, client_id):
    """Whether payments wait for approval, up to what amount they need none, and above what the MD signs too."""
    return {"on": str(tenant_setting(db, client_id, ON_KEY, "")).strip().lower() in ("1", "true", "yes", "on"),
            "free_below": _num(tenant_setting(db, client_id, FREE_KEY, "0"), 0.0),
            "md_above": _num(tenant_setting(db, client_id, MD_KEY, "100000"), 100000.0)}


def save_rules(db, client_id, on, free_below, md_above):
    for key, value in ((ON_KEY, "true" if on else "false"), (FREE_KEY, str(money(free_below or 0))),
                       (MD_KEY, str(money(md_above or 0)))):
        row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id,
                                                 models.DBSettings.key == key).first()
        if row:
            row.value = value
        else:
            db.add(models.DBSettings(client_id=client_id, key=key, value=value, description="Payment approval"))


def needs_request(db, client_id, emp, amount):
    """Whether a payment of `amount` by this person has to go through a request first. The Master never does."""
    rules = approval_rules(db, client_id)
    return bool(rules["on"] and emp is not None and money(amount) > rules["free_below"])


def can_check(emp):
    return emp is None or employee_can(emp, "payments.approve") or employee_can(emp, "payments.approve_high")


def can_release(emp):
    return emp is None or employee_can(emp, "payments.approve_high")


def next_request_number(db, client_id):
    top = 0
    for (number,) in db.query(models.DBPaymentRequest.number).filter(models.DBPaymentRequest.client_id == client_id).all():
        tail = (number or "")[4:]
        if tail.isdigit():
            top = max(top, int(tail))
    return "PRQ-%04d" % (top + 1)


def asked_on_doc(db, client_id, doc_type, doc_id, but=None):
    """What is already asked for against a bill and not yet paid, refused or withdrawn."""
    q = db.query(models.DBPaymentRequest).filter(
        models.DBPaymentRequest.client_id == client_id, models.DBPaymentRequest.doc_type == doc_type,
        models.DBPaymentRequest.doc_id == doc_id, models.DBPaymentRequest.status.in_(OPEN))
    if but:
        q = q.filter(models.DBPaymentRequest.id != but)
    return money(sum(r.amount or 0 for r in q.all()))


def raise_request(db, client, emp, actor_name, body):
    """A request to pay a bill (or part of it), an advance on account, or an expense."""
    from app.services.crm import settled_on
    from app.services.money import _doc_for
    amount = money(body.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "How much?")
    doc_type = (body.doc_type or "on_account").strip()
    head, doc, doc_number, party_id = "", None, "", None
    if doc_type == "expense":
        head = next((h for h in EXPENSE_HEADS if h.lower() == (body.head or "").strip().lower()), "")
        if not head:
            raise HTTPException(400, "Book it under one of: %s." % ", ".join(EXPENSE_HEADS))
        party_type, party_name = "other", (body.party_name or "").strip()
        job_id = body.job_id or None
    elif doc_type == "on_account":
        party_type = body.party_type if body.party_type in PARTY_TYPES else "other"
        party_name, job_id = (body.party_name or "").strip(), body.job_id or None
    else:
        if not body.doc_id:
            raise HTTPException(400, "Which bill is this for?")
        doc, worth, direction, party_type, party_name, party_id, job_id = _doc_for(db, client.id, doc_type, body.doc_id)
        if direction != "OUT":
            raise HTTPException(400, "Money coming in needs no approval; record it as received.")
        left = money(worth - settled_on(db, client.id, doc_type, doc.id) - asked_on_doc(db, client.id, doc_type, doc.id))
        if amount > left + 0.009:
            raise HTTPException(400, "%s has only %s left that is not paid or already asked for; %s is more than that."
                                     % (doc.number, inr(max(left, 0)), inr(amount)))
        doc_number = doc.number or ""
    if not party_name:
        raise HTTPException(400, "Paid to whom?")
    if job_id and not db.query(models.DBJob.id).filter(models.DBJob.id == job_id,
                                                       models.DBJob.client_id == client.id).first():
        raise HTTPException(404, "Project not found")
    r = models.DBPaymentRequest(
        client_id=client.id, number=next_request_number(db, client.id), doc_type=doc_type,
        doc_id=doc.id if doc else None, doc_number=doc_number, party_type=party_type, party_name=party_name,
        party_id=party_id, job_id=job_id, head=head, amount=amount, account_id=body.account_id or None,
        mode=(body.mode or "").strip()[:30], note=(body.note or "").strip()[:300],
        requested_by=emp.id if emp is not None else None, requested_by_name=actor_name)
    db.add(r)
    db.flush()
    return r


def request_or_404(db, client_id, request_id):
    r = db.query(models.DBPaymentRequest).filter(models.DBPaymentRequest.id == request_id,
                                                 models.DBPaymentRequest.client_id == client_id).first()
    if r is None:
        raise HTTPException(404, "Payment request not found")
    return r


def decide(db, client, emp, actor_name, r, decision, note=""):
    """Approve or reject, at whichever step the request stands. Over the MD's limit, the accounts head's approval
    sends it on to the MD; somebody who may release it themselves approves it in one go."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if r.status not in ("PENDING", "AWAITING_MD"):
        raise HTTPException(409, "%s is %s; there is nothing to decide." % (r.number, STATUS_LABEL.get(r.status, r.status).lower()))
    allowed = can_check(emp) if r.status == "PENDING" else can_release(emp)
    if not allowed:
        raise HTTPException(403, "Your access does not include %s payments." % (
            "checking" if r.status == "PENDING" else "releasing large"))
    if emp is not None and r.requested_by == emp.id:
        raise HTTPException(403, "Your own request is approved by somebody else.")
    if decision == "reject":
        reason = (note or "").strip()
        if not reason:
            raise HTTPException(400, "Say why it is rejected.")
        r.status, r.rejected_by_name, r.reject_reason = "REJECTED", actor_name, reason[:300]
        return "%s rejected." % r.number
    if decision != "approve":
        raise HTTPException(400, "Approve or reject.")
    if r.status == "PENDING":
        r.checked_by_name, r.checked_at = actor_name, now
        md_above = approval_rules(db, client.id)["md_above"]
        if md_above and money(r.amount) > md_above and not can_release(emp):
            r.status = "AWAITING_MD"
            return "%s checked; over %s, so it goes to the MD." % (r.number, inr(md_above))
    r.status, r.approved_by_name, r.approved_at = "APPROVED", actor_name, now
    return "%s approved: %s to %s can be paid." % (r.number, inr(r.amount), r.party_name)


def cancel(db, client, emp, r):
    if r.status not in OPEN:
        raise HTTPException(409, "%s is %s." % (r.number, STATUS_LABEL.get(r.status, r.status).lower()))
    if emp is not None and r.requested_by != emp.id and not can_check(emp):
        raise HTTPException(403, "Only whoever asked for it, or the accounts head, withdraws a request.")
    r.status = "CANCELLED"
    return "%s withdrawn." % r.number


def _same_name(a, b):
    return " ".join((a or "").lower().split()) == " ".join((b or "").lower().split())


def lock_to_request(db, client_id, body):
    """Paying an approved request: what is paid, to whom, for which project and under which head are what was approved.
    The payer chooses only how and when (date, mode, reference, account) and may pay less, never more. A payee, project
    or head sent that differs from the approval is refused rather than quietly replaced, so nobody believes they paid
    someone else; the approved ones are then filled in for whatever was left out."""
    r = request_or_404(db, client_id, body.request_id)
    if r.status != "APPROVED":
        raise HTTPException(409, "%s is %s, not approved to pay." % (r.number, STATUS_LABEL.get(r.status, r.status).lower()))
    approved_type = r.doc_type or "on_account"
    if (body.doc_type or "on_account").strip() != approved_type or (body.doc_id or None) != (r.doc_id or None):
        raise HTTPException(400, "%s was approved for something else." % r.number)
    changed = []
    if (body.party_name or "").strip() and not _same_name(body.party_name, r.party_name):
        changed.append("payee")
    elif approved_type == "on_account" and (body.party_type or "").strip() and body.party_type != (r.party_type or "other"):
        changed.append("payee")
    if body.job_id and body.job_id != r.job_id:
        changed.append("project")
    if (body.head or "").strip() and not _same_name(body.head, r.head):
        changed.append("head")
    if (body.direction or "").strip() and body.direction.strip().upper() != "OUT":
        changed.append("direction")
    if changed:
        what = " and ".join(changed)
        raise HTTPException(409, "%s was approved to pay %s%s. The %s cannot be changed when it is paid - raise a new request for that."
                                 % (r.number, r.party_name or "the payee", (" under " + r.head) if r.head else "", what))
    body.party_name, body.party_type, body.job_id, body.head, body.direction = r.party_name, r.party_type or "other", r.job_id, r.head, "OUT"
    return r


def use_for_payment(db, client_id, request_id, doc_type, doc_id, amount, party_name=None, job_id=None):
    """The approved request a payment settles: the same bill (or the same kind of payment), the same payee and project,
    no more than was approved. A bill's payee or project changed since the approval stops the payment."""
    r = request_or_404(db, client_id, request_id)
    if r.status != "APPROVED":
        raise HTTPException(409, "%s is %s, not approved to pay." % (r.number, STATUS_LABEL.get(r.status, r.status).lower()))
    if (r.doc_type or "") != (doc_type or "on_account") or (r.doc_id or None) != (doc_id or None):
        raise HTTPException(400, "%s was approved for something else." % r.number)
    if party_name is not None and not _same_name(party_name, r.party_name):
        raise HTTPException(409, "%s was approved to pay %s, not %s. Raise a new request." % (r.number, r.party_name, party_name))
    if job_id is not None and (job_id or None) != (r.job_id or None):
        raise HTTPException(409, "%s was approved for another project. Raise a new request." % r.number)
    if money(amount) > money(r.amount) + 0.009:
        raise HTTPException(400, "%s approved %s; %s is more than that." % (r.number, inr(r.amount), inr(amount)))
    return r


def request_for_entry(db, entry_id):
    return db.query(models.DBPaymentRequest).filter(models.DBPaymentRequest.entry_id == entry_id).first()


def request_dict(r, accounts=None, jobs=None):
    acc = (accounts or {}).get(r.account_id)
    job = (jobs or {}).get(r.job_id)
    return {"id": r.id, "number": r.number or "", "doc_type": r.doc_type or "", "doc_id": r.doc_id,
            "doc_number": r.doc_number or "", "party_type": r.party_type or "", "party_name": r.party_name or "",
            "job_id": r.job_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "head": r.head or "", "amount": money(r.amount), "account_id": r.account_id,
            "account": acc.name if acc else "", "mode": r.mode or "", "note": r.note or "",
            "status": r.status, "status_label": STATUS_LABEL.get(r.status, r.status),
            "requested_by": r.requested_by, "requested_by_name": r.requested_by_name or "",
            "requested_at": r.requested_at or "", "checked_by_name": r.checked_by_name or "",
            "checked_at": r.checked_at or "", "approved_by_name": r.approved_by_name or "",
            "approved_at": r.approved_at or "", "rejected_by_name": r.rejected_by_name or "",
            "reject_reason": r.reject_reason or "", "entry_id": r.entry_id}
