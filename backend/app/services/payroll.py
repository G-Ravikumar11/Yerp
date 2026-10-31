"""The rules and workings behind the payroll endpoints."""
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models

from app.constants.common import ORDINARY_HOURS_PER_MONTH, OVERTIME_MULTIPLIER, PAYROLL_EXCLUDED_STATUSES
from app.core.currency import money
from app.core.serials import next_sequence_number
from app.core.dates import _parse_date
from app.core.scheduler import scheduled_job
from app.services.employee_portal import attendance_settings_for, leave_balance_for, working_days_between
from app.services.hr import resolve_basic_pay
from app.services.salary_revisions import employee_on, salaries_on
from app.services import lop, statutory
from app.services.income_tax import tds_function
from app.services.salary_structure import apply_statutory, attach_lines, line_totals, structure_lines
from app.services.holidays import custom_holidays
from app.services.wallet_ai import require_credit


def default_overtime_rate(emp):
    """The overtime rate for somebody with none of their own: the hourly rate they have, or twice the ordinary rate their salary makes."""
    if emp.hourly_rate:
        return emp.hourly_rate
    return round((emp.salary or 0) / ORDINARY_HOURS_PER_MONTH * OVERTIME_MULTIPLIER, 2) if emp.salary else 0


def compute_payslip_figures(emp, data, lines=None, tax_fn=None):
    """Single source of truth for payslip arithmetic, used by create, update and
    the bulk payroll run so the three can never drift apart.

    `data` is a dict of the editable inputs. `tax_fn(gross, one_off)`, when given, works out the month's TDS on the new
    regime (services.income_tax.tds_function); a tax amount typed in `data` still wins over it. When the payslip has `lines` from the salary structure, they decide the
    basic pay, the allowances, the PF, the insurance and the other deductions; hours, overtime, bonus and tax still
    come from `data`.
    """
    hours = float(data.get("hours_worked") or 0)
    ot_hours = float(data.get("overtime_hours") or 0)
    ot_rate = float(data.get("overtime_rate") or 0)
    if ot_hours > 0 and ot_rate <= 0:
        ot_rate = default_overtime_rate(emp)

    ot_pay = money(ot_hours * ot_rate) if ot_hours > 0 else 0.0
    bonus = money(data.get("bonus") or 0)
    if lines is not None:
        # Earnings first; PF and ESI follow from the basic and the gross they made, overtime and bonus included.
        apply_statutory(lines, emp, extra_gross=ot_pay + bonus, create=False)
        totals = line_totals(lines)
        basic, allowances = totals["basic_salary"], totals["allowances"]
        insurance, retirement, other = totals["insurance"], totals["retirement"], totals["other_deductions"]
    else:
        basic = resolve_basic_pay(emp, data.get("basic_salary"), hours)
        allowances = money(data.get("allowances") or 0)
        insurance = money(data.get("insurance") or 0)
        retirement = money(data.get("retirement") or 0)
        other = money(data.get("other_deductions") or 0)
    gross = money(basic + ot_pay + bonus + allowances)

    tax = data.get("tax_amount")
    if tax is None or float(tax) <= 0:
        if tax_fn is not None:
            # New-regime TDS on the year's projected salary; bonus and overtime are this month's only, not projected.
            tax = tax_fn(gross, bonus + ot_pay)
        else:
            tax = money(gross * ((emp.tax_rate or 0) / 100)) if (emp.tax_rate or 0) > 0 else 0.0
    else:
        tax = money(tax)

    if lines is None and statutory.applies_to(emp):
        # No salary structure to carry them: PF and ESI are still the law's, unless somebody typed an amount.
        if retirement <= 0:
            retirement = statutory.provident_fund(emp, basic)[0]
        if insurance <= 0:
            insurance = statutory.state_insurance(emp, gross)[0]
    pt = statutory.professional_tax(emp, gross)
    employer = statutory.employer_contributions(emp, basic, gross)

    standing = money(emp.deductions or 0)
    total_deductions = money(tax + insurance + retirement + other + pt + standing)
    net = money(gross - total_deductions)

    return {
        "hours_worked": hours, "overtime_hours": ot_hours, "overtime_rate": money(ot_rate),
        "basic_salary": basic, "overtime_pay": ot_pay, "bonus": bonus, "allowances": allowances,
        "gross_pay": gross, "tax_amount": tax, "insurance": insurance, "retirement": retirement,
        # Deliberately not returned here: this dict is splatted straight into
        # DBPayslip, which has no such column. It is derived on read instead,
        # which also makes payslips issued before this fix reconcile.
        "other_deductions": other, "professional_tax": pt, **employer,
        "total_deductions": total_deductions, "net_pay": net,
    }


