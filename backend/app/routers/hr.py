"""The hr endpoints."""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, func as sqlfunc, or_
from sqlalchemy.orm import Session

from app import models
from app.core import passwords
from app.db import get_db

from app.constants.hr import ONBOARDING_STAGES, ORG_DOMAIN_KEY
from app.core.audit import log_audit
from app.core.auth import get_client_user, owned_or_404
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.permissions import (
    DEFAULT_PERMISSION_ROLE,
    EMPLOYEE_LEVELS,
    EMPLOYEE_ROLES,
    PERMISSION_KEYS,
    PERMISSION_ROLES,
    PORTAL_PERMISSIONS,
    ROLE_PERMISSIONS,
    permission_list,
    permissions_for,
)
from app.core.security import validate_password_strength
from app.schemas.hr import DepartmentCreate, DocumentRequirementIn, EmployeeCreate, RequirementTemplateIn
from app.services.employee_portal import leave_balance_for
from app.services.hr import (
    assert_department_name_free,
    assert_employee_code_free,
    assign_document_requests,
    employee_sites_payload,
    maybe_complete_onboarding,
    onboarding_snapshot,
    org_domain_for,
    request_to_dict,
    requirement_to_dict,
    resolve_basic_pay,
    seed_default_requirements,
    serialise,
    set_employee_sites,
    start_onboarding,
    suggest_org_email,
    sync_requirement_to_requests,
    validated_staff_password,
)
from app.validators.common import validate_candidate_document
from app.validators.hr import (
    clean_department_name,
    clean_employee_email,
    clean_org_domain,
    clean_person_name,
    validate_employee_money,
    validate_level,
    validate_manager,
    validate_permission_role,
    validate_requirement,
    validate_role,
)


router = APIRouter()


@router.get("/api/onboarding/pipeline")
def onboarding_pipeline(request: Request, db: Session = Depends(get_db)):
    """Everyone still onboarding, grouped by what they are waiting on."""
    client = get_client_user(request, db)
    employees = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status == "onboarding",
    ).all()

    hired_from = {
        s.hired_employee_id: s for s in db.query(models.DBFormSubmission).filter(
            models.DBFormSubmission.client_id == client.id,
            models.DBFormSubmission.hired_employee_id.isnot(None),
        ).all()
    }

    buckets = {key: [] for key, _, _ in ONBOARDING_STAGES}
    for emp in employees:
        snap = onboarding_snapshot(db, emp)
        sub = hired_from.get(emp.id)
        card = {
            "employee_id": emp.id,
            "name": f"{emp.first_name} {emp.last_name}".strip(),
            "employee_number": emp.employee_id or "",
            "job_title": emp.job_title or "",
            "department": emp.department.name if emp.department else "",
            "start_date": emp.start_date or "",
            "email": emp.email or "",
        }
        card.update(snap)
        # Where they came from, so the hire and the onboarding are one story.
        card["hired_from"] = ({
            "submission_id": sub.id,
            "candidate_name": sub.candidate_name or "",
            "hired_at": sub.hired_at or "",
        } if sub else None)
        buckets[snap["stage"]].append(card)

    for rows in buckets.values():
        # Anything blocked first, then whoever has been waiting longest.
        rows.sort(key=lambda c: (not c["is_blocked"], -(c["days_since_start"] or 0)))

    return {
        "stages": [
            {"key": key, "label": label, "hint": hint,
             "count": len(buckets[key]), "cards": buckets[key]}
            for key, label, hint in ONBOARDING_STAGES
        ],
        "total": len(employees),
        "blocked": sum(1 for rows in buckets.values() for c in rows if c["is_blocked"]),
    }


