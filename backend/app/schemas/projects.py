"""What the projects endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class JobIn(BaseModel):
    name: str
    customer_name: Optional[str] = ""
    contact_id: Optional[int] = None
    site_address: Optional[str] = ""
    description: Optional[str] = ""
    status: Optional[str] = "quoting"
    start_date: Optional[str] = ""
    target_end_date: Optional[str] = ""
    quoted_value: Optional[float] = 0.0
    budget: Optional[float] = 0.0
    retention_percent: Optional[float] = 0.0
    currency: Optional[str] = ""
    reference: Optional[str] = ""
    manager_id: Optional[int] = None
    # The state the site is in, which decides the GST place of supply. None leaves it as it was.
    state_code: Optional[str] = None


class JobStateIn(BaseModel):
    state_code: str


class DiaryIn(BaseModel):
    job_id: Optional[int] = None
    work_order_id: Optional[int] = None
    diary_date: Optional[str] = ""
    weather: Optional[str] = ""
    rain_hours: Optional[float] = None
    working_hours: Optional[float] = None
    work_done: Optional[str] = None
    holdups: Optional[str] = None
    instructions: Optional[str] = None
    visitors: Optional[str] = None
    safety_note: Optional[str] = None
    labour: Optional[list] = None
    plant: Optional[list] = None


class ActivityIn(BaseModel):
    name: str
    code: Optional[str] = ""
    planned_start: str
    planned_finish: str
    weight: Optional[float] = 0
    depends_on_id: Optional[int] = None
    work_order_line_id: Optional[int] = None
    is_milestone: Optional[bool] = False
    actual_start: Optional[str] = ""
    actual_finish: Optional[str] = ""


class ProgressIn(BaseModel):
    percent: float
    reported_on: Optional[str] = ""
    note: Optional[str] = ""


class FromWorkOrderIn(BaseModel):
    start: str
    finish: str


class DrawingIn(BaseModel):
    number: str
    title: Optional[str] = ""
    discipline: Optional[str] = "Structural"


class SiteLocationIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    position: Optional[str] = ""       # or pasted: "17.42, 78.34" or a maps link
    radius_m: Optional[float] = 300
