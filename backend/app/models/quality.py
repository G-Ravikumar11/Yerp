"""Inspections, cube tests and non-conformances."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


class DBInspection(Base):
    """A checklist walked on site before work is covered up or passed: the
    reinforcement before the pour, the shuttering, the plaster - item by item,
    with who looked and what they found."""
    __tablename__ = "qc_inspections"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)            # INS-0001
    checklist = Column(String, default="")                      # Pre-pour (concrete)
    location = Column(String, default="")                       # Raft, grid A-C
    inspected_on = Column(String, default="")
    inspected_by = Column(String, default="")
    witnessed_by = Column(String, default="")                   # the client's engineer
    items = Column(Text, default="[]")                          # [{item, result: ok|not ok|na, remark}]
    result = Column(String, default="OPEN", index=True)         # OPEN | PASSED | FAILED
    remarks = Column(Text, default="")
    # Where on the project, what work, who is to inspect it, what was measured.
    building = Column(String, default="")
    floor_area = Column(String, default="")
    work_activity = Column(String, default="")
    assigned_to = Column(String, default="")
    measurements = Column(Text, default="")
    # The inspector submits; somebody who signs off decides. "" | submitted | returned | approved
    approval_status = Column(String, default="")
    submitted_by = Column(String, default="")
    submitted_on = Column(String, default="")
    approved_by = Column(String, default="")
    approved_on = Column(String, default="")
    return_note = Column(Text, default="")
    # The inspection this one re-checks after corrective work.
    reinspection_of = Column(Integer, nullable=True, index=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCubeSet(Base):
    """Concrete cubes cast from one pour, and what they crushed at."""
    __tablename__ = "qc_cube_sets"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # CT-0001
    cast_on = Column(String, default="", index=True)
    location = Column(String, default="")
    grade = Column(String, default="M25")
    fck = Column(Float, default=25.0)                           # characteristic strength, N/mm2
    slump_mm = Column(Float, default=0.0)
    supplier = Column(String, default="")                       # RMC plant or site mixer
    docket = Column(String, default="")
    cast_by = Column(String, default="")
    remarks = Column(Text, default="")
    pour_ref = Column(String, default="")                       # the pour's own reference
    cube_ids = Column(String, default="")                       # A1, A2, A3 - how each cube is marked
    test_ages = Column(String, default="")                      # "7,28": the schedule this project asked for
    # The engineer's decision on the concrete, taken over all its results.
    acceptance = Column(String, default="")                     # "" | accepted | conditional | rejected
    acceptance_note = Column(Text, default="")
    accepted_by = Column(String, default="")
    accepted_on = Column(String, default="")
    reviewed_results = Column(Integer, default=0)               # how many results the decision covered
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCubeResult(Base):
    __tablename__ = "qc_cube_results"
    __table_args__ = (UniqueConstraint("set_id", "age_days", name="uq_cube_result_age"),)

    id = Column(Integer, primary_key=True, index=True)
    set_id = Column(Integer, ForeignKey("qc_cube_sets.id"), nullable=False, index=True)
    age_days = Column(Integer, default=28)
    tested_on = Column(String, default="")
    strengths = Column(String, default="")                      # "31.2, 29.8, 30.5" N/mm2
    average = Column(Float, default=0.0)
    lab = Column(String, default="")
    recorded_by_name = Column(String, default="")
    remarks = Column(Text, default="")
    flagged = Column(Boolean, default=False)                    # sent for engineering review by whoever recorded it
    # What the result was read against, as it stood when it was recorded - so a later change
    # to the criteria never rewrites an old verdict.
    evaluation = Column(String, default="")                     # meets | below | no_criteria
    criteria_min = Column(Float, default=0.0)
    criteria_single = Column(Float, default=0.0)
    criteria_ref = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBNcr(Base):
    """A non-conformance: work that is not what was specified, who owns
    putting it right, by when, and how it was closed."""
    __tablename__ = "qc_ncrs"
    __table_args__ = (UniqueConstraint("auto_key", name="uq_qc_ncr_auto_key"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # NCR-0001
    raised_on = Column(String, default="")
    raised_by = Column(String, default="")
    location = Column(String, default="")
    description = Column(Text, default="")
    severity = Column(String, default="Minor")                  # Minor | Major
    responsible = Column(String, default="")                    # the contractor, the supplier...
    corrective_action = Column(Text, default="")
    target_date = Column(String, default="")
    source_type = Column(String, default="")                    # inspection | cube_set | manual
    source_id = Column(Integer, nullable=True)
    status = Column(String, default="OPEN", index=True)         # OPEN | CLOSED
    closed_on = Column(String, default="")
    closure_note = Column(Text, default="")
    closed_by = Column(String, default="")
    origin = Column(String, default="")                         # "" (raised by hand) | Automatic Cube Test Failure
    # cube:<set>:<age>, on an NCR raised by a failed result. Unique: one failure, one NCR, however many times it is sent.
    auto_key = Column(String, nullable=True)
    store_batch_id = Column(Integer, nullable=True, index=True)  # the store lot it is raised against
    source_ref = Column(String, default="")                     # which result of the source, e.g. "28" days
    root_cause = Column(Text, default="")
    assigned_by = Column(String, default="")
    assigned_on = Column(String, default="")
    corrective_done = Column(Text, default="")                  # what was actually done, recorded by whoever did it
    corrective_on = Column(String, default="")
    verification_result = Column(String, default="")            # "" | verified | rejected
    verification_note = Column(Text, default="")
    verified_by = Column(String, default="")
    verified_on = Column(String, default="")
    reinspection_ref = Column(String, default="")               # the inspection that re-checked it
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBQcChecklist(Base):
    """A checklist a company keeps for itself: the items and what each must meet, drawn from the
    approved specification. The standard lists are built in; one of these with the same name replaces
    it for the company, or for one project."""
    __tablename__ = "qc_checklists"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    name = Column(String, default="")
    work_type = Column(String, default="")
    spec_ref = Column(String, default="")                       # the specification clause it comes from
    items = Column(Text, default="[]")                          # [{item, criteria}]
    is_active = Column(Boolean, default=True)
    created_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBQcCriteria(Base):
    """What a grade of concrete must reach at an age on one project, as the approved specification says.
    Nothing here is assumed: a result with no row to read against is sent for engineering review."""
    __tablename__ = "qc_criteria"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    grade = Column(String, default="")                          # M25
    age_days = Column(Integer, default=28)
    min_mean = Column(Float, default=0.0)                       # the set's average must reach this, N/mm2
    min_single = Column(Float, default=0.0)                     # no single cube below this (0 = not specified)
    standard = Column(String, default="")                       # IS 456:2000 cl. 16, or the project specification
    approved_by = Column(String, default="")
    approved_on = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCubeDueNotice(Base):
    """The day's notice of cube tests due for one project, what it listed, and how delivery went. One a project a day."""
    __tablename__ = "qc_cube_due_notices"
    __table_args__ = (UniqueConstraint("job_id", "run_date", name="uq_cube_due_notice"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    run_date = Column(String, nullable=False, index=True)       # the project's own today
    project = Column(String, default="")
    subject = Column(String, default="")
    body = Column(Text, default="")
    tests = Column(Text, default="{}")
    test_count = Column(Integer, default=0)
    status = Column(String, default="Pending", index=True)      # Pending | Sending | Sent | Failed
    attempts = Column(Integer, default=0)
    bell_sent = Column(Boolean, default=False)
    sent_to = Column(String, default="")                        # who has it: a retry leaves them out
    sent_at = Column(String, default="")
    error = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
