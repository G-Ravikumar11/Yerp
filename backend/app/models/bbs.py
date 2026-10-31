"""The Bar Bending Schedule: one row for each bar mark, and every earlier version of it."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBBbsEntry(Base):
    """One bar mark on one member. Length and weight are worked out from these figures, never stored rounded. The cutting
    length is stored: rules changed later must not move a schedule already issued."""
    __tablename__ = "bbs_entries"
    __table_args__ = (UniqueConstraint("client_id", "entry_key", name="uq_bbs_entry"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    entry_key = Column(String, nullable=False)              # project|block|floor|member|mark, cleaned
    block = Column(String, default="", index=True)
    floor = Column(String, default="", index=True)
    element = Column(String, default="", index=True)        # Beam | Column | Slab | Footing | ...
    member_ref = Column(String, default="")
    bar_mark = Column(String, default="", index=True)
    diameter_mm = Column(Float, default=0.0, index=True)
    grade = Column(String, default="")
    shape = Column(String, default="Straight")
    dims = Column(Text, default="{}")                       # {"A": 3000, "B": 300} in mm
    num_bars = Column(Integer, default=0)
    cutting_length_mm = Column(Float, default=0.0)
    remarks = Column(Text, default="")
    status = Column(String, default="Draft", index=True)    # Draft | Approved
    revision = Column(Integer, default=0)
    approved_by = Column(String, default="")
    approved_at = Column(String, default="")
    created_by = Column(String, default="")
    created_at = Column(String, default=_now)


class DBBbsRevision(Base):
    """An entry as it stood before a change, and why it changed."""
    __tablename__ = "bbs_revisions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("bbs_entries.id"), nullable=False, index=True)
    revision = Column(Integer, default=0)
    snapshot = Column(Text, default="{}")
    reason = Column(String, default="")
    changed_by = Column(String, default="")
    changed_at = Column(String, default=_now)
