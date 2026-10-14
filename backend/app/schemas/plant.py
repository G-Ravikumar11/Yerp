"""What the Equipment & Plant endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class AllocationIn(BaseModel):
    asset_id: int
    employee_id: int
    role: str = "Operator"
    shift: str = "Day"
    start_date: str = ""
    end_date: Optional[str] = ""
    supervisor_id: Optional[int] = None
    notes: Optional[str] = ""


class ReassignIn(BaseModel):
    employee_id: int
    on: Optional[str] = ""
    reason: Optional[str] = ""


class EndIn(BaseModel):
    on: Optional[str] = ""
    reason: Optional[str] = ""


class LogbookIn(BaseModel):
    asset_id: int
    employee_id: int
    log_date: str = ""
    shift: str = "Day"
    start_time: str = ""
    end_time: str = ""
    break_minutes: Optional[int] = 0
    opening_meter: Optional[float] = None
    closing_meter: Optional[float] = None
    operating_hours: Optional[float] = None      # when the machine has no meter
    idle_hours: Optional[float] = None
    breakdown_hours: Optional[float] = 0
    work_done: Optional[str] = ""
    fuel_litres: Optional[float] = 0
    supervisor_remarks: Optional[str] = ""
    correction_reason: Optional[str] = ""


class DecisionIn(BaseModel):
    decision: str                                # approve | reject
    remarks: Optional[str] = ""


class HoursRuleIn(BaseModel):
    regular_hours: float


class FuelIn(BaseModel):
    asset_id: int
    filled_on: str = ""
    filled_time: Optional[str] = ""
    fuel_type: str = "Diesel"
    litres: float
    rate: float
    amount: Optional[float] = None
    supplier: Optional[str] = ""
    voucher_no: Optional[str] = ""
    meter_reading: Optional[float] = None
    notes: Optional[str] = ""


class MaintenanceIn(BaseModel):
    asset_id: int
    kind: str = "Preventive"
    reported_on: Optional[str] = ""
    description: str = ""
    priority: Optional[str] = "Normal"
    mechanic: Optional[str] = ""
    scheduled_on: Optional[str] = ""
    next_service_meter: Optional[float] = None
    out_of_service: Optional[bool] = False


class MaintenanceUpdateIn(BaseModel):
    status: Optional[str] = None                 # Scheduled | In progress
    scheduled_on: Optional[str] = None
    mechanic: Optional[str] = None
    priority: Optional[str] = None
    parts_used: Optional[str] = None
    parts_cost: Optional[float] = None
    labour_cost: Optional[float] = None
    downtime_start: Optional[str] = None
    work_performed: Optional[str] = None
    invoice_no: Optional[str] = None


class MaintenanceDoneIn(BaseModel):
    completed_on: str = ""
    work_performed: str = ""
    parts_used: Optional[str] = ""
    parts_cost: Optional[float] = 0
    labour_cost: Optional[float] = 0
    downtime_start: Optional[str] = ""
    downtime_end: Optional[str] = ""
    invoice_no: Optional[str] = ""
    meter_at_service: Optional[float] = None
    next_service_on: Optional[str] = ""
    next_service_meter: Optional[float] = None


class ProviderIn(BaseModel):
    name: str
    contact_person: Optional[str] = ""
    mobile: Optional[str] = ""
    email: Optional[str] = ""
    address: Optional[str] = ""
    supplier_id: Optional[int] = None


class RentalIn(BaseModel):
    asset_id: int
    provider_id: int
    agreement_no: str = ""
    start_date: str = ""
    expected_return: str = ""
    rate: float = 0
    billing: str = "Daily"
    min_billable_hours: Optional[float] = 0
    overtime_rate: Optional[float] = 0
    transport_charges: Optional[float] = 0
    deposit: Optional[float] = 0
    advance: Optional[float] = 0
    fuel_included: Optional[bool] = False
    operator_included: Optional[bool] = False
    notes: Optional[str] = ""


class ExtendIn(BaseModel):
    to_date: str
    reason: Optional[str] = ""


class ReturnIn(BaseModel):
    returned_on: str = ""


class RentalInvoiceIn(BaseModel):
    invoice_no: str
    invoice_date: str = ""
    period_from: Optional[str] = ""
    period_to: Optional[str] = ""
    billed_hours: Optional[float] = 0
    amount: float
    paid: Optional[float] = 0
    paid_on: Optional[str] = ""
    payment_ref: Optional[str] = ""


class PaymentIn(BaseModel):
    amount: float
    paid_on: str = ""
    payment_ref: Optional[str] = ""


class ExpenseIn(BaseModel):
    asset_id: int
    category: str
    spent_on: str = ""
    description: str = ""
    quantity: Optional[float] = 0
    unit_rate: Optional[float] = 0
    amount: Optional[float] = None
    vendor: Optional[str] = ""
    invoice_no: Optional[str] = ""
    payment_status: Optional[str] = "Unpaid"
    payment_ref: Optional[str] = ""
