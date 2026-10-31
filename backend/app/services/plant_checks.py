"""What Equipment & Plant checks for itself: that a meter only ever runs forward, that the fuel fits the hours, that a
hire bill fits its agreement, and the alerts that come of all that. Everything is worked out from the records each time;
only decisions (a replaced meter, a review, an alert raised) are stored."""
import calendar
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app import models
from app.constants.projects import JOB_FINISHED
from app.core.config import logger
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.notifications import notify
from app.core.scheduler import scheduled_job
from app.services.assets import asset_service_state, hire_cost_for
from app.services.plant import clean_day, in_range, invoice_period, machine_hours, month_end, now, today

DEFAULT_DOCUMENT_ALERT_DAYS = 30
DEFAULT_FUEL_TOLERANCE = 20.0       # percent over the norm before it is a flag
DEFAULT_RENTAL_TOLERANCE = 2.0      # percent off the agreement before a bill is flagged
RETURN_ALERT_DAYS = 3
SITE_SILENT_DAYS = 2

FLAG_LABELS = {"above_norm": "Fuel Anomaly", "over_tank": "Requires Investigation", "no_hours": "Possible Fuel Misuse"}
FLAG_DECISIONS = {"investigate": "Under review", "resolve": "Resolved", "dismiss": "Dismissed"}


# ---- settings ------------------------------------------------------------------------------------

def _setting(db, client_id, key, default, low, high):
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == key).first()
    try:
        value = float(row.value) if row and row.value not in (None, "") else default
    except ValueError:
        return default
    return value if low <= value <= high else default


def alert_settings(db, client_id):
    return {"document_alert_days": int(_setting(db, client_id, "plant_document_alert_days", DEFAULT_DOCUMENT_ALERT_DAYS, 1, 365)),
            "fuel_tolerance_percent": _setting(db, client_id, "plant_fuel_tolerance_percent", DEFAULT_FUEL_TOLERANCE, 0, 200),
            "rental_tolerance_percent": _setting(db, client_id, "plant_rental_tolerance_percent", DEFAULT_RENTAL_TOLERANCE, 0, 100)}


def job_label(jobs, jid):
    j = jobs.get(jid)
    return ("%s %s" % (j.number or "", j.name or "")).strip() if j else ""


def jobs_of(db, client_id):
    return {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}


# ---- the meter -----------------------------------------------------------------------------------

def reading_of(log):
    """The reading a log ended on; older logs carry one reading only."""
    return log.closing_meter if log.closing_meter is not None else log.meter_reading


def _readings(db, asset_id, skip_id=None):
    """Every standing log of a machine that has a reading, in order."""
    L = models.DBAssetLog
    q = db.query(L).filter(L.asset_id == asset_id, (L.approval_status != "Rejected") | L.approval_status.is_(None))
    if skip_id:
        q = q.filter(L.id != skip_id)
    rows = [l for l in q.all() if reading_of(l) is not None]
    return sorted(rows, key=lambda l: (l.log_date or "", l.start_time or "", l.id))


def _replacements(db, asset_id):
    M = models.DBPlantMeterEvent
    return db.query(M).filter(M.asset_id == asset_id, M.kind == "Replaced").order_by(M.on_date, M.id).all()


def last_valid_reading(db, a, on, shift, start_time, skip_id=None):
    """(reading, date, what it is) the next opening has to follow on from. Another line of the same machine, day and
    shift is the same stretch of work, so it is not 'before' this one."""
    before = [l for l in _readings(db, a.id, skip_id) if (l.log_date, l.start_time or "") < (on, start_time or "")
              and not (l.log_date == on and (l.shift or "") == shift)]
    prior = before[-1] if before else None
    fitted = [e for e in _replacements(db, a.id) if e.on_date <= on and e.log_id != skip_id]
    latest = fitted[-1] if fitted else None
    if latest and (not prior or (latest.on_date >= prior.log_date and latest.log_id != prior.id)):
        return latest.new_reading, latest.on_date, "the replacement meter"
    if prior:
        return reading_of(prior), prior.log_date, "the last closing reading"
    # Nothing logged yet: the register's reading, for days since the machine came onto it.
    if (a.meter_reading or 0) > 0 and (a.created_at or "")[:10] <= on:
        return a.meter_reading, (a.created_at or "")[:10], "the machine's register reading"
    return None, "", ""


