"""What the contractor compliance endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class ComplianceDocIn(BaseModel):
    contractor_id: int
    kind: str
    number: Optional[str] = ""
    valid_from: Optional[str] = ""
    valid_to: str
    note: Optional[str] = ""


class BackChargeIn(BaseModel):
    contractor_id: int
    order_id: Optional[int] = None
    kind: Optional[str] = "Other"
    reason: str
    amount: float


class ApplyBackChargesIn(BaseModel):
    ids: List[int]


class RatingIn(BaseModel):
    contractor_id: int
    bill_id: Optional[int] = None
    quality: int = 3
    speed: int = 3
    safety: int = 3
    discipline: int = 3
    note: Optional[str] = ""
