"""What the bank, EPFO and ESIC files are made from: a month's payslips with the people they pay.

The figures are the payslip's own, as it was issued; nothing is worked out again from today's salary. A payslip made
before the employer columns existed has them filled in from its PF and gross, the way the payslip would have had them.
"""
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException

from app import models
from app.core.currency import money
from app.services import payroll_month, statutory


def month_label(month):
    """2026-10 -> October 2026."""
    return datetime.strptime(month + "-01", "%Y-%m-%d").strftime("%B %Y")


def month_payslips(db, client_id, month):
    """[(payslip, employee)] for the month, ordered by employee number then name. 404 when there are none."""
    slips = payroll_month.payslips_of(db, client_id, month)
    if not slips:
        raise HTTPException(status_code=404, detail="There are no payslips for %s." % month_label(month))
    people = {e.id: e for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id, models.DBEmployee.id.in_({p.employee_id for p in slips})).all()}
    pairs = [(p, people[p.employee_id]) for p in slips if p.employee_id in people]
    pairs.sort(key=lambda pe: ((pe[1].employee_id or ""), (pe[1].first_name or ""), (pe[1].last_name or "")))
    return pairs


def salary_bank_file(db, client_id, pairs, month, bank, account, pay_on):
    """The month's salary transfer in one of the banks' own layouts (services.payouts.FORMATS), the same files a payment
    batch writes: (header or None, rows, [(name, reason)] for those left out). `account` is the bank account the salary
    goes out of (needed by banks whose layout names it); nobody is sent whose account number or IFSC is missing."""
    from app.services import payouts
    batch = SimpleNamespace(number="SAL-%s" % month, bank_format=bank, pay_on=pay_on)
    lines, left_out = [], []
    for ps, emp in pairs:
        acct, ifsc = (emp.bank_account or ""), (emp.bank_ifsc or "").strip().upper()
        why = payouts.beneficiary_problem(acct, ifsc, ps.net_pay)
        if why:
            left_out.append((full_name(emp), why.replace(" on file", "")))
            continue
        lines.append(SimpleNamespace(
            party_name=full_name(emp), doc_number=ps.number or "", amount=money(ps.net_pay), beneficiary_account=acct,
            beneficiary_ifsc=ifsc, beneficiary_bank=emp.bank_name or "", beneficiary_email=emp.email or ""))
    ours = account or SimpleNamespace(account_no="", ifsc="")
    header, rows = payouts.file_rows(batch, lines, ours)
    if bank == "csv":
        for r in rows:
            r[4] = money(r[4])              # the plain sheet keeps the amount a number, so it can be summed
    return header, rows, left_out


def full_name(emp):
    return ("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()


def pf_figures(ps):
    """(employee PF, employer EPS, employer EPF-EPS difference) as the payslip has them."""
    employee = money(ps.retirement or 0)
    eps, diff = money(ps.employer_eps or 0), money(ps.employer_epf or 0)
    if employee > 0 and not (eps or diff):
        # Made before the employer columns: the employer's shares follow from the same PF wage.
        _, diff, eps = statutory.provident_fund(SimpleNamespace(pf_enabled=True, pay_frequency="monthly", salary=1),
                                                ps.basic_salary or 0)
    return employee, eps, diff


def esi_figures(ps):
    """(employee ESI, employer ESI) as the payslip has them."""
    employee = money(ps.insurance or 0)
    employer = money(ps.employer_esi or 0)
    if employee > 0 and not employer:
        employer = money((ps.gross_pay or 0) * statutory.ESI_EMPLOYER_RATE / 100.0)
    return employee, employer
