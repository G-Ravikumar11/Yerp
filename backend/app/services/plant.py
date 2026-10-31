"""The workings behind Equipment & Plant: hours from a shift, the status of a hire, and what the machines cost - each
figure worked out from what is stored, so nothing is entered twice and nothing is counted twice."""
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core.currency import money
from app.core.dates import _parse_date

ROLES = ("Operator", "Driver", "Helper", "Technician", "Other")
SHIFTS = ("Day", "Night", "General")
FUEL_TYPES = ("Diesel", "Petrol", "CNG", "Electric", "Other")
MAINT_KINDS = ("Preventive", "Corrective", "Emergency")
PRIORITIES = ("Low", "Normal", "High", "Urgent")
BILLING = ("Hourly", "Daily", "Weekly", "Monthly")
# Fuel, maintenance and rental charges have registers of their own; the expense register is for everything else, so
# none of it is ever entered twice.
EXPENSE_CATEGORIES = ("Spare parts", "Operator wages and overtime", "Transportation and shifting", "Insurance and permits", "Other")
DERIVED_CATEGORIES = {"Fuel and diesel": "the Fuel register", "Maintenance and repairs": "Maintenance",
                      "Rental charges": "the Rental register"}
DEFAULT_REGULAR_HOURS = 8.0
IDLE_SHARE_ALERT = 0.4          # idle for more than 40% of the hours on duty is too much


def today():
    return date.today().isoformat()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_day(value, what, required=False):
    v = (value or "").strip()[:10]
    if not v:
        if required:
            raise HTTPException(400, "Give the %s." % what)
        return ""
    if not _parse_date(v):
        raise HTTPException(400, "The %s as a date: 2026-09-30." % what)
    return v


def minutes_of(hhmm, what):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", hhmm or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise HTTPException(400, "The %s as a time: 07:30." % what)
    return int(m.group(1)) * 60 + int(m.group(2))


def shift_span(start, end):
    """(start, end) in minutes from the work date's midnight. An end before the start is the next morning."""
    s, e = minutes_of(start, "start time"), minutes_of(end, "end time")
    if e <= s:
        e += 24 * 60
    return s, e


def regular_hours(db, client_id):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id,
                                             models.DBSettings.key == "plant_regular_hours").first()
    try:
        v = float(row.value) if row and row.value else DEFAULT_REGULAR_HOURS
    except ValueError:
        v = DEFAULT_REGULAR_HOURS
    return v if 1 <= v <= 16 else DEFAULT_REGULAR_HOURS


def number_for(db, model, client_id, stem):
    best = 0
    for (n,) in db.query(model.number).filter(model.client_id == client_id).all():
        m = re.search(r"(\d+)$", n or "")
        if m:
            best = max(best, int(m.group(1)))
    return "%s-%04d" % (stem, best + 1)


def employee_or_400(db, client_id, emp_id, what="employee"):
    e = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id, models.DBEmployee.client_id == client_id).first() if emp_id else None
    if not e:
        raise HTTPException(400, "Choose the %s from the employee list." % what)
    return e


def employee_card(e):
    """What the plant screens need of a person - no more: their code, name, mobile, designation and whether they are working."""
    if not e:
        return None
    return {"id": e.id, "code": e.employee_id or "", "name": ("%s %s" % (e.first_name or "", e.last_name or "")).strip(),
            "mobile": e.phone or "", "designation": e.job_title or "", "status": e.status or ""}


def hourly_cost(e):
    """What an hour of a person costs, from their pay: their hourly rate, or a monthly salary over 26 days of 8 hours."""
    if not e:
        return 0.0
    if e.hourly_rate:
        return float(e.hourly_rate)
    return round(float(e.salary or 0) / 208.0, 2) if e.salary else 0.0


