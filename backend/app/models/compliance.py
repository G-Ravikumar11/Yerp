"""What makes a subcontractor safe to pay: documents that expire, charges against them, and how they performed."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBComplianceDocument(Base):
    """A licence, registration or policy a contractor must hold, with the date it runs out."""
    __tablename__ = "compliance_documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=False, index=True)
    kind = Column(String, default="", index=True)          # labour_licence | pf | esi | insurance | bocw | other
    number = Column(String, default="")
    valid_from = Column(String, default="")
    valid_to = Column(String, default="", index=True)
    note = Column(String, default="")
    file_id = Column(Integer, nullable=True)
    recorded_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBBackCharge(Base):
    """Money charged back to a contractor (wastage beyond allowance, damage, clean-up, a safety penalty).
    OPEN until it is taken off one of their bills; then APPLIED, pointing at that bill."""
    __tablename__ = "back_charges"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("subcontract_orders.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    number = Column(String, default="", index=True)
    kind = Column(String, default="Other")                 # Wastage | Damage | Clean-up | Safety | Other
    reason = Column(Text, default="")
    amount = Column(Float, default=0.0)
    status = Column(String, default="OPEN", index=True)    # OPEN | APPLIED | CANCELLED
    applied_bill_id = Column(Integer, ForeignKey("sub_bills.id"), nullable=True, index=True)
    raised_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    applied_at = Column(String, default="")


class DBContractorRating(Base):
    """A score for the contractor's work on one certified bill, each 1 (poor) to 5 (excellent)."""
    __tablename__ = "contractor_ratings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    contractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=False, index=True)
    bill_id = Column(Integer, ForeignKey("sub_bills.id"), nullable=True, index=True)
    quality = Column(Integer, default=3)
    speed = Column(Integer, default=3)
    safety = Column(Integer, default=3)
    discipline = Column(Integer, default=3)
    note = Column(String, default="")
    rated_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
