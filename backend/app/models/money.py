"""Bank accounts, money in and out, and retention released."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBBankAccount(Base):
    """A bank account or a cash box - wherever money is kept."""
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, default="")               # "SBI current", "Site cash - Vizag"
    kind = Column(String, default="Bank")           # Bank | Cash
    bank_name = Column(String, default="")
    account_no = Column(String, default="")
    ifsc = Column(String, default="")
    opening_balance = Column(Float, default=0.0)
    opening_date = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # A site's cash box (imprest): the site it is for, who holds it, and the float it is topped back up to.
    job_id = Column(Integer, nullable=True, index=True)
    custodian_id = Column(Integer, nullable=True, index=True)
    imprest_amount = Column(Float, default=0.0)


class DBMoneyEntry(Base):
    """One movement of money: a receipt from a client or a payment out.

    Never edited and never deleted. A mistake is voided, with a reason, and
    the bill it settled goes back to owing what it owed - because a ledger
    that can be rubbed out is not a ledger.
    """
    __tablename__ = "money_entries"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)     # RCT-0001 / PMT-0001
    direction = Column(String, default="IN", index=True)  # IN | OUT
    party_type = Column(String, default="", index=True)   # client | supplier | contractor | other
    party_name = Column(String, default="", index=True)
    party_id = Column(Integer, nullable=True, index=True)
    doc_type = Column(String, default="", index=True)     # ra_bill | sub_bill | supplier_bill | on_account
    doc_id = Column(Integer, nullable=True, index=True)
    doc_number = Column(String, default="")
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True, index=True)
    amount = Column(Float, default=0.0)
    paid_on = Column(String, default="", index=True)
    mode = Column(String, default="Bank transfer")        # Bank transfer | Cheque | Cash | UPI | Adjustment
    reference = Column(String, default="")               # UTR, cheque number
    note = Column(String, default="")
    voided = Column(Boolean, default=False, index=True)
    void_reason = Column(String, default="")
    recorded_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # An expense or sundry receipt: the head it is booked under (EXPENSE_HEADS / INCOME_HEADS).
    head = Column(String, default="")
    # A transfer between our own accounts is two entries, one out of each side and one into the other; each names the other.
    pair_id = Column(Integer, nullable=True, index=True)
    # The day the bank actually moved the money (a cheque clears days after it is written), and the statement line
    # it was matched to. Blank until it shows on the bank's statement.
    cleared_on = Column(String, default="")
    statement_line_id = Column(Integer, nullable=True, index=True)


# RETENTION RELEASED
#
# Retention is held on every certified bill, both ways: the client holds it
# from us, and we hold it from the contractors. A release is the document that
# brings it back - a claim on the client at practical completion or at the
# end of the defects period, or a payment due to a contractor. It carries the GST
# the bills did not, because each bill charged tax only on what it asked for.
class DBRetentionRelease(Base):
    __tablename__ = "retention_releases"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    side = Column(String, default="client", index=True)      # client | contractor
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    sub_order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)

    number = Column(String, default="", index=True)
    stage = Column(String, default="")
    release_on = Column(String, default="")
    amount = Column(Float, default=0.0)            # the retention given back
    gst_percent = Column(Float, default=0.0)
    gst_amount = Column(Float, default=0.0)
    cgst_amount = Column(Float, default=0.0)
    sgst_amount = Column(Float, default=0.0)
    igst_amount = Column(Float, default=0.0)
    place_of_supply = Column(String, default="")
    net_amount = Column(Float, default=0.0)        # what moves: the release and its tax

    # CERTIFIED (due) | PAID | CANCELLED
    # SUBMITTED (a contractor's retention raised by staff, waiting for somebody else to certify it) | CERTIFIED |
    # PAID | CANCELLED
    status = Column(String, default="CERTIFIED", index=True)
    raised_by = Column(Integer, nullable=True)
    certified_by_name = Column(String, default="")
    certified_at = Column(String, default="")
    # Why it went ahead though a check said not yet (defects period still running, a back-charge open...).
    override_note = Column(Text, default="")
    notes = Column(Text, default="")
    cancel_reason = Column(String, default="")
    created_by_name = Column(String, default="")
    paid_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# A certified bill is never cancelled or rewritten: GST and TDS on it go into the return of the month it was
# certified, and that month may be filed. When the work billed turns out to be more than the book supports - a
# measurement corrected downwards, work rejected, a rate wrong - the correction is a credit note issued today,
# against that bill, for the quantities taken back. It reverses the same GST, TDS and retention the bill charged,
# in the period it is issued, and the quantities it takes back are claimable again if the work is measured again.
# One table both ways, as retention releases are: side "client" is against our RA bill, "contractor" against a
# contractor's bill.
class DBCreditNote(Base):
    __tablename__ = "credit_notes"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    side = Column(String, default="client", index=True)      # client | contractor
    ra_bill_id = Column(Integer, ForeignKey("ra_bills.id"), nullable=True, index=True)
    sub_bill_id = Column(Integer, ForeignKey("sub_bills.id"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    sub_order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)

    number = Column(String, default="", index=True)         # <bill number>/CN-01
    sequence = Column(Integer, default=1)                   # CN-01, CN-02 ... on that bill
    note_date = Column(String, default="")
    reason = Column(Text, default="")

    taxable = Column(Float, default=0.0)                    # the work taken back, at the bill's rates
    gst_percent = Column(Float, default=0.0)
    gst_amount = Column(Float, default=0.0)
    cgst_amount = Column(Float, default=0.0)
    sgst_amount = Column(Float, default=0.0)
    igst_amount = Column(Float, default=0.0)
    place_of_supply = Column(String, default="")
    retention_amount = Column(Float, default=0.0)           # retention no longer held on the work taken back
    tds_percent = Column(Float, default=0.0)
    tds_amount = Column(Float, default=0.0)                 # TDS no longer deducted on it
    cess_amount = Column(Float, default=0.0)                # labour cess (contractor bills)
    net_amount = Column(Float, default=0.0)                 # what the bill's net payable is reduced by

    status = Column(String, default="ISSUED", index=True)
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCreditNoteLine(Base):
    __tablename__ = "credit_note_lines"

    id = Column(Integer, primary_key=True, index=True)
    credit_note_id = Column(Integer, ForeignKey("credit_notes.id"), nullable=False, index=True)
    # The bill line it takes back from: ra_bill_lines.id or sub_bill_lines.id. The item it is
    # (work_order_lines.id / subcontract_items.id) is what the billed quantity is counted against.
    bill_line_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=True, index=True)
    description = Column(Text, default="")
    uom = Column(String, default="")
    qty = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)


# PAYMENTS WAIT FOR A SIGNATURE
#
# A bill approved is a bill owed, not a bill to be paid today: what goes out this week is the accounts head's call,
# and a large one the MD's. A payment request is that decision on paper - asked for by accounts, checked by the
# accounts head, released by the MD over a limit - and only a released request is paid. Off unless the company
# turns it on (Settings > Company > Payment approval).
class DBPaymentRequest(Base):
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)              # PRQ-0001
    doc_type = Column(String, default="", index=True)            # sub_bill | supplier_bill | sub_advance | on_account | expense
    doc_id = Column(Integer, nullable=True, index=True)
    doc_number = Column(String, default="")
    party_type = Column(String, default="")
    party_name = Column(String, default="")
    party_id = Column(Integer, nullable=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    head = Column(String, default="")                             # an expense's head
    amount = Column(Float, default=0.0)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    mode = Column(String, default="")
    note = Column(String, default="")
    # PENDING (with the accounts head) -> AWAITING_MD (over the limit) -> APPROVED -> PAID; or REJECTED / CANCELLED
    status = Column(String, default="PENDING", index=True)
    requested_by = Column(Integer, nullable=True)                 # the member of staff; None for the Master
    requested_by_name = Column(String, default="")
    requested_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    checked_by_name = Column(String, default="")
    checked_at = Column(String, default="")
    approved_by_name = Column(String, default="")
    approved_at = Column(String, default="")
    rejected_by_name = Column(String, default="")
    reject_reason = Column(String, default="")
    entry_id = Column(Integer, nullable=True, index=True)         # the payment that settled it


# SITE CASH (IMPREST)
#
# A site runs on a cash box: head office tops it up, the site engineer pays the diesel, the lorry, the tea out of it,
# and keeps the bills. Each payment is entered from site - with a photo of the bill - and checked by accounts; only a
# checked expense is booked (as an expense voucher out of the box, charged to the site), and the box is topped back
# up to its float. Until it is checked it is cash the box no longer holds but the books do not know of yet.
class DBSiteCashExpense(Base):
    __tablename__ = "site_cash_expenses"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)                 # SCE-0001
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    spent_on = Column(String, default="")
    head = Column(String, default="")
    paid_to = Column(String, default="")
    amount = Column(Float, default=0.0)
    note = Column(String, default="")
    bill_no = Column(String, default="")
    status = Column(String, default="SUBMITTED", index=True)         # SUBMITTED -> APPROVED | REJECTED
    submitted_by = Column(Integer, nullable=True)                    # the member of staff; None for the Master
    submitted_by_name = Column(String, default="")
    submitted_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    checked_by_name = Column(String, default="")
    checked_at = Column(String, default="")
    reject_reason = Column(String, default="")
    entry_id = Column(Integer, nullable=True, index=True)           # the expense voucher it was booked as


# THE BANK'S OWN STATEMENT
#
# What the books say is in the bank and what the bank says are never the same on a given day: cheques written and not
# yet presented, cheques deposited and not yet credited, charges and interest the bank booked on its own. The bank's
# statement is read in line by line, each line matched to the entry it is, and what is left over is the
# reconciliation.
class DBBankStatementLine(Base):
    __tablename__ = "bank_statement_lines"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False, index=True)
    txn_date = Column(String, default="", index=True)
    narration = Column(String, default="")
    reference = Column(String, default="")             # cheque number, UTR
    debit = Column(Float, default=0.0)                 # out of the account
    credit = Column(Float, default=0.0)                # into it
    balance = Column(Float, nullable=True)             # as the bank printed it, when it did
    status = Column(String, default="UNMATCHED", index=True)    # UNMATCHED | MATCHED | IGNORED
    entry_id = Column(Integer, nullable=True, index=True)
    file_name = Column(String, default="")
    imported_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    imported_by_name = Column(String, default="")