def check_invoice_unique(db, client_id, invoice_no, skip=None):
    """One invoice or voucher, one record - across fuel, maintenance, rental bills and expenses."""
    v = (invoice_no or "").strip()
    if not v:
        return ""
    low = v.lower()
    checks = (("fuel", models.DBPlantFuel, models.DBPlantFuel.voucher_no, "fuel entry %s"),
              ("expense", models.DBPlantExpense, models.DBPlantExpense.invoice_no, "expense %s"),
              ("rental_invoice", models.DBPlantRentalInvoice, models.DBPlantRentalInvoice.invoice_no, "rental bill %s"),
              ("maintenance", models.DBAssetService, models.DBAssetService.invoice_no, "maintenance %s"))
    from sqlalchemy import func
    for kind, model, col, label in checks:
        q = db.query(model).filter(model.client_id == client_id, func.lower(col) == low)
        if skip and skip[0] == kind:
            q = q.filter(model.id != skip[1])
        hit = q.first()
        if hit:
            raise HTTPException(409, "Invoice or voucher %s is already recorded (%s)." % (v, label % (getattr(hit, "number", "") or getattr(hit, "invoice_no", "") or hit.id)))
    return v


def rental_status(r, extended):
    t = today()
    if r.actual_return:
        return "Returned"
    if r.start_date and r.start_date > t:
        return "Upcoming"
    if r.expected_return and r.expected_return < t:
        return "Overdue"
    return "Extended" if extended else "Active"


def in_range(day, date_from, date_to):
    d = (day or "")[:10]
    return (not date_from or d >= date_from) and (not date_to or d <= date_to)


def machine_hours(logs):
    """Machine hours from the logbook. Two people on one machine in one shift - an operator and a helper - are one
    machine's hours, not two: each machine-day-shift counts once, at the largest figure logged for it."""
    by = {}
    for l in logs:
        key = (l.asset_id, l.log_date, l.shift or ("#%d" % l.id))
        cur = by.setdefault(key, {"asset_id": l.asset_id, "job_id": l.job_id, "date": l.log_date, "operating": 0.0, "idle": 0.0, "breakdown": 0.0})
        cur["operating"] = max(cur["operating"], l.hours_worked or 0)
        cur["idle"] = max(cur["idle"], l.idle_hours or 0)
        cur["breakdown"] = max(cur["breakdown"], l.breakdown_hours or 0)
    return list(by.values())