def proration_applies(emp):
    """Paid days are worked out for a monthly salary; hourly and weekly pay is for the hours and weeks worked."""
    return (emp.pay_frequency or "monthly") == "monthly" and (emp.salary or 0) > 0


def pay_basis(db, client_id, emp, period_start, period_end, data, use_structure=True, **days_kw):
    """(days, lines) for a payslip being made: the paid days of the period and the structure lines worked out for them.

    `days` is lop.pay_days, or None when paid days do not apply to this person. When there is no structure, a basic pay
    that was not typed is the salary over the paid days, put into `data` for compute_payslip_figures."""
    days = lop.pay_days(db, client_id, emp, period_start, period_end, **days_kw) if proration_applies(emp) else None
    factor = days["factor"] if days else 1.0
    lines = structure_lines(db, client_id, emp, factor=factor) if use_structure else None
    if lines is None and days and factor < 1 and not (data.get("basic_salary") or 0) > 0:
        data["basic_salary"] = lop.prorated(emp.salary, factor)
    return days, lines


def record_days(ps, days):
    """Put a payslip's day counts on it."""
    if days:
        ps.working_days, ps.lop_days, ps.paid_days = days["working_days"], days["lop_days"], days["paid_days"]


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


def pay_period_days(db, client_id, emp, payslip):
    """The day counts printed on a payslip: calendar days in the period, the working days among
    them under the tenant's own working week, and the annual leave left."""
    start = _parse_date(payslip.period_start)
    end = _parse_date(payslip.period_end)
    total = (end - start).days + 1 if start and end and end >= start else 0
    work = working_days_between(start, end, attendance_settings_for(db, client_id), holidays=custom_holidays(db, client_id, start, end)) if total else 0.0
    balance = leave_balance_for(db, emp)["annual_remaining"] if emp else 0.0
    return {"total": total, "work": work, "balance_leaves": balance}


