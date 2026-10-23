"""Store module - tables added after the five slices: goods rejected at the gate (held until they go back or are disposed of), and the
further tables the later Store features keep. All new tables, made by create_all at start-up. Stock still moves only through the ledger;
nothing here is stock."""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base
from app.models.store_core import QTY

REJECTION_HELD, REJECTION_RETURNED, REJECTION_DISPOSED, REJECTION_VOID = "HELD", "RETURNED", "DISPOSED", "VOID"


class DBStoreRejection(Base):
    """Goods a receipt turned away. They never enter stock; this is the list of what is still lying at the gate waiting to go back to the
    supplier, and the record of what became of it."""
    __tablename__ = "store_rejection"
    __table_args__ = (UniqueConstraint("grn_line_id", name="uq_store_rejection_grn_line"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    grn_id = Column(Integer, ForeignKey("store_grn.id"), nullable=False, index=True)
    grn_line_id = Column(Integer, ForeignKey("store_grn_line.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty = Column(QTY, nullable=False, default=0)             # base unit
    reason = Column(String, default="")
    status = Column(String, nullable=False, default=REJECTION_HELD, index=True)   # HELD | RETURNED | DISPOSED | VOID
    created_at = Column(DateTime, default=datetime.now)
    resolved_on = Column(Date, nullable=True)
    resolved_by_name = Column(String, default="")
    vehicle_no = Column(String, default="")
    resolution_note = Column(Text, default="")


class DBStorePoClosure(Base):
    """A purchase order the store has short-closed: what is still undelivered will not now come, so nothing more is received against it.
    The order itself (purchasing's record) is not touched; removing this row reopens it for receiving."""
    __tablename__ = "store_po_closure"
    __table_args__ = (UniqueConstraint("po_id", name="uq_store_po_closure_po"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    reason = Column(String, default="")
    closed_by_name = Column(String, default="")
    closed_at = Column(DateTime, default=datetime.now)
