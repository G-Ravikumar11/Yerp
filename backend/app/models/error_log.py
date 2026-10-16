"""The error log: every error the app answered with, kept so the Master can see it in Settings > Error log."""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Text

from app.db.session import Base


class DBErrorLog(Base):
    """One error: when, which code and ref, where in the app, who, and - for a fault - what went wrong underneath.
    A screen that crashed in the browser reports itself here too (code YE-APP)."""
    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=True, index=True)       # the company, when known
    at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)
    code = Column(String, default="", index=True)                # YE-AUTH-01, YE-SRV-01 ...
    ref = Column(String, default="", index=True)                 # 7F3A9C21
    status = Column(Integer, default=0)                          # the HTTP status; 0 for a screen fault
    method = Column(String, default="")
    path = Column(String, default="")
    detail = Column(Text, default="")                            # the message the person saw
    who = Column(String, default="")                             # owner | member:5 | employee:7 | an email tried at sign-in
    trace = Column(Text, default="")                             # the traceback of a fault (never sent to the browser but here)
