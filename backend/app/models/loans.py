"""Loans the company has taken, and the instalments (EMIs) that repay them."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBLoan(Base):
    """A term loan, an equipment loan, a vehicle loan, a loan from a director (LN-0001). Money borrowed is a liability on its own
    ledger; each instalment repays part of the principal (to that ledger) and pays the rest as interest (an expense)."""
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)
    lender = Column(String, nullable=False)                         # the bank or person it was borrowed from
    name = Column(String, default="")                               # what it was for: "Excavator", "Working capital"
    kind = Column(String, default="secured")                        # secured | unsecured
    principal = Column(Float, nullable=False, default=0.0)          # what the schedule runs on: the amount received, or what was left on the as-on date
    annual_rate = Column(Float, default=0.0)                        # per cent a year, reducing balance
    emi = Column(Float, default=0.0)                                # the scheduled instalment
    first_due = Column(String, default="")
    # A loan taken before these books began has no money received to record: only what was left of it on `taken_on`.
    opening = Column(Boolean, default=False)
    taken_on = Column(String, default="", index=True)               # the day the money was received, or the day the balance stood at
    note = Column(String, default="")
    created_by_name = Column(String, default="")
    created_at = Column(String, default=_now)
    updated_at = Column(String, default="")


class DBLoanInstalment(Base):
    """One instalment of a loan. What it is worth is the principal it repays and the interest it costs; whether it is paid is what
    the money book says, set by the payment that settles it."""
    __tablename__ = "loan_instalments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False, default=1)
    number = Column(String, default="")                             # LN-0001 EMI 3/36: what the payment is entered against
    due_on = Column(String, nullable=False, index=True)
    principal = Column(Float, default=0.0)
    interest = Column(Float, default=0.0)
    status = Column(String, default="DUE", index=True)              # DUE | PAID
    paid_on = Column(String, default="")
