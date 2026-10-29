"""The rules and workings behind the hr endpoints."""
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import joinedload

from app import models

from app.constants.approvals import GONE_STATUSES
from app.constants.hr import DEFAULT_DOCUMENT_REQUIREMENTS, DEFAULT_ONBOARDING_ITEMS, ORG_DOMAIN_KEY, emergency_contact_required
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.permissions import EMPLOYEE_ROLES
from app.core.security import validate_password_strength
from app.core.tenant_settings import tenant_setting


_ROLE_BOSS = {r["code"]: r["reports_to"] for r in EMPLOYEE_ROLES}


def automatic_reports_to(db, client_id, role, department_id=None, exclude_id=None):
    """Who a person in `role` reports to when nobody has said: the holder of the role above theirs.

    If nobody holds that role it climbs to the one above, so a Store Assistant with no Store Executive
    reports to the Project Manager. A holder in the same department wins, then the longest-serving.
    None when no role above is held; the Master can then set the line by hand.
    """
    seen = set()
    code = _ROLE_BOSS.get(role)
    while code and code not in seen:
        seen.add(code)
        holders = db.query(models.DBEmployee).filter(
            models.DBEmployee.client_id == client_id, models.DBEmployee.role == code,
            models.DBEmployee.id != (exclude_id or 0),
            models.DBEmployee.status.notin_(GONE_STATUSES)).order_by(models.DBEmployee.id).all()
        if holders:
            same = [h for h in holders if department_id and h.department_id == department_id]
            return (same or holders)[0].id
        code = _ROLE_BOSS.get(code)
    return None


def validated_staff_password(password):
    validate_password_strength(password)
    return password


def start_onboarding(db, client_id, emp, *, new=False):
    """Give a new starter their checklist and their document requests.

    Both ways in have to do this. Hiring from recruitment used to create the
    employee and stop, so anyone who came through the pipeline arrived with an
    empty checklist and nothing asked of them, while the same person added by
    hand got both.

    `new` is for somebody created in this same transaction: they can have no
    checklist and no requests yet, so neither is looked for. On a database
    across an ocean each look is a third of a second.
    """
    if new or not db.query(models.DBOnboardingItem).filter(
            models.DBOnboardingItem.employee_id == emp.id).count():
        for title, category, assignee in DEFAULT_ONBOARDING_ITEMS:
            db.add(models.DBOnboardingItem(
                client_id=client_id, employee_id=emp.id,
                title=title, category=category, assigned_to=assignee,
            ))
    # Every requirement in one read; the defaults are seeded only when there are none at all.
    rules = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.client_id == client_id,
    ).order_by(models.DBDocumentRequirement.sort_order.asc()).all()
    rules = [r for r in rules if r.is_active] if rules else seed_default_requirements(db, client_id)
    assign_document_requests(db, client_id, emp, rules, existing=set() if new else None)


def onboarding_snapshots(db, emps, today=None):
    """{employee id: onboarding_snapshot} for many people, in two queries however many there are."""
    ids = [e.id for e in emps]
    items, reqs = {i: [] for i in ids}, {i: [] for i in ids}
    if ids:
        for row in db.query(models.DBOnboardingItem).filter(models.DBOnboardingItem.employee_id.in_(ids)).all():
            items[row.employee_id].append(row)
        for row in db.query(models.DBDocumentRequest).filter(models.DBDocumentRequest.employee_id.in_(ids)).all():
            reqs[row.employee_id].append(row)
    return {e.id: onboarding_snapshot(db, e, today, items=items[e.id], reqs=reqs[e.id]) for e in emps}


