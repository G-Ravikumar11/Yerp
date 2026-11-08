"""Journal vouchers and debit notes to suppliers: the two entries the books need that move no money."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBJournal(Base):
    """A journal voucher (JV-0001): an adjustment between ledgers - a balance written off, a cost moved between sites, a
    TDS or GST correction. Raised by accounts, counted only once the Master approves it."""
    __tablename__ = "journal_vouchers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)
    voucher_date = Column(String, default="", index=True)
    narration = Column(Text, default="")
    status = Column(String, default="PENDING", index=True)        # PENDING | APPROVED | REJECTED | CANCELLED
    raised_by_name = Column(String, default="")
    raised_at = Column(String, default=_now)
    decided_by_name = Column(String, default="")
    decided_at = Column(String, default="")
    decision_note = Column(String, default="")


class DBJournalLine(Base):
    """One line of a journal: a party, an expense or income head, a bank or cash account, or one of the books' own ledgers
    (TDS receivable, retention, GST...). Debit or credit, never both; a project for the site it concerns."""
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    journal_id = Column(Integer, ForeignKey("journal_vouchers.id"), nullable=False, index=True)
    kind = Column(String, default="party")                          # party | head | account | ledger
    party_type = Column(String, default="")
    party_name = Column(String, default="")
    head = Column(String, default="")
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    ledger_key = Column(String, default="")
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    debit = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    note = Column(String, default="")
    display_order = Column(Integer, default=0)


class DBSupplierDebitNote(Base):
    """A debit note to a supplier (DN-0001): goods sent back, a price charged above the order, short supply, a penalty.
    It comes off what we owe them - off the bill it names, or off their account."""
    __tablename__ = "supplier_debit_notes"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)
    note_date = Column(String, default="", index=True)
    supplier_name = Column(String, default="", index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True, index=True)
    purchase_return_id = Column(Integer, ForeignKey("store_purchase_return.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    reason = Column(String, default="")
    taxable = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    status = Column(String, default="ISSUED", index=True)          # ISSUED | CANCELLED
    cancel_reason = Column(String, default="")
    raised_by_name = Column(String, default="")
    created_at = Column(String, default=_now)
