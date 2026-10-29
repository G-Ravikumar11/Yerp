"""A site's cash box (imprest): topped up by head office, spent on site, checked by accounts.

The site engineer holds the box and enters each payment from site with a photo of the bill. Accounts check it: approved,
it is booked as an expense voucher out of the box, charged to the site; rejected, it says why, and the cash is the
custodian's to account for. Head office tops the box back up to its float with a bank-to-cash transfer.

What the box should hold now is its book balance less what has been spent and not yet checked.
"""
from datetime import date, datetime

from fastapi import HTTPException

from app import models
from app.constants.money import EXPENSE_HEADS
from app.core.currency import inr, money
from app.core.permissions import employee_can


def can_manage(emp):
    """Accounts (and the Master) look after every box: set them up, check what is spent, top them up."""
    return emp is None or any(employee_can(emp, p) for p in ("bills.pay", "payments.approve", "payments.approve_high"))


def boxes_for(db, client_id, emp):
    """The cash boxes this person sees: every one for accounts, the ones they hold for a site engineer."""
    q = db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client_id,
                                              models.DBBankAccount.kind == "Cash",
                                              models.DBBankAccount.is_active.isnot(False))
    if not can_manage(emp):
        q = q.filter(models.DBBankAccount.custodian_id == emp.id)
    return q.order_by(models.DBBankAccount.name).all()


def box_or_404(db, client_id, emp, account_id):
    box = db.query(models.DBBankAccount).filter(models.DBBankAccount.id == account_id,
                                                models.DBBankAccount.client_id == client_id).first()
    if box is None or (box.kind or "") != "Cash":
        raise HTTPException(404, "That cash box is not on file.")
    if not can_manage(emp) and box.custodian_id != emp.id:
        raise HTTPException(403, "That cash box is held by somebody else.")
    return box


def pending_by_box(db, client_id):
    from sqlalchemy import func
    return {a: float(v or 0) for a, v in db.query(models.DBSiteCashExpense.account_id,
                                                  func.coalesce(func.sum(models.DBSiteCashExpense.amount), 0.0)).filter(
        models.DBSiteCashExpense.client_id == client_id, models.DBSiteCashExpense.status == "SUBMITTED").group_by(
        models.DBSiteCashExpense.account_id).all()}


def box_dict(db, box, balance, pending, names, jobs):
    in_hand = money(balance - pending)
    job = jobs.get(box.job_id)
    return {"id": box.id, "name": box.name or "", "job_id": box.job_id,
            "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "custodian_id": box.custodian_id, "custodian": names.get(box.custodian_id, ""),
            "imprest_amount": money(box.imprest_amount), "balance": money(balance), "pending": money(pending),
            "in_hand": in_hand,
            # The float topped back up: what the books say is missing from it, once what is pending is checked.
            "top_up": money(max(0.0, (box.imprest_amount or 0) - balance)) if box.imprest_amount else 0.0}


def next_number(db, client_id):
    top = 0
    for (number,) in db.query(models.DBSiteCashExpense.number).filter(models.DBSiteCashExpense.client_id == client_id).all():
        tail = (number or "")[4:]
        if tail.isdigit():
            top = max(top, int(tail))
    return "SCE-%04d" % (top + 1)


