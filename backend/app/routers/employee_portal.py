"""The employee portal endpoints."""
import os
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, func as sqlfunc, or_
from sqlalchemy.orm import Session

from app import models
from app.core import passwords
from app.db import get_db

from app.constants.approvals import GONE_STATUSES
from app.constants.projects import JOB_CLOSED_STATUSES
from app.core.audit import log_audit
from app.core.auth import end_every_session, get_client_user, get_employee_user, require_employee_permission
from app.core.config import logger
from app.core.dates import _parse_date
from app.core.files import ALLOWED_DOCUMENT_EXTENSIONS, MAX_DOCUMENT_BYTES
from app.core.notifications import default_from_email, notify_employee, send_email_background
from app.core.permissions import DEFAULT_PERMISSION_ROLE, PERMISSION_ROLES, employee_can, permissions_for
from app.core.security import RESET_TOKEN_TTL_MINUTES, issue_reset_token, rate_limiter, upgrade_password_hash
from app.core.serials import allocate_bill_number, allocate_po_number
from app.schemas.auth import ForgotPasswordIn
from app.schemas.employee_portal import EmployeeDocumentUpload
from app.services.approvals import (
    approval_doc,
    bill_exceeds_its_order,
    decide_approval_step,
    get_approval_chain_history,
    start_approval,
)
from app.services.auth import reset_email_bodies
from app.services.employee_portal import (
    attendance_settings_for,
    bill_money_from,
    bill_to_employee_dict,
    decide_leave,
    employee_bill_or_404,
    is_working_day,
    leave_balance_for,
    should_auto_clock_in,
    site_for_point,
    working_days_between,
)
from app.services.hr import employee_name, employee_site_ids, request_to_dict, resolve_employee_job_id
from app.services.procurement import (
    apply_order_fields,
    purchase_order_or_404,
    purchase_order_to_dict,
    resolve_order_id,
    resolve_po_line_id,
)
from app.services.projects import job_label_for
from app.validators.common import validate_candidate_document


router = APIRouter()


@router.get("/api/my/login-history")
def my_login_history(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    logs = db.query(models.DBClientLoginLog).filter(
        models.DBClientLoginLog.client_id == client.id
    ).order_by(models.DBClientLoginLog.created_at.desc()).limit(limit).all()
    return [{
        "id": l.id, "email": l.email, "login_type": l.login_type,
        "ip_address": l.ip_address, "device_info": l.device_info,
        "status": l.status, "created_at": l.created_at,
    } for l in logs]


@router.post("/api/employee/forgot-password")
def employee_forgot_password(body: ForgotPasswordIn, background_tasks: BackgroundTasks,
                             request: Request, db: Session = Depends(get_db)):
    """Staff sign in with a password, so they are the ones who get locked out.
    Until now the only way back was to ask HR to set a new one by hand."""
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"emp_forgot:{ip}", max_requests=5, window=300):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    generic = {"message": "If that email has an account, a reset link is on its way."}
    email = (body.email or "").strip().lower()
    if not email:
        return generic

    emp = db.query(models.DBEmployee).filter(sqlfunc.lower(models.DBEmployee.email) == email).first()
    # Someone with no password set has never signed in; there is nothing to reset.
    if not emp or not emp.password_hash or emp.status == "terminated":
        return generic

    token = issue_reset_token(db, "employee", emp.id, ip)
    db.commit()

    base = (os.getenv("APP_BASE_URL") or str(request.base_url)).rstrip("/")
    link = f"{base}/reset-password.html?token={token}&portal=employee"
    who = f"{emp.first_name} {emp.last_name}".strip() or emp.email
    text_body, html_body = reset_email_bodies(link, who, RESET_TOKEN_TTL_MINUTES)
    from_email = default_from_email()

    background_tasks.add_task(
        send_email_background, emp.email, "Reset your password",
        text_body, f"Y ERP <{from_email}>", html_body, None, "", "",
        client_id=emp.client_id,
    )
    return generic


@router.post("/api/employee/auth/login")
def employee_login(request: Request, body: dict = None, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"emp_login:{ip}", max_requests=10, window=60):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    if not body or not body.get("email") or not body.get("password"):
        raise HTTPException(status_code=400, detail="Email and password required")
    email = body["email"].strip().lower()
    emp = db.query(models.DBEmployee).filter(sqlfunc.lower(models.DBEmployee.email) == email).first()
    if not emp:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not emp.password_hash:
        raise HTTPException(status_code=401, detail="Password not set. Contact your administrator.")
    if not passwords.verify_password(body["password"], emp.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    upgrade_password_hash(emp, "password_hash", body["password"])
    if emp.status in ("terminated",):
        raise HTTPException(status_code=403, detail="Account deactivated")
    # One identity per session. Signing in as staff ends any owner session in
    # this browser; without that the owner's rights survive underneath and
    # every permission check below is answered by the wrong person.
    request.session.pop('client_id', None)
    request.session.pop('member_id', None)
    request.session.pop('portal_user_id', None)
    request.session['employee_id'] = emp.id
    request.session['employee_client_id'] = emp.client_id
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    ip = request.client.host if request and request.client else ""
    device = body.get("device_info", "")
    lat = body.get("latitude", 0.0)
    lng = body.get("longitude", 0.0)
    loc_label = body.get("location_label", "")
    existing = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp.id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == emp.client_id,
    ).first()
    who = {"id": emp.id, "name": f"{emp.first_name} {emp.last_name}", "email": emp.email}
    if existing and existing.clock_in:
        return {"message": "Already clocked in today", "employee": who, "clock_in": existing.clock_in}

    settings = attendance_settings_for(db, emp.client_id)
    working_day = is_working_day(settings)
    if not should_auto_clock_in(settings):
        # Opening the portal on a day off - to read a payslip or upload a
        # document - is not a shift. The Clock In button is still there for
        # anyone who really is working.
        return {
            "message": "Signed in", "employee": who, "clock_in": "",
            "auto_clock_in": False, "is_working_day": working_day,
        }

    check_type = "remote"
    if lat and lng:
        if settings and settings.office_lat and settings.office_lng:
            from math import radians, cos, sin, asin, sqrt
            dlat = radians(lat - settings.office_lat)
            dlng = radians(lng - settings.office_lng)
            a = sin(dlat/2)**2 + cos(radians(settings.office_lat)) * cos(radians(lat)) * sin(dlng/2)**2
            dist = 2 * 6371000 * asin(sqrt(a))
            if dist <= settings.geofence_radius:
                check_type = "office"
            else:
                check_type = "field"
    site, _ = site_for_point(db, emp.client_id, lat, lng)
    if site:
        check_type = "site"
    att = models.DBAttendance(
        client_id=emp.client_id, employee_id=emp.id, date=today,
        clock_in=now_str, status="present", check_type=check_type,
        ip_address=ip, device_info=device,
        location_lat=lat, location_lng=lng,
        location_label=loc_label or (("%s %s" % (site.number, site.name)) if site else ""),
        job_id=site.id if site else None,
    )
    db.add(att)
    db.commit()
    return {
        "message": "Clocked in automatically",
        "employee": who,
        "clock_in": now_str, "check_type": check_type,
        "auto_clock_in": True, "is_working_day": working_day,
    }


