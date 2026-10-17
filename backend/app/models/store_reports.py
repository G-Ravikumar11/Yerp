"""Store module - reports and integration tables. Owned by P5.

Migration: store_006_reports (this repo has no Alembic: create_all makes the tables, the name only labels the change).

store_consumption_norm: how much of an item one unit of a BOQ item should consume (with an allowance for wastage). It lets the
consumption report set what was issued against what the BOQ says it should have taken.
store_recovery_link: remembers which material-recovery row (subcontract billing) was made from which chargeable issue line, so that
syncing is repeatable and a cancelled or returned issue withdraws its recovery.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint

from app.db.session import Base
from app.models.store_core import FACTOR, PERCENT

REVISION = "store_006_reports"


class DBStoreConsumptionNorm(Base):
    __tablename__ = "store_consumption_norm"
    __table_args__ = (UniqueConstraint("boq_item_id", "item_id", name="uq_store_norm_boq_item"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    boq_item_id = Column(Integer, ForeignKey("boq_lines.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty_per_unit = Column(FACTOR, nullable=False)                 # base unit of the item per unit of the BOQ item
    wastage_pct = Column(PERCENT, default=0)
    updated_at = Column(DateTime, default=datetime.now)


class DBStoreRecoveryLink(Base):
    __tablename__ = "store_recovery_link"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    issue_line_id = Column(Integer, nullable=False, unique=True, index=True)      # the outward slice's issue line; not a foreign key, the slices stay independent
    recovery_id = Column(Integer, ForeignKey("material_recoveries.id"), nullable=False, index=True)
    synced_at = Column(DateTime, default=datetime.now)
