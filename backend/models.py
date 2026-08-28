from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime
import uuid
import hashlib
import os


def hash_password(password: str) -> str:
    salt = hashlib.sha256(os.urandom(32)).hexdigest().encode()
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return salt.hex() + ':' + pwd_hash.hex()


def verify_password(password: str, stored: str) -> bool:
    if ':' not in stored:
        return hashlib.sha256(password.encode()).hexdigest() == stored
    salt_hex, pwd_hash_hex = stored.split(':')
    salt = bytes.fromhex(salt_hex)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return pwd_hash.hex() == pwd_hash_hex


class DBClient(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    company_name = Column(String, default="")
    contact_name = Column(String, default="")
    phone_number = Column(String, default="")
    logo_url = Column(String, default="")
    address = Column(String, default="")
    website = Column(String, default="")
    abn = Column(String, default="")
    industry = Column(String, default="")
    is_active = Column(Boolean, default=True)
    is_onboarded = Column(Boolean, default=False)
    currency = Column(String, default="INR")
    last_login = Column(String, default="")
    login_count = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    settings = relationship("DBSettings", back_populates="client")
    invoices = relationship("DBInvoice", back_populates="client")
    bills = relationship("DBBill", back_populates="client")
    contacts = relationship("DBContact", back_populates="client")
    departments = relationship("DBDepartment", back_populates="client")
    employees = relationship("DBEmployee", back_populates="client")
    attendance = relationship("DBAttendance")


class DBInvoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_invoice_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    number = Column(String, index=True)
    ref = Column(String, default="")
    to_contact = Column(String)
    email = Column(String, default="")
    phone_number = Column(String, default="")
    issue_date = Column(String)
    due_date = Column(String)
    paid = Column(Float, default=0.0)
    due = Column(Float, default=0.0)
    status = Column(String, default="Draft", index=True)
    sent = Column(String, default="")
    tax_type = Column(String, default="exclusive")
    currency = Column(String, default="")
    bank_details = Column(String, default="")
    tracking_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    open_count = Column(Integer, default=0)
    last_opened = Column(String, default="")

    # Hierarchical approval. "none" means the document never entered the
    # workflow, which is the normal case for a tenant that does not use it.
    # none | pending | approved | rejected
    approval_status = Column(String, default="none", index=True)
    submitted_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    current_approval_step = Column(Integer, default=0)

    # Which job this was billed against, so revenue lands where the cost did.
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    line_items = relationship("DBLineItem", back_populates="invoice")
    client = relationship("DBClient", back_populates="invoices")


class DBPayment(Base):
    """A single receipt against an invoice. Invoices keep running `paid`/`due`
    totals; this table is the ledger that explains how they got there."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    amount = Column(Float, default=0.0)
    paid_on = Column(String, default="")
    method = Column(String, default="bank_transfer")
    reference = Column(String, default="")
    note = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBLineItem(Base):
    __tablename__ = "line_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), index=True)
    name = Column(String, default="")
    description = Column(String)
    qty = Column(Float)
    price = Column(Float)
    disc = Column(Float, default=0.0)
    account = Column(String, default="200 - Sales")
    tax_rate = Column(String, default="20% (VAT on Income)")

    invoice = relationship("DBInvoice", back_populates="line_items")


class DBRecurringInvoice(Base):
    """A standing instruction to raise the same invoice on a schedule.

    Holds the lines itself rather than pointing at an invoice, so editing the
    template never rewrites invoices already issued from it.
    """
    __tablename__ = "recurring_invoices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, default="")
    to_contact = Column(String, default="")
    email = Column(String, default="")
    phone_number = Column(String, default="")
    reference = Column(String, default="")
    tax_type = Column(String, default="exclusive")
    currency = Column(String, default="")
    bank_details = Column(String, default="")
    # weekly | monthly | quarterly | yearly
    frequency = Column(String, default="monthly")
    # Days after issue that the generated invoice falls due.
    payment_terms_days = Column(Integer, default=14)
    next_run = Column(String, default="", index=True)
    end_date = Column(String, default="")
    is_active = Column(Boolean, default=True, index=True)
    # Whether to email each one as it is raised, or leave it as a draft.
    auto_send = Column(Boolean, default=False)
    last_run = Column(String, default="")
    last_invoice_number = Column(String, default="")
    invoices_created = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    line_items = relationship("DBRecurringLineItem", back_populates="template")


class DBRecurringLineItem(Base):
    __tablename__ = "recurring_line_items"

    id = Column(Integer, primary_key=True, index=True)
    recurring_id = Column(Integer, ForeignKey("recurring_invoices.id"), index=True)
    name = Column(String, default="")
    description = Column(String)
    qty = Column(Float)
    price = Column(Float)
    disc = Column(Float, default=0.0)
    account = Column(String, default="200 - Sales")
    tax_rate = Column(String, default="20% (VAT on Income)")

    template = relationship("DBRecurringInvoice", back_populates="line_items")


class DBInvoiceReminder(Base):
    """One chase actually sent, so the same one is never sent twice."""
    __tablename__ = "invoice_reminders"
    __table_args__ = (
        UniqueConstraint('invoice_id', 'stage_days', name='uq_invoice_reminder_stage'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    # Which rung of the ladder this was: days past due.
    stage_days = Column(Integer, default=0)
    sent_to = Column(String, default="")
    sent_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBInterviewReminder(Base):
    """One interview reminder actually sent, so nobody is nudged twice."""
    __tablename__ = "interview_reminders"
    __table_args__ = (
        UniqueConstraint('interview_id', 'recipient', name='uq_interview_reminder'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), nullable=False, index=True)
    # "candidate" or "interviewer" - each gets at most one.
    recipient = Column(String, default="candidate")
    sent_to = Column(String, default="")
    sent_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBJobRun(Base):
    """A claim on one run of one scheduled job.

    Railway can run more than one worker, and each would otherwise fire the
    same job. The unique constraint is the lock: whoever inserts the row for a
    period gets to do the work, everyone else finds it taken.
    """
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint('job_name', 'period_key', name='uq_job_period'),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String, nullable=False, index=True)
    # What "this run" means for the job - usually a date, so a daily job runs
    # once a day however often the loop wakes up.
    period_key = Column(String, nullable=False, index=True)
    status = Column(String, default="running")
    detail = Column(String, default="")
    started_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    finished_at = Column(String, default="")


class DBTeamMember(Base):
    """Somebody who works at a tenant, other than the account owner.

    The owner stays on DBClient, which is where the company and its original
    credentials live. Everyone else is a row here, so adding colleagues never
    touches the record the whole tenancy hangs off.
    """
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint('client_id', 'email', name='uq_client_member_email'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    name = Column(String, default="")
    password_hash = Column(String, default="")
    # owner: everything. admin: everything but the team and the wallet.
    # viewer: read-only, enforced centrally rather than endpoint by endpoint.
    role = Column(String, default="admin", index=True)
    is_active = Column(Boolean, default=True)
    invited_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    accepted_at = Column(String, default="")
    last_login = Column(String, default="")


class DBPasswordReset(Base):
    """One password reset link.

    Only a hash of the token is kept, the same way passwords are, so a copy of
    this table is not a set of working reset links.
    """
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    # Owners and staff both need a way back in, and the mechanism is identical,
    # so one table serves both rather than two that can drift apart.
    user_type = Column(String, default="client", index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    member_id = Column(Integer, ForeignKey("team_members.id"), nullable=True, index=True)
    token_hash = Column(String, nullable=False, index=True)
    expires_at = Column(String, nullable=False)
    used_at = Column(String, default="")
    requested_ip = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBTaxRate(Base):
    """A tax rate the tenant can pick when writing a line.

    This is only the picker. Documents store the rendered label ("20% VAT") on
    the line itself, so editing or deleting a rate here never restates an
    invoice that has already gone out.
    """
    __tablename__ = "tax_rates"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    percent = Column(Float, default=0.0)
    sort_order = Column(Integer, default=0)
    is_default = Column(Boolean, default=False)


class DBQuote(Base):
    """A priced proposal, before any money is owed.

    Deliberately a separate table from invoices rather than a status on one:
    a quote has an expiry instead of a due date, is never part-paid, and must
    keep its own numbering sequence so QU-0007 does not consume INV-0007.
    """
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_quote_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    number = Column(String, index=True)
    ref = Column(String, default="")
    to_contact = Column(String)
    email = Column(String, default="")
    phone_number = Column(String, default="")
    issue_date = Column(String)
    expiry_date = Column(String)
    total = Column(Float, default=0.0)
    # Draft, Sent, Accepted, Declined, Expired, Invoiced
    status = Column(String, default="Draft", index=True)
    sent = Column(String, default="")
    tax_type = Column(String, default="exclusive")
    currency = Column(String, default="")
    title = Column(String, default="")
    summary = Column(String, default="")
    terms = Column(String, default="")
    # Set once the quote has been turned into an invoice, so it cannot be
    # converted twice.
    invoice_number = Column(String, default="")
    decided_at = Column(String, default="")

    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    line_items = relationship("DBQuoteLineItem", back_populates="quote")


class DBQuoteLineItem(Base):
    __tablename__ = "quote_line_items"

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(Integer, ForeignKey("quotes.id"), index=True)
    name = Column(String, default="")
    description = Column(String)
    qty = Column(Float)
    price = Column(Float)
    disc = Column(Float, default=0.0)
    account = Column(String, default="200 - Sales")
    tax_rate = Column(String, default="20% (VAT on Income)")

    quote = relationship("DBQuote", back_populates="line_items")


class DBJob(Base):
    """A job, site or contract - the thing a contracting business actually
    makes or loses money on.

    Everything priced, bought or worked hangs off one of these: quotes,
    invoices, bills, purchase orders and hours. Without it the books answer
    "what did we turn over" but never "did Fairview make money", which is the
    question that decides whether to take the next one like it.

    Deliberately nullable everywhere it is referenced. A business that does not
    work job-by-job carries on exactly as before.
    """
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_job_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, index=True)
    name = Column(String, nullable=False)

    # Who it is for. The contact is the link to the customer record; the name is
    # kept alongside so a job still reads correctly if the contact is deleted.
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    customer_name = Column(String, default="")

    site_address = Column(String, default="")
    description = Column(Text, default="")

    # quoting | won | in_progress | on_hold | complete | cancelled
    status = Column(String, default="quoting", index=True)
    start_date = Column(String, default="")
    target_end_date = Column(String, default="")
    completed_at = Column(String, default="")

    # What it was sold for, and what it was expected to cost. Margin is the gap.
    quoted_value = Column(Float, default=0.0)
    budget = Column(Float, default=0.0)
    currency = Column(String, default="")

    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    reference = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    contact = relationship("DBContact")
    manager = relationship("DBEmployee")


class DBPurchaseOrder(Base):
    """Spend committed to a supplier, agreed before the work or delivery.

    The bill approval chain answers "should we have spent this" after the money
    is already owed. A purchase order asks the same question while the answer
    can still change anything, which is the whole point of having one.
    """
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_po_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    number = Column(String, index=True)

    supplier_name = Column(String, default="")
    supplier_email = Column(String, default="")

    issue_date = Column(String, default="")
    needed_by = Column(String, default="")

    amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)

    # Draft | Awaiting Approval | Approved | Rejected | Closed | Cancelled
    status = Column(String, default="Draft", index=True)
    category = Column(String, default="general")
    reference = Column(String, default="")
    notes = Column(Text, default="")

    approval_status = Column(String, default="none", index=True)
    submitted_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    current_approval_step = Column(Integer, default=0)
    rejection_reason = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    job = relationship("DBJob")
    line_items = relationship("DBPurchaseOrderLineItem", back_populates="order")


class DBPurchaseOrderLineItem(Base):
    __tablename__ = "purchase_order_line_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), index=True)
    description = Column(String, default="")
    qty = Column(Float, default=1.0)
    price = Column(Float, default=0.0)
    tax_rate = Column(String, default="20%")

    order = relationship("DBPurchaseOrder", back_populates="line_items")


class DBItem(Base):
    """The item master: everything a contract is allowed to reference.

    Two kinds share the table because they share every field and are picked
    from the same sheet:

      RM - raw material. Master stock, reused across jobs. Re-uploading an
           existing code is not a mistake; the row is skipped.
      FG - finished goods. One code is one deliverable on one contract, so a
           duplicate is an error and the ERP code has to change.

    That asymmetry is the whole reason `kind` is part of the unique key rather
    than the code alone.
    """
    __tablename__ = "erp_items"
    __table_args__ = (
        # Unique across the whole system, not per tenant. A code is issued
        # from one global sequence, so one code is one item everywhere and a
        # code read off a delivery note never means two different things.
        UniqueConstraint('item_code', name='uq_item_code'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)          # RM | FG
    item_code = Column(String, nullable=False, index=True)
    item_name = Column(String, nullable=False)
    segment = Column(String, default="")
    description = Column(String, default="")
    category = Column(String, default="")                      # RAW MATERIAL | FINISHED GOOD
    sub_category = Column(String, default="")                  # RM | FG
    hsn_code = Column(String, default="")
    item_tax_type = Column(String, default="")
    item_type = Column(String, default="Purchased")            # Purchased | Service
    units_of_measure = Column(String, default="Nos")
    make = Column(String, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCodeSequence(Base):
    """The counter behind the issued codes.

    A row per series, incremented under a row lock, so two people saving at the
    same moment cannot be handed the same number. Deriving the next code by
    scanning the items table instead would race exactly where it matters.
    """
    __tablename__ = "code_sequences"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    next_value = Column(Integer, default=1, nullable=False)
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


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


class DBBomLine(Base):
    """Budget allocation: what raw material each sold FG line consumes.

    Sale value comes from the work order line, cost from here. The gap between
    them is the margin the contract was actually won on, which is the figure an
    approver is being asked to sign off.
    """
    __tablename__ = "bom_lines"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    fg_code = Column(String, index=True)
    rm_code = Column(String, index=True)
    rm_name = Column(String, default="")
    qty = Column(Float, default=0.0)
    uom = Column(String, default="")
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBSettings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    key = Column(String, index=True)
    value = Column(String)
    description = Column(String, default="")

    client = relationship("DBClient", back_populates="settings")


class DBContact(Base):
    """A customer. Invoices address one, projects belong to one.

    The billing side only ever needed a name and a way to reach somebody. A
    contract needs the rest - who signs, where to send the invoice, and the
    GST number that has to appear on it - so those live here rather than being
    retyped onto every document.
    """
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, index=True)
    email = Column(String)
    phone_number = Column(String)

    code = Column(String, default="", index=True)
    contact_person = Column(String, default="")
    gstin = Column(String, default="")
    address = Column(String, default="")
    city = Column(String, default="")
    state = Column(String, default="")
    pincode = Column(String, default="")
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="contacts")


class DBSuperAdmin(Base):
    __tablename__ = "super_admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    email = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)


class DBDepartment(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    color = Column(String, default="#00f0ff")
    icon = Column(String, default="building")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="departments")
    employees = relationship("DBEmployee", back_populates="department")


class DBEmployee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    reports_to = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)

    employee_id = Column(String, default="")
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, default="")
    address = Column(String, default="")

    job_title = Column(String, default="")
    role = Column(String, default="employee")
    # What this person may DO in the portal, decided by HR. Deliberately
    # separate from `role`, which is their place in the reporting line: a site
    # supervisor may need to raise costs without being anyone's manager, and a
    # department head may have no business touching payroll.
    permission_role = Column(String, default="staff", index=True)
    # What the owner has granted or withheld for this person on top of their
    # role. A role is a sensible starting point, not a straitjacket: one
    # supervisor may also settle bills, one manager may be kept out of payroll,
    # and neither should need a new role invented for them. Comma separated
    # permission keys; a denial beats a grant.
    extra_permissions = Column(Text, default="")
    denied_permissions = Column(Text, default="")
    # Seniority band (L1..L8). Kept separate from `role`, which describes what
    # the person does in the reporting line, not how senior they are.
    level = Column(String, default="", index=True)
    employment_type = Column(String, default="full_time")
    pay_frequency = Column(String, default="monthly")

    salary = Column(Float, default=0.0)
    hourly_rate = Column(Float, default=0.0)
    tax_rate = Column(Float, default=0.0)
    deductions = Column(Float, default=0.0)
    allowances = Column(Float, default=0.0)
    bonus = Column(Float, default=0.0)

    bank_name = Column(String, default="")
    bank_account = Column(String, default="")
    tax_id = Column(String, default="")

    emergency_contact = Column(String, default="")
    emergency_phone = Column(String, default="")

    annual_leave_entitlement = Column(Float, default=25.0)
    sick_leave_entitlement = Column(Float, default=10.0)

    password_hash = Column(String, default="")
    work_location = Column(String, default="")
    latitude = Column(Float, default=0.0)
    longitude = Column(Float, default=0.0)

    start_date = Column(String, default="")
    end_date = Column(String, default="")
    status = Column(String, default="active", index=True)
    onboarding_complete = Column(Boolean, default=False)
    offboarding_complete = Column(Boolean, default=False)

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="employees")
    department = relationship("DBDepartment", back_populates="employees")
    manager = relationship("DBEmployee", remote_side=[id], backref="direct_reports")
    payslips = relationship("DBPayslip", back_populates="employee")
    onboarding_items = relationship("DBOnboardingItem", back_populates="employee")
    attendance = relationship("DBAttendance")


class DBPayslip(Base):
    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_payslip_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    number = Column(String, index=True)

    period_start = Column(String, default="")
    period_end = Column(String, default="")
    pay_date = Column(String, default="")

    hours_worked = Column(Float, default=0.0)
    overtime_hours = Column(Float, default=0.0)
    overtime_rate = Column(Float, default=0.0)

    basic_salary = Column(Float, default=0.0)
    overtime_pay = Column(Float, default=0.0)
    bonus = Column(Float, default=0.0)
    allowances = Column(Float, default=0.0)
    gross_pay = Column(Float, default=0.0)

    tax_amount = Column(Float, default=0.0)
    insurance = Column(Float, default=0.0)
    retirement = Column(Float, default=0.0)
    other_deductions = Column(Float, default=0.0)
    total_deductions = Column(Float, default=0.0)

    net_pay = Column(Float, default=0.0)

    status = Column(String, default="Draft", index=True)
    sent = Column(String, default="")
    notes = Column(String, default="")
    pay_frequency = Column(String, default="")

    tracking_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    open_count = Column(Integer, default=0)
    last_opened = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee", back_populates="payslips")


class DBOnboardingItem(Base):
    __tablename__ = "onboarding_items"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    title = Column(String, nullable=False)
    description = Column(String, default="")
    category = Column(String, default="general")
    is_completed = Column(Boolean, default=False)
    completed_at = Column(String, default="")
    assigned_to = Column(String, default="")
    due_date = Column(String, default="")
    sort_order = Column(Integer, default=0)

    employee = relationship("DBEmployee", back_populates="onboarding_items")


class DBOnboardingTemplate(Base):
    __tablename__ = "onboarding_templates"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    items_json = Column(Text, default="[]")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAttendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(String, nullable=False, index=True)
    clock_in = Column(String, default="")
    clock_out = Column(String, default="")
    total_hours = Column(Float, default=0.0)
    status = Column(String, default="present", index=True)
    check_type = Column(String, default="manual")
    ip_address = Column(String, default="")
    device_info = Column(String, default="")
    location_lat = Column(Float, default=0.0)
    location_lng = Column(Float, default=0.0)
    location_label = Column(String, default="")
    break_start = Column(String, default="")
    break_minutes = Column(Float, default=0.0)
    is_on_break = Column(Boolean, default=False)
    overtime_hours = Column(Float, default=0.0)
    overtime_announced = Column(Boolean, default=False)
    overtime_announced_by = Column(String, default="")
    # Which job the day was worked on, so labour reaches job costing. Left
    # empty for office staff and anyone whose time is not chargeable to a site.
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    notes = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAttendanceSettings(Base):
    __tablename__ = "attendance_settings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, unique=True)
    office_name = Column(String, default="Head Office")
    office_lat = Column(Float, default=0.0)
    office_lng = Column(Float, default=0.0)
    geofence_radius = Column(Float, default=200.0)
    work_start = Column(String, default="09:00")
    work_end = Column(String, default="17:30")
    grace_minutes = Column(Float, default=15.0)
    auto_clockout_hours = Column(Float, default=10.0)
    max_overtime_hours = Column(Float, default=4.0)
    allow_remote = Column(Boolean, default=True)
    require_location = Column(Boolean, default=True)
    # ISO weekday numbers, Monday = 1 through Sunday = 7.
    working_days = Column(String, default="1,2,3,4,5")
    # Whether signing in to the portal counts as starting a shift. Off means
    # people clock in deliberately, so opening the portal on a day off - to
    # read a payslip or upload a document - does not record attendance.
    auto_clock_in = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBClientLoginLog(Base):
    __tablename__ = "client_login_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    email = Column(String, nullable=False)
    user_type = Column(String, default="client")
    login_type = Column(String, default="password")
    ip_address = Column(String, default="")
    device_info = Column(String, default="")
    location_label = Column(String, default="")
    status = Column(String, default="success")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBOvertimeLog(Base):
    __tablename__ = "overtime_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(String, nullable=False)
    hours = Column(Float, default=0.0)
    reason = Column(String, default="")
    announced_by = Column(String, default="")
    status = Column(String, default="announced")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBJobRequisition(Base):
    """An open role. The application form describes *how* to apply; the
    requisition describes *what* is being hired for, which is what a hiring
    manager, the job board and the reporting all key off."""
    __tablename__ = "job_requisitions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    reference = Column(String, default="", index=True)
    title = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    hiring_manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)

    description = Column(Text, default="")
    requirements = Column(Text, default="")
    location = Column(String, default="")
    work_mode = Column(String, default="onsite")       # onsite | hybrid | remote
    employment_type = Column(String, default="full_time")
    level = Column(String, default="")

    salary_min = Column(Float, default=0.0)
    salary_max = Column(Float, default=0.0)
    salary_currency = Column(String, default="")
    show_salary = Column(Boolean, default=True)

    openings = Column(Integer, default=1)
    status = Column(String, default="draft", index=True)  # draft|open|on_hold|closed|filled
    is_published = Column(Boolean, default=False, index=True)
    closing_date = Column(String, default="")
    opened_at = Column(String, default="")
    closed_at = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    department = relationship("DBDepartment")
    hiring_manager = relationship("DBEmployee")


class DBRecruitmentForm(Base):
    __tablename__ = "recruitment_forms"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("job_requisitions.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    fields = Column(Text, default="[]")
    is_active = Column(Boolean, default=True)
    form_token = Column(String, unique=True, index=True, default=lambda: str(__import__('uuid').uuid4()))
    pipeline_stages = Column(Text, default='["Applied","Screening","Interview","Offer","Hired"]')
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    job = relationship("DBJobRequisition")


class DBInterview(Base):
    """A scheduled conversation with a candidate, plus the scorecard."""
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)

    round_name = Column(String, default="Interview")
    scheduled_at = Column(String, default="", index=True)   # YYYY-MM-DD HH:MM
    duration_minutes = Column(Integer, default=45)
    mode = Column(String, default="video")                  # video | phone | onsite
    location = Column(String, default="")
    meeting_link = Column(String, default="")
    interviewer_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    interviewer_name = Column(String, default="")

    status = Column(String, default="scheduled", index=True)  # scheduled|completed|cancelled|no_show
    outcome = Column(String, default="")                      # pass | fail | hold
    score = Column(Integer, default=0)                        # 0-5
    feedback = Column(Text, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    interviewer = relationship("DBEmployee")


class DBOffer(Base):
    """An offer extended to a candidate."""
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)

    job_title = Column(String, default="")
    level = Column(String, default="")
    salary = Column(Float, default=0.0)
    currency = Column(String, default="")
    start_date = Column(String, default="")
    expires_on = Column(String, default="")
    notes = Column(Text, default="")

    status = Column(String, default="draft", index=True)  # draft|sent|accepted|declined|withdrawn
    sent_at = Column(String, default="")
    responded_at = Column(String, default="")
    decline_reason = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBFormSubmission(Base):
    __tablename__ = "form_submissions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    form_id = Column(Integer, ForeignKey("recruitment_forms.id"), nullable=False, index=True)
    answers = Column(Text, default="{}")
    file_name = Column(String, default="")
    file_type = Column(String, default="")
    file_data = Column(Text, default="")
    candidate_name = Column(String, default="")
    candidate_email = Column(String, default="")
    candidate_phone = Column(String, default="")
    status = Column(String, default="new")
    current_stage = Column(String, default="Applied")
    stage_order = Column(Integer, default=0)
    rating = Column(Integer, default=0)
    notes = Column(String, default="")
    source = Column(String, default="direct")
    owner_name = Column(String, default="")
    rejected_reason = Column(String, default="")
    rejected_at = Column(String, default="")
    hired_at = Column(String, default="")
    hired_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    form = relationship("DBRecruitmentForm")
    documents = relationship("DBCandidateDocument", back_populates="submission")


class DBCandidateDocument(Base):
    """Files attached to an application. The submission row carries a single
    legacy attachment; a candidate normally sends several (CV, cover letter,
    right-to-work, certificates), so they live here."""
    __tablename__ = "candidate_documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)
    doc_type = Column(String, default="other")
    file_name = Column(String, default="")
    file_type = Column(String, default="")
    file_size = Column(Integer, default=0)
    file_data = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    submission = relationship("DBFormSubmission", back_populates="documents")


class DBSubmissionEvent(Base):
    """Audit trail of a candidate's movement through the pipeline."""
    __tablename__ = "submission_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)
    from_stage = Column(String, default="")
    to_stage = Column(String, default="")
    note = Column(String, default="")
    actor = Column(String, default="HR")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBEmployeeGoal(Base):
    __tablename__ = "employee_goals"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    target_value = Column(Float, default=100.0)
    current_value = Column(Float, default=0.0)
    unit = Column(String, default="%")
    category = Column(String, default="performance")
    priority = Column(String, default="medium")
    start_date = Column(String, default="")
    due_date = Column(String, default="")
    status = Column(String, default="in_progress")
    created_by = Column(String, default="HR")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee")
    department = relationship("DBDepartment")


class DBDepartmentGoal(Base):
    __tablename__ = "department_goals"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    target_value = Column(Float, default=100.0)
    unit = Column(String, default="%")
    category = Column(String, default="performance")
    priority = Column(String, default="medium")
    start_date = Column(String, default="")
    due_date = Column(String, default="")
    created_by = Column(String, default="HR")
    is_assigned = Column(Boolean, default=False)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    department = relationship("DBDepartment")


class DBAuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    user_type = Column(String, default="client")
    user_name = Column(String, default="")
    action = Column(String, nullable=False)
    entity_type = Column(String, default="")
    entity_id = Column(Integer, nullable=True)
    entity_name = Column(String, default="")
    details = Column(Text, default="")
    ip_address = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBNotification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(String, default="")
    type = Column(String, default="info")
    is_read = Column(Boolean, default=False)
    link = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBLeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    leave_type = Column(String, default="annual")
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    days = Column(Float, default=0.0)
    reason = Column(String, default="")
    status = Column(String, default="pending")
    approved_by = Column(String, default="")
    decided_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee")


class DBDocument(Base):
    __tablename__ = "employee_documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    doc_type = Column(String, default="other")
    file_name = Column(String, default="")
    file_type = Column(String, default="")
    file_size = Column(Integer, default=0)
    file_data = Column(Text, default="")
    uploaded_by = Column(String, default="HR")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBDocumentRequirement(Base):
    """What HR asks new starters to provide.

    This is the template. Each employee gets their own request row against it,
    so a policy change does not rewrite what someone already submitted.
    """
    __tablename__ = "document_requirements"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    doc_type = Column(String, default="other")
    is_mandatory = Column(Boolean, default=True)
    due_days = Column(Integer, default=7)          # days after start date

    # Documents like a passport, visa or DBS check go out of date. HR decides
    # which ones need an expiry, and the employee supplies the actual date.
    requires_expiry = Column(Boolean, default=False)
    expiry_reminder_days = Column(Integer, default=30)

    # An optional blank form for the employee to download, complete and return.
    template_file_name = Column(String, default="")
    template_file_type = Column(String, default="")
    template_file_data = Column(Text, default="")

    applies_to = Column(String, default="all")     # all | department | level
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    level = Column(String, default="")
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    department = relationship("DBDepartment")


class DBDocumentRequest(Base):
    """One employee's obligation to provide one document, and its review."""
    __tablename__ = "document_requests"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    requirement_id = Column(Integer, ForeignKey("document_requirements.id"), nullable=True, index=True)
    document_id = Column(Integer, ForeignKey("employee_documents.id"), nullable=True)

    name = Column(String, nullable=False)          # copied so it survives template edits
    description = Column(String, default="")
    doc_type = Column(String, default="other")
    is_mandatory = Column(Boolean, default=True)
    due_date = Column(String, default="")

    # Supplied by the employee when the requirement asks for it.
    requires_expiry = Column(Boolean, default=False)
    expires_on = Column(String, default="", index=True)

    status = Column(String, default="pending", index=True)  # pending|submitted|approved|rejected
    submitted_at = Column(String, default="")
    reviewed_at = Column(String, default="")
    reviewed_by = Column(String, default="")
    review_note = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee")
    document = relationship("DBDocument")
    # Needed so a request can report its template and reminder window; without
    # it the lookups silently returned None.
    requirement = relationship("DBDocumentRequirement")


class DBBill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_bill_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    number = Column(String, index=True)
    vendor_name = Column(String, default="")
    vendor_email = Column(String, default="")
    issue_date = Column(String)
    due_date = Column(String)
    amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    amount_paid = Column(Float, default=0.0)
    # Draft | Awaiting Approval | Approved for payment | Paid | Rejected
    status = Column(String, default="Draft", index=True)
    category = Column(String, default="general")
    reference = Column(String, default="")
    notes = Column(String, default="")

    # Hierarchical approval. A bill raised by a member of staff walks up the
    # reporting line; only once it is approved may finance pay it.
    # none | pending | approved | rejected
    approval_status = Column(String, default="none", index=True)
    submitted_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    current_approval_step = Column(Integer, default=0)
    # Why the last approver sent it back, so the submitter can fix and resubmit.
    rejection_reason = Column(String, default="")

    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    # The order this bill is settling, when there was one. Matching the two is
    # what turns "approved after the fact" into "we agreed this beforehand".
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True, index=True)

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="bills")

    line_items = relationship("DBBillLineItem", back_populates="bill")


