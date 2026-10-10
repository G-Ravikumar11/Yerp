"""The rules and workings behind the employee portal endpoints."""
from datetime import date, datetime, timedelta
import math
from typing import Any, Dict, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session


from app import models
from app.core.audit import log_audit
from app.core.currency import money
from app.core.dates import DEFAULT_WORKING_DAYS, _parse_date, parse_working_days
from app.core.permissions import employee_can
from app.services.approvals import get_approval_chain_history
from app.services.hr import employee_name
from app.services.projects import job_label_for


# -------------------------------------------------------------------------
# ATTENDANCE & WORKING DAYS
# -------------------------------------------------------------------------

def attendance_settings_for(db: Session, client_id: int) -> Optional[models.DBAttendanceSettings]:
    """Retrieve attendance settings for a tenant client."""
    if not client_id:
        return None
    return db.query(models.DBAttendanceSettings).filter(
        models.DBAttendanceSettings.client_id == client_id
    ).first()


def is_working_day(settings: Optional[models.DBAttendanceSettings], on_date: Any = None) -> bool:
    """Check whether a given date is a working day under tenant settings."""
    if on_date is None:
        target = datetime.now().date()
    elif isinstance(on_date, str):
        target = _parse_date(on_date) or datetime.now().date()
    elif isinstance(on_date, datetime):
        target = on_date.date()
    elif isinstance(on_date, date):
        target = on_date
    else:
        target = datetime.now().date()

    raw = getattr(settings, "working_days", None) if settings else None
    return target.isoweekday() in parse_working_days(raw or DEFAULT_WORKING_DAYS)


def should_auto_clock_in(settings: Optional[models.DBAttendanceSettings], on_date: Any = None) -> bool:
    """Determine whether accessing the portal should automatically clock the employee in."""
    if settings is not None and not bool(getattr(settings, "auto_clock_in", True)):
        return False
    return is_working_day(settings, on_date)


# -------------------------------------------------------------------------
# BILLS & PROCUREMENT
# -------------------------------------------------------------------------

def bill_money_from(body: Optional[Dict[str, Any]]) -> Tuple[float, float, float]:
    """Extract and validate amount, tax, and recompute total from a form body.

    Guards against NaN, Inf, negatives, and ensures total exactly reconciles.
    """
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid request body")

    try:
        raw_amount = body.get("amount")
        raw_tax = body.get("tax_amount")
        amount = float(0 if raw_amount in (None, "") else raw_amount)
        tax = float(0 if raw_tax in (None, "") else raw_tax)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Amount and tax must be numbers")

    if math.isnan(amount) or math.isnan(tax) or math.isinf(amount) or math.isinf(tax):
        raise HTTPException(status_code=400, detail="Amount and tax must be valid finite numbers")

    if amount < 0 or tax < 0:
        raise HTTPException(status_code=400, detail="Amount and tax cannot be negative")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Enter what this cost")
    if amount > 100_000_000 or tax > 100_000_000:
        raise HTTPException(status_code=400, detail="That amount is unrealistically large")

    amount_m = money(amount)
    tax_m = money(tax)
    total_m = money(amount_m + tax_m)
    return amount_m, tax_m, total_m