def check_meter(db, a, body, v, skip_id=None):
    """Refuse a reading that runs the meter backwards. A replaced meter is the one exception, and it has to be said.
    Returns what a replacement has to record, or None."""
    opening, closing = v["opening_meter"], v["closing_meter"]
    replaced = bool(getattr(body, "meter_replaced", False))
    if opening is None:
        if replaced:
            raise HTTPException(400, "Give the new meter's opening reading.")
        return None
    last, last_on, what = last_valid_reading(db, a, v["log_date"], v["shift"], v["start_time"], skip_id)
    if replaced:
        when = clean_day(body.replacement_date, "replacement date", required=True)
        why = (body.replacement_reason or "").strip()
        if not why:
            raise HTTPException(400, "Say why the meter was replaced - it goes on the record.")
        if when > v["log_date"]:
            raise HTTPException(400, "The meter cannot be replaced after the day that reads it.")
        if last_on and when < last_on:
            raise HTTPException(400, "The old meter was still being read on %s." % last_on)
        return {"on": when, "reason": why[:300], "old": last if last is not None else (a.meter_reading or 0), "new": opening}
    if last is not None and opening < last - 0.001:
        raise HTTPException(400, "The opening reading (%g) is below %s (%g on %s). A meter only runs forward: check the reading, or "
                                 "tick Meter Replaced and give the date and reason." % (opening, what, last, last_on))
    following = [l for l in _readings(db, a.id, skip_id) if (l.log_date, l.start_time or "") > (v["log_date"], v["start_time"] or "")
                 and not (l.log_date == v["log_date"] and (l.shift or "") == v["shift"]) and l.opening_meter is not None]
    fitted_after = [e for e in _replacements(db, a.id) if e.on_date > v["log_date"]]
    if following and closing is not None and not skip_id and closing > following[0].opening_meter + 0.001:
        if not fitted_after or fitted_after[0].on_date > following[0].log_date:
            raise HTTPException(400, "The closing reading (%g) is above the opening reading of %s (%g)." % (closing, following[0].log_date, following[0].opening_meter))
    return None


def record_replacement(db, client_id, a, rep, log, actor):
    """A new meter starts a new count. The service schedule is on the old count, so it moves by the same amount: what
    was left to the next service is still left to it."""
    db.add(models.DBPlantMeterEvent(client_id=client_id, asset_id=a.id, log_id=log.id, kind="Replaced", on_date=rep["on"],
                                    old_reading=rep["old"], new_reading=rep["new"], reason=rep["reason"], by_name=actor))
    shift = rep["new"] - rep["old"]
    if a.next_service_meter is not None:
        a.next_service_meter = round(a.next_service_meter + shift, 2)
    if a.last_service_meter is not None:
        a.last_service_meter = round(a.last_service_meter + shift, 2)
    a.meter_reading = log.closing_meter if log.closing_meter is not None else rep["new"]


def resync_meter(db, a, old_reading=None):
    """After a correction or a rejection, the machine reads what its latest standing log says - unless something else
    has since moved it on (a fuel fill's reading, a service), which is left alone."""
    rows = _readings(db, a.id)
    if rows and (old_reading is None or abs((a.meter_reading or 0) - old_reading) < 0.01):
        a.meter_reading = reading_of(rows[-1])


def apply_correction(db, client_id, a, log, before, actor, reason):
    """Record a corrected reading and carry it on: the next line opened on the old closing, so it now opens on the new
    one and its hours are worked out again. Fuel per hour, billable hours and costs are read from the logs, so they follow."""
    M = models.DBPlantMeterEvent
    changed = False
    for field, old, new in (("opening", before["opening"], log.opening_meter), ("closing", before["closing"], log.closing_meter)):
        if old != new:
            changed = True
            db.add(M(client_id=client_id, asset_id=a.id, log_id=log.id, kind="Corrected", on_date=log.log_date, field=field,
                     old_reading=old, new_reading=new, reason=reason[:300], by_name=actor))
    if not changed:
        return None
    following = None
    if before["closing"] is not None and log.closing_meter is not None and before["closing"] != log.closing_meter:
        later = [l for l in _readings(db, a.id, log.id) if (l.log_date, l.start_time or "") > (log.log_date, log.start_time or "")
                 and not (l.log_date == log.log_date and (l.shift or "") == (log.shift or "")) and l.opening_meter is not None]
        following = later[0] if later and abs(later[0].opening_meter - before["closing"]) < 0.001 else None
    if following:
        if following.closing_meter is not None and log.closing_meter > following.closing_meter + 0.001:
            raise HTTPException(400, "The new closing reading (%g) is past the closing reading of %s (%g). Correct that day first." % (
                log.closing_meter, following.log_date, following.closing_meter))
        db.add(M(client_id=client_id, asset_id=a.id, log_id=following.id, kind="Corrected", on_date=following.log_date, field="opening",
                 old_reading=following.opening_meter, new_reading=log.closing_meter, reason=("Carried from %s: %s" % (log.log_date, reason))[:300], by_name=actor))
        following.opening_meter = log.closing_meter
        if following.closing_meter is not None and (a.meter_unit or "Hours") == "Hours":
            following.hours_worked = round(following.closing_meter - following.opening_meter, 2)
            if following.hire_cost:
                following.hire_cost = hire_cost_for(a, following.hours_worked)
    resync_meter(db, a, before["closing"])
    return following


