"""The rules and workings behind the assets endpoints."""
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func as sqlfunc

from app import models

from app.constants.assets import (
    ASSET_BOOK_DEFAULTS,
    ASSET_CATEGORIES,
    BOOK_METHODS,
    DAYS_IN_A_HIRE_MONTH,
    HALF_RATE_DAYS,
    HIRE_BASES,
    TAX_BLOCK_DEFAULTS,
)
from app.core.currency import money
from app.core.dates import _days_until, _parse_date


INTERVAL_TYPES = ("Both", "Meter", "Days", "None")
# Worst first: the one a combined schedule reports is whichever threshold is reached first.
SERVICE_STATUSES = ("Overdue", "Service due", "Due soon", "Upcoming", "Incomplete", "Not scheduled")
UNIT_WORD = {"Hours": "hours", "Km": "km"}
EARLIEST_YEAR = 1980        # a service date before this is a mistyped year, not a record


def _day(value):
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def interval_type(a):
    """The schedule's type; a record from before the type was kept reads it from its intervals."""
    t = a.service_interval_type or ""
    if t in INTERVAL_TYPES:
        return t
    meter, days = (a.service_every or 0) > 0, (a.service_every_days or 0) > 0
    return "Both" if meter and days else "Meter" if meter else "Days" if days else "None"


def reminder_windows(a):
    """How early the reminder comes: as set, or a tenth of the interval (at least three days)."""
    m = a.reminder_meter if a.reminder_meter is not None else round((a.service_every or 0) * 0.1, 1)
    d = a.reminder_days if a.reminder_days is not None else max(3, int(round((a.service_every_days or 0) * 0.1)))
    return m, d


def next_thresholds(a):
    """The reading and the date the next service falls due at - as stored, or worked out from the
    last service plus the interval. A missing reading or date gives no threshold, never a nought."""
    t = interval_type(a)
    meter = on = None
    if t in ("Both", "Meter") and (a.service_every or 0) > 0:
        if a.next_service_meter is not None:
            meter = a.next_service_meter
        elif a.last_service_meter is not None:
            meter = round(a.last_service_meter + a.service_every, 1)
    if t in ("Both", "Days") and (a.service_every_days or 0) > 0:
        if _day(a.next_service_on):
            on = a.next_service_on[:10]
        elif _day(a.last_service_on):
            on = (_day(a.last_service_on) + timedelta(days=a.service_every_days)).isoformat()
    return meter, on


def service_schedule(a, today=None):
    """Where a machine stands on its schedule: the one reading of it the register, the machine,
    the dashboard and the reports all share.

    Meter: Due soon inside the reminder window, Service due once the reading reaches the
    threshold, Overdue once it has run past it by more than a tenth of the interval.
    Calendar: Due soon inside the reminder window, Service due on the date, Overdue after it.
    Both: whichever is reached first."""
    today = today or date.today()
    t = interval_type(a)
    unit = UNIT_WORD.get(a.meter_unit or "Hours", "hours")
    rem_m, rem_d = reminder_windows(a)
    nm, nd = next_thresholds(a)
    out = {"type": t, "unit": unit, "every_meter": a.service_every or 0, "every_days": a.service_every_days or 0,
           "reminder_meter": rem_m, "reminder_days": rem_d, "reminder_meter_set": a.reminder_meter is not None,
           "reminder_days_set": a.reminder_days is not None,
           "last_service_on": a.last_service_on or "", "last_service_meter": a.last_service_meter,
           "next_meter": nm, "next_on": nd, "meter_left": None, "days_left": None,
           "status": "Not scheduled", "reasons": [], "missing": []}
    if t == "None":
        return out
    found = []
    if t in ("Both", "Meter"):
        if nm is None:
            out["missing"].append("the meter reading at the last service")
        else:
            left = round(nm - (a.meter_reading or 0), 1)
            out["meter_left"] = left
            grace = (a.service_every or 0) * 0.1
            if left < -grace:
                found.append(("Overdue", "%g %s past its service" % (abs(left), unit)))
            elif left <= 0:
                found.append(("Service due", ("%g %s past its service" % (abs(left), unit)) if left < 0 else "service due now, at %g %s" % (nm, unit)))
            elif left <= rem_m:
                found.append(("Due soon", "service in %g %s" % (left, unit)))
            else:
                found.append(("Upcoming", "service in %g %s" % (left, unit)))
    if t in ("Both", "Days"):
        if nd is None:
            out["missing"].append("the date of the last service")
        else:
            left = (_day(nd) - today).days
            out["days_left"] = left
            if left < 0:
                found.append(("Overdue", "%d days past its service" % abs(left)))
            elif left == 0:
                found.append(("Service due", "service due today"))
            elif left <= rem_d:
                found.append(("Due soon", "service in %d days" % left))
            else:
                found.append(("Upcoming", "service in %d days" % left))
    if not found:
        out["status"] = "Incomplete"
        out["reasons"] = ["no service due can be worked out without %s" % " and ".join(out["missing"])]
        return out
    out["status"] = min((s for s, _ in found), key=SERVICE_STATUSES.index)
    # The upcoming count is noise in a warning list; it is shown in the summary instead.
    out["reasons"] = [r for s, r in sorted(found, key=lambda x: SERVICE_STATUSES.index(x[0])) if s != "Upcoming"]
    return out