def onboarding_snapshot(db, emp, today=None, *, items=None, reqs=None):
    """Where one person has got to, worked out from their actual records
    rather than a status column that has to be kept in step. `items` and
    `reqs` are theirs when the caller has already read them for everybody."""
    today = today or datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")

    if items is None:
        items = db.query(models.DBOnboardingItem).filter(
            models.DBOnboardingItem.employee_id == emp.id).all()
    done_items = sum(1 for i in items if i.is_completed)
    overdue_items = sum(
        1 for i in items
        if not i.is_completed and i.due_date and i.due_date < today_str)

    if reqs is None:
        reqs = db.query(models.DBDocumentRequest).filter(
            models.DBDocumentRequest.employee_id == emp.id).all()
    mandatory = [r for r in reqs if r.is_mandatory]
    awaiting_employee = [r.name for r in mandatory if r.status in ("pending", "rejected")]
    # The one thing onboarding always insists on: somebody to call in an emergency (a name and a number).
    has_emergency = bool((emp.emergency_contact or "").strip()) and bool((emp.emergency_phone or "").strip())
    if not has_emergency and emergency_contact_required():
        awaiting_employee.insert(0, "Emergency contact")
    awaiting_hr = [r for r in reqs if r.status == "submitted"]
    approved = [r for r in mandatory if r.status == "approved"]
    overdue_docs = [
        r for r in mandatory if r.status in ("pending", "rejected") and r.due_date and r.due_date < today_str]

    checklist_done = bool(items) and done_items == len(items)
    documents_done = not awaiting_employee and not awaiting_hr

    # Ordered by who is being waited on: the new starter, then HR, then the
    # internal setup nobody outside the company can see.
    if awaiting_employee:
        stage = "paperwork"
    elif awaiting_hr:
        stage = "review"
    elif not checklist_done:
        stage = "setup"
    else:
        stage = "ready"

    started = _parse_date(emp.start_date)
    return {
        "stage": stage,
        "items_total": len(items),
        "items_done": done_items,
        "items_overdue": overdue_items,
        "docs_total": len(mandatory),
        "docs_approved": len(approved),
        "awaiting_employee": awaiting_employee,
        "emergency_contact_given": has_emergency,
        "awaiting_hr": [r.name for r in awaiting_hr],
        "docs_overdue": [r.name for r in overdue_docs],
        "checklist_done": checklist_done,
        "documents_done": documents_done,
        "days_since_start": (today - started).days if started else None,
        "is_blocked": bool(overdue_items or overdue_docs),
    }


def maybe_complete_onboarding(db, emp):
    """Turn a starter into a working employee once nothing is outstanding.

    Completion used to depend on the checklist alone, so somebody could be made
    active with a mandatory document still missing. Both halves now have to be
    finished, and this runs after a checklist change and after a document is
    reviewed, so whichever finishes last is the one that completes it.
    """
    if not emp or emp.status != "onboarding":
        return False
    snap = onboarding_snapshot(db, emp)
    if not (snap["checklist_done"] and snap["documents_done"]):
        return False
    emp.onboarding_complete = True
    emp.status = "active"
    return True


def assert_department_name_free(db, client_id, name, exclude_id=None):
    """Case-insensitive: 'Engineering' and 'engineering' are the same team."""
    query = db.query(models.DBDepartment).filter(
        models.DBDepartment.client_id == client_id,
        sqlfunc.lower(models.DBDepartment.name) == name.lower(),
    )
    if exclude_id:
        query = query.filter(models.DBDepartment.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"A department called '{name}' already exists")


