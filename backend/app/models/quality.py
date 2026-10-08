"""Inspections, cube tests and non-conformances."""
from datetime import datetime

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

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
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCubeResult(Base):
    __tablename__ = "qc_cube_results"

    id = Column(Integer, primary_key=True, index=True)
    set_id = Column(Integer, ForeignKey("qc_cube_sets.id"), nullable=False, index=True)
    age_days = Column(Integer, default=28)
    tested_on = Column(String, default="")
    strengths = Column(String, default="")                      # "31.2, 29.8, 30.5" N/mm2
    average = Column(Float, default=0.0)
    lab = Column(String, default="")
    recorded_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBNcr(Base):
    """A non-conformance: work that is not what was specified, who owns
    putting it right, by when, and how it was closed."""
    __tablename__ = "qc_ncrs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # NCR-0001
    raised_on = Column(String, default="")
    raised_by = Column(String, default="")
    location = Column(String, default="")
    description = Column(Text, default="")
    severity = Column(String, default="Minor")                  # Minor | Major
    responsible = Column(String, default="")                    # the gang, the supplier...
    corrective_action = Column(Text, default="")
    target_date = Column(String, default="")
    source_type = Column(String, default="")                    # inspection | cube_set | manual
    source_id = Column(Integer, nullable=True)
    status = Column(String, default="OPEN", index=True)         # OPEN | CLOSED
    closed_on = Column(String, default="")
    closure_note = Column(Text, default="")
    closed_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
