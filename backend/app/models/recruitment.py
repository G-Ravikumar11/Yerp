"""Hiring: requisitions, forms, interviews, offers and the documents asked of people."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class DBInterviewReminder(Base):
    """One interview reminder actually sent, so nobody is nudged twice."""
    __tablename__ = "interview_reminders"
    __table_args__ = (
        UniqueConstraint('interview_id', 'recipient', name='uq_interview_reminder'),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), nullable=False, index=True)
    # "candidate" or "interviewer" - each gets at most one.
    recipient = Column(String, default="candidate")
    sent_to = Column(String, default="")
    sent_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBJobRequisition(Base):
    """An open role. The application form describes *how* to apply; the
    requisition describes *what* is being hired for, which is what a hiring
    manager, the job board and the reporting all key off."""
    __tablename__ = "job_requisitions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    reference = Column(String, default="", index=True)
    title = Column(String, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True, index=True)
    hiring_manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)

    description = Column(Text, default="")
    requirements = Column(Text, default="")
    location = Column(String, default="")
    work_mode = Column(String, default="onsite")       # onsite | hybrid | remote
    employment_type = Column(String, default="full_time")
    level = Column(String, default="")

    salary_min = Column(Float, default=0.0)
    salary_max = Column(Float, default=0.0)
    salary_currency = Column(String, default="")
    show_salary = Column(Boolean, default=True)

    openings = Column(Integer, default=1)
    status = Column(String, default="draft", index=True)  # draft|open|on_hold|closed|filled
    is_published = Column(Boolean, default=False, index=True)
    closing_date = Column(String, default="")
    opened_at = Column(String, default="")
    closed_at = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    department = relationship("DBDepartment")
    hiring_manager = relationship("DBEmployee")


class DBRecruitmentForm(Base):
    __tablename__ = "recruitment_forms"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    job_id = Column(Integer, ForeignKey("job_requisitions.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    fields = Column(Text, default="[]")
    is_active = Column(Boolean, default=True)
    form_token = Column(String, unique=True, index=True, default=lambda: str(__import__('uuid').uuid4()))
    pipeline_stages = Column(Text, default='["Applied","Screening","Interview","Offer","Hired"]')
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    job = relationship("DBJobRequisition")


class DBInterview(Base):
    """A scheduled conversation with a candidate, plus the scorecard."""
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)

    round_name = Column(String, default="Interview")
    scheduled_at = Column(String, default="", index=True)   # YYYY-MM-DD HH:MM
    duration_minutes = Column(Integer, default=45)
    mode = Column(String, default="video")                  # video | phone | onsite
    location = Column(String, default="")
    meeting_link = Column(String, default="")
    interviewer_id = Column(Integer, ForeignKey("employees.id"), nullable=True, index=True)
    interviewer_name = Column(String, default="")

    status = Column(String, default="scheduled", index=True)  # scheduled|completed|cancelled|no_show
    outcome = Column(String, default="")                      # pass | fail | hold
    score = Column(Integer, default=0)                        # 0-5
    feedback = Column(Text, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    interviewer = relationship("DBEmployee")


class DBOffer(Base):
    """An offer extended to a candidate."""
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)

    job_title = Column(String, default="")
    level = Column(String, default="")
    salary = Column(Float, default=0.0)
    currency = Column(String, default="")
    start_date = Column(String, default="")
    expires_on = Column(String, default="")
    notes = Column(Text, default="")

    status = Column(String, default="draft", index=True)  # draft|sent|accepted|declined|withdrawn
    sent_at = Column(String, default="")
    responded_at = Column(String, default="")
    decline_reason = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBFormSubmission(Base):
    __tablename__ = "form_submissions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    form_id = Column(Integer, ForeignKey("recruitment_forms.id"), nullable=False, index=True)
    answers = Column(Text, default="{}")
    file_name = Column(String, default="")
    file_type = Column(String, default="")
    file_data = Column(Text, default="")
    candidate_name = Column(String, default="")
    candidate_email = Column(String, default="")
    candidate_phone = Column(String, default="")
    status = Column(String, default="new")
    current_stage = Column(String, default="Applied")
    stage_order = Column(Integer, default=0)
    rating = Column(Integer, default=0)
    notes = Column(String, default="")
    source = Column(String, default="direct")
    owner_name = Column(String, default="")
    rejected_reason = Column(String, default="")
    rejected_at = Column(String, default="")
    hired_at = Column(String, default="")
    hired_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    form = relationship("DBRecruitmentForm")
    documents = relationship("DBCandidateDocument", back_populates="submission")


class DBCandidateDocument(Base):
    """Files attached to an application. The submission row carries a single
    legacy attachment; a candidate normally sends several (CV, cover letter,
    right-to-work, certificates), so they live here."""
    __tablename__ = "candidate_documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)
    doc_type = Column(String, default="other")
    file_name = Column(String, default="")
    file_type = Column(String, default="")
    file_size = Column(Integer, default=0)
    file_data = Column(Text, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    submission = relationship("DBFormSubmission", back_populates="documents")


class DBSubmissionEvent(Base):
    """Audit trail of a candidate's movement through the pipeline."""
    __tablename__ = "submission_events"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    submission_id = Column(Integer, ForeignKey("form_submissions.id"), nullable=False, index=True)
    from_stage = Column(String, default="")
    to_stage = Column(String, default="")
    note = Column(String, default="")
    actor = Column(String, default="HR")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBDocument(Base):
    __tablename__ = "employee_documents"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    doc_type = Column(String, default="other")
    file_name = Column(String, default="")
    file_type = Column(String, default="")
    file_size = Column(Integer, default=0)
    file_data = Column(Text, default="")
    uploaded_by = Column(String, default="HR")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBDocumentRequirement(Base):
    """What HR asks new starters to provide.

    This is the template. Each employee gets their own request row against it,
    so a policy change does not rewrite what someone already submitted.
    """
    __tablename__ = "document_requirements"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    doc_type = Column(String, default="other")
    is_mandatory = Column(Boolean, default=True)
    due_days = Column(Integer, default=7)          # days after start date

    # Documents like a passport, visa or DBS check go out of date. HR decides
    # which ones need an expiry, and the employee supplies the actual date.
    requires_expiry = Column(Boolean, default=False)
    expiry_reminder_days = Column(Integer, default=30)

    # An optional blank form for the employee to download, complete and return.
    template_file_name = Column(String, default="")
    template_file_type = Column(String, default="")
    template_file_data = Column(Text, default="")

    applies_to = Column(String, default="all")     # all | department | level
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    level = Column(String, default="")
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    department = relationship("DBDepartment")


class DBDocumentRequest(Base):
    """One employee's obligation to provide one document, and its review."""
    __tablename__ = "document_requests"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    requirement_id = Column(Integer, ForeignKey("document_requirements.id"), nullable=True, index=True)
    document_id = Column(Integer, ForeignKey("employee_documents.id"), nullable=True)

    name = Column(String, nullable=False)          # copied so it survives template edits
    description = Column(String, default="")
    doc_type = Column(String, default="other")
    is_mandatory = Column(Boolean, default=True)
    due_date = Column(String, default="")

    # Supplied by the employee when the requirement asks for it.
    requires_expiry = Column(Boolean, default=False)
    expires_on = Column(String, default="", index=True)

    status = Column(String, default="pending", index=True)  # pending|submitted|approved|rejected
    submitted_at = Column(String, default="")
    reviewed_at = Column(String, default="")
    reviewed_by = Column(String, default="")
    review_note = Column(String, default="")

    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    employee = relationship("DBEmployee")
    document = relationship("DBDocument")
    # Needed so a request can report its template and reminder window; without
    # it the lookups silently returned None.
    requirement = relationship("DBDocumentRequirement")
