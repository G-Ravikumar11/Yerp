"""Items, serial codes, bills of materials and stock."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


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
    # Below this, the store is running out. Zero means nobody set one, which
    # is not the same as "never reorder" - so it simply never warns.
    reorder_level = Column(Float, default=0.0)
    # What this code was last sold or bought at. Prices are not fixed on a
    # contract, so this is an offer rather than a rule: the next order opens
    # with it filled in and whoever is pricing can change it.
    last_rate = Column(Float, default=0.0)
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


# STOCK
#
# The item master said what may be bought and the goods receipt said what
# arrived, but nothing said what is actually in the store, what went out to
# site, or what is left. On a contract that is the difference between
# material control and hoping.
#
# Every movement is a row with a signed quantity and the balance is their
# sum - the same shape as the measurement book, and for the same reason: a
# ledger that can be edited is not a ledger. A miscount is corrected by
# posting the correction, so the store's history survives the fix.
class DBStockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    item_code = Column(String, nullable=False, index=True)
    item_name = Column(String, default="")
    uom = Column(String, default="")
    store = Column(String, default="Main store", index=True)

    # RECEIPT | ISSUE | RETURN | ADJUSTMENT
    kind = Column(String, nullable=False, index=True)
    # Signed: what this row does to the balance. An issue is negative, so the
    # balance is a sum and never a subtraction somebody has to remember.
    quantity = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    value = Column(Float, default=0.0)

    moved_on = Column(String, default="", index=True)
    # Where it came from or went to, so a movement can always be traced back
    # to the document that caused it.
    source_type = Column(String, default="")      # goods_receipt | stock_issue | manual
    source_id = Column(Integer, nullable=True, index=True)
    source_ref = Column(String, default="")
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    remarks = Column(String, default="")
    recorded_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    recorded_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBStockIssue(Base):
    """Material going out of the store to a site.

    Issued against a work order, because material that cannot be attributed to
    the work it was bought for is material nobody can cost.
    """
    __tablename__ = "stock_issues"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_issue_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)

    number = Column(String, index=True)               # ISS-0001
    issued_on = Column(String, default="")
    store = Column(String, default="Main store")
    # DRAFT | POSTED | CANCELLED
    status = Column(String, default="DRAFT", index=True)

    issued_to = Column(String, default="")            # the ganger who took it
    purpose = Column(String, default="")
    total_value = Column(Float, default=0.0)

    issued_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    issued_by_name = Column(String, default="")
    remarks = Column(Text, default="")
    posted_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBStockIssueLine(Base):
    __tablename__ = "stock_issue_lines"

    id = Column(Integer, primary_key=True, index=True)
    stock_issue_id = Column(Integer, ForeignKey("stock_issues.id"), index=True)
    item_code = Column(String, default="", index=True)
    item_name = Column(String, default="")
    uom = Column(String, default="")
    quantity = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


class DBStockBalance(Base):
    """One row per item: what is in the store right now.

    The ledger is the truth and this is its running total, kept up to date by
    the one function that writes movements. Reading the stock screen used to
    mean replaying the whole year's ledger in Python to arrive at today's
    balance - fine at a hundred movements, a second at ten thousand, and
    every dashboard load did it. A perpetual balance is what every stock
    system keeps for exactly this reason. If it is ever doubted, it can be
    rebuilt from the ledger in one call, and the two must agree.
    """
    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint('client_id', 'item_code', name='uq_stock_balance_item'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    item_code = Column(String, nullable=False, index=True)
    item_name = Column(String, default="")
    uom = Column(String, default="")
    on_hand = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)            # weighted average of what is held
    value = Column(Float, default=0.0)
    received = Column(Float, default=0.0)        # lifetime in
    issued = Column(Float, default=0.0)          # lifetime out
    movements = Column(Integer, default=0)
    updated_at = Column(String, default="")
