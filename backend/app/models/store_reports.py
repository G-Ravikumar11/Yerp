"""Store module - reports tables: the material norms that say what a BOQ item should consume (so reports can set theoretical use against
actual issues) and the report filters a person has saved. Owned by P5.

Reports themselves read the stock ledger and take nothing from here but the norms; nothing in this file moves stock.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.db.session import Base
from app.models.store_core import FACTOR, PERCENT


class DBStoreMaterialNorm(Base):
    """How much of an item one unit of a BOQ item consumes: qty_per_unit of the item's BASE unit per 1 unit of the BOQ item's quantity,
    plus an allowance for wastage. Theoretical requirement = BOQ quantity x qty_per_unit x (1 + wastage_pct / 100)."""
    __tablename__ = "store_material_norm"
    __table_args__ = (UniqueConstraint("boq_item_id", "item_id", name="uq_store_norm_boq_item"), Index("ix_store_norm_client", "client_id"))

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty_per_unit = Column(FACTOR, nullable=False, default=0)
    wastage_pct = Column(PERCENT, default=0)
    notes = Column(String, default="")
    updated_by_name = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.now)


class DBStoreSavedReport(Base):
    """A report with its filters, kept under a name so it can be run again."""
    __tablename__ = "store_saved_report"
    __table_args__ = (UniqueConstraint("client_id", "name", name="uq_store_saved_report_name"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    report = Column(String, nullable=False)                  # valuation | movement | consumption | norm-variance | slow-moving | reorder
    params = Column(Text, default="{}")                      # the filters, as JSON
    created_by_name = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
