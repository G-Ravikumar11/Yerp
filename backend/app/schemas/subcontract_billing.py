"""What the subcontract billing endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class DimensionIn(BaseModel):
    """One line of the book: what, how many, how long, how wide, how deep."""
    particulars: Optional[str] = ""
    nos: Optional[float] = None
    nom: Optional[float] = None
    length: Optional[float] = None
    breadth: Optional[float] = None
    depth: Optional[float] = None
    deduct: Optional[bool] = False
    # A heading line - "Living Room", "Deductions" - that groups the lines
    # under it and measures nothing.
    is_heading: Optional[bool] = False


class MeasurementIn(BaseModel):
    line_id: int
    # The total, when it is typed as one. Ignored when dimensions are given,
    # because then the total is what the dimensions come to.
    quantity: Optional[float] = 0
    dimensions: Optional[List[DimensionIn]] = None
    measured_on: Optional[str] = ""
    mb_ref: Optional[str] = ""
    location: Optional[str] = ""
    remarks: Optional[str] = ""
    witnessed_by: Optional[str] = ""


class SubMeasurementIn(BaseModel):
    item_id: int
    quantity: Optional[float] = 0
    dimensions: Optional[List[DimensionIn]] = None
    # Blocks built alike: the dimensions are of one, the entry is this many.
    multiplier: Optional[float] = 1
    measured_on: Optional[str] = ""
    mb_ref: Optional[str] = ""
    location: Optional[str] = ""
    remarks: Optional[str] = ""
    # Where it sat in the sheet it was imported from.
    section: Optional[str] = ""
    block_label: Optional[str] = ""
    group_ref: Optional[str] = ""


class SubMeasureBatchEntry(BaseModel):
    location: Optional[str] = ""
    multiplier: Optional[float] = 1
    dimensions: Optional[List[DimensionIn]] = None
    quantity: Optional[float] = 0
    section: Optional[str] = ""
    block_label: Optional[str] = ""
    group: Optional[str] = ""


class SubMeasureBatchHold(BaseModel):
    group: Optional[str] = ""
    quantity: float
    reason: str


class SubMeasureBatchIn(BaseModel):
    item_id: int
    measured_on: Optional[str] = ""
    mb_ref: Optional[str] = ""
    remarks: Optional[str] = ""
    entries: List[SubMeasureBatchEntry]
    holds: Optional[List[SubMeasureBatchHold]] = None


class SubBillIn(BaseModel):
    order_id: int
    # Bill only these entries of the measurement book (by id) instead of everything measured and not yet billed.
    entry_ids: Optional[List[int]] = None
    period_from: Optional[str] = ""
    period_to: Optional[str] = ""
    advance_recovery: Optional[float] = None
    other_deductions: Optional[float] = None
    deduction_notes: Optional[str] = ""
    bill_date: Optional[str] = ""
    work_type: Optional[str] = ""
    work_name: Optional[str] = ""
    hsn_sac: Optional[str] = ""
    debit_notes: Optional[float] = None


class SubBillEditIn(BaseModel):
    """The certificate's own boxes, while the bill is still a draft."""
    period_from: Optional[str] = None
    period_to: Optional[str] = None
    bill_date: Optional[str] = None
    work_type: Optional[str] = None
    work_name: Optional[str] = None
    hsn_sac: Optional[str] = None
    debit_notes: Optional[float] = None
    advance_recovery: Optional[float] = None
    other_deductions: Optional[float] = None      # besides material recovered, which stays
    deduction_notes: Optional[str] = None


class RetentionReleaseIn(BaseModel):
    side: str = "client"
    order_id: int
    stage: Optional[str] = "Practical completion"
    amount: float
    release_on: Optional[str] = ""
    gst_percent: Optional[float] = None
    notes: Optional[str] = ""
