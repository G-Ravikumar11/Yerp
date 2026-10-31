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
    timezone = Column(String, default="")                       # where the site is; "" = the company default
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
    # Whether somebody actually stated the retention. An empty field holds 0 too, and a project that states none is
    # billed at the usual 5%; one whose contract says no retention at all states 0 and is billed at 0.
    retention_stated = Column(Boolean, default=False)

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
    submitted_by_name = Column(String, default="")      # who signed the day off
    # Each time a signed-off day was reopened to be changed: when, by whom and why, one line each. Kept for good, so a
    # diary that was amended after sign-off says so.
    amendments = Column(Text, default="")
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
    # Comma-separated worker_screenings ids, when this line was added "from Workers & Safety" rather than typed by
    # hand - the headcount then always matches how many are named here, and the diary shows them by name.
    worker_ids = Column(Text, default="")


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
    # The BOQ line (or section) it was drawn from, so drawing from the BOQ again adds only what is not on the programme yet.
    boq_key = Column(String, default="", index=True)
    is_milestone = Column(Boolean, default=False)
    actual_start = Column(String, default="")
    actual_finish = Column(String, default="")
    display_order = Column(Integer, default=0)
    assigned_to_id = Column(Integer, nullable=True, index=True)   # the employee responsible for it
    status = Column(String, default="")                          # Not Started | In Progress | Completed | Delayed, as set by hand
    notes = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # The programme as the office's Excel schedule has it (app/services/programme_engine.py works it out). Rows nest
    # under a parent to any depth: block, unit, activity, sub-activity. A parent's dates are worked out from its
    # sub-items, never kept as typed. A leaf keeps what was typed: planned_start, and duration_days (working days) or,
    # when there are none, planned_finish.
    parent_id = Column(Integer, ForeignKey("schedule_activities.id"), nullable=True, index=True)
    description = Column(Text, default="")             # the BOQ's full wording; `name` is the short one shown
    boq_ref = Column(String, default="")               # the client's item number, I-2.1.1 (the sheet's V.NO)
    uom = Column(String, default="")
    quantity = Column(Float, default=0.0)
    rate = Column(Float, default=0.0)
    amount = Column(Float, default=0.0)
    labour_required = Column(Float, default=0.0)
    duration_days = Column(Integer, nullable=True)     # working days, as typed
    not_before = Column(String, default="")            # never starts before this date
    productivity = Column(Boolean, default=False)      # days = quantity / (output per gang per day x gangs)
    output_per_day = Column(Float, default=0.0)        # per gang
    gangs = Column(Float, default=0.0)
    qty_done = Column(Float, default=0.0)              # progress in the row's unit; % done = qty_done / quantity
    # Why it is late against the baseline, when no hindrance on the register explains it: one of DELAY_REASONS, and a word more.
    delay_reason = Column(String, default="")
    delay_note = Column(Text, default="")


class DBScheduleLink(Base):
    """One row waiting on another: FS (after it ends), SS (after it starts), FF (ends after it ends) or SF (ends
    after it starts), with a lag in working days - negative for a lead. A row may wait on several."""
    __tablename__ = "schedule_links"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("schedule_activities.id"), nullable=False, index=True)      # the one that waits
    predecessor_id = Column(Integer, ForeignKey("schedule_activities.id"), nullable=False, index=True)
    kind = Column(String, default="FS")
    lag = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBScheduleCalendar(Base):
    """A project's working week: which weekdays are off (ISO numbers, Sunday 7), or every day counted."""
    __tablename__ = "schedule_calendars"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True, unique=True)
    calendar_days = Column(Boolean, default=False)
    weekly_off = Column(String, default="7")
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBScheduleHoliday(Base):
    """A day the project's site does not work, skipped like a Sunday."""
    __tablename__ = "schedule_holidays"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    holiday_on = Column(String, default="", index=True)
    name = Column(String, default="")


