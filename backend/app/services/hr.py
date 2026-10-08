"""The rules and workings behind the hr endpoints."""
import re
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func as sqlfunc

from app import models

from app.constants.hr import DEFAULT_DOCUMENT_REQUIREMENTS, DEFAULT_ONBOARDING_ITEMS, ORG_DOMAIN_KEY
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.security import validate_password_strength
from app.core.tenant_settings import tenant_setting


def validated_staff_password(password):
    validate_password_strength(password)
    return password


def start_onboarding(db, client_id, emp):
    """Give a new starter their checklist and their document requests.

    Both ways in have to do this. Hiring from recruitment used to create the
    employee and stop, so anyone who came through the pipeline arrived with an
    empty checklist and nothing asked of them, while the same person added by
    hand got both.
    """
    existing = db.query(models.DBOnboardingItem).filter(
        models.DBOnboardingItem.employee_id == emp.id).count()
    if not existing:
        for title, category, assignee in DEFAULT_ONBOARDING_ITEMS:
            db.add(models.DBOnboardingItem(
                client_id=client_id, employee_id=emp.id,
                title=title, category=category, assigned_to=assignee,
            ))
    seed_default_requirements(db, client_id)
    assign_document_requests(db, client_id, emp)


def onboarding_snapshot(db, emp, today=None):
    """Where one person has got to, worked out from their actual records
    rather than a status column that has to be kept in step."""
    today = today or datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")

    items = db.query(models.DBOnboardingItem).filter(
        models.DBOnboardingItem.employee_id == emp.id).all()
    done_items = sum(1 for i in items if i.is_completed)
    overdue_items = sum(
        1 for i in items
        if not i.is_completed and i.due_date and i.due_date < today_str)

    reqs = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.employee_id == emp.id).all()
    mandatory = [r for r in reqs if r.is_mandatory]
    awaiting_employee = [r for r in mandatory if r.status in ("pending", "rejected")]
    awaiting_hr = [r for r in reqs if r.status == "submitted"]
    approved = [r for r in mandatory if r.status == "approved"]
    overdue_docs = [
        r for r in awaiting_employee if r.due_date and r.due_date < today_str]

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
        "awaiting_employee": [r.name for r in awaiting_employee],
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
        (e.email or "").lower()
        for e in db.query(models.DBEmployee).filter(
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


def employee_name(emp) -> str:
    if not emp:
        return ""
    return f"{emp.first_name} {emp.last_name}".strip()


def employee_site_ids(db, emp):
    """The job ids this employee is assigned to, or None for no restriction.

    None rather than an empty set on purpose: "assigned to nothing" and
    "allowed everything" are different answers, and returning an empty set for
    both would lock every existing employee out of every job the moment this
    shipped.
    """
    rows = db.query(models.DBEmployeeSite.job_id).filter(
        models.DBEmployeeSite.employee_id == emp.id).all()
    if not rows:
        return None
    return {r[0] for r in rows}


def employee_may_use_job(db, emp, job_id) -> bool:
    if job_id is None:
        return True
    allowed = employee_site_ids(db, emp)
    return allowed is None or job_id in allowed


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


def set_employee_sites(db, client_id, emp, job_ids):
    """Replace this person's site list. None leaves it alone."""
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
        wanted = {j for j in wanted if j in real}
    db.query(models.DBEmployeeSite).filter(
        models.DBEmployeeSite.employee_id == emp.id).delete(synchronize_session=False)
    for job_id in sorted(wanted):
        db.add(models.DBEmployeeSite(
            client_id=client_id, employee_id=emp.id, job_id=job_id))


def employee_sites_payload(db, emp):
    rows = db.query(models.DBEmployeeSite.job_id).filter(
        models.DBEmployeeSite.employee_id == emp.id).all()
    ids = [r[0] for r in rows]
    if not ids:
        return {"site_ids": [], "site_names": [], "all_sites": True}
    jobs = db.query(models.DBJob).filter(models.DBJob.id.in_(ids)).all()
    return {
        "site_ids": ids,
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
        "has_template": bool(r.template_file_data),
        "template_file_name": r.template_file_name or "",
        "department_id": r.department_id,
        "department_name": r.department.name if r.department else "",
        "level": r.level or "", "is_active": bool(r.is_active),
        "sort_order": r.sort_order, "created_at": r.created_at,
    }


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
    data["has_template"] = bool(rule is not None and rule.template_file_data)

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


def assign_document_requests(db, client_id, emp, requirements=None):
    """Create the outstanding requests for one employee, skipping any they
    already have so this is safe to re-run after a department or level change."""
    if requirements is None:
        requirements = db.query(models.DBDocumentRequirement).filter(
            models.DBDocumentRequirement.client_id == client_id,
            models.DBDocumentRequirement.is_active == True,
        ).order_by(models.DBDocumentRequirement.sort_order.asc()).all()

    existing = {
        r.requirement_id for r in db.query(models.DBDocumentRequest).filter(
            models.DBDocumentRequest.employee_id == emp.id
        ).all() if r.requirement_id
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
    db.flush()
    return rows


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.projects import resolve_job_id
