"""Plant and equipment, the fixed asset book."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

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
    make = Column(String, default="")
    model = Column(String, default="")
    reg_no = Column(String, default="")
    serial_no = Column(String, default="")
    purchase_date = Column(String, default="")
    purchase_value = Column(Float, default=0.0)
    hired_from = Column(String, default="")
    hire_rate = Column(Float, default=0.0)
    hire_basis = Column(String, default="Day")               # Hour | Day | Month
    meter_unit = Column(String, default="Hours")             # Hours | Km
    meter_reading = Column(Float, default=0.0)
    service_every = Column(Float, default=0.0)               # meter units between services
    service_every_days = Column(Integer, default=0)
    last_service_on = Column(String, default="")
    last_service_meter = Column(Float, default=0.0)
    insurance_until = Column(String, default="")
    fitness_until = Column(String, default="")               # RTO fitness for vehicles
    current_job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    status = Column(String, default="Available", index=True)  # Available | Deployed | Under repair | Disposed
    notes = Column(Text, default="")
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
