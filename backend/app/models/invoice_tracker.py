"""What the invoice tracker records beyond what a goods receipt already holds.

Plain integer keys, not foreign keys: the tracker only annotates receipts, projects and tenants, so deleting one of
them must never be blocked by a note about it. A note whose receipt is gone is simply not shown.
"""
from datetime import datetime

from sqlalchemy import Column, Float, Integer, String, Text, UniqueConstraint

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBTrackerInvoice(Base):
    """The supplier's own bill for one goods receipt: its date, the amount printed on it, and any freight charged."""
    __tablename__ = "tracker_invoices"
    __table_args__ = (UniqueConstraint("client_id", "grn_id", name="uq_tracker_invoice_grn"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    grn_id = Column(Integer, nullable=False, index=True)
    invoice_date = Column(String, default="")
    invoice_amount = Column(Float, nullable=True)     # None until somebody keys in what the bill says
    freight = Column(Float, default=0.0)
    updated_at = Column(String, default=_now)


class DBTrackerBlock(Base):
    """Where a delivered line was used - the block or pour a lorry of concrete went into."""
    __tablename__ = "tracker_blocks"
    __table_args__ = (UniqueConstraint("client_id", "grn_line_id", name="uq_tracker_block_line"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    grn_line_id = Column(Integer, nullable=False, index=True)
    block = Column(String, default="")
    updated_at = Column(String, default=_now)


class DBTrackerNote(Base):
    """The work-order value and the remark for one trade (plumbing, electrical, civil, RMC), on one project or all."""
    __tablename__ = "tracker_notes"
    __table_args__ = (UniqueConstraint("client_id", "job_id", "category", name="uq_tracker_note_category"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, nullable=False, default=0)      # 0 = every project
    category = Column(String, nullable=False)
    wo_amount = Column(Float, default=0.0)
    remarks = Column(Text, default="")
    updated_at = Column(String, default=_now)


class DBTrackerCharge(Base):
    """Insurance or hamali (loading and unloading) charged on one supplier invoice, beyond the goods and the freight."""
    __tablename__ = "tracker_charges"
    __table_args__ = (UniqueConstraint("client_id", "grn_id", "kind", name="uq_tracker_charge_kind"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    grn_id = Column(Integer, nullable=False, index=True)
    kind = Column(String, nullable=False)                  # insurance | hamali
    amount = Column(Float, default=0.0)
    updated_at = Column(String, default=_now)


class DBTrackerInvoiceNote(Base):
    """A remark on one supplier invoice - "some coils not received" - shown under that invoice's column."""
    __tablename__ = "tracker_invoice_notes"
    __table_args__ = (UniqueConstraint("client_id", "grn_id", name="uq_tracker_invoice_note"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    grn_id = Column(Integer, nullable=False, index=True)
    remark = Column(Text, default="")
    updated_at = Column(String, default=_now)


class DBTrackerWorkingRate(Base):
    """The rate a material is being worked at, which can differ from what it was bought at. Per project, or all (0)."""
    __tablename__ = "tracker_working_rates"
    __table_args__ = (UniqueConstraint("client_id", "job_id", "item_key", name="uq_tracker_working_rate"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=False, index=True)
    job_id = Column(Integer, nullable=False, default=0)
    item_key = Column(String, nullable=False)           # the item code, upper case, or the description where there is none
    rate = Column(Float, default=0.0)
    updated_at = Column(String, default=_now)
