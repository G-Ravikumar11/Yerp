"""Bills of quantities and their variations."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


class DBBoq(Base):
    """The client's bill of quantities for one project: the master every order and bill hangs off.

    One per project. It has revisions - R0 tender, R1 award, R2 after variations - and the lines belong to a
    revision, so what the BOQ said when an order was placed is never overwritten by what it says now.
    """
    __tablename__ = "boqs"
    __table_args__ = (UniqueConstraint("client_id", "job_id", name="uq_client_job_boq"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, index=True)                       # BOQ-0001
    title = Column(String, default="")
    current_rev = Column(Integer, default=0)
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBBoqRevision(Base):
    __tablename__ = "boq_revisions"
    __table_args__ = (UniqueConstraint("boq_id", "rev_no", name="uq_boq_revision"),)

    id = Column(Integer, primary_key=True, index=True)
    boq_id = Column(Integer, ForeignKey("boqs.id"), nullable=False, index=True)
    rev_no = Column(Integer, default=0)
    label = Column(String, default="")                        # "R1 - Award"
    note = Column(Text, default="")
    status = Column(String, default="OPEN")                   # OPEN (being edited) | ISSUED (locked)
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    issued_at = Column(String, default="")


class DBBoqLine(Base):
    """A line of a BOQ revision: a section heading, a priced item, a priced sub-item, or a note."""
    __tablename__ = "boq_lines"

    id = Column(Integer, primary_key=True, index=True)
    boq_id = Column(Integer, ForeignKey("boqs.id"), nullable=False, index=True)
    revision_id = Column(Integer, ForeignKey("boq_revisions.id"), nullable=False, index=True)
    # Stays the same on a line through every revision, so a change can be followed and orders can point at it.
    key = Column(String, nullable=False, index=True)
    kind = Column(String, default="item")                     # section | item | sub | note
    # The group the line belongs to (PCC, RCC, Steel ...): picked from a list or typed, and kept as the sheet has it.
    group_code = Column(String, default="", index=True)
    description = Column(Text, default="")
    uom = Column(String, default="")
    quantity = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    item_code = Column(String, default="", index=True)        # ours, from the item master
    # The master item itself, kept beside the code (which stays what orders, contractors, measurements and bills use).
    # Stamped from the code whenever lines are saved, so it never disagrees with it.
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=True, index=True)
    remarks = Column(Text, default="")
    # The grade or material the item is in ("M40", "Fe550/550D", "Ply wood"), kept apart from the description so a
    # sheet can be read, filtered and totalled by it.
    material = Column(String, default="")
    # Rate agreed, quantity not yet known ("R/o" on the client's sheet): it carries a rate and no amount, and
    # stays out of every total until a quantity is put on it.
    rate_only = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)


class DBBoqVariation(Base):
    """A change to the BOQ the client agrees: quantities that ran past it, and extra items it never had.

    It is priced line by line, goes up an approval route, and when it is approved the BOQ moves to its next
    revision with the changes in it (and the client's work order is raised to match).
    """
    __tablename__ = "boq_variations"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_client_boq_variation"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    boq_id = Column(Integer, ForeignKey("boqs.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    number = Column(String, index=True)                       # BOQ-0001/BV-01
    sequence = Column(Integer, default=1)
    status = Column(String, default="DRAFT", index=True)      # DRAFT | SUBMITTED | APPROVED | CANCELLED
    reason = Column(Text, default="")
    value = Column(Float, default=0.0)                        # what it adds to (or takes from) the BOQ
    basis_rev = Column(Integer, default=0)                    # the revision it was drawn against
    applied_rev = Column(Integer, nullable=True)              # the revision it created, once approved
    raised_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    raised_by_name = Column(String, default="")
    approved_by_name = Column(String, default="")
    approved_at = Column(String, default="")
    rejection_reason = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBBoqVariationLine(Base):
    __tablename__ = "boq_variation_lines"

    id = Column(Integer, primary_key=True, index=True)
    variation_id = Column(Integer, ForeignKey("boq_variations.id"), nullable=False, index=True)
    kind = Column(String, default="quantity")                 # quantity (an existing line) | extra (a new item)
    boq_key = Column(String, default="", index=True)          # quantity: the BOQ line changed
    section_key = Column(String, default="")                  # extra: the section it goes under
    description = Column(Text, default="")
    uom = Column(String, default="")
    old_qty = Column(Float, default=0.0)
    change_qty = Column(Float, default=0.0)                   # added (or taken away, if negative)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    remarks = Column(Text, default="")
    display_order = Column(Integer, default=0)