def bill_to_employee_dict(db: Session, b: models.DBBill, include_chain: bool = False) -> Dict[str, Any]:
    """Serialize a bill for employee portal consumption with tenant isolation."""
    submitter = None
    if b.submitted_by:
        submitter = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == b.submitted_by,
            models.DBEmployee.client_id == b.client_id,
        ).first()

    order = None
    if b.purchase_order_id:
        order = db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.id == b.purchase_order_id,
            models.DBPurchaseOrder.client_id == b.client_id,
        ).first()

    row = {
        "id": b.id,
        "number": b.number,
        "vendor_name": b.vendor_name or "",
        "issue_date": b.issue_date or "",
        "due_date": b.due_date or "",
        "amount": b.amount or 0.0,
        "tax_amount": b.tax_amount or 0.0,
        "total": b.total or 0.0,
        "amount_paid": b.amount_paid or 0.0,
        "status": b.status or "Draft",
        "category": b.category or "general",
        "reference": b.reference or "",
        "notes": b.notes or "",
        "approval_status": b.approval_status or "none",
        "current_step": b.current_approval_step or 0,
        "rejection_reason": b.rejection_reason or "",
        "submitted_by": b.submitted_by,
        "submitted_by_name": employee_name(submitter) if submitter else "",
        "job_id": b.job_id,
        "job_name": job_label_for(db, b.job_id),
        "purchase_order_id": b.purchase_order_id,
        "purchase_order_number": order.number if order else "",
        "purchase_order_total": (order.total or 0.0) if order else 0.0,
        "over_order": bool(order and money(b.total or 0) > money(order.total or 0) + 0.005),
        "created_at": b.created_at or "",
    }
    if include_chain:
        row["chain"] = get_approval_chain_history("bill", b.id, db)
    return row


def employee_bill_or_404(db: Session, emp: models.DBEmployee, bill_id: int) -> models.DBBill:
    """Retrieve a bill ensuring tenant ownership."""
    if not emp:
        raise HTTPException(status_code=401, detail="Employee authentication required")
    bill = db.query(models.DBBill).filter(
        models.DBBill.id == bill_id,
        models.DBBill.client_id == emp.client_id,
    ).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


# -------------------------------------------------------------------------
# LEAVE & ENTITLEMENTS
# -------------------------------------------------------------------------

def working_days_between(
    start_date: Any,
    end_date: Any,
    settings: Optional[models.DBAttendanceSettings] = None,
) -> float:
    """Calculate working days between two dates under tenant attendance rules."""
    start = _parse_date(start_date) if isinstance(start_date, str) else start_date
    end = _parse_date(end_date) if isinstance(end_date, str) else end_date

    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()

    if not start or not end or end < start:
        return 0.0

    raw = getattr(settings, "working_days", None) if settings else None
    allowed_days = parse_working_days(raw or DEFAULT_WORKING_DAYS)

    days = 0
    cursor = start
    while cursor <= end:
        if cursor.isoweekday() in allowed_days:
            days += 1
        cursor += timedelta(days=1)
    return float(days)


def leave_balance_for(db: Session, emp: models.DBEmployee, for_year: Optional[int] = None) -> Dict[str, float]:
    """Calculate leave entitlement and remaining balance bounded to the calendar year."""
    if not emp:
        return {
            "annual_total": 0.0, "annual_taken": 0.0, "annual_pending": 0.0, "annual_remaining": 0.0,
            "sick_total": 0.0, "sick_taken": 0.0, "sick_pending": 0.0, "sick_remaining": 0.0,
        }

    year = for_year or datetime.now().year
    year_prefix = f"{year}-"

    leaves = db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.employee_id == emp.id,
        models.DBLeaveRequest.client_id == emp.client_id,
        models.DBLeaveRequest.start_date.like(f"{year_prefix}%"),
    ).all()

    def taken(kind: str, statuses: tuple) -> float:
        return round(sum(float(l.days or 0) for l in leaves if l.leave_type == kind and l.status in statuses), 2)

    annual_total = float(emp.annual_leave_entitlement if emp.annual_leave_entitlement is not None else 25.0)
    sick_total = float(emp.sick_leave_entitlement if emp.sick_leave_entitlement is not None else 10.0)

    annual_taken = taken("annual", ("approved",))
    annual_pending = taken("annual", ("pending",))
    sick_taken = taken("sick", ("approved",))
    sick_pending = taken("sick", ("pending",))

    return {
        "annual_total": annual_total,
        "annual_taken": annual_taken,
        "annual_pending": annual_pending,
        "annual_remaining": round(max(0.0, annual_total - annual_taken - annual_pending), 2),
        "sick_total": sick_total,
        "sick_taken": sick_taken,
        "sick_pending": sick_pending,
        "sick_remaining": round(max(0.0, sick_total - sick_taken - sick_pending), 2),
    }


