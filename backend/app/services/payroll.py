"""The rules and workings behind the payroll endpoints."""
from app import models

from app.core.currency import money
from app.core.dates import _parse_date
from app.services.hr import resolve_basic_pay


def compute_payslip_figures(emp, data):
    """Single source of truth for payslip arithmetic, used by create, update and
    the bulk payroll run so the three can never drift apart.

    `data` is a dict of the editable inputs.
    """
    hours = float(data.get("hours_worked") or 0)
    ot_hours = float(data.get("overtime_hours") or 0)
    ot_rate = float(data.get("overtime_rate") or 0)
    if ot_hours > 0 and ot_rate <= 0:
        # Fall back to a 1.5x rate derived from the employee's own pay.
        ot_rate = emp.hourly_rate or (round((emp.salary or 0) / 160 * 1.5, 2) if emp.salary else 0)

    basic = resolve_basic_pay(emp, data.get("basic_salary"), hours)
    ot_pay = money(ot_hours * ot_rate) if ot_hours > 0 else 0.0
    bonus = money(data.get("bonus") or 0)
    allowances = money(data.get("allowances") or 0)
    gross = money(basic + ot_pay + bonus + allowances)

    tax = data.get("tax_amount")
    if tax is None or float(tax) <= 0:
        tax = money(gross * ((emp.tax_rate or 0) / 100)) if (emp.tax_rate or 0) > 0 else 0.0
    else:
        tax = money(tax)

    insurance = money(data.get("insurance") or 0)
    retirement = money(data.get("retirement") or 0)
    other = money(data.get("other_deductions") or 0)
    standing = money(emp.deductions or 0)
    total_deductions = money(tax + insurance + retirement + other + standing)
    net = money(gross - total_deductions)

    return {
        "hours_worked": hours, "overtime_hours": ot_hours, "overtime_rate": money(ot_rate),
        "basic_salary": basic, "overtime_pay": ot_pay, "bonus": bonus, "allowances": allowances,
        "gross_pay": gross, "tax_amount": tax, "insurance": insurance, "retirement": retirement,
        # Deliberately not returned here: this dict is splatted straight into
        # DBPayslip, which has no such column. It is derived on read instead,
        # which also makes payslips issued before this fix reconcile.
        "other_deductions": other, "total_deductions": total_deductions, "net_pay": net,
    }


def find_overlapping_payslip(db, client_id, employee_id, period_start, period_end, exclude_id=None):
    """Guard against paying the same person twice for the same period."""
    start = _parse_date(period_start)
    end = _parse_date(period_end)
    if not start or not end:
        return None
    query = db.query(models.DBPayslip).filter(
        models.DBPayslip.client_id == client_id,
        models.DBPayslip.employee_id == employee_id,
        models.DBPayslip.status != "Void",
    )
    if exclude_id:
        query = query.filter(models.DBPayslip.id != exclude_id)
    for existing in query.all():
        e_start = _parse_date(existing.period_start)
        e_end = _parse_date(existing.period_end)
        if e_start and e_end and start <= e_end and e_start <= end:
            return existing
    return None