@router.post("/api/employees/{emp_id}/complete-onboarding")
def complete_onboarding(emp_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark a starter as a working employee.

    Refuses while something is still outstanding, and says what, rather than
    quietly activating someone whose paperwork is not in.
    """
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.status != "onboarding":
        raise HTTPException(status_code=400, detail="This employee is not onboarding")

    snap = onboarding_snapshot(db, emp)
    blockers = []
    if snap["awaiting_employee"]:
        blockers.append("waiting on " + ", ".join(snap["awaiting_employee"]))
    if snap["awaiting_hr"]:
        blockers.append("still to review " + ", ".join(snap["awaiting_hr"]))
    if not snap["checklist_done"]:
        blockers.append(
            f"{snap['items_total'] - snap['items_done']} checklist item(s) left")
    if blockers:
        raise HTTPException(status_code=400, detail="Not finished: " + "; ".join(blockers))

    emp.onboarding_complete = True
    emp.status = "active"
    log_audit(db, client.id, "onboarding_completed", "employee", emp.id,
              f"{emp.first_name} {emp.last_name}".strip(), "", request)
    db.commit()
    return {"message": "Onboarding complete", "status": emp.status}


@router.post("/api/employees/{emp_id}/nudge")
def nudge_onboarding(emp_id: int, request: Request, db: Session = Depends(get_db)):
    """Remind a starter what is still outstanding, in their own portal."""
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    snap = onboarding_snapshot(db, emp)
    if not snap["awaiting_employee"]:
        raise HTTPException(status_code=400, detail="Nothing is waiting on this person")
    db.add(models.DBNotification(
        client_id=client.id, employee_id=emp.id, type="warning",
        title="Documents still needed",
        message="Please upload: " + ", ".join(snap["awaiting_employee"]),
    ))
    db.commit()
    return {"message": "Reminder sent", "items": snap["awaiting_employee"]}


@router.get("/api/hr/levels")
def get_hr_levels(request: Request, db: Session = Depends(get_db)):
    """Catalogue the UI uses to populate level and role pickers."""
    get_client_user(request, db)
    return {
        "levels": EMPLOYEE_LEVELS,
        "roles": EMPLOYEE_ROLES,
        "permission_roles": PERMISSION_ROLES,
        "permissions": PORTAL_PERMISSIONS,
    }


@router.get("/api/departments")
def get_departments(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    depts = db.query(models.DBDepartment).filter(models.DBDepartment.client_id == client.id).all()
    result = []
    for d in depts:
        employees = db.query(models.DBEmployee).filter(models.DBEmployee.department_id == d.id).all()
        emp_list = [{"id": e.id, "name": (e.first_name + " " + e.last_name).strip(), "job_title": e.job_title or "", "email": e.email or ""} for e in employees]
        result.append({
            "id": d.id, "name": d.name, "description": d.description,
            "color": d.color or "#00f0ff", "icon": d.icon or "building",
            "employee_count": len(employees), "employees": emp_list, "created_at": d.created_at,
        })
    return result


@router.get("/api/departments/{dept_id}")
def get_department(dept_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    d = db.query(models.DBDepartment).filter(models.DBDepartment.id == dept_id, models.DBDepartment.client_id == client.id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Department not found")
    employees = db.query(models.DBEmployee).filter(models.DBEmployee.department_id == d.id).all()
    emp_list = [{"id": e.id, "name": (e.first_name + " " + e.last_name).strip(), "job_title": e.job_title or "", "email": e.email or "", "status": e.status or ""} for e in employees]
    return {
        "id": d.id, "name": d.name, "description": d.description,
        "color": d.color or "#00f0ff", "icon": d.icon or "building",
        "employee_count": len(employees), "employees": emp_list, "created_at": d.created_at,
    }


@router.post("/api/departments")
def create_department(request: Request, body: DepartmentCreate, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    name = clean_department_name(body.name)
    assert_department_name_free(db, client.id, name)
    dept = models.DBDepartment(name=name, description=body.description, color=body.color, icon=body.icon, client_id=client.id)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return {"id": dept.id, "name": dept.name, "description": dept.description, "color": dept.color, "icon": dept.icon, "employee_count": 0}


@router.put("/api/departments/{dept_id}")
def update_department(dept_id: int, request: Request, body: DepartmentCreate, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == dept_id, models.DBDepartment.client_id == client.id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    name = clean_department_name(body.name)
    # Create checked for duplicates but update did not, so a rename could
    # produce two departments with the same name.
    assert_department_name_free(db, client.id, name, exclude_id=dept.id)
    dept.name = name
    dept.description = body.description
    dept.color = body.color
    dept.icon = body.icon
    db.commit()
    return {"id": dept.id, "name": dept.name, "description": dept.description, "color": dept.color, "icon": dept.icon}


@router.delete("/api/departments/{dept_id}")
def delete_department(dept_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == dept_id, models.DBDepartment.client_id == client.id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    db.query(models.DBEmployee).filter(models.DBEmployee.department_id == dept_id).update(
        {"department_id": None}, synchronize_session=False
    )
    # Goals hang off departments too and would block the delete on Postgres.
    db.query(models.DBDepartmentGoal).filter(models.DBDepartmentGoal.department_id == dept_id).delete(
        synchronize_session=False
    )
    db.query(models.DBEmployeeGoal).filter(models.DBEmployeeGoal.department_id == dept_id).update(
        {"department_id": None}, synchronize_session=False
    )
    log_audit(db, client.id, "department_deleted", "department", dept.id, dept.name, "", request)
    db.delete(dept)
    db.commit()
    return {"message": "Department deleted"}


@router.get("/api/employees")
def get_employees(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id)
    if status:
        query = query.filter(models.DBEmployee.status == status)
    if q:
        query = query.filter(or_(
            models.DBEmployee.first_name.ilike(f"%{q}%"),
            models.DBEmployee.last_name.ilike(f"%{q}%"),
            models.DBEmployee.email.ilike(f"%{q}%"),
            models.DBEmployee.job_title.ilike(f"%{q}%"),
        ))
    employees = query.order_by(models.DBEmployee.created_at.desc()).all()
    result = []
    for e in employees:
        dept_name = ""
        if e.department_id:
            dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == e.department_id).first()
            dept_name = dept.name if dept else ""
        manager_name = ""
        if e.reports_to:
            mgr = db.query(models.DBEmployee).filter(models.DBEmployee.id == e.reports_to).first()
            manager_name = f"{mgr.first_name} {mgr.last_name}" if mgr else ""
        result.append({
            "site_count": db.query(models.DBEmployeeSite).filter(
                models.DBEmployeeSite.employee_id == e.id).count(),
            "id": e.id, "employee_id": e.employee_id,
            "first_name": e.first_name, "last_name": e.last_name,
            "full_name": f"{e.first_name} {e.last_name}",
            "email": e.email, "phone": e.phone,
            "department_id": e.department_id, "department_name": dept_name,
            "reports_to": e.reports_to, "manager_name": manager_name,
            "job_title": e.job_title, "role": e.role, "level": e.level or "",
            "permission_role": e.permission_role or DEFAULT_PERMISSION_ROLE,
            "employment_type": e.employment_type,
            "pay_frequency": e.pay_frequency,
            "salary": e.salary, "hourly_rate": e.hourly_rate,
            "tax_rate": e.tax_rate, "deductions": e.deductions,
            "allowances": e.allowances, "bonus": e.bonus,
            "bank_name": e.bank_name, "bank_account": e.bank_account, "tax_id": e.tax_id,
            "emergency_contact": e.emergency_contact, "emergency_phone": e.emergency_phone,
            "start_date": e.start_date, "end_date": e.end_date,
            "status": e.status, "onboarding_complete": e.onboarding_complete,
            "offboarding_complete": e.offboarding_complete,
            "created_at": e.created_at,
        })
    return result


@router.post("/api/employees")
def create_employee(request: Request, body: EmployeeCreate, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    serialise(db, "employee-create:%d" % client.id)
    first_name = clean_person_name(body.first_name, "First name")
    last_name = clean_person_name(body.last_name, "Last name")
    email = clean_employee_email(db, client.id, body.email, required=bool(body.password))
    validate_employee_money(body.model_dump())
    employee_code = assert_employee_code_free(db, client.id, body.employee_id)

    level = validate_level(body.level)
    role = validate_role(body.role)
    permission_role = validate_permission_role(body.permission_role)
    reports_to = validate_manager(db, client.id, None, body.reports_to)
    owned_or_404(db, models.DBDepartment, client.id, body.department_id, "Department")

    max_num = db.query(sqlfunc.coalesce(sqlfunc.max(models.DBEmployee.id), 0)).filter(models.DBEmployee.client_id == client.id).scalar()
    emp_number = employee_code or f"EMP-{max_num + 1:04d}"

    emp = models.DBEmployee(
        client_id=client.id, employee_id=emp_number,
        first_name=first_name, last_name=last_name,
        email=email, phone=body.phone, address=body.address,
        department_id=body.department_id, reports_to=reports_to,
        job_title=body.job_title, role=role, level=level,
        permission_role=permission_role,
        employment_type=body.employment_type, pay_frequency=body.pay_frequency,
        salary=body.salary, hourly_rate=body.hourly_rate,
        tax_rate=body.tax_rate, deductions=body.deductions,
        allowances=body.allowances, bonus=body.bonus,
        bank_name=body.bank_name, bank_account=body.bank_account,
        tax_id=body.tax_id,
        emergency_contact=body.emergency_contact, emergency_phone=body.emergency_phone,
        start_date=body.start_date, status="onboarding",
        password_hash=passwords.hash_password(validated_staff_password(body.password)) if body.password else "",
    )
    db.add(emp)
    db.flush()

    # Create default onboarding checklist
    start_onboarding(db, client.id, emp)

    if body.department_id:
        pending_goals = db.query(models.DBDepartmentGoal).filter(
            models.DBDepartmentGoal.department_id == body.department_id,
            models.DBDepartmentGoal.client_id == client.id,
            models.DBDepartmentGoal.is_assigned == False,
        ).all()
        for dg in pending_goals:
            goal = models.DBEmployeeGoal(
                client_id=client.id, employee_id=emp.id, department_id=body.department_id,
                title=dg.title, description=dg.description,
                target_value=dg.target_value, current_value=0,
                unit=dg.unit, category=dg.category,
                priority=dg.priority, start_date=dg.start_date,
                due_date=dg.due_date, created_by="HR",
            )
            db.add(goal)
            note = models.DBNotification(
                client_id=client.id, employee_id=emp.id,
                title="New Goal Assigned", message=f"HR has assigned you a department goal: {dg.title}",
                type="info",
            )
            db.add(note)
            dg.is_assigned = True

    db.commit()
    db.refresh(emp)
    set_employee_sites(db, client.id, emp, body.site_ids)
    log_audit(db, client.id, "employee_created", "employee", emp.id, f"{emp.first_name} {emp.last_name}", f"Dept: {body.department_id or 'None'}", request)
    db.commit()
    return {
        **employee_sites_payload(db, emp),
        "id": emp.id, "employee_id": emp.employee_id,
        "first_name": emp.first_name, "last_name": emp.last_name,
        "email": emp.email, "status": emp.status, "level": emp.level or "", "role": emp.role,
        "permission_role": emp.permission_role or DEFAULT_PERMISSION_ROLE,
        "department_id": emp.department_id, "reports_to": emp.reports_to,
        "message": "Employee created. Onboarding checklist generated.",
    }


@router.get("/api/employees/{emp_id}")
def get_employee(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    dept_name = ""
    if emp.department_id:
        dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == emp.department_id).first()
        dept_name = dept.name if dept else ""
    manager_name = ""
    if emp.reports_to:
        mgr = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp.reports_to).first()
        manager_name = f"{mgr.first_name} {mgr.last_name}" if mgr else ""
    payslips = db.query(models.DBPayslip).filter(models.DBPayslip.employee_id == emp.id).order_by(models.DBPayslip.created_at.desc()).limit(12).all()
    onboarding = db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.employee_id == emp.id).all()

    # The profile is the one place HR looks up a person, so it answers every
    # question about them rather than sending the user hunting across tabs.
    leave_rows = db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.employee_id == emp.id
    ).order_by(models.DBLeaveRequest.id.desc()).limit(10).all()

    today = datetime.now().date()
    on_leave_today = False
    for l in leave_rows:
        if l.status != "approved":
            continue
        start, end = _parse_date(l.start_date), _parse_date(l.end_date)
        if start and end and start <= today <= end:
            on_leave_today = True
            break

    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    attendance = db.query(models.DBAttendance).filter(
        models.DBAttendance.employee_id == emp.id,
        models.DBAttendance.date >= since,
    ).order_by(models.DBAttendance.date.desc()).all()
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_row = next((a for a in attendance if a.date == today_str), None)

    goals = db.query(models.DBEmployeeGoal).filter(
        models.DBEmployeeGoal.employee_id == emp.id
    ).order_by(models.DBEmployeeGoal.id.desc()).limit(10).all()
    documents = db.query(models.DBDocument).filter(
        models.DBDocument.employee_id == emp.id
    ).order_by(models.DBDocument.id.desc()).all()
    doc_requests = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.employee_id == emp.id
    ).order_by(models.DBDocumentRequest.id.asc()).all()

    # Where this person came from, if they were hired through recruitment.
    origin = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.hired_employee_id == emp.id
    ).first()

    direct_reports = db.query(models.DBEmployee).filter(
        models.DBEmployee.reports_to == emp.id,
        models.DBEmployee.client_id == client.id,
    ).all()

    return {
        **employee_sites_payload(db, emp),
        "id": emp.id, "employee_id": emp.employee_id,
        "first_name": emp.first_name, "last_name": emp.last_name,
        "full_name": f"{emp.first_name} {emp.last_name}",
        "email": emp.email, "phone": emp.phone, "address": emp.address,
        "department_id": emp.department_id, "department_name": dept_name,
        "reports_to": emp.reports_to, "manager_name": manager_name,
        "job_title": emp.job_title, "role": emp.role, "level": emp.level or "",
        "permission_role": emp.permission_role or DEFAULT_PERMISSION_ROLE,
        "permissions": sorted(permissions_for(emp)),
        # What the role gives, so a screen can show which boxes were ticked by
        # the role and which by hand, rather than one undifferentiated list.
        "role_permissions": sorted(ROLE_PERMISSIONS.get(
            (emp.permission_role or DEFAULT_PERMISSION_ROLE).lower(), set())),
        "extra_permissions": sorted(permission_list(emp.extra_permissions)),
        "denied_permissions": sorted(permission_list(emp.denied_permissions)),
        "employment_type": emp.employment_type, "pay_frequency": emp.pay_frequency,
        "salary": emp.salary, "hourly_rate": emp.hourly_rate,
        "tax_rate": emp.tax_rate, "deductions": emp.deductions,
        "allowances": emp.allowances, "bonus": emp.bonus,
        "bank_name": emp.bank_name, "bank_account": emp.bank_account, "tax_id": emp.tax_id,
        "emergency_contact": emp.emergency_contact, "emergency_phone": emp.emergency_phone,
        "start_date": emp.start_date, "end_date": emp.end_date,
        "status": emp.status, "onboarding_complete": emp.onboarding_complete,
        "offboarding_complete": emp.offboarding_complete,
        "created_at": emp.created_at,
        "payslips": [{"id": p.id, "number": p.number, "period_start": p.period_start, "period_end": p.period_end,
                       "pay_date": p.pay_date, "gross_pay": p.gross_pay, "net_pay": p.net_pay,
                       "status": p.status, "sent": p.sent} for p in payslips],
        "onboarding_items": [{"id": o.id, "title": o.title, "description": o.description,
                               "category": o.category, "is_completed": o.is_completed,
                               "completed_at": o.completed_at, "assigned_to": o.assigned_to,
                               "due_date": o.due_date} for o in onboarding],
        "leave_balance": leave_balance_for(db, emp),
        "on_leave_today": on_leave_today,
        "leave_requests": [{
            "id": l.id, "leave_type": l.leave_type, "start_date": l.start_date,
            "end_date": l.end_date, "days": l.days, "status": l.status,
            "reason": l.reason, "created_at": l.created_at,
        } for l in leave_rows],
        "attendance_summary": {
            "days_present": sum(1 for a in attendance if a.clock_in),
            "days_late": sum(1 for a in attendance if a.status == "late"),
            "hours_30d": round(sum(a.total_hours or 0 for a in attendance), 2),
            "overtime_30d": round(sum(a.overtime_hours or 0 for a in attendance), 2),
            "clocked_in_today": bool(today_row and today_row.clock_in and not today_row.clock_out),
            "today_clock_in": today_row.clock_in if today_row else "",
            "today_clock_out": today_row.clock_out if today_row else "",
        },
        "goals": [{
            "id": g.id, "title": g.title, "status": g.status,
            "current_value": g.current_value, "target_value": g.target_value,
            "unit": g.unit, "due_date": g.due_date, "priority": g.priority,
        } for g in goals],
        "documents": [{
            "id": d.id, "title": d.title, "doc_type": d.doc_type,
            "file_name": d.file_name, "uploaded_by": d.uploaded_by,
            "created_at": d.created_at,
        } for d in documents],
        "document_requests": [request_to_dict(r) for r in doc_requests],
        "documents_outstanding": sum(
            1 for r in doc_requests if r.status in ("pending", "rejected")
        ),
        "direct_reports": [{
            "id": r.id, "full_name": f"{r.first_name} {r.last_name}",
            "job_title": r.job_title, "level": r.level or "", "status": r.status,
        } for r in direct_reports],
        "hired_from": {
            "submission_id": origin.id, "form_id": origin.form_id,
            "applied_on": origin.created_at,
        } if origin else None,
    }


@router.put("/api/employees/{emp_id}")
def update_employee(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    old_dept = emp.department_id
    body = body or {}
    # Everything a blind setattr would have accepted unchecked.
    if "first_name" in body:
        body["first_name"] = clean_person_name(body["first_name"], "First name")
    if "last_name" in body:
        body["last_name"] = clean_person_name(body["last_name"], "Last name")
    if "email" in body:
        body["email"] = clean_employee_email(db, client.id, body["email"], exclude_id=emp.id,
                                             required=bool(emp.password_hash or body.get("password")))
    validate_employee_money(body)
    # Hierarchy fields go through the same checks as on create; a blind
    # setattr let callers set an unknown level or build a reporting loop.
    if "level" in body:
        body["level"] = validate_level(body["level"])
    if "role" in body:
        body["role"] = validate_role(body["role"])
    if "permission_role" in body:
        body["permission_role"] = validate_permission_role(body["permission_role"])
    if "reports_to" in body:
        body["reports_to"] = validate_manager(db, client.id, emp.id, body["reports_to"])
    site_ids = body.pop("site_ids", None)
    for key, val in body.items():
        if hasattr(emp, key) and key not in ("id", "client_id", "created_at", "password_hash", "employee_id"):
            setattr(emp, key, val)
    set_employee_sites(db, client.id, emp, site_ids)
    new_dept = emp.department_id
    if new_dept and new_dept != old_dept:
        pending_goals = db.query(models.DBDepartmentGoal).filter(
            models.DBDepartmentGoal.department_id == new_dept,
            models.DBDepartmentGoal.client_id == client.id,
            models.DBDepartmentGoal.is_assigned == False,
        ).all()
        for dg in pending_goals:
            goal = models.DBEmployeeGoal(
                client_id=client.id, employee_id=emp.id, department_id=new_dept,
                title=dg.title, description=dg.description,
                target_value=dg.target_value, current_value=0,
                unit=dg.unit, category=dg.category,
                priority=dg.priority, start_date=dg.start_date,
                due_date=dg.due_date, created_by="HR",
            )
            db.add(goal)
            note = models.DBNotification(
                client_id=client.id, employee_id=emp.id,
                title="New Goal Assigned", message=f"HR has assigned you a department goal: {dg.title}",
                type="info",
            )
            db.add(note)
            dg.is_assigned = True
    log_audit(db, client.id, "employee_updated", "employee", emp.id, f"{emp.first_name} {emp.last_name}", f"Fields: {', '.join(body.keys()) if body else 'none'}", request)
    db.commit()
    return {"message": "Employee updated"}


@router.delete("/api/employees/{emp_id}")
def delete_employee(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp_name = f"{emp.first_name} {emp.last_name}"
    # Every table that points at employees must be cleared first, otherwise the
    # delete fails on a foreign key violation. Attendance, goals, leave,
    # documents, notifications and overtime were all being left behind.
    for model in (
        models.DBOnboardingItem, models.DBPayslip, models.DBAttendance,
        models.DBEmployeeGoal, models.DBLeaveRequest, models.DBDocument,
        models.DBNotification, models.DBOvertimeLog,
    ):
        db.query(model).filter(model.employee_id == emp_id).delete(synchronize_session=False)
    # Anyone reporting to this person would keep a dangling manager reference.
    db.query(models.DBEmployee).filter(models.DBEmployee.reports_to == emp_id).update(
        {"reports_to": None}, synchronize_session=False
    )
    log_audit(db, client.id, "employee_deleted", "employee", emp.id, emp_name, "", request)
    db.delete(emp)
    db.commit()
    return {"message": "Employee deleted"}


@router.post("/api/employees/{emp_id}/reset-password")
def reset_employee_password(emp_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    new_pass = body.get("password", "")
    validate_password_strength(new_pass)
    emp.password_hash = passwords.hash_password(new_pass)
    db.commit()
    return {"message": "Password updated successfully"}


@router.get("/api/hr/org-domain")
def get_org_domain(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    domain = org_domain_for(db, client.id)
    off_domain = 0
    if domain:
        off_domain = sum(
            1 for e in db.query(models.DBEmployee).filter(
                models.DBEmployee.client_id == client.id).all()
            if not (e.email or "").lower().endswith("@" + domain)
        )
    return {
        "domain": domain,
        # Existing people are left alone when a domain is first set; this is
        # how many of them still sign in with an address off it.
        "employees_off_domain": off_domain,
    }


@router.put("/api/hr/org-domain")
def set_org_domain(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Set the domain staff accounts are issued on.

    Existing employees are deliberately not rewritten: changing somebody's
    address changes what they sign in with, and doing that to a whole workforce
    behind a settings save would lock everyone out at once.
    """
    client = get_client_user(request, db)
    domain = clean_org_domain((body or {}).get("domain", ""))
    setting = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client.id,
        models.DBSettings.key == ORG_DOMAIN_KEY,
    ).first()
    if setting:
        setting.value = domain
    else:
        db.add(models.DBSettings(
            client_id=client.id, key=ORG_DOMAIN_KEY, value=domain,
            description="Domain that staff portal accounts are issued on",
        ))
    log_audit(db, client.id, "org_domain_set", "settings", None, ORG_DOMAIN_KEY,
              f"Set to {domain or '(none)'}", request)
    db.commit()
    return {"domain": domain, "message": "Organisation domain saved"}


