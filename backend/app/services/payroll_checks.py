"""What to look at before a month's payroll is approved: the checks the monthly run puts on the bell.

Each check is a short list of people and a reason, gathered into one notice per kind, so HR gets "4 people have no
IFSC" once rather than four notices. The bank, ECR and ESIC files are built here as well, to find who could not go in
them while there is still time to put it right; the files themselves are made when they are downloaded, from the
payslips as they then stand.
"""
from app import models
from app.documents import ecr, esic, neft
from app.services import payroll_exports

WAGE_SWING = 20.0          # per cent change in net pay from the month before that is worth a look


def _name(emp):
    return payroll_exports.full_name(emp)


def previous_net(db, client_id, emp_id, before_month):
    P = models.DBPayslip
    prev = db.query(P).filter(P.client_id == client_id, P.employee_id == emp_id, P.status != "Void",
                              P.period_end < before_month + "-01").order_by(P.period_end.desc()).first()
    return prev.net_pay if prev else None


def month_checks(db, client_id, month):
    """{kind: {"title", "people": [...], "files"?: ...}} for the month's payslips. Empty kinds are left out."""
    try:
        pairs = payroll_exports.month_payslips(db, client_id, month)
    except Exception:
        return {}
    A = models.DBAttendance
    tracked = {r[0] for r in db.query(A.employee_id).filter(A.client_id == client_id).distinct()}
    found = {k: [] for k in ("no_hours", "no_pan", "no_bank", "no_uan", "no_esi", "zero_pay", "wage_swing", "heavy_lop")}
    for ps, emp in pairs:
        name = _name(emp)
        if emp.id in tracked and (ps.hours_worked or 0) <= 0 and (ps.paid_days or 0) > 0:
            found["no_hours"].append(name)
        if not (emp.pan_no or "").strip():
            found["no_pan"].append(name)
        if neft.problem(emp, ps.net_pay or 1) and (ps.net_pay or 0) > 0:
            found["no_bank"].append("%s (%s)" % (name, neft.problem(emp, ps.net_pay)))
        if (ps.retirement or 0) > 0 and not ecr.UAN_RE.match("".join(ch for ch in (emp.uan_no or "") if ch.isdigit())):
            found["no_uan"].append(name)
        if (ps.insurance or 0) > 0 and not esic.IP_RE.match("".join(ch for ch in (emp.esi_no or "") if ch.isdigit())):
            found["no_esi"].append(name)
        if (ps.net_pay or 0) <= 0:
            found["zero_pay"].append(name)
        prev = previous_net(db, client_id, emp.id, month)
        if prev and prev > 0 and ps.net_pay is not None:
            change = (ps.net_pay - prev) / prev * 100
            if abs(change) > WAGE_SWING:
                found["wage_swing"].append("%s (%+.0f%%)" % (name, change))
        if (ps.working_days or 0) > 0 and (ps.lop_days or 0) >= (ps.working_days or 0) / 2:
            found["heavy_lop"].append("%s (%g days)" % (name, ps.lop_days))
    titles = {
        "no_hours": "logged no hours though attendance is kept for them",
        "no_pan": "have no PAN on record",
        "no_bank": "cannot be paid by bank transfer",
        "no_uan": "have PF deducted but no UAN, so cannot go in the ECR",
        "no_esi": "have ESI deducted but no ESI (IP) number, so cannot go in the ESIC return",
        "zero_pay": "have a net pay of nothing",
        "wage_swing": "have net pay more than %g%% different from last month" % WAGE_SWING,
        "heavy_lop": "lost half the month or more to loss of pay",
    }
    out = {k: {"title": titles[k], "people": v} for k, v in found.items() if v}
    # The statutory files, built now so what would stop them is known before anyone downloads one.
    ecr_lines, _ = ecr.lines(pairs)
    esic_rows, _ = esic.rows(pairs, lambda ps, emp: int((ps.paid_days or 0) + 0.5))
    out["_files"] = {"ecr_members": len(ecr_lines), "esic_members": len(esic_rows),
                     "pf_total": sum(int(l[6]) + int(l[7]) + int(l[8]) for l in ecr_lines),
                     "esi_total": round(sum(r[4] + r[5] for r in esic_rows), 2)}
    return out


def announce(db, client_id, month, checks):
    """One bell notice per kind of problem, each saying who and what to do. Returns how many were raised."""
    from app.core.notifications import notify
    label = payroll_exports.month_label(month)
    raised = 0
    for kind, found in checks.items():
        if kind.startswith("_"):
            continue
        people = found["people"]
        shown = ", ".join(people[:8]) + (" and %d more" % (len(people) - 8) if len(people) > 8 else "")
        notify(db, client_id, "payroll_check", "%s payroll: %d %s %s" % (
            label, len(people), "person" if len(people) == 1 else "people", found["title"]),
            "%s. Put it right before approving %s." % (shown, label), view="payroll-view", severity="action")
        raised += 1
    return raised
