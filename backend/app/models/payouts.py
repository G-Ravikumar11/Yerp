"""Paying out: bank payment files, cheque books and post-dated cheques, and staff expense claims."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBPaymentBatch(Base):
    """A bank payment file (PB-0001): bills chosen to be paid together from one of our bank accounts, written out in that
    bank's bulk-upload layout. Uploaded at the bank, then marked paid here - which records each payment in the bank book."""
    __tablename__ = "payment_batches"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False)
    bank_format = Column(String, default="csv")                     # hdfc | icici | sbi | axis | csv
    pay_on = Column(String, default="")
    status = Column(String, default="DRAFT", index=True)            # DRAFT | PAID | CANCELLED
    note = Column(String, default="")
    made_by_name = Column(String, default="")
    made_at = Column(String, default=_now)
    paid_by_name = Column(String, default="")
    paid_at = Column(String, default="")


class DBPaymentBatchLine(Base):
    __tablename__ = "payment_batch_lines"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("payment_batches.id"), nullable=False, index=True)
    doc_type = Column(String, default="")                           # supplier_bill | sub_bill | expense_claim | on_account
    doc_id = Column(Integer, nullable=True)
    doc_number = Column(String, default="")
    request_id = Column(Integer, nullable=True)                     # the approved payment request it pays, where payments need one
    party_type = Column(String, default="")
    party_name = Column(String, default="")
    job_id = Column(Integer, nullable=True)
    amount = Column(Float, default=0.0)
    beneficiary_account = Column(String, default="")
    beneficiary_ifsc = Column(String, default="")
    beneficiary_bank = Column(String, default="")
    beneficiary_email = Column(String, default="")
    status = Column(String, default="READY")                        # READY | PAID | FAILED
    error = Column(String, default="")
    entry_id = Column(Integer, nullable=True)


class DBChequeBook(Base):
    """A cheque book from the bank: its leaves, numbered first to last. Every leaf is written (a cheque in the bank book or
    a post-dated cheque given), spoilt, or still blank."""
    __tablename__ = "cheque_books"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False, index=True)
    first_no = Column(Integer, default=0)
    last_no = Column(Integer, default=0)
    received_on = Column(String, default="")
    note = Column(String, default="")
    created_at = Column(String, default=_now)


class DBChequeSpoilt(Base):
    """A leaf torn up, written wrong or lost - kept so the book accounts for every number."""
    __tablename__ = "cheque_spoilt"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("cheque_books.id"), nullable=False, index=True)
    number = Column(Integer, default=0)
    reason = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPostDatedCheque(Base):
    """A cheque dated ahead: one we have given (ISSUED) or one we hold (RECEIVED). Not money yet. On its date it is
    presented (ours) or deposited (theirs), and only then goes in the bank book as a payment or a receipt."""
    __tablename__ = "post_dated_cheques"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    direction = Column(String, default="OUT", index=True)          # OUT = we gave it | IN = we hold it
    cheque_no = Column(String, default="")
    cheque_date = Column(String, default="", index=True)
    drawn_on = Column(String, default="")                           # the payer's bank, for one we hold
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)   # our account: drawn on (OUT) / to deposit in (IN)
    party_type = Column(String, default="")
    party_name = Column(String, default="")
    doc_type = Column(String, default="")                           # the bill it is for, when there is one
    doc_id = Column(Integer, nullable=True)
    doc_number = Column(String, default="")
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    amount = Column(Float, default=0.0)
    note = Column(String, default="")
    status = Column(String, default="HELD", index=True)             # HELD | BANKED | RETURNED | CANCELLED
    entry_id = Column(Integer, nullable=True)
    closed_reason = Column(String, default="")
    made_by_name = Column(String, default="")
    created_at = Column(String, default=_now)


class DBExpenseClaim(Base):
    """A member of staff's own money spent for the company - a bus fare, a meal on site, a part bought in town - claimed
    back with the bill (EC-0001). Approved, it is owed to them (and a cost of the project); reimbursed, or set against
    an advance they hold, it is settled."""
    __tablename__ = "expense_claims"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    employee_name = Column(String, default="")
    spent_on = Column(String, default="")
    head = Column(String, default="")
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    amount = Column(Float, default=0.0)
    description = Column(Text, default="")
    bill_no = Column(String, default="")
    status = Column(String, default="SUBMITTED", index=True)        # SUBMITTED | APPROVED | REJECTED | SETTLED | CANCELLED
    submitted_at = Column(String, default=_now)
    decided_by_name = Column(String, default="")
    decided_at = Column(String, default="")
    decision_note = Column(String, default="")
    against_advance = Column(Float, default=0.0)                    # what was set against an advance they held
