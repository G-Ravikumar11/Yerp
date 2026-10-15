"""What the item master endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class MasterItemIn(BaseModel):
    item_code: Optional[str] = ""              # blank means "issue me the next one"
    item_name: str
    description: Optional[str] = ""
    kind: Optional[str] = "FG"                 # BOQ work items are finished goods; the existing meaning is kept
    item_category: Optional[str] = ""
    item_subcategory: Optional[str] = ""
    item_type: Optional[str] = "Work"
    units_of_measure: Optional[str] = "Nos"
    specification: Optional[str] = ""
    purchase_rate: Optional[float] = None
    selling_rate: Optional[float] = None
    hsn_code: Optional[str] = ""
    gst_percent: Optional[float] = None
    preferred_supplier: Optional[str] = ""
    reorder_level: Optional[float] = None
    remarks: Optional[str] = ""
    is_active: Optional[bool] = True


class StatusIn(BaseModel):
    is_active: bool


class BulkStatusIn(BaseModel):
    ids: List[int]
    is_active: bool


class BulkCategoryIn(BaseModel):
    ids: List[int]
    item_category: str = ""
    item_subcategory: str = ""


class CategoryIn(BaseModel):
    name: str
    parent_id: Optional[int] = None


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
