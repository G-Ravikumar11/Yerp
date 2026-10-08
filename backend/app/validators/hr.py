"""Checks on what is entered for hr."""
import re

from fastapi import HTTPException
from sqlalchemy import func as sqlfunc

from app import models

from app.constants.hr import EMPLOYEE_MONEY_FIELDS, PERMISSION_ROLE_CODES, _DOMAIN_RE
from app.core.permissions import DEFAULT_PERMISSION_ROLE, LEVEL_CODES, ROLE_CODES


def validate_permission_role(role):
    role = (role or "").strip().lower()
    if not role:
        return DEFAULT_PERMISSION_ROLE
    if role not in PERMISSION_ROLE_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown access level '{role}'. Expected one of: "
                   f"{', '.join(sorted(PERMISSION_ROLE_CODES))}",
        )
    return role


def validate_level(level):
    level = (level or "").strip().upper()
    if level and level not in LEVEL_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown level '{level}'. Expected one of: {', '.join(sorted(LEVEL_CODES))}",
        )
    return level


def validate_role(role):
    role = (role or "").strip().lower()
    if role and role not in ROLE_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role '{role}'. Expected one of: {', '.join(sorted(ROLE_CODES))}",
        )
    return role or "employee"


def validate_manager(db, client_id, employee_id, manager_id):
    """A reporting line must stay a tree.

    Without this an admin could point A at B and B at A; the org chart renderer
    walks children recursively and would spin forever on the cycle.
    """
    if not manager_id:
        return None
    if employee_id and manager_id == employee_id:
        raise HTTPException(status_code=400, detail="An employee cannot report to themselves")
    manager = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == manager_id, models.DBEmployee.client_id == client_id
    ).first()
    if not manager:
        raise HTTPException(status_code=400, detail="Manager not found")
    # Walk up from the proposed manager; hitting this employee means a cycle.
    seen = set()
    cursor = manager
    while cursor and cursor.reports_to:
        if cursor.reports_to in seen:
            break  # pre-existing loop in the data; don't spin
        seen.add(cursor.reports_to)
        if employee_id and cursor.reports_to == employee_id:
            raise HTTPException(
                status_code=400,
                detail=f"{manager.first_name} {manager.last_name} already reports to this employee, "
                       "so this would create a reporting loop",
            )
        cursor = db.query(models.DBEmployee).filter(models.DBEmployee.id == cursor.reports_to).first()
    return manager_id


# These fields flow straight into payroll and the employee login, so bad values
# here surface later as wrong pay or an account nobody can sign into.
def clean_department_name(name):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A department name is required")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="Department name must be 80 characters or fewer")
    return name


def clean_org_domain(value: str) -> str:
    """Accept what people actually paste - '@acme.co.uk', 'https://acme.co.uk/'
    - and store the bare domain."""
    domain = (value or "").strip().lower()
    if not domain:
        return ""
    domain = re.sub(r"^https?://", "", domain).strip("/")
    domain = domain.split("/")[0].lstrip("@")
    if domain.startswith("www."):
        domain = domain[4:]
    if not _DOMAIN_RE.match(domain):
        raise HTTPException(
            status_code=400,
            detail=f"'{value}' does not look like a domain. Try something like acme.co.uk.")
    return domain


def clean_employee_email(db, client_id, email, exclude_id=None, required=True):
    email = (email or "").strip().lower()
    if not email:
        # A mason, an operator or a storekeeper is on the payroll without
        # ever signing in, and often has no email at all. Only somebody being
        # given a login needs one - the login is by email.
        if not required:
            return ""
        raise HTTPException(status_code=400, detail="An email address is required to sign in")
    if not validate_email_address(email):
        raise HTTPException(status_code=400, detail=f"'{email}' is not a valid email address")
    domain = org_domain_for(db, client_id)
    if domain and not email.endswith("@" + domain):
        raise HTTPException(
            status_code=400,
            detail=f"Staff accounts use your organisation's address. "
                   f"'{email}' should end in @{domain}.")
    query = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id,
        sqlfunc.lower(models.DBEmployee.email) == email,
    )
    if exclude_id:
        query = query.filter(models.DBEmployee.id != exclude_id)
    if query.first():
        # Case-variant duplicates also make the employee login ambiguous,
        # because it matches on email and takes the first row.
        raise HTTPException(status_code=400, detail="An employee with this email already exists")
    return email


def clean_person_name(value, label):
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if len(value) > 80:
        raise HTTPException(status_code=400, detail=f"{label} must be 80 characters or fewer")
    return value


def validate_employee_money(values):
    """Reject negatives and an out-of-range tax rate.

    A 500% tax rate previously produced a payslip with a large negative net,
    i.e. a payslip saying the employee owes the company money.
    """
    for field, label in EMPLOYEE_MONEY_FIELDS.items():
        if field not in values or values[field] is None:
            continue
        try:
            amount = float(values[field])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{label} must be a number")
        if amount < 0:
            raise HTTPException(status_code=400, detail=f"{label} cannot be negative")
        if amount > 100_000_000:
            raise HTTPException(status_code=400, detail=f"{label} is unrealistically large")
    if values.get("tax_rate") is not None:
        try:
            rate = float(values["tax_rate"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Tax rate must be a number")
        if rate < 0 or rate > 100:
            raise HTTPException(status_code=400, detail="Tax rate must be between 0 and 100 percent")


def validate_requirement(body, db, client_id):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A document name is required")
    if len(name) > 120:
        raise HTTPException(status_code=400, detail="Document name must be 120 characters or fewer")
    applies = (body.applies_to or "all").strip().lower()
    if applies not in ("all", "department", "level"):
        raise HTTPException(status_code=400, detail="Applies to must be all, department or level")
    try:
        due_days = int(body.due_days if body.due_days is not None else 7)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Due days must be a whole number")
    if due_days < 0 or due_days > 365:
        raise HTTPException(status_code=400, detail="Due days must be between 0 and 365")
    if applies == "department":
        if not body.department_id:
            raise HTTPException(status_code=400, detail="Choose a department for this rule")
        dept = db.query(models.DBDepartment).filter(
            models.DBDepartment.id == body.department_id,
            models.DBDepartment.client_id == client_id,
        ).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Department not found")
    level = validate_level(body.level)
    if applies == "level" and not level:
        raise HTTPException(status_code=400, detail="Choose a level for this rule")
    try:
        reminder = int(body.expiry_reminder_days if body.expiry_reminder_days is not None else 30)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Expiry reminder must be a whole number of days")
    if reminder < 0 or reminder > 365:
        raise HTTPException(status_code=400, detail="Expiry reminder must be between 0 and 365 days")
    return name, applies, due_days, level, reminder


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.hr import org_domain_for
from app.validators.common import validate_email_address
