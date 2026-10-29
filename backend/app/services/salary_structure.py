"""The salary structure: what a month's pay is made of, kept by HR in the database.

A company lists its components once - Basic is 40% of the monthly salary, Conveyance 10%, PF 12% - and every payslip made
afterwards gets its own lines worked out from that list and saved on it. Nothing is recalculated when a payslip is viewed
or downloaded, and changing the structure never touches a payslip already issued.
"""
from app import models
from app.core.currency import money

# What a company starts with, taken from the office's own payslip sheet: name, kind, basis, percent, where it counts.
# HRA and Spcl allowance have no formula there, so they are typed by HR on each payslip.
DEFAULT_COMPONENTS = (
    ("Basic", "earning", "percent", 40.0, "basic"),
    ("HRA", "earning", "manual", 0.0, "allowance"),
    ("Conveyance", "earning", "percent", 10.0, "allowance"),
    ("Medical allowance", "earning", "percent", 20.0, "allowance"),
    ("Spcl allowance", "earning", "manual", 0.0, "allowance"),
    ("PF", "deduction", "percent", 12.0, "pf"),
)
SEEDED_KEY = "salary_structure_seeded"
KINDS = ("earning", "deduction")
BASES = ("percent", "manual")
COUNTS_AS = {"earning": ("basic", "allowance"), "deduction": ("pf", "esi", "other")}


def default_counts_as(kind):
    return "allowance" if kind == "earning" else "other"


def ensure_structure(db, client_id):
    """Gives a company the starting list the first time it is needed, and never again: a company that removes
    everything is left with nothing rather than having the list put back."""
    mark = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client_id, models.DBSettings.key == SEEDED_KEY).first()
    if mark:
        return
    for order, (name, kind, basis, percent, counts_as) in enumerate(DEFAULT_COMPONENTS, start=1):
        db.add(models.DBPayComponent(client_id=client_id, name=name, kind=kind, basis=basis, percent=percent,
                                     counts_as=counts_as, sort_order=order, is_active=True))
    db.add(models.DBSettings(client_id=client_id, key=SEEDED_KEY, value="1"))
    db.flush()


def components(db, client_id, active_only=False):
    query = db.query(models.DBPayComponent).filter(models.DBPayComponent.client_id == client_id)
    if active_only:
        query = query.filter(models.DBPayComponent.is_active.is_(True))
    return query.order_by(models.DBPayComponent.sort_order, models.DBPayComponent.id).all()


def component_amount(component, base):
    return money(base * (component.percent or 0) / 100.0) if component.basis == "percent" else 0.0


def _is_seeded(db, client_id):
    return db.query(models.DBSettings.id).filter(
        models.DBSettings.client_id == client_id, models.DBSettings.key == SEEDED_KEY).first() is not None


def structure_lines(db, client_id, emp, preview=False):
    """The lines a new payslip gets for this employee, or None when the structure does not apply to them: it is worked out
    from a monthly salary, so somebody paid by the hour or the week is paid the way they always were.

    `preview` only reads: a company that has no list yet is shown the starting one without it being saved."""
    if (emp.salary or 0) <= 0 or (emp.pay_frequency or "monthly") != "monthly":
        return None
    if preview and not _is_seeded(db, client_id):
        return [{"component_id": None, "name": n, "kind": k, "basis": b, "percent": pc, "counts_as": ca,
                 "amount": money(emp.salary * pc / 100.0) if b == "percent" else 0.0, "sort_order": i}
                for i, (n, k, b, pc, ca) in enumerate(DEFAULT_COMPONENTS, start=1)]
    if not preview:
        ensure_structure(db, client_id)
    active = components(db, client_id, active_only=True)
    if not active:
        return None
    return [{"component_id": c.id, "name": c.name, "kind": c.kind, "basis": c.basis, "percent": c.percent or 0.0,
             "counts_as": c.counts_as or default_counts_as(c.kind), "amount": component_amount(c, emp.salary),
             "sort_order": i} for i, c in enumerate(active, start=1)]


def _get(line, key):
    return line[key] if isinstance(line, dict) else getattr(line, key)


def line_totals(lines):
    """The payslip's own totals that a set of lines adds up to."""
    out = {"basic_salary": 0.0, "allowances": 0.0, "retirement": 0.0, "insurance": 0.0, "other_deductions": 0.0}
    for line in lines:
        amount, kind, counts = float(_get(line, "amount") or 0), _get(line, "kind"), _get(line, "counts_as")
        if kind == "earning":
            out["basic_salary" if counts == "basic" else "allowances"] += amount
        else:
            out[{"pf": "retirement", "esi": "insurance"}.get(counts, "other_deductions")] += amount
    return {k: money(v) for k, v in out.items()}


def attach_lines(ps, emp, lines):
    """Gives a payslip its own lines, replacing any it had."""
    ps.lines = [models.DBPayslipLine(client_id=ps.client_id, employee_id=emp.id, **{k: v for k, v in line.items()})
                for line in lines]
