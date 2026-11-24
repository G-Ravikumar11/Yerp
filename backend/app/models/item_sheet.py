"""Store - the project's Item sheet: the materials a project will need, each under a group code of its BOQ (RCC, PCC,
Masonry ...), with the item's HSN and unit from the item master and the quantity. Made in the app or uploaded from the
Excel template; it is used only once the Master approves it. New tables, made by create_all at start-up."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base

SHEET_DRAFT, SHEET_SUBMITTED, SHEET_APPROVED = "DRAFT", "SUBMITTED", "APPROVED"


class DBItemSheet(Base):
    """One per project. `approved_lines` is the copy the Master last approved, as JSON [{group_code, item_id, qty}]:
    that is what the store goes by, so a sheet being changed again leaves the approved one in force until it is approved."""
    __tablename__ = "store_item_sheet"
    __table_args__ = (UniqueConstraint("client_id", "job_id", name="uq_store_item_sheet_job"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default=SHEET_DRAFT)          # DRAFT | SUBMITTED | APPROVED
    approved_lines = Column(Text, nullable=True)                          # None until first approved
    approved_by_name = Column(String, default="")
    approved_at = Column(DateTime, nullable=True)
    submitted_by_name = Column(String, default="")
    submitted_at = Column(DateTime, nullable=True)
    returned_note = Column(String, default="")                            # why the Master sent it back
    updated_by_name = Column(String, default="")
    updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class DBItemSheetLine(Base):
    """A material on the sheet under one BOQ group code. The same item may stand under several group codes."""
    __tablename__ = "store_item_sheet_line"
    __table_args__ = (UniqueConstraint("sheet_id", "group_code", "item_id", name="uq_store_item_sheet_line"),)

    id = Column(Integer, primary_key=True, index=True)
    sheet_id = Column(Integer, ForeignKey("store_item_sheet.id"), nullable=False, index=True)
    line_no = Column(Integer, default=0)
    group_code = Column(String, nullable=False, default="")
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    qty = Column(Float, nullable=False, default=0.0)                      # in the item's base unit
    remarks = Column(String, default="")
