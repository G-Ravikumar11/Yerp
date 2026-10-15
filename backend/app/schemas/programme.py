"""What the programme endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel, Field


class ProgrammeEditIn(BaseModel):
    # each: {"id": .., and any of name, start, end, days, uom, quantity, predecessors, ...}
    changes: List[dict] = Field(default_factory=list)


class ProgrammeAddIn(BaseModel):
    anchor_id: Optional[int] = None
    position: str = "after"                 # after | child | end
    rows: List[dict] = Field(default_factory=lambda: [{}])


class ProgrammeFromBoqIn(BaseModel):
    # each: {"id": a BOQ node id, "name": the short name if changed, "splits": [{"label": "A-16", "quantity": 300}]}
    picks: List[dict] = Field(default_factory=list)
    anchor_id: Optional[int] = None
    position: str = "end"                   # after | child | end
    start: str = ""


class ProgrammeBaselineIn(BaseModel):
    label: str = ""


class ProgrammeMoveIn(BaseModel):
    id: int
    parent_id: Optional[int] = None
    before_id: Optional[int] = None


class ProgrammeCopyTarget(BaseModel):
    name: str
    start: str = ""
    offset: Optional[int] = None


class ProgrammeCopyIn(BaseModel):
    source_id: int
    targets: List[ProgrammeCopyTarget]


class ProgrammeCalendarIn(BaseModel):
    calendar_days: bool = False
    weekly_off: List[int] = Field(default_factory=lambda: [7])


class ProgrammeHolidayIn(BaseModel):
    date: str
    name: str = ""


class ProgrammePublicHolidaysIn(BaseModel):
    year: int


class ProgrammeRestoreIn(BaseModel):
    rows: List[dict]
    links: List[dict] = Field(default_factory=list)

class ProgrammeImportIn(BaseModel):
    nodes: List[dict]
    calendar: Optional[dict] = None