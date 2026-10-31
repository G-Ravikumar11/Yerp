"""Income tax on salary under the new regime (section 115BAC), and the TDS a month's payslip deducts.

    taxable income = projected salary for the year - standard deduction (75,000)
    tax            = slab tax, less the section 87A rebate (nil tax up to 12 lakh, with marginal relief just above it),
                     plus surcharge on high incomes, plus 4% health and education cess
    this month TDS = (projected tax for the year - TDS already deducted this year) / months left in the year

The year is the financial year, April to March. The salary for the year is what has been paid in it so far, plus this
month's, plus this month's regular pay (without bonus or overtime, which do not recur) for each month still to come.

Professional tax is not deducted: the new regime allows only the standard deduction against salary. Somebody with a flat
tax_rate on their record keeps it - that is HR's own override - and only those at 0 are taxed on the regime.

The slabs are kept per financial year. FY 2026-27 is taken to be the same as FY 2025-26 until a Finance Act changes it.
"""
from datetime import date

from app import models
from app.core.currency import money
from app.core.dates import _parse_date

STANDARD_DEDUCTION = 75000.0
REBATE_LIMIT = 1200000.0           # 87A: no tax at all on taxable income up to this
REBATE_MAX = 60000.0
CESS_RATE = 4.0

# (upper limit of the slab, rate %). The last slab has no limit.
SLABS_2025 = ((400000, 0), (800000, 5), (1200000, 10), (1600000, 15), (2000000, 20), (2400000, 25), (float("inf"), 30))
SLABS = {2025: SLABS_2025, 2026: SLABS_2025}
# (income above, surcharge %). The new regime stops at 25%.
SURCHARGE = ((20000000, 25), (10000000, 15), (5000000, 10))


def fy_start_year(on):
    """The year a financial year begins in: 2025 for anything from April 2025 to March 2026."""
    d = _parse_date(on) if isinstance(on, str) else on
    return d.year if d.month >= 4 else d.year - 1


def fy_label(start_year):
    return "%d-%02d" % (start_year, (start_year + 1) % 100)


def fy_bounds(start_year):
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def months_left(on):
    """Months from this one to March, both counted: 12 in April, 1 in March."""
    d = _parse_date(on) if isinstance(on, str) else on
    return (3 - d.month) % 12 + 1


def slabs_for(start_year):
    """A year's own slabs; failing that, the latest year's before it (a new year carries on until it is told otherwise)."""
    if start_year in SLABS:
        return SLABS[start_year]
    earlier = [k for k in SLABS if k <= start_year]
    return SLABS[max(earlier)] if earlier else SLABS_2025


def slab_tax(taxable, start_year=2025):
    slabs = slabs_for(start_year)
    tax, lower = 0.0, 0.0
    for upper, rate in slabs:
        if taxable > lower:
            tax += (min(taxable, upper) - lower) * rate / 100.0
        lower = upper
    return tax


def annual_tax(gross_salary, start_year=2025):
    """The year's tax on a year's salary, worked through: a dict with each step, for Form 16 and for the TDS."""
    taxable = max(float(gross_salary or 0) - STANDARD_DEDUCTION, 0.0)
    taxable = float(int(taxable / 10 + 0.5) * 10)                   # rounded to the nearest ten rupees (section 288A)
    tax = slab_tax(taxable, start_year)
    rebate = 0.0
    if taxable <= REBATE_LIMIT:
        rebate = min(tax, REBATE_MAX)
    elif tax > taxable - REBATE_LIMIT:
        rebate = tax - (taxable - REBATE_LIMIT)                    # marginal relief: no more tax than income over 12 lakh
    after_rebate = tax - rebate
    surcharge = 0.0
    for above, rate in SURCHARGE:
        if taxable > above:
            surcharge = after_rebate * rate / 100.0
            break
    cess = (after_rebate + surcharge) * CESS_RATE / 100.0
    total = float(int(after_rebate + surcharge + cess + 0.5))       # whole rupees (section 288B)
    return {"gross": money(gross_salary), "standard_deduction": STANDARD_DEDUCTION, "taxable": taxable,
            "slab_tax": money(tax), "rebate_87a": money(rebate), "surcharge": money(surcharge), "cess": money(cess),
            "total_tax": total}


def uses_regime(emp):
    """Taxed on the regime: a monthly salary, and no flat rate of HR's own on the record."""
    return ((emp.pay_frequency or "monthly") == "monthly" and (emp.salary or 0) > 0
            and not (emp.tax_rate or 0) > 0)


def earlier_in_year(db, client_id, emp_id, period_end, exclude_id=None):
    """(gross, TDS) on this employee's payslips earlier in the same financial year."""
    start_year = fy_start_year(period_end)
    fy_start, _ = fy_bounds(start_year)
    month_start = _parse_date(period_end).replace(day=1)
    P = models.DBPayslip
    q = db.query(P.gross_pay, P.tax_amount).filter(
        P.client_id == client_id, P.employee_id == emp_id, P.status != "Void",
        P.period_end >= fy_start.isoformat(), P.period_end < month_start.isoformat())
    if exclude_id:
        q = q.filter(P.id != exclude_id)
    rows = q.all()
    return sum(r.gross_pay or 0 for r in rows), sum(r.tax_amount or 0 for r in rows)


def tds_for_month(paid_gross, paid_tds, gross, one_off, period_end):
    """This month's TDS: the year's projected tax less what has been deducted, spread over the months left."""
    left = months_left(period_end)
    regular = max(float(gross or 0) - float(one_off or 0), 0.0)
    projected = float(paid_gross) + float(gross or 0) + regular * (left - 1)
    year_tax = annual_tax(projected, fy_start_year(period_end))["total_tax"]
    return money(max(year_tax - float(paid_tds or 0), 0.0) / left)


def tds_function(db, client_id, emp, period_end, exclude_id=None):
    """A function of (gross, one-off pay) giving this month's TDS for this person, or None when the regime does not
    apply to them (compute_payslip_figures then falls back to their flat rate)."""
    if not period_end or not _parse_date(period_end) or not uses_regime(emp):
        return None
    paid_gross, paid_tds = earlier_in_year(db, client_id, emp.id, period_end, exclude_id)
    return lambda gross, one_off=0.0: tds_for_month(paid_gross, paid_tds, gross, one_off, period_end)
