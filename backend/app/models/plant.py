"""Plant beyond the register: who works each machine, the fuel it takes, the machines hired in and what they are billed,
and what else the machines cost. The register itself, the daily log and the services are in assets.py."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBPlantAllocation(Base):
    """One employee on one machine, for a shift, over a stretch of days. Ended, never deleted - the history is the record."""
    __tablename__ = "plant_allocations"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    role = Column(String, default="Operator")              # Operator | Driver | Helper | Technician | Other
    shift = Column(String, default="Day")                  # Day | Night | General
    allocated_on = Column(String, default="")
    start_date = Column(String, default="", index=True)
    end_date = Column(String, default="")                  # "" = open
    supervisor_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    status = Column(String, default="Active", index=True)  # Active | Ended
    notes = Column(Text, default="")
    ended_reason = Column(String, default="")
    created_by = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPlantFuel(Base):
    """Fuel put into a machine: how much, at what price, from whom, against which voucher."""
    __tablename__ = "plant_fuel"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)        # FUEL-0001
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    filled_at = Column(String, default="", index=True)     # 2026-10-13 07:30
    fuel_type = Column(String, default="Diesel")
    litres = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    supplier = Column(String, default="")
    voucher_no = Column(String, default="", index=True)
    meter_reading = Column(Float, nullable=True)
    notes = Column(Text, default="")
    recorded_by = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPlantRentalProvider(Base):
    """Whoever a machine is hired from."""
    __tablename__ = "plant_rental_providers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, default="", index=True)
    contact_person = Column(String, default="")
    mobile = Column(String, default="")
    email = Column(String, default="")
    address = Column(Text, default="")
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    created_at = Column(String, default=_now)


class DBPlantRental(Base):
    """A machine hired in, on its own terms: the agreement, its dates, its rates and what is included."""
    __tablename__ = "plant_rentals"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)        # RNT-0001
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("plant_rental_providers.id"), nullable=False, index=True)
    agreement_no = Column(String, default="", index=True)
    start_date = Column(String, default="")
    expected_return = Column(String, default="")
    actual_return = Column(String, default="")
    rate = Column(Float, default=0.0)
    billing = Column(String, default="Daily")              # Hourly | Daily | Weekly | Monthly
    min_billable_hours = Column(Float, default=0.0)
    overtime_rate = Column(Float, default=0.0)
    transport_charges = Column(Float, default=0.0)
    deposit = Column(Float, default=0.0)
    advance = Column(Float, default=0.0)
    fuel_included = Column(Boolean, default=False)
    operator_included = Column(Boolean, default=False)
    notes = Column(Text, default="")
    created_by = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPlantRentalExtension(Base):
    """A hire run on past its date - kept, so the agreement's history reads in order."""
    __tablename__ = "plant_rental_extensions"

    id = Column(Integer, primary_key=True, index=True)
    rental_id = Column(Integer, ForeignKey("plant_rentals.id"), nullable=False, index=True)
    from_date = Column(String, default="")
    to_date = Column(String, default="")
    reason = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPlantRentalInvoice(Base):
    """The owner's bill for a period of hire, and what has been paid against it."""
    __tablename__ = "plant_rental_invoices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    rental_id = Column(Integer, ForeignKey("plant_rentals.id"), nullable=False, index=True)
    invoice_no = Column(String, default="", index=True)
    invoice_date = Column(String, default="")
    period_from = Column(String, default="")
    period_to = Column(String, default="")
    billed_hours = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    paid = Column(Float, default=0.0)
    paid_on = Column(String, default="")
    payment_ref = Column(String, default="")
    recorded_by = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPlantExpense(Base):
    """Any other cost of running a machine - spares, transport, insurance, wages paid out - entered once, against its voucher."""
    __tablename__ = "plant_expenses"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)        # EXP-0001
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    category = Column(String, default="Other", index=True)
    spent_on = Column(String, default="", index=True)
    description = Column(Text, default="")
    quantity = Column(Float, default=0.0)
    unit_rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    vendor = Column(String, default="")
    invoice_no = Column(String, default="", index=True)
    payment_status = Column(String, default="Unpaid")      # Unpaid | Part paid | Paid
    payment_ref = Column(String, default="")
    approval_status = Column(String, default="Pending")    # Pending | Approved | Rejected
    approved_by = Column(String, default="")
    recorded_by = Column(String, default="")
    created_at = Column(String, default=_now)