def asset_service_state(a, today=None):
    """Whether a machine needs attention: its service schedule, and its insurance and fitness."""
    sch = service_schedule(a, today)
    due = sch["status"] in ("Overdue", "Service due")
    soon = sch["status"] == "Due soon"
    reasons = list(sch["reasons"]) if sch["status"] != "Incomplete" else []
    for label, value in (("insurance", a.insurance_until), ("fitness", a.fitness_until)):
        d = _days_until(value)
        if d is not None and d < 0:
            due = True
            reasons.append("%s lapsed %d days ago" % (label, abs(d)))
        elif d is not None and d <= 15:
            soon = True
            reasons.append("%s lapses in %d days" % (label, d))
    return {"due": due, "soon": soon and not due, "reasons": reasons, "status": sch["status"], "schedule": sch}


LOCATION_TYPES = ("Yard", "Site", "Transit")
LOCATION_LABEL = {"Yard": "Yard", "Transit": "In transit"}


def location_type_of(a):
    """Where the machine is kept, as said - a machine on a site is on a site whatever else was recorded."""
    return "Site" if a.current_job_id else (a.location_type or "")


def apply_location(db, client_id, a, body, by_name=""):
    """The Yard / Site / In transit chosen on the form. Not sent: where it is stays as it is.
    A change of site is written to the machine's move history, the same as a move."""
    kind = body.location_type
    if kind in (None, ""):
        return
    if kind not in LOCATION_TYPES:
        raise HTTPException(400, "Where is it - the yard, a site, or in transit?")
    if kind == "Site":
        if not body.location_id:
            raise HTTPException(400, "Which site is it on?")
        job = db.query(models.DBJob).filter(models.DBJob.id == body.location_id, models.DBJob.client_id == client_id).first()
        if not job:
            raise HTTPException(404, "That site was not found.")
        if a.current_job_id != job.id:
            if a.status in ("Under repair", "Breakdown", "Returned", "Disposed"):
                raise HTTPException(409, "%s is %s - it cannot be sent to a site." % (a.code or "The machine", (a.status or "").lower()))
            if a.id:
                db.add(models.DBAssetMove(client_id=client_id, asset_id=a.id, from_job_id=a.current_job_id, to_job_id=job.id,
                                          moved_on=datetime.now().strftime("%Y-%m-%d"), note="Set on the register", by_name=by_name))
            a.current_job_id = job.id
            a.status = "Deployed"
    else:
        if a.current_job_id:
            if a.id:
                db.add(models.DBAssetMove(client_id=client_id, asset_id=a.id, from_job_id=a.current_job_id, to_job_id=None,
                                          moved_on=datetime.now().strftime("%Y-%m-%d"), note="Set on the register", by_name=by_name))
            a.current_job_id = None
            if a.status == "Deployed":
                a.status = "Available"
    a.location_type = kind


