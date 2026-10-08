"""What the boq endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class ProjectBoqLineIn(BaseModel):
    key: Optional[str] = ""
    kind: Optional[str] = "item"
    sno: Optional[str] = ""
    description: Optional[str] = ""
    uom: Optional[str] = ""
    quantity: Optional[float] = 0
    rate: Optional[float] = 0
    code: Optional[str] = ""
    item_code: Optional[str] = ""
    remarks: Optional[str] = ""


class ProjectBoqLinesIn(BaseModel):
    lines: List[ProjectBoqLineIn]
    # Give every priced line without one an item code from the master: matched to an item of the same name, or issued.
    issue_codes: Optional[bool] = False


class ProjectBoqIn(BaseModel):
    job_id: int
    title: Optional[str] = ""


class BoqVariationLineIn(BaseModel):
    kind: Optional[str] = "quantity"
    boq_key: Optional[str] = ""
    section_key: Optional[str] = ""
    sno: Optional[str] = ""
    description: Optional[str] = ""
    uom: Optional[str] = ""
    change_qty: Optional[float] = 0
    rate: Optional[float] = None
    remarks: Optional[str] = ""


class BoqVariationIn(BaseModel):
    boq_id: Optional[int] = None
    reason: Optional[str] = ""
    lines: List[BoqVariationLineIn]