@router.get("/api/hr/suggest-email")
def suggest_employee_email(request: Request, first_name: str = "", last_name: str = "",
                           db: Session = Depends(get_db)):
    """The address a new starter would be given, so HR does not type it."""
    client = get_client_user(request, db)
    domain = org_domain_for(db, client.id)
    return {
        "domain": domain,
        "email": suggest_org_email(db, client.id, first_name, last_name),
    }


@router.put("/api/employees/{emp_id}/permissions")
def set_employee_permissions(emp_id: int, request: Request, body: dict = None,
                             db: Session = Depends(get_db)):
    """HR decides what a member of staff may do in the portal.

    Recorded in the audit log because it is a change of access, not a change of
    detail: who widened somebody's rights, and when, is the first question
    asked after a cost is approved by the wrong person.
    """
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id,
        models.DBEmployee.client_id == client.id,
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    body = body or {}
    new_role = validate_permission_role(body.get("permission_role"))
    old_role = emp.permission_role or DEFAULT_PERMISSION_ROLE
    before = sorted(permissions_for(emp))
    emp.permission_role = new_role

    # Anything named here is measured against the role rather than stored on
    # top of it, so the record says what was actually decided: a right the
    # role already carries is not written as a grant, and one it never had is
    # not written as a denial. Otherwise the two lists fill up with entries
    # that mean nothing and hide the one that does.
    if "permissions" in body:
        wanted = {p for p in (body.get("permissions") or []) if p in PERMISSION_KEYS}
        from_role = set(ROLE_PERMISSIONS.get(new_role, set()))
        emp.extra_permissions = ",".join(sorted(wanted - from_role))
        emp.denied_permissions = ",".join(sorted(from_role - wanted))

    after = sorted(permissions_for(emp))
    detail = "Access changed from %s to %s" % (old_role, new_role)
    if before != after:
        gained = sorted(set(after) - set(before))
        lost = sorted(set(before) - set(after))
        if gained:
            detail += "; gained " + ", ".join(gained)
        if lost:
            detail += "; lost " + ", ".join(lost)
    log_audit(db, client.id, "employee_permissions_changed", "employee", emp.id,
              f"{emp.first_name} {emp.last_name}", detail, request)
    db.commit()
    return {
        "message": "Access updated",
        "permission_role": new_role,
        "permissions": after,
        "role_permissions": sorted(ROLE_PERMISSIONS.get(new_role, set())),
    }