class DBScheduleBaseline(Base):
    """The programme as it was agreed, kept so today's dates can be read against it."""
    __tablename__ = "schedule_baselines"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    label = Column(String, default="")
    saved_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBScheduleBaselineRow(Base):
    __tablename__ = "schedule_baseline_rows"

    id = Column(Integer, primary_key=True, index=True)
    baseline_id = Column(Integer, ForeignKey("schedule_baselines.id"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("schedule_activities.id"), nullable=False, index=True)
    start = Column(String, default="")
    finish = Column(String, default="")
    days = Column(Integer, default=0)


class DBScheduleTask(Base):
    """A thing to be done on a given day: "pour the slab, 8 labourers", optionally under one of the project's
    activities. Ticked off when it is done, with who ticked it and when."""
    __tablename__ = "schedule_tasks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    activity_id = Column(Integer, ForeignKey("schedule_activities.id"), nullable=True, index=True)
    task_date = Column(String, default="", index=True)
    text = Column(String, default="")
    done = Column(Boolean, default=False)
    # How much of it is done when it is only part done (0-100). A task that is done is 100 whatever this says.
    percent = Column(Float, default=0.0)
    done_by_name = Column(String, default="")
    done_at = Column(String, default="")
    created_by_name = Column(String, default="")
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
    qty_done = Column(Float, nullable=True)            # in the row's unit, when it has a quantity
    note = Column(String, default="")
    by_name = Column(String, default="")
    # The site diary whose "work done" made this report, so deleting that draft takes it back (null: reported on the plan itself).
    diary_id = Column(Integer, nullable=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBDiaryTaskChange(Base):
    """What a site diary did to a task - ticked it, part-ticked it, put it back - with how the task stood before, so the diary can
    be deleted while it is still a draft and the task goes back as it was."""
    __tablename__ = "diary_task_changes"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    diary_id = Column(Integer, nullable=False, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    was_done = Column(Boolean, default=False)
    was_percent = Column(Float, default=0.0)
    was_done_by_name = Column(String, default="")
    was_done_at = Column(String, default="")
    now_done = Column(Boolean, default=False)
    now_percent = Column(Float, default=0.0)


class DBHindrance(Base):
    """Something that held the work up - rain, drawings not issued, the client's decision, a front not handed over - kept as it
    happened: the cause, from when to when, whose risk it was, how many days it cost and when the client was told. It is the record
    an extension of time is argued from, so it is kept per site, numbered, and can be raised straight from a day's diary."""
    __tablename__ = "hindrances"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="")                  # H-001, per site
    activity_id = Column(Integer, nullable=True, index=True)      # the activity it held up, when it held up one in particular
    diary_id = Column(Integer, nullable=True, index=True)         # the day's diary it was raised from
    cause = Column(String, default="")                   # one of HINDRANCE_CAUSES
    description = Column(Text, default="")
    from_date = Column(String, default="", index=True)
    to_date = Column(String, default="")                 # blank while it is still holding the work up
    responsibility = Column(String, default="")          # one of HINDRANCE_PARTIES: whose risk it was
    impact_days = Column(Float, default=0.0)             # working days it cost the work
    notice_date = Column(String, default="")             # when the client was told in writing
    status = Column(String, default="Open", index=True)  # one of HINDRANCE_STATUSES
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBDelayAlert(Base):
    """An activity that has gone late against its baseline, and the day its people were told. One a delay: the next morning's run
    finds it here and says nothing more; once the activity is back on time the row goes, so a later slip is a new delay."""
    __tablename__ = "delay_alerts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, nullable=False, index=True)
    activity_id = Column(Integer, nullable=False, index=True)
    promised = Column(String, default="")              # the baseline finish it went late against
    delay_days = Column(Integer, default=0)            # how late it was when told
    told = Column(String, default="")                  # who was told, by name
    alerted_on = Column(String, default="")


class DBSiteReportRun(Base):
    """What the evening run did for a site on a day: the report sent (and to whom), or the reminder that no diary was written."""
    __tablename__ = "site_report_runs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, nullable=False, index=True)
    run_on = Column(String, default="", index=True)
    kind = Column(String, default="")                  # report | reminder
    sent_to = Column(Text, default="")
    note = Column(String, default="")
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
    description = Column(Text, default="")
    category = Column(String, default="General", index=True)    # General | Site Progress | Materials | Quality | Safety | Design | Approvals
    priority = Column(String, default="Normal", index=True)     # Low | Normal | High | Urgent
    members = Column(String, default="")                         # "member:3,employee:7" - who the thread is for
    link_type = Column(String, default="")                       # progress | delivery | quality | safety | design | approval
    link_ref = Column(String, default="")                        # NCR-0005, GRN-0012, drawing STR-101...
    link_id = Column(Integer, nullable=True)
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
    parent_id = Column(Integer, nullable=True, index=True)       # the message this replies to
    edited_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBThreadRead(Base):
    """How far one person has read one thread."""
    __tablename__ = "project_thread_reads"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("project_threads.id"), nullable=False, index=True)
    reader = Column(String, default="", index=True)
    last_read_id = Column(Integer, default=0)


class DBChatReaction(Base):
    """One person's emoji on one message."""
    __tablename__ = "chat_reactions"
    __table_args__ = (UniqueConstraint("message_id", "reader", "emoji", name="uq_chat_reaction"),)

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("project_messages.id"), nullable=False, index=True)
    reader = Column(String, default="", index=True)
    emoji = Column(String, default="")


class DBChatTask(Base):
    """An action item made from a conversation: who, by when, and where it stands."""
    __tablename__ = "chat_tasks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    thread_id = Column(Integer, ForeignKey("project_threads.id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("project_messages.id"), nullable=True, index=True)
    title = Column(String, default="")
    description = Column(Text, default="")
    assignee = Column(String, default="", index=True)            # "employee:7"
    assignee_name = Column(String, default="")
    due_date = Column(String, default="")
    priority = Column(String, default="Normal")
    status = Column(String, default="Open", index=True)          # Open | In Progress | Blocked | Resolved | Closed
    created_by = Column(String, default="")
    created_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default="")


class DBChatNotice(Base):
    """Something for one person: a message to them, a reply, a mention, a task, a date coming up."""
    __tablename__ = "chat_notices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    recipient = Column(String, default="", index=True)           # "employee:7"
    kind = Column(String, default="")                            # message | reply | mention | assigned | due | update
    title = Column(String, default="")
    body = Column(Text, default="")
    thread_id = Column(Integer, nullable=True, index=True)
    task_id = Column(Integer, nullable=True)
    dedupe = Column(String, default="", index=True)              # one reminder per task per day
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)
