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


class WorkerIn(BaseModel):
    job_id: int
    name: str
    age: int
    address: Optional[str] = ""
    trade: str
    screened_on: Optional[str] = ""
    contractor_name: Optional[str] = ""
    father_name: Optional[str] = ""
    dob: Optional[str] = ""
    sex: Optional[str] = ""
    marital_status: Optional[str] = ""
    children: Optional[int] = 0
    mother_tongue: Optional[str] = ""
    other_languages: Optional[str] = ""
    emergency_contact: Optional[str] = ""
    phone: Optional[str] = ""
    identification_mark: Optional[str] = ""
    vision_normal: Optional[bool] = True
    vision_problem: Optional[str] = ""
    health_normal: Optional[bool] = True
    health_problem: Optional[str] = ""
    weight_kg: Optional[float] = 0
    height_cm: Optional[float] = 0
    blood_group: Optional[str] = ""
    education: Optional[list] = None
    experience: Optional[list] = None
    pan: Optional[str] = ""
    aadhaar: Optional[str] = ""
    certificates_verified: Optional[bool] = False
    trial_briefed: Optional[bool] = False
    safety_officer_name: Optional[str] = ""


class CheckItemIn(BaseModel):
    key: str
    answer: Optional[str] = ""
    remarks: Optional[str] = ""


class CheckIn(BaseModel):
    job_id: int
    form_type: str
    equipment_no: str
    specs: Optional[str] = ""
    location: Optional[str] = ""
    extinguisher_type: Optional[str] = ""
    board_type: Optional[str] = ""
    contractor_name: Optional[str] = ""
    inspection_date: Optional[str] = ""
    next_inspection_date: Optional[str] = ""
    items: list[CheckItemIn]
    readings: Optional[dict] = None
    signoffs: Optional[dict] = None


class CheckSignoffIn(BaseModel):
    role: str                         # a sign-off role of the form, or "review" for the client / PMC decision
    name: str
    date: Optional[str] = ""
    decision: Optional[str] = ""      # for "review": accepted | rejected
