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


# RETENTION RELEASED
#
# Retention is held on every certified bill, both ways: the client holds it
# from us, and we hold it from the gangs. A release is the document that
# brings it back - a claim on the client at practical completion or at the
# end of the defects period, or a payment due to a gang. It carries the GST
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
    status = Column(String, default="CERTIFIED", index=True)
    notes = Column(Text, default="")
    cancel_reason = Column(String, default="")
    created_by_name = Column(String, default="")
    paid_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
