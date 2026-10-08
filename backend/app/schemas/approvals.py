"""What the approvals endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class ApprovalDecisionIn(BaseModel):
    kind: str
    id: int
    decision: str
    note: Optional[str] = ""
    override: Optional[bool] = False