def costs(db, client_id, date_from="", date_to="", asset_id=0):
    """Per machine, for the period: hours run, idle and broken down; fuel; maintenance; hire billed and owed; other
    expenses by category; the people's hours and what they cost. Each cost comes from one register only."""
    A = models.DBAsset
    assets = {a.id: a for a in db.query(A).filter(A.client_id == client_id).all() if not asset_id or a.id == asset_id}
    out = {aid: {"asset_id": aid, "code": a.code, "name": a.name, "ownership": a.ownership, "operating_hours": 0.0, "idle_hours": 0.0,
                 "breakdown_hours": 0.0, "fuel_litres": 0.0, "fuel": 0.0, "maintenance": 0.0, "rental": 0.0, "rental_outstanding": 0.0,
                 "expenses": {c: 0.0 for c in EXPENSE_CATEGORIES}, "labour_hours": 0.0, "overtime_hours": 0.0, "labour_cost": 0.0}
           for aid, a in assets.items()}
    logs = [l for l in db.query(models.DBAssetLog).filter(models.DBAssetLog.client_id == client_id).all()
            if l.asset_id in out and in_range(l.log_date, date_from, date_to) and (l.approval_status or "") != "Rejected"]
    for h in machine_hours(logs):
        c = out[h["asset_id"]]
        c["operating_hours"] += h["operating"]
        c["idle_hours"] += h["idle"]
        c["breakdown_hours"] += h["breakdown"]
    staff = {}
    rentals_of = rentals_by_asset(db, client_id)
    register_days = fuel_register_days(db, client_id)
    for l in logs:
        c = out[l.asset_id]
        # Fuel and hire written on the older daily log, before those had registers of their own.
        if l.fuel_cost and log_fuel_counts(l, register_days):
            c["fuel"] += l.fuel_cost
            c["fuel_litres"] += l.fuel_litres or 0
        if not on_agreement(rentals_of, l.asset_id, l.log_date):
            c["rental"] += l.hire_cost or 0
        if l.employee_id:
            if l.employee_id not in staff:
                staff[l.employee_id] = db.query(models.DBEmployee).filter(models.DBEmployee.id == l.employee_id).first()
            c["labour_hours"] += l.attendance_hours or 0
            c["overtime_hours"] += l.overtime_hours or 0
            rate = hourly_cost(staff[l.employee_id])
            c["labour_cost"] += (l.regular_hours or 0) * rate + (l.overtime_hours or 0) * rate * 1.5
    for f in db.query(models.DBPlantFuel).filter(models.DBPlantFuel.client_id == client_id).all():
        if f.asset_id in out and in_range(f.filled_at, date_from, date_to):
            out[f.asset_id]["fuel"] += f.amount or 0
            out[f.asset_id]["fuel_litres"] += f.litres or 0
    for s in db.query(models.DBAssetService).filter(models.DBAssetService.client_id == client_id).all():
        if s.asset_id in out and in_range(s.completed_on or s.service_on, date_from, date_to):
            out[s.asset_id]["maintenance"] += s.total_cost or 0
    rentals = {r.id: r for r in db.query(models.DBPlantRental).filter(models.DBPlantRental.client_id == client_id).all()}
    for inv in db.query(models.DBPlantRentalInvoice).filter(models.DBPlantRentalInvoice.client_id == client_id).all():
        r = rentals.get(inv.rental_id)
        if r and r.asset_id in out and in_range(inv.invoice_date, date_from, date_to):
            out[r.asset_id]["rental"] += inv.amount or 0
            out[r.asset_id]["rental_outstanding"] += max(0.0, (inv.amount or 0) - (inv.paid or 0))
    for e in db.query(models.DBPlantExpense).filter(models.DBPlantExpense.client_id == client_id,
                                                    models.DBPlantExpense.approval_status != "Rejected").all():
        if e.asset_id in out and in_range(e.spent_on, date_from, date_to):
            out[e.asset_id]["expenses"][e.category if e.category in EXPENSE_CATEGORIES else "Other"] += e.amount or 0
    for c in out.values():
        other = sum(c["expenses"].values())
        for k in ("operating_hours", "idle_hours", "breakdown_hours", "fuel_litres", "labour_hours", "overtime_hours"):
            c[k] = round(c[k], 2)
        for k in ("fuel", "maintenance", "rental", "rental_outstanding", "labour_cost"):
            c[k] = money(c[k])
        c["expenses"] = {k: money(v) for k, v in c["expenses"].items()}
        c["other_expenses"] = money(other)
        # Labour is shown worked out from hours and pay; it is in the total only as wages actually entered, so a
        # wage paid and entered is never counted a second time as an estimate.
        c["total"] = money(c["fuel"] + c["maintenance"] + c["rental"] + other)
        c["fuel_per_hour"] = round(c["fuel"] / c["operating_hours"], 2) if c["operating_hours"] else 0.0
        c["litres_per_hour"] = round(c["fuel_litres"] / c["operating_hours"], 2) if c["operating_hours"] else 0.0
        on_duty = c["operating_hours"] + c["idle_hours"]
        c["idle_share"] = round(c["idle_hours"] / on_duty, 3) if on_duty else 0.0
    return out


def month_end(day):
    d = _parse_date(day[:10])
    nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    return (nxt - timedelta(days=1)).isoformat()


def invoice_period(inv):
    """The days a rental bill covers: what it says, or the month it is dated in when it does not say."""
    day = (inv.invoice_date or today())[:10]
    return (inv.period_from or day[:8] + "01"), (inv.period_to or month_end(inv.period_from or day))


def rentals_by_asset(db, client_id):
    by = {}
    for r in db.query(models.DBPlantRental).filter(models.DBPlantRental.client_id == client_id).all():
        by.setdefault(r.asset_id, []).append(r)
    return by


def on_agreement(rentals, asset_id, day):
    """Whether a day is inside a hire agreement. Hire for that day is then the owner's bill, whatever a log worked out:
    the log's figure is an estimate of the same money."""
    return any((r.start_date or "") <= day <= (r.actual_return or "9999-12-31") for r in rentals.get(asset_id, ()))


