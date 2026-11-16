"""Paying an approved expense claim with the salary.

Accounts put an approved claim "on the salary". The next payslip made for that person then carries the claim's unpaid
amount as a reimbursement: it is added to the net pay but not to the gross, so no PF, ESI or tax is worked on it. When
the payslip is released (marked paid, on its own or with its month) the claim is settled by an adjustment payment
entry, the same document Accounts would have entered by hand, so the staff ledger and the claim list agree. A payslip
taken back (reopened or deleted) voids the entry and the claim is owed again.
"""
from datetime import date

from fastapi import HTTPException

from app import models
from app.core.currency import money
from app.models.payouts import DBExpenseClaim
from app.services.money import _settle_doc, next_money_number
from app.services.payouts import claim_left

NOTE = "Expense claim %s paid with salary on payslip %s"


def queued(db, client_id, employee_id):
    """Approved claims waiting for this person's next payslip, with something still to pay."""
    rows = db.query(DBExpenseClaim).filter(
        DBExpenseClaim.client_id == client_id, DBExpenseClaim.employee_id == employee_id,
        DBExpenseClaim.status == "APPROVED", DBExpenseClaim.pay_with_salary.is_(True),
        DBExpenseClaim.payslip_id.is_(None)).order_by(DBExpenseClaim.id).all()
    return [c for c in rows if claim_left(db, c) > 0.009]


def total(db, claims):
    return money(sum(claim_left(db, c) for c in claims))


def set_queue(db, c, on):
    """Put an approved claim on the salary, or take it off again while no payslip has picked it up."""
    if c.payslip_id:
        raise HTTPException(409, "%s is already on a payslip. Reopen or delete that payslip to change it." % c.number)
    if on:
        if c.status != "APPROVED":
            raise HTTPException(409, "%s is %s; only an approved claim is paid with salary." % (c.number, (c.status or "").lower()))
        if claim_left(db, c) <= 0.009:
            raise HTTPException(409, "%s has nothing left to pay." % c.number)
    c.pay_with_salary = bool(on)


def attach(db, ps, claims):
    """Link the claims to the payslip they were added to (flushes it first to have its id)."""
    db.flush()
    for c in claims:
        c.payslip_id = ps.id
        c.salary_amount = claim_left(db, c)


def on_payslip(db, ps):
    return db.query(DBExpenseClaim).filter(DBExpenseClaim.client_id == ps.client_id, DBExpenseClaim.payslip_id == ps.id).all()


def settle_on_release(db, client_id, slips, by_name):
    """One adjustment payment per claim on each released payslip; the claim becomes SETTLED. Adds, never commits."""
    made = []
    today = date.today().isoformat()
    for ps in slips:
        for c in on_payslip(db, ps):
            if c.salary_entry_id or c.status != "APPROVED":
                continue
            amount = money(c.salary_amount or 0)
            if amount <= 0:
                continue
            e = models.DBMoneyEntry(
                client_id=client_id, number=next_money_number(db, client_id, "OUT"), direction="OUT", party_type="staff",
                party_name=c.employee_name, party_id=c.employee_id, doc_type="expense_claim", doc_id=c.id, doc_number=c.number,
                job_id=c.job_id, account_id=None, amount=amount, paid_on=today, mode="Adjustment", reference=ps.number or "",
                note=NOTE % (c.number, ps.number or ""), recorded_by_name=by_name or "")
            db.add(e)
            db.flush()
            c.salary_entry_id = e.id
            _settle_doc(db, client_id, "expense_claim", c, money((c.amount or 0) - (c.against_advance or 0)), today)
            made.append(e)
    return made


def undo(db, client_id, ps, why, keep_link):
    """A payslip taken back: void the claim payments it made so each claim is owed again. With keep_link (a reopened
    payslip) the claims stay on it for its next release; without (deleted) they go back on the queue."""
    for c in on_payslip(db, ps):
        if c.salary_entry_id:
            e = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == c.salary_entry_id,
                                                     models.DBMoneyEntry.client_id == client_id).first()
            c.salary_entry_id = None
            if e and not e.voided:
                e.voided, e.void_reason = True, (why or "")[:300]
            if c.status == "SETTLED":
                c.status = "APPROVED"
        if not keep_link:
            c.payslip_id, c.salary_amount = None, 0.0
