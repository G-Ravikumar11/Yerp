"""What the hr endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    color: Optional[str] = "#00f0ff"
    icon: Optional[str] = "building"


class EmployeeCreate(BaseModel):
    # The sites this person works on. None means "leave as it is"; an empty
    # list means "every site", which is what somebody unassigned already had.
    site_ids: Optional[List[int]] = None
    first_name: str
    last_name: str
    email: Optional[str] = ""
    phone: Optional[str] = ""
    address: Optional[str] = ""
    department_id: Optional[int] = None
    reports_to: Optional[int] = None
    job_title: Optional[str] = ""
    role: Optional[str] = "employee"
    permission_role: Optional[str] = "staff"
    level: Optional[str] = ""
    employment_type: Optional[str] = "full_time"
    pay_frequency: Optional[str] = "monthly"
    salary: Optional[float] = 0.0
    hourly_rate: Optional[float] = 0.0
    tax_rate: Optional[float] = 0.0
    deductions: Optional[float] = 0.0
    allowances: Optional[float] = 0.0
    bonus: Optional[float] = 0.0
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    tax_id: Optional[str] = ""
    emergency_contact: Optional[str] = ""
    emergency_phone: Optional[str] = ""
    start_date: Optional[str] = ""
    employee_id: Optional[str] = ""
    password: Optional[str] = ""


class DocumentRequirementIn(BaseModel):
    name: str
    description: Optional[str] = ""
    doc_type: Optional[str] = "other"
    is_mandatory: Optional[bool] = True
    due_days: Optional[int] = 7
    requires_expiry: Optional[bool] = False
    expiry_reminder_days: Optional[int] = 30
    applies_to: Optional[str] = "all"
    department_id: Optional[int] = None
    level: Optional[str] = ""
    is_active: Optional[bool] = True
    sort_order: Optional[int] = 0


class RequirementTemplateIn(BaseModel):
    file_name: str
    file_type: Optional[str] = ""
    file_data: str
