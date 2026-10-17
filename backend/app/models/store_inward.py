"""Store module - inward (GRN, quality check, returns to supplier) tables. Owned by P2.

A GRN (goods received note) is received against a purchase order or stand-alone. Only the *accepted* quantity of a line
is posted to stock (GRN_IN); rejected goods are recorded on the line and never enter the ledger. A purchase return (PRN)
sends accepted stock back to the supplier (PURCHASE_RETURN_OUT). Both follow DRAFT -> SUBMITTED -> APPROVED -> POSTED,
or CANCELLED, and every change of status is written to store_inward_log.

Quantities are kept in the item's BASE unit (`*_qty`); the unit the storekeeper typed and the quantity in it are kept
beside them (`uom`, `entered_qty`) for the printout. Rates are per base unit.
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.db.session import Base
from app.models.store_core import QTY, RATE, VALUE, DocStatus

REVISION = "store_003_inward"


class DBStoreGrn(Base):
    __tablename__ = "store_grn"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_grn_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)             # GRN/CS01/26-27/00042
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    grn_date = Column(Date, nullable=False, default=date.today)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)
    supplier_name = Column(String, default="")
    challan_no = Column(String, default="")
    challan_date = Column(Date, nullable=True)
    vehicle_no = Column(String, default="")
    remarks = Column(Text, default="")
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    cancel_reason = Column(String, default="")
    created_by = Column(Integer, nullable=True)                      # employee id; empty for the account holder
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStoreGrnLine(Base):
    __tablename__ = "store_grn_line"

    id = Column(Integer, primary_key=True, index=True)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    po_line_id = Column(Integer, ForeignKey("purchase_order_line_items.id"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    uom = Column(String, nullable=False)                             # the unit typed
    entered_qty = Column(QTY, nullable=False)                        # received, in `uom`
    received_qty = Column(QTY, nullable=False)                       # received, in the base unit
    accepted_qty = Column(QTY, nullable=False, default=0)           # base unit; what goes to stock
    rejected_qty = Column(QTY, nullable=False, default=0)
    rate = Column(RATE, nullable=False, default=0)                   # per base unit
    bin_id = Column(Integer, ForeignKey("store_bin.id"), nullable=True)
    batch_no = Column(String, default="")
    qc_done = Column(Boolean, default=False)
    qc_remarks = Column(String, default="")
    remarks = Column(String, default="")


class DBStorePurchaseReturn(Base):
    __tablename__ = "store_purchase_return"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_prn_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)             # PRN/CS01/26-27/00003
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    return_date = Column(Date, nullable=False, default=date.today)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=True, index=True)
    supplier_name = Column(String, default="")
    reason = Column(String, default="")
    remarks = Column(Text, default="")
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    cancel_reason = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStorePurchaseReturnLine(Base):
    __tablename__ = "store_purchase_return_line"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("store_purchase_return.id"), nullable=False, index=True)
    grn_line_id = Column(Integer, ForeignKey("store_grn_line.id"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty = Column(QTY, nullable=False)                                # base unit
    value = Column(VALUE, nullable=False, default=0)                 # filled when posted (valued at the store average)
    remarks = Column(String, default="")


class DBStoreInwardLog(Base):
    """Who moved a GRN or purchase return to which status, and when."""
    __tablename__ = "store_inward_log"
    __table_args__ = (Index("ix_store_inward_log_doc", "doc_type", "doc_id"),)

    id = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String, nullable=False)                        # GRN | PRN
    doc_id = Column(Integer, nullable=False)
    from_status = Column(String, default="")
    to_status = Column(String, nullable=False)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")
