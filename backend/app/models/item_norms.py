"""Material norms: what one unit of a BOQ work item uses up of each store material (1 cum of PCC M15: 4.4 bags of cement,
0.47 cum of sand ...), with the wastage allowed on top. Kept on the work item in the Item Master, so they serve every
project; the Item sheet fills a BOQ line's materials from them. And, on the Item sheet, which work item a BOQ line is
when its BOQ does not say. New tables, made by create_all at start-up."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint

from app.db.session import Base


class DBItemNorm(Base):
    """`qty_per_unit` is in the material's base unit, for one unit of the work item's own unit; `wastage_pct` is added on top."""
    __tablename__ = "item_material_norm"
    __table_args__ = (UniqueConstraint("work_item_id", "material_id", name="uq_item_material_norm"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    work_item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    line_no = Column(Integer, default=0)
    qty_per_unit = Column(Float, nullable=False, default=0.0)
    wastage_pct = Column(Float, nullable=False, default=0.0)
    remarks = Column(String, default="")
    updated_by_name = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.now)


class DBItemSheetWork(Base):
    """The work item a BOQ line of a project is, as said on its Item sheet (the BOQ line carries none, or the wrong one)."""
    __tablename__ = "store_item_sheet_work"
    __table_args__ = (UniqueConstraint("sheet_id", "boq_key", name="uq_store_item_sheet_work"),)

    id = Column(Integer, primary_key=True, index=True)
    sheet_id = Column(Integer, ForeignKey("store_item_sheet.id"), nullable=False, index=True)
    boq_key = Column(String, nullable=False)
    work_item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    set_by_name = Column(String, default="")
    set_at = Column(DateTime, default=datetime.now)