def asset_dict(db, a, jobs=None, costs=None):
    job = (jobs or {}).get(a.current_job_id) if jobs is not None else (
        db.query(models.DBJob).filter(models.DBJob.id == a.current_job_id).first()
        if a.current_job_id else None)
    c = (costs or {}).get(a.id, {})
    return {"id": a.id, "code": a.code or "", "name": a.name or "", "category": a.category or "",
            "ownership": a.ownership or "Owned", "brand": a.brand or "", "model": a.model or "",
            "reg_no": a.reg_no or "",
            "purchase_date": a.purchase_date or "", "purchase_value": money(a.purchase_value),
            "hired_from": a.hired_from or "", "hire_rate": money(a.hire_rate),
            "hire_basis": a.hire_basis or "Day", "meter_unit": a.meter_unit or "Hours",
            "meter_reading": a.meter_reading or 0, "service_every": a.service_every or 0,
            "service_every_days": a.service_every_days or 0,
            "last_service_on": a.last_service_on or "", "last_service_meter": a.last_service_meter,
            "service_interval_type": interval_type(a), "reminder_meter": a.reminder_meter,
            "reminder_days": a.reminder_days,
            "insurance_until": a.insurance_until or "", "fitness_until": a.fitness_until or "",
            "current_job_id": a.current_job_id,
            "location_type": location_type_of(a), "location_id": a.current_job_id,
            "current_job": ("%s %s" % (job.number, job.name)).strip() if job else "",
            "where": ("With its owner" if a.status == "Returned" else
                      ("%s %s" % (job.number, job.name)).strip() if job else
                      LOCATION_LABEL.get(a.location_type or "", "Not set")),
            "status": a.status or "Available", "notes": a.notes or "",
            # "Hired" is how the register has always stored a machine hired in; it is shown as Rented.
            "ownership_label": {"Hired": "Rented"}.get(a.ownership or "Owned", a.ownership or "Owned"),
            "condition": a.condition or "Good", "is_archived": bool(a.is_archived),
            "service": asset_service_state(a),
            "cost_to_date": money(c.get("total", 0.0)),
            "hours_to_date": money(c.get("hours", 0.0)),
            "fuel_to_date": money(c.get("litres", 0.0))}


def _apply_asset(a, body):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "What is the machine?")
    own = "Hired" if body.ownership == "Rented" else body.ownership
    ownership = own if own in ("Owned", "Hired", "Leased") else "Owned"
    if ownership == "Hired" and not (body.hire_rate or 0) > 0:
        raise HTTPException(400, "A hired machine needs its hire rate - it is what it costs the site.")
    a.name = name
    a.category = body.category if body.category in ASSET_CATEGORIES else "Other"
    a.ownership = ownership
    a.brand, a.model = (body.brand or "").strip(), (body.model or "").strip()
    a.reg_no = (body.reg_no or "").strip().upper()
    a.purchase_date = (body.purchase_date or "").strip()
    a.purchase_value = money(body.purchase_value or 0)
    a.hired_from = (body.hired_from or "").strip()
    a.hire_rate = money(body.hire_rate or 0)
    a.hire_basis = body.hire_basis if body.hire_basis in HIRE_BASES else "Day"
    a.meter_unit = body.meter_unit if body.meter_unit in ("Hours", "Km") else "Hours"
    a.insurance_until = (body.insurance_until or "").strip()
    a.fitness_until = (body.fitness_until or "").strip()
    a.notes = (body.notes or "").strip()
    if getattr(body, "condition", None):
        if body.condition not in ("Good", "Fair", "Poor"):
            raise HTTPException(400, "Condition is Good, Fair or Poor.")
        a.condition = body.condition


