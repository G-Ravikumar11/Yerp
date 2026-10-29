"""What the Store module's slices hand each other. Frozen on purpose: a slice reads these and never edits them, and a
change here is a change to the contract (docs/store/CONTRACT.md) that every slice must agree to."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class PoLineReceipt:
    po_line_id: int
    item_id: Optional[int]
    ordered_qty: Decimal
    received_qty: Decimal
    accepted_qty: Decimal
    rejected_qty: Decimal
    pending_qty: Decimal


@dataclass(frozen=True)
class SubconIssueLine:
    issue_line_id: int
    issue_date: date
    item_id: int
    qty_issued: Decimal
    qty_returned: Decimal
    chargeable: bool
    recovery_rate: Decimal
    recovery_value: Decimal


@dataclass(frozen=True)
class ReturnableOutstanding:
    issue_line_id: int
    item_id: int
    holder_type: str                        # EMPLOYEE | SUBCONTRACTOR | GANG
    holder_id: int
    qty_outstanding: Decimal
    expected_return_date: Optional[date]
    overdue_days: int


@dataclass(frozen=True)
class WriteOffRequest:
    request_id: int
    store_id: int
    item_id: int
    qty: Decimal
    reason: str
    source_issue_line_id: Optional[int]
    status: str                             # OPEN | CLOSED


@dataclass(frozen=True)
class InTransitLine:
    transfer_id: int
    from_store_id: int
    to_store_id: int
    item_id: int
    qty: Decimal
    value: Decimal
    dispatched_on: date
    inter_project: bool


@dataclass(frozen=True)
class CountVarianceLine:
    count_id: int
    item_id: int
    system_qty: Decimal
    counted_qty: Decimal
    variance_qty: Decimal
    variance_value: Decimal


@dataclass(frozen=True)
class ScrapLine:
    scrap_doc_id: int
    item_id: int
    qty: Decimal
    book_value: Decimal
    realised_value: Decimal


@dataclass(frozen=True)
class MaterialCostLine:
    project_id: int
    cost_head: Optional[str]
    work_order_id: Optional[int]
    boq_item_id: Optional[int]
    item_id: int
    qty: Decimal
    value: Decimal
