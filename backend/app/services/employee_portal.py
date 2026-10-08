"""The rules and workings behind the employee portal endpoints."""
from datetime import datetime

from fastapi import HTTPException

from app import models

from app.core.audit import log_audit
from app.core.currency import money
from app.core.dates import DEFAULT_WORKING_DAYS, _parse_date, parse_working_days


def attendance_settings_for(db, client_id):
    return db.query(models.DBAttendanceSettings).filter(
        models.DBAttendanceSettings.client_id == client_id
    ).first()


def is_working_day(settings, on_date=None):
    on_date = on_date or datetime.now().date()
    raw = getattr(settings, "working_days", None) if settings else None
    return on_date.isoweekday() in parse_working_days(raw or DEFAULT_WORKING_DAYS)


def should_auto_clock_in(settings, on_date=None):
    """Signing in only starts a shift on a working day, and only if the tenant
    wants sign-in to count at all. Someone opening the portal on a Sunday to
    check a document is not at work."""
    if settings is not None and not bool(getattr(settings, "auto_clock_in", True)):
        return False
    return is_working_day(settings, on_date)


def bill_money_from(body) -> tuple:
    """Amount, tax and total off a submitted form.

    The total is recomputed rather than trusted: it is the figure the approver
    reads and the figure finance pays, and a client that sends its own total
    can make those two disagree with the lines above them.
    """
    try:
        amount = float(body.get("amount") or 0)
        tax = float(body.get("tax_amount") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Amount and tax must be numbers")
    if amount < 0 or tax < 0:
        raise HTTPException(status_code=400, detail="Amount and tax cannot be negative")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Enter what this cost")
    if amount > 100_000_000:
        raise HTTPException(status_code=400, detail="That amount is unrealistically large")
    return money(amount), money(tax), money(amount + tax)


def bill_to_employee_dict(db, b, include_chain=False):
    submitter = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == b.submitted_by).first() if b.submitted_by else None
    order = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == b.purchase_order_id).first() if b.purchase_order_id else None
    row = {
        "id": b.id, "number": b.number, "vendor_name": b.vendor_name or "",
        "issue_date": b.issue_date or "", "due_date": b.due_date or "",
        "amount": b.amount or 0.0, "tax_amount": b.tax_amount or 0.0,
        "total": b.total or 0.0, "amount_paid": b.amount_paid or 0.0,
        "status": b.status or "Draft", "category": b.category or "general",
        "reference": b.reference or "", "notes": b.notes or "",
        "approval_status": b.approval_status or "none",
        "current_step": b.current_approval_step or 0,
        "rejection_reason": b.rejection_reason or "",
        "submitted_by": b.submitted_by, "submitted_by_name": employee_name(submitter),
        "job_id": b.job_id, "job_name": job_label_for(db, b.job_id),
        "purchase_order_id": b.purchase_order_id,
        "purchase_order_number": order.number if order else "",
        "purchase_order_total": (order.total or 0.0) if order else 0.0,
        # The whole reason for raising an order first: did the bill come in
        # higher than what was agreed?
        "over_order": bool(order and money(b.total or 0) > money(order.total or 0) + 0.005),
        "created_at": b.created_at or "",
    }
    if include_chain:
        row["chain"] = get_approval_chain_history("bill", b.id, db)
    return row


def employee_bill_or_404(db, emp, bill_id):
    bill = db.query(models.DBBill).filter(
        models.DBBill.id == bill_id,
        models.DBBill.client_id == emp.client_id,
    ).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def working_days_between(start_date, end_date) -> float:
    """Inclusive weekday count. Leave is booked in working days, so a Mon-Fri
    request is 5 days, not the 7 a raw date subtraction would give."""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if not start or not end or end < start:
        return 0.0
    from datetime import timedelta
    days = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return float(days)


