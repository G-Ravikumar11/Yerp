"""Subcontract orders, budgets, the gangs' measurement and their bills."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    event as _sa_event,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import deferred

from app.db.session import Base


# SUBCONTRACT WORK ORDERS
#
# The order a contractor issues *out* to a subcontractor, which is a different
# document from the priced scope sold *in* to a customer (DBWorkOrder above).
# This one carries a BOQ, the legal clauses the trade argues over, statutory
# deductions, and a signature chain - so it lives in its own tables rather
# than growing more nullable columns onto the sales side.
class DBBusinessUnit(Base):
    """The legal entity issuing the order. Its GSTIN prints on the document."""
    __tablename__ = "business_units"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    name = Column(String, default="")
    code = Column(String, default="", index=True)
    gstin = Column(String, default="")
    pan = Column(String, default="")
    address = Column(Text, default="")
    # Its own letterhead where the unit has one, falling back to the account's.
    # A group issuing orders under three trading names needs three letterheads.
    logo_url = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBWorkType(Base):
    """The kinds of work an order can be raised for.

    A taxonomy rather than free text, so the same trade is not filed under
    four spellings - but one an engineer cannot extend on their own, because a
    list anybody may add to is free text with extra steps. What they can do is
    ask for one, which lands as a request for whoever administers the system.
    """
    __tablename__ = "work_types"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    code = Column(String, default="", index=True)
    department = Column(String, default="")
    # active | requested | declined
    status = Column(String, default="active", index=True)
    requested_by = Column(Integer, nullable=True)
    requested_by_name = Column(String, default="")
    request_reason = Column(Text, default="")
    decided_by_name = Column(String, default="")
    decided_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBContractor(Base):
    """A subcontractor. Kept apart from customers: the money runs the other way,
    and what has to be held about them - PAN, bank, GST - is what makes a
    payment legal rather than what makes an invoice addressable."""
    __tablename__ = "contractors"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    vendor_code = Column(String, default="", index=True)
    company_name = Column(String, default="", index=True)
    contact_person = Column(String, default="")
    email = Column(String, default="")
    phone_number = Column(String, default="")
    pan = Column(String, default="")
    gst_number = Column(String, default="")
    bank_name = Column(String, default="")
    bank_account = Column(String, default="")
    bank_ifsc = Column(String, default="")
    address = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # The rest of the Sub Contractor Registration Form, box for box: the
    # project they were taken on for, where they are from, what they do, and
    # the documents collected. A gang is paid on what this form says, so it is
    # held here rather than in a folder of printouts.
    registered_project = Column(String, default="")
    joining_date = Column(String, default="")
    pin_code = Column(String, default="")
    city = Column(String, default="")
    state = Column(String, default="")
    nature_of_work = Column(String, default="")
    entity_type = Column(String, default="")
    aadhaar = Column(String, default="")
    bank_branch = Column(String, default="")
    documents = Column(String, default="")          # comma separated keys of what was collected
    # The uploaded files themselves, {key: {"name", "data": data URL}} - loaded
    # only when one is opened, never with the register. Their names are kept
    # beside them for the list to show.
    document_files = deferred(Column(Text, default="{}"))
    document_names = Column(Text, default="{}")
    declaration_signed = Column(Boolean, default=False)
    # PENDING | APPROVED | REJECTED. Somebody on site can register a gang; it
    # is signed off before an order is issued to them. Rows from before the
    # form existed were never questioned and read as approved.
    registration_status = Column(String, default="APPROVED", index=True)
    registered_by = Column(Integer, nullable=True)
    registered_by_name = Column(String, default="")
    approved_by_name = Column(String, default="")
    approved_at = Column(String, default="")
    rejection_reason = Column(Text, default="")


class DBSubcontractOrder(Base):
    """A work order issued to a subcontractor."""
    __tablename__ = "subcontract_orders"

    id = Column(Integer, primary_key=True, index=True)
    # The last measurement-entry code number given on this order: it only goes up, so no code is ever reused.
    mb_code_seq = Column(Integer, default=0)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    wo_number = Column(String, default="", index=True)
    status = Column(String, default="DRAFT", index=True)
    amendment_no = Column(Integer, default=0)
    supersedes_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True)

    business_unit_id = Column(Integer, ForeignKey("business_units.id"), nullable=True, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    work_type = Column(String, default="")
    department = Column(String, default="")

    subject = Column(Text, default="")
    scope_of_work = Column(Text, default="")

    commencement_date = Column(String, default="")
    completion_date = Column(String, default="")
    duration_months = Column(Float, default=0.0)
    defect_liability_months = Column(Integer, default=0)

    bank_guarantee_applicable = Column(Boolean, default=False)
    bank_guarantee_amount = Column(Float, default=0.0)
    bank_guarantee_validity = Column(String, default="")

    # Held rather than recomputed on read, so an approved order still prints
    # the figures it was approved on after a rate is edited elsewhere.
    gross_amount = Column(Float, default=0.0)
    gst_rate = Column(Float, default=18.0)
    gst_amount = Column(Float, default=0.0)
    tds_rate = Column(Float, default=1.0)
    tds_amount = Column(Float, default=0.0)
    net_order_value = Column(Float, default=0.0)

    # Retention is withheld from each bill and given back later; the advance is
    # paid up front and taken back out of the bills. Neither changes what the
    # contract is worth, which is why they are held apart from the order value
    # rather than netted into it - a contractor who reads 5% retention as a
    # 5% cut in the price will price the next job accordingly.
    retention_percent = Column(Float, default=0.0)
    retention_amount = Column(Float, default=0.0)
    mobilization_advance_percent = Column(Float, default=0.0)
    mobilization_advance_amount = Column(Float, default=0.0)
    advance_recovery_percent = Column(Float, default=0.0)
    # Labour welfare cess - the BOCW levy on the value of construction work,
    # deducted from each bill and remitted to the Welfare Board. Like TDS it
    # is money the contractor never receives, so it comes off the net.
    labour_cess_percent = Column(Float, default=0.0)
    labour_cess_amount = Column(Float, default=0.0)

    # When they may bill and how long we then have to pay: the two payment
    # terms every contractor asks about before signing, printed as a clause.
    billing_cycle = Column(String, default="")        # Monthly | Fortnightly | On milestone
    payment_days = Column(Integer, default=0)         # after certification

    # Where this order was copied from, when it was. A new order for the same
    # trade on the next site starts as a copy of the last one far more often
    # than it starts blank.
    copied_from_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True)

    submitted_by = Column(Integer, nullable=True)
    approved_by = Column(Integer, nullable=True)
    approved_at = Column(String, default="")
    executed_at = Column(String, default="")
    rejection_reason = Column(Text, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBProjectBudget(Base):
    """What a project is allowed to spend, split by cost centre.

    The allocation is held per project rather than per order, because that is
    the question being asked: not "is this order large" but "is there anything
    left to spend on this site". An order is checked against the balance when
    somebody commits the business to it, which is at approval - a draft may be
    priced at any figure, since pricing it is how you find out it is too big.

    Consumption is not stored. It is summed from the orders themselves, so a
    cancelled order gives its money back without anybody having to remember to
    do anything, and a stored counter cannot drift away from the orders it is
    supposed to be counting.
    """
    __tablename__ = "project_budgets"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    code = Column(String, default="", index=True)
    name = Column(String, default="")
    department = Column(String, default="")
    allocated_amount = Column(Float, default=0.0)
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBSubcontractItem(Base):
    """One BOQ line."""
    __tablename__ = "subcontract_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), index=True)
    activity_no = Column(String, default="")
    item_code = Column(String, default="")
    item_description = Column(Text, default="")
    # Kept apart from the description because they are read by different
    # people: the description is what the line is, the specification is what
    # it has to satisfy before it can be measured and certified.
    technical_spec = Column(Text, default="")
    uom = Column(String, default="")
    quantity = Column(Float, default=0.0)
    unit_rate = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    # Which allocation this line spends. The free-text name is kept beside it
    # rather than replaced: orders raised before budgets existed carry one, and
    # a line may legitimately name a cost centre that was never allocated.
    budget_id = Column(Integer, ForeignKey("project_budgets.id"), nullable=True, index=True)
    cost_centre = Column(String, default="")
    display_order = Column(Integer, default=0)
    # A heading row - "ELECTRICAL WORK", "SUB STATION EQUIPMENT" - that the
    # lines under it belong to. It carries no quantity or rate and is never
    # measured; it exists so a two-hundred-line schedule reads as the BOQ it
    # was copied from rather than as a list.
    is_header = Column(Boolean, default=False)
    # How far the measured quantity may run past the ordered one before the
    # order has to be amended. Nought means exactly what was ordered.
    tolerance_percent = Column(Float, default=0.0)
    # The line of the project BOQ this is part of (its stable key), so what is given to gangs can be added up
    # against what the client's BOQ allows.
    boq_key = Column(String, default="", index=True)


class DBSubcontractTerm(Base):
    """A clause. Ordered, because these are read as a numbered schedule."""
    __tablename__ = "subcontract_terms"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), index=True)
    clause_category = Column(String, default="")
    clause_text = Column(Text, default="")
    display_order = Column(Integer, default=0)


class DBOrderAccess(Base):
    """A member of staff the owner (or the one who made the order) has let see it, though they did not
    make it and are not on its route - a site engineer who measures it, say."""
    __tablename__ = "order_access"
    __table_args__ = (UniqueConstraint("order_id", "employee_id", name="uq_order_access"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBSubcontractApproval(Base):
    """Who did what to the order, and what they said about it."""
    __tablename__ = "subcontract_approvals"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(String, default="")
    action = Column(String, default="")
    from_status = Column(String, default="")
    to_status = Column(String, default="")
    comments = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# SUBCONTRACTOR BILLS
#
# The other side of the ledger. A work order is what the client buys from us
# and an RA bill against it is money coming in. A subcontract order is what we
# buy from a gang, and until now it could be signed but never measured or
# billed - so the money going out to the people actually doing the work was
# not in the app at all, and the P&L was flattered by exactly that amount.
#
# Same shape as the client side on purpose: measurements accumulate, a bill
# claims the difference, retention is held and TDS deducted. The difference
# is who holds the retention. Here it is us.
class DBSubMeasurement(Base):
    __tablename__ = "sub_measurements"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("subcontract_items.id"), nullable=False, index=True)
    activity_no = Column(String, default="")
    mb_ref = Column(String, default="")
    location = Column(String, default="")        # where on site: grid, floor, element
    measured_on = Column(String, default="")
    quantity = Column(Float, default=0.0)          # may be negative: a correction
    remarks = Column(String, default="")
    recorded_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    recorded_by_name = Column(String, default="")
    sub_bill_id = Column(Integer, ForeignKey("sub_bills.id"), nullable=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # One block measured, several built alike: "Total Quantity for 4 Blocks".
    # The dimensions are of one; the entry is that many times what they come to.
    multiplier = Column(Float, default=1.0)
    # Where the entry sits in the sheet it came from: its section ("I  Laying of tiles"), its block letter,
    # and which blocks share one hold-back subtotal - so the book can be read like the sheet.
    section = Column(String, default="")
    block_label = Column(String, default="")
    # "" for work measured; "hold" for quantity held back from billing; "release" for a hold put back (hold_of).
    kind = Column(String, default="")
    hold_of = Column(Integer, nullable=True, index=True)
    group_ref = Column(String, default="")
    # The entry's own code, "WO/2026-27/STP/001/MB-007": numbered in the order they are recorded, one series for
    # each order, never reused after an entry is deleted. Given when the entry is saved (see below).
    code = Column(String, default="", index=True)
    code_no = Column(Integer, nullable=True)


class DBMeasurementDimension(Base):
    """One line of a measurement: what was measured and its dimensions.

    A measurement book is a book of dimensions, not of totals. The total is
    what the dimensions come to, and the dimensions are what get checked on
    site - so the book has to hold them, or the real book stays in a
    spreadsheet and the app only ever sees its answer. Held against either
    book, the client's or the gang's. A deduction (an opening in a wall) is a
    line that takes away.
    """
    __tablename__ = "measurement_dimensions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    measurement_id = Column(Integer, ForeignKey("measurements.id"), nullable=True, index=True)
    sub_measurement_id = Column(Integer, ForeignKey("sub_measurements.id"), nullable=True, index=True)
    particulars = Column(String, default="")       # "Footing F1, grid A-3"
    nos = Column(Float, nullable=True)
    length = Column(Float, nullable=True)
    breadth = Column(Float, nullable=True)
    depth = Column(Float, nullable=True)
    deduct = Column(Boolean, default=False)
    quantity = Column(Float, default=0.0)          # the product, signed
    display_order = Column(Integer, default=0)
    # No's x NoM: how many flats, and how many of the member in each - the
    # book's second count. And a heading ("Living Room", "Deductions") that
    # groups the lines under it and measures nothing itself.
    nom = Column(Float, nullable=True)
    is_heading = Column(Boolean, default=False)


class DBSubBill(Base):
    __tablename__ = "sub_bills"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_sub_bill_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)

    number = Column(String, index=True)              # WO/2026-27/STP/001/RA-01
    sequence = Column(Integer, default=1)
    period_from = Column(String, default="")
    period_to = Column(String, default="")
    # DRAFT | SUBMITTED | CERTIFIED | PAID | CANCELLED
    status = Column(String, default="DRAFT", index=True)

    gross_to_date = Column(Float, default=0.0)
    previously_billed = Column(Float, default=0.0)
    this_bill = Column(Float, default=0.0)

    retention_percent = Column(Float, default=0.0)
    retention_amount = Column(Float, default=0.0)     # held back by us
    advance_recovery = Column(Float, default=0.0)     # mobilisation advance clawed back
    other_deductions = Column(Float, default=0.0)
    back_charges = Column(Float, default=0.0)         # open back-charges taken off this bill (back_charges table)
    deduction_notes = Column(String, default="")
    gst_percent = Column(Float, default=0.0)
    gst_amount = Column(Float, default=0.0)           # the gang charges us
    cgst_amount = Column(Float, default=0.0)
    sgst_amount = Column(Float, default=0.0)
    igst_amount = Column(Float, default=0.0)
    place_of_supply = Column(String, default="")
    tds_percent = Column(Float, default=0.0)
    tds_amount = Column(Float, default=0.0)           # we withhold and remit
    labour_cess_percent = Column(Float, default=0.0)
    labour_cess_amount = Column(Float, default=0.0)   # BOCW cess, withheld and remitted
    net_payable = Column(Float, default=0.0)          # what actually leaves the bank

    certified_by = Column(Integer, ForeignKey("employees.id"), nullable=True)
    certified_by_name = Column(String, default="")
    certified_at = Column(String, default="")
    paid_at = Column(String, default="")
    paid_reference = Column(String, default="")
    remarks = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")

    # The Certificate of Payment's own boxes.
    bill_date = Column(String, default="")
    # "" for a bill of everything measured and not yet billed; "chosen" for one drawn from entries picked for it.
    entry_mode = Column(String, default="")
    # The hard copy of this same bill, on paper, scanned and attached before this one is sent up for approval so the
    # approvers can read the two side by side - and the amount of work it claims, to check ours against.
    scan_file_id = Column(Integer, nullable=True)
    scan_name = Column(String, default="")
    scan_type = Column(String, default="")
    scan_size = Column(Integer, default=0)
    scan_amount = Column(Float, nullable=True)
    scan_by_name = Column(String, default="")
    scan_at = Column(String, default="")
    work_type = Column(String, default="")           # 3.3 Type of Work
    work_name = Column(String, default="")           # Name of the Work, on the abstract and the book
    hsn_sac = Column(String, default="")             # 3.2 HSN/SAC
    debit_notes = Column(Float, default=0.0)         # 4.04 Recoveries in Debit Notes, before GST
    # Who prepared it and when it was sent. Certifying then climbs the
    # hierarchy one signature at a time (approval_chains, "sub_bill").
    submitted_by = Column(Integer, nullable=True)
    submitted_by_name = Column(String, default="")
    submitted_at = Column(String, default="")
    approved_by_name = Column(String, default="")    # the last signature - Approved By
    # "Accepted for Sub Contractor": the gang's own signature on the certificate.
    accepted_by_name = Column(String, default="")
    accepted_at = Column(String, default="")


class DBSubBillLine(Base):
    __tablename__ = "sub_bill_lines"

    id = Column(Integer, primary_key=True, index=True)
    sub_bill_id = Column(Integer, ForeignKey("sub_bills.id"), index=True)
    item_id = Column(Integer, ForeignKey("subcontract_items.id"), index=True)
    activity_no = Column(String, default="")
    description = Column(String, default="")
    uom = Column(String, default="")
    ordered_qty = Column(Float, default=0.0)
    measured_to_date = Column(Float, default=0.0)
    previously_billed_qty = Column(Float, default=0.0)
    this_bill_qty = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


class DBMaterialRecovery(Base):
    """Material issued to a gang that is to be taken back out of their bills.

    One row per issue line; split when a bill can bear only part of it, so a
    row is always either waiting or taken by exactly one bill - and a bill
    that is cancelled gives its rows back to be recovered on the next.
    """
    __tablename__ = "material_recoveries"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    stock_issue_id = Column(Integer, ForeignKey("stock_issues.id"), nullable=True, index=True)
    issue_number = Column(String, default="")
    item_code = Column(String, default="")
    item_name = Column(String, default="")
    uom = Column(String, default="")
    quantity = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    sub_bill_id = Column(Integer, ForeignKey("sub_bills.id"), nullable=True, index=True)
    issued_on = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def _give_entry_its_code(mapper, connection, target):
    """Every measurement entry - work, hold or release - gets the next code of its order as it is saved."""
    if target.code:
        return
    from sqlalchemy import select, func
    from sqlalchemy.orm import object_session
    session = object_session(target)
    seen = session.info.setdefault("entry_code_no", {}) if session is not None else {}
    last = seen.get(target.order_id)
    if last is None:
        last = max(connection.execute(select(func.max(DBSubMeasurement.code_no)).where(
            DBSubMeasurement.order_id == target.order_id)).scalar() or 0,
            connection.execute(select(DBSubcontractOrder.mb_code_seq).where(
                DBSubcontractOrder.id == target.order_id)).scalar() or 0)
    number = last + 1
    seen[target.order_id] = number
    connection.execute(DBSubcontractOrder.__table__.update().where(
        DBSubcontractOrder.id == target.order_id).values(mb_code_seq=number))
    wo = connection.execute(select(DBSubcontractOrder.wo_number).where(
        DBSubcontractOrder.id == target.order_id)).scalar() or "MB"
    target.code_no = number
    target.code = "%s/MB-%03d" % (wo, number)


_sa_event.listen(DBSubMeasurement, "before_insert", _give_entry_its_code)