def apply_schedule(a, body, before=None):
    """The maintenance schedule from the form, checked, with its next thresholds worked out.
    Called once the machine's meter and last service are on it; `before` is its schedule_snapshot
    from before the edit touched it. Returns what changed, for the audit."""
    before = before or schedule_snapshot(a)
    t = body.service_interval_type
    if t in (None, ""):
        # Sent without a type (older screens, imports): read it from the intervals sent.
        meter, days = (body.service_every or 0) > 0, (body.service_every_days or 0) > 0
        t = "Both" if meter and days else "Meter" if meter else "Days" if days else "None"
    if t not in INTERVAL_TYPES:
        raise HTTPException(400, "The service interval is by the meter and the calendar, the meter only, or the calendar only.")
    unit = UNIT_WORD.get(a.meter_unit or "Hours", "hours")
    every = float(body.service_every or 0)
    days = body.service_every_days or 0
    if every < 0 or days < 0:
        raise HTTPException(400, "A service interval cannot be negative.")
    if days != int(days):
        raise HTTPException(400, "The calendar interval is a whole number of days.")
    days = int(days)
    uses_meter, uses_days = t in ("Both", "Meter"), t in ("Both", "Days")
    if uses_meter and every <= 0:
        raise HTTPException(400, "How many %s between services?" % unit)
    if uses_days and days <= 0:
        raise HTTPException(400, "How many days between services?")
    if uses_meter:
        if a.last_service_meter is None:
            raise HTTPException(400, "Enter the meter reading at the last service - the next one is counted from it.")
        if a.last_service_meter < 0:
            raise HTTPException(400, "A meter reading cannot be negative.")
        if a.last_service_meter > (a.meter_reading or 0):
            raise HTTPException(400, "The meter reads %g %s now; it cannot have been serviced at %g." % (a.meter_reading or 0, unit, a.last_service_meter))
    if uses_days:
        last = _day(a.last_service_on)
        if not last:
            raise HTTPException(400, "Enter the date of the last service (or the day it started work) - the next one is counted from it.")
        if last > date.today():
            raise HTTPException(400, "The last service cannot be in the future.")
        if last.year < EARLIEST_YEAR:
            raise HTTPException(400, "The last service on %s? Check the year." % last.isoformat())
    rem_m, rem_d = body.reminder_meter, body.reminder_days
    if rem_m is not None and uses_meter and not 0 <= rem_m < every:
        raise HTTPException(400, "The early reminder is a number of %s below the interval (%g)." % (unit, every))
    if rem_d is not None and uses_days and (rem_d != int(rem_d) or not 0 <= rem_d < days):
        raise HTTPException(400, "The early reminder is a whole number of days below the interval (%d)." % days)
    inputs = lambda: (interval_type(a), a.service_every or 0, a.service_every_days or 0, a.last_service_meter, (a.last_service_on or "")[:10])
    was = (before["type"], before["every_meter"], before["every_days"], before["last_service_meter"], before["last_service_on"][:10])
    a.service_interval_type = t
    a.service_every = every if uses_meter else 0.0
    a.service_every_days = days if uses_days else 0
    a.reminder_meter = float(rem_m) if (uses_meter and rem_m is not None) else None
    a.reminder_days = int(rem_d) if (uses_days and rem_d is not None) else None
    # A threshold set by hand when a service was completed stands until the schedule itself is changed.
    same = was == inputs()
    if not (same and uses_meter and a.next_service_meter is not None):
        a.next_service_meter = round(a.last_service_meter + every, 1) if uses_meter else None
    if not (same and uses_days and _day(a.next_service_on)):
        a.next_service_on = (_day(a.last_service_on) + timedelta(days=days)).isoformat() if uses_days else ""
    after = schedule_snapshot(a)
    return {k: (before[k], after[k]) for k in after if before[k] != after[k]}


def schedule_snapshot(a):
    return {"type": interval_type(a), "every_meter": a.service_every or 0, "every_days": a.service_every_days or 0,
            "reminder_meter": a.reminder_meter, "reminder_days": a.reminder_days,
            "last_service_on": a.last_service_on or "", "last_service_meter": a.last_service_meter,
            "next_meter": a.next_service_meter, "next_on": a.next_service_on or "", "unit": a.meter_unit or "Hours"}


def describe_changes(changes):
    return "; ".join("%s %s -> %s" % (k.replace("_", " "), "-" if v[0] in (None, "") else v[0], "-" if v[1] in (None, "") else v[1])
                     for k, v in changes.items())