def generate_payroll(db, client_id, period_start, period_end, pay_date, employee_ids=None,
                     include_attendance_hours=True, skip_existing=True):
    """Draft a payslip for everyone on the books for one pay period.

    The one place payroll is run, so the Run payroll button and the monthly
    automatic run can never disagree. Adds the payslips and charges the wallet
    but does not commit: the caller records its own audit entry and commits.
    """
    from app.services import payroll_month
    payroll_month.assert_open(db, client_id, payroll_month.month_of(period_end), payroll_month.month_of(period_start))
    # Anyone still on the books gets paid. New starters sit in "onboarding" and
    # leavers in "offboarding" - both are still owed a payslip; only terminated
    # staff are excluded.
    query = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id,
        models.DBEmployee.status.notin_(PAYROLL_EXCLUDED_STATUSES),
    )
    if employee_ids:
        query = query.filter(models.DBEmployee.id.in_(employee_ids))
    employees = query.all()
    if not employees:
        raise HTTPException(status_code=400, detail="No payable employees match this payroll run")

    created, skipped, warnings, total_net, total_gross = [], [], [], 0.0, 0.0
    next_number = next_sequence_number(db, models.DBPayslip, client_id, "PS-")
    seq = int(next_number.split("-")[1])

    known = salaries_on(db, client_id, [e.id for e in employees], period_end)   # one read for the whole run
    settings = attendance_settings_for(db, client_id)
    start_day, end_day = _parse_date(period_start), _parse_date(period_end)
    holidays = custom_holidays(db, client_id, date(start_day.year, 1, 1), date(end_day.year, 12, 31)) if start_day and end_day else {}
    for emp in employees:
        clash = find_overlapping_payslip(db, client_id, emp.id, period_start, period_end)
        if clash:
            if skip_existing:
                skipped.append({
                    "employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
                    "reason": f"already covered by {clash.number}",
                })
                continue
            raise HTTPException(
                status_code=409,
                detail=f"{emp.first_name} {emp.last_name} already has payslip {clash.number} for this period",
            )

        hours = 0.0
        if include_attendance_hours:
            records = db.query(models.DBAttendance).filter(
                models.DBAttendance.employee_id == emp.id,
                models.DBAttendance.client_id == client_id,
                models.DBAttendance.date >= period_start,
                models.DBAttendance.date <= period_end,
            ).all()
            hours = round(sum(r.total_hours or 0 for r in records), 2)

        ot_hours = round(sum(
            log.hours or 0 for log in db.query(models.DBOvertimeLog).filter(
                models.DBOvertimeLog.employee_id == emp.id,
                models.DBOvertimeLog.client_id == client_id,
                models.DBOvertimeLog.date >= period_start,
                models.DBOvertimeLog.date <= period_end,
                models.DBOvertimeLog.status == "announced",
            ).all()
        ), 2)

        emp = employee_on(db, emp, period_end, known)
        data = {"hours_worked": hours, "overtime_hours": ot_hours, "bonus": emp.bonus or 0, "allowances": emp.allowances or 0}
        days, lines = pay_basis(db, client_id, emp, period_start, period_end, data, settings=settings, holidays=holidays)
        if days and days["working_days"] > 0 and days["active_days"] <= 0:
            skipped.append({"employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
                            "reason": "not employed on any working day of this period"})
            continue
        if days and lines is None:
            data["allowances"] = lop.prorated(data["allowances"], days["factor"])
        figures = compute_payslip_figures(emp, data, lines, tds_function(db, client_id, emp, period_end))
        ps = models.DBPayslip(
            client_id=client_id, employee_id=emp.id, number=f"PS-{seq:04d}",
            period_start=period_start, period_end=period_end, pay_date=pay_date,
            status="Draft", pay_frequency=emp.pay_frequency or "", **figures,
        )
        record_days(ps, days)
        if lines is not None:
            attach_lines(ps, emp, lines)
        seq += 1
        db.add(ps)
        total_net += figures["net_pay"]
        total_gross += figures["gross_pay"]
        created.append({
            "employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
            "number": ps.number, "gross_pay": figures["gross_pay"], "net_pay": figures["net_pay"],
        })
        # A zero-value payslip is almost always missing data (an hourly worker
        # with no attendance logged) rather than a genuine nil payment. Surface
        # it instead of quietly paying someone nothing.
        if figures["gross_pay"] <= 0:
            warnings.append({
                "employee_id": emp.id, "name": f"{emp.first_name} {emp.last_name}",
                "number": ps.number,
                "reason": "no salary and no hours recorded for this period - payslip is zero",
            })

    if created:
        # Priced per payslip; charged once for the batch so a part-run cannot
        # be billed twice.
        require_credit(db, client_id, "payroll_run", len(created),
                       f"{period_start}..{period_end}")
    return {"created": created, "skipped": skipped, "warnings": warnings,
            "total_gross": money(total_gross), "total_net": money(total_net)}


# AUTOMATIC MONTHLY PAYROLL
AUTO_PAYROLL_KEY = "auto_payroll"


def auto_payroll_enabled(db, client_id):
    """On unless the company has switched it off."""
    row = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client_id, models.DBSettings.key == AUTO_PAYROLL_KEY).first()
    return not (row and str(row.value).strip() in ("0", "false", "off"))