@router.post("/api/employee/auth/logout")
def employee_logout(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        end_every_session(request)
        return {"message": "Not logged in"}
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client_id,
    ).first()
    hours = 0.0
    if att and att.clock_in and not att.clock_out:
        if att.is_on_break and att.break_start:
            try:
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                bs = datetime.strptime(today_str + " " + att.break_start, "%Y-%m-%d %H:%M:%S")
                att.break_minutes = (att.break_minutes or 0) + round((now - bs).total_seconds() / 60, 1)
            except Exception:
                pass
            att.is_on_break = False
            att.break_start = ""
        att.clock_out = now_str
        try:
            cin = datetime.strptime(today + " " + att.clock_in, "%Y-%m-%d %H:%M:%S")
            cout = datetime.strptime(today + " " + now_str, "%Y-%m-%d %H:%M:%S")
            raw_hours = (cout - cin).total_seconds() / 3600
            break_hours = (att.break_minutes or 0) / 60
            att.total_hours = round(raw_hours - break_hours, 2)
            hours = att.total_hours
            att.status = "completed"
        except Exception:
            pass
        db.commit()
    end_every_session(request)
    return {"message": "Logged out", "total_hours": hours, "break_minutes": att.break_minutes if att else 0}


@router.get("/api/employee/auth/me")
def employee_me(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    dept_name = ""
    if emp.department_id:
        dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == emp.department_id).first()
        dept_name = dept.name if dept else ""
    today = datetime.now().strftime("%Y-%m-%d")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp.id,
        models.DBAttendance.date == today,
    ).first()
    role_code = emp.permission_role or DEFAULT_PERMISSION_ROLE
    role_label = next((r["label"] for r in PERMISSION_ROLES if r["code"] == role_code),
                      role_code)
    return {
        "id": emp.id, "employee_id": emp.employee_id,
        "full_name": f"{emp.first_name} {emp.last_name}",
        "email": emp.email, "job_title": emp.job_title,
        "department": dept_name, "phone": emp.phone,
        "status": emp.status, "work_location": emp.work_location,
        # The single portal builds its navigation from these, so a person is
        # never shown a section they would be refused at.
        "permission_role": role_code,
        "permission_role_label": role_label,
        "permissions": sorted(permissions_for(emp)),
        "today_clock_in": att.clock_in if att else "",
        "today_clock_out": att.clock_out if att else "",
        "today_hours": att.total_hours if att else 0,
        "today_status": att.status if att else "absent",
        "today_is_on_break": att.is_on_break if att else False,
        "today_break_minutes": (att.break_minutes or 0) if att else 0,
    }


@router.post("/api/employee/attendance/clock-in")
def employee_clock_in(request: Request, body: dict = None, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    existing = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client_id,
    ).first()
    if existing and existing.clock_in:
        raise HTTPException(status_code=400, detail="Already clocked in today")
    ip = request.client.host if request and request.client else ""
    device = ""
    lat = lng = 0.0
    loc_label = ""
    if body:
        ip = body.get("ip_address", ip)
        device = body.get("device_info", "")
        lat = body.get("latitude", 0.0)
        lng = body.get("longitude", 0.0)
        loc_label = body.get("location_label", "")
    check_type = "manual"
    if lat and lng:
        settings = db.query(models.DBAttendanceSettings).filter(models.DBAttendanceSettings.client_id == client_id).first()
        if settings and settings.office_lat and settings.office_lng:
            from math import radians, cos, sin, asin, sqrt
            dlat = radians(lat - settings.office_lat)
            dlng = radians(lng - settings.office_lng)
            a = sin(dlat/2)**2 + cos(radians(settings.office_lat)) * cos(radians(lat)) * sin(dlng/2)**2
            dist = 2 * 6371000 * asin(sqrt(a))
            if dist <= settings.geofence_radius:
                check_type = "office"
            else:
                check_type = "field"

    # Flag lateness against the configured start time + grace period. The
    # settings already existed but nothing ever read them.
    status = "present"
    minutes_late = 0
    att_settings = db.query(models.DBAttendanceSettings).filter(
        models.DBAttendanceSettings.client_id == client_id
    ).first()
    if att_settings and att_settings.work_start:
        try:
            expected = datetime.strptime(f"{today} {att_settings.work_start}", "%Y-%m-%d %H:%M")
            actual = datetime.strptime(f"{today} {now_str}", "%Y-%m-%d %H:%M:%S")
            grace = att_settings.grace_minutes or 0
            late_by = (actual - expected).total_seconds() / 60
            if late_by > grace:
                status = "late"
                minutes_late = int(round(late_by))
        except (ValueError, TypeError):
            pass

    site, _ = site_for_point(db, client_id, lat, lng)
    if site:
        check_type = "site"
        loc_label = loc_label or "%s %s" % (site.number, site.name)
    if existing:
        # A row may already exist for today (e.g. marked absent); reuse it
        # rather than creating a duplicate for the same employee and date.
        existing.job_id = site.id if site else existing.job_id
        existing.clock_in = now_str
        existing.status = status
        existing.check_type = check_type
        existing.ip_address = ip
        existing.device_info = device
        existing.location_lat = lat
        existing.location_lng = lng
        existing.location_label = loc_label
        att = existing
    else:
        att = models.DBAttendance(
            client_id=client_id, employee_id=emp_id, date=today,
            clock_in=now_str, status=status, check_type=check_type,
            ip_address=ip, device_info=device,
            location_lat=lat, location_lng=lng, location_label=loc_label,
            job_id=site.id if site else None,
        )
        db.add(att)
    db.commit()
    return {
        "message": ("Clocked in at %s" % loc_label) if site else "Clocked in",
        "clock_in": now_str, "check_type": check_type,
        "status": status, "minutes_late": minutes_late,
        "site": ({"job_id": site.id, "name": "%s %s" % (site.number, site.name)} if site else None),
    }


@router.post("/api/employee/attendance/clock-out")
def employee_clock_out(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client_id,
    ).first()
    if not att or not att.clock_in:
        raise HTTPException(status_code=400, detail="No clock-in found for today")
    if att.clock_out:
        raise HTTPException(status_code=400, detail="Already clocked out")
    if att.is_on_break:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            break_start = datetime.strptime(today_str + " " + att.break_start, "%Y-%m-%d %H:%M:%S")
            att.break_minutes += round((now - break_start).total_seconds() / 60, 1)
        except Exception:
            pass
        att.is_on_break = False
        att.break_start = ""
    att.clock_out = now_str
    try:
        from datetime import timedelta
        cin = datetime.strptime(today + " " + att.clock_in, "%Y-%m-%d %H:%M:%S")
        cout = datetime.strptime(today + " " + now_str, "%Y-%m-%d %H:%M:%S")
        # A clock-out earlier than the clock-in means the shift ran past
        # midnight. Without this, total_hours went negative and silently
        # corrupted the hours that payroll reads.
        if cout < cin:
            cout += timedelta(days=1)
        raw_hours = (cout - cin).total_seconds() / 3600
        break_hours = (att.break_minutes or 0) / 60
        att.total_hours = max(0.0, round(raw_hours - break_hours, 2))
        settings = db.query(models.DBAttendanceSettings).filter(models.DBAttendanceSettings.client_id == client_id).first()
        if settings:
            try:
                wh_start = datetime.strptime(settings.work_start, "%H:%M")
                wh_end = datetime.strptime(settings.work_end, "%H:%M")
                work_hours = (wh_end - wh_start).total_seconds() / 3600
            except Exception:
                work_hours = 8.0
            if att.total_hours > work_hours:
                overtime = round(att.total_hours - work_hours, 2)
                # Respect the configured overtime ceiling so a forgotten
                # clock-out cannot book an unbounded overtime claim.
                cap = settings.max_overtime_hours or 0
                att.overtime_hours = min(overtime, cap) if cap > 0 else overtime
        att.status = "completed"
    except Exception:
        logger.exception("Failed to compute hours for attendance %s", att.id)
    db.commit()
    return {"message": "Clocked out", "total_hours": att.total_hours, "overtime_hours": att.overtime_hours, "break_minutes": att.break_minutes}