def department_or_404(db, client_id, dept_id):
    dept = db.query(models.DBDepartment).filter(
        models.DBDepartment.id == dept_id, models.DBDepartment.client_id == client_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


def _member_dict(e):
    return {"id": e.id, "name": f"{e.first_name} {e.last_name}".strip(),
            "job_title": e.job_title or "", "email": e.email or "",
            "status": e.status or ""}


def _dept_dict(dept, members, site_ids=()):
    site_ids = sorted(site_ids)
    return {
        "id": dept.id, "name": dept.name, "description": dept.description,
        "color": dept.color or "#00f0ff", "icon": dept.icon or "building",
        "employee_count": len(members), "created_at": dept.created_at,
        "employees": [_member_dict(e) for e in members],
        # The sites it was added to. A department on no site is shown nowhere.
        "site_ids": site_ids,
    }


def departments_to_dicts(db, client_id, depts):
    """Departments with the people in them, in one query however many there are.

    On a database across an ocean every query is a third of a second, so a
    query per department was most of the time the Departments page took.
    """
    ids = [d.id for d in depts]
    by_dept = {i: [] for i in ids}
    if ids:
        for e in db.query(models.DBEmployee).filter(
                models.DBEmployee.client_id == client_id,
                models.DBEmployee.department_id.in_(ids),
        ).order_by(models.DBEmployee.first_name, models.DBEmployee.last_name).all():
            by_dept[e.department_id].append(e)
    sites = department_site_map(db, client_id, ids)
    return [_dept_dict(d, by_dept[d.id], sites.get(d.id, ())) for d in depts]


def department_site_map(db, client_id, dept_ids=None):
    """{department id: [site ids]} for every department that has been added to a
    site. A department missing from it is on no site, and is shown nowhere."""
    q = db.query(models.DBDepartmentSite.department_id, models.DBDepartmentSite.job_id).filter(
        models.DBDepartmentSite.client_id == client_id)
    if dept_ids is not None:
        if not dept_ids:
            return {}
        q = q.filter(models.DBDepartmentSite.department_id.in_(dept_ids))
    out = {}
    for dept_id, job_id in q.all():
        out.setdefault(dept_id, []).append(job_id)
    return out


def set_department_sites(db, client_id, dept, job_ids):
    """Replace the sites this department is on. None leaves them alone; an
    empty list takes it off every site."""
    if job_ids is None:
        return
    wanted = set()
    for raw in job_ids:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    if wanted:
        real = {j.id for j in db.query(models.DBJob.id).filter(
            models.DBJob.client_id == client_id, models.DBJob.id.in_(wanted)).all()}
        wanted &= real
    db.query(models.DBDepartmentSite).filter(
        models.DBDepartmentSite.department_id == dept.id).delete(synchronize_session=False)
    for job_id in sorted(wanted):
        db.add(models.DBDepartmentSite(client_id=client_id, department_id=dept.id, job_id=job_id))


def departments_on_site(db, client_id, depts, site_id):
    """The departments that were added to this site, and only those."""
    sites = department_site_map(db, client_id, [d.id for d in depts])
    return [d for d in depts if site_id in sites.get(d.id, ())]


def department_to_dict(db, dept):
    return departments_to_dicts(db, dept.client_id, [dept])[0]


def pending_department_goals(db, client_id, dept_id):
    return db.query(models.DBDepartmentGoal).filter(
        models.DBDepartmentGoal.department_id == dept_id,
        models.DBDepartmentGoal.client_id == client_id,
        models.DBDepartmentGoal.is_assigned == False,  # noqa: E712
    ).all()


def hand_out_department_goals(db, client_id, emp_id, dept_id, goals):
    """The department's goals nobody has been given yet go to this person."""
    for dg in goals:
        if dg.is_assigned:
            continue
        db.add(models.DBEmployeeGoal(
            client_id=client_id, employee_id=emp_id, department_id=dept_id,
            title=dg.title, description=dg.description,
            target_value=dg.target_value, current_value=0,
            unit=dg.unit, category=dg.category,
            priority=dg.priority, start_date=dg.start_date,
            due_date=dg.due_date, created_by="HR",
        ))
        db.add(models.DBNotification(
            client_id=client_id, employee_id=emp_id,
            title="New Goal Assigned", message=f"HR has assigned you a department goal: {dg.title}",
            type="info",
        ))
        dg.is_assigned = True


def move_to_department(db, client_id, emp, dept_id, *, checked=False, goals=None):
    """Put an employee in a department, or in none, wherever they were before.

    The department's goals not yet handed out go to whoever joins it. Returns
    the department they left (or None), so the caller can record the move.
    A caller moving several people passes `checked` once it has looked the
    department up itself, and the department's pending `goals`, so neither is
    fetched again for every person.
    """
    dept_id = dept_id or None
    old = emp.department_id
    if old == dept_id:
        return old                     # staying put: nothing to look up
    if dept_id is not None and not checked:
        department_or_404(db, client_id, dept_id)
    emp.department_id = dept_id
    if dept_id is None:
        return old
    if goals is None:
        goals = pending_department_goals(db, client_id, dept_id)
    hand_out_department_goals(db, client_id, emp.id, dept_id, goals)
    return old


def org_domain_for(db, client_id) -> str:
    return tenant_setting(db, client_id, ORG_DOMAIN_KEY, "")


def suggest_org_email(db, client_id, first_name, last_name) -> str:
    """first.last@domain, with a number appended if that is already somebody."""
    domain = org_domain_for(db, client_id)
    if not domain:
        return ""
    part = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").strip().lower())
    stem = ".".join(p for p in (part(first_name), part(last_name)) if p) or "staff"
    candidate = f"{stem}@{domain}"
    taken = {
        (email or "").lower()
        for (email,) in db.query(models.DBEmployee.email).filter(
            models.DBEmployee.client_id == client_id).all()
    }
    if candidate not in taken:
        return candidate
    for n in range(2, 100):
        alternative = f"{stem}{n}@{domain}"
        if alternative not in taken:
            return alternative
    return candidate


def assert_employee_code_free(db, client_id, code, exclude_id=None):
    code = (code or "").strip()
    if not code:
        return ""
    query = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id,
        models.DBEmployee.employee_id == code,
    )
    if exclude_id:
        query = query.filter(models.DBEmployee.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=400, detail=f"Employee ID '{code}' is already in use")
    return code


