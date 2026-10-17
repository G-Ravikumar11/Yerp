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
from app.models.store_core import PERCENT, QTY, RATE, DocStatus

ISSUE, ISSUE_RETURN = "ISSUE", "ISSRET"             # what the ledger calls these documents (ref_doc_type) and their number prefix
SITE, SUBCONTRACTOR = "SITE", "SUBCONTRACTOR"       # issue_type
EMPLOYEE, GANG = "EMPLOYEE", "GANG"                 # holder_type, besides SUBCONTRACTOR
INDENT, GATE_PASS = "INDENT", "GATE"                # an indent's number prefix; a gate pass's
PERSON, FOREMAN = "PERSON", "FOREMAN"               # received_by_type, besides GANG
CONTRACT_RATE, AVERAGE_COST = "CONTRACT_RATE", "AVERAGE_COST"   # how the rate to recover from a subcontractor is set


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
    direct = Column(Integer, default=0)                                # 1 when it was issued without an indent (by someone with the direct-issue right)
    indent_id = Column(Integer, ForeignKey("store_indent.id"), nullable=True, index=True)
    subcontract_order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True, index=True)
    received_by_type = Column(String, default="")                      # PERSON | GANG | FOREMAN: who took the material away
    received_by_employee_id = Column(Integer, nullable=True)
    received_by_name = Column(String, default="")


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
    indent_line_id = Column(Integer, ForeignKey("store_indent_line.id"), nullable=True, index=True)
    recovery_basis = Column(String, default="")                        # CONTRACT_RATE | AVERAGE_COST, for a chargeable subcontractor line
    handling_pct = Column(PERCENT, default=0)                          # added to the recovery rate for handling


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
    qty_lost = Column(QTY, nullable=False, default=0)                  # base unit, lost: a write-off request
    reason = Column(String, default="")
    condition = Column(String, default="GOOD")                         # GOOD | DAMAGED: damaged goods come back into a bin kept for them
    bin_id = Column(Integer, ForeignKey("store_bin.id"), nullable=True)


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
    doc_type = Column(String, nullable=False)                          # ISSUE | ISSRET | INDENT | GATE
    doc_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)                            # create | submit | approve | post | cancel | direct
    from_status = Column(String, default="")
    to_status = Column(String, default="")
    user_id = Column(Integer, nullable=True)
    user_name = Column(String, default="")
    at = Column(DateTime, default=datetime.now)
    note = Column(String, default="")


class DBStoreIndent(Base):
    """A site engineer's request for material for a project, approved (and possibly cut back) by the project manager and then filled by issues.
    Status runs DRAFT -> SUBMITTED (waiting for the approver) -> OPEN (approved, nothing issued) -> PARTIAL -> CLOSED, or CANCELLED."""
    __tablename__ = "store_indent"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_indent_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="DRAFT", index=True)
    indent_date = Column(Date, nullable=False, default=date.today)
    required_by = Column(Date, nullable=True)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=True)
    activity = Column(String, default="")                              # the programme activity it is for, in words
    remarks = Column(Text, default="")
    requested_by_id = Column(Integer, nullable=True)
    requested_by_name = Column(String, default="")
    approved_by_name = Column(String, default="")
    approved_at = Column(DateTime, nullable=True)
    approver_remarks = Column(String, default="")
    cancel_reason = Column(String, default="")                         # why it was cancelled, or why it was closed short
    short_closed = Column(Integer, default=0)                          # 1 when it was closed by hand with quantities still pending
    created_at = Column(DateTime, default=datetime.now)


class DBStoreIndentLine(Base):
    __tablename__ = "store_indent_line"

    id = Column(Integer, primary_key=True, index=True)
    indent_id = Column(Integer, ForeignKey("store_indent.id"), nullable=False, index=True)
    line_no = Column(Integer, default=1)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    entry_uom = Column(String, default="")
    entry_qty = Column(QTY, default=0)
    qty = Column(QTY, nullable=False, default=0)                       # asked for, base unit
    approved_qty = Column(QTY, nullable=True)                          # what the approver allowed (never more than was asked); empty until approved
    purpose = Column(String, default="")


class DBStoreRecovery(Base):
    """Material the store has charged to someone to be recovered from them: what a subcontractor was issued as chargeable, or a returnable that was
    converted to a charge. One row per issue line (or conversion); P5 feeds the open ones into the subcontractor's bills."""
    __tablename__ = "store_recovery"
    __table_args__ = (Index("ix_store_recovery_sub", "subcontractor_id", "status"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    source = Column(String, default="ISSUE")                           # ISSUE | CONVERSION
    issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    subcontractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True)
    subcontract_order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True)
    holder_type = Column(String, default="")
    holder_id = Column(Integer, nullable=True)
    holder_name = Column(String, default="")
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    qty = Column(QTY, nullable=False, default=0)                       # base unit charged
    qty_returned = Column(QTY, nullable=False, default=0)              # base unit that came back since
    basis = Column(String, default="")                                 # CONTRACT_RATE | AVERAGE_COST | CONVERSION
    base_rate = Column(RATE, default=0)                                # per base unit, before handling
    handling_pct = Column(PERCENT, default=0)
    recovery_rate = Column(RATE, default=0)                            # per base unit to recover: base rate plus handling
    status = Column(String, default="OPEN", index=True)                # OPEN | CANCELLED
    created_at = Column(DateTime, default=datetime.now)


class DBStoreReturnableClosure(Base):
    """A returnable item closed other than by returning it: converted to a charge (a recovery) or handed to a write-off request."""
    __tablename__ = "store_returnable_closure"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)                              # CONVERSION | WRITEOFF
    qty = Column(QTY, nullable=False, default=0)
    reason = Column(String, default="")
    recovery_id = Column(Integer, ForeignKey("store_recovery.id"), nullable=True)
    writeoff_request_id = Column(Integer, ForeignKey("store_writeoff_request.id"), nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class DBStoreGatePass(Base):
    """A pass for material leaving the store's premises, made from a posted issue. It moves no stock. A returnable pass says when the material is due back."""
    __tablename__ = "store_gate_pass"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_store_gate_number"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("store_store.id"), nullable=False, index=True)
    number = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="ISSUED", index=True)   # ISSUED | CLOSED (the material is back) | CANCELLED
    gate_date = Column(Date, nullable=False, default=date.today)
    issue_id = Column(Integer, ForeignKey("store_issue.id"), nullable=False, index=True)
    vehicle_no = Column(String, default="")
    driver_name = Column(String, default="")
    destination = Column(String, default="")
    purpose = Column(String, default="")
    returnable = Column(Integer, default=0)
    expected_return_date = Column(Date, nullable=True)
    authorised_by_name = Column(String, default="")
    remarks = Column(Text, default="")
    cancel_reason = Column(String, default="")
    closed_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)


class DBStoreGatePassLine(Base):
    __tablename__ = "store_gate_pass_line"

    id = Column(Integer, primary_key=True, index=True)
    gate_pass_id = Column(Integer, ForeignKey("store_gate_pass.id"), nullable=False, index=True)
    issue_line_id = Column(Integer, ForeignKey("store_issue_line.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False)
    qty = Column(QTY, nullable=False, default=0)                       # base unit


class DBStoreOutwardSetting(Base):
    """A company's outward defaults: the handling percentage added to what is recovered from a subcontractor, and how that rate is usually set."""
    __tablename__ = "store_outward_setting"
    __table_args__ = (UniqueConstraint("client_id", name="uq_store_outward_setting_client"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    subcon_handling_pct = Column(PERCENT, default=0)
    default_recovery_basis = Column(String, default=AVERAGE_COST)