@router.post("/api/employee/attendance/break-start")
def employee_break_start(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M:%S")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client_id,
    ).first()
    if not att or not att.clock_in:
        raise HTTPException(status_code=400, detail="Not clocked in")
    if att.clock_out:
        raise HTTPException(status_code=400, detail="Already clocked out")
    if att.is_on_break:
        raise HTTPException(status_code=400, detail="Already on break")
    att.is_on_break = True
    att.break_start = now_str
    db.commit()
    return {"message": "Break started", "break_start": now_str}


@router.post("/api/employee/attendance/break-stop")
def employee_break_stop(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    today = datetime.now().strftime("%Y-%m-%d")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client_id,
    ).first()
    if not att or not att.is_on_break:
        raise HTTPException(status_code=400, detail="Not on break")
    try:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        break_start = datetime.strptime(today_str + " " + att.break_start, "%Y-%m-%d %H:%M:%S")
        elapsed = round((now - break_start).total_seconds() / 60, 1)
        att.break_minutes = (att.break_minutes or 0) + elapsed
    except Exception:
        logger.error(f"Failed to calculate break duration for attendance {att.id}")
    att.is_on_break = False
    att.break_start = ""
    db.commit()
    return {"message": "Break ended", "break_minutes": att.break_minutes}


@router.get("/api/employee/attendance/today")
def employee_today_attendance(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    today = datetime.now().strftime("%Y-%m-%d")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client_id,
    ).first()
    # The portal says why the Clock In button is waiting rather than filled in.
    working_day = is_working_day(attendance_settings_for(db, client_id))
    if not att:
        return {"clocked_in": False, "is_working_day": working_day}
    now_str = datetime.now().strftime("%H:%M:%S")
    elapsed = 0
    if att.clock_in and not att.clock_out:
        try:
            cin = datetime.strptime(today + " " + att.clock_in, "%Y-%m-%d %H:%M:%S")
            now_t = datetime.strptime(today + " " + now_str, "%Y-%m-%d %H:%M:%S")
            elapsed = round((now_t - cin).total_seconds() / 3600, 2)
            if att.is_on_break and att.break_start:
                bs = datetime.strptime(today + " " + att.break_start, "%Y-%m-%d %H:%M:%S")
                elapsed -= round((now_t - bs).total_seconds() / 3600, 2)
            elapsed -= (att.break_minutes or 0) / 60
            elapsed = round(max(0, elapsed), 2)
        except Exception:
            pass
    return {
        "clocked_in": bool(att.clock_in),
        "clock_in": att.clock_in,
        "clock_out": att.clock_out,
        "total_hours": att.total_hours,
        "is_on_break": att.is_on_break,
        "break_start": att.break_start,
        "break_minutes": att.break_minutes or 0,
        "overtime_hours": att.overtime_hours,
        "elapsed_hours": elapsed,
        "status": att.status,
    }


@router.get("/api/employee/dashboard")
def employee_dashboard(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    client_id = request.session.get('employee_client_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    from datetime import timedelta
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    records = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date >= thirty_days_ago,
    ).order_by(models.DBAttendance.date.desc()).limit(30).all()
    attendance = [{
        "date": r.date, "clock_in": r.clock_in, "clock_out": r.clock_out,
        "total_hours": r.total_hours, "status": r.status, "check_type": r.check_type,
        "break_minutes": r.break_minutes or 0, "overtime_hours": r.overtime_hours or 0,
        "is_on_break": r.is_on_break,
    } for r in records]
    payslips = db.query(models.DBPayslip).filter(models.DBPayslip.employee_id == emp_id).order_by(models.DBPayslip.created_at.desc()).limit(6).all()
    payslip_list = [{
        "number": p.number, "period_start": p.period_start, "period_end": p.period_end,
        "pay_date": p.pay_date, "net_pay": p.net_pay, "status": p.status,
    } for p in payslips]
    onboarding = db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.employee_id == emp_id).all()
    onboarding_list = [{
        "id": o.id, "title": o.title, "is_completed": o.is_completed,
        "category": o.category, "assigned_to": o.assigned_to,
    } for o in onboarding]
    ot_logs = db.query(models.DBOvertimeLog).filter(
        models.DBOvertimeLog.employee_id == emp_id,
        models.DBOvertimeLog.client_id == client_id,
    ).order_by(models.DBOvertimeLog.created_at.desc()).limit(10).all()
    overtime_list = [{
        "date": l.date, "hours": l.hours, "reason": l.reason,
        "announced_by": l.announced_by, "status": l.status,
    } for l in ot_logs]
    days_present = sum(1 for r in records if r.status in ("present", "completed"))
    total_hours = sum(max(r.total_hours, 0) for r in records if r.total_hours)
    total_breaks = sum(r.break_minutes or 0 for r in records)
    avg_hours = round(total_hours / max(len(records), 1), 2)
    return {
        "employee": {
            "full_name": f"{emp.first_name} {emp.last_name}", "email": emp.email,
            "job_title": emp.job_title, "salary": emp.salary, "pay_frequency": emp.pay_frequency,
            "bank_name": emp.bank_name, "bank_account": emp.bank_account, "tax_id": emp.tax_id,
        },
        "attendance_summary": {
            "days_present": days_present, "total_hours": round(total_hours, 2),
            "avg_hours": avg_hours, "total_break_minutes": round(total_breaks, 1),
        },
        "attendance": attendance,
        "payslips": payslip_list,
        "onboarding": onboarding_list,
        "overtime": overtime_list,
    }


@router.post("/api/employee/heartbeat")
def employee_heartbeat(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        return {"status": "no_session"}
    today = datetime.now().strftime("%Y-%m-%d")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
    ).first()
    if att and att.clock_in and not att.clock_out:
        try:
            cin = datetime.strptime(att.clock_in, "%H:%M:%S")
            now_time = datetime.strptime(datetime.now().strftime("%H:%M:%S"), "%H:%M:%S")
            elapsed = (now_time - cin).total_seconds() / 3600
            settings = db.query(models.DBAttendanceSettings).filter(models.DBAttendanceSettings.client_id == att.client_id).first()
            max_hours = settings.auto_clockout_hours if settings else 10.0
            if elapsed >= max_hours:
                att.clock_out = datetime.now().strftime("%H:%M:%S")
                att.total_hours = round(elapsed, 2)
                att.status = "completed"
                att.notes = "Auto clocked out"
                db.commit()
                return {"status": "auto_clocked_out", "total_hours": att.total_hours}
        except Exception:
            pass
    return {"status": "ok"}


