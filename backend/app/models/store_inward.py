"""Store module - inward tables: goods received against purchase orders (GRN) with their quality check, returns to the
supplier, material the client supplies free of charge, and opening stock. Owned by P2.

Every document has a header and lines, a status from DocStatus (DRAFT -> SUBMITTED -> APPROVED -> POSTED, or CANCELLED) and
a row in store_inward_log for every change of status. Stock moves only when a document is POSTED, through
app/services/stock_ledger.py. Quantities are Numeric(18,3) in the item's BASE unit (the unit the person typed is kept in
entry_uom / entry_qty), rates Numeric(18,4) per base unit.
"""
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declared_attr

from app.db.session import Base
from app.models.store_core import PERCENT, QTY, RATE, VALUE, DocStatus

# What the ledger calls each document (ref_doc_type) and what its number starts with.
GRN, PURCHASE_RETURN, CLIENT_SUPPLY, OPENING = "GRN", "PRTN", "CSUP", "OSTK"


class _Header:
    """The columns every inward document shares."""

    @declared_attr
    def client_id(cls):
        return Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    @declared_attr
    def store_id(cls):
        return Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    remarks = Column(Text, default="")
    cancel_reason = Column(String, default="")
    created_by_id = Column(Integer, nullable=True)           # employee id; empty when the account holder did it
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStoreGrn(_Header, Base):
    """One delivery received at a store, usually against a purchase order."""
    __tablename__ = "store_grn"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_grn_number"),)

    grn_date = Column(Date, nullable=False, default=date.today)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)
    supplier_name = Column(String, default="")
    challan_no = Column(String, default="")
    challan_date = Column(Date, nullable=True)
    vehicle_no = Column(String, default="")
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    # A gate delivery: a lorry unloaded before any purchase order was raised for it, received on its own challan. It is
    # posted to stock at once at the rate known at the gate, and linked to the order later; the difference between that
    # rate and the order's is its price variance (the ledger is never rewritten).
    gate_delivery = Column(Integer, default=0)
    driver_remarks = Column(String, default="")
    linked_at = Column(DateTime, nullable=True)
    linked_by_name = Column(String, default="")
    price_variance = Column(VALUE, default=0)
    # Landed cost: freight, loading, GST that cannot be claimed back and the like, on the supplier's bill or the transporter's.
    # A JSON list of {kind, label, amount, basis}; spread over the accepted lines (by value, or by quantity) when it posts, so
    # the stock is valued at what it cost to bring in, not only at the invoice rate.
    charges = Column(Text, default="[]")
    charges_total = Column(VALUE, default=0)


class DBStoreGrnLine(Base):
    __tablename__ = "store_grn_line"

    id = Column(Integer, primary_key=True, index=True)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    line_no = Column(Integer, default=1)
    po_line_id = Column(Integer, ForeignKey("purchase_order_line_items.id"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    received_qty = Column(QTY, nullable=False, default=0)    # base unit: what came off the lorry
    accepted_qty = Column(QTY, nullable=False, default=0)    # base unit: what goes into stock
    rejected_qty = Column(QTY, nullable=False, default=0)    # base unit: what goes back
    rate = Column(RATE, nullable=False, default=0)           # per base unit
    qc_status = Column(String, default="NOT_REQUIRED")       # NOT_REQUIRED | PENDING | PASSED | FAILED
    qc_by_name = Column(String, default="")
    qc_note = Column(String, default="")
    reject_reason = Column(String, default="")
    batch_no = Column(String, default="")
    manufacturing_date = Column(Date, nullable=True)         # shelf life: cement, admixtures, epoxies (services/store_batches.py)
    expiry_date = Column(Date, nullable=True)
    bin_id = Column(Integer, ForeignKey("store_bin.id"), nullable=True)
    remarks = Column(String, default="")
    charges_share = Column(VALUE, default=0)                 # this line's part of the receipt's charges, set when it posts
    landed_rate = Column(RATE, nullable=True)                # per base unit, rate plus its charges: what it went into stock at


class DBStorePurchaseReturn(_Header, Base):
    """Goods sent back to the supplier from a posted GRN."""
    __tablename__ = "store_purchase_return"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_prtn_number"),)

    return_date = Column(Date, nullable=False, default=date.today)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    supplier_name = Column(String, default="")
    reason = Column(String, default="")
    # The debit note: what the supplier owes back, at the rate on the receipt, with the GST of the order line. Fixed when it posts.
    debit_value = Column(VALUE, default=0)
    tax_value = Column(VALUE, default=0)


class DBStorePurchaseReturnLine(Base):
    __tablename__ = "store_purchase_return_line"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("store_purchase_return.id"), nullable=False, index=True)
    grn_line_id = Column(Integer, ForeignKey("store_grn_line.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)             # base unit
    reason = Column(String, default="")
    rate = Column(RATE, default=0)                           # per base unit: the receipt line's invoice rate
    value = Column(VALUE, default=0)
    tax_pct = Column(PERCENT, default=0)
    tax_value = Column(VALUE, default=0)


class DBStoreClientSupply(_Header, Base):
    """Material the client hands over for the project (free issue). It is stock of ours to look after, valued at the rate
    given on the receipt (zero if the client gives none)."""
    __tablename__ = "store_client_supply"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_csup_number"),)

    supply_date = Column(Date, nullable=False, default=date.today)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    client_ref = Column(String, default="")                  # the client's own challan or letter


class DBStoreClientSupplyLine(Base):
    __tablename__ = "store_client_supply_line"

    id = Column(Integer, primary_key=True, index=True)
    supply_id = Column(Integer, ForeignKey("store_client_supply.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)
    rate = Column(RATE, nullable=False, default=0)
    remarks = Column(String, default="")


class DBStoreOpening(_Header, Base):
    """Stock already held when the store starts being kept on the system."""
    __tablename__ = "store_opening"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_ostk_number"),)

    as_on_date = Column(Date, nullable=False, default=date.today)


class DBStoreOpeningLine(Base):
    __tablename__ = "store_opening_line"

    id = Column(Integer, primary_key=True, index=True)
    opening_id = Column(Integer, ForeignKey("store_opening.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)
    rate = Column(RATE, nullable=False, default=0)


class DBStoreInwardLog(Base):
    """Every change of status of an inward document: who, when, from what to what."""
    __tablename__ = "store_inward_log"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    doc_type = Column(String, nullable=False)                # GRN | PRTN | CSUP | OSTK
    doc_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)                  # create | submit | approve | post | cancel | qc
    from_status = Column(String, default="")
    to_status = Column(String, default="")
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")

    __table_args__ = (Index("ix_store_inward_log_doc", "doc_type", "doc_id"),)
