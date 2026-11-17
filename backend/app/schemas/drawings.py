"""What the drawings endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class DrawingStatusIn(BaseModel):
    status: str


class TakeoffLineIn(BaseModel):
    description: str
    uom: Optional[str] = ""
    quantity: float
    item_code: Optional[str] = ""


class TakeoffSendIn(BaseModel):
    """Lines of a take-off, as the person ticked (and perhaps reworded) them, sent to the BOQ or to an enquiry."""
    lines: List[TakeoffLineIn]
    needed_by: Optional[str] = ""
