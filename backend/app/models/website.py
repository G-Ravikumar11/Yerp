"""The company website's words and pictures, kept so they can be changed without a new release (Settings -> Website)."""
from datetime import datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db.session import Base


class DBWebsiteSection(Base):
    """One section of the website (the hero, the about text, what we build...) for one company.

    `draft` is what whoever manages the website is working on; `published` is what visitors see. Both are the section's
    content as JSON, in the shape frontend/src/features/site/data/content.ts gives it. They start the same, from
    app/constants/website_content.json (services/website_content.py)."""
    __tablename__ = "website_sections"
    __table_args__ = (UniqueConstraint("client_id", "key", name="uq_website_section"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    key = Column(String, nullable=False)
    draft = Column(Text, nullable=False, default="null")
    published = Column(Text, nullable=False, default="null")
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_by = Column(String, default="")
    published_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    published_by = Column(String, default="")


class DBWebsiteVersion(Base):
    """One publishing of the website: every section as it went live, so an earlier version can be put back.

    `content` is {section key: content} for every section, the projects' cards included. Numbered 1, 2, 3... per company."""
    __tablename__ = "website_versions"
    __table_args__ = (UniqueConstraint("client_id", "number", name="uq_website_version"),)

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False, default="{}")
    note = Column(String, default="")
    published_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    published_by = Column(String, default="")
