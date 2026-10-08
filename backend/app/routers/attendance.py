"""The attendance endpoints."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.auth import get_client_user, require_erp_read
from app.core.dates import DEFAULT_WORKING_DAYS
from app.validators.common import clean_working_days


router = APIRouter()


@router.post("/api/attendance/clock-in")
def clock_in(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body or not body.get("employee_id"):
        raise HTTPException(status_code=400, detail="employee_id required")
    emp_id = body["employee_id"]
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    today = datetime.now().strftime("%Y-%m-%d")
    existing = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client.id,
    ).first()
    if existing:
        if existing.clock_in:
            raise HTTPException(status_code=400, detail="Already clocked in today")
        existing.clock_in = datetime.now().strftime("%H:%M:%S")
        existing.status = "present"
        db.commit()
        return {"message": "Clocked in", "clock_in": existing.clock_in}
    att = models.DBAttendance(
        client_id=client.id, employee_id=emp_id, date=today,
        clock_in=datetime.now().strftime("%H:%M:%S"), status="present",
    )
    db.add(att)
    db.commit()
    return {"message": "Clocked in", "clock_in": att.clock_in}


@router.post("/api/attendance/clock-out")
def clock_out(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body or not body.get("employee_id"):
        raise HTTPException(status_code=400, detail="employee_id required")
    emp_id = body["employee_id"]
    today = datetime.now().strftime("%Y-%m-%d")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp_id,
        models.DBAttendance.date == today,
        models.DBAttendance.client_id == client.id,
    ).first()
    if not att or not att.clock_in:
        raise HTTPException(status_code=400, detail="Not clocked in today")
    if att.clock_out:
        raise HTTPException(status_code=400, detail="Already clocked out today")
    att.clock_out = datetime.now().strftime("%H:%M:%S")
    try:
        cin = datetime.strptime(att.clock_in, "%H:%M:%S")
        cout = datetime.strptime(att.clock_out, "%H:%M:%S")
        att.total_hours = round((cout - cin).total_seconds() / 3600, 2)
    except Exception:
        att.total_hours = 0.0
    att.status = "completed"
    db.commit()
    return {"message": "Clocked out", "clock_out": att.clock_out, "total_hours": att.total_hours}


@router.get("/api/attendance")
def get_attendance(request: Request, employee_id: int = 0, date: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBAttendance).filter(models.DBAttendance.client_id == client.id)
    if employee_id:
        query = query.filter(models.DBAttendance.employee_id == employee_id)
    if date:
        query = query.filter(models.DBAttendance.date == date)
    records = query.order_by(models.DBAttendance.date.desc(), models.DBAttendance.clock_in.desc()).limit(200).all()
    result = []
    for a in records:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == a.employee_id).first()
        result.append({
            "id": a.id, "employee_id": a.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "",
            "employee_email": emp.email if emp else "",
            "date": a.date, "clock_in": a.clock_in, "clock_out": a.clock_out,
            "total_hours": a.total_hours, "status": a.status, "notes": a.notes,
            "created_at": a.created_at,
        })
    return result


@router.get("/api/attendance/today")
def get_today_attendance(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    today = datetime.now().strftime("%Y-%m-%d")
    records = db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client.id,
        models.DBAttendance.date == today,
    ).all()
    result = []
    for a in records:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == a.employee_id).first()
        result.append({
            "id": a.id, "employee_id": a.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "",
            "date": a.date, "clock_in": a.clock_in, "clock_out": a.clock_out,
            "total_hours": a.total_hours, "status": a.status,
        })
    return result


@router.get("/api/attendance/stats")
def get_attendance_stats(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    today = datetime.now().strftime("%Y-%m-%d")
    total_employees = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status.in_(["active", "onboarding"]),
    ).count()
    today_records = db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client.id,
        models.DBAttendance.date == today,
    ).all()
    present = sum(1 for r in today_records if r.status in ("present", "completed"))
    absent = total_employees - present
    avg_hours = 0.0
    if today_records:
        avg_hours = round(sum(r.total_hours for r in today_records) / len(today_records), 2)
    return {
        "total_employees": total_employees,
        "present": present,
        "absent": max(0, absent),
        "avg_hours": avg_hours,
        "date": today,
    }


@router.get("/api/attendance/live")
def get_live_attendance(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    today = datetime.now().strftime("%Y-%m-%d")
    all_active = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status.in_(["active", "onboarding"]),
    ).all()
    today_records = db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client.id,
        models.DBAttendance.date == today,
    ).all()
    record_map = {r.employee_id: r for r in today_records}
    result = []
    for emp in all_active:
        rec = record_map.get(emp.id)
        dept_name = ""
        if emp.department_id:
            dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == emp.department_id).first()
            dept_name = dept.name if dept else ""
        result.append({
            "id": emp.id, "employee_id": emp.employee_id,
            "full_name": f"{emp.first_name} {emp.last_name}",
            "email": emp.email, "job_title": emp.job_title,
            "department": dept_name, "status": emp.status,
            "clock_in": rec.clock_in if rec else "",
            "clock_out": rec.clock_out if rec else "",
            "total_hours": rec.total_hours if rec else 0,
            "attendance_status": rec.status if rec else "absent",
            "location_label": rec.location_label if rec else "",
            "ip_address": rec.ip_address if rec else "",
            "check_type": rec.check_type if rec else "",
        })
    return result


@router.get("/api/attendance/analytics")
def get_attendance_analytics(request: Request, days: int = 30, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    from datetime import timedelta
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    records = db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client.id,
        models.DBAttendance.date >= start_date,
    ).all()
    total_employees = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status.in_(["active", "onboarding"]),
    ).count()
    daily_stats = {}
    late_count = 0
    overtime_count = 0
    total_hours_all = 0
    remote_count = 0
    for r in records:
        d = r.date
        if d not in daily_stats:
            daily_stats[d] = {"present": 0, "absent": 0, "hours": 0}
        daily_stats[d]["present"] += 1
        daily_stats[d]["hours"] += r.total_hours or 0
        total_hours_all += r.total_hours or 0
        if r.clock_in and r.clock_in > "09:15":
            late_count += 1
        if r.overtime_hours and r.overtime_hours > 0:
            overtime_count += 1
        if r.location_label and "remote" in r.location_label.lower():
            remote_count += 1
    days_with_data = max(len(daily_stats), 1)
    for d in daily_stats:
        daily_stats[d]["absent"] = total_employees - daily_stats[d]["present"]
    return {
        "period_days": days,
        "total_records": len(records),
        "avg_daily_hours": round(total_hours_all / max(len(records), 1), 2),
        "late_arrivals": late_count,
        "overtime_sessions": overtime_count,
        "remote_sessions": remote_count,
        "avg_attendance_rate": round(sum(d["present"] for d in daily_stats.values()) / (days_with_data * max(total_employees, 1)) * 100, 1),
        "daily": dict(sorted(daily_stats.items())),
    }


@router.get("/api/attendance/export")
def export_attendance(request: Request, start_date: str = "", end_date: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBAttendance).filter(models.DBAttendance.client_id == client.id)
    if start_date:
        query = query.filter(models.DBAttendance.date >= start_date)
    if end_date:
        query = query.filter(models.DBAttendance.date <= end_date)
    records = query.order_by(models.DBAttendance.date.desc()).limit(1000).all()
    rows = []
    for r in records:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == r.employee_id).first()
        rows.append({
            "Employee": f"{emp.first_name} {emp.last_name}" if emp else "",
            "Email": emp.email if emp else "",
            "Date": r.date, "Clock In": r.clock_in, "Clock Out": r.clock_out,
            "Hours": r.total_hours, "Status": r.status, "Type": r.check_type,
            "Location": r.location_label, "IP": r.ip_address,
            "Overtime": r.overtime_hours, "Notes": r.notes,
        })
    return rows


@router.post("/api/attendance/overtime/announce")
def announce_overtime(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body or not body.get("employee_id") or not body.get("hours"):
        raise HTTPException(status_code=400, detail="employee_id and hours required")
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == body["employee_id"],
        models.DBEmployee.client_id == client.id,
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    date = body.get("date", datetime.now().strftime("%Y-%m-%d"))
    hours = float(body["hours"])
    reason = body.get("reason", "")
    att = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp.id,
        models.DBAttendance.date == date,
        models.DBAttendance.client_id == client.id,
    ).first()
    if att:
        att.overtime_hours = hours
        att.overtime_announced = True
        att.overtime_announced_by = client.company_name or client.contact_name or "HR"
    log = models.DBOvertimeLog(
        client_id=client.id, employee_id=emp.id, date=date,
        hours=hours, reason=reason,
        announced_by=client.company_name or client.contact_name or "HR",
        status="announced",
    )
    db.add(log)
    db.commit()
    return {"message": f"Overtime of {hours}h announced for {emp.first_name} {emp.last_name}"}


@router.get("/api/attendance/overtime/logs")
def get_overtime_logs(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    logs = db.query(models.DBOvertimeLog).filter(
        models.DBOvertimeLog.client_id == client.id
    ).order_by(models.DBOvertimeLog.created_at.desc()).limit(100).all()
    result = []
    for l in logs:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == l.employee_id).first()
        result.append({
            "id": l.id, "employee_id": l.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}" if emp else "",
            "date": l.date, "hours": l.hours, "reason": l.reason,
            "announced_by": l.announced_by, "status": l.status,
            "created_at": l.created_at,
        })
    return result


@router.put("/api/attendance/settings")
def update_attendance_settings(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    settings = db.query(models.DBAttendanceSettings).filter(models.DBAttendanceSettings.client_id == client.id).first()
    if not settings:
        settings = models.DBAttendanceSettings(client_id=client.id)
        db.add(settings)
    if body:
        for key, val in body.items():
            if not hasattr(settings, key) or key in ("id", "client_id", "created_at"):
                continue
            if key == "working_days":
                # Normalised, so a stray value cannot leave a tenant with no
                # working days at all.
                val = clean_working_days(val)
            elif key == "auto_clock_in":
                val = bool(val)
            setattr(settings, key, val)
    db.commit()
    return {"message": "Settings saved"}


@router.get("/api/attendance/settings")
def get_attendance_settings(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    settings = db.query(models.DBAttendanceSettings).filter(models.DBAttendanceSettings.client_id == client.id).first()
    if not settings:
        return {
            "office_name": "Head Office", "office_lat": 0.0, "office_lng": 0.0,
            "geofence_radius": 200.0, "work_start": "09:00", "work_end": "17:30",
            "grace_minutes": 15.0, "auto_clockout_hours": 10.0, "max_overtime_hours": 4.0,
            "allow_remote": True, "require_location": True,
            "working_days": DEFAULT_WORKING_DAYS, "auto_clock_in": True,
        }
    return {
        "office_name": settings.office_name, "office_lat": settings.office_lat,
        "office_lng": settings.office_lng, "geofence_radius": settings.geofence_radius,
        "work_start": settings.work_start, "work_end": settings.work_end,
        "grace_minutes": settings.grace_minutes,
        "auto_clockout_hours": settings.auto_clockout_hours,
        "max_overtime_hours": settings.max_overtime_hours,
        "allow_remote": settings.allow_remote, "require_location": settings.require_location,
        "working_days": clean_working_days(settings.working_days),
        "auto_clock_in": bool(settings.auto_clock_in),
    }


@router.get("/api/attendance/by-site")
def attendance_by_site(request: Request, day: str = "", db: Session = Depends(get_db)):
    """Who clocked in where on a day: each site with the people inside its
    circle, and anybody who clocked in outside every site."""
    client = require_erp_read(request, db)
    day = (day or date.today().isoformat())[:10]
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    fenced = {g.job_id: g for g in db.query(models.DBSiteGeofence).filter(
        models.DBSiteGeofence.client_id == client.id).all()}
    people = {e.id: e for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).all()}
    sites, elsewhere = {}, []
    for a in db.query(models.DBAttendance).filter(models.DBAttendance.client_id == client.id,
                                                  models.DBAttendance.date == day).all():
        if not a.clock_in:
            continue
        e = people.get(a.employee_id)
        row = {"employee": ("%s %s" % (e.first_name or "", e.last_name or "")).strip() if e else "",
               "job_title": (e.job_title or "") if e else "", "clock_in": a.clock_in or "",
               "clock_out": a.clock_out or "", "hours": a.total_hours or 0, "check_type": a.check_type or "",
               "located": bool(a.location_lat and a.location_lng)}
        if a.job_id and a.job_id in jobs:
            j = jobs[a.job_id]
            sites.setdefault(a.job_id, {"job_id": j.id, "project": "%s %s" % (j.number or "", j.name or ""),
                                        "fenced": a.job_id in fenced, "people": []})["people"].append(row)
        else:
            elsewhere.append(row)
    for jid, g in fenced.items():
        if jid in jobs and jid not in sites:
            j = jobs[jid]
            sites[jid] = {"job_id": j.id, "project": "%s %s" % (j.number or "", j.name or ""),
                          "fenced": True, "people": []}
    return {"day": day, "sites": sorted(sites.values(), key=lambda x: -len(x["people"])),
            "elsewhere": elsewhere, "fenced_sites": len(fenced),
            "summary": {"on_site": sum(len(x["people"]) for x in sites.values()),
                        "elsewhere": len(elsewhere)}}
