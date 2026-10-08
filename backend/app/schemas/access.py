"""What the access endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class TeamInvite(BaseModel):
    email: str
    name: Optional[str] = ""
    role: Optional[str] = "admin"


class TeamUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None


class PortalInviteIn(BaseModel):
    party_type: str
    party_id: int
    email: str
    name: Optional[str] = ""
