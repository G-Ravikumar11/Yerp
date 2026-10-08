"""What the recruitment endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class JobRequisitionIn(BaseModel):
    title: str
    department_id: Optional[int] = None
    hiring_manager_id: Optional[int] = None
    description: Optional[str] = ""
    requirements: Optional[str] = ""
    location: Optional[str] = ""
    work_mode: Optional[str] = "onsite"
    employment_type: Optional[str] = "full_time"
    level: Optional[str] = ""
    salary_min: Optional[float] = 0.0
    salary_max: Optional[float] = 0.0
    show_salary: Optional[bool] = True
    openings: Optional[int] = 1
    closing_date: Optional[str] = ""
    status: Optional[str] = "draft"


class InterviewIn(BaseModel):
    round_name: Optional[str] = "Interview"
    scheduled_at: str
    duration_minutes: Optional[int] = 45
    mode: Optional[str] = "video"
    location: Optional[str] = ""
    meeting_link: Optional[str] = ""
    interviewer_id: Optional[int] = None
    interviewer_name: Optional[str] = ""


class OfferIn(BaseModel):
    job_title: Optional[str] = ""
    level: Optional[str] = ""
    salary: Optional[float] = 0.0
    start_date: Optional[str] = ""
    expires_on: Optional[str] = ""
    notes: Optional[str] = ""


class CandidateEmailIn(BaseModel):
    template: Optional[str] = "custom"     # interview | offer | rejection | custom
    subject: Optional[str] = ""
    body: Optional[str] = ""


class RecruitmentFormCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    fields: Optional[str] = "[]"
    job_id: Optional[int] = None
    pipeline_stages: Optional[str] = '["Applied","Screening","Interview","Offer","Hired"]'


class CandidateDocumentIn(BaseModel):
    doc_type: Optional[str] = "other"
    file_name: str
    file_type: Optional[str] = ""
    file_data: str


class FormSubmissionCreate(BaseModel):
    answers: Optional[str] = "{}"
    file_name: Optional[str] = ""
    file_type: Optional[str] = ""
    file_data: Optional[str] = ""
    candidate_name: Optional[str] = ""
    candidate_email: Optional[str] = ""
    candidate_phone: Optional[str] = ""
    documents: Optional[List[CandidateDocumentIn]] = None
