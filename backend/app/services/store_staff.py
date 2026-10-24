"""Store module - people leaving: someone who leaves the company is taken out of every store they worked in. Their rows stay, switched
off, so the history of who worked where is kept; coming back does not put them back - a store in-charge does that, deliberately."""
from app.models.store_core import DBStoreUserAssignment

LEFT = frozenset({"terminated", "inactive", "resigned", "left", "exited"})


def release_on_leaving(db, emp) -> int:
    """Switch off the store assignments of an employee whose status says they have left. Returns how many were switched off."""
    if (getattr(emp, "status", "") or "").strip().lower() not in LEFT:
        return 0
    rows = db.query(DBStoreUserAssignment).filter(DBStoreUserAssignment.employee_id == emp.id, DBStoreUserAssignment.is_active.is_(True)).all()
    for r in rows:
        r.is_active = False
    if rows:
        db.flush()
    return len(rows)