def following_is_approved(db, a, log, old_closing):
    """Whether correcting this closing reading would carry into a day somebody has already approved."""
    later = [l for l in _readings(db, a.id, log.id) if (l.log_date, l.start_time or "") > (log.log_date, log.start_time or "")
             and not (l.log_date == log.log_date and (l.shift or "") == (log.shift or "")) and l.opening_meter is not None]
    return bool(later) and old_closing is not None and abs(later[0].opening_meter - old_closing) < 0.001 and later[0].approval_status == "Approved"


def meter_gaps(db, client_id, asset_id=0):
    """Where the readings stop and start again: days with no reading between two that have one, and hours the meter ran
    that nobody logged. Filling the missing days clears a gap by itself."""
    A, M = models.DBAsset, models.DBPlantMeterEvent
    assets = {a.id: a for a in db.query(A).filter(A.client_id == client_id).all() if not asset_id or a.id == asset_id}
    resolved = {(e.asset_id, e.on_date, e.to_date): e for e in db.query(M).filter(M.client_id == client_id, M.kind == "GapResolved").all()}
    L = models.DBAssetLog
    rows = [l for l in db.query(L).filter(L.client_id == client_id).all()
            if (l.approval_status or "") != "Rejected" and l.asset_id in assets and reading_of(l) is not None]
    fitted = {}
    for e in db.query(M).filter(M.client_id == client_id, M.kind == "Replaced").all():
        fitted.setdefault(e.asset_id, []).append(e.on_date)
    by_asset = {}
    for l in sorted(rows, key=lambda l: (l.log_date or "", l.start_time or "", l.id)):
        by_asset.setdefault(l.asset_id, []).append(l)
    out = []
    for aid, logs in by_asset.items():
        a = assets[aid]
        for prev, nxt in zip(logs, logs[1:]):
            if prev.log_date == nxt.log_date:
                continue
            d0, d1 = _parse_date(prev.log_date), _parse_date(nxt.log_date)
            missing = (d1 - d0).days - 1 if d0 and d1 else 0
            swapped = any(prev.log_date <= x <= nxt.log_date for x in fitted.get(aid, ()))
            jump = 0.0
            if nxt.opening_meter is not None and not swapped:
                jump = round(nxt.opening_meter - reading_of(prev), 2)
            if missing <= 0 and jump <= 0:
                continue
            done = resolved.get((aid, prev.log_date, nxt.log_date))
            out.append({"asset_id": aid, "code": a.code, "machine": a.name, "from": prev.log_date, "to": nxt.log_date, "days_without_reading": max(0, missing),
                        "last_closing": reading_of(prev), "next_opening": nxt.opening_meter, "unlogged_meter": max(0.0, jump), "unit": (a.meter_unit or "Hours").lower(),
                        "resolved": bool(done), "note": done.reason if done else "", "resolved_by": done.by_name if done else ""})
    return sorted(out, key=lambda g: (g["resolved"], g["to"]), reverse=False)


def meter_history(db, client_id, a):
    """Everything that happened to a machine's meter, oldest first."""
    L, M = models.DBAssetLog, models.DBPlantMeterEvent
    jobs = jobs_of(db, client_id)
    rows = []
    for l in db.query(L).filter(L.asset_id == a.id).all():
        if reading_of(l) is None:
            continue
        rows.append({"type": "Reading", "date": l.log_date, "at": l.log_date + " " + (l.start_time or ""), "shift": l.shift or "", "opening": l.opening_meter,
                     "closing": reading_of(l), "hours": l.hours_worked or 0, "status": l.approval_status or "Recorded", "project": job_label(jobs, l.job_id),
                     "by": l.recorded_by_name or "", "approved_by": l.approved_by or "", "note": "", "log_id": l.id})
    for e in db.query(M).filter(M.asset_id == a.id).order_by(M.id).all():
        label = {"Replaced": "Meter replaced", "Corrected": "Reading corrected", "GapResolved": "Gap reviewed"}.get(e.kind, e.kind)
        note = e.reason or ""
        if e.kind == "Corrected":
            note = "%s reading: %s" % (e.field.capitalize(), note)
        rows.append({"type": label, "date": e.on_date, "at": e.on_date + " ~" + (e.created_at or ""), "shift": "", "opening": e.old_reading, "closing": e.new_reading,
                     "hours": None, "status": "", "project": "", "by": e.by_name or "", "approved_by": "", "note": note, "log_id": e.log_id})
    rows.sort(key=lambda r: r["at"])
    return rows


