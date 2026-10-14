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
    hired_with_agreement = {r.asset_id for r in db.query(models.DBPlantRental).filter(models.DBPlantRental.client_id == client_id).all()}
    for l in logs:
        c = out[l.asset_id]
        # Fuel and hire written on the older daily log, before those had registers of their own.
        c["fuel"] += l.fuel_cost or 0
        c["fuel_litres"] += l.fuel_litres if (l.fuel_cost or 0) else 0
        if l.asset_id not in hired_with_agreement:
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


def month_bounds():
    t = date.today()
    first = t.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()