class DBBillLineItem(Base):
    __tablename__ = "bill_line_items"

    id = Column(Integer, primary_key=True, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), index=True)
    description = Column(String, default="")
    qty = Column(Float, default=1.0)
    price = Column(Float, default=0.0)
    tax_rate = Column(String, default="20%")

    bill = relationship("DBBill", back_populates="line_items")


# ===========================================================================
# WALLET & BILLING
# Balances are held in integer minor units (pence, cents, paise). A wallet has
# to reconcile exactly, and repeated float arithmetic on a running balance
# drifts; the rest of the app uses floats because invoice totals are recomputed
# from their lines rather than accumulated.
# ===========================================================================

class DBWallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, unique=True, index=True)
    balance_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")
    low_balance_minor = Column(Integer, default=500)      # warn under this
    is_suspended = Column(Boolean, default=False)
    lifetime_topped_up_minor = Column(Integer, default=0)
    lifetime_spent_minor = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBApprovalChain(Base):
    """Tracks every approval step for invoices and bills going through the
    hierarchical approval workflow."""
    __tablename__ = "approval_chains"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    entity_type = Column(String, nullable=False, index=True)   # "invoice" or "bill"
    entity_id = Column(Integer, nullable=False, index=True)    # FK → invoices.id / bills.id
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)  # who created
    approver_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)  # who approves
    level = Column(String, default="")       # approver's level (L1-L8)
    step = Column(Integer, default=1)        # step number in chain
    status = Column(String, default="pending", index=True)  # pending / approved / rejected
    notes = Column(Text, default="")
    decided_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient")