def serialise(db, key):
    """Hold a lock on `key` until this transaction ends, on Postgres.

    "Is this email taken?" then "insert it" is two steps, and two requests
    a moment apart both got through the first before either did the second -
    the same person twice. SQLite already writes one at a time."""
    if db.bind.dialect.name == "postgresql":
        import zlib
        from sqlalchemy import text as sql_text
        db.execute(sql_text("SELECT pg_advisory_xact_lock(:k)"), {"k": zlib.crc32(key.encode("utf-8"))})


def resolve_basic_pay(emp, requested_basic, hours_worked):
    """Work out basic pay for a period.

    An explicit figure from the caller always wins. Otherwise a salaried
    employee gets their salary; an hourly employee is paid hours x rate.
    Falling through to `emp.salary` for hourly staff paid them zero.
    """
    if requested_basic and requested_basic > 0:
        return money(requested_basic)
    if (emp.salary or 0) > 0:
        return money(emp.salary)
    if (emp.hourly_rate or 0) > 0 and (hours_worked or 0) > 0:
        return money(emp.hourly_rate * hours_worked)
    return 0.0


def ytd_totals(db, client_id, emp_id, year=""):
    """Year-to-date totals for one employee - required on most statutory payslip formats. One read, of only the
    columns that are added up."""
    year = year or datetime.now().strftime("%Y")
    P = models.DBPayslip
    slips = db.query(P.period_end, P.pay_date, P.gross_pay, P.tax_amount, P.total_deductions, P.net_pay).filter(
        P.client_id == client_id, P.employee_id == emp_id, P.status != "Void").all()
    in_year = [s for s in slips if (s.period_end or s.pay_date or "").startswith(year)]
    return {
        "year": year,
        "payslip_count": len(in_year),
        "gross_pay": money(sum(s.gross_pay or 0 for s in in_year)),
        "tax_amount": money(sum(s.tax_amount or 0 for s in in_year)),
        "total_deductions": money(sum(s.total_deductions or 0 for s in in_year)),
        "net_pay": money(sum(s.net_pay or 0 for s in in_year)),
    }


