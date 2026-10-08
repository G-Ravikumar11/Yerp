"""Contacts, leads, quotes and estimates."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


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
    pan = Column(String, default="")
    address = Column(String, default="")
    city = Column(String, default="")
    state = Column(String, default="")
    pincode = Column(String, default="")
    notes = Column(Text, default="")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="contacts")


# ESTIMATION
#
# The chain used to start at a signed work order. Half of a contracting
# business happens before that: a tender arrives, somebody builds up a rate
# for every item from material, labour, plant and overhead, adds a margin,
# and submits a price. Win it and that priced schedule IS the work order.
# Lose it and the rate build-ups are still worth keeping, because the next
# tender has the same items in it.
#
# An estimate is a BOQ with a cost side. The rate analysis is the part that
# makes it an estimate rather than a guess.
class DBEstimate(Base):
    __tablename__ = "estimates"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_estimate_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    number = Column(String, index=True)               # EST-0001
    title = Column(String, default="")
    customer_name = Column(String, default="")
    tender_reference = Column(String, default="")
    due_on = Column(String, default="")

    # DRAFT | SUBMITTED | WON | LOST | WITHDRAWN
    status = Column(String, default="DRAFT", index=True)

    # The margin the whole tender was priced on. Each item can override it.
    overhead_percent = Column(Float, default=0.0)
    profit_percent = Column(Float, default=0.0)

    cost_total = Column(Float, default=0.0)          # what it will cost us
    quoted_total = Column(Float, default=0.0)        # what we are asking for
    margin_amount = Column(Float, default=0.0)

    # Once won, the work order this became. Set once and never changed, so
    # the estimate and the order can always be laid side by side later.
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    decided_at = Column(String, default="")
    lost_reason = Column(String, default="")
    notes = Column(Text, default="")
    prepared_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBEstimateItem(Base):
    """One BOQ item on the tender, with what it costs and what we ask."""
    __tablename__ = "estimate_items"

    id = Column(Integer, primary_key=True, index=True)
    estimate_id = Column(Integer, ForeignKey("estimates.id"), index=True)
    item_no = Column(String, default="")             # 1.1, 2.3 - the tender's numbering
    fg_code = Column(String, default="")             # our code, once it has one
    description = Column(Text, default="")
    uom = Column(String, default="")
    quantity = Column(Float, default=0.0)

    # Built up from the analysis lines below, or typed if the estimator
    # already knows the number.
    cost_rate = Column(Float, default=0.0)
    overhead_percent = Column(Float, nullable=True)   # None: use the estimate's
    profit_percent = Column(Float, nullable=True)
    quoted_rate = Column(Float, default=0.0)
    cost_amount = Column(Float, default=0.0)
    quoted_amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


class DBRateAnalysis(Base):
    """What goes into one unit of one item.

    A cubic metre of M25 concrete is so much cement, so much sand, so many
    mason-hours and a share of a mixer. Written down per resource, so the
    rate is defensible when the client asks and reusable when the next
    tender has concrete in it.
    """
    __tablename__ = "rate_analyses"

    id = Column(Integer, primary_key=True, index=True)
    estimate_item_id = Column(Integer, ForeignKey("estimate_items.id"), index=True)
    # MATERIAL | LABOUR | PLANT | OTHER
    kind = Column(String, default="MATERIAL", index=True)
    item_code = Column(String, default="")           # RM code, when it is stock
    description = Column(String, default="")
    uom = Column(String, default="")
    # Per unit of the BOQ item: 0.35 cum sand per cum of concrete.
    quantity_per_unit = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    wastage_percent = Column(Float, default=0.0)
    amount_per_unit = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


# SALES: THE TENDER PIPELINE
#
# Before there is an estimate there is a tender notice, a site visit, a
# pre-bid meeting, a bid date and an earnest money deposit sitting with the
# client. Which tenders are live, what is due this week, which EMDs have not
# come back - that was a register in a notebook.
class DBLead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)            # TND-0001
    title = Column(String, default="")                         # "295 KLD STP, Vanya City"
    customer_name = Column(String, default="", index=True)
    contact_person = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    location = Column(String, default="")
    source = Column(String, default="")                        # Tender portal | Client enquiry | Referral | Repeat client
    tender_reference = Column(String, default="")
    estimated_value = Column(Float, default=0.0)
    site_visit_on = Column(String, default="")
    prebid_on = Column(String, default="")
    bid_due_on = Column(String, default="", index=True)
    emd_amount = Column(Float, default=0.0)
    emd_mode = Column(String, default="")                      # DD | BG | Online | FDR
    emd_reference = Column(String, default="")
    emd_paid_on = Column(String, default="")
    emd_returned_on = Column(String, default="")
    status = Column(String, default="NEW", index=True)          # NEW | QUALIFIED | ESTIMATING | SUBMITTED | WON | LOST | DROPPED
    lost_reason = Column(String, default="")
    winning_bidder = Column(String, default="")
    winning_price = Column(Float, default=0.0)
    our_price = Column(Float, default=0.0)
    estimate_id = Column(Integer, ForeignKey("estimates.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    owner_name = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBLeadActivity(Base):
    """A call, a visit, a meeting, a follow-up - dated, so the pipeline has a
    history and the next thing to do is written down."""
    __tablename__ = "lead_activities"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    kind = Column(String, default="Note")                      # Call | Visit | Meeting | Note | Status
    note = Column(Text, default="")
    next_action = Column(String, default="")
    next_on = Column(String, default="", index=True)
    by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
