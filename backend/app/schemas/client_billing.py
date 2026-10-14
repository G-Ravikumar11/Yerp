"""What the client billing endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class RABillIn(BaseModel):
    work_order_id: int
    period_from: Optional[str] = ""
    period_to: Optional[str] = ""
    retention_percent: Optional[float] = None   # omit to take the contract's own
    advance_recovery: Optional[float] = 0.0
    other_deductions: Optional[float] = 0.0
    deduction_notes: Optional[str] = ""
    tax_percent: Optional[float] = None
    tds_percent: Optional[float] = None


class RAActionIn(BaseModel):
    comments: Optional[str] = ""


class VariationIn(BaseModel):
    work_order_id: int
    reason: Optional[str] = ""
    lines: Optional[list] = None          # omit to let the book fill it in


class CreditNoteIn(BaseModel):
    """A credit note against one certified bill: the quantities taken back, line by line, and why."""
    lines: Optional[list] = None          # [{"bill_line_id": 12, "qty": 3.5}, ...]
    reason: Optional[str] = ""
    note_date: Optional[str] = ""         # YYYY-MM-DD; today when omitted