def duplicate_days(db, client_id):
    """Machine-days where the records may say the same day twice. For review: nothing here is ever removed by itself."""
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client_id).all()}
    days = {}
    for l in db.query(models.DBAssetLog).filter(models.DBAssetLog.client_id == client_id).all():
        if (l.approval_status or "") != "Rejected":
            days.setdefault((l.asset_id, l.log_date), []).append(l)
    out = []
    for (aid, day), logs in days.items():
        older = [l for l in logs if not l.shift]
        same = {}
        for l in logs:
            if l.shift:
                same.setdefault((l.shift, l.employee_id), []).append(l)
        repeated = [v for v in same.values() if len(v) > 1]
        if (older and len(logs) > 1) or repeated:
            a = assets.get(aid)
            out.append({"asset_id": aid, "code": a.code if a else "", "machine": a.name if a else "", "date": day, "reason": "Older Log day beside a logbook entry" if older else "Same shift and person twice",
                        "entries": [{"id": l.id, "shift": l.shift or "(older Log day)", "operator": l.operator or "", "hours": l.hours_worked or 0, "status": l.approval_status or "Recorded", "by": l.recorded_by_name or ""} for l in logs]})
    return sorted(out, key=lambda x: x["date"], reverse=True)


# ---- fuel ----------------------------------------------------------------------------------------

def _hours_by_day(db, client_id):
    """{asset: {day: machine hours}}, standing logs only, each machine-day-shift once."""
    logs = [l for l in db.query(models.DBAssetLog).filter(models.DBAssetLog.client_id == client_id).all() if (l.approval_status or "") != "Rejected"]
    out = {}
    for h in machine_hours(logs):
        d = out.setdefault(h["asset_id"], {})
        d[h["date"]] = d.get(h["date"], 0.0) + (h["operating"] or 0)
    return out


def _hours_between(days, a, b):
    return sum(h for d, h in days.items() if a <= d <= b)


def tank_warning(a, litres):
    if a.tank_capacity_l and litres > a.tank_capacity_l:
        return "%g L is more than the %s tank holds (%g L) - flagged for investigation." % (litres, a.code, a.tank_capacity_l)
    return ""


def fuel_flags_for(a, fills, days, tolerance):
    """The flags on one machine's fills, oldest first. A fill replaces what was burned since the fill before, so it is
    measured against those hours; the first fill on record has nothing to be measured against."""
    flags = []
    prev = None
    for f in fills:
        day = (f.filled_at or "")[:10]
        if a.tank_capacity_l and (f.litres or 0) > a.tank_capacity_l:
            flags.append((f, "over_tank", "%g L is more than the tank holds (%g L)." % (f.litres, a.tank_capacity_l)))
        if prev is not None:
            prev_day = (prev.filled_at or "")[:10]
            hours = _hours_between(days, prev_day, day)
            if f.meter_reading is not None and prev.meter_reading is not None and (a.meter_unit or "Hours") == "Hours":
                hours = max(0.0, round(f.meter_reading - prev.meter_reading, 2))
            if hours <= 0:
                flags.append((f, "no_hours", "Filled with no operating hours recorded since the fill of %s." % prev_day))
            elif a.fuel_norm_lph:
                actual = (f.litres or 0) / hours
                limit = a.fuel_norm_lph * (1 + tolerance / 100.0)
                if actual > limit:
                    flags.append((f, "above_norm", "%.2f L/h since %s, against a norm of %g L/h (%g%% tolerance)." % (actual, prev_day, a.fuel_norm_lph, tolerance)))
        prev = f
    return flags