def employee_name(emp) -> str:
    if not emp:
        return ""
    return f"{emp.first_name} {emp.last_name}".strip()


def employee_site_ids(db, emp):
    """The job ids this employee is assigned to, or None for no restriction (global access)."""
    from app.services.employee_portal import accessible_job_ids_for
    return accessible_job_ids_for(db, emp)


def employee_may_use_job(db, emp, job_id) -> bool:
    if job_id is None:
        return True
    from app.services.employee_portal import employee_can_access_job
    return employee_can_access_job(db, emp, job_id)



def resolve_employee_job_id(db, emp, raw):
    """A job id from a member of staff, checked against their sites.

    Everything a person books - hours, a cost, an order - comes through here,
    so a site they are not on cannot be reached by typing its id at the API
    even though the picker would never have offered it.
    """
    job_id = resolve_job_id(db, emp.client_id, raw)
    if job_id is not None and not employee_may_use_job(db, emp, job_id):
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to that site. Ask HR to add you to it.")
    return job_id


def set_employee_sites(db, client_id, emp, job_ids, *, new=False):
    """Replace this person's site list. None leaves it alone. Returns the sites
    kept, as (id, number, name), so the answer needs no second look; `new` is
    for somebody created in this transaction, who has no list to clear."""
    if job_ids is None:
        return None
    wanted = set()
    for raw in job_ids:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    jobs = []
    if wanted:
        jobs = db.query(models.DBJob.id, models.DBJob.number, models.DBJob.name).filter(
            models.DBJob.client_id == client_id, models.DBJob.id.in_(wanted)).order_by(models.DBJob.id).all()
    if not new:
        db.query(models.DBEmployeeSite).filter(
            models.DBEmployeeSite.employee_id == emp.id).delete(synchronize_session=False)
    for job in jobs:
        db.add(models.DBEmployeeSite(
            client_id=client_id, employee_id=emp.id, job_id=job.id))
    return jobs


def sites_payload(jobs):
    """The site part of an employee's answer from (id, number, name) rows. None of them is every site."""
    if not jobs:
        return {"site_ids": [], "site_names": [], "all_sites": True}
    return {
        "site_ids": [j.id for j in jobs],
        "site_names": [((j.number + " ") if j.number else "") + (j.name or "") for j in jobs],
        "all_sites": False,
    }


def requirement_to_dict(r):
    return {
        "id": r.id, "name": r.name, "description": r.description or "",
        "doc_type": r.doc_type, "is_mandatory": bool(r.is_mandatory),
        "due_days": r.due_days, "applies_to": r.applies_to,
        "requires_expiry": bool(r.requires_expiry),
        "expiry_reminder_days": r.expiry_reminder_days or 30,
        "has_template": bool(r.has_template),
        "template_file_name": r.template_file_name or "",
        "department_id": r.department_id,
        "department_name": r.department.name if r.department else "",
        "level": r.level or "", "is_active": bool(r.is_active),
        "sort_order": r.sort_order, "created_at": r.created_at,
    }


def with_request_links(query):
    """Document requests with their requirement and their file record joined in, for `request_to_dict`.

    Each row otherwise fetched both on its own - two trips per document across the
    ocean. Neither brings the file itself: that is read only when it is opened."""
    return query.options(joinedload(models.DBDocumentRequest.requirement), joinedload(models.DBDocumentRequest.document))


