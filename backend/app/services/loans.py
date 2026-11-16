"""Loans and EMIs: what the company has borrowed, and the instalments that repay it.

A loan is a liability on a ledger of its own. Each instalment repays some of the principal (to that ledger) and costs the
rest as interest (an expense), but it leaves the bank as one payment: the EMI. So an instalment is a document that a payment
settles - the same way a supplier's bill is - and the split is read from it by everything that needs it: Tally (a payment
voucher with the principal to the loan ledger and the interest to the interest head), the profit and loss (the interest),
the balance sheet (the principal still owed). Paying one is the ordinary payment: approval, the books lock, the bank
account, the voucher and the void all work as they do for a bill.

The money received on a new loan is recorded as a receipt against it. A loan that was already running when these books began
has no receipt: it carries only what was left of it on the day, as an opening balance.
"""
import re
from datetime import date

from fastapi import HTTPException

from app import models
from app.core import checks
from app.core.auth import owned_or_404
from app.constants.money import LOAN_INTEREST_HEAD as INTEREST_HEAD  # noqa: F401
from app.core.currency import money
from app.models.loans import DBLoan, DBLoanInstalment
from app.services.recurring_payments import following

KINDS = ("secured", "unsecured")
LARGEST = 100_000_000_000
MAX_MONTHS = 600                    # fifty years of instalments: a slip of the finger beyond that


def _name(raw):
    return re.sub(r"\s+", " ", raw or "").strip()


def ledger_name(loan):
    """The loan's own ledger in the books: named for who lent and what for, and prefixed so it is never mistaken for a party."""
    return ("Loan - %s%s" % (loan.lender, (" - " + loan.name) if loan.name else ""))[:100]


def ledger_group(loan):
    return "Secured Loans" if loan.kind == "secured" else "Unsecured Loans"


def next_number(db, client_id):
    top = 0
    for (n,) in db.query(DBLoan.number).filter(DBLoan.client_id == client_id).all():
        tail = (n or "")[3:]
        if tail.isdigit():
            top = max(top, int(tail))
    return "LN-%04d" % (top + 1)


# --- the schedule ---------------------------------------------------------------------------------------------------------

def build_schedule(principal, annual_rate, months, first_due, emi=None):
    """The instalments of a reducing-balance loan: [(due date, principal, interest)] and the EMI they were worked out at.

    Interest each month is the balance times the rate over twelve. The EMI is the standard one unless the bank's own is given;
    the last instalment clears whatever is left, so rounding never leaves a few paise owing (or a few paise overpaid)."""
    r = annual_rate / 1200.0
    if not emi:
        emi = principal / months if r == 0 else principal * r * (1 + r) ** months / ((1 + r) ** months - 1)
    emi = money(emi)
    if r > 0 and emi <= money(principal * r) + 0.004:
        raise HTTPException(400, "An instalment of %s does not even cover the first month's interest of %s, so the loan would never be repaid."
                                 % (emi, money(principal * r)))
    rows, balance, due = [], money(principal), first_due
    for i in range(months):
        interest = money(balance * r)
        repay = balance if (i == months - 1 or emi - interest >= balance) else money(emi - interest)
        rows.append((due, money(repay), interest))
        balance = money(balance - repay)
        if balance <= 0.004:
            break
        due = following(due, first_due.day)
    return rows, emi