def fuel_monitor(db, client_id, date_from="", date_to="", asset_id=0):
    """Machine by machine, consumption against the norm, and every flag with where its review stands."""
    settings = alert_settings(db, client_id)
    tolerance = settings["fuel_tolerance_percent"]
    A, F = models.DBAsset, models.DBPlantFuel
    assets = {a.id: a for a in db.query(A).filter(A.client_id == client_id).all() if not asset_id or a.id == asset_id}
    fills = {}
    for f in db.query(F).filter(F.client_id == client_id).order_by(F.filled_at, F.id).all():
        if f.asset_id in assets:
            fills.setdefault(f.asset_id, []).append(f)
    hours = _hours_by_day(db, client_id)
    jobs = jobs_of(db, client_id)
    reviews = {(r.fuel_id, r.reason): r for r in db.query(models.DBPlantFuelReview).filter(models.DBPlantFuelReview.client_id == client_id).all()}
    machines, flags = [], []
    for aid, a in assets.items():
        days = hours.get(aid, {})
        shown = [f for f in fills.get(aid, []) if in_range(f.filled_at, date_from, date_to)]
        worked = round(sum(h for d, h in days.items() if in_range(d, date_from, date_to)), 2)
        if not shown and not a.fuel_norm_lph and not a.tank_capacity_l:
            continue
        litres = round(sum(f.litres or 0 for f in shown), 2)
        actual = round(litres / worked, 2) if worked else 0.0
        expected = round((a.fuel_norm_lph or 0) * worked, 2)
        over = bool(a.fuel_norm_lph and worked and actual > a.fuel_norm_lph * (1 + tolerance / 100.0))
        machine_flags = [x for x in fuel_flags_for(a, fills.get(aid, []), days, tolerance) if in_range(x[0].filled_at, date_from, date_to)]
        for f, reason, detail in machine_flags:
            r = reviews.get((f.id, reason))
            flags.append({"fuel_id": f.id, "number": f.number, "date": (f.filled_at or "")[:10], "asset_id": aid, "code": a.code, "machine": a.name, "project": job_label(jobs, f.job_id),
                          "litres": f.litres or 0, "reason": reason, "label": FLAG_LABELS[reason], "detail": detail, "status": r.status if r else "Open",
                          "note": r.note if r else "", "reviewed_by": r.by_name if r else "", "reviewed_at": (r.updated_at or "")[:16] if r else ""})
        machines.append({"asset_id": aid, "code": a.code, "name": a.name, "litres": litres, "operating_hours": worked, "actual_lph": actual, "fuel_norm_lph": a.fuel_norm_lph,
                         "expected_litres": expected, "tank_capacity_l": a.tank_capacity_l, "over_norm": over, "open_flags": len([1 for f, reason, _ in machine_flags
                                                                                                                                 if not reviews.get((f.id, reason)) or reviews[(f.id, reason)].status == "Under review"])})
    flags.sort(key=lambda x: x["date"], reverse=True)
    return {"machines": sorted(machines, key=lambda m: -m["litres"]), "flags": flags, "tolerance_percent": tolerance}


def review_fuel_flag(db, client_id, body, actor):
    if body.decision not in FLAG_DECISIONS:
        raise HTTPException(400, "Investigate, resolve or dismiss.")
    if body.reason not in FLAG_LABELS:
        raise HTTPException(400, "That is not a fuel flag.")
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "Give the reason - it goes on the record.")
    f = db.query(models.DBPlantFuel).filter(models.DBPlantFuel.id == body.fuel_id, models.DBPlantFuel.client_id == client_id).first()
    if not f:
        raise HTTPException(404, "Fuel entry not found")
    R = models.DBPlantFuelReview
    r = db.query(R).filter(R.fuel_id == f.id, R.reason == body.reason).first()
    if not r:
        r = R(client_id=client_id, fuel_id=f.id, reason=body.reason)
        db.add(r)
    r.status, r.note, r.by_name, r.updated_at = FLAG_DECISIONS[body.decision], note[:1000], actor, now()
    return f, r


# ---- rental bills --------------------------------------------------------------------------------

def _days(a, b):
    d = _parse_date(a)
    last = _parse_date(b)
    while d <= last:
        yield d.isoformat()
        d += timedelta(days=1)


def _month_share(first, last):
    """How much of a calendar month (or months) a stretch of days is: the whole of October is 1."""
    share = 0.0
    for day in _days(first, last):
        d = _parse_date(day)
        share += 1.0 / calendar.monthrange(d.year, d.month)[1]
    return share


def expected_charge(r, period_from, period_to, hours):
    """What the agreement comes to for a stretch of days, on its own billing cycle. The agreement's minimum is per
    cycle: per day on daily hire, per week on weekly, per month on hourly and monthly hire. A part cycle pays its share.
    Days before the machine arrived or after it went back are not on hire."""
    first = max(period_from, r.start_date or period_from)
    last = min(period_to, r.actual_return) if r.actual_return else period_to
    if last < first:
        return {"days_on_hire": 0, "minimum_hours": 0.0, "actual_hours": 0.0, "overtime_hours": 0.0, "base": 0.0, "overtime": 0.0, "transport": 0.0, "expected": 0.0}
    span = list(_days(first, last))
    worked = round(sum(hours.get(d, 0.0) for d in span), 2)
    minimum_cycle, rate, ot_rate = r.min_billable_hours or 0.0, r.rate or 0.0, r.overtime_rate or 0.0
    if r.billing == "Daily":
        minimum, base = minimum_cycle * len(span), rate * len(span)
        overtime = sum(max(0.0, hours.get(d, 0.0) - minimum_cycle) for d in span) if minimum_cycle else 0.0
    elif r.billing == "Weekly":
        minimum, base = minimum_cycle * len(span) / 7.0, rate * len(span) / 7.0
        overtime = max(0.0, worked - minimum) if minimum_cycle else 0.0
    elif r.billing == "Monthly":
        share = _month_share(first, last)
        minimum, base = minimum_cycle * share, rate * share
        overtime = max(0.0, worked - minimum) if minimum_cycle else 0.0
    else:                       # Hourly: the hours worked, or the minimum if they fall short
        minimum = minimum_cycle * _month_share(first, last)
        overtime = max(0.0, worked - minimum) if minimum_cycle else 0.0
        base = (max(worked, minimum) - overtime) * rate
        ot_rate = ot_rate or rate
    extra = overtime * ot_rate
    transport = (r.transport_charges or 0.0) if first <= (r.start_date or "") <= last else 0.0
    return {"days_on_hire": len(span), "minimum_hours": round(minimum, 2), "actual_hours": worked, "overtime_hours": round(overtime, 2), "base": money(base),
            "overtime": money(extra), "transport": money(transport), "expected": money(base + extra + transport)}