def submit(db, client, emp, who, box, body):
    """One payment out of the box, as the site made it."""
    amount = money(body.amount or 0)
    if amount <= 0:
        raise HTTPException(400, "How much?")
    head = next((h for h in EXPENSE_HEADS if h.lower() == (body.head or "").strip().lower()), "")
    if not head:
        raise HTTPException(400, "What was it for? One of: %s." % ", ".join(EXPENSE_HEADS))
    paid_to = (body.paid_to or "").strip()
    if not paid_to:
        raise HTTPException(400, "Paid to whom?")
    on = (body.spent_on or date.today().isoformat())[:10]
    if on > date.today().isoformat():
        raise HTTPException(400, "It cannot have been spent on a day still to come.")
    job_id = body.job_id or box.job_id
    if job_id and not db.query(models.DBJob.id).filter(models.DBJob.id == job_id, models.DBJob.client_id == client.id).first():
        raise HTTPException(404, "Project not found")
    x = models.DBSiteCashExpense(
        client_id=client.id, number=next_number(db, client.id), account_id=box.id, job_id=job_id, spent_on=on,
        head=head, paid_to=paid_to[:120], amount=amount, note=(body.note or "").strip()[:300],
        bill_no=(body.bill_no or "").strip()[:60], submitted_by=emp.id if emp is not None else None,
        submitted_by_name=who)
    db.add(x)
    db.flush()
    return x


def expense_or_404(db, client_id, expense_id):
    x = db.query(models.DBSiteCashExpense).filter(models.DBSiteCashExpense.id == expense_id,
                                                  models.DBSiteCashExpense.client_id == client_id).first()
    if x is None:
        raise HTTPException(404, "Site expense not found")
    return x


def decide(db, client, emp, who, x, decision, note=""):
    """Accounts' check. Approved, it is booked: an expense voucher out of the box, charged to the site. The cash has
    already gone, so this is not a payment waiting for approval - it is the bill for one already made."""
    from app.services.money import next_money_number
    if not can_manage(emp):
        raise HTTPException(403, "Accounts check what the site spent.")
    if emp is not None and x.submitted_by == emp.id:
        raise HTTPException(403, "What you spent yourself is checked by somebody else.")
    if x.status != "SUBMITTED":
        raise HTTPException(409, "%s is already %s." % (x.number, x.status.lower()))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if decision == "reject":
        reason = (note or "").strip()
        if not reason:
            raise HTTPException(400, "Say why it is not accepted.")
        x.status, x.checked_by_name, x.checked_at, x.reject_reason = "REJECTED", who, now, reason[:300]
        return "%s rejected: %s is for %s to account for." % (x.number, inr(x.amount), x.submitted_by_name or "the custodian")
    if decision != "approve":
        raise HTTPException(400, "Approve or reject.")
    e = models.DBMoneyEntry(
        client_id=client.id, number=next_money_number(db, client.id, "OUT"), direction="OUT", party_type="other",
        party_name=x.paid_to, doc_type="expense", doc_number="", job_id=x.job_id, account_id=x.account_id,
        amount=x.amount, paid_on=x.spent_on, mode="Cash", reference=(x.bill_no or x.number)[:80],
        note=("%s - %s" % (x.number, x.note) if x.note else x.number)[:300], head=x.head,
        recorded_by_name=x.submitted_by_name or who)
    db.add(e)
    db.flush()
    x.status, x.checked_by_name, x.checked_at, x.entry_id = "APPROVED", who, now, e.id
    return "%s approved and booked as %s: %s for %s." % (x.number, e.number, inr(x.amount), x.head.lower())


def expense_for_entry(db, entry_id):
    return db.query(models.DBSiteCashExpense).filter(models.DBSiteCashExpense.entry_id == entry_id).first()


def expense_dict(x, photos=None, names=None, jobs=None):
    job = (jobs or {}).get(x.job_id)
    return {"id": x.id, "number": x.number or "", "account_id": x.account_id, "job_id": x.job_id,
            "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "spent_on": x.spent_on or "", "head": x.head or "", "paid_to": x.paid_to or "", "amount": money(x.amount),
            "note": x.note or "", "bill_no": x.bill_no or "", "status": x.status, "submitted_by": x.submitted_by,
            "submitted_by_name": x.submitted_by_name or "", "submitted_at": x.submitted_at or "",
            "checked_by_name": x.checked_by_name or "", "checked_at": x.checked_at or "",
            "reject_reason": x.reject_reason or "", "entry_id": x.entry_id, "photo": (photos or {}).get(x.id)}
