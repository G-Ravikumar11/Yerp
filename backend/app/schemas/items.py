"""What the items endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class ItemCommitIn(BaseModel):
    rows: List[dict]


class ItemIn(BaseModel):
    kind: str
    item_code: Optional[str] = ""          # blank means "issue me the next one"
    item_name: str
    description: Optional[str] = ""
    segment: Optional[str] = ""
    hsn_code: Optional[str] = ""
    item_tax_type: Optional[str] = "18%"
    item_type: Optional[str] = "Purchased"
    units_of_measure: Optional[str] = "Nos"
    make: Optional[str] = ""
    # None means "leave it alone" - a form that omits the field must not
    # silently switch off a warning somebody set deliberately.
    reorder_level: Optional[float] = None


class ItemBulkIn(BaseModel):
    items: List[ItemIn]


class BomLineIn(BaseModel):
    fg_code: str
    rm_code: str
    qty: float = 0.0
    rate: float = 0.0


class BomIn(BaseModel):
    work_order_id: int
    lines: List[BomLineIn]


class MDDecision(BaseModel):
    approve: bool = True
    notes: Optional[str] = ""
