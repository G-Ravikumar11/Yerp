"""The client's work orders, measurement and running account bills, and variations."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class DBWorkOrder(Base):
    """The priced scope sold to the customer on a job, line by line in FG codes.

    Sits against a job rather than carrying its own customer and project: the
    job already knows who it is for, and duplicating that is how the two drift
    apart. Approval runs through the same hierarchical chain as bills and
    purchase orders, so "MD approved" means the same thing everywhere.
    """
    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_wo_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, index=True)

    order_date = Column(String, default="")
    reference = Column(String, default="")
    notes = Column(Text, default="")

    # Draft | Awaiting Approval | Approved | Rejected | Closed
    status = Column(String, default="Draft", index=True)
    total_value = Column(Float, default=0.0)

    approval_status = Column(String, default="none", index=True)
    submitted_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    current_approval_step = Column(Integer, default=0)
    rejection_reason = Column(String, default="")
    # The project BOQ this order's scope and rates were drawn from.
    boq_id = Column(Integer, ForeignKey("boqs.id"), nullable=True, index=True)

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    job = relationship("DBJob")
    lines = relationship("DBWorkOrderLine", back_populates="work_order")


class DBWorkOrderLine(Base):
    __tablename__ = "work_order_lines"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), index=True)
    fg_code = Column(String, index=True)
    item_name = Column(String, default="")
    description = Column(String, default="")
    qty = Column(Float, default=0.0)
    uom = Column(String, default="")
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)

    work_order = relationship("DBWorkOrder", back_populates="lines")


# MEASUREMENT AND RUNNING ACCOUNT BILLS
#
# The stretch the contracts deck never covered, because it stops at approval -
# and approval is where the money starts moving. Work is measured on site,
# measurements accumulate, and each bill claims the difference between what
# has been measured to date and what has already been billed.
class DBMeasurement(Base):
    """One entry in the measurement book, against one ordered line.

    Entries accumulate rather than replace: the book is a history of what was
    found on site on a given day, and the quantity to date is their sum. A
    correction is a negative entry, not an edit, for the same reason a ledger
    is not rubbed out.
    """
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), index=True)
    line_id = Column(Integer, ForeignKey("work_order_lines.id"), index=True)
    fg_code = Column(String, default="", index=True)

    mb_ref = Column(String, default="")          # the page it is written on
    location = Column(String, default="")        # where on site: grid, floor, element
    measured_on = Column(String, default="")
    quantity = Column(Float, default=0.0)        # may be negative, to correct
    remarks = Column(Text, default="")

    recorded_by = Column(Integer, nullable=True)
    recorded_by_name = Column(String, default="")
    # Joint measurement: the contractor's man signs too, or it is not a
    # measurement, it is an opinion.
    witnessed_by = Column(String, default="")

    ra_bill_id = Column(Integer, ForeignKey("ra_bills.id"), nullable=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBRABill(Base):
    """A running account bill: everything measured to date, less what has
    already been claimed."""
    __tablename__ = "ra_bills"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    number = Column(String, default="", index=True)
    sequence = Column(Integer, default=1)        # RA 1, RA 2, ... on this order
    period_from = Column(String, default="")
    period_to = Column(String, default="")

    # DRAFT | SUBMITTED | CERTIFIED | PAID | CANCELLED
    status = Column(String, default="DRAFT", index=True)

    gross_to_date = Column(Float, default=0.0)   # everything measured, priced
    previously_billed = Column(Float, default=0.0)
    this_bill = Column(Float, default=0.0)       # the difference, and the claim

    retention_percent = Column(Float, default=5.0)
    retention_amount = Column(Float, default=0.0)
    advance_recovery = Column(Float, default=0.0)
    other_deductions = Column(Float, default=0.0)
    deduction_notes = Column(Text, default="")

    tax_percent = Column(Float, default=18.0)
    tax_amount = Column(Float, default=0.0)
    # The split the return needs. Intra-state is half and half; inter-state
    # is all IGST. Decided by our state against the site's.
    cgst_amount = Column(Float, default=0.0)
    sgst_amount = Column(Float, default=0.0)
    igst_amount = Column(Float, default=0.0)
    place_of_supply = Column(String, default="")
    tds_percent = Column(Float, default=1.0)
    tds_amount = Column(Float, default=0.0)
    net_payable = Column(Float, default=0.0)

    submitted_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    certified_by = Column(Integer, nullable=True)
    certified_by_name = Column(String, default="")
    certified_at = Column(String, default="")
    paid_at = Column(String, default="")
    remarks = Column(Text, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBRABillLine(Base):
    """One ordered line as it stands on one bill.

    The three quantities are kept rather than recomputed, because a certified
    bill must still read the same next year when the measurements behind it
    have moved on.
    """
    __tablename__ = "ra_bill_lines"

    id = Column(Integer, primary_key=True, index=True)
    ra_bill_id = Column(Integer, ForeignKey("ra_bills.id"), index=True)
    line_id = Column(Integer, ForeignKey("work_order_lines.id"), nullable=True)
    fg_code = Column(String, default="")
    description = Column(Text, default="")
    uom = Column(String, default="")

    ordered_qty = Column(Float, default=0.0)
    measured_to_date = Column(Float, default=0.0)
    previously_billed_qty = Column(Float, default=0.0)
    this_bill_qty = Column(Float, default=0.0)

    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


class DBVariationOrder(Base):
    """Work that was not in the order but was done anyway.

    Site conditions differ from the schedule, so quantities run over and items
    nobody priced get built. The measurement book already knows this - it marks
    the lines that ran past their ordered quantity. What was missing was the
    step that turns that flag into an agreed, priced, approved change, and
    until it exists the extra work is done, measured, and never paid for.
    """
    __tablename__ = "variation_orders"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_vo_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    number = Column(String, index=True)          # WO-0001/VO-01
    sequence = Column(Integer, default=1)
    # DRAFT | SUBMITTED | APPROVED | REJECTED | CANCELLED
    status = Column(String, default="DRAFT", index=True)
    # measured | manual - whether the app drew this up from the book itself.
    origin = Column(String, default="manual")

    reason = Column(Text, default="")
    value = Column(Float, default=0.0)
    order_value_before = Column(Float, default=0.0)
    order_value_after = Column(Float, default=0.0)

    raised_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    raised_by_name = Column(String, default="")
    approved_by_name = Column(String, default="")
    approved_at = Column(String, default="")
    rejection_reason = Column(String, default="")
    applied_at = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBVariationLine(Base):
    """One changed quantity, or one item the order never had.

    line_id is null for genuinely new work; on approval a fresh order line is
    created for it, so the measurement book can be kept against it afterwards.
    """
    __tablename__ = "variation_lines"

    id = Column(Integer, primary_key=True, index=True)
    variation_order_id = Column(Integer, ForeignKey("variation_orders.id"), index=True)
    line_id = Column(Integer, ForeignKey("work_order_lines.id"), nullable=True, index=True)
    fg_code = Column(String, default="")
    description = Column(String, default="")
    uom = Column(String, default="")

    ordered_qty = Column(Float, default=0.0)     # what the order said before
    measured_qty = Column(Float, default=0.0)    # what the book actually holds
    extra_qty = Column(Float, default=0.0)       # what is being added
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)
