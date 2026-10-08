"""What the safety endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class IncidentIn(BaseModel):
    job_id: int
    kind: str
    description: str
    happened_on: Optional[str] = ""
    happened_at: Optional[str] = ""
    location: Optional[str] = ""
    injured_name: Optional[str] = ""
    injury: Optional[str] = ""
    treatment: Optional[str] = ""
    lost_days: Optional[float] = 0
    immediate_action: Optional[str] = ""
    root_cause: Optional[str] = ""
    corrective_action: Optional[str] = ""


class IncidentCloseIn(BaseModel):
    root_cause: Optional[str] = ""
    corrective_action: Optional[str] = ""
    closure_note: Optional[str] = ""


class TalkIn(BaseModel):
    job_id: int
    topic: str
    held_on: Optional[str] = ""
    attendees: Optional[int] = 0
    attendee_names: Optional[str] = ""
    minutes: Optional[int] = 15
    notes: Optional[str] = ""


class PermitIn(BaseModel):
    job_id: int
    kind: str
    location: Optional[str] = ""
    description: Optional[str] = ""
    valid_from: Optional[str] = ""
    valid_to: str
    receiver: Optional[str] = ""
    precautions: Optional[list] = None


class PermitCloseIn(BaseModel):
    note: Optional[str] = ""
    cancel: Optional[bool] = False
