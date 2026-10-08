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


class CubeSetIn(BaseModel):
    job_id: int
    cast_on: Optional[str] = ""
    location: Optional[str] = ""
    grade: Optional[str] = "M25"
    slump_mm: Optional[float] = 0
    supplier: Optional[str] = ""
    docket: Optional[str] = ""
    remarks: Optional[str] = ""


class CubeResultIn(BaseModel):
    age_days: int
    strengths: str                  # "31.2, 29.8, 30.5"
    tested_on: Optional[str] = ""
    lab: Optional[str] = ""


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


class NcrCloseIn(BaseModel):
    closure_note: str
