"""What the partner portal endpoints are sent."""
from pydantic import BaseModel


class PortalPasswordIn(BaseModel):
    token: str
    password: str


class PortalLoginIn(BaseModel):
    email: str
    password: str
