"""Companies, their sign-ins, settings, the audit trail and the platform's own bookkeeping."""
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class DBClient(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    company_name = Column(String, default="")
    contact_name = Column(String, default="")
    phone_number = Column(String, default="")
    logo_url = Column(String, default="")
    address = Column(String, default="")
    website = Column(String, default="")
    abn = Column(String, default="")                      # template leftover; GSTIN is below
    # The GSTIN says which state we are registered in - the first two digits
    # are the state code - and that is what decides whether a bill carries
    # CGST+SGST or IGST.
    gstin = Column(String, default="")
    state_code = Column(String, default="")
    industry = Column(String, default="")
    is_active = Column(Boolean, default=True)
    is_onboarded = Column(Boolean, default=False)
    currency = Column(String, default="INR")
    last_login = Column(String, default="")
    login_count = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    settings = relationship("DBSettings", back_populates="client")
    invoices = relationship("DBInvoice", back_populates="client")
    bills = relationship("DBBill", back_populates="client")
    contacts = relationship("DBContact", back_populates="client")
    departments = relationship("DBDepartment", back_populates="client")
    employees = relationship("DBEmployee", back_populates="client")
    attendance = relationship("DBAttendance")


class DBJobRun(Base):
    """A claim on one run of one scheduled job.

    Railway can run more than one worker, and each would otherwise fire the
    same job. The unique constraint is the lock: whoever inserts the row for a
    period gets to do the work, everyone else finds it taken.
    """
    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint('job_name', 'period_key', name='uq_job_period'),
    )

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String, nullable=False, index=True)
    # What "this run" means for the job - usually a date, so a daily job runs
    # once a day however often the loop wakes up.
    period_key = Column(String, nullable=False, index=True)
    status = Column(String, default="running")
    detail = Column(String, default="")
    started_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    finished_at = Column(String, default="")


class DBTeamMember(Base):
    """Somebody who works at a tenant, other than the account owner.

    The owner stays on DBClient, which is where the company and its original
    credentials live. Everyone else is a row here, so adding colleagues never
    touches the record the whole tenancy hangs off.
    """
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint('client_id', 'email', name='uq_client_member_email'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    name = Column(String, default="")
    password_hash = Column(String, default="")
    # owner: everything. admin: everything but the team and the wallet.
    # viewer: read-only, enforced centrally rather than endpoint by endpoint.
    role = Column(String, default="admin", index=True)
    is_active = Column(Boolean, default=True)
    invited_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    accepted_at = Column(String, default="")
    last_login = Column(String, default="")


class DBPasswordReset(Base):
    """One password reset link.

    Only a hash of the token is kept, the same way passwords are, so a copy of
    this table is not a set of working reset links.
    """
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    # Owners and staff both need a way back in, and the mechanism is identical,
    # so one table serves both rather than two that can drift apart.
    user_type = Column(String, default="client", index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    member_id = Column(Integer, ForeignKey("team_members.id"), nullable=True, index=True)
    token_hash = Column(String, nullable=False, index=True)
    expires_at = Column(String, nullable=False)
    used_at = Column(String, default="")
    requested_ip = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBSettings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    key = Column(String, index=True)
    value = Column(String)
    description = Column(String, default="")

    client = relationship("DBClient", back_populates="settings")


class DBSuperAdmin(Base):
    __tablename__ = "super_admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    email = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)


class DBClientLoginLog(Base):
    __tablename__ = "client_login_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    email = Column(String, nullable=False)
    user_type = Column(String, default="client")
    login_type = Column(String, default="password")
    ip_address = Column(String, default="")
    device_info = Column(String, default="")
    location_label = Column(String, default="")
    status = Column(String, default="success")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    user_type = Column(String, default="client")
    user_name = Column(String, default="")
    action = Column(String, nullable=False)
    entity_type = Column(String, default="")
    entity_id = Column(Integer, nullable=True)
    entity_name = Column(String, default="")
    details = Column(Text, default="")
    ip_address = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# THE PARTNER PORTAL
#
# A gang or a supplier signs in to see their own orders, bills, payments and
# statement - the phone call asking "has my bill been passed?" answered
# without anybody in the office picking up. One login is one person at one
# party, and it sees nothing of anybody else's.
class DBPortalUser(Base):
    __tablename__ = "partner_portal_users"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    party_type = Column(String, default="contractor", index=True)     # contractor | supplier
    party_id = Column(Integer, nullable=False, index=True)
    name = Column(String, default="")
    email = Column(String, default="", index=True)
    password_hash = Column(String, default="")
    invite_token_hash = Column(String, default="", index=True)
    invite_expires = Column(String, default="")
    is_active = Column(Boolean, default=True)
    last_login = Column(String, default="")
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBIdempotency(Base):
    """The answer given to a change sent with an Idempotency-Key, so that sending it again does not make it twice."""
    __tablename__ = "idempotent_requests"
    __table_args__ = (UniqueConstraint("key", "scope", name="uq_idempotent_key"),)

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, nullable=False, index=True)
    scope = Column(String, nullable=False)
    status = Column(Integer, default=200)
    headers = Column(Text, default="")
    body = Column(LargeBinary)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)