@router.post("/api/employees/{emp_id}/offboard")
def start_offboarding(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    emp.status = "offboarding"
    db.commit()
    return {"message": "Offboarding started"}


@router.post("/api/employees/{emp_id}/complete-offboard")
def complete_offboarding(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    end_date = body.get("end_date", "") if body else ""
    emp.status = "terminated"
    emp.end_date = end_date
    emp.offboarding_complete = True
    db.commit()
    return {"message": "Employee offboarded"}


@router.get("/api/onboarding/hub")
def get_onboarding_hub(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    employees = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status.in_(["onboarding", "active"])
    ).all()
    result = []
    for emp in employees:
        items = db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.employee_id == emp.id).all()
        completed = sum(1 for i in items if i.is_completed)
        overdue = 0
        today = datetime.now().strftime("%Y-%m-%d")
        for i in items:
            if not i.is_completed and i.due_date and i.due_date < today:
                overdue += 1
        result.append({
            "id": emp.id, "name": (emp.first_name + " " + emp.last_name).strip(),
            "job_title": emp.job_title or "", "department": emp.department.name if emp.department else "",
            "status": emp.status or "", "start_date": emp.start_date or "",
            "total": len(items), "completed": completed,
            "progress": round((completed / len(items)) * 100) if items else 0,
            "overdue": overdue,
        })
    result.sort(key=lambda x: (-x["overdue"], x["progress"]))
    return result


@router.get("/api/employees/{emp_id}/onboarding")
def get_onboarding(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    items = db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.employee_id == emp_id).order_by(models.DBOnboardingItem.sort_order).all()
    completed = sum(1 for i in items if i.is_completed)
    return {
        "total": len(items), "completed": completed,
        "progress": round((completed / len(items)) * 100) if items else 0,
        "items": [{"id": i.id, "title": i.title, "description": i.description,
                    "category": i.category, "is_completed": i.is_completed,
                    "completed_at": i.completed_at, "assigned_to": i.assigned_to,
                    "due_date": i.due_date, "sort_order": i.sort_order} for i in items],
    }


@router.put("/api/onboarding/{item_id}")
def update_onboarding_item(item_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    item = db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.id == item_id, models.DBOnboardingItem.client_id == client.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if body:
        if "is_completed" in body:
            item.is_completed = body["is_completed"]
            if body["is_completed"]:
                item.completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                item.completed_at = ""
        if "title" in body:
            item.title = body["title"]
        if "description" in body:
            item.description = body["description"]
        if "category" in body:
            item.category = body["category"]
        if "assigned_to" in body:
            item.assigned_to = body["assigned_to"]
        if "due_date" in body:
            item.due_date = body["due_date"]
    db.commit()
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == item.employee_id).first()
    if maybe_complete_onboarding(db, emp):
        db.commit()
    return {"message": "Item updated"}


@router.delete("/api/onboarding/{item_id}")
def delete_onboarding_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    item = db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.id == item_id, models.DBOnboardingItem.client_id == client.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"message": "Item deleted"}


