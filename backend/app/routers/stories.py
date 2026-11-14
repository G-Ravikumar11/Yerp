"""Site stories in the phone app: the site diary's photos, site by site (services/stories.py has the rules)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import stories

router = APIRouter()


@router.get("/api/stories")
def story_row(request: Request, db: Session = Depends(get_db)):
    """The sites that have a story for this person, each with its photos, oldest first."""
    out = stories.row(db, stories.Viewer(request, db))
    db.commit()                 # the first asking sets when this company's stories begin
    return out


@router.post("/api/stories/{file_id}/seen")
def story_seen(file_id: int, request: Request, db: Session = Depends(get_db)):
    """This person has opened this story. Opened by the Master or an admin, it leaves the row 24 hours later."""
    out = stories.seen(db, stories.Viewer(request, db), file_id)
    db.commit()
    return out
