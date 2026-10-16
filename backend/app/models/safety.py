"""Incidents, toolbox talks, work permits, and the screening of workers before they start."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text

from app.db.session import Base


class DBSafetyIncident(Base):
    """Something that happened, or nearly did - a near miss is the cheapest
    lesson a site gets."""
    __tablename__ = "safety_incidents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # INC-0001
    happened_on = Column(String, default="", index=True)        # date
    happened_at = Column(String, default="")                     # time
    kind = Column(String, default="Near miss")
    location = Column(String, default="")
    description = Column(Text, default="")
    injured_name = Column(String, default="")
    injury = Column(String, default="")
    treatment = Column(String, default="")
    lost_days = Column(Float, default=0.0)
    immediate_action = Column(Text, default="")
    root_cause = Column(Text, default="")
    corrective_action = Column(Text, default="")
    reported_by = Column(String, default="")
    status = Column(String, default="OPEN", index=True)         # OPEN | CLOSED
    closed_on = Column(String, default="")
    closure_note = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBToolboxTalk(Base):
    __tablename__ = "toolbox_talks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    held_on = Column(String, default="", index=True)
    topic = Column(String, default="")
    conducted_by = Column(String, default="")
    attendees = Column(Integer, default=0)
    attendee_names = Column(Text, default="")
    minutes = Column(Integer, default=15)
    notes = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBWorkPermit(Base):
    """A permit to work: what is allowed, where, until when, on which
    precautions - and closed when the work stops."""
    __tablename__ = "work_permits"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # PTW-0001
    kind = Column(String, default="Work at height")
    location = Column(String, default="")
    description = Column(Text, default="")
    valid_from = Column(String, default="")                      # "2026-09-26 08:00"
    valid_to = Column(String, default="", index=True)
    issued_by = Column(String, default="")
    receiver = Column(String, default="")                        # the person doing the work
    precautions = Column(Text, default="[]")                     # [{item, done}]
    status = Column(String, default="ACTIVE", index=True)        # ACTIVE | CLOSED | CANCELLED
    closed_at = Column(String, default="")
    closed_by = Column(String, default="")
    closure_note = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBWorkerScreening(Base):
    """A worker screened before starting on site, after the company's own paper "Screening Of Worker" form: who
    they are, their trade, their physical and education details, their previous work, and the proof - a photo and
    a medical certificate, kept as files attached to this record (attached_type "worker")."""
    __tablename__ = "worker_screenings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # WKR-0001, also the form's "Worker ID No"
    name = Column(String, default="")
    age = Column(Integer, default=0)
    address = Column(Text, default="")
    trade = Column(String, default="", index=True)              # one of WORKER_TRADES; the form's "Suitable for employment as"
    screened_on = Column(String, default="", index=True)
    screened_by = Column(String, default="")

    contractor_name = Column(String, default="")                # Name of the Contractor / Sub-Contractor
    father_name = Column(String, default="")                    # Father / Husband's Name
    dob = Column(String, default="")
    sex = Column(String, default="")
    marital_status = Column(String, default="")
    children = Column(Integer, default=0)
    mother_tongue = Column(String, default="")
    other_languages = Column(String, default="")
    emergency_contact = Column(String, default="")
    phone = Column(String, default="")                           # the worker's own mobile, 10 digits
    identification_mark = Column(String, default="")

    vision_normal = Column(Boolean, default=True)
    vision_problem = Column(String, default="")
    health_normal = Column(Boolean, default=True)
    health_problem = Column(String, default="")
    weight_kg = Column(Float, default=0.0)
    height_cm = Column(Float, default=0.0)
    blood_group = Column(String, default="")

    education = Column(Text, default="[]")                      # [{exam, year, school}]
    experience = Column(Text, default="[]")                     # [{organization, project_site, category, period, salary}]

    pan = Column(String, default="")                             # ABCDE1234F
    aadhaar = Column(String, default="")                         # 12 digits; shown masked, only the last four
    signature = Column(Text, default="")                         # the photo of the worker's signature, a PNG data: URI
    signed_at = Column(String, default="")
    certificates_verified = Column(Boolean, default=False)
    trial_briefed = Column(Boolean, default=False)              # seen and briefed the site's EHS rules
    safety_officer_name = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBEquipmentCheck(Base):
    """One inspection of a tool, an extinguisher or an electrical board, on the company's paper checklist. The answers,
    the readings and the sign-offs are kept as they were filled in; the photos are files attached to this record
    (attached_type "equipment_check", caption "item:<key>")."""
    __tablename__ = "equipment_checks"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)             # CHK-0001
    form_type = Column(String, default="", index=True)          # a key of EQUIPMENT_CHECKS
    equipment_no = Column(String, default="", index=True)       # the equipment, extinguisher or board number
    specs = Column(String, default="")
    location = Column(String, default="")
    extinguisher_type = Column(String, default="")
    board_type = Column(String, default="")
    contractor_name = Column(String, default="")
    inspection_date = Column(String, default="", index=True)
    next_inspection_date = Column(String, default="", index=True)
    items = Column(Text, default="[]")                          # [{key, answer, remarks}]
    readings = Column(Text, default="{}")                       # {wheel_rpm, machine_rpm, earth_resistance}
    signoffs = Column(Text, default="{}")                       # {role: {name, date}}
    decision = Column(String, default="")                       # "" | accepted | rejected  (the client / PMC review)
    decision_by = Column(String, default="")
    decision_on = Column(String, default="")
    recorded_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
