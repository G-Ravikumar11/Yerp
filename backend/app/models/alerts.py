"""Notifications and the alert feed."""
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBNotification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(String, default="")
    type = Column(String, default="info")
    is_read = Column(Boolean, default=False)
    link = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAlert(Base):
    """Something announced - on the bell in the app, and by email or WhatsApp
    to whoever the company named for that kind of thing."""
    __tablename__ = "office_alerts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    kind = Column(String, default="", index=True)
    title = Column(String, default="")
    body = Column(Text, default="")
    view = Column(String, default="")            # the screen it opens
    ref_type = Column(String, default="")
    ref_id = Column(Integer, nullable=True)
    severity = Column(String, default="info")
    sent_to = Column(String, default="")          # emails and numbers it went out to
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)


class DBAlertRead(Base):
    """Who has seen it - the owner, or a member of staff by id."""
    __tablename__ = "office_alert_reads"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("office_alerts.id"), nullable=False, index=True)
    viewer = Column(String, default="owner", index=True)
    read_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