def create_loan(db, client_id, body, who):
    """Check the form and make the loan with its instalments. Returns (loan, instalments); the money received is recorded by the caller."""
    from app.services.money import refuse_if_locked
    lender = _name(body.lender)
    if not lender:
        raise HTTPException(400, "Who is it borrowed from?")
    if len(lender) > 120:
        raise HTTPException(400, "The lender's name is too long.")
    if (body.kind or "secured") not in KINDS:
        raise HTTPException(400, "A loan is secured or unsecured.")
    principal = checks.between(body.principal, "loan amount", 0, LARGEST, unit="rupees", blank_ok=False)
    if money(principal) <= 0:
        raise HTTPException(400, "The amount has to be more than nothing.")
    rate = checks.between(body.annual_rate if body.annual_rate is not None else 0, "interest rate", 0, 100, unit="per cent a year", blank_ok=False)
    months = int(body.months or 0)
    if not 1 <= months <= MAX_MONTHS:
        raise HTTPException(400, "The number of instalments is from 1 to %d." % MAX_MONTHS)
    existing = bool(body.existing)
    taken_on = checks.day(body.taken_on, "as-on date" if existing else "date the money was received", required=True, not_future=True)
    first_due = checks.day(body.first_due, "first instalment date", required=True)
    if first_due <= taken_on and not existing:
        raise HTTPException(400, "The first instalment falls after the money was received.")
    if first_due < taken_on:
        raise HTTPException(400, "The first instalment falls on or after the day the balance stood at.")
    if not existing:
        if not body.account_id:
            raise HTTPException(400, "Which account was the money paid into? Pick it, so the loan and the bank book agree. "
                                     "A loan taken before these books began is entered as already running.")
        owned_or_404(db, models.DBBankAccount, client_id, body.account_id, "Account")
    refuse_if_locked(db, client_id, taken_on, "booked")
    rows, emi = build_schedule(money(principal), rate, months, date.fromisoformat(first_due), money(body.emi) if body.emi else None)
    name = _name(body.name)[:120]
    for other in db.query(DBLoan).filter(DBLoan.client_id == client_id, DBLoan.lender == lender, DBLoan.name == name,
                                         DBLoan.principal == money(principal), DBLoan.taken_on == taken_on).all():
        raise HTTPException(409, "%s (%s) is already entered with the same lender, purpose, amount and date. Open that one instead of entering it twice."
                            % (other.number, other.name or other.lender))
    loan = DBLoan(client_id=client_id, number=next_number(db, client_id), lender=lender, name=name, kind=body.kind or "secured",
                  principal=money(principal), annual_rate=rate, emi=emi, first_due=first_due, opening=existing, taken_on=taken_on,
                  note=_name(body.note)[:300], created_by_name=who)
    db.add(loan)
    db.flush()
    made = [DBLoanInstalment(client_id=client_id, loan_id=loan.id, seq=i, number="%s EMI %d/%d" % (loan.number, i, len(rows)),
                             due_on=d.isoformat(), principal=p, interest=it, status="DUE") for i, (d, p, it) in enumerate(rows, 1)]
    db.add_all(made)
    db.flush()
    return loan, made


# --- reading them ---------------------------------------------------------------------------------------------------------

def loan_or_404(db, client_id, loan_id):
    loan = db.query(DBLoan).filter(DBLoan.id == loan_id, DBLoan.client_id == client_id).first()
    if not loan:
        raise HTTPException(404, "Loan not found")
    return loan


def instalment_or_404(db, client_id, instalment_id):
    i = db.query(DBLoanInstalment).filter(DBLoanInstalment.id == instalment_id, DBLoanInstalment.client_id == client_id).first()
    if not i:
        raise HTTPException(404, "Instalment not found")
    return i


def instalment_dict(i, today):
    late = (today - date.fromisoformat(i.due_on)).days if i.status != "PAID" and i.due_on < today.isoformat() else 0
    return {"id": i.id, "seq": i.seq, "number": i.number, "due_on": i.due_on, "principal": money(i.principal), "interest": money(i.interest),
            "total": money((i.principal or 0) + (i.interest or 0)), "status": i.status, "paid_on": i.paid_on or "", "overdue": late > 0, "days_late": late}


def disbursed_ids(db, client_id):
    """The loans whose money received is on the books (and not voided)."""
    return {d for (d,) in db.query(models.DBMoneyEntry.doc_id).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.doc_type == "loan_disbursal",
        models.DBMoneyEntry.voided.is_(False), models.DBMoneyEntry.doc_id.isnot(None)).all()}


