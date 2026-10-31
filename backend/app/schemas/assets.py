"""What the assets endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class AssetIn(BaseModel):
    name: str
    category: Optional[str] = "Other"
    ownership: Optional[str] = "Owned"
    brand: Optional[str] = ""
    model: Optional[str] = ""
    reg_no: Optional[str] = ""
    purchase_date: Optional[str] = ""
    purchase_value: Optional[float] = 0
    hired_from: Optional[str] = ""
    hire_rate: Optional[float] = 0
    hire_basis: Optional[str] = "Day"
    fuel_norm_lph: Optional[float] = None         # litres an hour; blank or 0 = not set
    tank_capacity_l: Optional[float] = None       # litres; blank or 0 = not set
    meter_unit: Optional[str] = "Hours"
    meter_reading: Optional[float] = 0
    service_every: Optional[float] = 0
    service_every_days: Optional[int] = 0
    last_service_on: Optional[str] = ""
    last_service_meter: Optional[float] = None
    insurance_until: Optional[str] = ""
    fitness_until: Optional[str] = ""
    notes: Optional[str] = ""
    code: Optional[str] = ""               # blank: the next EQP number
    condition: Optional[str] = "Good"
    location_type: Optional[str] = None    # Yard | Site | Transit; None leaves where it is alone
    location_id: Optional[int] = None      # the site (project), when location_type is Site
    service_interval_type: Optional[str] = None   # Both | Meter | Days | None; not sent = read from the intervals
    reminder_meter: Optional[float] = None        # blank: a tenth of the interval
    reminder_days: Optional[float] = None         # blank: a tenth of the interval, at least 3


class ServiceDoneIn(BaseModel):
    """A scheduled service, done."""
    completed_on: Optional[str] = ""
    meter_at_service: Optional[float] = None
    work_performed: Optional[str] = ""
    parts_used: Optional[str] = ""
    parts_cost: Optional[float] = 0
    labour_cost: Optional[float] = 0
    vendor: Optional[str] = ""
    invoice_no: Optional[str] = ""
    next_service_meter: Optional[float] = None   # blank: this reading plus the interval
    next_service_on: Optional[str] = ""          # blank: this date plus the interval


class AssetMoveIn(BaseModel):
    to_job_id: Optional[int] = None       # none = back to the yard
    moved_on: Optional[str] = ""
    note: Optional[str] = ""


class AssetLogIn(BaseModel):
    log_date: Optional[str] = ""
    hours_worked: Optional[float] = 0
    idle_hours: Optional[float] = 0
    fuel_litres: Optional[float] = 0
    fuel_rate: Optional[float] = 0
    meter_reading: Optional[float] = None
    operator: Optional[str] = ""
    work_done: Optional[str] = ""


class AssetServiceIn(BaseModel):
    service_on: Optional[str] = ""
    kind: Optional[str] = "Preventive"
    description: Optional[str] = ""
    vendor: Optional[str] = ""
    parts_cost: Optional[float] = 0
    labour_cost: Optional[float] = 0
    downtime_hours: Optional[float] = 0
    meter_at_service: Optional[float] = None
    out_of_service: Optional[bool] = False     # a breakdown that keeps it off work


class AssetBookIn(BaseModel):
    method: Optional[str] = "WDV"
    life_years: Optional[float] = None
    residual_percent: Optional[float] = 5.0
    put_to_use_on: Optional[str] = ""
    cost: Optional[float] = None
    opening_fy: Optional[str] = ""
    opening_book_value: Optional[float] = 0
    tax_block: Optional[str] = ""


class AssetDisposalIn(BaseModel):
    disposed_on: str
    disposal_value: Optional[float] = 0
    note: Optional[str] = ""


class TaxBlockIn(BaseModel):
    rate: Optional[float] = None
    opening_fy: Optional[str] = ""
    opening_wdv: Optional[float] = 0
