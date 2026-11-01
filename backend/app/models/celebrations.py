"""Birthdays and special days, and what people say about them."""
from datetime import datetime

from sqlalchemy import Text, Boolean, Column, ForeignKey, Integer, LargeBinary, String, UniqueConstraint

from app.db.session import Base


class DBSpecialDay(Base):
    """A day HR wants everybody told about - a festival, the company's anniversary, a milestone.

    India's public holidays are announced on their own and are not kept here; this is for what HR adds.
    The date is YYYY-MM-DD. A `yearly` day comes round again on the same month and day every year."""
    __tablename__ = "special_days"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    date = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    message = Column(String, default="")
    emoji = Column(String, default="")
    yearly = Column(Boolean, default=False)
    announced_on = Column(String, default="")          # the day everybody was told, so a day is told once
    created_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCelebrationReaction(Base):
    """One emoji from one person on one celebration. `celebration` names it: birthday:<employee>:<year>,
    special:<id>:<year> or festival:<date>. Reacting with the same emoji again takes it back."""
    __tablename__ = "celebration_reactions"
    __table_args__ = (UniqueConstraint("client_id", "celebration", "author", "emoji", name="uq_celebration_reaction"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    celebration = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False)              # e:<employee id>, or owner
    author_name = Column(String, default="")
    emoji = Column(String, nullable=False)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBCelebrationWish(Base):
    """A message left on a celebration. Its writer may take it down again, and so may HR."""
    __tablename__ = "celebration_wishes"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    celebration = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False)
    author_name = Column(String, default="")
    message = Column(String, nullable=False)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBAnnouncement(Base):
    """Something HR wants every employee to see on the Feed: a site notice, a holiday, anything important.

    Only HR and the Master write them; everybody in the company reads them. `pinned` keeps one at the top, and
    `expires_on` (YYYY-MM-DD, optional) takes it off the Feed after that day so old news does not pile up."""
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    category = Column(String, default="general")          # general | site | holiday | important
    pinned = Column(Boolean, default=False)
    expires_on = Column(String, default="")
    posted_by = Column(String, default="")                # the name shown
    posted_by_key = Column(String, default="")            # owner, m:<member>, e:<employee>
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)
    updated_at = Column(String, default="")


class DBAnnouncementMedia(Base):
    """A photo or a video shown with an announcement. Kept in the database like the project photos: the server's own
    disk is replaced on every deploy. Everybody in the company may watch it; only HR and the Master add or remove."""
    __tablename__ = "announcement_media"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False, index=True)
    kind = Column(String, default="image")                # image | video
    name = Column(String, default="")
    content_type = Column(String, default="")
    size = Column(Integer, default=0)
    data = Column(LargeBinary)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