@router.post("/api/employees/{emp_id}/onboarding")
def add_onboarding_item(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    max_order = db.query(func.max(models.DBOnboardingItem.sort_order)).filter(models.DBOnboardingItem.employee_id == emp_id).scalar() or 0
    item = models.DBOnboardingItem(
        client_id=client.id, employee_id=emp_id,
        title=body.get("title", ""), description=body.get("description", ""),
        category=body.get("category", "general"), assigned_to=body.get("assigned_to", ""),
        due_date=body.get("due_date", ""), sort_order=max_order + 1,
    )
    db.add(item)
    db.commit()
    return {"id": item.id, "title": item.title, "message": "Item added"}


@router.post("/api/employees/{emp_id}/onboarding/bulk")
def bulk_add_onboarding(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    items = body.get("items", []) if body else []
    max_order = db.query(func.max(models.DBOnboardingItem.sort_order)).filter(models.DBOnboardingItem.employee_id == emp_id).scalar() or 0
    added = []
    for i, item_data in enumerate(items):
        oitem = models.DBOnboardingItem(
            client_id=client.id, employee_id=emp_id,
            title=item_data.get("title", ""), description=item_data.get("description", ""),
            category=item_data.get("category", "general"), assigned_to=item_data.get("assigned_to", ""),
            due_date=item_data.get("due_date", ""), sort_order=max_order + i + 1,
        )
        db.add(oitem)
        added.append(item_data.get("title", ""))
    db.commit()
    return {"added": len(added), "message": f"Added {len(added)} items"}


@router.post("/api/onboarding/apply-template")
def apply_onboarding_template(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp_ids = body.get("employee_ids", []) if body else []
    template_items = body.get("items", []) if body else []
    count = 0
    for emp_id in emp_ids:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
        if not emp:
            continue
        max_order = db.query(func.max(models.DBOnboardingItem.sort_order)).filter(models.DBOnboardingItem.employee_id == emp_id).scalar() or 0
        for i, item_data in enumerate(template_items):
            db.add(models.DBOnboardingItem(
                client_id=client.id, employee_id=emp_id,
                title=item_data.get("title", ""), description=item_data.get("description", ""),
                category=item_data.get("category", "general"), assigned_to=item_data.get("assigned_to", ""),
                due_date=item_data.get("due_date", ""), sort_order=max_order + i + 1,
            ))
            count += 1
    db.commit()
    return {"added": count, "message": f"Added {count} items to {len(emp_ids)} employees"}


@router.get("/api/onboarding/templates")
def get_onboarding_templates(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    templates = db.query(models.DBOnboardingTemplate).filter(models.DBOnboardingTemplate.client_id == client.id).all()
    return [{"id": t.id, "name": t.name, "items": json.loads(t.items_json) if t.items_json else [], "created_at": t.created_at} for t in templates]


@router.post("/api/onboarding/templates")
def create_onboarding_template(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body or not body.get("name"):
        raise HTTPException(status_code=400, detail="Name required")
    template = models.DBOnboardingTemplate(
        client_id=client.id, name=body["name"],
        items_json=json.dumps(body.get("items", [])),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return {"id": template.id, "name": template.name, "message": "Template created"}


@router.delete("/api/onboarding/templates/{template_id}")
def delete_onboarding_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    template = db.query(models.DBOnboardingTemplate).filter(models.DBOnboardingTemplate.id == template_id, models.DBOnboardingTemplate.client_id == client.id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"message": "Template deleted"}


@router.get("/api/employees/{emp_id}/pay-details")
def get_employee_pay_details(emp_id: int, request: Request, period_start: str = "", period_end: str = "", db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    hours_worked = 0.0
    if period_start and period_end:
        records = db.query(models.DBAttendance).filter(
            models.DBAttendance.employee_id == emp_id,
            models.DBAttendance.client_id == client.id,
            models.DBAttendance.date >= period_start,
            models.DBAttendance.date <= period_end,
        ).all()
        for r in records:
            hours_worked += r.total_hours or 0
        hours_worked = round(hours_worked, 2)

    overtime_hours = 0.0
    if period_start and period_end:
        ot_logs = db.query(models.DBOvertimeLog).filter(
            models.DBOvertimeLog.employee_id == emp_id,
            models.DBOvertimeLog.client_id == client.id,
            models.DBOvertimeLog.date >= period_start,
            models.DBOvertimeLog.date <= period_end,
            models.DBOvertimeLog.status == "announced",
        ).all()
        for log in ot_logs:
            overtime_hours += log.hours or 0
        overtime_hours = round(overtime_hours, 2)

    ot_rate = emp.hourly_rate or 0.0
    if ot_rate == 0 and (emp.salary or 0) > 0:
        ot_rate = round(emp.salary / 160 * 1.5, 2)

    # Hourly staff have salary == 0; paying them their (zero) salary produced a
    # blank payslip. Derive basic from the hours actually worked instead.
    basic = resolve_basic_pay(emp, None, hours_worked)
    ot_pay = money(overtime_hours * ot_rate) if overtime_hours > 0 else 0
    bonus = emp.bonus or 0.0
    allowances = emp.allowances or 0.0
    gross = money(basic + ot_pay + bonus + allowances)
    tax_rate = emp.tax_rate or 0.0
    tax_amount = money(gross * (tax_rate / 100)) if tax_rate > 0 else 0
    deductions = emp.deductions or 0.0
    total_deductions = money(tax_amount + deductions)
    net_pay = money(gross - total_deductions)

    return {
        "employee_id": emp.id,
        "full_name": f"{emp.first_name} {emp.last_name}",
        "employee_id_code": emp.employee_id,
        "job_title": emp.job_title,
        "pay_frequency": emp.pay_frequency,
        "bank_name": emp.bank_name,
        "bank_account": emp.bank_account,
        "tax_id": emp.tax_id,
        "salary": basic,
        "is_hourly": (emp.salary or 0) <= 0 and (emp.hourly_rate or 0) > 0,
        "hourly_rate": emp.hourly_rate or 0.0,
        "tax_rate": tax_rate,
        "deductions": deductions,
        "allowances": allowances,
        "bonus": bonus,
        "hours_worked": hours_worked,
        "overtime_hours": overtime_hours,
        "overtime_rate": ot_rate,
        "overtime_pay": ot_pay,
        "gross_pay": round(gross, 2),
        "tax_amount": tax_amount,
        "total_deductions": round(total_deductions, 2),
        "net_pay": net_pay,
    }


@router.get("/api/employees/{emp_id}/ytd")
def employee_ytd(emp_id: int, request: Request, year: str = "", db: Session = Depends(get_db)):
    """Year-to-date totals - required on most statutory payslip formats."""
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    year = year or datetime.now().strftime("%Y")
    slips = db.query(models.DBPayslip).filter(
        models.DBPayslip.client_id == client.id,
        models.DBPayslip.employee_id == emp_id,
        models.DBPayslip.status != "Void",
    ).all()
    in_year = [s for s in slips if (s.period_end or s.pay_date or "").startswith(year)]
    return {
        "year": year,
        "payslip_count": len(in_year),
        "gross_pay": money(sum(s.gross_pay or 0 for s in in_year)),
        "tax_amount": money(sum(s.tax_amount or 0 for s in in_year)),
        "total_deductions": money(sum(s.total_deductions or 0 for s in in_year)),
        "net_pay": money(sum(s.net_pay or 0 for s in in_year)),
    }


@router.get("/api/org-chart")
def get_org_chart(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    employees = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        models.DBEmployee.status.in_(["active", "onboarding"])
    ).all()
    departments = db.query(models.DBDepartment).filter(models.DBDepartment.client_id == client.id).all()

    emp_map = {}
    for e in employees:
        dept_name = ""
        if e.department_id:
            dept = db.query(models.DBDepartment).filter(models.DBDepartment.id == e.department_id).first()
            dept_name = dept.name if dept else ""
        emp_map[e.id] = {
            "id": e.id, "employee_id": e.employee_id,
            "name": f"{e.first_name} {e.last_name}",
            "job_title": e.job_title, "email": e.email,
            "level": e.level or "", "role": e.role or "employee",
            "department": dept_name, "reports_to": e.reports_to,
            "status": e.status,
        }

    roots = []
    for e_id, e_data in emp_map.items():
        if e_data["reports_to"] and e_data["reports_to"] in emp_map:
            parent = emp_map[e_data["reports_to"]]
            if "children" not in parent:
                parent["children"] = []
            parent["children"].append(e_data)
        else:
            roots.append(e_data)

    dept_groups = {}
    for d in departments:
        dept_employees = [e for e in emp_map.values() if e["department"] == d.name]
        if dept_employees:
            dept_groups[d.name] = dept_employees

    return {"roots": roots, "departments": dept_groups, "total_employees": len(employees)}


@router.get("/api/hr/stats")
def get_hr_stats(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    total = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).count()
    active = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.status == "active").count()
    onboarding = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.status == "onboarding").count()
    offboarding = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.status == "offboarding").count()
    terminated = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.status == "terminated").count()
    depts = db.query(models.DBDepartment).filter(models.DBDepartment.client_id == client.id).count()
    total_payroll = db.query(sqlfunc.coalesce(sqlfunc.sum(models.DBPayslip.net_pay), 0)).filter(models.DBPayslip.client_id == client.id, models.DBPayslip.status == "Paid").scalar()
    pending_payroll = db.query(sqlfunc.coalesce(sqlfunc.sum(models.DBPayslip.net_pay), 0)).filter(models.DBPayslip.client_id == client.id, models.DBPayslip.status != "Paid").scalar()
    return {
        "total_employees": total, "active": active, "onboarding": onboarding,
        "offboarding": offboarding, "terminated": terminated,
        "departments": depts,
        "total_payroll": round(float(total_payroll), 2),
        "pending_payroll": round(float(pending_payroll), 2),
    }


@router.put("/api/employees/{emp_id}/set-password")
def set_employee_password(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not body or not body.get("password"):
        raise HTTPException(status_code=400, detail="Password required")
    validate_password_strength(body["password"])
    emp.password_hash = passwords.hash_password(body["password"])
    db.commit()
    return {"message": "Password set successfully"}


@router.get("/api/onboarding/requirements")
def list_document_requirements(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    rows = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.client_id == client.id
    ).order_by(models.DBDocumentRequirement.sort_order.asc(),
               models.DBDocumentRequirement.id.asc()).all()
    if not rows:
        rows = seed_default_requirements(db, client.id)
        db.commit()
    return [requirement_to_dict(r) for r in rows]


@router.post("/api/onboarding/requirements")
def create_document_requirement(request: Request, body: DocumentRequirementIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    name, applies, due_days, level, reminder = validate_requirement(body, db, client.id)
    clash = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.client_id == client.id,
        sqlfunc.lower(models.DBDocumentRequirement.name) == name.lower(),
    ).first()
    if clash:
        raise HTTPException(status_code=400, detail=f"'{name}' is already on the list")
    row = models.DBDocumentRequirement(
        client_id=client.id, name=name, description=body.description or "",
        doc_type=body.doc_type or "other", is_mandatory=bool(body.is_mandatory),
        due_days=due_days, applies_to=applies,
        requires_expiry=bool(body.requires_expiry), expiry_reminder_days=reminder,
        department_id=owned_or_404(db, models.DBDepartment, client.id, body.department_id, "Department")
        if applies == "department" else None,
        level=level if applies == "level" else "",
        is_active=bool(body.is_active), sort_order=int(body.sort_order or 0),
    )
    db.add(row)
    log_audit(db, client.id, "doc_requirement_created", "requirement", None, name, "", request)
    db.commit()
    db.refresh(row)
    return requirement_to_dict(row)


@router.put("/api/onboarding/requirements/{req_id}")
def update_document_requirement(req_id: int, request: Request, body: DocumentRequirementIn, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    row = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.id == req_id,
        models.DBDocumentRequirement.client_id == client.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found")
    name, applies, due_days, level, reminder = validate_requirement(body, db, client.id)
    clash = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.client_id == client.id,
        models.DBDocumentRequirement.id != req_id,
        sqlfunc.lower(models.DBDocumentRequirement.name) == name.lower(),
    ).first()
    if clash:
        raise HTTPException(status_code=400, detail=f"'{name}' is already on the list")
    row.name = name
    row.description = body.description or ""
    row.doc_type = body.doc_type or "other"
    row.is_mandatory = bool(body.is_mandatory)
    row.due_days = due_days
    row.requires_expiry = bool(body.requires_expiry)
    row.expiry_reminder_days = reminder
    row.applies_to = applies
    row.department_id = owned_or_404(db, models.DBDepartment, client.id, body.department_id, "Department") \
        if applies == "department" else None
    row.level = level if applies == "level" else ""
    row.is_active = bool(body.is_active)
    row.sort_order = int(body.sort_order or 0)
    db.flush()
    # Otherwise the change only applies to people hired after it.
    sync_requirement_to_requests(db, client.id, row)
    # Widening the rule should also reach anyone it now covers for the first time.
    if row.is_active:
        for emp in db.query(models.DBEmployee).filter(
            models.DBEmployee.client_id == client.id,
            models.DBEmployee.status != "offboarded",
        ).all():
            assign_document_requests(db, client.id, emp, requirements=[row])
    db.commit()
    return requirement_to_dict(row)


@router.delete("/api/onboarding/requirements/{req_id}")
def delete_document_requirement(req_id: int, request: Request, db: Session = Depends(get_db)):
    """Outstanding requests go with it; anything already submitted is kept so
    the record of what someone provided is not destroyed."""
    client = get_client_user(request, db)
    row = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.id == req_id,
        models.DBDocumentRequirement.client_id == client.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found")
    db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.requirement_id == req_id,
        models.DBDocumentRequest.status == "pending",
    ).delete(synchronize_session=False)
    db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.requirement_id == req_id
    ).update({"requirement_id": None}, synchronize_session=False)
    log_audit(db, client.id, "doc_requirement_deleted", "requirement", row.id, row.name, "", request)
    db.delete(row)
    db.commit()
    return {"message": "Requirement removed"}


@router.post("/api/employees/{emp_id}/document-requests/sync")
def sync_employee_document_requests(emp_id: int, request: Request, db: Session = Depends(get_db)):
    """Apply the current requirements to one employee - used after their
    department or level changes, or for staff who predate a new rule."""
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    created = assign_document_requests(db, client.id, emp)
    db.commit()
    return {"message": f"{len(created)} document request(s) added", "added": len(created)}


@router.get("/api/employees/{emp_id}/document-requests")
def list_employee_document_requests(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    rows = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.employee_id == emp_id
    ).order_by(models.DBDocumentRequest.id.asc()).all()
    return [request_to_dict(r) for r in rows]


@router.get("/api/onboarding/document-queue")
def document_review_queue(request: Request, status: str = "submitted", db: Session = Depends(get_db)):
    """What employees have sent in, waiting on HR. This is the auto-fetch the
    employee portal feeds."""
    client = get_client_user(request, db)
    query = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.client_id == client.id
    )
    if status and status != "all":
        query = query.filter(models.DBDocumentRequest.status == status)
    rows = query.order_by(models.DBDocumentRequest.submitted_at.desc(),
                          models.DBDocumentRequest.id.desc()).all()

    emp_names = {
        e.id: f"{e.first_name} {e.last_name}"
        for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).all()
    }
    out = []
    for r in rows:
        data = request_to_dict(r)
        data["employee_name"] = emp_names.get(r.employee_id, "")
        out.append(data)
    return out


