"""Document control: what went to whom and what came back - transmittals, RFIs and submittals, each with a due date."""
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBDocControl(Base):
    """One transmittal (drawings and papers sent to a party, to be acknowledged), RFI (a question that needs an answer)
    or submittal (material or a shop drawing put up for approval). Numbered in its own series per kind."""
    __tablename__ = "doc_control"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    kind = Column(String, nullable=False, index=True)              # TRANSMITTAL | RFI | SUBMITTAL
    number = Column(String, default="", index=True)                # TR-0001, RFI-0001, SUB-0001
    subject = Column(String, default="")
    to_party = Column(String, default="")                          # the consultant, the client, a subcontractor
    to_email = Column(String, default="")
    details = Column(Text, default="")                             # the question, what is submitted, the cover note
    purpose = Column(String, default="")                           # For approval | For information | For construction ...
    revision = Column(String, default="")                          # a submittal's revision
    due_date = Column(String, default="", index=True)
    status = Column(String, default="OPEN", index=True)            # OPEN | ACKNOWLEDGED | ANSWERED | APPROVED | APPROVED_AS_NOTED | REJECTED | CLOSED | CANCELLED
    response = Column(Text, default="")
    responded_on = Column(String, default="")
    responded_by = Column(String, default="")                      # who recorded the reply
    created_by_id = Column(Integer, nullable=True)
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    closed_at = Column(String, default="")
    reminded_on = Column(String, default="")
    reminders = Column(Integer, default=0)
    overdue_told = Column(Integer, default=0)                      # the raiser was told it went overdue


class DBDocControlItem(Base):
    """What a transmittal sent: a drawing at its revision, or a paper described in words."""
    __tablename__ = "doc_control_items"

    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(Integer, ForeignKey("doc_control.id"), nullable=False, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=True)
    revision = Column(String, default="")
    description = Column(String, default="")
