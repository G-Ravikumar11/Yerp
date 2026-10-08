"""Who has to approve what."""
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.session import Base


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