def fuel_register_days(db, client_id):
    return {(f.asset_id, (f.filled_at or "")[:10]) for f in db.query(models.DBPlantFuel.asset_id, models.DBPlantFuel.filled_at).filter(
        models.DBPlantFuel.client_id == client_id).all()}


def log_fuel_counts(log, register_days):
    """Fuel written on an older log counts, unless the register has that machine's fuel for the day: then it is the same diesel."""
    return (log.asset_id, log.log_date) not in register_days


def _invoice_shares(inv, rental, hours_by_asset, assets, moves_by_asset):
    """{job_id: amount}: a rental bill names no project, so it goes to the sites the machine worked in its period, by
    hours. No hours logged: the site it stood on. Nowhere known: job 0, shown as not yet charged to a project."""
    pf, pt = invoice_period(inv)
    hours = {}
    for h in hours_by_asset.get(rental.asset_id, ()):
        if pf <= h["date"] <= pt and h["job_id"]:
            hours[h["job_id"]] = hours.get(h["job_id"], 0.0) + (h["operating"] or 0)
    total = sum(hours.values())
    if total <= 0:
        site = None
        for m in moves_by_asset.get(rental.asset_id, ()):
            if (m.moved_on or "") <= pt:
                site = m.to_job_id
        a = assets.get(rental.asset_id)
        site = site or (a.current_job_id if a else None)
        return {site or 0: money(inv.amount or 0)}
    jobs = sorted(hours)
    out = {j: money((inv.amount or 0) * hours[j] / total) for j in jobs}
    out[jobs[-1]] = money((inv.amount or 0) - sum(out[j] for j in jobs[:-1]))    # the paise left over by rounding
    return out


