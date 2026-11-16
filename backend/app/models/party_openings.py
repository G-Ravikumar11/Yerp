"""What a party owed, or was owed, on the day the books here begin."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String

from app.db.session import Base


class DBPartyOpening(Base):
    """A client's, supplier's or contractor's balance on the day these books start (OB-0001): what they owed us, or we them,
    from before there was a bill here to show it - or what was paid ahead of one. It sits in the party's ledger as the first
    line, goes to the balance sheet with the rest of the ledger, and to Tally as an opening journal."""
    __tablename__ = "party_openings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    party_type = Column(String, nullable=False, index=True)       # client | supplier | contractor
    party_name = Column(String, nullable=False, index=True)
    # owed: the usual side - a client owes us, we owe a supplier or contractor. advance: the other side - a client paid us
    # ahead, we paid a supplier or contractor ahead.
    side = Column(String, nullable=False, default="owed")
    amount = Column(Float, nullable=False, default=0.0)           # always above nothing; the side says which way it runs
    as_on = Column(String, nullable=False, index=True)            # the day it stood at: YYYY-MM-DD
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    note = Column(String, default="")
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")
