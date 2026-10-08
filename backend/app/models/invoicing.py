"""Invoices, bills, payments, tax and e-invoicing."""
from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


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
    po_line_id = Column(Integer, ForeignKey("purchase_order_line_items.id"),
                        nullable=True, index=True)
    description = Column(String, default="")
    qty = Column(Float, default=1.0)
    price = Column(Float, default=0.0)
    tax_rate = Column(String, default="20%")

    bill = relationship("DBBill", back_populates="line_items")


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


class DBEwayBill(Base):
    """An e-way bill for goods on the road: a store transfer between sites,
    plant moved to a site, material returned to a supplier. Laid out here,
    generated on the NIC portal from the file this app writes, and its number
    and validity recorded back against the movement it covers."""
    __tablename__ = "eway_bills"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)            # EWB-0001, our own reference
    source_type = Column(String, default="manual")             # transfer | manual
    source_ref = Column(String, default="", index=True)        # TRF-0001
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    supply_type = Column(String, default="O")                  # O outward | I inward
    sub_type = Column(String, default="5")                     # NIC sub-supply code; 5 = own use
    sub_type_desc = Column(String, default="")
    doc_type = Column(String, default="CHL")                   # CHL challan | INV | BIL | OTH
    doc_no = Column(String, default="")
    doc_date = Column(String, default="")
    from_name = Column(String, default="")
    from_gstin = Column(String, default="")
    from_address = Column(Text, default="")
    from_place = Column(String, default="")
    from_pincode = Column(String, default="")
    from_state = Column(String, default="")                    # GST state code, "36"
    to_name = Column(String, default="")
    to_gstin = Column(String, default="")
    to_address = Column(Text, default="")
    to_place = Column(String, default="")
    to_pincode = Column(String, default="")
    to_state = Column(String, default="")
    distance_km = Column(Integer, default=0)                   # 0 = let the portal work it out
    trans_mode = Column(String, default="1")                   # 1 road, 2 rail, 3 air, 4 ship
    vehicle_no = Column(String, default="")
    vehicle_type = Column(String, default="R")                 # R regular, O over-dimensional
    transporter_id = Column(String, default="")
    transporter_name = Column(String, default="")
    trans_doc_no = Column(String, default="")
    trans_doc_date = Column(String, default="")
    taxable_value = Column(Float, default=0.0)
    cgst = Column(Float, default=0.0)
    sgst = Column(Float, default=0.0)
    igst = Column(Float, default=0.0)
    total_value = Column(Float, default=0.0)
    status = Column(String, default="DRAFT", index=True)       # DRAFT | GENERATED | CANCELLED
    ewb_no = Column(String, default="", index=True)
    ewb_date = Column(String, default="")
    valid_upto = Column(String, default="")
    cancel_reason = Column(String, default="")
    vehicle_history = Column(Text, default="")                 # Part B changes, one per line
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBEwayBillLine(Base):
    __tablename__ = "eway_bill_lines"

    id = Column(Integer, primary_key=True, index=True)
    eway_bill_id = Column(Integer, ForeignKey("eway_bills.id"), nullable=False, index=True)
    item_code = Column(String, default="")
    product_name = Column(String, default="")
    hsn = Column(String, default="")
    qty = Column(Float, default=0.0)
    unit = Column(String, default="")
    taxable = Column(Float, default=0.0)
    tax_rate = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


class DBTaxBlock(Base):
    """A block of assets for income-tax depreciation, with its rate and the
    written-down value it opened a year on."""
    __tablename__ = "tax_blocks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, default="")
    rate = Column(Float, default=15.0)
    opening_fy = Column(String, default="")
    opening_wdv = Column(Float, default=0.0)


# E-INVOICE REGISTRATIONS
#
# What the Invoice Registration Portal gave back for a bill: the IRN, the
# acknowledgement, and the signed QR the printed invoice has to carry.
class DBEinvoiceIrn(Base):
    __tablename__ = "einvoice_irns"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    doc_type = Column(String, default="ra_bill", index=True)     # ra_bill | retention_release
    doc_id = Column(Integer, nullable=False, index=True)
    doc_number = Column(String, default="")
    irn = Column(String, default="", index=True)
    ack_no = Column(String, default="")
    ack_date = Column(String, default="")
    signed_qr = Column(Text, default="")
    signed_invoice = Column(Text, default="")
    qr_data = Column(Text, default="")                           # what the QR says, decoded
    ewb_no = Column(String, default="")
    status = Column(String, default="ACTIVE", index=True)        # ACTIVE | CANCELLED
    cancel_reason = Column(String, default="")
    cancelled_at = Column(String, default="")
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