def decide_leave(
    db: Session,
    client_id: int,
    leave: models.DBLeaveRequest,
    action: str,
    approver: str,
    request: Any = None,
) -> Dict[str, str]:
    """Approve or reject a leave request within the entitlement, with tenant isolation."""
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")

    if leave.client_id != client_id:
        raise HTTPException(status_code=403, detail="Access denied to this leave request")

    action_clean = (action or "").strip().lower()
    if action_clean not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
    if leave.status != "pending":
        raise HTTPException(status_code=409, detail=f"This request has already been {leave.status}")

    if action_clean == "approve":
        emp = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == leave.employee_id,
            models.DBEmployee.client_id == client_id,
        ).first()

        if emp:
            leave_year = int(str(leave.start_date)[:4]) if leave.start_date else datetime.now().year
            balance = leave_balance_for(db, emp, for_year=leave_year)
            leave_days = float(leave.days or 0)

            if leave.leave_type == "annual":
                available = balance["annual_total"] - balance["annual_taken"]
                if leave_days > available:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Approving this would exceed annual entitlement ({balance['annual_total']:g} days, {available:g} available)",
                    )
            elif leave.leave_type == "sick":
                available = balance["sick_total"] - balance["sick_taken"]
                if leave_days > available:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Approving this would exceed sick entitlement ({balance['sick_total']:g} days, {available:g} available)",
                    )

    leave.status = "approved" if action_clean == "approve" else "rejected"
    leave.approved_by = approver or "HR"
    leave.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    leave_type_label = (leave.leave_type or "leave").title()
    db.add(models.DBNotification(
        client_id=client_id,
        employee_id=leave.employee_id,
        title=f"Leave Request {leave.status.title()}",
        message=f"Your {leave_type_label} leave request for {leave.start_date} to {leave.end_date} has been {leave.status}.",
        type="success" if leave.status == "approved" else "warning",
    ))

    log_audit(
        db,
        client_id=client_id,
        action=f"leave_{leave.status}",
        entity_type="leave",
        entity_id=leave.id,
        entity_name=f"{leave.leave_type} ({leave.days}d)",
        details=f"Employee ID: {leave.employee_id}",
        request=request,
        user_type="employee",
        user_name=approver or "HR",
    )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save leave decision")

    return {"message": f"Leave {leave.status}", "status": leave.status}


# -------------------------------------------------------------------------
# GEOLOCATION & SITE GEOFENCING
# -------------------------------------------------------------------------

