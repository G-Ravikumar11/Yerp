"""Punches read from the office's biometric attendance system (eSSL eTimeTrackLite), and the machines they came from."""
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from app.db.session import Base


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DBBiometricDevice(Base):
    """A biometric machine, as the attendance system names it. Put on a site, its punches are that site's attendance."""
    __tablename__ = "biometric_devices"
    __table_args__ = (UniqueConstraint("client_id", "device_code", name="uq_biometric_device"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    device_code = Column(String, nullable=False)                 # the machine's id in the attendance system
    name = Column(String, default="")
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)   # the site it stands at; none for the office
    last_punch_at = Column(String, default="")
    created_at = Column(String, default=_now)


class DBBiometricPunch(Base):
    """One punch on a machine. Kept as it came, matched to an employee when their biometric number is known - one that
    is not waits here and is applied the day the number is filled in. The same punch sent twice is kept once."""
    __tablename__ = "biometric_punches"
    __table_args__ = (UniqueConstraint("client_id", "biometric_id", "punched_at", "device_code", name="uq_biometric_punch"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    biometric_id = Column(String, nullable=False, index=True)    # the person's number on the machine
    punched_at = Column(String, nullable=False, index=True)      # YYYY-MM-DD HH:MM:SS, the machine's own clock
    device_code = Column(String, default="")
    direction = Column(String, default="")                       # in | out | "" when the machine does not say
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    employee_name = Column(String, default="")                   # the person's name in the attendance system, to suggest who a number is
    received_at = Column(String, default=_now)