def leave_balance_for(db, emp) -> dict:
    """Entitlement and usage per leave type for one employee."""
    leaves = db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.employee_id == emp.id
    ).all()

    def taken(kind, statuses):
        return round(sum(l.days or 0 for l in leaves if l.leave_type == kind and l.status in statuses), 2)

    annual_total = emp.annual_leave_entitlement if emp.annual_leave_entitlement is not None else 25.0
    sick_total = emp.sick_leave_entitlement if emp.sick_leave_entitlement is not None else 10.0
    annual_taken = taken("annual", ("approved",))
    annual_pending = taken("annual", ("pending",))
    sick_taken = taken("sick", ("approved",))
    return {
        "annual_total": annual_total,
        "annual_taken": annual_taken,
        "annual_pending": annual_pending,
        "annual_remaining": round(annual_total - annual_taken - annual_pending, 2),
        "sick_total": sick_total,
        "sick_taken": sick_taken,
        "sick_remaining": round(sick_total - sick_taken, 2),
    }


def decide_leave(db, client_id, leave, action, approver, request):
    """Approve or turn down a leave request, within the entitlement."""
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    action = (action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
    if leave.status != "pending":
        raise HTTPException(status_code=409, detail=f"This request has already been {leave.status}")

    if action == "approve":
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == leave.employee_id).first()
        if emp:
            balance = leave_balance_for(db, emp)
            # Pending days include this request, so compare against taken only.
            if leave.leave_type == "annual" and (leave.days or 0) > (balance["annual_total"] - balance["annual_taken"]):
                raise HTTPException(
                    status_code=400,
                    detail=f"Approving this would exceed the annual entitlement ({balance['annual_total']:g} days)",
                )
            if leave.leave_type == "sick" and (leave.days or 0) > (balance["sick_total"] - balance["sick_taken"]):
                raise HTTPException(
                    status_code=400,
                    detail=f"Approving this would exceed the sick leave entitlement ({balance['sick_total']:g} days)",
                )

    leave.status = "approved" if action == "approve" else "rejected"
    leave.approved_by = approver or "HR"
    leave.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.add(models.DBNotification(
        client_id=client.id, employee_id=leave.employee_id,
        title=f"Leave Request {leave.status.title()}",
        message=f"Your {leave.leave_type} leave request for {leave.start_date} to {leave.end_date} has been {leave.status}.",
        type="success" if leave.status == "approved" else "warning",
    ))
    log_audit(db, client.id, f"leave_{leave.status}", "leave", leave.id, f"{leave.leave_type} ({leave.days}d)", f"Employee ID: {leave.employee_id}", request)
    db.commit()
    return {"message": f"Leave {leave.status}", "status": leave.status}


# SITE LOCATIONS FOR ATTENDANCE
#
# The office was the only place a clock-in was checked against, so a site
# engineer on a site twenty kilometres out read as "field" every day and his
# hours landed on no project. Each project can carry its site's position and
# how far from it still counts as on site; a clock-in inside one is tagged to
# that project, and one outside every site says so.
def distance_m(lat1, lng1, lat2, lng2):
    from math import radians, cos, sin, asin, sqrt
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def site_for_point(db, client_id, lat, lng):
    """(job, metres) for the nearest site whose circle the point is inside,
    or (None, metres to the nearest site) when it is inside none."""
    if not (lat and lng):
        return None, None
    best, best_d, nearest = None, None, None
    for g in db.query(models.DBSiteGeofence).filter(models.DBSiteGeofence.client_id == client_id).all():
        d = distance_m(g.lat, g.lng, lat, lng)
        nearest = d if nearest is None else min(nearest, d)
        if d <= (g.radius_m or 300) and (best_d is None or d < best_d):
            best, best_d = g, d
    if not best:
        return None, nearest
    job = db.query(models.DBJob).filter(models.DBJob.id == best.job_id).first()
    return job, best_d


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.approvals import get_approval_chain_history
from app.services.hr import employee_name
from app.services.projects import job_label_for
