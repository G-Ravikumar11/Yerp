"""The Material Issue Voucher: the store's paper slip for material given out to a project, kept as it is on paper."""
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBMaterialVoucher(Base):
    """One voucher, field for field as on the printed form: Sl. No., date, project, who indented it, who issued it and
    for what, then each line - item, unit, quantity issued, quantity returned, remarks (lines are JSON). It is a
    record of the slip; it does not move stock (Stock & Issues does that)."""
    __tablename__ = "material_vouchers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(Integer, default=0, index=True)           # Sl. No., in sequence for the company
    voucher_on = Column(String, default="", index=True)       # Date
    indented_by = Column(String, default="")                  # Material Indented By
    issued_by = Column(String, default="")                    # Issued By
    issued_for = Column(String, default="")                   # Issued For
    lines = Column(Text, default="[]")                        # [{description, uom, issued_qty, returned_qty, remarks}]
    recorded_by = Column(String, default="")
    removed = Column(Integer, default=0, index=True)          # taken off the register; its Sl. No. is never reused
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
