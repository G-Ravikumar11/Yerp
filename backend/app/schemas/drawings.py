"""What the drawings endpoints are sent."""
from pydantic import BaseModel


class DrawingStatusIn(BaseModel):
    status: str
