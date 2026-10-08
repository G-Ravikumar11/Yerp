"""What the client billing endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class RABillIn(BaseModel):
    work_order_id: int
    period_from: Optional[str] = ""
    period_to: Optional[str] = ""
    retention_percent: Optional[float] = 5.0
    advance_recovery: Optional[float] = 0.0
    other_deductions: Optional[float] = 0.0
    deduction_notes: Optional[str] = ""
    tax_percent: Optional[float] = 18.0
    tds_percent: Optional[float] = 1.0


class RAActionIn(BaseModel):
    comments: Optional[str] = ""


class VariationIn(BaseModel):
    work_order_id: int
    reason: Optional[str] = ""
    lines: Optional[list] = None          # omit to let the book fill it in
