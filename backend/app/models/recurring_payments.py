"""Payments that fall due every month - rent, internet, hire, insurance - so they are not entered by hand each time."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBRecurringPayment(Base):
    """A payment that falls due on the same day every month. Each month a daily job raises an expense payment request for it,
    which goes through the company's usual approval and is paid like any other. It carries its own next due date, so a month
    missed while the app was down is raised when it is back, not lost."""
    __tablename__ = "recurring_payments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    payee = Column(String, nullable=False)                          # who is paid: the landlord, the ISP, the hire company
    head = Column(String, nullable=False)                           # the expense head it is booked under
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)       # the project it is charged to; none: head office
    amount = Column(Float, nullable=False, default=0.0)
    day_of_month = Column(Integer, nullable=False, default=1)       # 1 to 31; in a shorter month, its last day
    start_date = Column(String, default="")                         # no payment is raised before this day
    end_date = Column(String, default="")                           # none after this day; blank: until stopped
    next_due = Column(String, default="", index=True)               # the next day to raise it; blank once it has ended
    is_active = Column(Boolean, default=True, index=True)           # false: paused, or ended
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)      # the account it is usually paid from
    mode = Column(String, default="")
    note = Column(String, default="")
    raised_count = Column(Integer, default=0)
    last_raised_on = Column(String, default="")
    last_error = Column(String, default="")                         # why the last attempt to raise it failed, until one works
    created_by_name = Column(String, default="")
    created_at = Column(String, default=_now)
    updated_at = Column(String, default="")


class DBRecurringPaymentRun(Base):
    """A month that has been raised for a recurring payment, and the payment request it became: the record that stops one
    month being raised twice. Kept by number rather than by key, so deleting a request or a template leaves no tangle."""
    __tablename__ = "recurring_payment_runs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    recurring_id = Column(Integer, nullable=False, index=True)
    due_on = Column(String, nullable=False)
    request_id = Column(Integer, nullable=True, index=True)
    raised_at = Column(String, default=_now)
