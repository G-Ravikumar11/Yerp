"""The EPFO Electronic Challan cum Return (ECR 2.0): the month's PF, one line per member, as uploaded on the
employer portal.

Eleven fields in this order, whole rupees, no heading line:

    UAN, member name, gross wages, EPF wages, EPS wages, EDLI wages,
    EPF contribution (12%), EPS contribution (8.33%, at most 1,250), EPF-EPS difference (3.67%), NCP days, refunds

The portal reads the fields separated by #~#, which is the default here. `sep="pipe"` gives the same line with | between
the fields, for a payroll tool that wants that instead; the EPFO portal itself does not accept it.
"""
import re

from app.services import statutory
from app.services.payroll_exports import full_name, pf_figures

SEPARATORS = {"epfo": "#~#", "pipe": "|"}
FIELDS = ["UAN", "Member Name", "Gross Wages", "EPF Wages", "EPS Wages", "EDLI Wages", "EPF Contribution",
          "EPS Contribution", "EPF-EPS Diff", "NCP Days", "Refund of Advances"]
UAN_RE = re.compile(r"^\d{12}$")


def _rupees(value):
    """ECR figures are whole rupees, rounded half up."""
    return int(float(value or 0) + 0.5)


def _name(emp):
    """Upper case, letters, spaces and dots only: what the portal matches against the UAN record."""
    return re.sub(r"[^A-Z. ]", "", full_name(emp).upper()).strip()


def lines(pairs):
    """(the members' lines as lists of fields, [(name, reason)] for those left out)."""
    out, left_out = [], []
    for ps, emp in pairs:
        employee, eps, _diff = pf_figures(ps)
        if employee <= 0:
            continue                                    # no PF this month: not a member line
        uan = re.sub(r"\D", "", emp.uan_no or "")
        if not UAN_RE.match(uan):
            left_out.append((full_name(emp), "no 12-digit UAN"))
            continue
        wage = _rupees(statutory.pf_basic(ps.basic_salary or 0))
        # The portal checks EPS + difference = EPF contribution, so the difference is what is left once both are whole
        # rupees: rounding 1,249.50 and 550.50 each on their own would make 1,801 of an 1,800 contribution.
        epf_r, eps_r = _rupees(employee), min(_rupees(eps), int(statutory.EPS_MAX))
        out.append([uan, _name(emp), _rupees(ps.gross_pay), wage, wage, wage, epf_r, eps_r, max(epf_r - eps_r, 0),
                    _rupees(ps.lop_days or 0), 0])
    return out, left_out


def text(member_lines, sep="epfo"):
    """The file's text: one member per line, CRLF as the portal's own samples have it."""
    joiner = SEPARATORS.get(sep, SEPARATORS["epfo"])
    return "".join(joiner.join(str(f) for f in line) + "\r\n" for line in member_lines)
