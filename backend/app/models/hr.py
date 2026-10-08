"""Departments, employees, pay, attendance and leave."""
from datetime import datetime
import uuid

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class DBDepartment(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    color = Column(String, default="#00f0ff")
    icon = Column(String, default="building")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="departments")
    employees = relationship("DBEmployee", back_populates="department")


class DBEmployee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    reports_to = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)

    employee_id = Column(String, default="")
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String, default="")
    address = Column(String, default="")

    job_title = Column(String, default="")
    role = Column(String, default="employee")
    # What this person may DO in the portal, decided by HR. Deliberately
    # separate from `role`, which is their place in the reporting line: a site
    # supervisor may need to raise costs without being anyone's manager, and a
    # department head may have no business touching payroll.
    permission_role = Column(String, default="staff", index=True)
    # What the owner has granted or withheld for this person on top of their
    # role. A role is a sensible starting point, not a straitjacket: one
    # supervisor may also settle bills, one manager may be kept out of payroll,
    # and neither should need a new role invented for them. Comma separated
    # permission keys; a denial beats a grant.
    extra_permissions = Column(Text, default="")
    denied_permissions = Column(Text, default="")
    # Seniority band (L1..L8). Kept separate from `role`, which describes what
    # the person does in the reporting line, not how senior they are.
    level = Column(String, default="", index=True)
    employment_type = Column(String, default="full_time")
    pay_frequency = Column(String, default="monthly")

    salary = Column(Float, default=0.0)
    hourly_rate = Column(Float, default=0.0)
    tax_rate = Column(Float, default=0.0)
    deductions = Column(Float, default=0.0)
    allowances = Column(Float, default=0.0)
    bonus = Column(Float, default=0.0)

    bank_name = Column(String, default="")
    bank_account = Column(String, default="")
    tax_id = Column(String, default="")

    emergency_contact = Column(String, default="")
    emergency_phone = Column(String, default="")

    annual_leave_entitlement = Column(Float, default=25.0)
    sick_leave_entitlement = Column(Float, default=10.0)

    password_hash = Column(String, default="")
    work_location = Column(String, default="")
    latitude = Column(Float, default=0.0)
    longitude = Column(Float, default=0.0)

    start_date = Column(String, default="")
    end_date = Column(String, default="")
    status = Column(String, default="active", index=True)
    onboarding_complete = Column(Boolean, default=False)
    offboarding_complete = Column(Boolean, default=False)

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    client = relationship("DBClient", back_populates="employees")
    department = relationship("DBDepartment", back_populates="employees")
    manager = relationship("DBEmployee", remote_side=[id], backref="direct_reports")
    payslips = relationship("DBPayslip", back_populates="employee")
    onboarding_items = relationship("DBOnboardingItem", back_populates="employee")
    attendance = relationship("DBAttendance")


class DBPayslip(Base):
    __tablename__ = "payslips"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_payslip_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    number = Column(String, index=True)

    period_start = Column(String, default="")
    period_end = Column(String, default="")
    pay_date = Column(String, default="")

    hours_worked = Column(Float, default=0.0)
    overtime_hours = Column(Float, default=0.0)
    overtime_rate = Column(Float, default=0.0)

    basic_salary = Column(Float, default=0.0)
    overtime_pay = Column(Float, default=0.0)
    bonus = Column(Float, default=0.0)
    allowances = Column(Float, default=0.0)
    gross_pay = Column(Float, default=0.0)

    tax_amount = Column(Float, default=0.0)
    insurance = Column(Float, default=0.0)
    retirement = Column(Float, default=0.0)
    other_deductions = Column(Float, default=0.0)
    total_deductions = Column(Float, default=0.0)

    net_pay = Column(Float, default=0.0)

    status = Column(String, default="Draft", index=True)
    sent = Column(String, default="")
    notes = Column(String, default="")
    pay_frequency = Column(String, default="")

    tracking_id = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    open_count = Column(Integer, default=0)
    last_opened = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee", back_populates="payslips")


class DBOnboardingItem(Base):
    __tablename__ = "onboarding_items"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)

    title = Column(String, nullable=False)
    description = Column(String, default="")
    category = Column(String, default="general")
    is_completed = Column(Boolean, default=False)
    completed_at = Column(String, default="")
    assigned_to = Column(String, default="")
    due_date = Column(String, default="")
    sort_order = Column(Integer, default=0)

    employee = relationship("DBEmployee", back_populates="onboarding_items")


