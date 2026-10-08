"""Purchase orders, goods received, quotations and suppliers."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


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
    # Named so the line can be received off a lorry and counted into stock.
    item_code = Column(String, default="")
    uom = Column(String, default="")
    qty = Column(Float, default=1.0)
    price = Column(Float, default=0.0)
    tax_rate = Column(String, default="20%")

    order = relationship("DBPurchaseOrder", back_populates="line_items")


# GOODS RECEIPT
#
# A purchase order says what was agreed. A bill says what is being charged.
# Neither says what actually arrived at the gate, and without that third
# number a site pays for forty tonnes of steel and receives thirty-eight.
# The receipt note is the record that closes it.
class DBGoodsReceipt(Base):
    """One delivery, against one order.

    A single order is delivered many times over weeks, so a receipt is never
    the whole order; it is what came off one lorry on one day, with the
    supplier's own challan number so the two paper trails can be lined up.
    """
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_grn_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"),
                               nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    number = Column(String, index=True)          # GRN-0001
    supplier_name = Column(String, default="")
    received_on = Column(String, default="")

    # The supplier's own paperwork. When a bill is disputed three months later
    # this is the number both sides can look up.
    challan_number = Column(String, default="")
    invoice_number = Column(String, default="")
    vehicle_number = Column(String, default="")

    # DRAFT | POSTED | CANCELLED
    # A draft is somebody still counting. Posting is the assertion that this
    # is what arrived, and it is what a bill is allowed to be matched against.
    status = Column(String, default="DRAFT", index=True)

    received_value = Column(Float, default=0.0)
    accepted_value = Column(Float, default=0.0)
    rejected_value = Column(Float, default=0.0)

    received_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    received_by_name = Column(String, default="")
    inspected_by = Column(String, default="")
    store_location = Column(String, default="")
    remarks = Column(Text, default="")

    posted_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBGoodsReceiptLine(Base):
    """What arrived on one line, and how much of it was fit to use.

    Received and accepted are separate numbers on purpose. Material that turns
    up broken has still arrived - it has to be recorded, returned and credited,
    and a store that can only record good stock quietly loses the argument.
    """
    __tablename__ = "goods_receipt_lines"

    id = Column(Integer, primary_key=True, index=True)
    goods_receipt_id = Column(Integer, ForeignKey("goods_receipts.id"), index=True)
    po_line_id = Column(Integer, ForeignKey("purchase_order_line_items.id"),
                        nullable=True, index=True)
    item_code = Column(String, default="")
    description = Column(String, default="")
    uom = Column(String, default="")

    ordered_qty = Column(Float, default=0.0)
    previously_received = Column(Float, default=0.0)
    received_qty = Column(Float, default=0.0)
    accepted_qty = Column(Float, default=0.0)
    rejected_qty = Column(Float, default=0.0)
    rejection_reason = Column(String, default="")

    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


# FINANCE: PARTIES AND MONEY
#
# Every rupee that moves, in either direction, against whatever it settles.
# Bills said "paid" or "not paid" and nothing in between, so a part-payment
# lived in a notebook and a party's statement of account lived in Tally. This
# is the ledger that makes both unnecessary.
class DBSupplier(Base):
    """Somebody we buy material from. Kept apart from subcontractors: what is
    bought from them is counted off a lorry, not measured in a book."""
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    code = Column(String, default="", index=True)
    name = Column(String, default="", index=True)
    contact_person = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    gstin = Column(String, default="")
    pan = Column(String, default="")
    state_code = Column(String, default="")
    address = Column(Text, default="")
    bank_name = Column(String, default="")
    bank_account = Column(String, default="")
    bank_ifsc = Column(String, default="")
    payment_days = Column(Integer, default=30)
    supplies = Column(String, default="")          # "Cement, steel" - what they are used for
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# PURCHASE: ENQUIRIES TO SUPPLIERS AND THE COMPARATIVE STATEMENT
#
# Before an order there is a question put to three or four suppliers, their
# answers, and a sheet that lays them side by side so the cheapest is plain
# and the choice of anybody else is explained. That sheet is what an auditor
# asks for, and it was being kept in a spreadsheet.
class DBRfq(Base):
    __tablename__ = "rfqs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)       # RFQ-0001
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    title = Column(String, default="")
    needed_by = Column(String, default="")
    status = Column(String, default="OPEN", index=True)    # OPEN | AWARDED | CANCELLED
    notes = Column(Text, default="")
    award_reason = Column(Text, default="")
    created_by_name = Column(String, default="")
    awarded_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBRfqLine(Base):
    __tablename__ = "rfq_lines"

    id = Column(Integer, primary_key=True, index=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=False, index=True)
    item_code = Column(String, default="")
    description = Column(String, default="")
    uom = Column(String, default="")
    qty = Column(Float, default=0.0)
    awarded_supplier = Column(String, default="")
    awarded_rate = Column(Float, default=0.0)
    po_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    display_order = Column(Integer, default=0)


class DBRfqQuote(Base):
    """One supplier's answer to one enquiry."""
    __tablename__ = "rfq_quotes"

    id = Column(Integer, primary_key=True, index=True)
    rfq_id = Column(Integer, ForeignKey("rfqs.id"), nullable=False, index=True)
    supplier_name = Column(String, default="")
    quote_ref = Column(String, default="")
    quote_date = Column(String, default="")
    delivery_days = Column(Integer, default=0)
    payment_terms = Column(String, default="")
    freight = Column(Float, default=0.0)                   # lump sum to site
    valid_until = Column(String, default="")
    notes = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBRfqQuoteLine(Base):
    __tablename__ = "rfq_quote_lines"

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(Integer, ForeignKey("rfq_quotes.id"), nullable=False, index=True)
    rfq_line_id = Column(Integer, ForeignKey("rfq_lines.id"), nullable=False, index=True)
    rate = Column(Float, default=0.0)
    tax_percent = Column(Float, default=18.0)
    remarks = Column(String, default="")
