"""Statutory deductions on a monthly payslip: Provident Fund, Employee State Insurance and Professional Tax.

Pure arithmetic over an employee's switches (pf_enabled, esi_enabled, pt_enabled, pt_state) and the month's figures, so
the payslip, the salary-structure preview and the tests all work it out the same way. These rules are for a month's
pay: somebody paid weekly or by the day is not given them (see applies_to).
"""
from app.core.currency import money

PF_RATE = 12.0                 # employee's share, and the employer's in all, of the PF basic
PF_WAGE_CEILING = 15000.0      # the PF basic counts only up to this: at most 1,800 a month from the employee
EPS_RATE = 8.33                # the employer's pension share of the PF basic ...
EPS_MAX = 1250.0               # ... never more than this a month
ESI_GROSS_LIMIT = 21000.0      # ESI applies to a month's gross up to and including this
ESI_EMPLOYEE_RATE = 0.75
ESI_EMPLOYER_RATE = 3.25

PT_STATES = ("TS", "AP")
PT_STATE_NAMES = {"TS": "Telangana", "AP": "Andhra Pradesh"}
# (gross up to and including, tax). Telangana and Andhra Pradesh share one slab.
PT_SLABS = {
    "TS": ((15000.0, 0.0), (20000.0, 150.0), (float("inf"), 200.0)),
    "AP": ((15000.0, 0.0), (20000.0, 150.0), (float("inf"), 200.0)),
}
DEFAULT_PT_STATE = "TS"


def _on(emp, flag):
    """A switch on the employee; an employee record from before the switches existed has them on."""
    value = getattr(emp, flag, None)
    return True if value is None else bool(value)


def applies_to(emp):
    """The statutory deductions are a monthly reckoning on a monthly salary: hourly, weekly and fortnightly pay is left as typed."""
    return (getattr(emp, "pay_frequency", None) or "monthly") == "monthly" and (getattr(emp, "salary", 0) or 0) > 0


def pf_basic(basic):
    """The part of the basic pay PF is worked on."""
    return min(max(float(basic or 0), 0.0), PF_WAGE_CEILING)


def provident_fund(emp, basic):
    """(employee PF, employer EPF, employer EPS) for the month, on the basic pay only and never the gross."""
    if not _on(emp, "pf_enabled") or not applies_to(emp):
        return 0.0, 0.0, 0.0
    wage = pf_basic(basic)
    employee = money(wage * PF_RATE / 100.0)
    eps = min(money(wage * EPS_RATE / 100.0), EPS_MAX)
    epf = money(wage * PF_RATE / 100.0 - eps)          # what is left of the employer's 12%: 3.67% until the pension is capped
    return employee, epf, eps


def esi_applies(emp, gross):
    return _on(emp, "esi_enabled") and applies_to(emp) and 0 < float(gross or 0) <= ESI_GROSS_LIMIT


def state_insurance(emp, gross):
    """(employee ESI, employer ESI) for the month, on the gross; nothing once the gross is over the limit."""
    if not esi_applies(emp, gross):
        return 0.0, 0.0
    gross = float(gross)
    return money(gross * ESI_EMPLOYEE_RATE / 100.0), money(gross * ESI_EMPLOYER_RATE / 100.0)


def pt_state_of(emp):
    state = (getattr(emp, "pt_state", None) or DEFAULT_PT_STATE).strip().upper()
    return state if state in PT_SLABS else DEFAULT_PT_STATE


def professional_tax(emp, gross):
    """The month's professional tax by the gross and the employee's state slab."""
    if not _on(emp, "pt_enabled") or not applies_to(emp):
        return 0.0
    gross = float(gross or 0)
    for limit, tax in PT_SLABS[pt_state_of(emp)]:
        if gross <= limit:
            return tax
    return 0.0


def employer_contributions(emp, basic, gross):
    """What the company pays on top, for the payslip's employer columns."""
    _, epf, eps = provident_fund(emp, basic)
    _, esi = state_insurance(emp, gross)
    return {"employer_pf": money(epf + eps), "employer_epf": epf, "employer_eps": eps, "employer_esi": esi}