def _months(first, last):
    y, m = int(first[:4]), int(first[5:7])
    while "%04d-%02d" % (y, m) <= last[:7]:
        yield "%04d-%02d" % (y, m)
        m += 1
        if m > 12:
            y, m = y + 1, 1


def rental_rows(db, client_id, month="", rental_id=0, upto=None):
    """Every bill against what its agreement comes to, and every month that should have a bill and does not."""
    upto = upto or today()
    settings = alert_settings(db, client_id)
    tolerance = settings["rental_tolerance_percent"]
    R, I = models.DBPlantRental, models.DBPlantRentalInvoice
    q = db.query(R).filter(R.client_id == client_id)
    if rental_id:
        q = q.filter(R.id == rental_id)
    rentals = q.all()
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client_id).all()}
    providers = {p.id: p for p in db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.client_id == client_id).all()}
    invoices = {}
    for inv in db.query(I).filter(I.client_id == client_id).order_by(I.invoice_date, I.id).all():
        invoices.setdefault(inv.rental_id, []).append(inv)
    hours = _hours_by_day(db, client_id)
    jobs = jobs_of(db, client_id)
    L = models.DBAssetLog
    worked_on = {}
    for l in db.query(L.asset_id, L.log_date, L.job_id).filter(L.client_id == client_id).all():
        if l.job_id:
            worked_on[(l.asset_id, l.log_date[:7])] = l.job_id
    rows = []
    for r in rentals:
        a = assets.get(r.asset_id)
        p = providers.get(r.provider_id)
        days = hours.get(r.asset_id, {})
        bills = invoices.get(r.id, [])
        base = {"rental_id": r.id, "number": r.number, "agreement_no": r.agreement_no, "asset_id": r.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
                "supplier": p.name if p else "", "billing": r.billing, "rate": r.rate or 0, "overtime_rate": r.overtime_rate or 0, "min_billable_hours": r.min_billable_hours or 0}
        seen = []
        for inv in bills:
            pf, pt = invoice_period(inv)
            c = expected_charge(r, pf, pt, days)
            diff = money((inv.amount or 0) - c["expected"])
            off = abs(diff) > abs(c["expected"]) * tolerance / 100.0 + 0.009
            twin = next((o for o in seen if pf <= o[1] and o[0] <= pt), None)
            seen.append((pf, pt, inv))
            state = "Duplicate" if twin else ("Mismatch" if off else "Matched")
            rows.append({**base, **c, "kind": "invoice", "invoice_id": inv.id, "invoice_no": inv.invoice_no, "month": pf[:7], "period_from": pf, "period_to": pt,
                         "project": job_label(jobs, worked_on.get((r.asset_id, pf[:7]))), "actual": money(inv.amount or 0), "difference": diff, "status": state,
                         "detail": ("Overlaps invoice %s." % twin[2].invoice_no) if twin else "", "verification_status": inv.verification_status or "", "verified_by": inv.verified_by or "",
                         "verification_note": inv.verification_note or "", "expected_at_review": inv.expected_at_review})
        end = r.actual_return or upto
        if (r.start_date or "") and end >= r.start_date:
            for m in _months(r.start_date, min(end, upto)):
                first, last = max(m + "-01", r.start_date), min(month_end(m + "-01"), end)
                if not first <= upto:
                    continue
                on_hire = set(_days(first, min(last, upto)))
                covered = set()
                for pf, pt, _ in seen:
                    covered |= {d for d in _days(max(pf, first), min(pt, last))} if max(pf, first) <= min(pt, last) else set()
                missing = on_hire - covered
                if not missing:
                    continue
                closed = month_end(m + "-01") < upto or bool(r.actual_return and r.actual_return <= upto)
                c = expected_charge(r, min(missing), max(missing), days)
                rows.append({**base, **c, "kind": "missing", "invoice_id": None, "invoice_no": "", "month": m, "period_from": min(missing), "period_to": max(missing),
                             "project": job_label(jobs, worked_on.get((r.asset_id, m)) or (a.current_job_id if a else None)), "actual": None, "difference": None,
                             "status": ("Incomplete" if covered else "Missing") if closed else "In progress",
                             "detail": "%d of %d days on hire have no invoice." % (len(missing), len(on_hire)), "verification_status": "", "verified_by": "", "verification_note": "", "expected_at_review": None})
    if month:
        rows = [x for x in rows if x["month"] == month]
    rows.sort(key=lambda x: (x["month"], x["number"]), reverse=True)
    return {"rows": rows, "tolerance_percent": tolerance,
            "summary": {k: len([x for x in rows if x["status"] == k]) for k in ("Matched", "Mismatch", "Duplicate", "Missing", "Incomplete")}}