def plant_cost_breakdown(db, client_id, date_from="", date_to="", lines=False):
    """{job_id: what the machines cost it}. Job 0 is cost not yet tied to a project. Everything comes from the record it
    is kept in, by the date it was incurred:

      fuel         the fuel register, and fuel on older logs for a day the register does not cover
      rental       rental invoices, shared across sites by hours (the actual bill, never the expected one)
      hire         hire on a logged day with no agreement behind it; inside an agreement the invoice is the cost
      maintenance  maintenance and repair jobs
      expenses     the expense register, unless rejected

    Rejected logs and expenses count for nothing. Worked out from the records every time, so a correction, an
    approval or an invoice shows at once."""
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client_id).all()}
    rentals = rentals_by_asset(db, client_id)
    register_days = fuel_register_days(db, client_id)
    out = {}

    def row(job):
        return out.setdefault(job or 0, {"job_id": job or 0, "fuel": 0.0, "rental": 0.0, "hire": 0.0, "maintenance": 0.0, "expenses": 0.0,
                                         "total": 0.0, "duplicates_excluded": 0.0, "unbilled_hire_estimate": 0.0, "lines": []})

    def add(job, category, source, ref, day, asset_id, description, amount):
        r = row(job)
        r[category] += amount or 0
        if lines:
            a = assets.get(asset_id)
            r["lines"].append({"category": category, "source": source, "ref": ref or "", "date": (day or "")[:10], "asset_id": asset_id,
                               "code": a.code if a else "", "machine": a.name if a else "", "description": description or "", "amount": money(amount or 0)})

    for f in db.query(models.DBPlantFuel).filter(models.DBPlantFuel.client_id == client_id).all():
        if in_range(f.filled_at, date_from, date_to) and f.amount:
            add(f.job_id, "fuel", "Fuel register", f.number, f.filled_at, f.asset_id, "%g L %s" % (f.litres or 0, f.fuel_type or ""), f.amount)

    logs = [l for l in db.query(models.DBAssetLog).filter(models.DBAssetLog.client_id == client_id).all()
            if (l.approval_status or "") != "Rejected"]
    invoices = db.query(models.DBPlantRentalInvoice).filter(models.DBPlantRentalInvoice.client_id == client_id).all()
    billed = {}
    by_id = {r.id: r for rs in rentals.values() for r in rs}
    for inv in invoices:
        r = by_id.get(inv.rental_id)
        if r:
            billed.setdefault(r.asset_id, []).append(invoice_period(inv))
    for l in logs:
        if not in_range(l.log_date, date_from, date_to):
            continue
        if l.fuel_cost:
            if log_fuel_counts(l, register_days):
                add(l.job_id, "fuel", "Older logbook", "LOG-%d" % l.id, l.log_date, l.asset_id, "%g L on the daily log" % (l.fuel_litres or 0), l.fuel_cost)
            else:
                row(l.job_id)["duplicates_excluded"] += l.fuel_cost
        if l.hire_cost:
            if not on_agreement(rentals, l.asset_id, l.log_date):
                add(l.job_id, "hire", "Logbook hire", "LOG-%d" % l.id, l.log_date, l.asset_id, "%g h on hire terms" % (l.hours_worked or 0), l.hire_cost)
            elif any(pf <= l.log_date <= pt for pf, pt in billed.get(l.asset_id, ())):
                row(l.job_id)["duplicates_excluded"] += l.hire_cost
            else:
                row(l.job_id)["unbilled_hire_estimate"] += l.hire_cost

    hours_by_asset = {}
    for h in machine_hours(logs):
        hours_by_asset.setdefault(h["asset_id"], []).append(h)
    moves = {}
    for m in db.query(models.DBAssetMove).filter(models.DBAssetMove.client_id == client_id).order_by(models.DBAssetMove.moved_on, models.DBAssetMove.id).all():
        moves.setdefault(m.asset_id, []).append(m)
    for inv in invoices:
        r = by_id.get(inv.rental_id)
        if r and in_range(inv.invoice_date, date_from, date_to) and inv.amount:
            for job, amount in _invoice_shares(inv, r, hours_by_asset, assets, moves).items():
                add(job, "rental", "Rental invoice", inv.invoice_no, inv.invoice_date, r.asset_id, "%s, hire %s to %s" % (r.agreement_no, *invoice_period(inv)), amount)

    for s in db.query(models.DBAssetService).filter(models.DBAssetService.client_id == client_id).all():
        if s.total_cost and in_range(s.completed_on or s.service_on, date_from, date_to):
            add(s.job_id, "maintenance", "Maintenance", s.number or ("SVC-%d" % s.id), s.completed_on or s.service_on, s.asset_id,
                (s.work_performed or s.description or "")[:120], s.total_cost)
    for e in db.query(models.DBPlantExpense).filter(models.DBPlantExpense.client_id == client_id, models.DBPlantExpense.approval_status != "Rejected").all():
        if e.amount and in_range(e.spent_on, date_from, date_to):
            add(e.job_id, "expenses", "Plant expense", e.number, e.spent_on, e.asset_id, ("%s: %s" % (e.category, e.description or ""))[:120], e.amount)

    # Shuttering and scaffolding: what each return came to, on the day it went back. What is still out is an estimate.
    H, R = models.DBFormworkHire, models.DBFormworkReturn
    for h in db.query(H).filter(H.client_id == client_id).all():
        back = db.query(R).filter(R.hire_id == h.id).all()
        for r in back:
            if in_range(r.returned_on, date_from, date_to):
                add(h.job_id, "hire", "%s hire" % h.kind, h.number, r.returned_on, None, (h.description or "")[:120], (r.hire_charge or 0) + (r.loss_charge or 0) + (r.damage_charge or 0))
        out_qty = (h.quantity or 0) - sum((r.returned_qty or 0) + (r.damaged_qty or 0) + (r.lost_qty or 0) for r in back)
        if out_qty > 0:
            row(h.job_id)["unbilled_hire_estimate"] += out_qty * (h.daily_rate or 0) * max(1, (date.today() - _parse_date(h.start_date)).days + 1)

    for r in out.values():
        for k in ("fuel", "rental", "hire", "maintenance", "expenses", "duplicates_excluded", "unbilled_hire_estimate"):
            r[k] = money(r[k])
        r["total"] = money(r["fuel"] + r["rental"] + r["hire"] + r["maintenance"] + r["expenses"])
        r["lines"].sort(key=lambda x: x["date"], reverse=True)
    return out


def month_bounds():
    t = date.today()
    first = t.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()
