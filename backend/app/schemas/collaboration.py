"""What the collaboration endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class ThreadIn(BaseModel):
    job_id: int
    title: str
    body: Optional[str] = ""
    file_ids: Optional[list] = None
    description: Optional[str] = ""
    category: Optional[str] = "General"
    priority: Optional[str] = "Normal"
    members: Optional[list] = None
    link_type: Optional[str] = ""
    link_ref: Optional[str] = ""


class ThreadEditIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    members: Optional[list] = None
    link_type: Optional[str] = None
    link_ref: Optional[str] = None


class MessageIn(BaseModel):
    body: Optional[str] = ""
    file_ids: Optional[list] = None
    parent_id: Optional[int] = None


class MessageEditIn(BaseModel):
    body: str


class ReactionIn(BaseModel):
    emoji: str


class TaskIn(BaseModel):
    title: Optional[str] = ""
    description: Optional[str] = ""
    assignee: Optional[str] = ""
    due_date: Optional[str] = ""
    priority: Optional[str] = "Normal"
    message_id: Optional[int] = None


class TaskEditIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


class NoticesReadIn(BaseModel):
    ids: Optional[list] = None
