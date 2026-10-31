"""Full and final settlement: what is owed to somebody leaving, and arrears of a backdated increment.

    final month   the monthly salary over the paid days of the last month (services.lop), unless a payslip already
                  covers that month
    leave         unused annual leave x last drawn basic / 26
    gratuity      15/26 x last drawn basic x years of service, for five years' service or more (Payment of Gratuity
                  Act, s.4); a part year of more than six months counts as a whole one; at most 20 lakh
    arrears       for each payslip already issued: the salary as it now stands for its period, less the salary as it
                  was known when the payslip was made, over that payslip's paid days

"Last drawn basic" is the Basic of the company's salary structure on the last salary (40% unless HR changed it), or the
whole salary for somebody paid without a structure. Dearness allowance is not kept separately here, so it is not added.

Arrears are worked out on the salary and nothing else: PF, ESI and TDS on them are left for the payslip that pays them.
"""
import calendar
from datetime import date
from types import SimpleNamespace

from app import models
from app.core.currency import inr, money
from app.core.dates import _parse_date
from app.services import lop
from app.services.employee_portal import leave_balance_for
from app.services.salary_revisions import salary_on

GRATUITY_MIN_YEARS = 5
GRATUITY_CAP = 2000000.0
DAYS_IN_MONTH_FOR_PAY = 26          # the Act's divisor, also used for a day's pay in leave encashment


def _add_months(day, months):
    year, month = divmod(day.month - 1 + months, 12)
    year, month = day.year + year, month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def years_of_service(start, last):
    """(completed years, years counted): a part year of more than six months counts as a whole one, as the Act counts
    it - the day after the date six months on from the last anniversary is the first that does."""
    if not start or not last or last < start:
        return 0, 0
    years = last.year - start.year - ((last.month, last.day) < (start.month, start.day))
    try:
        anniversary = start.replace(year=start.year + years)
    except ValueError:                                  # joined on 29 February
        anniversary = date(start.year + years, 2, 28)
    return years, years + (1 if last > _add_months(anniversary, 6) else 0)


def gratuity(basic, start, last):
    if not start:
        return {"eligible": False, "completed_years": 0, "years_counted": 0, "amount": 0.0,
                "reason": "There is no joining date on record, so service cannot be counted."}
    completed, counted = years_of_service(start, last)
    if completed < GRATUITY_MIN_YEARS:
        return {"eligible": False, "completed_years": completed, "years_counted": counted, "amount": 0.0,
                "reason": "Gratuity is due after %d years' service; %d completed." % (GRATUITY_MIN_YEARS, completed)}
    amount = min(money(15.0 / DAYS_IN_MONTH_FOR_PAY * basic * counted), GRATUITY_CAP)
    return {"eligible": True, "completed_years": completed, "years_counted": counted, "amount": amount,
            "capped": amount == GRATUITY_CAP, "reason": ""}


def last_basic(db, emp, salary):
    """The Basic of the last salary: the structure's Basic share of it, or all of it without a structure."""
    from app.services.salary_structure import structure_lines
    lines = structure_lines(db, emp.client_id, SimpleNamespace(salary=salary, pay_frequency=emp.pay_frequency), preview=True)
    if lines:
        basic = sum(l["amount"] for l in lines if l["kind"] == "earning" and l["counts_as"] == "basic")
        if basic > 0:
            return money(basic)
    return money(salary)


def salary_known(revs, emp, on, known_by):
    """The salary for the date `on` as it was known at `known_by`: only the increments entered by then count."""
    seen = [r for r in revs if (r.created_at or "") <= known_by]
    later = [r for r in seen if r.effective_date > on]
    if later:
        return later[0].old_salary
    if seen:
        return seen[-1].new_salary
    return revs[0].old_salary if revs else emp.salary