def list_loans(db, client_id, today=None):
    today = today or date.today()
    loans = db.query(DBLoan).filter(DBLoan.client_id == client_id).order_by(DBLoan.id.desc()).all()
    by = {}
    for i in db.query(DBLoanInstalment).filter(DBLoanInstalment.client_id == client_id).order_by(DBLoanInstalment.loan_id, DBLoanInstalment.seq).all():
        by.setdefault(i.loan_id, []).append(i)
    got = disbursed_ids(db, client_id)
    return [loan_dict(l, by.get(l.id, []), today, l.opening or l.id in got) for l in loans]


def loan_dict(loan, instalments, today, received=True, detail=False):
    paid = [i for i in instalments if i.status == "PAID"]
    open_ = [i for i in instalments if i.status != "PAID"]
    repaid = money(sum(i.principal or 0 for i in paid))
    nxt = min(open_, key=lambda i: (i.due_on, i.seq), default=None)
    out = {"id": loan.id, "number": loan.number, "lender": loan.lender, "name": loan.name or "", "kind": loan.kind, "ledger": ledger_name(loan),
           "principal": money(loan.principal), "annual_rate": loan.annual_rate or 0.0, "emi": money(loan.emi), "first_due": loan.first_due,
           "existing": bool(loan.opening), "taken_on": loan.taken_on, "note": loan.note or "", "created_by_name": loan.created_by_name or "",
           "instalments": len(instalments), "paid": len(paid), "repaid": repaid, "outstanding": money(max(0.0, (loan.principal or 0) - repaid)),
           "interest_paid": money(sum(i.interest or 0 for i in paid)), "interest_to_come": money(sum(i.interest or 0 for i in open_)),
           "status": "CLOSED" if instalments and not open_ else "ACTIVE", "received": bool(received),
           "next": instalment_dict(nxt, today) if nxt else None, "overdue": sum(1 for i in open_ if i.due_on < today.isoformat())}
    if detail:
        out["schedule"] = [instalment_dict(i, today) for i in instalments]
    return out


# --- what the books need --------------------------------------------------------------------------------------------------

def loans_outstanding(db, client_id):
    """What is still owed on loans: the principal less what the instalments paid have repaid. A loan taken in these books counts
    once the money received is on them, so the liability and the bank agree."""
    repaid = {}
    for loan_id, p in db.query(DBLoanInstalment.loan_id, DBLoanInstalment.principal).filter(
            DBLoanInstalment.client_id == client_id, DBLoanInstalment.status == "PAID").all():
        repaid[loan_id] = repaid.get(loan_id, 0.0) + (p or 0)
    got = disbursed_ids(db, client_id)
    return money(sum(max(0.0, (l.principal or 0) - repaid.get(l.id, 0.0)) for l in db.query(DBLoan).filter(DBLoan.client_id == client_id).all()
                     if l.opening or l.id in got))


def interest_paid_entries(db, client_id):
    """(day paid, interest) for every instalment paid and not voided: the interest is the expense, the rest repaid the loan."""
    return [(on or "", money(interest)) for on, interest in db.query(models.DBMoneyEntry.paid_on, DBLoanInstalment.interest).join(
        DBLoanInstalment, DBLoanInstalment.id == models.DBMoneyEntry.doc_id).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.doc_type == "loan_instalment",
        models.DBMoneyEntry.voided.is_(False)).all()]


def due_instalments(db, client_id, today, days=7):
    """(due within the next `days` days, overdue): [(loan, instalment)] each, soonest first. An instalment paid is neither."""
    horizon = date.fromordinal(today.toordinal() + days).isoformat()
    loans = {l.id: l for l in db.query(DBLoan).filter(DBLoan.client_id == client_id).all()}
    rows = db.query(DBLoanInstalment).filter(DBLoanInstalment.client_id == client_id, DBLoanInstalment.status != "PAID",
                                             DBLoanInstalment.due_on <= horizon).order_by(DBLoanInstalment.due_on, DBLoanInstalment.id).all()
    soon = [(loans[i.loan_id], i) for i in rows if i.loan_id in loans and i.due_on >= today.isoformat()]
    late = [(loans[i.loan_id], i) for i in rows if i.loan_id in loans and i.due_on < today.isoformat()]
    return soon, late