# ---- alerts --------------------------------------------------------------------------------------

def raise_alert(db, client_id, kind, dedupe_key, notice, title, body, asset_id=None, rental_id=None, period="", severity="warning"):
    """Store it first, so the unique key decides whether it is a repeat; then put it on the bell and send it. The record
    says how delivery went. Returns the alert, or None if it was already raised."""
    P = models.DBPlantAlert
    if db.query(P.id).filter(P.dedupe_key == dedupe_key).first():
        return None
    alert = P(client_id=client_id, kind=kind, dedupe_key=dedupe_key, asset_id=asset_id, rental_id=rental_id, period=period, title=title[:200], body=body, severity=severity)
    db.add(alert)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    sent = notify(db, client_id, notice, title, body, view="equipment-view", ref_type="plant_alert", ref_id=alert.id, severity=severity)
    alert.office_alert_id = sent.id if sent else None
    alert.sent_to = (sent.sent_to or "") if sent else ""
    alert.delivery_status = "Delivered" if sent else "Failed"
    db.commit()
    return alert


def raise_breakdown_alert(db, client_id, a, service, severity):
    """An emergency is not kept for Monday's summary. Never allowed to stop the breakdown being recorded."""
    try:
        job = db.query(models.DBJob).filter(models.DBJob.id == a.current_job_id).first() if a.current_job_id else None
        site = ("%s %s" % (job.number or "", job.name or "")).strip() if job else "Not on a site"
        on = service.reported_on or service.service_on or today()
        body = "Machine: %s\nMachine ID: %s\nProject/site: %s\nBreakdown date: %s\nSeverity: %s\n%s" % (
            a.name, a.code, site, on, severity, (service.description or "")[:300])
        return raise_alert(db, client_id, "emergency", "emergency:%d:%d" % (client_id, service.id), "plant_breakdown", "Emergency breakdown: %s %s" % (a.code, a.name),
                           body, asset_id=a.id, period=on, severity="danger")
    except Exception as exc:
        logger.error("Breakdown alert for %s failed: %s", a.code, type(exc).__name__)
        db.rollback()
        return None


def _document_reason(label, until, day, warn_days):
    d = _parse_date(until) if until else None
    if not d:
        return None
    left = (d - day).days
    if left < 0:
        return "%s expired on %s" % (label, until)
    if left <= warn_days:
        return "%s expires on %s (%d days left)" % (label, until, left)
    return None


def machine_alert_reasons(db, client_id, a, day, warn_days, rentals, logged, moves, jobs):
    """Everything worth saying about one machine this week."""
    reasons = []
    state = asset_service_state(a, day)
    if state["due"] or state["soon"]:
        reasons.append("Service %s: %s" % (state["status"].lower(), "; ".join(state["reasons"])))
    for label, until in (("Insurance", a.insurance_until), ("Fitness certificate", a.fitness_until)):
        why = _document_reason(label, until, day, warn_days)
        if why:
            reasons.append(why)
    for r in rentals.get(a.id, ()):
        if r.actual_return or not r.expected_return:
            continue
        ret = _parse_date(r.expected_return)
        left = (ret - day).days if ret else None
        if left is not None and left < 0:
            reasons.append("Hire %s was due back on %s and has not been returned" % (r.agreement_no, r.expected_return))
        elif left is not None and left <= RETURN_ALERT_DAYS:
            reasons.append("Hire %s is due back on %s" % (r.agreement_no, r.expected_return))
    job = jobs.get(a.current_job_id)
    on_site = a.status == "Deployed" and a.current_job_id and job and (job.status or "").lower() != JOB_FINISHED
    if on_site:
        arrived = moves.get(a.id, "")
        silent = [(day - timedelta(days=n)).isoformat() for n in range(1, SITE_SILENT_DAYS + 1)]
        if all(d not in logged.get(a.id, ()) for d in silent) and (not arrived or arrived <= silent[-1]):
            reasons.append("On site at %s with no logbook entry for %d days (%s and %s)" % (job.number or job.name, SITE_SILENT_DAYS, silent[-1], silent[0]))
    return reasons


def weekly_key(now_=None):
    return (now_ or datetime.now()).strftime("%G-W%V")