@router.get("/api/onboarding/document-requests/{req_id}/file")
def download_document_request_file(req_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    row = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.id == req_id,
        models.DBDocumentRequest.client_id == client.id,
    ).first()
    if not row or not row.document:
        raise HTTPException(status_code=404, detail="No file submitted for this document")
    return {
        "file_name": row.document.file_name, "file_type": row.document.file_type,
        "file_data": row.document.file_data, "name": row.name,
    }


@router.post("/api/onboarding/document-requests/{req_id}/review")
def review_document_request(req_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    body = body or {}
    row = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.id == req_id,
        models.DBDocumentRequest.client_id == client.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Document request not found")
    if row.status not in ("submitted", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Nothing has been submitted for this document yet")

    decision = (body.get("decision") or "").strip().lower()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Decision must be approve or reject")
    note = (body.get("note") or "").strip()
    if decision == "reject" and not note:
        raise HTTPException(
            status_code=400,
            detail="Give a reason so the employee knows what to resubmit",
        )

    row.status = "approved" if decision == "approve" else "rejected"
    row.reviewed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row.reviewed_by = body.get("reviewed_by") or "HR"
    row.review_note = note

    db.add(models.DBNotification(
        client_id=client.id, employee_id=row.employee_id,
        title=f"Document {row.status}: {row.name}",
        message=note or (f"Your {row.name} has been approved." if decision == "approve"
                         else f"Your {row.name} needs resubmitting."),
        type="success" if decision == "approve" else "warning",
    ))
    log_audit(db, client.id, f"document_{row.status}", "document_request", row.id,
              row.name, f"Employee {row.employee_id}", request)
    # Approving the last outstanding document can be what finishes onboarding,
    # so completion is checked here as well as on the checklist.
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == row.employee_id).first()
    maybe_complete_onboarding(db, emp)
    db.commit()
    return request_to_dict(row)


@router.post("/api/onboarding/requirements/{req_id}/template")
def upload_requirement_template(req_id: int, body: RequirementTemplateIn, request: Request,
                                db: Session = Depends(get_db)):
    """Attach a blank form for the employee to download, fill in and return."""
    client = get_client_user(request, db)
    row = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.id == req_id,
        models.DBDocumentRequirement.client_id == client.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found")
    validate_candidate_document(body)
    row.template_file_name = body.file_name
    row.template_file_type = body.file_type or ""
    row.template_file_data = body.file_data
    db.commit()
    return {"message": f"Template attached to {row.name}", "template_file_name": row.template_file_name}


@router.delete("/api/onboarding/requirements/{req_id}/template")
def delete_requirement_template(req_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    row = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.id == req_id,
        models.DBDocumentRequirement.client_id == client.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found")
    row.template_file_name = ""
    row.template_file_type = ""
    row.template_file_data = ""
    db.commit()
    return {"message": "Template removed"}


@router.get("/api/onboarding/requirements/{req_id}/template")
def download_requirement_template(req_id: int, request: Request, db: Session = Depends(get_db)):
    """Readable by HR and by any employee who has been asked for it."""
    client_id = None
    if request.session.get("client_id"):
        client_id = request.session["client_id"]
    elif request.session.get("employee_id"):
        client_id = request.session.get("employee_client_id")
    if not client_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.id == req_id,
        models.DBDocumentRequirement.client_id == client_id,
    ).first()
    if not row or not row.template_file_data:
        raise HTTPException(status_code=404, detail="No template attached to this document")
    return {
        "file_name": row.template_file_name,
        "file_type": row.template_file_type,
        "file_data": row.template_file_data,
    }


@router.get("/api/onboarding/expiring-documents")
def expiring_documents(request: Request, days: int = 60, db: Session = Depends(get_db)):
    """Approved documents that have expired or are about to.

    Right-to-work and DBS checks lapse quietly; this is what stops a company
    finding out during an audit.
    """
    client = get_client_user(request, db)
    days = max(1, min(days, 365))
    horizon = (datetime.now().date() + timedelta(days=days))
    today = datetime.now().date()

    rows = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.client_id == client.id,
        models.DBDocumentRequest.status == "approved",
        models.DBDocumentRequest.expires_on != "",
    ).all()

    emp_names = {
        e.id: f"{e.first_name} {e.last_name}"
        for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).all()
    }
    out = []
    for r in rows:
        expires = _parse_date(r.expires_on)
        if not expires or expires > horizon:
            continue
        data = request_to_dict(r)
        data["employee_name"] = emp_names.get(r.employee_id, "")
        out.append(data)
    out.sort(key=lambda d: d["expires_on"])
    return {
        "expired": [d for d in out if d["is_expired"]],
        "expiring": [d for d in out if not d["is_expired"]],
        "window_days": days,
    }


