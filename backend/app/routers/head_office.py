"""The head office endpoints: the HO portal's front page."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db, get_read_db

from app.core.auth import require_items_access, session_employee
from app.core.cache import cached_read
from app.services.head_office import ho_overview


router = APIRouter()


@router.get("/api/ho/budget-control")
def head_office_budget_control(request: Request, db: Session = Depends(get_read_db)):
    """Every live project with a BOQ: how much of it HO QS has budgeted and what is left (services/budget_control.py).
    The values are the BOQ's own, so this is for those who see budgets."""
    from app.services.budget_control import live_projects
    client = require_items_access(request, db, ("budget.view", "budget.edit"))
    return {"projects": live_projects(db, client.id)}


@router.get("/api/ho/overview")
def head_office_overview(request: Request, db: Session = Depends(get_db)):
    """What head office looks after, on every site: vendors, work orders both ways, BOQs and bills -
    what is open, what is in draft, what waits on whom, and which projects have no BOQ yet.
    For HO QS, HO Coordinator and the Master."""
    client = require_items_access(request, db, "ho.view_all")
    emp = session_employee(request, db)
    # Refreshed every minute while the page is open; kept until anything is saved.
    return cached_read(("ho-overview", client.id, emp.id if emp else None),
                       lambda: ho_overview(db, client, emp), ttl=30)