@router.get("/api/employee/bills")
def employee_list_bills(request: Request, db: Session = Depends(get_db)):
    """What this person has raised - or everything, if their access allows."""
    emp = require_employee_permission(request, db, "bills.submit")
    query = db.query(models.DBBill).filter(models.DBBill.client_id == emp.client_id)
    if not employee_can(emp, "bills.view_all"):
        query = query.filter(models.DBBill.submitted_by == emp.id)
    bills = query.order_by(models.DBBill.id.desc()).limit(200).all()
    return {
        "bills": [bill_to_employee_dict(db, b) for b in bills],
        "can_view_all": employee_can(emp, "bills.view_all"),
        "can_pay": employee_can(emp, "bills.pay"),
    }


@router.get("/api/employee/bills/{bill_id}")
def employee_get_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    emp = require_employee_permission(request, db, "bills.submit")
    bill = employee_bill_or_404(db, emp, bill_id)
    if bill.submitted_by != emp.id and not employee_can(emp, "bills.view_all"):
        # Unless they are an approver on it, in which case they must be able to
        # read what they are being asked to sign off.
        is_approver = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "bill",
            models.DBApprovalChain.entity_id == bill.id,
            models.DBApprovalChain.approver_id == emp.id,
        ).first()
        if not is_approver:
            raise HTTPException(status_code=403, detail="That bill is not yours to view")
    return bill_to_employee_dict(db, bill, include_chain=True)


@router.post("/api/employee/bills")
def employee_create_bill(request: Request, body: dict = None,
                         db: Session = Depends(get_db)):
    """Raise a cost and send it up the reporting line."""
    emp = require_employee_permission(request, db, "bills.submit")
    body = body or {}
    vendor = (body.get("vendor_name") or "").strip()
    if not vendor:
        raise HTTPException(status_code=400, detail="Who is this owed to?")
    amount, tax, total = bill_money_from(body)

    bill = models.DBBill(
        client_id=emp.client_id,
        number=allocate_bill_number(db, emp.client_id),
        vendor_name=vendor,
        vendor_email=(body.get("vendor_email") or "").strip(),
        issue_date=body.get("issue_date") or datetime.now().strftime("%Y-%m-%d"),
        due_date=body.get("due_date") or "",
        amount=amount, tax_amount=tax, total=total,
        status="Draft",
        category=body.get("category") or "general",
        reference=(body.get("reference") or "").strip(),
        notes=(body.get("notes") or "").strip(),
        submitted_by=emp.id,
        approval_status="none",
        job_id=resolve_employee_job_id(db, emp, body.get("job_id")),
        purchase_order_id=resolve_order_id(db, emp.client_id, body.get("purchase_order_id")),
    )
    db.add(bill)
    db.flush()

    for li in (body.get("line_items") or [])[:50]:
        db.add(models.DBBillLineItem(
            bill_id=bill.id,
            description=(li.get("description") or "")[:500],
            po_line_id=resolve_po_line_id(db, bill.purchase_order_id,
                                          li.get("po_line_id")),
            qty=float(li.get("qty") or 1),
            price=float(li.get("price") or 0),
            tax_rate=li.get("tax_rate") or "0%",
        ))

    log_audit(db, emp.client_id, "bill_created", "bill", bill.id, bill.number,
              f"Raised by {employee_name(emp)}: {vendor}, {total}", request,
              user_type="employee", user_name=employee_name(emp))
    db.commit()
    db.refresh(bill)

    result = start_approval(db, emp.client_id, bill, "bill", emp.id, request,
                            actor=employee_name(emp))
    db.refresh(bill)
    return {"bill": bill_to_employee_dict(db, bill, include_chain=True), **result}


@router.put("/api/employee/bills/{bill_id}")
def employee_update_bill(bill_id: int, request: Request, body: dict = None,
                         db: Session = Depends(get_db)):
    """Correct a bill that was sent back. Only the person who raised it, and
    only while it is not sitting in somebody's approval queue."""
    emp = require_employee_permission(request, db, "bills.submit")
    bill = employee_bill_or_404(db, emp, bill_id)
    if bill.submitted_by != emp.id:
        raise HTTPException(status_code=403, detail="Only the person who raised this can change it")
    if bill.approval_status == "pending":
        raise HTTPException(status_code=409,
                            detail="This is with an approver. Ask them to send it back first.")
    if bill.approval_status == "approved":
        raise HTTPException(status_code=409, detail="This has been approved and cannot be changed")

    body = body or {}
    if "vendor_name" in body:
        vendor = (body.get("vendor_name") or "").strip()
        if not vendor:
            raise HTTPException(status_code=400, detail="Who is this owed to?")
        bill.vendor_name = vendor
    if "amount" in body or "tax_amount" in body:
        amount, tax, total = bill_money_from({
            "amount": body.get("amount", bill.amount),
            "tax_amount": body.get("tax_amount", bill.tax_amount),
        })
        bill.amount, bill.tax_amount, bill.total = amount, tax, total
    for field in ("vendor_email", "issue_date", "due_date", "category", "reference", "notes"):
        if field in body:
            setattr(bill, field, (body.get(field) or ""))
    if "job_id" in body:
        bill.job_id = resolve_employee_job_id(db, emp, body.get("job_id"))
    if "purchase_order_id" in body:
        bill.purchase_order_id = resolve_order_id(db, emp.client_id, body.get("purchase_order_id"))
    db.commit()
    return bill_to_employee_dict(db, bill, include_chain=True)


@router.post("/api/employee/bills/{bill_id}/submit")
def employee_resubmit_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """Send a corrected bill back up the line. The chain is rebuilt from the
    current reporting structure, so somebody who has changed manager since is
    not sent back to their old one."""
    emp = require_employee_permission(request, db, "bills.submit")
    bill = employee_bill_or_404(db, emp, bill_id)
    if bill.submitted_by != emp.id:
        raise HTTPException(status_code=403, detail="Only the person who raised this can send it")
    return start_approval(db, emp.client_id, bill, "bill", emp.id, request,
                          actor=employee_name(emp))


@router.post("/api/employee/purchase-orders")
def employee_create_purchase_order(request: Request, body: dict = None,
                                   db: Session = Depends(get_db)):
    """Raise an order and send it up the line, before the money is committed."""
    emp = require_employee_permission(request, db, "bills.submit")
    body = body or {}
    order = models.DBPurchaseOrder(
        client_id=emp.client_id, number=allocate_po_number(db, emp.client_id),
        status="Draft", submitted_by=emp.id, approval_status="none")
    apply_order_fields(db, emp.client_id, order, body)
    db.add(order)
    db.flush()
    for li in (body.get("line_items") or [])[:50]:
        db.add(models.DBPurchaseOrderLineItem(
            order_id=order.id, description=(li.get("description") or "")[:500],
            item_code=(li.get("item_code") or "")[:60],
            uom=(li.get("uom") or "")[:20],
            qty=float(li.get("qty") or 1), price=float(li.get("price") or 0),
            tax_rate=li.get("tax_rate") or "0%"))
    log_audit(db, emp.client_id, "purchase_order_created", "purchase_order", order.id,
              order.number, f"Raised by {employee_name(emp)}: {order.supplier_name}",
              request, user_type="employee", user_name=employee_name(emp))
    db.commit()
    db.refresh(order)
    result = start_approval(db, emp.client_id, order, "purchase_order", emp.id, request,
                            actor=employee_name(emp))
    db.refresh(order)
    return {"order": purchase_order_to_dict(db, order, include_chain=True), **result}