def monthly_key(now_=None):
    return (now_ or datetime.now()).strftime("%Y-%m")


def run_weekly_alerts(db, client_id, day, period):
    """One summary a machine a week, whatever the number of reasons."""
    A = models.DBAsset
    assets = [a for a in db.query(A).filter(A.client_id == client_id, A.is_archived.isnot(True)).all() if a.status not in ("Disposed", "Returned")]
    if not assets:
        return 0
    warn_days = alert_settings(db, client_id)["document_alert_days"]
    rentals = {}
    for r in db.query(models.DBPlantRental).filter(models.DBPlantRental.client_id == client_id).all():
        rentals.setdefault(r.asset_id, []).append(r)
    logged = {}
    L = models.DBAssetLog
    since = (day - timedelta(days=SITE_SILENT_DAYS + 1)).isoformat()
    for aid, on, status in db.query(L.asset_id, L.log_date, L.approval_status).filter(L.client_id == client_id, L.log_date >= since).all():
        if (status or "") != "Rejected":
            logged.setdefault(aid, set()).add(on)
    moves = {}
    for m in db.query(models.DBAssetMove).filter(models.DBAssetMove.client_id == client_id).order_by(models.DBAssetMove.moved_on, models.DBAssetMove.id).all():
        moves[m.asset_id] = m.moved_on or ""
    jobs = jobs_of(db, client_id)
    raised = 0
    for a in assets:
        reasons = machine_alert_reasons(db, client_id, a, day, warn_days, rentals, logged, moves, jobs)
        if not reasons:
            continue
        body = "\n".join("- " + x for x in reasons)
        severity = "danger" if any(w in body for w in ("overdue", "expired", "not been returned")) else "warning"
        if raise_alert(db, client_id, "weekly", "weekly:%d:%d:%s" % (client_id, a.id, period), "plant_weekly", "%s %s: %d plant alert%s this week" % (
                a.code, a.name, len(reasons), "" if len(reasons) == 1 else "s"), body, asset_id=a.id, period=period, severity=severity):
            raised += 1
    return raised


def run_unbilled_alerts(db, client_id, day):
    """One alert for each machine, agreement and month with no invoice, for months that are over."""
    first_of_month = day.replace(day=1).isoformat()
    rows = rental_rows(db, client_id, upto=day.isoformat())["rows"]
    raised = 0
    for x in rows:
        if x["kind"] != "missing" or x["status"] not in ("Missing", "Incomplete") or x["month"] + "-01" >= first_of_month:
            continue
        body = "Machine: %s %s\nSupplier: %s\nProject: %s\nBilling month: %s\nAgreement: %s, %s at %s\nExpected rental: %s\n%s" % (
            x["code"], x["machine"], x["supplier"] or "-", x["project"] or "-", x["month"], x["agreement_no"], x["billing"].lower(), x["rate"], x["expected"], x["detail"])
        if raise_alert(db, client_id, "unbilled", "unbilled:%d:%d:%s" % (x["asset_id"], x["rental_id"], x["month"]), "plant_unbilled",
                       "No rental invoice: %s, %s" % (x["code"], x["month"]), body, asset_id=x["asset_id"], rental_id=x["rental_id"], period=x["month"]):
            raised += 1
    return raised


def _clients_with_machines(db):
    return [cid for (cid,) in db.query(models.DBAsset.client_id).distinct().all()]


@scheduled_job("plant_weekly_alerts", weekly_key)
def weekly_plant_alerts(db, now_):
    total = 0
    for cid in _clients_with_machines(db):
        try:
            total += run_weekly_alerts(db, cid, now_.date(), weekly_key(now_))
        except Exception:
            logger.exception("Weekly plant alerts failed for company %s", cid)
            db.rollback()
    return "%d machine alerts" % total


@scheduled_job("plant_unbilled_rentals", monthly_key)
def monthly_unbilled_rentals(db, now_):
    total = 0
    for cid in _clients_with_machines(db):
        try:
            total += run_unbilled_alerts(db, cid, now_.date())
        except Exception:
            logger.exception("Unbilled rental alerts failed for company %s", cid)
            db.rollback()
    return "%d unbilled rental alerts" % total


def alert_dict(x, assets):
    a = assets.get(x.asset_id)
    return {"id": x.id, "kind": x.kind, "period": x.period or "", "asset_id": x.asset_id, "code": a.code if a else "", "machine": a.name if a else "", "rental_id": x.rental_id,
            "title": x.title, "body": x.body or "", "severity": x.severity, "status": x.status, "delivery_status": x.delivery_status, "sent_to": x.sent_to or "",
            "reviewed_by": x.reviewed_by or "", "reviewed_at": x.reviewed_at or "", "review_note": x.review_note or "", "created_at": (x.created_at or "")[:16]}

