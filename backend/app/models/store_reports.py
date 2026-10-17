"""Store module - reports tables: consumption norms, and the material recoveries decided against subcontractor bills.
Owned by P5. Migration store_006_reports (down revision store_001_core): new tables only, made by create_all.

Reports themselves are not stored; they are read from the stock ledger every time.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.db.session import Base
from app.models.store_core import FACTOR, PERCENT, RATE, VALUE

REVISION_REPORTS = "store_006_reports"
DOWN_REVISION_REPORTS = "store_001_core"


class DBStoreConsumptionNorm(Base):
    """How much of a material a unit of work should take: 425 kg of cement a cum of M25, 1050 kg of steel a MT of
    reinforcement work. Keyed by the work-item code - the BOQ line's item code, the client work order line's FG code
    and the subcontract item's code are the same code - and optionally pinned to one BOQ line."""
    __tablename__ = "store_consumption_norm"
    __table_args__ = (Index("ix_store_norm_code_item", "client_id", "work_item_code", "item_id"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    work_item_code = Column(String, nullable=False, index=True)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=True, index=True)
    description = Column(String, default="")                   # "RCC M25 in columns"
    work_uom = Column(String, default="")                      # the unit the work is measured in: cum, MT, sqm
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    coefficient = Column(FACTOR, nullable=False)               # base units of the item per unit of work
    wastage_pct = Column(PERCENT, nullable=False, default=0)   # permissible over the coefficient
    penal_rate = Column(RATE, nullable=True)                   # per base unit, for excess recovered from a subcontractor
    is_active = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DBStoreSubconRecovery(Base):
    """A material recovery decided against a subcontractor bill - for material issued to them (P3's recovery records)
    or for wastage beyond the norm. Recorded here; the bill's own deductions are typed by its owner, so the sub-bill
    posting logic is never touched."""
    __tablename__ = "store_subcon_recovery"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    sub_bill_id = Column(Integer, ForeignKey("sub_bills.id"), nullable=False, index=True)
    subcontractor_id = Column(Integer, ForeignKey("contractors.id"), nullable=True, index=True)
    kind = Column(String, nullable=False)                      # MATERIAL | EXCESS_WASTAGE
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=True)
    amount = Column(VALUE, nullable=False)
    note = Column(Text, default="")
    recorded_by = Column(Integer, nullable=True)
    recorded_by_name = Column(String, default="")
    recorded_at = Column(DateTime, default=datetime.now)