def request_to_dict(req, include_file=False):
    data = {
        "id": req.id, "employee_id": req.employee_id,
        "requirement_id": req.requirement_id, "document_id": req.document_id,
        "name": req.name, "description": req.description or "",
        "doc_type": req.doc_type, "is_mandatory": bool(req.is_mandatory),
        "due_date": req.due_date or "", "status": req.status,
        "submitted_at": req.submitted_at or "", "reviewed_at": req.reviewed_at or "",
        "reviewed_by": req.reviewed_by or "", "review_note": req.review_note or "",
        "created_at": req.created_at,
    }
    # The employee needs to know a blank form exists before they can fetch it.
    rule = getattr(req, "requirement", None)
    data["has_template"] = bool(rule is not None and rule.has_template)

    doc = req.document
    if doc:
        data["file_name"] = doc.file_name
        data["file_type"] = doc.file_type
        data["file_size"] = doc.file_size or 0
        if include_file:
            data["file_data"] = doc.file_data
    # Overdue and expiry are derived, never stored, so they cannot go stale.
    today = datetime.now().date()
    due = _parse_date(req.due_date)
    data["is_overdue"] = bool(
        due and req.status in ("pending", "rejected") and due < today
    )

    data["requires_expiry"] = bool(getattr(req, "requires_expiry", False))
    data["expires_on"] = getattr(req, "expires_on", "") or ""
    expires = _parse_date(data["expires_on"])
    data["is_expired"] = bool(expires and expires < today)
    data["days_until_expiry"] = (expires - today).days if expires else None
    reminder = 30
    if req.requirement_id:
        rule = getattr(req, "requirement", None)
        if rule is not None:
            reminder = rule.expiry_reminder_days or 30
    data["expiring_soon"] = bool(
        expires and not data["is_expired"] and (expires - today).days <= reminder
    )
    return data


def requirement_applies_to_employee(req, emp):
    if not req.is_active:
        return False
    if req.applies_to == "department":
        return bool(req.department_id) and emp.department_id == req.department_id
    if req.applies_to == "level":
        return bool(req.level) and (emp.level or "") == req.level
    return True


def sync_requirement_to_requests(db, client_id, req):
    """Push a requirement change out to the people already holding it.

    Requests are copies, taken at the moment they were assigned, so an edit in
    HR's settings otherwise never reached anyone already on the system. That is
    how "this document now needs an expiry date" could be switched on and no
    employee was ever asked for one.

    Only outstanding requests are touched. Anything already submitted keeps the
    terms it was handed in under - restating those would reopen settled work and
    could mark an approved document as missing a date nobody was asked for.
    """
    outstanding = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.client_id == client_id,
        models.DBDocumentRequest.requirement_id == req.id,
        models.DBDocumentRequest.status.in_(("pending", "rejected")),
    ).all()
    if not outstanding:
        return 0

    employees = {
        e.id: e for e in db.query(models.DBEmployee).filter(
            models.DBEmployee.id.in_([r.employee_id for r in outstanding])
        ).all()
    }

    touched = 0
    for row in outstanding:
        emp = employees.get(row.employee_id)
        # Narrowing a requirement to a department or level should stop asking
        # the people it no longer covers.
        if emp is not None and not requirement_applies_to_employee(req, emp):
            db.delete(row)
            touched += 1
            continue
        row.name = req.name
        row.description = req.description or ""
        row.doc_type = req.doc_type
        row.is_mandatory = bool(req.is_mandatory)
        row.requires_expiry = bool(req.requires_expiry)
        if emp is not None:
            start = _parse_date(emp.start_date) or datetime.now().date()
            row.due_date = (start + timedelta(days=req.due_days or 0)).strftime("%Y-%m-%d")
        touched += 1
    return touched


def assign_document_requests(db, client_id, emp, requirements=None, existing=None):
    """Create the outstanding requests for one employee, skipping any they
    already have so this is safe to re-run after a department or level change.
    `existing` is the requirement ids they already hold, when the caller knows."""
    if requirements is None:
        requirements = db.query(models.DBDocumentRequirement).filter(
            models.DBDocumentRequirement.client_id == client_id,
            models.DBDocumentRequirement.is_active == True,
        ).order_by(models.DBDocumentRequirement.sort_order.asc()).all()

    if existing is None:
        existing = {
            rid for (rid,) in db.query(models.DBDocumentRequest.requirement_id).filter(
                models.DBDocumentRequest.employee_id == emp.id
            ).all() if rid
        }
    start = _parse_date(emp.start_date) or datetime.now().date()
    created = []
    for req in requirements:
        if req.id in existing or not requirement_applies_to_employee(req, emp):
            continue
        created.append(models.DBDocumentRequest(
            client_id=client_id, employee_id=emp.id, requirement_id=req.id,
            name=req.name, description=req.description or "", doc_type=req.doc_type,
            is_mandatory=bool(req.is_mandatory),
            requires_expiry=bool(req.requires_expiry),
            due_date=(start + timedelta(days=req.due_days or 0)).strftime("%Y-%m-%d"),
        ))
    for row in created:
        db.add(row)
    return created


