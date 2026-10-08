"""Projects, the site diary, the programme and project chat."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class DBJob(Base):
    """A job, site or contract - the thing a contracting business actually
    makes or loses money on.

    Everything priced, bought or worked hangs off one of these: quotes,
    invoices, bills, purchase orders and hours. Without it the books answer
    "what did we turn over" but never "did Fairview make money", which is the
    question that decides whether to take the next one like it.

    Deliberately nullable everywhere it is referenced. A business that does not
    work job-by-job carries on exactly as before.
    """
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint('client_id', 'number', name='uq_client_job_number'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(String, index=True)
    name = Column(String, nullable=False)

    # Who it is for. The contact is the link to the customer record; the name is
    # kept alongside so a job still reads correctly if the contact is deleted.
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    customer_name = Column(String, default="")

    site_address = Column(String, default="")
    # Place of supply. For a works contract that is where the property is,
    # not where the client's head office is.
    state_code = Column(String, default="")
    description = Column(Text, default="")

    # quoting | won | in_progress | on_hold | complete | cancelled
    status = Column(String, default="quoting", index=True)
    start_date = Column(String, default="")
    target_end_date = Column(String, default="")
    completed_at = Column(String, default="")

    # What it was sold for, and what it was expected to cost. Margin is the gap.
    quoted_value = Column(Float, default=0.0)
    budget = Column(Float, default=0.0)
    currency = Column(String, default="")

    # The slice the customer keeps back until the job is signed off. A term of
    # this contract rather than a company setting, because it is negotiated
    # per job and forgetting it overstates what the job will actually collect.
    retention_percent = Column(Float, default=0.0)

    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    reference = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    contact = relationship("DBContact")
    manager = relationship("DBEmployee")


# THE SITE DIARY
#
# The daily record a site actually keeps: who turned up, what plant was
# standing, what the weather did, what got built and what stopped it. On a
# civil contract it is the document that settles a delay claim two years
# later, and it was the one piece of paper this app had no home for.
#
# One diary per site per day, enforced in the database. Two diaries for the
# same day is how a claim gets thrown out.
class DBSiteDiary(Base):
    __tablename__ = "site_diaries"
    __table_args__ = (
        UniqueConstraint('client_id', 'job_id', 'diary_date', name='uq_site_diary_day'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)

    diary_date = Column(String, nullable=False, index=True)
    # Clear | Cloudy | Rain | Heavy rain. Rain hours are what a claim turns
    # on, so they are a number rather than a note somebody has to read.
    weather = Column(String, default="Clear")
    rain_hours = Column(Float, default=0.0)
    working_hours = Column(Float, default=8.0)

    work_done = Column(Text, default="")
    holdups = Column(Text, default="")
    instructions = Column(Text, default="")
    visitors = Column(String, default="")
    safety_note = Column(String, default="")

    labour_cost = Column(Float, default=0.0)
    plant_cost = Column(Float, default=0.0)
    total_mandays = Column(Float, default=0.0)

    # DRAFT | SUBMITTED
    status = Column(String, default="DRAFT", index=True)
    prepared_by = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    prepared_by_name = Column(String, default="")
    submitted_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBDiaryLabour(Base):
    """Heads on site, by trade and by whose payroll they are on."""
    __tablename__ = "diary_labour"

    id = Column(Integer, primary_key=True, index=True)
    site_diary_id = Column(Integer, ForeignKey("site_diaries.id"), index=True)
    trade = Column(String, default="")           # Mason, Helper, Bar bender...
    agency = Column(String, default="Own")       # Own, or the subcontractor
    headcount = Column(Float, default=0.0)
    hours = Column(Float, default=8.0)
    rate = Column(Float, default=0.0)            # per manday
    amount = Column(Float, default=0.0)
    display_order = Column(Integer, default=0)


class DBDiaryPlant(Base):
    """Plant on site. Idle hours are recorded separately because plant that
    stood all day still costs money and is the first thing an owner asks
    about when the hire bill arrives."""
    __tablename__ = "diary_plant"

    id = Column(Integer, primary_key=True, index=True)
    site_diary_id = Column(Integer, ForeignKey("site_diaries.id"), index=True)
    plant = Column(String, default="")
    worked_hours = Column(Float, default=0.0)
    idle_hours = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)            # per hour
    amount = Column(Float, default=0.0)
    remarks = Column(String, default="")
    display_order = Column(Integer, default=0)


# PROJECT SCHEDULE
#
# What is meant to happen when, what has happened, and what slips if the
# thing before it slips. Progress on an activity tied to a work order line is
# read from the measurement book, so nobody types a percentage that the book
# already knows.
class DBScheduleActivity(Base):
    __tablename__ = "schedule_activities"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    code = Column(String, default="")                    # A10, A20...
    name = Column(String, default="")
    planned_start = Column(String, default="")
    planned_finish = Column(String, default="")
    weight = Column(Float, default=0.0)                  # its value, or any relative weight
    depends_on_id = Column(Integer, nullable=True)       # finish-to-start
    work_order_line_id = Column(Integer, ForeignKey("work_order_lines.id"), nullable=True, index=True)
    is_milestone = Column(Boolean, default=False)
    actual_start = Column(String, default="")
    actual_finish = Column(String, default="")
    display_order = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBScheduleProgress(Base):
    """Progress reported on an activity that is not measured in the book -
    dated, so the S-curve can be drawn for any week in the past."""
    __tablename__ = "schedule_progress"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("schedule_activities.id"), nullable=False, index=True)
    reported_on = Column(String, default="", index=True)
    percent = Column(Float, default=0.0)
    note = Column(String, default="")
    by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


# PROJECT CHAT
#
# The conversation about a site - the pour moved to Thursday, the client's
# engineer wants the cover blocks checked, a photo of the crack - kept on
# the project instead of in forty WhatsApp groups nobody can search.
class DBProjectThread(Base):
    __tablename__ = "project_threads"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    title = Column(String, default="")
    started_by = Column(String, default="")          # "member:3", "employee:7", "owner:1"
    started_by_name = Column(String, default="")
    closed = Column(Boolean, default=False, index=True)
    last_message_at = Column(String, default="", index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBProjectMessage(Base):
    __tablename__ = "project_messages"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    thread_id = Column(Integer, ForeignKey("project_threads.id"), nullable=False, index=True)
    author = Column(String, default="")              # as started_by
    author_name = Column(String, default="")
    body = Column(Text, default="")
    file_ids = Column(String, default="")            # "12,13"
    mentions = Column(String, default="")            # "member:3,employee:7"
    deleted = Column(Boolean, default=False)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBThreadRead(Base):
    """How far one person has read one thread."""
    __tablename__ = "project_thread_reads"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("project_threads.id"), nullable=False, index=True)
    reader = Column(String, default="", index=True)
    last_read_id = Column(Integer, default=0)