@router.get("/api/employee/purchase-orders")
def employee_list_purchase_orders(request: Request, db: Session = Depends(get_db)):
    emp = require_employee_permission(request, db, "bills.submit")
    query = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == emp.client_id)
    if not employee_can(emp, "bills.view_all"):
        query = query.filter(models.DBPurchaseOrder.submitted_by == emp.id)
    orders = query.order_by(models.DBPurchaseOrder.id.desc()).limit(200).all()
    return {"orders": [purchase_order_to_dict(db, o) for o in orders]}


@router.post("/api/employee/purchase-orders/{order_id}/submit")
def employee_resubmit_purchase_order(order_id: int, request: Request,
                                     db: Session = Depends(get_db)):
    emp = require_employee_permission(request, db, "bills.submit")
    order = purchase_order_or_404(db, emp.client_id, order_id)
    # Whoever raised it sends it; so may the purchase department, for a draft
    # that came off the budget or a quote comparison with nobody's name on it.
    if order.submitted_by != emp.id and not employee_can(emp, "purchase.manage"):
        raise HTTPException(status_code=403, detail="Only the person who raised this can send it")
    return start_approval(db, emp.client_id, order, "purchase_order", emp.id, request,
                          actor=employee_name(emp))


@router.get("/api/employee/jobs")
def employee_list_jobs(request: Request, db: Session = Depends(get_db)):
    """The jobs somebody can book time or costs against.

    Only live ones: a finished site should not be on the picker, because the
    cost of it landing there is a job that reopens months after it was closed.
    """
    emp = get_employee_user(request, db)
    query = db.query(models.DBJob).filter(
        models.DBJob.client_id == emp.client_id,
        ~models.DBJob.status.in_(JOB_CLOSED_STATUSES),
    )
    allowed = employee_site_ids(db, emp)
    if allowed is not None:
        query = query.filter(models.DBJob.id.in_(allowed or {0}))
    jobs = query.order_by(models.DBJob.id.desc()).all()
    return {"jobs": [{"id": j.id, "number": j.number, "name": j.name,
                      "customer_name": j.customer_name or "",
                      "site_address": j.site_address or ""} for j in jobs]}


@router.post("/api/employee/attendance/job")
def employee_set_attendance_job(request: Request, body: dict = None,
                                db: Session = Depends(get_db)):
    """Book today's hours to a job."""
    emp = get_employee_user(request, db)
    body = body or {}
    job_id = resolve_employee_job_id(db, emp, body.get("job_id"))
    on_date = body.get("date") or datetime.now().strftime("%Y-%m-%d")
    row = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp.id,
        models.DBAttendance.client_id == emp.client_id,
        models.DBAttendance.date == on_date,
    ).first()
    if not row:
        raise HTTPException(status_code=404,
                            detail="Nothing recorded for that day to book against a job.")
    row.job_id = job_id
    db.commit()
    return {"ok": True, "date": on_date, "job_id": job_id,
            "job_name": job_label_for(db, job_id)}


@router.get("/api/employee/approvals")
def employee_pending_approvals(request: Request, db: Session = Depends(get_db)):
    """What is waiting on this person to decide."""
    emp = require_employee_permission(request, db, "bills.approve")
    steps = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.client_id == emp.client_id,
        models.DBApprovalChain.approver_id == emp.id,
        models.DBApprovalChain.status == "pending",
    ).order_by(models.DBApprovalChain.id.desc()).all()

    waiting, later = [], []
    for s in steps:
        doc = approval_doc(db, s.entity_type, s.entity_id, emp.client_id)
        if not doc or doc.approval_status != "pending":
            continue
        submitter = db.query(models.DBEmployee).filter(
            models.DBEmployee.id == s.employee_id).first()
        row = {
            "step_id": s.id, "step": s.step,
            "entity_type": s.entity_type, "entity_id": doc.id,
            "number": getattr(doc, "number", str(doc.id)),
            "vendor_name": (getattr(doc, "vendor_name", "")
                            or getattr(doc, "supplier_name", "")
                            or getattr(doc, "to_contact", "")),
            "total": getattr(doc, "total", None) or getattr(doc, "due", 0.0),
            "category": getattr(doc, "category", ""),
            "notes": getattr(doc, "notes", ""),
            "issue_date": getattr(doc, "issue_date", ""),
            "submitted_by_name": employee_name(submitter),
            "current_step": doc.current_approval_step or 0,
            # An order commits money that has not been spent yet; a bill is
            # money already owed. An approver should be told which they are
            # looking at before they sign it.
            "kind": {"purchase_order": "Purchase order", "bill": "Bill",
                     "invoice": "Invoice"}.get(s.entity_type, s.entity_type),
            "job_name": job_label_for(db, getattr(doc, "job_id", None)),
            "over_order": bill_exceeds_its_order(db, doc, s.entity_type),
        }
        # Steps above the current rung are real, but not this person's turn yet.
        (waiting if s.step == (doc.current_approval_step or 0) else later).append(row)

    return {"pending": waiting, "upcoming": later}


@router.post("/api/employee/approvals/{step_id}/action")
def employee_approval_action(step_id: int, request: Request, body: dict = None,
                             db: Session = Depends(get_db)):
    """Approve or send back a document addressed to this approver."""
    emp = require_employee_permission(request, db, "bills.approve")
    body = body or {}
    step = db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.id == step_id,
        models.DBApprovalChain.client_id == emp.client_id,
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Approval step not found")
    if step.approver_id != emp.id:
        # Not "forbidden" in the abstract: this step belongs to someone else,
        # and saying so stops people hunting for a permission they do need.
        raise HTTPException(status_code=403, detail="This approval is addressed to somebody else")
    return decide_approval_step(db, step, body.get("action", ""), body.get("notes", ""),
                                request, emp.client_id, actor=employee_name(emp))


@router.get("/api/employee/approvals/history/{entity_type}/{entity_id}")
def employee_approval_history(entity_type: str, entity_id: int, request: Request,
                              db: Session = Depends(get_db)):
    emp = require_employee_permission(request, db, "bills.submit")
    if entity_type not in ("invoice", "bill"):
        raise HTTPException(status_code=400, detail="Unknown document type")
    doc = approval_doc(db, entity_type, entity_id, emp.client_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"history": get_approval_chain_history(entity_type, entity_id, db)}


@router.post("/api/employee/bills/{bill_id}/pay")
def employee_pay_bill(bill_id: int, request: Request, db: Session = Depends(get_db)):
    """Finance releases payment on an approved bill."""
    emp = require_employee_permission(request, db, "bills.pay")
    bill = employee_bill_or_404(db, emp, bill_id)
    if (bill.approval_status or "none") not in ("none", "approved", ""):
        raise HTTPException(
            status_code=403,
            detail=f"This bill is {bill.approval_status} and cannot be paid yet.")
    bill.amount_paid = bill.total or bill.amount or 0.0
    bill.status = "Paid"
    notify_employee(db, emp.client_id, bill.submitted_by, "Paid",
                    f"{bill.number} has been paid.")
    log_audit(db, emp.client_id, "bill_paid", "bill", bill.id, bill.number,
              f"Paid by {employee_name(emp)}: {bill.amount_paid}", request,
              user_type="employee", user_name=employee_name(emp))
    db.commit()
    return {"ok": True, "status": "Paid"}


