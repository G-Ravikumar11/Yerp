"""Store module - control (transfers, stock counts, adjustments, scrap) tables. Owned by P4.

Transfer (TRF): stock leaves the sending store when POSTED (TRANSFER_OUT) and is "in transit" until the receiving store
confirms it (TRANSFER_IN at the rate it left at); anything short comes back to the sender. Stock count (CNT): freezes the store,
counts against a blind snapshot, and posts the variance as ADJUST_IN / ADJUST_OUT. Adjustment (ADJ): a stock correction, wastage
charged to a project or cost head, or the write-off of material lost on issue. Scrap (SCR): scrap taken out at book value with
what it fetched recorded. All follow DRAFT -> SUBMITTED -> APPROVED -> POSTED or CANCELLED; every change is in store_control_log.
`store_id` on each document is the store whose stock it moves (the sender, for a transfer).
"""
import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.db.session import Base
from app.models.store_core import QTY, RATE, VALUE, DocStatus

REVISION = "store_005_control"


class AdjustmentReason(str, enum.Enum):
    """Why stock is corrected by hand (kind STOCK)."""
    DATA_CORRECTION = "DATA_CORRECTION"
    FOUND = "FOUND"
    LOST = "LOST"
    THEFT = "THEFT"
    CONVERSION = "CONVERSION"


class WastageReason(str, enum.Enum):
    """Why material is written off (kinds WASTAGE and WRITEOFF) and why goods were lost in transit."""
    CEMENT_SET = "CEMENT_SET"            # cement set / hardened
    BREAKAGE = "BREAKAGE"
    RUSTING = "RUSTING"
    EXPIRY = "EXPIRY"
    PILFERAGE = "PILFERAGE"


class ScrapClass(str, enum.Enum):
    STEEL_CUT_PIECES = "STEEL_CUT_PIECES"
    EMPTY_CEMENT_BAGS = "EMPTY_CEMENT_BAGS"
    DAMAGED_SHUTTERING = "DAMAGED_SHUTTERING"
    OTHER = "OTHER"


class _Doc:
    """Columns every control document shares."""
    number = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    cancel_reason = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStoreTransfer(Base, _Doc):
    __tablename__ = "store_transfer"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_trf_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)        # the sender
    to_store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    trf_date = Column(Date, nullable=False, default=date.today)
    inter_project = Column(Boolean, default=False)
    vehicle_no = Column(String, default="")
    driver_name = Column(String, default="")
    challan_no = Column(String, default="")
    challan_date = Column(Date, nullable=True)
    remarks = Column(Text, default="")
    loss_status = Column(String, default="")                      # "" none | PENDING (reported, not approved) | APPROVED (posted as wastage)
    loss_approved_at = Column(DateTime, nullable=True)
    loss_approved_by_name = Column(String, default="")
    received_at = Column(DateTime, nullable=True)                 # empty while the goods are in transit
    received_by_name = Column(String, default="")
    received_on = Column(Date, nullable=True)


class DBStoreTransferLine(Base):
    __tablename__ = "store_transfer_line"

    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("store_transfer.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty = Column(QTY, nullable=False)                             # sent, base unit
    rate = Column(RATE, nullable=False, default=0)                # the average it left at; set when posted
    value = Column(VALUE, nullable=False, default=0)
    received_qty = Column(QTY, nullable=True)                     # filled when received
    loss_qty = Column(QTY, nullable=False, default=0)             # lost or damaged in transit; received + loss = sent
    loss_reason = Column(String, default="")                      # a WastageReason
    loss_remarks = Column(String, default="")
    remarks = Column(String, default="")


class DBStoreCount(Base, _Doc):
    __tablename__ = "store_count"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_cnt_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    count_date = Column(Date, nullable=False, default=date.today)
    freeze_id = Column(Integer, ForeignKey("store_freeze.id"), nullable=True)      # the freeze this count took
    categories = Column(String, default="")                       # comma list of item categories this count is limited to; empty = any
    bin_id = Column(Integer, ForeignKey("store_bin.id"), nullable=True)           # the bin / section being counted (printed on the sheet)
    recount_rounds = Column(Integer, default=0)
    remarks = Column(Text, default="")


class DBStoreCountLine(Base):
    __tablename__ = "store_count_line"

    id = Column(Integer, primary_key=True, index=True)
    count_id = Column(Integer, ForeignKey("store_count.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    system_qty = Column(QTY, nullable=False, default=0)           # the books when the count started (hidden from counters)
    system_value = Column(VALUE, nullable=False, default=0)
    avg_rate = Column(RATE, nullable=False, default=0)
    counted_qty = Column(QTY, nullable=True)
    first_count_qty = Column(QTY, nullable=True)                  # kept when a line is recounted
    recount = Column(Boolean, default=False)                      # asked to be counted again
    recounts = Column(Integer, default=0)
    variance_qty = Column(QTY, nullable=False, default=0)         # counted - system, set on submit
    variance_value = Column(VALUE, nullable=False, default=0)     # signed
    remarks = Column(String, default="")


class DBStoreAdjustment(Base, _Doc):
    __tablename__ = "store_adjustment"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_adj_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    adj_date = Column(Date, nullable=False, default=date.today)
    kind = Column(String, nullable=False, default="STOCK")        # STOCK | WASTAGE | WRITEOFF
    reason = Column(String, default="")                           # the mandatory remark
    reason_code = Column(String, default="")                      # an AdjustmentReason (STOCK) or a WastageReason (WASTAGE, WRITEOFF)
    attachment_ref = Column(String, default="")                   # reference of the supporting paper (police report, survey note, photo ...)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    cost_head = Column(String, nullable=True)
    high_value = Column(Boolean, default=False)


class DBStoreAdjustmentLine(Base):
    __tablename__ = "store_adjustment_line"

    id = Column(Integer, primary_key=True, index=True)
    adjustment_id = Column(Integer, ForeignKey("store_adjustment.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    direction = Column(String, nullable=False, default="OUT")     # IN | OUT
    qty = Column(QTY, nullable=False)
    rate = Column(RATE, nullable=False, default=0)                # IN: given or the average; OUT: the average it left at
    value = Column(VALUE, nullable=False, default=0)
    writeoff_request_id = Column(Integer, nullable=True)          # a write-off request from the outward slice, for kind WRITEOFF
    remarks = Column(String, default="")


class DBStoreScrap(Base, _Doc):
    __tablename__ = "store_scrap"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_scr_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    scrap_date = Column(Date, nullable=False, default=date.today)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    buyer = Column(String, default="")
    gate_pass_no = Column(String, default="")
    reason = Column(String, default="")


class DBStoreScrapLine(Base):
    __tablename__ = "store_scrap_line"

    id = Column(Integer, primary_key=True, index=True)
    scrap_id = Column(Integer, ForeignKey("store_scrap.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty = Column(QTY, nullable=False)
    scrap_class = Column(String, default="OTHER")                 # a ScrapClass
    book_value = Column(VALUE, nullable=False, default=0)         # at the store average, set when posted
    realised_value = Column(VALUE, nullable=False, default=0)     # what it fetched
    remarks = Column(String, default="")


class DBStoreControlLog(Base):
    __tablename__ = "store_control_log"
    __table_args__ = (Index("ix_store_control_log_doc", "doc_type", "doc_id"),)

    id = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String, nullable=False)                      # TRF | CNT | ADJ | SCR
    doc_id = Column(Integer, nullable=False)
    from_status = Column(String, default="")
    to_status = Column(String, nullable=False)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")
