"""The Store module's shared core: stores, bins, who may use them, per-item stock settings, unit conversions, freezes,
document numbering and - the heart of it - the stock ledger and the balance kept from it.

Every slice of the Store module (masters, enquiry, inward, outward, control, reports) reads and writes stock only through
app/services/stock_ledger.py. Nothing outside that file inserts into store_stock_ledger or store_stock_balance.

Quantities are Numeric(18,3), rates Numeric(18,4), values Numeric(18,2). Keep them as Decimal in Python; never float.
Migration: store_001_core. This repo has no Alembic - tables are made by Base.metadata.create_all on start-up (see
app/core/application.py), so the revision is a name for the change, not a script; the new tables need no column patches.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declared_attr

from app.db.session import Base

REVISION = "store_001_core"

QTY = Numeric(18, 3)
RATE = Numeric(18, 4)
VALUE = Numeric(18, 2)
FACTOR = Numeric(18, 6)
PERCENT = Numeric(7, 3)


class MovementType(str, enum.Enum):
    OPENING_IN = "OPENING_IN"
    GRN_IN = "GRN_IN"
    CLIENT_SUPPLY_IN = "CLIENT_SUPPLY_IN"
    PURCHASE_RETURN_OUT = "PURCHASE_RETURN_OUT"
    ISSUE_OUT = "ISSUE_OUT"
    ISSUE_RETURN_IN = "ISSUE_RETURN_IN"
    SUBCON_ISSUE_OUT = "SUBCON_ISSUE_OUT"
    SUBCON_RETURN_IN = "SUBCON_RETURN_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"
    ADJUST_IN = "ADJUST_IN"
    ADJUST_OUT = "ADJUST_OUT"
    WASTAGE_OUT = "WASTAGE_OUT"
    SCRAP_OUT = "SCRAP_OUT"


IN_MOVEMENTS = frozenset(m for m in MovementType if m.value.endswith("_IN"))
OUT_MOVEMENTS = frozenset(m for m in MovementType if m.value.endswith("_OUT"))


class DocStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    CANCELLED = "CANCELLED"


class DocHeader:
    """The columns every store document shares - the inward, outward and control documents each had a copy."""

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


class CostHead(str, enum.Enum):
    SITE_ESTABLISHMENT = "SITE_ESTABLISHMENT"
    P_AND_M_FUEL = "P_AND_M_FUEL"
    OVERHEAD = "OVERHEAD"
    SAFETY = "SAFETY"
    TEMPORARY_WORKS = "TEMPORARY_WORKS"


class StoreType(str, enum.Enum):
    CENTRAL = "CENTRAL"
    SITE = "SITE"
    YARD = "YARD"


class ItemCategory(str, enum.Enum):
    CONSUMABLE = "CONSUMABLE"
    RETURNABLE = "RETURNABLE"
    TOOL = "TOOL"
    SPARE = "SPARE"


class StoreError(Exception):
    """Base of the Store module's own errors. Routers turn these into 4xx answers (see app/core/store_auth.py)."""


class InsufficientStockError(StoreError):
    """An OUT movement larger than what the store holds. Stock never goes negative."""

    def __init__(self, store_id, item_id, available, requested):
        self.store_id, self.item_id, self.available, self.requested = store_id, item_id, available, requested
        super().__init__("Only %s on hand in store %s for item %s; %s was asked for." % (available, store_id, item_id, requested))


class BatchOnHoldError(StoreError):
    """A batch under a quality hold cannot go out for use, however much of it is on hand."""


class StoreFrozenError(StoreError):
    """The store is frozen (a stock count is on): nothing may move in or out until it is unfrozen."""

    def __init__(self, store_id, reason=""):
        self.store_id, self.reason = store_id, reason
        super().__init__("Store %s is frozen%s." % (store_id, (": " + reason) if reason else ""))


class InvalidMovementError(StoreError):
    """A movement that is wrong in itself: no rate on an IN, a rate on an OUT, zero quantity, unknown store or item."""


