"""What the opening-balance form sends. Left out (None) on a change keeps what it was."""
from typing import Optional

from pydantic import BaseModel


class PartyOpeningIn(BaseModel):
    party_type: Optional[str] = None
    party_name: Optional[str] = None
    side: Optional[str] = None
    amount: Optional[float] = None
    as_on: Optional[str] = None
    job_id: Optional[int] = None
    note: Optional[str] = None
