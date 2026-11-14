"""Site stories: who has opened which site photo in the phone app."""
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint

from app.db.session import Base


class DBStoryView(Base):
    """One person has opened one site diary photo as a story. A person opens a story once; opening it again changes
    nothing, so the first time stands.

    `viewer` says who: owner, member:<id> or employee:<id>. `by_admin` is whether that person was the Master, an account
    admin or staff at the Master's access level at the time: the first such opening starts the 24 hours after which the
    story leaves the row (services/stories.py). The photo itself is the diary's and is never touched from here.

    `file_id` is the photo's number in project_files, kept as a plain number: a photo that is later removed takes nothing
    with it and is not held back by these rows."""
    __tablename__ = "story_views"
    __table_args__ = (UniqueConstraint("file_id", "viewer", name="uq_story_view"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    file_id = Column(Integer, nullable=False, index=True)
    viewer = Column(String, nullable=False)
    viewer_name = Column(String, default="")
    by_admin = Column(Boolean, default=False)
    viewed_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