def record_service_done(a, done_on, meter, next_meter=None, next_on=None):
    """A service done: the clock starts again from it. The next thresholds are the interval on from
    this service, unless given; either way they are after it. Returns the thresholds set."""
    t = interval_type(a)
    unit = UNIT_WORD.get(a.meter_unit or "Hours", "hours")
    done = _day(done_on)
    if not done:
        raise HTTPException(400, "When was it serviced? (YYYY-MM-DD)")
    if done > date.today():
        raise HTTPException(400, "A service cannot be recorded before it is done.")
    if done.year < EARLIEST_YEAR:
        raise HTTPException(400, "Serviced on %s? Check the year." % done.isoformat())
    last = _day(a.last_service_on)
    if last and done < last:
        raise HTTPException(400, "It was last serviced on %s; this service cannot be before that." % a.last_service_on[:10])
    if meter is None and t in ("Both", "Meter"):
        raise HTTPException(400, "The meter reading at this service - the next one is counted from it.")
    if meter is not None:
        if meter < 0:
            raise HTTPException(400, "A meter reading cannot be negative.")
        if a.last_service_meter is not None and meter < a.last_service_meter:
            raise HTTPException(400, "It was last serviced at %g %s; the meter cannot read less now." % (a.last_service_meter, unit))
        if meter > (a.meter_reading or 0):
            a.meter_reading = float(meter)
    if next_meter is not None and (meter is None or next_meter <= meter):
        raise HTTPException(400, "The next service reading is above this one (%s)." % ("%g" % meter if meter is not None else "not given"))
    if next_on and (not _day(next_on) or _day(next_on) <= done or _day(next_on).year > done.year + 20):
        raise HTTPException(400, "The next service is after this one.")
    a.last_service_on = done.isoformat()
    if meter is not None:
        a.last_service_meter = float(meter)
    a.next_service_meter = (float(next_meter) if next_meter is not None else
                            round(meter + a.service_every, 1) if (t in ("Both", "Meter") and meter is not None and (a.service_every or 0) > 0) else None)
    a.next_service_on = (next_on[:10] if next_on else
                         (done + timedelta(days=a.service_every_days)).isoformat() if (t in ("Both", "Days") and (a.service_every_days or 0) > 0) else "")
    return a.next_service_meter, a.next_service_on


def check_unique_asset(db, client_id, a, code=None):
    """No two machines with the same equipment ID or registration number."""
    q = db.query(models.DBAsset).filter(models.DBAsset.client_id == client_id)
    if a.id:
        q = q.filter(models.DBAsset.id != a.id)
    for what, col, value in (("equipment ID", models.DBAsset.code, code if code is not None else a.code),
                             ("registration number", models.DBAsset.reg_no, a.reg_no)):
        v = (value or "").strip()
        if v and q.filter(sqlfunc.lower(col) == v.lower()).first():
            raise HTTPException(409, "Another machine already has the %s %s." % (what, v))


def asset_or_404(db, client_id, asset_id):
    a = db.query(models.DBAsset).filter(models.DBAsset.id == asset_id,
                                        models.DBAsset.client_id == client_id).first()
    if not a:
        raise HTTPException(404, "Machine not found")
    return a


def asset_costs(db, client_id, job_id=None):
    """{asset_id: {fuel, hire, service, total, hours, litres}} in two queries."""
    out = {}
    q = db.query(models.DBAssetLog).filter(models.DBAssetLog.client_id == client_id)
    if job_id:
        q = q.filter(models.DBAssetLog.job_id == job_id)
    for l in q.all():
        c = out.setdefault(l.asset_id, {"fuel": 0.0, "hire": 0.0, "service": 0.0,
                                         "total": 0.0, "hours": 0.0, "litres": 0.0, "idle": 0.0})
        c["fuel"] += l.fuel_cost or 0
        c["hire"] += l.hire_cost or 0
        c["hours"] += l.hours_worked or 0
        c["idle"] += l.idle_hours or 0
        c["litres"] += l.fuel_litres or 0
    q = db.query(models.DBAssetService).filter(models.DBAssetService.client_id == client_id)
    if job_id:
        q = q.filter(models.DBAssetService.job_id == job_id)
    for s in q.all():
        c = out.setdefault(s.asset_id, {"fuel": 0.0, "hire": 0.0, "service": 0.0,
                                         "total": 0.0, "hours": 0.0, "litres": 0.0, "idle": 0.0})
        c["service"] += s.total_cost or 0
    for c in out.values():
        c["total"] = money(c["fuel"] + c["hire"] + c["service"])
    return out


