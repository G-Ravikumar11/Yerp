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


class DBStoreItemLevel(Base):
    """An item's reorder, minimum and maximum levels for one store, where they differ from the item's own. An empty column uses the item's."""
    __tablename__ = "store_item_level"
    __table_args__ = (UniqueConstraint("store_id", "item_id", name="uq_store_item_level"),)

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    reorder_level = Column(QTY, nullable=True)
    min_qty = Column(QTY, nullable=True)
    max_qty = Column(QTY, nullable=True)


class DBStoreReorderAlert(Base):
    """Whether an item in a store is at its reorder level and has been told to the company: one open alert until the stock is back above the
    level, so it is raised once, not on every issue below it."""
    __tablename__ = "store_reorder_alert"
    __table_args__ = (UniqueConstraint("store_id", "item_id", name="uq_store_reorder_alert"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    alerted_at = Column(DateTime, default=datetime.now)
    cleared_at = Column(DateTime, nullable=True)


TOOL_AVAILABLE, TOOL_ISSUED, TOOL_IN_SERVICE, TOOL_LOST, TOOL_RETIRED = "AVAILABLE", "ISSUED", "IN_SERVICE", "LOST", "RETIRED"


class DBStoreTool(Base):
    """One tool, by serial number: where it is, who holds it, what condition it is in and when it is next due for service. The stock ledger
    counts tools by quantity; this is the register of the individual ones."""
    __tablename__ = "store_tool"
    __table_args__ = (UniqueConstraint("client_id", "item_id", "serial_no", name="uq_store_tool_serial"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)       # where it lives when it is not out
    serial_no = Column(String, nullable=False)
    status = Column(String, nullable=False, default=TOOL_AVAILABLE, index=True)
    condition = Column(String, default="GOOD")                                                  # GOOD | DAMAGED
    holder_name = Column(String, default="")
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    issue_id = Column(Integer, ForeignKey("store_issue.id"), nullable=True)
    due_back = Column(Date, nullable=True)
    last_service = Column(Date, nullable=True)
    next_service = Column(Date, nullable=True)
    notes = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class DBStoreToolEvent(Base):
    __tablename__ = "store_tool_event"

    id = Column(Integer, primary_key=True, index=True)
    tool_id = Column(Integer, ForeignKey("store_tool.id"), nullable=False, index=True)
    event = Column(String, nullable=False)           # REGISTERED | ISSUED | RETURNED | SERVICE_OUT | SERVICE_DONE | LOST | RETIRED
    condition = Column(String, default="")
    holder_name = Column(String, default="")
    note = Column(String, default="")
    by_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)


class DBStoreReminder(Base):
    """When a reminder about one thing (a returnable issue line that is overdue, a tool due for service) was last sent, so it is repeated weekly
    and not every day."""
    __tablename__ = "store_reminder"
    __table_args__ = (UniqueConstraint("client_id", "kind", "ref_id", name="uq_store_reminder"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)            # RETURN_OVERDUE | TOOL_RETURN_OVERDUE | TOOL_SERVICE_DUE
    ref_id = Column(Integer, nullable=False)
    last_sent_at = Column(DateTime, default=datetime.now)


class DBStoreCycleSetting(Base):
    """A company's rules for cycle counting: how often each ABC class is counted, and how far a count may be from the books before it must be
    counted again."""
    __tablename__ = "store_cycle_setting"
    __table_args__ = (UniqueConstraint("client_id", name="uq_store_cycle_setting_client"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    days_a = Column(Integer, default=30)
    days_b = Column(Integer, default=90)
    days_c = Column(Integer, default=180)
    recount_value = Column(QTY, default=25000)       # a difference worth this much or more is counted again (0 = never on value)
    recount_pct = Column(QTY, default=20)            # ... or this percent of the books, once it is worth at least recount_min_value (0 = never on percent)
    recount_min_value = Column(QTY, default=1000)


class DBStoreCountRecount(Base):
    """The second, blind count of a line whose first count was far from the books. The line then carries the second count; the first is kept here."""
    __tablename__ = "store_count_recount"
    __table_args__ = (UniqueConstraint("count_line_id", name="uq_store_count_recount_line"),)

    id = Column(Integer, primary_key=True, index=True)
    count_line_id = Column(Integer, ForeignKey("store_count_line.id"), nullable=False)
    first_qty = Column(QTY, nullable=False, default=0)
    recount_qty = Column(QTY, nullable=False, default=0)
    by_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
