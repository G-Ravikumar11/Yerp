"""The bank's salary disbursement file: one row per person paid, for a bulk NEFT upload.

Only rows a bank can act on: an account number, an IFSC and an amount above nothing. Anybody else is reported back
rather than sent, since a row with a missing IFSC fails the whole upload at most banks.
"""
import re

from app.core.currency import money
from app.services.payroll_exports import full_name, month_label

HEADERS = ["Beneficiary Account No", "Beneficiary Name", "IFSC Code", "Amount", "Transaction Reference / Narration"]
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
NARRATION_MAX = 30          # what most banks keep of the narration


def problem(emp, net):
    """Why a person cannot go in the file, or "" when they can."""
    account = re.sub(r"\s", "", emp.bank_account or "")
    ifsc = (emp.bank_ifsc or "").strip().upper()
    if not account:
        return "no bank account number"
    if not ifsc:
        return "no IFSC"
    if not IFSC_RE.match(ifsc):
        return "IFSC %s is not 11 characters of the right form" % ifsc
    if money(net) <= 0:
        return "nothing to pay"
    return ""


def rows(pairs, month):
    """(rows for the file, [(name, reason)] for those left out)."""
    narration = ("Salary for %s" % month_label(month))[:NARRATION_MAX]
    out, left_out = [], []
    for ps, emp in pairs:
        why = problem(emp, ps.net_pay)
        if why:
            left_out.append((full_name(emp), why))
            continue
        out.append([re.sub(r"\s", "", emp.bank_account), full_name(emp), emp.bank_ifsc.strip().upper(),
                    money(ps.net_pay), narration])
    return out, left_out
