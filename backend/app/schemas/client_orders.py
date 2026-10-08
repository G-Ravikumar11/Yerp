"""What the client orders endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel, Field


class DocLineIn(BaseModel):
    code: str
    qty: float = 0.0
    rate: float = 0.0
    description: Optional[str] = ""


class WorkOrderIn(BaseModel):
    job_id: int
    # The client's own order number. It is printed on every bill raised
    # against this order, because that is what they file it under - so it is
    # held to a length that fits on a line rather than whatever was pasted.
    reference: Optional[str] = Field("", max_length=60)
    notes: Optional[str] = ""
    lines: List[DocLineIn]


class WoDecisionIn(BaseModel):
    decision: str
    note: Optional[str] = ""


class RaisePoIn(BaseModel):
    supplier_name: str
    supplier_email: Optional[str] = ""
    needed_by: Optional[str] = ""
    item_codes: Optional[list] = None      # omit to take everything short