def arrears(db, emp):
    """Payslips already issued that a backdated increment says were underpaid, with the amount each is short."""
    R, P = models.DBSalaryRevision, models.DBPayslip
    revs = db.query(R).filter(R.client_id == emp.client_id, R.employee_id == emp.id).order_by(R.effective_date, R.id).all()
    if not revs:
        return {"rows": [], "total": 0.0}
    rows = []
    for ps in db.query(P).filter(P.client_id == emp.client_id, P.employee_id == emp.id, P.status != "Void",
                                 P.period_end >= revs[0].effective_date).order_by(P.period_end).all():
        then = salary_known(revs, emp, ps.period_end, ps.created_at or "")
        now = salary_on(db, emp, ps.period_end)
        if money(now) == money(then):
            continue
        share = (ps.paid_days / ps.working_days) if (ps.working_days or 0) > 0 else 1.0
        rows.append({"payslip": ps.number, "period_end": ps.period_end, "paid_on_salary": money(then),
                     "salary_now": money(now), "share_of_month": round(share, 4), "amount": money((now - then) * share)})
    return {"rows": rows, "total": money(sum(r["amount"] for r in rows))}


def final_month(db, emp, last):
    """The last month's salary, unless a payslip already covers it."""
    month_start = last.replace(day=1)
    P = models.DBPayslip
    covered = db.query(P).filter(P.client_id == emp.client_id, P.employee_id == emp.id, P.status != "Void",
                                 P.period_end >= month_start.isoformat()).first()
    if covered:
        return {"amount": 0.0, "covered_by": covered.number, "paid_days": covered.paid_days, "working_days": covered.working_days}
    leaving = SimpleNamespace(**{c: getattr(emp, c) for c in ("id", "start_date", "annual_leave_entitlement",
                                                             "sick_leave_entitlement", "client_id")}, end_date=last.isoformat())
    month_end = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    days = lop.pay_days(db, emp.client_id, leaving, month_start.isoformat(), month_end.isoformat(),
                       today=min(last, date.today()))          # a day not yet come cannot be an absence
    salary = salary_on(db, emp, last.isoformat())
    return {"amount": lop.prorated(salary, days["factor"]), "covered_by": "", "paid_days": days["paid_days"],
            "working_days": days["working_days"], "lop_days": days["lop_days"]}


def settle(db, emp, last_day=None):
    """The full and final settlement for somebody whose last day is `last_day` (their end date, unless given)."""
    last = _parse_date(last_day or emp.end_date or "")
    if not last:
        raise ValueError("Give the last working day.")
    start = _parse_date(emp.start_date or "")
    salary = salary_on(db, emp, last.isoformat())
    basic = last_basic(db, emp, salary)
    leave = leave_balance_for(db, emp, for_year=last.year)["annual_remaining"]
    day_pay = money(basic / DAYS_IN_MONTH_FOR_PAY)
    final = final_month(db, emp, last)
    grat = gratuity(basic, start, last)
    arr = arrears(db, emp)
    encash = money(leave * day_pay)
    parts = [
        {"item": "Salary for the final month", "amount": final["amount"],
         "note": ("Already paid on %s" % final["covered_by"]) if final["covered_by"] else
                 "%g of %g working days" % (final["paid_days"], final["working_days"])},
        {"item": "Leave encashment", "amount": encash, "note": "%g unused day(s) at %s a day (basic / %d)" % (leave, inr(day_pay), DAYS_IN_MONTH_FOR_PAY)},
        {"item": "Gratuity", "amount": grat["amount"], "note": grat["reason"] or "15/26 x %s x %d year(s)%s" % (
            inr(basic), grat["years_counted"], " (capped)" if grat.get("capped") else "")},
        {"item": "Arrears of salary", "amount": arr["total"], "note": "%d payslip(s) short after a backdated increment" % len(arr["rows"])
         if arr["rows"] else "None"},
    ]
    return {"employee_id": emp.id, "last_day": last.isoformat(), "start_date": emp.start_date or "",
            "monthly_salary": money(salary), "last_basic": basic, "service": {"completed_years": grat["completed_years"],
                                                                                "years_counted": grat["years_counted"]},
            "final_month": final, "leave": {"unused_days": leave, "day_pay": day_pay, "amount": encash},
            "gratuity": grat, "arrears": arr, "parts": parts, "total": money(sum(p["amount"] for p in parts))}
