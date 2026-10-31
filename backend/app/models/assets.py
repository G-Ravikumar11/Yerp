"""Plant and equipment, the fixed asset book."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, String, Text

from app.db.session import Base


# EQUIPMENT AND ASSETS
#
# The excavator, the transit mixer, the tower crane, the site generator. What
# the business owns and what it hires in, where each one is today, what it did
# yesterday and what it burned doing it, and when it is next due a service -
# so a machine is not found to be overdue by breaking down on the pour.
class DBAsset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    code = Column(String, default="", index=True)            # EQP-0001
    name = Column(String, default="")                        # "JCB 3DX backhoe"
    category = Column(String, default="")                    # Earthmoving | Concrete | Lifting | ...
    ownership = Column(String, default="Owned")              # Owned | Hired
    brand = Column(String, default="")                       # "JCB" - was make
    model = Column(String, default="")
    reg_no = Column(String, default="")
    purchase_date = Column(String, default="")
    purchase_value = Column(Float, default=0.0)
    hired_from = Column(String, default="")
    hire_rate = Column(Float, default=0.0)
    hire_basis = Column(String, default="Day")               # Hour | Day | Month
    fuel_norm_lph = Column(Float, nullable=True)             # litres an hour it should burn; None = not set
    tank_capacity_l = Column(Float, nullable=True)           # litres its tank holds; None = not set
    meter_unit = Column(String, default="Hours")             # Hours | Km
    meter_reading = Column(Float, default=0.0)
    service_every = Column(Float, default=0.0)               # meter units between services
    service_every_days = Column(Integer, default=0)
    last_service_on = Column(String, default="")
    last_service_meter = Column(Float, nullable=True)        # None: not known - never counted as nought
    # The maintenance schedule: by the meter, the calendar, or whichever comes first.
    service_interval_type = Column(String, default="")       # Both | Meter | Days | None ("" = older record, read from the intervals)
    reminder_meter = Column(Float, nullable=True)            # warn this many meter units early; None = a tenth of the interval
    reminder_days = Column(Integer, nullable=True)           # warn this many days early; None = a tenth, at least 3
    next_service_meter = Column(Float, nullable=True)        # the reading the next service falls due at
    next_service_on = Column(String, default="")             # the date it falls due on
    insurance_until = Column(String, default="")
    fitness_until = Column(String, default="")               # RTO fitness for vehicles
    current_job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)   # the site, when location_type is Site
    location_type = Column(String, default="")               # Yard | Site | Transit; "" = never said, not assumed to be the yard
    status = Column(String, default="Available", index=True)  # Available | Deployed | Under repair | Breakdown | Returned | Disposed
    notes = Column(Text, default="")
    condition = Column(String, default="Good")                # Good | Fair | Poor
    is_archived = Column(Boolean, default=False, index=True)  # off the working register, kept for its history
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAssetMove(Base):
    """Where a machine went and when: to a site, between sites, back to yard."""
    __tablename__ = "asset_moves"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    from_job_id = Column(Integer, nullable=True)
    to_job_id = Column(Integer, nullable=True)
    moved_on = Column(String, default="")
    note = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAssetLog(Base):
    """One machine, one day: hours worked and idle, diesel, the meter, and
    what it cost the site."""
    __tablename__ = "asset_logs"
    __table_args__ = (Index("ux_asset_logs_day_key", "day_key", unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    log_date = Column(String, default="", index=True)
    hours_worked = Column(Float, default=0.0)
    idle_hours = Column(Float, default=0.0)
    fuel_litres = Column(Float, default=0.0)
    fuel_rate = Column(Float, default=0.0)
    fuel_cost = Column(Float, default=0.0)
    hire_cost = Column(Float, default=0.0)
    meter_reading = Column(Float, nullable=True)
    operator = Column(String, default="")
    work_done = Column(String, default="")
    recorded_by_name = Column(String, default="")
    # The logbook: who ran it, in which shift, from when to when, and the meter at each end.
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    shift = Column(String, default="")
    start_time = Column(String, default="")                  # 07:00
    end_time = Column(String, default="")                    # 19:30 - before start means past midnight
    break_minutes = Column(Integer, default=0)
    opening_meter = Column(Float, nullable=True)
    closing_meter = Column(Float, nullable=True)
    breakdown_hours = Column(Float, default=0.0)
    attendance_hours = Column(Float, default=0.0)            # the employee's time on duty - not the machine's
    regular_hours = Column(Float, default=0.0)
    overtime_hours = Column(Float, default=0.0)
    approval_status = Column(String, default="")             # "" (older days) | Submitted | Approved | Rejected
    approved_by = Column(String, default="")
    approved_on = Column(String, default="")
    supervisor_remarks = Column(String, default="")
    # machine|date|shift|person while the line stands: the unique index is what stops the same line twice. Empty on a
    # rejected line and on the older days, which are kept as they were.
    day_key = Column(String, nullable=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAssetService(Base):
    """A service, a breakdown or a repair, and what it cost."""
    __tablename__ = "asset_services"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    service_on = Column(String, default="", index=True)
    kind = Column(String, default="Preventive")              # Preventive | Breakdown | Repair
    description = Column(Text, default="")
    vendor = Column(String, default="")
    parts_cost = Column(Float, default=0.0)
    labour_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)
    downtime_hours = Column(Float, default=0.0)
    meter_at_service = Column(Float, nullable=True)
    recorded_by_name = Column(String, default="")
    # As a maintenance request: raised, scheduled, worked, completed and approved.
    number = Column(String, default="", index=True)          # MNT-0001
    priority = Column(String, default="Normal")              # Low | Normal | High | Urgent
    status = Column(String, default="Completed", index=True)  # Requested | Scheduled | In progress | Completed
    reported_on = Column(String, default="")
    scheduled_on = Column(String, default="")
    completed_on = Column(String, default="")
    mechanic = Column(String, default="")
    parts_used = Column(Text, default="")
    downtime_start = Column(String, default="")
    downtime_end = Column(String, default="")
    work_performed = Column(Text, default="")
    invoice_no = Column(String, default="")
    next_service_on = Column(String, default="")
    next_service_meter = Column(Float, nullable=True)
    approval_status = Column(String, default="")             # "" | Approved
    approved_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# FIXED ASSETS
#
# What each owned asset is worth on the books: cost, how it wears down (WDV
# or straight line, over a life), and what it fetched when it went. Kept
# beside the equipment register rather than in it, because an asset's book
# is an accountant's record and its register is a site's.
class DBAssetBook(Base):
    __tablename__ = "asset_books"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    method = Column(String, default="WDV")               # WDV | SLM
    life_years = Column(Float, default=15.0)
    residual_percent = Column(Float, default=5.0)
    put_to_use_on = Column(String, default="")
    cost = Column(Float, default=0.0)
    # An asset bought before the app: the book value it carried at the start
    # of this financial year, as the last audited accounts have it.
    opening_fy = Column(String, default="")              # "2025-26"
    opening_book_value = Column(Float, default=0.0)
    tax_block = Column(String, default="Plant & machinery")
    disposed_on = Column(String, default="")
    disposal_value = Column(Float, default=0.0)
    disposal_note = Column(String, default="")
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
