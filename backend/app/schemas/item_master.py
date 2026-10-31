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
    make: Optional[str] = ""                   # the brand: UltraTech, Tata Tiscon, Finolex
    shelf_life_applicable: Optional[bool] = False
    shelf_life_days: Optional[int] = None
    expiry_tracking: Optional[bool] = False
    segment: Optional[str] = ""                # the company or division the item belongs to, as the old ERP kept it


class StatusIn(BaseModel):
    is_active: bool
    confirm: bool = False          # deactivating something in use must be said to be meant


class BulkStatusIn(BaseModel):
    ids: List[int]
    is_active: bool
    confirm: bool = False


class BulkUpdateIn(BaseModel):
    """Several items changed together. A field left out (None) is left as it is on every item."""
    ids: List[int]
    kind: Optional[str] = None
    item_category: Optional[str] = None
    item_subcategory: Optional[str] = None
    item_type: Optional[str] = None
    units_of_measure: Optional[str] = None
    gst_percent: Optional[float] = None
    hsn_code: Optional[str] = None
    make: Optional[str] = None


class BulkCategoryIn(BaseModel):
    ids: List[int]
    item_category: str = ""
    item_subcategory: str = ""


class ImportRowIn(BaseModel):
    line: int
    values: dict
    action: Optional[str] = None      # import | skip - what the person chose; blank leaves it to the row's status


class ImportRowsIn(BaseModel):
    rows: List[ImportRowIn]


class MergeIn(BaseModel):
    into_id: int


class CategoryIn(BaseModel):
    name: str
    parent_id: Optional[int] = None


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