def set_auto_payroll(db, client_id, enabled):
    row = db.query(models.DBSettings).filter(
        models.DBSettings.client_id == client_id, models.DBSettings.key == AUTO_PAYROLL_KEY).first()
    value = "1" if enabled else "0"
    if row:
        row.value = value
    else:
        db.add(models.DBSettings(client_id=client_id, key=AUTO_PAYROLL_KEY, value=value))


def last_month_bounds(now):
    """(first day, last day) of the month before `now`, as YYYY-MM-DD strings."""
    last = now.date().replace(day=1) - timedelta(days=1)
    return last.replace(day=1).strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d")


def payroll_month_key(now=None):
    """The month being paid. It changes on the 1st, which is what makes the job due once a month."""
    return last_month_bounds(now or datetime.now())[0][:7]


@scheduled_job("monthly_payroll", payroll_month_key)
def job_monthly_payroll(db, now):
    """Once a month ends, draft everyone's payslips for it.

    Each company that has not switched it off gets payslips dated the last day of
    the month just gone. They are drafts: nothing is marked paid or emailed, so
    the Master still reviews before paying. People who already have a payslip
    covering the month (run by hand) are skipped, and a company that cannot be
    charged for the run is told so rather than half-processed.

    Each payslip is made the way a hand run makes it (generate_payroll): paid days and loss of pay from attendance and
    leave, then PF, ESI and professional tax by each person's own switches. The month is then checked - no hours, no
    PAN, bank, UAN or ESI number, nothing to pay, a big swing from last month, heavy loss of pay - and the ECR and
    ESIC files are built to see who could not go in them; each kind of problem is one notice on the bell.
    """
    from app.core.audit import log_audit
    from app.core.notifications import notify
    from app.services import payroll_checks

    start, end = last_month_bounds(now)
    done = []
    for client in db.query(models.DBClient).filter(models.DBClient.is_active.is_(True)).all():
        if not auto_payroll_enabled(db, client.id):
            continue
        label = datetime.strptime(start, "%Y-%m-%d").strftime("%B %Y")
        try:
            result = generate_payroll(db, client.id, start, end, end)
            if not result["created"]:
                db.rollback()
                continue
            log_audit(db, client.id, "payroll_auto_run", "payslip", None, f"{start}..{end}",
                      f"{len(result['created'])} payslips, net {result['total_net']:.2f}",
                      user_type="system", user_name="Automatic payroll")
            db.commit()                         # the payslips first: notify() commits and rolls back on its own
            try:
                checks = payroll_checks.month_checks(db, client.id, start[:7])
            except Exception:
                # The checks are advice. The payslips are made and saved: a fault in a check must not fail the run
                # or keep HR from being told the month is ready.
                from app.core.config import logger
                logger.exception("Month-end payroll checks failed for client %s", client.id)
                db.rollback()
                checks = {}
            files = checks.get("_files", {})
            notify(db, client.id, "payroll_ready", f"{label} payroll is ready",
                   f"{len(result['created'])} draft payslip(s), net {result['total_net']:.2f}. "
                   f"PF for {files.get('ecr_members', 0)} member(s), {files.get('pf_total', 0)} in all; ESI for "
                   f"{files.get('esic_members', 0)}. Review them in Payroll before approving.",
                   view="payroll-view", severity="action")
            try:
                raised = payroll_checks.announce(db, client.id, start[:7], checks)
            except Exception:
                from app.core.config import logger
                logger.exception("Could not announce the payroll checks for client %s", client.id)
                db.rollback()
                raised = 0
            db.commit()
            done.append(f"{client.id}:{len(result['created'])}" + (f" ({raised} to check)" if raised else ""))
        except HTTPException as exc:
            # Nothing to pay, or the wallet cannot cover it: leave it for a person.
            db.rollback()
            if exc.status_code != 400:
                notify(db, client.id, "payroll_failed", f"{label} payroll could not run automatically",
                       str(exc.detail)[:200] + " Run payroll from the Payroll page.", view="payroll-view", severity="action")
                db.commit()
        except Exception:
            db.rollback()
            raise
    return "payslips drafted for " + (", ".join(done) if done else "no company")
