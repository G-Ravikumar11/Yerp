"""The head office endpoints: the HO portal's front page."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db

from app.core.auth import require_items_access, session_employee
from app.services.head_office import ho_overview


router = APIRouter()


@router.get("/api/ho/overview")
def head_office_overview(request: Request, db: Session = Depends(get_db)):
    """What head office looks after, on every site: vendors, work orders both ways, BOQs and bills -
    what is open, what is in draft, what waits on whom, and which projects have no BOQ yet.
    For HO QS, HO Coordinator and the Master."""
    client = require_items_access(request, db, "ho.view_all")
    return ho_overview(db, client, session_employee(request, db))