class DBStore(Base):
    """A place stock is kept: the central store, a project's site store, or a yard."""
    __tablename__ = "store_store"
    __table_args__ = (UniqueConstraint("client_id", "code", name="uq_store_client_code"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    code = Column(String, nullable=False, index=True)          # CS01 - appears in every document number
    name = Column(String, nullable=False)
    type = Column(String, nullable=False, default=StoreType.CENTRAL.value)   # CENTRAL | SITE | YARD
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    address = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)


class DBStoreBin(Base):
    """A rack, shelf or yard bay inside a store."""
    __tablename__ = "store_bin"
    __table_args__ = (UniqueConstraint("store_id", "code", name="uq_store_bin_code"),)

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    code = Column(String, nullable=False)
    description = Column(String, default="")
    is_active = Column(Boolean, default=True)


class DBStoreUserAssignment(Base):
    """Which staff work in which store. Without a row (and without store.admin) a member of staff has no access to it."""
    __tablename__ = "store_user_assignment"
    __table_args__ = (UniqueConstraint("store_id", "employee_id", name="uq_store_assignment"),)

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    role = Column(String, default="STOREKEEPER")               # a label for the screens; rights come from permissions
    is_active = Column(Boolean, default=True)
    assigned_at = Column(DateTime, default=datetime.now)


class DBStoreItemSettings(Base):
    """What the store needs to know about an item beyond the item master (erp_items)."""
    __tablename__ = "store_item_settings"
    __table_args__ = (UniqueConstraint("item_id", name="uq_store_item_settings_item"),)

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    category = Column(String, default=ItemCategory.CONSUMABLE.value)   # CONSUMABLE | RETURNABLE | TOOL | SPARE
    base_uom = Column(String, nullable=False)                  # the unit stock is counted and valued in
    reorder_level = Column(QTY, default=0)
    min_qty = Column(QTY, default=0)
    max_qty = Column(QTY, default=0)
    qc_required = Column(Boolean, default=False)
    over_receipt_tolerance_pct = Column(PERCENT, default=0)
    is_batch_tracked = Column(Boolean, default=False)
    barcode = Column(String, default="", index=True)            # the maker's barcode on packaged goods, scanned to find the item


class DBStoreUomConversion(Base):
    """1 `from_uom` of an item = `to_base_factor` of its base unit (1 bag = 50 kg)."""
    __tablename__ = "store_uom_conversion"
    __table_args__ = (UniqueConstraint("item_id", "from_uom", name="uq_store_uom_item_from"),)

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    from_uom = Column(String, nullable=False)
    to_base_factor = Column(FACTOR, nullable=False)


class DBStoreFreeze(Base):
    """A store frozen for a stock count. Open while unfrozen_at is empty."""
    __tablename__ = "store_freeze"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    reason = Column(String, default="")
    frozen_by = Column(Integer, nullable=True)                 # employee id; empty when the account holder did it
    frozen_at = Column(DateTime, default=datetime.now)
    unfrozen_at = Column(DateTime, nullable=True, index=True)
    unfrozen_by = Column(Integer, nullable=True)


class DBStoreDocSequence(Base):
    """The last number used for one kind of document in one store in one financial year."""
    __tablename__ = "store_doc_sequence"
    __table_args__ = (UniqueConstraint("doc_type", "store_id", "fy", name="uq_store_doc_sequence"),)

    id = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String, nullable=False)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    fy = Column(String, nullable=False)                        # 26-27
    last_no = Column(Integer, nullable=False, default=0)


class DBStoreStockLedger(Base):
    """One stock movement, append-only. Never updated or deleted: a mistake is undone by a reversing entry that points
    back at it through reversal_of_id (same movement_type, quantity in the opposite column).

    `value` is always positive: qty_in x rate for an IN, qty_out x the average rate of the day for an OUT. Direction is
    which of qty_in / qty_out is non-zero. running_* and avg_rate are the store's position for this item right after
    this entry, in posting order (id) - txn_date is the business date and may be earlier than the posting."""
    __tablename__ = "store_stock_ledger"
    __table_args__ = (
        CheckConstraint("(qty_in > 0 AND qty_out = 0) OR (qty_out > 0 AND qty_in = 0)", name="ck_store_ledger_one_direction"),
        Index("ix_store_ledger_store_item", "store_id", "item_id"),
        Index("ix_store_ledger_ref", "ref_doc_type", "ref_doc_id"),
        Index("ix_store_ledger_project_date", "project_id", "txn_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    txn_date = Column(Date, nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    movement_type = Column(String, nullable=False, index=True)
    qty_in = Column(QTY, nullable=False, default=0)
    qty_out = Column(QTY, nullable=False, default=0)
    rate = Column(RATE, nullable=False, default=0)
    value = Column(VALUE, nullable=False, default=0)
    running_qty = Column(QTY, nullable=False, default=0)
    running_value = Column(VALUE, nullable=False, default=0)
    avg_rate = Column(RATE, nullable=False, default=0)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=True, index=True)
    cost_head = Column(String, nullable=True)
    subcontractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)
    ref_doc_type = Column(String, nullable=False)              # GRN, ISSUE, TRANSFER, OPENING ...
    ref_doc_id = Column(Integer, nullable=False)
    ref_line_id = Column(Integer, nullable=True)
    reversal_of_id = Column(Integer, ForeignKey("store_stock_ledger.id"), nullable=True, index=True)
    user_id = Column(Integer, nullable=True)                   # employee id; empty when the account holder did it
    created_at = Column(DateTime, default=datetime.now)
    remarks = Column(Text, nullable=True)


