"""Birthdays and special days, and what people say about them."""
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint

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