class DBOnboardingTemplate(Base):
    __tablename__ = "onboarding_templates"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    items_json = Column(Text, default="[]")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAttendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(String, nullable=False, index=True)
    clock_in = Column(String, default="")
    clock_out = Column(String, default="")
    total_hours = Column(Float, default=0.0)
    status = Column(String, default="present", index=True)
    check_type = Column(String, default="manual")
    ip_address = Column(String, default="")
    device_info = Column(String, default="")
    location_lat = Column(Float, default=0.0)
    location_lng = Column(Float, default=0.0)
    location_label = Column(String, default="")
    break_start = Column(String, default="")
    break_minutes = Column(Float, default=0.0)
    is_on_break = Column(Boolean, default=False)
    overtime_hours = Column(Float, default=0.0)
    overtime_announced = Column(Boolean, default=False)
    overtime_announced_by = Column(String, default="")
    # Which job the day was worked on, so labour reaches job costing. Left
    # empty for office staff and anyone whose time is not chargeable to a site.
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    notes = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAttendanceSettings(Base):
    __tablename__ = "attendance_settings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, unique=True)
    office_name = Column(String, default="Head Office")
    office_lat = Column(Float, default=0.0)
    office_lng = Column(Float, default=0.0)
    geofence_radius = Column(Float, default=200.0)
    work_start = Column(String, default="09:00")
    work_end = Column(String, default="17:30")
    grace_minutes = Column(Float, default=15.0)
    auto_clockout_hours = Column(Float, default=10.0)
    max_overtime_hours = Column(Float, default=4.0)
    allow_remote = Column(Boolean, default=True)
    require_location = Column(Boolean, default=True)
    # ISO weekday numbers, Monday = 1 through Sunday = 7.
    working_days = Column(String, default="1,2,3,4,5")
    # Whether signing in to the portal counts as starting a shift. Off means
    # people clock in deliberately, so opening the portal on a day off - to
    # read a payslip or upload a document - does not record attendance.
    auto_clock_in = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBOvertimeLog(Base):
    __tablename__ = "overtime_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    date = Column(String, nullable=False)
    hours = Column(Float, default=0.0)
    reason = Column(String, default="")
    announced_by = Column(String, default="")
    status = Column(String, default="announced")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBEmployeeGoal(Base):
    __tablename__ = "employee_goals"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    target_value = Column(Float, default=100.0)
    current_value = Column(Float, default=0.0)
    unit = Column(String, default="%")
    category = Column(String, default="performance")
    priority = Column(String, default="medium")
    start_date = Column(String, default="")
    due_date = Column(String, default="")
    status = Column(String, default="in_progress")
    created_by = Column(String, default="HR")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee")
    department = relationship("DBDepartment")


class DBDepartmentGoal(Base):
    __tablename__ = "department_goals"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    target_value = Column(Float, default=100.0)
    unit = Column(String, default="%")
    category = Column(String, default="performance")
    priority = Column(String, default="medium")
    start_date = Column(String, default="")
    due_date = Column(String, default="")
    created_by = Column(String, default="HR")
    is_assigned = Column(Boolean, default=False)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    department = relationship("DBDepartment")


class DBLeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    leave_type = Column(String, default="annual")
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    days = Column(Float, default=0.0)
    reason = Column(String, default="")
    status = Column(String, default="pending")
    approved_by = Column(String, default="")
    decided_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee")


class DBEmployeeSite(Base):
    """Which sites a person works on.

    A row per person per site rather than a column on the employee, because
    crews move and most of them are on more than one job in a season. No rows
    at all means no restriction - see employee_site_ids.
    """
    __tablename__ = "employee_sites"
    __table_args__ = (
        UniqueConstraint('employee_id', 'job_id', name='uq_employee_site'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBSiteGeofence(Base):
    """Where a project's site is, for attendance: a point and how far from it
    still counts as on site. A clock-in inside it is tagged to the project -
    the man-hours land on the job they were worked on."""
    __tablename__ = "site_geofences"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True, unique=True)
    lat = Column(Float, default=0.0)
    lng = Column(Float, default=0.0)
    radius_m = Column(Float, default=300.0)
    set_by_name = Column(String, default="")
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