def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in meters between two coordinates using Haversine formula."""
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2) + (
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * (math.sin(dlng / 2) ** 2)
    )
    # Clamp to [0.0, 1.0] to eliminate domain errors
    a = max(0.0, min(1.0, a))
    return 2 * 6371000 * math.asin(math.sqrt(a))


def site_for_point(
    db: Session,
    client_id: int,
    lat: Any,
    lng: Any,
) -> Tuple[Optional[models.DBJob], Optional[float]]:
    """Return (job, distance_meters) for the nearest site whose circle the point is inside."""
    if lat is None or lng is None:
        return None, None

    try:
        user_lat = float(lat)
        user_lng = float(lng)
    except (ValueError, TypeError):
        return None, None

    best_fence = None
    best_dist: Optional[float] = None
    nearest_dist: Optional[float] = None

    fences = db.query(models.DBSiteGeofence).filter(
        models.DBSiteGeofence.client_id == client_id
    ).all()

    for g in fences:
        if g.lat is None or g.lng is None:
            continue
        # Skip unconfigured dummy fences
        if g.lat == 0.0 and g.lng == 0.0:
            continue

        d = distance_m(g.lat, g.lng, user_lat, user_lng)
        nearest_dist = d if nearest_dist is None else min(nearest_dist, d)
        radius = float(g.radius_m or 300.0)

        if d <= radius and (best_dist is None or d < best_dist):
            best_fence, best_dist = g, d

    if not best_fence:
        return None, round(nearest_dist, 1) if nearest_dist is not None else None

    job = db.query(models.DBJob).filter(
        models.DBJob.id == best_fence.job_id,
        models.DBJob.client_id == client_id,
    ).first()

    return job, round(best_dist, 1) if best_dist is not None else None


# -------------------------------------------------------------------------
# ROLE-BASED PROJECT ACCESS (RBAC)
# -------------------------------------------------------------------------

GLOBAL_PROJECT_ROLES = {
    "owner",
    "head_projects",
    "executive",
    "planning_billing",
    "accounts",
    "finance",
}


def accessible_job_ids_for(db: Session, emp: models.DBEmployee) -> Optional[Set[int]]:
    """Determine the job IDs an employee is authorized to access based on their role.

    Returns:
        - None: Unrestricted (sees all tenant projects).
        - Set[int]: Authorized job IDs.
        - set() (empty set): No project access.
    """
    if not emp:
        return set()

    role = (getattr(emp, "permission_role", "") or "staff").lower()
    org_role = (getattr(emp, "role", "") or "employee").lower()

    # 1. Global visibility: Executive / Finance / Head of Projects / Owner
    if (
        role in GLOBAL_PROJECT_ROLES
        or org_role == "executive"
        or employee_can(emp, "bills.view_all")
        or employee_can(emp, "reports.view")
        or employee_can(emp, "billing.manage")
    ):
        return None

    allowed_job_ids: Set[int] = set()

    # 2. Directly assigned sites
    assigned_rows = db.query(models.DBEmployeeSite.job_id).filter(
        models.DBEmployeeSite.employee_id == emp.id,
        models.DBEmployeeSite.client_id == emp.client_id,
    ).all()
    for row in assigned_rows:
        allowed_job_ids.add(row[0])

    # 3. Project Managers: Include projects where manager_id == emp.id
    if role in ("project_manager", "manager") or org_role in ("manager", "team_lead"):
        managed_jobs = db.query(models.DBJob.id).filter(
            models.DBJob.client_id == emp.client_id,
            models.DBJob.manager_id == emp.id,
        ).all()
        for j in managed_jobs:
            allowed_job_ids.add(j[0])

    # 4. Team Leads / Supervisors: Include sites assigned to their direct crew
    if org_role in ("team_lead", "manager") or role in ("construction", "supervisor"):
        report_ids = [
            r[0] for r in db.query(models.DBEmployee.id).filter(
                models.DBEmployee.client_id == emp.client_id,
                models.DBEmployee.reports_to == emp.id,
            ).all()
        ]
        if report_ids:
            crew_sites = db.query(models.DBEmployeeSite.job_id).filter(
                models.DBEmployeeSite.employee_id.in_(report_ids),
                models.DBEmployeeSite.client_id == emp.client_id,
            ).all()
            for row in crew_sites:
                allowed_job_ids.add(row[0])

    return allowed_job_ids


def employee_can_access_job(db: Session, emp: models.DBEmployee, job_id: int) -> bool:
    """Validate whether an employee can access a specific job."""
    if job_id is None:
        return True
    allowed = accessible_job_ids_for(db, emp)
    if allowed is None:
        exists = db.query(models.DBJob.id).filter(
            models.DBJob.id == job_id,
            models.DBJob.client_id == emp.client_id,
        ).first()
        return bool(exists)
    return job_id in allowed


def filter_jobs_for_employee(query, emp: models.DBEmployee, db: Session):
    """Apply the role-based filter to an existing SQLAlchemy DBJob query."""
    allowed = accessible_job_ids_for(db, emp)
    if allowed is not None:
        if not allowed:
            return query.filter(models.DBJob.id == -1)
        return query.filter(models.DBJob.id.in_(allowed))
    return query
