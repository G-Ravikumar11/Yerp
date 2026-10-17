"""Store module - outward (requisitions, issues to site and to subcontractors, returns, write-off requests). Owned by P3.

A requisition (MRQ) asks for material and moves no stock. An issue (ISSUE) takes stock out to a project / work order / BOQ
item / cost head, or to a subcontractor; an issue return (RTN) brings unused or returnable items back. Issues and returns
follow DRAFT -> SUBMITTED -> APPROVED -> POSTED or CANCELLED; a requisition stops at APPROVED (or CANCELLED).
Quantities are in the item's base unit; the typed unit and quantity are kept beside them.
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.db.session import Base
from app.models.store_core import QTY, RATE, VALUE, DocStatus

REVISION = "store_004_outward"


class DBStoreRequisition(Base):
    __tablename__ = "store_requisition"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_mrq_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)             # MRQ/ST01/26-27/00004
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    req_date = Column(Date, nullable=False, default=date.today)
    required_by = Column(Date, nullable=True)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=True)
    cost_head = Column(String, nullable=True)
    purpose = Column(String, default="")
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    cancel_reason = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class DBStoreRequisitionLine(Base):
    __tablename__ = "store_requisition_line"

    id = Column(Integer, primary_key=True, index=True)
    requisition_id = Column(Integer, ForeignKey("store_requisition.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    uom = Column(String, nullable=False)
    entered_qty = Column(QTY, nullable=False)
    qty = Column(QTY, nullable=False)                                # base unit
    remarks = Column(String, default="")


class DBStoreIssue(Base):
    __tablename__ = "store_issue"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_issue_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)             # ISSUE/CS01/26-27/00042
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    issue_date = Column(Date, nullable=False, default=date.today)
    issue_type = Column(String, nullable=False, default="SITE")     # SITE | SUBCONTRACTOR
    requisition_id = Column(Integer, ForeignKey("store_requisition.id"), nullable=True, index=True)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=True)
    cost_head = Column(String, nullable=True)
    subcontractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)
    holder_type = Column(String, nullable=True)                     # EMPLOYEE | SUBCONTRACTOR | GANG - who holds returnable items
    holder_id = Column(Integer, nullable=True)
    holder_name = Column(String, default="")
    expected_return_date = Column(Date, nullable=True)
    purpose = Column(String, default="")
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    cancel_reason = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStoreIssueLine(Base):
    __tablename__ = "store_issue_line"

    id = Column(Integer, primary_key=True, index=True)
    issue_id = Column(Integer, ForeignKey("store_issue.id"), nullable=False, index=True)
    requisition_line_id = Column(Integer, ForeignKey("store_requisition_line.id"), nullable=True, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    uom = Column(String, nullable=False)
    entered_qty = Column(QTY, nullable=False)
    qty = Column(QTY, nullable=False)                                # base unit
    rate = Column(RATE, nullable=False, default=0)                  # the average it left at; set when posted
    value = Column(VALUE, nullable=False, default=0)
    returnable = Column(Boolean, default=False)                      # the item is RETURNABLE / TOOL: it is expected back
    chargeable = Column(Boolean, default=False)                      # subcontractor issue recovered from the subcontractor's bill
    recovery_rate = Column(RATE, nullable=False, default=0)         # per base unit; the issue rate when left empty
    remarks = Column(String, default="")


class DBStoreIssueReturn(Base):
    __tablename__ = "store_issue_return"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_rtn_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)             # RTN/CS01/26-27/00002
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    issue_id = Column(Integer, ForeignKey("store_issue.id"), nullable=False, index=True)
    return_date = Column(Date, nullable=False, default=date.today)
    remarks = Column(Text, default="")
    status = Column(String, nullable=False, default=DocStatus.DRAFT.value, index=True)
    cancel_reason = Column(String, default="")
    created_by = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    posted_at = Column(DateTime, nullable=True)


class DBStoreIssueReturnLine(Base):
    __tablename__ = "store_issue_return_line"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("store_issue_return.id"), nullable=False, index=True)
    issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    qty = Column(QTY, nullable=False, default=0)                    # comes back into stock (base unit)
    lost_qty = Column(QTY, nullable=False, default=0)               # will not come back: raises a write-off request when posted
    rate = Column(RATE, nullable=False, default=0)                  # the issue rate
    value = Column(VALUE, nullable=False, default=0)
    remarks = Column(String, default="")


class DBStoreWriteoffRequest(Base):
    """Material that was issued and will not come back, waiting for the control slice to write it off."""
    __tablename__ = "store_writeoff_request"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    qty = Column(QTY, nullable=False)
    reason = Column(String, default="")
    source_issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=True, index=True)
    source_return_id = Column(Integer, ForeignKey("store_issue_return.id"), nullable=True, index=True)
    status = Column(String, nullable=False, default="OPEN", index=True)    # OPEN | CLOSED | CANCELLED
    closed_by_doc_type = Column(String, nullable=True)
    closed_by_doc_id = Column(Integer, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class DBStoreOutwardLog(Base):
    __tablename__ = "store_outward_log"
    __table_args__ = (Index("ix_store_outward_log_doc", "doc_type", "doc_id"),)

    id = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String, nullable=False)                        # MRQ | ISSUE | RTN
    doc_id = Column(Integer, nullable=False)
    from_status = Column(String, default="")
    to_status = Column(String, nullable=False)
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")