# The name the Store module's contract uses.
StockLedgerEntry = DBStoreStockLedger


class DBStoreStockBalance(Base):
    """What a store holds of an item right now. Kept by post_movement alone, in step with the ledger."""
    __tablename__ = "store_stock_balance"
    __table_args__ = (
        UniqueConstraint("store_id", "item_id", name="uq_store_balance_store_item"),
        CheckConstraint("qty >= 0", name="ck_store_balance_not_negative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty = Column(QTY, nullable=False, default=0)
    value = Column(VALUE, nullable=False, default=0)
    avg_rate = Column(RATE, nullable=False, default=0)


# --- lots ------------------------------------------------------------------------------------------------------------------
# A lot is one batch of an item: the number the maker printed on it, or - for a receipt that gave a shelf life but no number -
# the receipt line itself. Lots are known company-wide, so a batch keeps its identity when it is moved to another store.
# What each store holds of each lot is kept by the ledger alongside the store's total, and always adds up to it; each ledger
# entry records which lots it moved. Stock with no batch is lot 0.

NO_BATCH = 0


class DBStoreBatch(Base):
    """One lot of an item, with the dates its shelf life is judged by."""
    __tablename__ = "store_batch"
    __table_args__ = (UniqueConstraint("client_id", "item_id", "batch_no", name="uq_store_batch_item_no"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    batch_no = Column(String, nullable=False)
    manufacturing_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    first_received = Column(Date, nullable=True)
    on_hold = Column(Boolean, default=False, nullable=False, index=True)     # true while any hold on it is active
    source = Column(String, default="")                       # where it first came from: "Receipt GRN-0003"
    created_at = Column(DateTime, default=datetime.now)


class DBStoreBatchHold(Base):
    """One reason a batch is held: placed by hand, or by an open NCR. Each stands alone, and stays as the record once
    released. `hold_key` is unique while it is active: one manual hold on a batch, one hold for an NCR."""
    __tablename__ = "store_batch_hold"
    __table_args__ = (UniqueConstraint("hold_key", name="uq_store_batch_hold_key"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("store_batch.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)                     # MANUAL | NCR
    ncr_id = Column(Integer, nullable=True, index=True)
    hold_key = Column(String, nullable=True)
    status = Column(String, default="ACTIVE", index=True)     # ACTIVE | RELEASED
    reason = Column(String, default="")
    remarks = Column(String, default="")
    placed_by = Column(String, default="")
    placed_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    released_by = Column(String, default="")
    released_at = Column(String, default="")
    release_note = Column(String, default="")


class DBStoreBatchBalance(Base):
    """What a store holds of one lot of an item (batch_id 0: stock with no batch). Kept by stock_ledger alone."""
    __tablename__ = "store_batch_balance"
    __table_args__ = (
        UniqueConstraint("store_id", "item_id", "batch_id", name="uq_store_batch_balance"),
        CheckConstraint("qty >= 0", name="ck_store_batch_balance_not_negative"),
    )

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    batch_id = Column(Integer, nullable=False, default=NO_BATCH, index=True)
    qty = Column(QTY, nullable=False, default=0)


class DBStoreLedgerBatch(Base):
    """Which lots one ledger entry moved, and how much of each. Append-only, like the ledger."""
    __tablename__ = "store_ledger_batch"

    id = Column(Integer, primary_key=True, index=True)
    ledger_id = Column(Integer, ForeignKey("store_stock_ledger.id"), nullable=False, index=True)
    batch_id = Column(Integer, nullable=False, default=NO_BATCH, index=True)
    qty = Column(QTY, nullable=False, default=0)


class DBStoreControlSetting(Base):
    """The company's controls on what the store may post, and when.

    books_locked_upto: nothing - no document, no cancellation - can be dated on or before it (a month that has been closed).
    max_backdate_days: how far back a document may be dated (0 = no limit). Opening stock is exempt, being dated to the day
    the store was taken on."""
    __tablename__ = "store_control_setting"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, unique=True, index=True)
    books_locked_upto = Column(Date, nullable=True)
    max_backdate_days = Column(Integer, nullable=False, default=30)
    separate_duties = Column(Integer, nullable=False, default=1)   # 1: staff may not approve what they made or submitted
    updated_at = Column(DateTime, nullable=True)
    updated_by_name = Column(String, default="")