# HR-side: Create goal for employee
@router.post("/api/employees/{emp_id}/goals")
def create_employee_goal(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body: body = {}
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    goal = models.DBEmployeeGoal(
        client_id=client.id, employee_id=emp_id,
        title=body.get("title", ""), description=body.get("description", ""),
        target_value=body.get("target_value", 100), current_value=body.get("current_value", 0),
        unit=body.get("unit", "%"), category=body.get("category", "performance"),
        priority=body.get("priority", "medium"), start_date=body.get("start_date", ""),
        due_date=body.get("due_date", ""), created_by="HR",
    )
    db.add(goal)
    note = models.DBNotification(
        client_id=client.id, employee_id=emp_id,
        title="New Goal Assigned", message=f"HR has assigned you a new goal: {goal.title}",
        type="info",
    )
    db.add(note)
    db.commit()
    return {"message": "Goal created", "id": goal.id}


@router.get("/api/employees/{emp_id}/leave-balance")
def get_employee_leave_balance(emp_id: int, request: Request, db: Session = Depends(get_db)):
    """Entitlement vs. usage, for the HR-side employee record."""
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return leave_balance_for(db, emp)


@router.put("/api/employees/{emp_id}/leave-entitlement")
def set_employee_leave_entitlement(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Entitlements were hard-coded at 25/10 for everyone; make them per-person."""
    client = get_client_user(request, db)
    emp = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    body = body or {}
    for field, attr in (("annual_days", "annual_leave_entitlement"), ("sick_days", "sick_leave_entitlement")):
        if body.get(field) is not None:
            try:
                value = float(body[field])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{field} must be a number")
            if value < 0 or value > 365:
                raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 365")
            setattr(emp, attr, value)
    log_audit(db, client.id, "leave_entitlement_updated", "employee", emp.id,
              f"{emp.first_name} {emp.last_name}", "", request)
    db.commit()
    return leave_balance_for(db, emp)


@router.get("/api/employees/{emp_id}/goals")
def get_goals_for_employee(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    goals = db.query(models.DBEmployeeGoal).filter(models.DBEmployeeGoal.employee_id == emp_id, models.DBEmployeeGoal.client_id == client.id).order_by(models.DBEmployeeGoal.created_at.desc()).all()
    return [{"id": g.id, "title": g.title, "description": g.description, "target_value": g.target_value, "current_value": g.current_value, "unit": g.unit, "category": g.category, "priority": g.priority, "start_date": g.start_date, "due_date": g.due_date, "status": g.status, "created_by": g.created_by, "department_id": g.department_id} for g in goals]


@router.get("/api/employees/{emp_id}/documents")
def get_documents_for_employee(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    docs = db.query(models.DBDocument).filter(models.DBDocument.employee_id == emp_id, models.DBDocument.client_id == client.id).order_by(models.DBDocument.created_at.desc()).all()
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "file_name": d.file_name, "uploaded_by": d.uploaded_by, "created_at": d.created_at} for d in docs]


@router.get("/api/employees/{emp_id}/leave")
def get_leave_for_employee(emp_id: int, request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    leaves = db.query(models.DBLeaveRequest).filter(models.DBLeaveRequest.employee_id == emp_id, models.DBLeaveRequest.client_id == client.id).order_by(models.DBLeaveRequest.created_at.desc()).all()
    return [{"id": l.id, "leave_type": l.leave_type, "start_date": l.start_date, "end_date": l.end_date, "days": l.days, "reason": l.reason, "status": l.status, "approved_by": l.approved_by, "created_at": l.created_at} for l in leaves]


@router.post("/api/employees/{emp_id}/documents")
def upload_document(emp_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    if not body: body = {}
    emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client.id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    doc = models.DBDocument(
        client_id=client.id, employee_id=emp_id,
        title=body.get("title", ""), doc_type=body.get("doc_type", "other"),
        file_name=body.get("file_name", ""), file_type=body.get("file_type", ""),
        file_data=body.get("file_data", ""), uploaded_by="HR",
    )
    db.add(doc)
    note = models.DBNotification(
        client_id=client.id, employee_id=emp_id,
        title="New Document Uploaded", message=f"HR has uploaded a document: {doc.title}",
        type="info",
    )
    db.add(note)
    db.commit()
    return {"message": "Document uploaded", "id": doc.id}
