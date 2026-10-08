"""Attached files and drawings."""
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String

from app.db.session import Base


class DBFile(Base):
    """A photo or a document kept against something on a project: a diary
    day, a measurement, a variation, a drawing revision, the project itself.
    Kept in the database - the server's own disk is replaced on every deploy,
    and a site photo is evidence that has to outlive a release."""
    __tablename__ = "project_files"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    kind = Column(String, default="photo", index=True)           # photo | drawing | document
    attached_type = Column(String, default="job", index=True)    # job | diary | measurement | variation | drawing
    attached_id = Column(Integer, nullable=True, index=True)
    name = Column(String, default="")
    content_type = Column(String, default="application/octet-stream")
    size = Column(Integer, default=0)
    sha256 = Column(String, default="", index=True)
    data = Column(LargeBinary)
    thumb = Column(LargeBinary, nullable=True)                   # a small copy for the gallery
    caption = Column(String, default="")
    taken_on = Column(String, default="")
    uploaded_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # What came in, before it was made smaller - so the saving is known.
    original_size = Column(Integer, default=0)
    # The same file kept against a second record is not stored twice: this
    # row carries no bytes of its own and reads them from the one named here.
    blob_of = Column(Integer, nullable=True, index=True)


class DBDrawing(Base):
    """One drawing on the register - its number, what it shows, and which
    revision is the one to build to."""
    __tablename__ = "drawings"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    number = Column(String, default="", index=True)              # STR-101
    title = Column(String, default="")
    discipline = Column(String, default="Structural")
    current_revision = Column(String, default="")
    status = Column(String, default="For information")           # For approval | Approved | Good for construction | Superseded | For information
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBDrawingRevision(Base):
    __tablename__ = "drawing_revisions"

    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False, index=True)
    revision = Column(String, default="R0")
    file_id = Column(Integer, ForeignKey("project_files.id"), nullable=True)
    status = Column(String, default="For information")
    received_on = Column(String, default="")
    received_from = Column(String, default="")
    remarks = Column(String, default="")
    recorded_by_name = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
