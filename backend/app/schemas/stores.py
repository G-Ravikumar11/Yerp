"""What the stores endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class StockIssueIn(BaseModel):
    work_order_id: Optional[int] = None
    job_id: Optional[int] = None
    issued_on: Optional[str] = ""
    issued_to: Optional[str] = ""
    purpose: Optional[str] = ""
    store: Optional[str] = ""
    remarks: Optional[str] = ""
    lines: Optional[list] = None


class AdjustmentIn(BaseModel):
    item_code: str
    counted: float
    store: Optional[str] = ""
    remarks: Optional[str] = ""


class TransferLineIn(BaseModel):
    item_code: str
    qty: float


class TransferIn(BaseModel):
    from_store: str
    to_store: str
    moved_on: Optional[str] = ""
    note: Optional[str] = ""
    lines: List[TransferLineIn]
