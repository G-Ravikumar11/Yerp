"""What the collaboration endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class ThreadIn(BaseModel):
    job_id: int
    title: str
    body: Optional[str] = ""
    file_ids: Optional[list] = None


class MessageIn(BaseModel):
    body: Optional[str] = ""
    file_ids: Optional[list] = None
