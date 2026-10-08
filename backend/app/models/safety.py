"""Incidents, toolbox talks and work permits."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBSafetyIncident(Base):
    """Something that happened, or nearly did - a near miss is the cheapest
    lesson a site gets."""
    __tablename__ = "safety_incidents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # INC-0001
    happened_on = Column(String, default="", index=True)        # date
    happened_at = Column(String, default="")                     # time
    kind = Column(String, default="Near miss")
    location = Column(String, default="")
    description = Column(Text, default="")
    injured_name = Column(String, default="")
    injury = Column(String, default="")
    treatment = Column(String, default="")
    lost_days = Column(Float, default=0.0)
    immediate_action = Column(Text, default="")
    root_cause = Column(Text, default="")
    corrective_action = Column(Text, default="")
    reported_by = Column(String, default="")
    status = Column(String, default="OPEN", index=True)         # OPEN | CLOSED
    closed_on = Column(String, default="")
    closure_note = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBToolboxTalk(Base):
    __tablename__ = "toolbox_talks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    held_on = Column(String, default="", index=True)
    topic = Column(String, default="")
    conducted_by = Column(String, default="")
    attendees = Column(Integer, default=0)
    attendee_names = Column(Text, default="")
    minutes = Column(Integer, default=15)
    notes = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBWorkPermit(Base):
    """A permit to work: what is allowed, where, until when, on which
    precautions - and closed when the work stops."""
    __tablename__ = "work_permits"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # PTW-0001
    kind = Column(String, default="Work at height")
    location = Column(String, default="")
    description = Column(Text, default="")
    valid_from = Column(String, default="")                      # "2026-09-26 08:00"
    valid_to = Column(String, default="", index=True)
    issued_by = Column(String, default="")
    receiver = Column(String, default="")                        # the person doing the work
    precautions = Column(Text, default="[]")                     # [{item, done}]
    status = Column(String, default="ACTIVE", index=True)        # ACTIVE | CLOSED | CANCELLED
    closed_at = Column(String, default="")
    closed_by = Column(String, default="")
    closure_note = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
