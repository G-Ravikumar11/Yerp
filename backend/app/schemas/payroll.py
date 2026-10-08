"""What the payroll endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class PayslipCreate(BaseModel):
    employee_id: int
    period_start: str
    period_end: str
    pay_date: str
    hours_worked: Optional[float] = 0.0
    overtime_hours: Optional[float] = 0.0
    overtime_rate: Optional[float] = 0.0
    basic_salary: Optional[float] = 0.0
    overtime_pay: Optional[float] = 0.0
    bonus: Optional[float] = 0.0
    allowances: Optional[float] = 0.0
    tax_amount: Optional[float] = 0.0
    insurance: Optional[float] = 0.0
    retirement: Optional[float] = 0.0
    other_deductions: Optional[float] = 0.0
    notes: Optional[str] = ""


class PayrollRunRequest(BaseModel):
    period_start: str
    period_end: str
    pay_date: str
    employee_ids: Optional[List[int]] = None
    include_attendance_hours: Optional[bool] = True
    skip_existing: Optional[bool] = True