@router.get("/api/employee/document-requests")
def employee_document_requests(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rows = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.employee_id == emp_id
    ).order_by(models.DBDocumentRequest.id.asc()).all()
    outstanding = sum(1 for r in rows if r.status in ("pending", "rejected"))
    return {
        "requests": [request_to_dict(r) for r in rows],
        "outstanding": outstanding,
        "complete": len(rows) > 0 and outstanding == 0,
        "limits": {
            "max_mb": MAX_DOCUMENT_BYTES // 1048576,
            "allowed": sorted(ALLOWED_DOCUMENT_EXTENSIONS),
        },
    }


@router.post("/api/employee/document-requests/{req_id}/upload")
def employee_upload_document(req_id: int, body: EmployeeDocumentUpload, request: Request,
                             db: Session = Depends(get_db)):
    """The employee satisfies one requirement. Reuses the same size and type
    checks as candidate uploads, since this is also a file from outside HR."""
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.id == req_id,
        models.DBDocumentRequest.employee_id == emp_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Document request not found")
    if row.status == "approved":
        raise HTTPException(status_code=409, detail="This document has already been approved")

    size = validate_candidate_document(body)

    # HR decides which documents expire; the employee supplies the date.
    expires_on = (body.expires_on or "").strip()
    if row.requires_expiry:
        if not expires_on:
            raise HTTPException(
                status_code=400,
                detail=f"{row.name} needs an expiry date. Enter the date shown on the document.",
            )
        parsed = _parse_date(expires_on)
        if not parsed:
            raise HTTPException(status_code=400, detail="Expiry date must be in YYYY-MM-DD format")
        if parsed <= datetime.now().date():
            raise HTTPException(
                status_code=400,
                detail="That document has already expired. Please upload a current one.",
            )
    else:
        # HR did not ask for a date on this one, so nothing the client sends is
        # kept. Storing it anyway would let a stale value from another upload
        # put a document into the expiring-soon queue nobody set a date for.
        expires_on = ""

    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()

    doc = models.DBDocument(
        client_id=row.client_id, employee_id=emp_id,
        title=row.name, doc_type=row.doc_type,
        file_name=body.file_name, file_type=body.file_type or "",
        file_size=size, file_data=body.file_data,
        uploaded_by=f"{emp.first_name} {emp.last_name}" if emp else "Employee",
    )
    db.add(doc)
    db.flush()

    row.document_id = doc.id
    row.expires_on = expires_on
    row.status = "submitted"
    row.submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.reviewed_at = ""
    row.reviewed_by = ""
    row.review_note = ""
    log_audit(db, row.client_id, "document_submitted", "document_request", row.id,
              row.name, f"Employee {emp_id}", request, user_type="employee",
              user_name=f"{emp.first_name} {emp.last_name}" if emp else "")
    db.commit()
    return {"message": f"{row.name} submitted for review", "status": row.status}


