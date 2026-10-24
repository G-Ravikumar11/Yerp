"""Store module - control tables: transfers between stores (with the time they are in transit), stock counts that freeze a store and
adjust it to what was found, and wastage and scrap. Owned by P4.

Every document has a header and lines and a status from DocStatus (DRAFT -> SUBMITTED -> APPROVED -> POSTED, or CANCELLED). Stock moves
only when it is POSTED, through app/services/stock_ledger.py. A transfer is POSTED when it is dispatched (stock leaves the source and
is in transit); receiving it at the destination is a second step recorded in `receipt_status`. Quantities are Numeric(18,3) in the
item's BASE unit; rates are Numeric(18,4), values Numeric(18,2).
"""
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint

from app.db.session import Base
from app.models.store_core import DocHeader, QTY, RATE, VALUE

TRANSFER, COUNT, SCRAP = "TRANSFER", "COUNT", "SCRAP"        # what the ledger calls these documents (ref_doc_type)
WASTAGE = "WASTAGE"                                          # a SCRAP document line's disposal, besides SCRAP itself


class DBStoreTransfer(DocHeader, Base):
    """Stock sent from one store (`store_id`) to another (`to_store_id`)."""
    __tablename__ = "store_transfer"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_transfer_number"),)

    to_store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    transfer_date = Column(Date, nullable=False, default=date.today)
    vehicle_no = Column(String, default="")
    receipt_status = Column(String, default="")              # '' until dispatched, then IN_TRANSIT -> RECEIVED
    received_at = Column(DateTime, nullable=True)
    received_by_name = Column(String, default="")
    inter_project = Column(Integer, default=0)               # 1 when the two stores belong to different projects


class DBStoreTransferLine(Base):
    __tablename__ = "store_transfer_line"

    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("store_transfer.id"), nullable=False, index=True)
    line_no = Column(Integer, default=1)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)             # base unit
    rate = Column(RATE, default=0)                           # what it left at (the average of the day): set when dispatched
    value = Column(VALUE, default=0)
    remarks = Column(String, default="")


class DBStoreCount(DocHeader, Base):
    """A physical stock count of one store. Starting it freezes the store and takes a snapshot of the books; posting it adjusts
    the books to what was counted and unfreezes the store."""
    __tablename__ = "store_count"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_count_number"),)

    count_date = Column(Date, nullable=False, default=date.today)
    count_type = Column(String, default="FULL")              # FULL (everything held) | PARTIAL (the items chosen)
    started_at = Column(DateTime, nullable=True)
    started_by_name = Column(String, default="")
    freeze_id = Column(Integer, ForeignKey("store_freeze.id"), nullable=True)


class DBStoreCountLine(Base):
    __tablename__ = "store_count_line"
    __table_args__ = (UniqueConstraint("count_id", "item_id", name="uq_store_count_item"),)

    id = Column(Integer, primary_key=True, index=True)
    count_id = Column(Integer, ForeignKey("store_count.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    system_qty = Column(QTY, default=0)                      # the books when the count started
    avg_rate = Column(RATE, default=0)                       # the average rate then; what the variance is valued at
    counted_qty = Column(QTY, nullable=True)                 # empty until counted
    in_snapshot = Column(Integer, default=1)                 # 0 for an item found that the books did not have
    reason = Column(String, default="")


class DBStoreScrap(DocHeader, Base):
    """Stock written off as wastage, or scrap that is sold or thrown away."""
    __tablename__ = "store_scrap"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_scrap_number"),)

    scrap_date = Column(Date, nullable=False, default=date.today)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    buyer = Column(String, default="")
    reference = Column(String, default="")                   # the gate pass, voucher or challan


class DBStoreScrapLine(Base):
    __tablename__ = "store_scrap_line"

    id = Column(Integer, primary_key=True, index=True)
    scrap_id = Column(Integer, ForeignKey("store_scrap.id"), nullable=False, index=True)
    line_no = Column(Integer, default=1)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)
    disposal = Column(String, default="SCRAP")               # SCRAP | WASTAGE
    reason = Column(String, default="")
    realised_value = Column(VALUE, default=0)                # what a scrap sale fetched
    cost_head = Column(String, nullable=True)                # where a wastage cost is charged (a CostHead)
    writeoff_request_id = Column(Integer, nullable=True)     # an outward write-off request this line deals with


class DBStoreControlLog(Base):
    """Every change of status of a control document: who, when, from what to what."""
    __tablename__ = "store_control_log"
    __table_args__ = (Index("ix_store_control_log_doc", "doc_type", "doc_id"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    doc_type = Column(String, nullable=False)                # TRANSFER | COUNT | SCRAP
    doc_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)                  # create | start | submit | approve | post | receive | cancel
    from_status = Column(String, default="")
    to_status = Column(String, default="")
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")