class DBWalletTransaction(Base):
    """Append-only ledger. `balance_after_minor` is stored on every row so the
    running balance can be audited against the wallet at any point."""
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True, index=True)

    direction = Column(String, default="debit", index=True)   # credit | debit
    amount_minor = Column(Integer, default=0)
    balance_after_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")

    action_key = Column(String, default="", index=True)       # which billable action
    module = Column(String, default="", index=True)           # invoicing | hr | platform
    description = Column(String, default="")
    reference = Column(String, default="")                    # invoice number, payslip id...
    quantity = Column(Integer, default=1)

    performed_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)


class DBPricingRule(Base):
    """What each billable action costs. Set by the platform operator, not by
    tenants."""
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    action_key = Column(String, nullable=False, unique=True, index=True)
    label = Column(String, nullable=False)
    description = Column(String, default="")
    module = Column(String, default="platform", index=True)   # invoicing | hr | platform
    unit_price_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")
    free_allowance = Column(Integer, default=0)               # free units per calendar month
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0)
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBTopUpOrder(Base):
    """A payment attempt against a gateway. Kept even when it fails, so a
    disputed or duplicated payment can be traced."""
    __tablename__ = "topup_orders"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    provider = Column(String, default="", index=True)         # stripe | razorpay | paypal | manual
    amount_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")

    status = Column(String, default="created", index=True)    # created|pending|paid|failed|cancelled
    provider_order_id = Column(String, default="", index=True)
    provider_payment_id = Column(String, default="", index=True)
    checkout_url = Column(String, default="")
    failure_reason = Column(String, default="")

    credited = Column(Boolean, default=False)                 # guards double-crediting
    credited_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBBrandingTheme(Base):
    """How a business wants its invoices and quotes to look.

    A tenant can keep several - a standard theme, one for a customer who wants
    their PO number as a column, a plainer one for print. Exactly one is the
    default, which is what a new document uses.

    Every display decision lives here rather than in the PDF code, so changing
    a theme re-renders every document that uses it without touching a stored
    file. Nothing here affects what is owed; it is presentation only.
    """
    __tablename__ = "branding_themes"
    __table_args__ = (
        UniqueConstraint('client_id', 'name', name='uq_client_theme_name'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, default="Standard")
    is_default = Column(Boolean, default=False, index=True)

    # --- brand and styling ---
    logo_data = Column(Text, default="")            # data: URI, per theme
    logo_position = Column(String, default="right")  # left | center | right
    brand_color = Column(String, default="#4F46E5")
    font = Column(String, default="helvetica")       # a jsPDF core font

    # --- which columns the line-item table shows, and what they are called ---
    show_item = Column(Boolean, default=False)
    show_quantity = Column(Boolean, default=True)
    show_price = Column(Boolean, default=True)
    show_discount = Column(Boolean, default=False)
    show_tax = Column(Boolean, default=True)
    label_item = Column(String, default="Item")
    label_description = Column(String, default="Description")
    label_quantity = Column(String, default="Quantity")
    label_price = Column(String, default="Unit Price")
    label_discount = Column(String, default="Discount")
    label_tax = Column(String, default="Tax")
    label_amount = Column(String, default="Amount")

    # --- tax ---
    # combined | separate_rates | separate_components
    tax_breakdown = Column(String, default="separate_rates")
    exclude_zero_rates = Column(Boolean, default=False)

    # --- currency ---
    always_show_currency_code = Column(Boolean, default=False)
    show_conversion_rate = Column(Boolean, default=False)

    # --- the online invoice ---
    show_text_links = Column(Boolean, default=True)
    show_qr_code = Column(Boolean, default=True)

    # --- wording ---
    approved_invoice_title = Column(String, default="TAX INVOICE")
    draft_invoice_title = Column(String, default="DRAFT INVOICE")
    quote_title = Column(String, default="QUOTE")
    payment_terms = Column(Text, default="")
    footer_note = Column(Text, default="")

    # --- print ---
    address_position = Column(String, default="default")   # default | window_envelope
    show_page_numbers = Column(Boolean, default=True)

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# ============================================================================
# SUBCONTRACT WORK ORDERS
#
# The order a contractor issues *out* to a subcontractor, which is a different
# document from the priced scope sold *in* to a customer (DBWorkOrder above).
# This one carries a BOQ, the legal clauses the trade argues over, statutory
# deductions, and a signature chain - so it lives in its own tables rather
# than growing more nullable columns onto the sales side.
# ============================================================================

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


class DBSubcontractOrder(Base):
    """A work order issued to a subcontractor."""
    __tablename__ = "subcontract_orders"

    id = Column(Integer, primary_key=True, index=True)
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


class DBSubcontractTerm(Base):
    """A clause. Ordered, because these are read as a numbered schedule."""
    __tablename__ = "subcontract_terms"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), index=True)
    clause_category = Column(String, default="")
    clause_text = Column(Text, default="")
    display_order = Column(Integer, default=0)


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
