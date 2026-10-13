"""What the quality endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class InspectionIn(BaseModel):
    job_id: int
    checklist: Optional[str] = ""
    # None, not "": an edit that sends only the ticks leaves the rest as it was.
    location: Optional[str] = None
    inspected_on: Optional[str] = None
    witnessed_by: Optional[str] = None
    items: Optional[list] = None
    remarks: Optional[str] = None
    building: Optional[str] = None
    floor_area: Optional[str] = None
    work_activity: Optional[str] = None
    assigned_to: Optional[str] = None
    measurements: Optional[str] = None


class NoteIn(BaseModel):
    note: Optional[str] = ""


class CubeSetIn(BaseModel):
    job_id: int
    cast_on: Optional[str] = ""
    location: Optional[str] = ""
    grade: Optional[str] = "M25"
    slump_mm: Optional[float] = 0
    supplier: Optional[str] = ""
    docket: Optional[str] = ""
    remarks: Optional[str] = ""
    pour_ref: Optional[str] = ""
    cube_ids: Optional[str] = ""
    test_ages: Optional[str] = ""          # "7,28" - blank takes the project's schedule


class CubeResultIn(BaseModel):
    age_days: int
    strengths: str                  # "31.2, 29.8, 30.5"
    tested_on: Optional[str] = ""
    lab: Optional[str] = ""
    remarks: Optional[str] = ""
    flag_review: Optional[bool] = False


class CubeDecisionIn(BaseModel):
    decision: str                   # accepted | conditional | rejected
    note: str = ""


class NcrIn(BaseModel):
    job_id: Optional[int] = None
    location: Optional[str] = ""
    description: Optional[str] = ""
    severity: Optional[str] = "Minor"
    responsible: Optional[str] = ""
    corrective_action: Optional[str] = ""
    target_date: Optional[str] = ""
    source_type: Optional[str] = ""
    source_id: Optional[int] = None
    source_ref: Optional[str] = ""
    root_cause: Optional[str] = ""


class NcrAssignIn(BaseModel):
    responsible: str
    target_date: Optional[str] = ""
    corrective_action: Optional[str] = ""
    root_cause: Optional[str] = None
    severity: Optional[str] = None


class NcrWorkIn(BaseModel):
    corrective_done: str
    root_cause: Optional[str] = None


class NcrVerifyIn(BaseModel):
    result: str                     # verified | rejected
    note: Optional[str] = ""


class NcrCloseIn(BaseModel):
    closure_note: str


class ChecklistIn(BaseModel):
    name: str
    work_type: Optional[str] = ""
    job_id: Optional[int] = None
    spec_ref: Optional[str] = ""
    items: list                     # [{item, criteria}]
    is_active: Optional[bool] = True


class CriteriaIn(BaseModel):
    job_id: int
    grade: str
    age_days: int
    min_mean: float
    min_single: Optional[float] = 0
    standard: str = ""
