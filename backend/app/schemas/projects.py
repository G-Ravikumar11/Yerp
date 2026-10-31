"""What the projects endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class JobIn(BaseModel):
    name: str
    # The job code, typed by whoever opens the project. Left out, the next JOB-0001 style number is given.
    number: Optional[str] = None
    customer_name: Optional[str] = ""
    contact_id: Optional[int] = None
    site_address: Optional[str] = ""
    description: Optional[str] = ""
    status: Optional[str] = "quoting"
    start_date: Optional[str] = ""
    target_end_date: Optional[str] = ""
    quoted_value: Optional[float] = 0.0
    budget: Optional[float] = 0.0
    # Left out (or null), the project states no retention and its bills take the usual 5%; 0 means none at all.
    retention_percent: Optional[float] = None
    currency: Optional[str] = ""
    reference: Optional[str] = ""
    manager_id: Optional[int] = None
    # The state the site is in, which decides the GST place of supply. None leaves it as it was.
    state_code: Optional[str] = None


class JobStateIn(BaseModel):
    state_code: str


class HindranceIn(BaseModel):
    """A hindrance as the register's form sends it. Left out (None) on a change keeps what it was."""
    activity_id: Optional[int] = None
    diary_id: Optional[int] = None
    cause: Optional[str] = None
    description: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    responsibility: Optional[str] = None
    impact_days: Optional[float] = None
    notice_date: Optional[str] = None
    status: Optional[str] = None


class DelayReasonIn(BaseModel):
    reason: Optional[str] = ""
    note: Optional[str] = ""


class ReopenIn(BaseModel):
    reason: Optional[str] = ""


class WorkUpdateIn(BaseModel):
    """What a diary says about the planned work: a task done (or not), or an activity now so far along."""
    task_id: Optional[int] = None
    done: Optional[bool] = None
    activity_id: Optional[int] = None
    percent: Optional[float] = None


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
    # Work from Planning & Progress that the day's diary reports done: applied to the plan when the diary is saved.
    work_updates: Optional[List[WorkUpdateIn]] = None


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
    assigned_to_id: Optional[int] = None
    status: Optional[str] = ""
    notes: Optional[str] = ""


class ProgressIn(BaseModel):
    percent: float = 0
    # For an activity with a quantity: how much is done so far (not today's share); the % follows from it.
    qty_done: Optional[float] = None
    reported_on: Optional[str] = ""
    note: Optional[str] = ""


class TaskIn(BaseModel):
    text: Optional[str] = None
    date: Optional[str] = None
    activity_id: Optional[int] = None
    done: Optional[bool] = None
    # Part done: how much of the task, 0-100. 100 is the same as done.
    percent: Optional[float] = None


class FromBoqIn(BaseModel):
    start: str
    finish: str
    # section: one activity per BOQ section with its items as tasks. item: one activity per priced line.
    by: Optional[str] = "section"


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