def seed_default_requirements(db, client_id):
    """First time HR opens the settings there is something sensible to edit,
    rather than an empty screen that looks broken."""
    existing = db.query(models.DBDocumentRequirement).filter(
        models.DBDocumentRequirement.client_id == client_id
    ).count()
    if existing:
        return []
    rows = []
    for order, (name, desc, dtype, mandatory, days) in enumerate(DEFAULT_DOCUMENT_REQUIREMENTS):
        row = models.DBDocumentRequirement(
            client_id=client_id, name=name, description=desc, doc_type=dtype,
            is_mandatory=mandatory, due_days=days, sort_order=order,
        )
        db.add(row)
        rows.append(row)
    # Starting from today's defaults, so the one-time move to them (apply_india_onboarding) has nothing to do here.
    db.add(models.DBSettings(client_id=client_id, key=INDIA_ONBOARDING_KEY, value="1", description="Onboarding documents brought to the current defaults"))
    db.flush()
    return rows


INDIA_ONBOARDING_KEY = "onboarding_documents_v2"


def apply_india_onboarding(db, client_id):
    """Bring one company's onboarding paperwork to the way it is meant to work now, once: an emergency contact is the only
    thing compulsory, and a new starter is asked (not required) to upload Aadhaar, PAN, UAN, a photo, bank details and the
    contract. What HR has set up is kept - nothing is deleted - but every requirement, and every request still waiting, stops
    being mandatory, and the ones the company lacks are added and given to anybody who is still being onboarded.
    Recorded in the company's settings, so HR making a document mandatory again later is not undone at the next start."""
    done = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == INDIA_ONBOARDING_KEY).first()
    if done:
        return 0
    rules = db.query(models.DBDocumentRequirement).filter(models.DBDocumentRequirement.client_id == client_id).all()
    added = []
    if rules:                                              # a company with none gets the defaults when it first needs them
        have = {r.name.strip().lower() for r in rules}
        top = max((r.sort_order or 0 for r in rules), default=0)
        for name, desc, dtype, _mandatory, days in DEFAULT_DOCUMENT_REQUIREMENTS:
            if name.lower() in have or (name == "Aadhaar card" and any("aadhaar" in h or "aadhar" in h for h in have)):
                continue
            top += 1
            row = models.DBDocumentRequirement(client_id=client_id, name=name, description=desc, doc_type=dtype,
                                               is_mandatory=False, due_days=days, sort_order=top)
            db.add(row)
            added.append(row)
        for r in rules:
            r.is_mandatory = False
        db.query(models.DBDocumentRequest).filter(
            models.DBDocumentRequest.client_id == client_id, models.DBDocumentRequest.status.in_(("pending", "rejected")),
        ).update({"is_mandatory": False}, synchronize_session=False)
        db.flush()
        if added:
            for emp in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id, models.DBEmployee.status == "onboarding").all():
                assign_document_requests(db, client_id, emp, added)
    db.add(models.DBSettings(client_id=client_id, key=INDIA_ONBOARDING_KEY, value="1", description="Onboarding documents brought to the current defaults"))
    db.commit()
    return len(added)


def apply_india_onboarding_all():
    from app.db import SessionLocal
    with SessionLocal() as db:
        for (cid,) in db.query(models.DBClient.id).all():
            apply_india_onboarding(db, cid)


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.projects import resolve_job_id
