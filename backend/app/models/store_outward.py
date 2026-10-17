"""Store module - outward tables: material issued to a project or to a subcontractor, what comes back, and the requests to
write off what does not. Owned by P3.

An issue names where the cost goes (a BOQ item, or one of the non-BOQ cost heads) and who holds returnable items. Stock moves
only when the document is POSTED, through app/services/stock_ledger.py. Quantities are Numeric(18,3) in the item's BASE unit
(entry_uom / entry_qty keep what was typed); an issue's rate is the average of the day, so the ledger holds it, not this table.
"""
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declared_attr

from app.db.session import Base
from app.models.store_core import QTY, DocStatus

ISSUE, ISSUE_RETURN = "ISSUE", "ISSRET"             # what the ledger calls these documents (ref_doc_type) and their number prefix
SITE, SUBCONTRACTOR = "SITE", "SUBCONTRACTOR"       # issue_type
EMPLOYEE, GANG = "EMPLOYEE", "GANG"                 # holder_type, besides SUBCONTRACTOR


class _Header:
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
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStoreIssue(_Header, Base):
    """Material leaving a store for a project: used on the work, or handed to a subcontractor."""
    __tablename__ = "store_issue"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_issue_number"),)

    issue_date = Column(Date, nullable=False, default=date.today)
    issue_type = Column(String, nullable=False, default=SITE)          # SITE | SUBCONTRACTOR
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    subcontractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)
    holder_type = Column(String, default="")                           # EMPLOYEE | SUBCONTRACTOR | GANG, for returnable items
    holder_id = Column(Integer, nullable=True)
    holder_name = Column(String, default="")
    purpose = Column(String, default="")
    direct = Column(Integer, default=0)                                # 1 when it was issued, approved and posted in one step


class DBStoreIssueLine(Base):
    __tablename__ = "store_issue_line"

    id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, ForeignKey("store_issue.id"), nullable=False, index=True)
    line_no = Column(Integer, default=1)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)                       # base unit
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=True, index=True)
    cost_head = Column(String, nullable=True)                          # a CostHead, when the cost is not BOQ work
    chargeable = Column(Integer, default=0)                            # subcontractor issue: recovered from their bill
    recovery_rate = Column(QTY, default=0)                             # per base unit
    expected_return_date = Column(Date, nullable=True)                 # returnable items
    remarks = Column(String, default="")


class DBStoreIssueReturn(_Header, Base):
    """Issued material coming back to the store, or reported lost or damaged."""
    __tablename__ = "store_issue_return"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_issret_number"),)

    return_date = Column(Date, nullable=False, default=date.today)
    issue_id = Column(Integer, ForeignKey("store_issue.id"), nullable=False, index=True)


class DBStoreIssueReturnLine(Base):
    __tablename__ = "store_issue_return_line"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("store_issue_return.id"), nullable=False, index=True)
    issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    entry_uom = Column(String, default="")
    qty_returned = Column(QTY, nullable=False, default=0)              # base unit, goes back into the store
    qty_lost = Column(QTY, nullable=False, default=0)                  # base unit, lost or damaged: a write-off request
    reason = Column(String, default="")


class DBStoreWriteoffRequest(Base):
    """A returnable that did not come back, waiting for someone to deal with it (P4 writes it off or recovers it)."""
    __tablename__ = "store_writeoff_request"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    qty = Column(QTY, nullable=False, default=0)
    reason = Column(String, default="")
    source_issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=True, index=True)
    source_return_id = Column(Integer, ForeignKey("store_issue_return.id"), nullable=True, index=True)
    status = Column(String, default="OPEN", index=True)                # OPEN | CLOSED | WITHDRAWN
    created_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)
    closed_ref_type = Column(String, default="")
    closed_ref_id = Column(Integer, nullable=True)
    closed_by = Column(Integer, nullable=True)


class DBStoreOutwardLog(Base):
    """Every change of status of an outward document: who, when, from what to what."""
    __tablename__ = "store_outward_log"
    __table_args__ = (Index("ix_store_outward_log_doc", "doc_type", "doc_id"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    doc_type = Column(String, nullable=False)                          # ISSUE | ISSRET
    doc_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)                            # create | submit | approve | post | cancel | direct
    from_status = Column(String, default="")
    to_status = Column(String, default="")
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")
