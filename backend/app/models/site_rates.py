"""What each item sells for at each site: the rate is finalised per site, never on the item master."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBSiteItemRate(Base):
    """One item's rate at one site (a site is a job). The item is shared; the price is not.

    A project has one BOQ with revisions, so (client, job, item) is the whole key: a rate belongs to the site and every
    revision of its BOQ reads the same one.
    """
    __tablename__ = "site_item_rates"
    __table_args__ = (UniqueConstraint("client_id", "job_id", "item_id", name="uq_site_item_rate"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    item_code = Column(String, default="")                     # as it was when the rate was set
    site_rate = Column(Float, nullable=True)                   # blank until one is entered
    status = Column(String, default="Draft", index=True)       # Draft | Finalized (no rate at all reads as Pending)
    # The master's default selling rate when this was finalised. If the master moves afterwards the row reads
    # "Changed" - flagged, never overwritten.
    default_rate_snapshot = Column(Float, nullable=True)
    effective_date = Column(String, default="")
    remarks = Column(Text, default="")
    # Bumped on every change, so two people saving the same row cannot silently overwrite one another.
    version = Column(Integer, default=1)
    created_by_name = Column(String, default="")
    updated_by_name = Column(String, default="")
    finalized_by_name = Column(String, default="")
    finalized_at = Column(String, default="")
    created_at = Column(String, default=_now)
    updated_at = Column(String, default=_now)


class DBRateAuditLog(Base):
    """Every change to a site rate, kept for good. Rows are only ever added: nothing here updates or deletes one."""
    __tablename__ = "rate_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("erp_items.id"), nullable=False, index=True)
    item_code = Column(String, default="")
    previous_rate = Column(Float, nullable=True)
    new_rate = Column(Float, nullable=True)
    previous_status = Column(String, default="Pending")
    new_status = Column(String, default="")
    action = Column(String, default="")                        # created | edited | finalized | reopened | applied
    changed_by_name = Column(String, default="")
    changed_at = Column(String, default=_now, index=True)
    remarks = Column(Text, default="")                         # the reason for the change
