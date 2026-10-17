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
    """An OUT movement larger than what the store holds. Stock never goes negative.

    `message` (optional) replaces the default text with one that names the item and store the way a person knows them;
    the four attributes are the same either way."""

    def __init__(self, store_id, item_id, available, requested, message=None):
        self.store_id, self.item_id, self.available, self.requested = store_id, item_id, available, requested
        super().__init__(message or "Only %s on hand in store %s for item %s; %s was asked for." % (available, store_id, item_id, requested))


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


class DBStoreUomConversion(Base):
    """1 `from_uom` of an item = `to_base_factor` of its base unit (1 bag = 50 kg)."""
    __tablename__ = "store_uom_conversion"
    __table_args__ = (UniqueConstraint("item_id", "from_uom", name="uq_store_uom_item_from"),)

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    from_uom = Column(String, nullable=False)
    to_base_factor = Column(FACTOR, nullable=False)


class DBStoreFreeze(Base):
    """A store frozen for a stock count. Open while unfrozen_at is empty.

    ref_doc_type / ref_doc_id (store_002_foundation) name the count the freeze is for, when it is for one: that count's
    own ADJUST_IN / ADJUST_OUT still post while everything else is held."""
    __tablename__ = "store_freeze"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    reason = Column(String, default="")
    frozen_by = Column(Integer, nullable=True)                 # employee id; empty when the account holder did it
    frozen_at = Column(DateTime, default=datetime.now)
    unfrozen_at = Column(DateTime, nullable=True, index=True)
    unfrozen_by = Column(Integer, nullable=True)
    ref_doc_type = Column(String, nullable=True)               # COUNT
    ref_doc_id = Column(Integer, nullable=True)


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
        # store_002_foundation: the item card and the back-dating check read by store + item + date, and a movement
        # can be reversed once only (NULLs do not clash, so every original row is free to have none).
        Index("ix_store_ledger_store_item_date", "store_id", "item_id", "txn_date"),
        Index("uq_store_ledger_reversal_of", "reversal_of_id", unique=True),
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


# store_002_foundation (P1) ------------------------------------------------------------------------------------------
# Opening stock as a document, and the trail of who moved a document from one status to the next. Additive: new tables
# (made by create_all), two new columns on store_freeze and two new ledger indexes, which upgrade_store_002_foundation
# adds to a database created before them.

REVISION_FOUNDATION = "store_002_foundation"
DOWN_REVISION_FOUNDATION = REVISION


class OpeningSource(str, enum.Enum):
    MANUAL = "MANUAL"                   # typed on the entry screen
    CSV = "CSV"                         # imported from a sheet
    LEGACY = "LEGACY"                   # carried over from the old stock screens (scripts/store_legacy_to_opening.py)


class DBStoreOpening(Base):
    """What a store held on the day it started on the Store module: one document per store and date, posted as OPENING_IN
    movements (ref_doc_type OPENING_STOCK, ref_doc_id = this id)."""
    __tablename__ = "store_opening"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)        # OPEN/CS01/26-27/00001
    opening_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    source = Column(String, nullable=False, default=OpeningSource.MANUAL.value)
    remarks = Column(Text, default="")
    created_by = Column(Integer, nullable=True)                # employee id; empty when the account holder did it
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, default="")


class DBStoreOpeningLine(Base):
    """One item of an opening: the quantity as entered (in any of the item's units) and as posted (in its base unit)."""
    __tablename__ = "store_opening_line"

    id = Column(Integer, primary_key=True, index=True)
    opening_id = Column(Integer, ForeignKey("store_opening.id"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False, default=1)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    bin_id = Column(Integer, ForeignKey("store_bin.id"), nullable=True)
    entered_qty = Column(QTY, nullable=False)
    entered_uom = Column(String, nullable=False)
    entered_rate = Column(RATE, nullable=False)                # per entered unit
    qty = Column(QTY, nullable=False)                          # base units - what is posted
    rate = Column(RATE, nullable=False)                        # per base unit - what is posted
    value = Column(VALUE, nullable=False)
    remarks = Column(String, default="")


class DBStoreDocStatusLog(Base):
    """Every status change of a store document: which document, from what to what, who and when. Any slice may write
    to it for its own documents (doc_type = its ref_doc_type)."""
    __tablename__ = "store_doc_status_log"
    __table_args__ = (Index("ix_store_doc_status_log_doc", "doc_type", "doc_id"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    doc_type = Column(String, nullable=False)
    doc_id = Column(Integer, nullable=False)
    from_status = Column(String, nullable=True)                # empty when the document was created
    to_status = Column(String, nullable=False)
    user_id = Column(Integer, nullable=True)                   # employee id; empty when the account holder did it
    user_name = Column(String, default="")
    note = Column(Text, default="")
    at = Column(DateTime, default=datetime.now, nullable=False)


_FOUNDATION_COLUMNS = (("store_freeze", "ref_doc_type", "VARCHAR"), ("store_freeze", "ref_doc_id", "INTEGER"))
_FOUNDATION_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_store_ledger_store_item_date ON store_stock_ledger (store_id, item_id, txn_date)",
    "CREATE INDEX IF NOT EXISTS ix_store_ledger_ref ON store_stock_ledger (ref_doc_type, ref_doc_id)",
    "CREATE INDEX IF NOT EXISTS ix_store_ledger_project_date ON store_stock_ledger (project_id, txn_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_ledger_reversal_of ON store_stock_ledger (reversal_of_id)",
)


def upgrade_store_002_foundation(engine):
    """Bring a database made before store_002_foundation up to it: the freeze's count link and the ledger indexes.
    Idempotent, additive, safe to run on every start-up after create_all. Returns what it did."""
    from sqlalchemy import inspect, text
    done = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, sql_type in _FOUNDATION_COLUMNS:
            if table in tables and column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, sql_type)))
                done.append("%s.%s" % (table, column))
        if "store_stock_ledger" in tables:
            for ddl in _FOUNDATION_INDEXES:
                conn.execute(text(ddl))
            done.append("ledger indexes")
    return done