def equipment_cost_by_job(db, client_id):
    """What the machines cost each project - read by the project P&L."""
    out = {}
    for l in db.query(models.DBAssetLog).filter(models.DBAssetLog.client_id == client_id).all():
        if l.job_id:
            out[l.job_id] = money(out.get(l.job_id, 0.0) + (l.fuel_cost or 0) + (l.hire_cost or 0))
    for s in db.query(models.DBAssetService).filter(models.DBAssetService.client_id == client_id).all():
        if s.job_id:
            out[s.job_id] = money(out.get(s.job_id, 0.0) + (s.total_cost or 0))
    return out


def next_asset_code(db, client_id):
    """One past the highest EQP number in use - a count would hand out a code twice once one was deleted."""
    best = 0
    for (c,) in db.query(models.DBAsset.code).filter(models.DBAsset.client_id == client_id).all():
        m = re.match(r"^EQP-(\d+)$", c or "")
        if m:
            best = max(best, int(m.group(1)))
    return "EQP-%04d" % (best + 1)


def hire_cost_for(a, hours_worked):
    """What a hired machine costs for one logged day on its hire terms."""
    if (a.ownership or "") not in ("Hired", "Leased") or not a.hire_rate:
        return 0.0
    if a.hire_basis == "Hour":
        return money(a.hire_rate * (hours_worked or 0))
    if a.hire_basis == "Month":
        return money(a.hire_rate / DAYS_IN_A_HIRE_MONTH)
    return money(a.hire_rate)


def fy_label(y):
    return "%d-%02d" % (y, (y + 1) % 100)


def fy_start_year(value):
    """The year a financial year starts in, from "2026-27", a date, or a
    date object. April to March."""
    if isinstance(value, date):
        return value.year if value.month >= 4 else value.year - 1
    text = str(value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})$", text)
    if m and int(m.group(2)) == (int(m.group(1)) + 1) % 100:
        return int(m.group(1))
    d = _parse_date(text)
    return fy_start_year(d) if d else None


def fy_bounds(y):
    return date(y, 4, 1), date(y + 1, 3, 31)


def ensure_tax_blocks(db, client_id):
    have = {b.name for b in db.query(models.DBTaxBlock).filter(
        models.DBTaxBlock.client_id == client_id).all()}
    added = False
    for name, rate in TAX_BLOCK_DEFAULTS:
        if name not in have:
            db.add(models.DBTaxBlock(client_id=client_id, name=name, rate=rate))
            added = True
    if added:
        db.flush()
    return db.query(models.DBTaxBlock).filter(
        models.DBTaxBlock.client_id == client_id).order_by(models.DBTaxBlock.id).all()


def wdv_rate(book):
    """The written-down rate that brings cost to its residual over the life:
    1 - (residual / cost) ^ (1 / life)."""
    cost = book.cost or 0
    residual = cost * (book.residual_percent or 0) / 100.0
    if cost <= 0 or residual <= 0 or (book.life_years or 0) <= 0:
        return 0.0
    return 1.0 - (residual / cost) ** (1.0 / float(book.life_years))


def book_schedule(book, upto_year):
    """Year by year, from the year the book starts to `upto_year`: opening,
    added, depreciation, what it fetched if it went, and closing."""
    rows = []
    put = _parse_date(book.put_to_use_on)
    cost = money(book.cost or 0)
    if not put or cost <= 0 or (book.life_years or 0) <= 0:
        return rows
    residual = money(cost * (book.residual_percent or 0) / 100.0)
    rate = wdv_rate(book)
    annual = (cost - residual) / float(book.life_years)
    opening_year = fy_start_year(book.opening_fy) if book.opening_fy else None
    if opening_year is not None and opening_year <= fy_start_year(put):
        opening_year = None          # an opening no earlier than purchase is just the purchase
    start = opening_year if opening_year is not None else fy_start_year(put)
    gone = _parse_date(book.disposed_on)
    closing = 0.0
    for y in range(start, upto_year + 1):
        fy_from, fy_to = fy_bounds(y)
        days_in = (fy_to - fy_from).days + 1
        if y == start and opening_year is not None:
            opening, added, from_day = money(book.opening_book_value or 0), 0.0, fy_from
        elif y == start:
            opening, added, from_day = 0.0, cost, put
        else:
            opening, added, from_day = closing, 0.0, fy_from
        if gone and gone < from_day:
            break
        to_day = gone if gone and gone <= fy_to else fy_to
        used = max(0, (to_day - from_day).days + 1)
        base = money(opening + added)
        room = max(0.0, base - residual)
        if book.method == "SLM":
            dep = min(annual * used / days_in, room)
        else:
            dep = min(base * rate * used / days_in, room)
        dep = money(dep)
        closing = money(base - dep)
        row = {"fy": fy_label(y), "opening": opening, "added": added, "depreciation": dep,
               "closing": closing, "accumulated": money(cost - closing),
               "days": used, "disposed": False, "disposal_value": 0.0, "gain": 0.0}
        if gone and fy_from <= gone <= fy_to:
            row.update({"disposed": True, "disposal_value": money(book.disposal_value or 0),
                        "book_value_at_sale": closing,
                        "gain": money((book.disposal_value or 0) - closing), "closing": 0.0,
                        "accumulated": money(cost - closing)})
            rows.append(row)
            break
        rows.append(row)
    return rows


