"""Plant beyond the register: who works each machine, the fuel it takes, the machines hired in and what they are billed,
and what else the machines cost. The register itself, the daily log and the services are in assets.py."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

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
    # Finance's word on a bill that differs from the agreement. The amount above stays what the owner billed.
    verification_status = Column(String, default="")      # "" | Approved | Disputed
    expected_at_review = Column(Float, nullable=True)     # what the agreement came to when it was reviewed
    verified_by = Column(String, default="")
    verified_on = Column(String, default="")
    verification_note = Column(Text, default="")
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


class DBPlantMeterEvent(Base):
    """What happened to a machine's meter besides running: replaced, a reading corrected, a gap in the readings explained."""
    __tablename__ = "plant_meter_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    asset_id = Column(Integer, nullable=False, index=True)
    log_id = Column(Integer, nullable=True, index=True)
    kind = Column(String, default="", index=True)          # Replaced | Corrected | GapResolved
    on_date = Column(String, default="", index=True)
    to_date = Column(String, default="")                   # the far end of a gap
    field = Column(String, default="")                     # opening | closing, on a correction
    old_reading = Column(Float, nullable=True)
    new_reading = Column(Float, nullable=True)
    reason = Column(Text, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default=_now)


class DBPlantFuelReview(Base):
    """Somebody's look into a fuel flag. The flags themselves are worked out from the records each time, so a corrected
    record clears its own flag; only the decision is stored."""
    __tablename__ = "plant_fuel_reviews"
    __table_args__ = (UniqueConstraint("fuel_id", "reason", name="uq_plant_fuel_review"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    fuel_id = Column(Integer, nullable=False, index=True)
    reason = Column(String, default="")                    # above_norm | over_tank | no_hours
    status = Column(String, default="Under review")        # Under review | Resolved | Dismissed
    note = Column(Text, default="")
    by_name = Column(String, default="")
    updated_at = Column(String, default=_now)


class DBPlantAlert(Base):
    """One plant alert and how it was delivered. `dedupe_key` is unique: a machine's week, a breakdown, an unbilled month
    can be raised once however many workers try."""
    __tablename__ = "plant_alerts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    kind = Column(String, default="", index=True)          # weekly | emergency | unbilled
    dedupe_key = Column(String, nullable=False, unique=True)
    asset_id = Column(Integer, nullable=True, index=True)
    rental_id = Column(Integer, nullable=True, index=True)
    period = Column(String, default="", index=True)        # 2026-W44 | 2026-10 | the breakdown's date
    title = Column(String, default="")
    body = Column(Text, default="")
    severity = Column(String, default="warning")
    status = Column(String, default="Open", index=True)    # Open | Reviewed | Resolved
    office_alert_id = Column(Integer, nullable=True)       # its line on the bell
    delivery_status = Column(String, default="Pending")    # Pending | Delivered | Failed
    sent_to = Column(String, default="")
    reviewed_by = Column(String, default="")
    reviewed_at = Column(String, default="")
    review_note = Column(Text, default="")
    created_at = Column(String, default=_now, index=True)