@router.get("/api/employee/goals")
def get_employee_goals(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    goals = db.query(models.DBEmployeeGoal).filter(models.DBEmployeeGoal.employee_id == emp_id).order_by(models.DBEmployeeGoal.created_at.desc()).all()
    return [{"id": g.id, "title": g.title, "description": g.description, "target_value": g.target_value, "current_value": g.current_value, "unit": g.unit, "category": g.category, "priority": g.priority, "start_date": g.start_date, "due_date": g.due_date, "status": g.status, "created_by": g.created_by} for g in goals]


@router.get("/api/employee/notifications")
def get_employee_notifications(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    notes = db.query(models.DBNotification).filter(models.DBNotification.employee_id == emp_id).order_by(models.DBNotification.created_at.desc()).limit(50).all()
    unread = db.query(models.DBNotification).filter(models.DBNotification.employee_id == emp_id, models.DBNotification.is_read == False).count()
    return {"notifications": [{"id": n.id, "title": n.title, "message": n.message, "type": n.type, "is_read": n.is_read, "link": n.link, "created_at": n.created_at} for n in notes], "unread_count": unread}


@router.patch("/api/employee/notifications/{note_id}/read")
def mark_notification_read(note_id: int, request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    note = db.query(models.DBNotification).filter(models.DBNotification.id == note_id, models.DBNotification.employee_id == emp_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Not found")
    note.is_read = True
    db.commit()
    return {"message": "Marked as read"}


@router.post("/api/employee/notifications/read-all")
def mark_all_notifications_read(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    db.query(models.DBNotification).filter(models.DBNotification.employee_id == emp_id, models.DBNotification.is_read == False).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}


@router.get("/api/employee/leave")
def get_employee_leave(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    leaves = db.query(models.DBLeaveRequest).filter(models.DBLeaveRequest.employee_id == emp_id).order_by(models.DBLeaveRequest.created_at.desc()).all()
    return {
        "requests": [{"id": l.id, "leave_type": l.leave_type, "start_date": l.start_date, "end_date": l.end_date, "days": l.days, "reason": l.reason, "status": l.status, "approved_by": l.approved_by, "created_at": l.created_at} for l in leaves],
        "balance": leave_balance_for(db, emp),
    }


@router.post("/api/employee/leave")
def request_leave(request: Request, body: dict, db: Session = Depends(get_db)):
    """Book leave. Days are computed server-side and checked against the
    remaining balance and existing bookings rather than trusted from the form."""
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    leave_type = (body.get("leave_type") or "annual").strip().lower()
    start_date = body.get("start_date", "")
    end_date = body.get("end_date", "")
    start, end = _parse_date(start_date), _parse_date(end_date)
    if not start or not end:
        raise HTTPException(status_code=400, detail="Start and end dates are required (YYYY-MM-DD)")
    if end < start:
        raise HTTPException(status_code=400, detail="End date cannot be before the start date")

    days = working_days_between(start_date, end_date)
    if days <= 0:
        raise HTTPException(status_code=400, detail="That range contains no working days")

    for existing in db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.employee_id == emp_id,
        models.DBLeaveRequest.status.in_(["pending", "approved"]),
    ).all():
        e_start, e_end = _parse_date(existing.start_date), _parse_date(existing.end_date)
        if e_start and e_end and start <= e_end and e_start <= end:
            raise HTTPException(
                status_code=409,
                detail=f"This overlaps an existing {existing.status} request ({existing.start_date} to {existing.end_date})",
            )

    balance = leave_balance_for(db, emp)
    if leave_type == "annual" and days > balance["annual_remaining"]:
        raise HTTPException(
            status_code=400,
            detail=f"Only {balance['annual_remaining']:g} day(s) of annual leave remaining; you requested {days:g}",
        )
    if leave_type == "sick" and days > balance["sick_remaining"]:
        raise HTTPException(
            status_code=400,
            detail=f"Only {balance['sick_remaining']:g} day(s) of sick leave remaining; you requested {days:g}",
        )

    leave = models.DBLeaveRequest(
        client_id=emp.client_id, employee_id=emp_id,
        leave_type=leave_type, start_date=start_date, end_date=end_date,
        days=days, reason=body.get("reason", ""),
    )
    db.add(leave)
    db.add(models.DBNotification(
        client_id=emp.client_id, employee_id=emp_id,
        title="Leave Request Submitted",
        message=f"Your {leave_type} leave request for {days:g} day(s) has been submitted.",
        type="info",
    ))
    db.commit()
    return {"message": "Leave request submitted", "days": days, "balance": leave_balance_for(db, emp)}


@router.get("/api/employee/documents")
def get_employee_documents(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    docs = db.query(models.DBDocument).filter(models.DBDocument.employee_id == emp_id).order_by(models.DBDocument.created_at.desc()).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "file_name": d.file_name, "uploaded_by": d.uploaded_by, "created_at": d.created_at} for d in docs]


@router.get("/api/employee/documents/{doc_id}/download")
def download_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    doc = db.query(models.DBDocument).filter(models.DBDocument.id == doc_id, models.DBDocument.employee_id == emp_id).first()
    if not doc or not doc.file_data:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"file_name": doc.file_name, "file_type": doc.file_type, "file_data": doc.file_data}


@router.get("/api/employee/profile")
def get_employee_profile(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == emp.department_id).first() if emp.department_id else None
    manager = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp.reports_to).first() if emp.reports_to else None
    team = db.query(models.DBEmployee).filter(models.DBEmployee.department_id == emp.department_id, or_(models.DBEmployee.status.is_(None), models.DBEmployee.status.notin_(GONE_STATUSES)), models.DBEmployee.id != emp_id).all() if emp.department_id else []
    goals = db.query(models.DBEmployeeGoal).filter(models.DBEmployeeGoal.employee_id == emp_id).all()
    goal_progress = 0
    if goals:
        goal_progress = round(sum(min(g.current_value / g.target_value * 100, 100) for g in goals) / len(goals), 1)
    return {
        "full_name": f"{emp.first_name} {emp.last_name}",
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "email": emp.email,
        "phone": emp.phone,
        "address": emp.address,
        "job_title": emp.job_title,
        "role": emp.role,
        "level": emp.level or "",
        "employment_type": emp.employment_type,
        "department": dept.name if dept else "",
        "department_id": emp.department_id,
        "manager": f"{manager.first_name} {manager.last_name}" if manager else "",
        "start_date": emp.start_date,
        "work_location": emp.work_location,
        "emergency_contact": emp.emergency_contact,
        "emergency_phone": emp.emergency_phone,
        "employee_id_code": emp.employee_id,
        "goals_count": len(goals),
        "goal_progress": goal_progress,
        "team": [{"id": t.id, "name": f"{t.first_name} {t.last_name}", "job_title": t.job_title, "email": t.email} for t in team],
    }


@router.get("/api/employee/analytics")
def get_employee_analytics(request: Request, days: int = 30, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from datetime import timedelta
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date >= start,
    ).order_by(models.DBAttendance.date.asc()).all()
    daily = []
    for r in records:
        daily.append({"date": r.date, "hours": r.total_hours or 0, "break": r.break_minutes or 0, "status": r.status, "check_type": r.check_type})
    total_hours = sum(d["hours"] for d in daily)
    days_present = len([d for d in daily if d["hours"] > 0])
    avg_hours = round(total_hours / max(days_present, 1), 1)
    late_days = 0
    for r in records:
        if r.clock_in:
            try:
                ci = datetime.strptime(r.clock_in, "%H:%M:%S")
                if ci.hour > 9 or (ci.hour == 9 and ci.minute > 15):
                    late_days += 1
            except: pass
    return {"daily": daily, "total_hours": round(total_hours, 1), "days_present": days_present, "avg_hours": avg_hours, "late_days": late_days, "period_days": days}


@router.get("/api/employee/team-presence")
def get_team_presence(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
    if not emp or not emp.department_id:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    team = db.query(models.DBEmployee).filter(models.DBEmployee.department_id == emp.department_id, or_(models.DBEmployee.status.is_(None), models.DBEmployee.status.notin_(GONE_STATUSES))).all()
    result = []
    for t in team:
        att = db.query(models.DBAttendance).filter(models.DBAttendance.employee_id == t.id, models.DBAttendance.date == today).first()
        is_online = att and att.clock_in and not att.clock_out
        result.append({
            "id": t.id, "name": f"{t.first_name} {t.last_name}", "job_title": t.job_title,
            "is_online": is_online, "clock_in": att.clock_in if att else "",
            "is_on_break": att.is_on_break if att else False,
        })
    return result


@router.get("/api/employee/weekly-chart")
def get_weekly_chart(request: Request, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from datetime import timedelta
    today = datetime.now()
    start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_days = []
    for i in range(7):
        d = (today - timedelta(days=today.weekday() - i)).strftime("%Y-%m-%d")
        att = db.query(models.DBAttendance).filter(models.DBAttendance.employee_id == emp_id, models.DBAttendance.date == d).first()
        week_days.append({"date": d, "day": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][i], "hours": att.total_hours if att else 0, "is_today": d == today.strftime("%Y-%m-%d")})
    return week_days


@router.post("/api/employee/goals/{goal_id}/update")
def update_goal_progress(goal_id: int, request: Request, body: dict, db: Session = Depends(get_db)):
    emp_id = request.session.get('employee_id')
    if not emp_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    goal = db.query(models.DBEmployeeGoal).filter(models.DBEmployeeGoal.id == goal_id, models.DBEmployeeGoal.employee_id == emp_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.current_value = body.get("current_value", goal.current_value)
    if goal.current_value >= goal.target_value:
        goal.status = "completed"
    db.commit()
    return {"message": "Goal updated"}


@router.post("/api/goals/assign-department")
def assign_department_goal(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body: body = {}
    dept_id = body.get("department_id")
    if not dept_id:
        raise HTTPException(status_code=400, detail="department_id required")
    dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == dept_id, models.DBDepartment.client_id == client.id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    employees = db.query(models.DBEmployee).filter(models.DBEmployee.department_id == dept_id, models.DBEmployee.client_id == client.id, models.DBEmployee.status == "active").all()
    created = []
    for emp in employees:
        goal = models.DBEmployeeGoal(
            client_id=client.id, employee_id=emp.id, department_id=dept_id,
            title=body.get("title", ""), description=body.get("description", ""),
            target_value=body.get("target_value", 100), current_value=0,
            unit=body.get("unit", "%"), category=body.get("category", "performance"),
            priority=body.get("priority", "medium"), start_date=body.get("start_date", ""),
            due_date=body.get("due_date", ""), created_by="HR",
        )
        db.add(goal)
        note = models.DBNotification(
            client_id=client.id, employee_id=emp.id,
            title="New Goal Assigned", message=f"HR has assigned you a new goal: {goal.title}",
            type="info",
        )
        db.add(note)
        created.append(emp.id)
    if not employees:
        dept_goal = models.DBDepartmentGoal(
            client_id=client.id, department_id=dept_id,
            title=body.get("title", ""), description=body.get("description", ""),
            target_value=body.get("target_value", 100),
            unit=body.get("unit", "%"), category=body.get("category", "performance"),
            priority=body.get("priority", "medium"), start_date=body.get("start_date", ""),
            due_date=body.get("due_date", ""), created_by="HR",
        )
        db.add(dept_goal)
        log_audit(db, client.id, "goal_saved_for_dept", "goal", None, body.get("title", ""), f"Dept: {dept.name} (pending)", request)
        db.commit()
        return {"message": f"Goal saved for {dept.name}. It will be assigned to employees when they join.", "count": 0, "department": dept.name, "pending": True}
    log_audit(db, client.id, "goal_assigned_dept", "goal", None, body.get("title", ""), f"Dept: {dept.name}, {len(created)} employees", request)
    db.commit()
    return {"message": f"Goal assigned to {len(created)} employees in {dept.name}", "count": len(created), "department": dept.name}


@router.get("/api/goals/department-pending")
def get_pending_department_goals(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    goals = db.query(models.DBDepartmentGoal).filter(
        models.DBDepartmentGoal.client_id == client.id,
        models.DBDepartmentGoal.is_assigned == False,
    ).all()
    result = []
    for g in goals:
        dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == g.department_id).first()
        result.append({
            "id": g.id, "department_id": g.department_id, "department_name": dept.name if dept else "",
            "title": g.title, "description": g.description,
            "target_value": g.target_value, "unit": g.unit,
            "category": g.category, "priority": g.priority,
            "due_date": g.due_date, "created_at": g.created_at,
        })
    return result


@router.get("/api/leave/requests")
def get_all_leave_requests(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    leaves = db.query(models.DBLeaveRequest).filter(models.DBLeaveRequest.client_id == client.id).order_by(models.DBLeaveRequest.created_at.desc()).all()
    result = []
    for l in leaves:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == l.employee_id).first()
        result.append({
            "id": l.id, "employee_id": l.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "",
            "leave_type": l.leave_type, "start_date": l.start_date, "end_date": l.end_date,
            "days": l.days, "reason": l.reason, "status": l.status,
            "approved_by": l.approved_by, "created_at": l.created_at,
        })
    return result


@router.post("/api/leave/requests/{leave_id}/action")
def action_leave_simple(leave_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body: body = {}
    leave = db.query(models.DBLeaveRequest).filter(models.DBLeaveRequest.id == leave_id, models.DBLeaveRequest.client_id == client.id).first()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    return decide_leave(db, client.id, leave, body.get("action"), body.get("approved_by", "HR"), request)


# THE SITE ENGINEER'S DAY
#
# Staff open the app on a phone, on a site, with a job to do. What they need
# first is not four statistics but their day: am I clocked in, is today's
# diary written, is anything open on my sites that should not be - and, for a
# supervisor, what is waiting for my signature. One call, the sites they are
# assigned to, nothing of anybody else's.
@router.get("/api/employee/today")
def employee_today(request: Request, db: Session = Depends(get_db)):
    emp = get_employee_user(request, db)
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    q = db.query(models.DBJob).filter(models.DBJob.client_id == emp.client_id,
                                      ~models.DBJob.status.in_(JOB_CLOSED_STATUSES))
    allowed = employee_site_ids(db, emp)
    if allowed is not None:
        q = q.filter(models.DBJob.id.in_(allowed or {0}))
    jobs = q.order_by(models.DBJob.number).limit(30).all()
    me = "employee:%d" % emp.id
    sites, waiting = [], []
    signoff = employee_can(emp, "site.signoff")
    ids = [j.id for j in jobs] or [0]
    cid = emp.client_id
    diaries = {d.job_id: d for d in db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.client_id == cid, models.DBSiteDiary.job_id.in_(ids),
        models.DBSiteDiary.diary_date == today).all()}
    permits_of = {}
    for p in db.query(models.DBWorkPermit).filter(models.DBWorkPermit.client_id == cid,
                                                  models.DBWorkPermit.job_id.in_(ids),
                                                  models.DBWorkPermit.status == "ACTIVE").all():
        permits_of.setdefault(p.job_id, []).append(p)
    incidents_of = dict(db.query(models.DBSafetyIncident.job_id, func.count(models.DBSafetyIncident.id)).filter(
        models.DBSafetyIncident.client_id == cid, models.DBSafetyIncident.job_id.in_(ids),
        models.DBSafetyIncident.status == "OPEN").group_by(models.DBSafetyIncident.job_id).all())
    inspections_of = dict(db.query(models.DBInspection.job_id, func.count(models.DBInspection.id)).filter(
        models.DBInspection.client_id == cid, models.DBInspection.job_id.in_(ids),
        ~models.DBInspection.result.in_(("PASSED", "FAILED"))).group_by(models.DBInspection.job_id).all())
    threads = db.query(models.DBProjectThread.id, models.DBProjectThread.job_id).filter(
        models.DBProjectThread.client_id == cid, models.DBProjectThread.job_id.in_(ids),
        models.DBProjectThread.closed.is_(False)).all()
    unread_of = {}
    if threads:
        tids = [t.id for t in threads]
        read_upto = dict(db.query(models.DBThreadRead.thread_id, models.DBThreadRead.last_read_id).filter(
            models.DBThreadRead.thread_id.in_(tids), models.DBThreadRead.reader == me).all())
        job_of_thread = {t.id: t.job_id for t in threads}
        for tid, mid in db.query(models.DBProjectMessage.thread_id, models.DBProjectMessage.id).filter(
                models.DBProjectMessage.thread_id.in_(tids), models.DBProjectMessage.author != me,
                models.DBProjectMessage.deleted.is_(False)).all():
            if mid > (read_upto.get(tid) or 0):
                unread_of[job_of_thread[tid]] = unread_of.get(job_of_thread[tid], 0) + 1
    drafts_of = dict(db.query(models.DBSiteDiary.job_id, func.count(models.DBSiteDiary.id)).filter(
        models.DBSiteDiary.client_id == cid, models.DBSiteDiary.job_id.in_(ids),
        models.DBSiteDiary.status == "DRAFT", models.DBSiteDiary.diary_date < today).group_by(
            models.DBSiteDiary.job_id).all()) if signoff else {}
    for j in jobs:
        diary = diaries.get(j.id)
        permits = permits_of.get(j.id, [])
        overdue = [p for p in permits if (p.valid_to or "") and p.valid_to[:16] < now]
        incidents = incidents_of.get(j.id, 0)
        inspections = inspections_of.get(j.id, 0)
        unread = unread_of.get(j.id, 0)
        sites.append({"job_id": j.id, "number": j.number or "", "name": j.name or "",
                      "diary": ({"id": diary.id, "status": diary.status} if diary else None),
                      "permits_live": len(permits), "permits_overdue": len(overdue),
                      "incidents_open": incidents, "inspections_open": inspections, "unread": unread})
        if signoff:
            drafts = drafts_of.get(j.id, 0)
            if drafts:
                waiting.append({"kind": "diary", "job_id": j.id, "view": "diary-view",
                                "text": "%d diary day%s on %s to sign off" % (drafts, "" if drafts == 1 else "s", j.name)})
            if overdue:
                waiting.append({"kind": "permits", "job_id": j.id, "view": "safety-view",
                                "text": "%d permit%s on %s ran out and %s still open" % (
                                    len(overdue), "" if len(overdue) == 1 else "s", j.name,
                                    "is" if len(overdue) == 1 else "are")})
            if incidents:
                waiting.append({"kind": "incidents", "job_id": j.id, "view": "safety-view",
                                "text": "%d incident%s on %s to close" % (incidents, "" if incidents == 1 else "s", j.name)})
    att = db.query(models.DBAttendance).filter(models.DBAttendance.client_id == emp.client_id,
                                               models.DBAttendance.employee_id == emp.id,
                                               models.DBAttendance.date == today).first()
    at_site = None
    if att and att.job_id:
        j = db.query(models.DBJob).filter(models.DBJob.id == att.job_id).first()
        at_site = j.name if j else None
    return {"date": today, "name": ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip(),
            "clock": {"in": (att.clock_in or "")[:5] if att else "", "out": (att.clock_out or "")[:5] if att else "",
                      "site": at_site or ""},
            "sites": sites, "waiting": waiting}