def book_dict(book, a, fy_year):
    rows = book_schedule(book, fy_year)
    row = next((r for r in rows if r["fy"] == fy_label(fy_year)), None)
    before = rows[-1] if rows and not row else None
    return {
        "asset_id": a.id, "code": a.code or "", "name": a.name or "", "category": a.category or "",
        "status": a.status or "", "method": book.method or "WDV",
        "life_years": book.life_years or 0, "residual_percent": book.residual_percent or 0,
        "rate_percent": round(wdv_rate(book) * 100, 2) if book.method != "SLM"
        else (round(100.0 / book.life_years, 2) if book.life_years else 0),
        "put_to_use_on": book.put_to_use_on or "", "cost": money(book.cost),
        "opening_fy": book.opening_fy or "", "opening_book_value": money(book.opening_book_value),
        "tax_block": book.tax_block or "", "disposed_on": book.disposed_on or "",
        "disposal_value": money(book.disposal_value), "disposal_note": book.disposal_note or "",
        # The year asked for; an asset gone before it, or not yet bought, has none.
        "year": row,
        "in_year": bool(row),
        "gone_before": bool(before and before.get("disposed")),
    }


def asset_book_or_none(db, client_id, asset_id):
    return db.query(models.DBAssetBook).filter(
        models.DBAssetBook.client_id == client_id,
        models.DBAssetBook.asset_id == asset_id).first()


def default_book(a):
    life, block = ASSET_BOOK_DEFAULTS.get(a.category or "Other", ASSET_BOOK_DEFAULTS["Other"])
    return {"method": "WDV", "life_years": life, "residual_percent": 5.0,
            "put_to_use_on": a.purchase_date or "", "cost": money(a.purchase_value),
            "tax_block": block}


def _apply_book(db, client_id, a, b, body):
    method = (body.method or "WDV").upper()
    if method not in BOOK_METHODS:
        raise HTTPException(400, "Method is WDV (written-down value) or SLM (straight line).")
    d = default_book(a)
    life = float(body.life_years if body.life_years is not None else d["life_years"])
    if not 0 < life <= 100:
        raise HTTPException(400, "Useful life should be between a year and a hundred.")
    residual = float(body.residual_percent if body.residual_percent is not None else 5.0)
    if not 0 <= residual < 100:
        raise HTTPException(400, "Residual value is a percentage of cost, under a hundred.")
    if method == "WDV" and residual <= 0:
        raise HTTPException(400, "Written-down value needs a residual above nought - five per cent is usual.")
    cost = money(body.cost if body.cost is not None else d["cost"])
    if cost <= 0:
        raise HTTPException(400, "What did it cost? The purchase bill value, with anything spent to bring it into use.")
    put = (body.put_to_use_on or d["put_to_use_on"] or "")[:10]
    if not _parse_date(put):
        raise HTTPException(400, "When was it put to use? (YYYY-MM-DD)")
    opening_fy = (body.opening_fy or "").strip()
    opening_value = money(body.opening_book_value or 0)
    if opening_fy:
        y = fy_start_year(opening_fy)
        if y is None:
            raise HTTPException(400, "Opening year should read like 2025-26.")
        opening_fy = fy_label(y)
        if y > fy_start_year(put):
            if opening_value <= 0:
                raise HTTPException(400, "What was its book value at the start of %s? The last audited "
                                         "accounts carry it." % opening_fy)
            if opening_value > cost + 0.009:
                raise HTTPException(400, "The opening book value cannot be more than it cost.")
        else:
            opening_fy, opening_value = "", 0.0
    blocks = {x.name for x in ensure_tax_blocks(db, client_id)}
    block = (body.tax_block or d["tax_block"]).strip()
    if block not in blocks:
        raise HTTPException(400, "Unknown income-tax block: %s" % block)
    b.method, b.life_years, b.residual_percent = method, life, residual
    b.cost, b.put_to_use_on, b.tax_block = cost, put, block
    b.opening_fy, b.opening_book_value = opening_fy, opening_value
    b.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return b


