"""The monthly ESIC return: every insured person paid this month, their days and wages, and both shares.

Only people ESI was deducted from are insured persons for the month; anybody earning over the limit, or switched off,
is not. An insured person with no ESI number (the IP number) is reported back rather than put in the file.
"""
import re

from app.core.currency import money
from app.services.payroll_exports import esi_figures, full_name

HEADERS = ["IP Number", "IP Name", "No of Days for which wages paid/payable during the month", "Total Monthly Wages",
           "Employee Contribution", "Employer Contribution"]
IP_RE = re.compile(r"^\d{10}$")


def rows(pairs, days_of):
    """(rows for the file, [(name, reason)] for those left out). `days_of(ps, emp)` is the days paid."""
    out, left_out = [], []
    for ps, emp in pairs:
        employee, employer = esi_figures(ps)
        if employee <= 0:
            continue                                    # not insured this month
        ip = re.sub(r"\D", "", emp.esi_no or "")
        if not IP_RE.match(ip):
            left_out.append((full_name(emp), "no 10-digit ESI (IP) number"))
            continue
        out.append([ip, full_name(emp), days_of(ps, emp), money(ps.gross_pay), employee, employer])
    return out, left_out