def tax_block_schedule(db, client_id, year):
    """Income-tax depreciation, block by block, for one year.

    Opening WDV, plus what was bought (at the full rate if used 180 days or
    more that year, half the rate if less), less what anything sold fetched.
    Where sales take a block below nothing, the excess is a short-term gain
    and the block closes at nought; where every asset in a block has gone,
    what is left is a short-term loss and no depreciation is due on it."""
    blocks = ensure_tax_blocks(db, client_id)
    books = db.query(models.DBAssetBook).filter(models.DBAssetBook.client_id == client_id).all()
    out = []
    for blk in blocks:
        mine = [b for b in books if b.tax_block == blk.name and _parse_date(b.put_to_use_on)]
        open_year = fy_start_year(blk.opening_fy) if blk.opening_fy else None
        years = [fy_start_year(b.put_to_use_on) for b in mine]
        start = open_year if open_year is not None else (min(years) if years else year)
        closing = money(blk.opening_wdv or 0) if open_year is not None else 0.0
        row = None
        for y in range(start, year + 1):
            fy_from, fy_to = fy_bounds(y)
            opening = closing
            full = half = deleted = 0.0
            counted = []
            for b in mine:
                put = _parse_date(b.put_to_use_on)
                # Bought before the block's opening: already inside that WDV.
                if open_year is not None and fy_start_year(put) < open_year:
                    pass
                elif fy_from <= put <= fy_to:
                    if (fy_to - put).days + 1 >= HALF_RATE_DAYS:
                        full += b.cost or 0
                    else:
                        half += b.cost or 0
                gone = _parse_date(b.disposed_on)
                if gone and fy_from <= gone <= fy_to:
                    deleted += b.disposal_value or 0
                    counted.append(b)
            base = money(opening + full + half - deleted)
            left = [b for b in mine if not (_parse_date(b.disposed_on) and _parse_date(b.disposed_on) <= fy_to)]
            ceased = bool(mine) and not left and not (blk.opening_wdv or 0)
            gain = loss = dep = 0.0
            if base < 0:
                gain, closing = money(-base), 0.0
            elif ceased:
                loss, closing = base, 0.0
            else:
                half_part = min(money(half), base)
                full_part = money(base - half_part)
                dep = money(full_part * blk.rate / 100.0 + half_part * blk.rate / 200.0)
                closing = money(base - dep)
            row = {"block_id": blk.id, "block": blk.name, "rate": blk.rate, "fy": fy_label(y),
                   "opening": opening, "added_full": money(full), "added_half": money(half),
                   "deleted": money(deleted), "depreciation": dep, "closing": closing,
                   "short_term_gain": gain, "short_term_loss": loss,
                   "opening_fy": blk.opening_fy or "", "opening_wdv": money(blk.opening_wdv),
                   "assets": len(left)}
        if row is None:
            row = {"block_id": blk.id, "block": blk.name, "rate": blk.rate, "fy": fy_label(year),
                   "opening": 0.0, "added_full": 0.0, "added_half": 0.0, "deleted": 0.0,
                   "depreciation": 0.0, "closing": 0.0, "short_term_gain": 0.0, "short_term_loss": 0.0,
                   "opening_fy": blk.opening_fy or "", "opening_wdv": money(blk.opening_wdv), "assets": 0}
        out.append(row)
    return out
