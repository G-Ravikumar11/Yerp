"""Equipment & Plant: the dashboard, who works each machine, the logbook, fuel, maintenance, machines hired in, the
expense register, costs and the reports. The machine register itself is /api/assets.

Who may do what - checked here, not on the screen:
  reading           anyone signed in to the company
  register, hire,   stores.manage or workorders.manage
  expenses
  allocate          stores.manage, workorders.manage or site.signoff
  logbook, fuel,    site.record (those on site)
  maintenance
  approve a day,    site.signoff
  an expense, a
  maintenance job
Every create, change, approval and removal is written to the audit trail.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, get_read_db
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.currency import money
from app.core.sheets import sheet_response
from app.schemas.plant import (
    AllocationIn, DecisionIn, EndIn, ExpenseIn, ExtendIn, FuelIn, HoursRuleIn, LogbookIn, MaintenanceDoneIn, MaintenanceIn,
    MaintenanceUpdateIn, PaymentIn, ProviderIn, ReassignIn, RentalIn, RentalInvoiceIn, ReturnIn,
)
from app.services.assets import (asset_dict, asset_or_404, asset_service_state, describe_changes, hire_cost_for,
                                 record_service_done, schedule_snapshot)
from app.services.plant import (
    BILLING, DERIVED_CATEGORIES, EXPENSE_CATEGORIES, FUEL_TYPES, IDLE_SHARE_ALERT, MAINT_KINDS, PRIORITIES, ROLES, SHIFTS,
    check_invoice_unique, clean_day, costs, employee_card, employee_or_400, in_range, machine_hours, month_bounds, now,
    number_for, regular_hours, rental_status, shift_span, today,
)

router = APIRouter()
MANAGE = ("stores.manage", "workorders.manage")
ALLOCATE = ("stores.manage", "workorders.manage", "site.signoff")
DOWN = ("Under repair", "Breakdown")


def audit(db, client, action, kind, rec_id, name, details, actor, request):
    log_audit(db, client.id, action, entity_type=kind, entity_id=rec_id, entity_name=name or "", details=(details or "")[:1000],
              request=request, user_name=actor)


def jobs_of(db, client_id):
    return {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}


def job_label(jobs, jid):
    j = jobs.get(jid)
    return ("%s %s" % (j.number or "", j.name or "")).strip() if j else ""


def usable(a, for_what="allocation"):
    if a.is_archived:
        raise HTTPException(409, "%s is archived." % a.code)
    if a.status == "Disposed":
        raise HTTPException(409, "%s has been disposed of." % a.code)
    if a.status == "Returned":
        raise HTTPException(409, "%s has gone back to its owner - it is not available for %s." % (a.code, for_what))


def people(db, client_id, ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {e.id: e for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id, models.DBEmployee.id.in_(ids)).all()}


# ---- dashboard ---------------------------------------------------------------------------------

@router.get("/api/plant/dashboard")
def dashboard(request: Request, date_from: str = "", date_to: str = "", db: Session = Depends(get_db)):
    """Every figure is worked out from the records each time it is asked for."""
    client = require_erp_read(request, db)
    f0, t0 = month_bounds()
    date_from, date_to = (date_from or f0)[:10], (date_to or t0)[:10]
    A = models.DBAsset
    shown = [a for a in db.query(A).filter(A.client_id == client.id, A.is_archived.isnot(True)).all() if a.status != "Disposed"]
    # A machine gone back to its owner is in the distribution, but no longer counted as equipment the company has.
    live = [a for a in shown if a.status != "Returned"]
    status = {}
    for a in shown:
        status[a.status or "Available"] = status.get(a.status or "Available", 0) + 1
    allocations = db.query(models.DBPlantAllocation).filter(models.DBPlantAllocation.client_id == client.id,
                                                            models.DBPlantAllocation.status == "Active").all()
    c = costs(db, client.id, date_from, date_to)
    tot = lambda k: money(sum(v[k] for v in c.values()))
    soon = (date.today() + timedelta(days=7)).isoformat()
    # One reminder per machine and cause: a schedule falling due and the preventive job already open
    # for it are the same reminder, shown once, on the job.
    by_id = {a.id: a for a in live}
    states = {a.id: asset_service_state(a) for a in live}
    open_jobs = db.query(models.DBAssetService).filter(models.DBAssetService.client_id == client.id,
                                                       models.DBAssetService.status.in_(("Requested", "Scheduled", "In progress"))).all()
    preventive_open = {s.asset_id for s in open_jobs if s.kind == "Preventive"}
    reminders = []
    for a in live:
        st = states[a.id]
        if (st["due"] or st["soon"]) and a.id not in preventive_open:
            reminders.append({"asset_id": a.id, "code": a.code, "name": a.name, "due": st["due"], "status": st["status"],
                              "what": "; ".join(st["reasons"]), "on": st["schedule"]["next_on"] or ""})
    for s in open_jobs:
        a = by_id.get(s.asset_id)
        if a:
            late = bool(s.scheduled_on) and s.scheduled_on < today()
            st = states[a.id]
            what = "%s %s - %s" % (s.number or "", s.kind.lower(), (s.description or "")[:80])
            if s.kind == "Preventive" and st["reasons"]:
                what += " (%s)" % "; ".join(st["reasons"])
            reminders.append({"asset_id": a.id, "code": a.code, "name": a.name, "due": late or s.priority == "Urgent" or (s.kind == "Preventive" and st["due"]),
                              "status": "Overdue" if late else (st["status"] if s.kind == "Preventive" else s.status),
                              "what": what, "on": s.scheduled_on or s.reported_on})
    returns = []
    for r in db.query(models.DBPlantRental).filter(models.DBPlantRental.client_id == client.id, models.DBPlantRental.actual_return == "").all():
        if r.expected_return and r.expected_return <= soon:
            a = db.query(A).filter(A.id == r.asset_id).first()
            returns.append({"rental_id": r.id, "number": r.number, "agreement_no": r.agreement_no, "code": a.code if a else "",
                            "name": a.name if a else "", "expected_return": r.expected_return, "overdue": r.expected_return < today()})
    idle = sorted(({"asset_id": v["asset_id"], "code": v["code"], "name": v["name"], "idle_hours": v["idle_hours"],
                    "operating_hours": v["operating_hours"], "idle_share": v["idle_share"]}
                   for v in c.values() if v["idle_share"] > IDLE_SHARE_ALERT and v["idle_hours"] >= 4), key=lambda x: -x["idle_share"])
    recent = [{"at": str(x.created_at or "")[:16], "who": x.user_name or "", "action": x.action, "what": x.entity_name or "", "details": x.details or ""}
              for x in db.query(models.DBAuditLog).filter(models.DBAuditLog.client_id == client.id, models.DBAuditLog.action.like("plant.%")).order_by(
                  models.DBAuditLog.id.desc()).limit(12).all()]
    expenses = {k: money(sum(v["expenses"][k] for v in c.values())) for k in EXPENSE_CATEGORIES}
    return {
        "date_from": date_from, "date_to": date_to,
        "cards": {
            "total": len(live), "owned": len([a for a in live if a.ownership == "Owned"]),
            "rented": len([a for a in live if a.ownership == "Hired"]), "leased": len([a for a in live if a.ownership == "Leased"]),
            "working": status.get("Deployed", 0), "idle": status.get("Available", 0), "maintenance": status.get("Under repair", 0),
            "breakdown": status.get("Breakdown", 0), "operators": len({x.employee_id for x in allocations}),
            "working_hours": round(sum(v["operating_hours"] for v in c.values()), 1), "fuel": tot("fuel"),
            "maintenance_cost": tot("maintenance"), "operating_cost": tot("total"),
            "upcoming": len(reminders) + len(returns),
            "service": {k: len([1 for st in states.values() if st["status"] == k]) for k in ("Due soon", "Service due", "Overdue")}},
        "status_distribution": [{"status": k, "count": v} for k, v in sorted(status.items())],
        "maintenance_reminders": sorted(reminders, key=lambda x: (not x["due"], x["on"] or "9999"))[:20],
        "rental_returns": sorted(returns, key=lambda x: x["expected_return"]),
        "excess_idle": idle[:10],
        "recent": recent,
        "cost_summary": {"fuel": tot("fuel"), "maintenance": tot("maintenance"), "rental": tot("rental"),
                         "rental_outstanding": tot("rental_outstanding"), **expenses, "labour_estimate": tot("labour_cost"),
                         "total": tot("total")},
    }


@router.get("/api/plant/costs")
def plant_costs(request: Request, date_from: str = "", date_to: str = "", asset_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    rows = sorted(costs(db, client.id, date_from[:10], date_to[:10], asset_id).values(), key=lambda r: -r["total"])
    keys = ("operating_hours", "fuel", "maintenance", "rental", "rental_outstanding", "other_expenses", "labour_hours", "labour_cost", "total")
    return {"machines": rows, "totals": {k: round(sum(r[k] for r in rows), 2) for k in keys}}


# ---- people and allocations ---------------------------------------------------------------------

@router.get("/api/plant/employees")
def plant_employees(request: Request, db: Session = Depends(get_read_db)):
    """The company's employees as the plant screens need them - code, name, mobile, designation, status - and what each is on."""
    client = require_erp_read(request, db)
    on = {}
    for al in db.query(models.DBPlantAllocation).filter(models.DBPlantAllocation.client_id == client.id, models.DBPlantAllocation.status == "Active").all():
        on.setdefault(al.employee_id, []).append(al.asset_id)
    assets = {a.id: a.code for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    rows = []
    for e in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id, models.DBEmployee.status != "terminated").order_by(
            models.DBEmployee.first_name).all():
        card = employee_card(e)
        card["on_machines"] = [assets.get(x, "") for x in on.get(e.id, [])]
        rows.append(card)
    return {"employees": rows, "roles": list(ROLES), "shifts": list(SHIFTS)}


def allocation_dict(al, assets, staff, jobs):
    a = assets.get(al.asset_id)
    return {"id": al.id, "asset_id": al.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
            "availability": a.status if a else "", "employee": employee_card(staff.get(al.employee_id)),
            "job_id": al.job_id, "project": job_label(jobs, al.job_id), "role": al.role, "shift": al.shift,
            "allocated_on": al.allocated_on, "start_date": al.start_date, "end_date": al.end_date or "",
            "supervisor": employee_card(staff.get(al.supervisor_id)), "status": al.status, "notes": al.notes or "",
            "ended_reason": al.ended_reason or "", "created_by": al.created_by or ""}


@router.get("/api/plant/allocations")
def list_allocations(request: Request, asset_id: int = 0, employee_id: int = 0, status: str = "", db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    P = models.DBPlantAllocation
    q = db.query(P).filter(P.client_id == client.id)
    if asset_id:
        q = q.filter(P.asset_id == asset_id)
    if employee_id:
        q = q.filter(P.employee_id == employee_id)
    if status:
        q = q.filter(P.status == status)
    rows = q.order_by(P.status, P.id.desc()).limit(1000).all()
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    staff = people(db, client.id, [r.employee_id for r in rows] + [r.supervisor_id for r in rows])
    jobs = jobs_of(db, client.id)
    return {"allocations": [allocation_dict(r, assets, staff, jobs) for r in rows]}


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start <= (b_end or "9999-12-31") and b_start <= (a_end or "9999-12-31")


def _check_allocation(db, client_id, asset, emp_id, role, shift, start, end, skip_id=None):
    P = models.DBPlantAllocation
    others = db.query(P).filter(P.client_id == client_id, P.status == "Active")
    if skip_id:
        others = others.filter(P.id != skip_id)
    for o in others.all():
        if not _overlaps(start, end, o.start_date, o.end_date):
            continue
        if o.employee_id == emp_id and o.shift == shift:
            m = db.query(models.DBAsset).filter(models.DBAsset.id == o.asset_id).first()
            raise HTTPException(409, "That person is already on %s in the %s shift for those dates." % (m.code if m else "another machine", shift.lower()))
        # A machine has one operator (or driver) a shift; others may work it alongside, and other shifts have their own.
        if o.asset_id == asset.id and o.shift == shift and role in ("Operator", "Driver") and o.role == role:
            raise HTTPException(409, "%s already has an %s in the %s shift for those dates - choose another shift, or reassign it." % (
                asset.code, role.lower(), shift.lower()))


@router.post("/api/plant/allocations")
def create_allocation(body: AllocationIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, ALLOCATE)
    a = asset_or_404(db, client.id, body.asset_id)
    usable(a)
    if a.status in DOWN:
        raise HTTPException(409, "%s is %s - it cannot be worked until it is back in service." % (a.code, a.status.lower()))
    e = employee_or_400(db, client.id, body.employee_id)
    if (e.status or "") in ("terminated", "inactive"):
        raise HTTPException(409, "%s is not working for the company." % employee_card(e)["name"])
    if body.role not in ROLES:
        raise HTTPException(400, "The role is one of: %s." % ", ".join(ROLES))
    if body.shift not in SHIFTS:
        raise HTTPException(400, "The shift is one of: %s." % ", ".join(SHIFTS))
    start = clean_day(body.start_date, "start date") or today()
    end = clean_day(body.end_date, "end date")
    if end and end < start:
        raise HTTPException(400, "It cannot end before it starts.")
    if body.supervisor_id:
        employee_or_400(db, client.id, body.supervisor_id, "supervisor")
    _check_allocation(db, client.id, a, e.id, body.role, body.shift, start, end)
    al = models.DBPlantAllocation(client_id=client.id, asset_id=a.id, employee_id=e.id, job_id=a.current_job_id, role=body.role,
                                  shift=body.shift, allocated_on=today(), start_date=start, end_date=end, supervisor_id=body.supervisor_id or None,
                                  status="Active", notes=(body.notes or "").strip(), created_by=actor)
    db.add(al)
    db.flush()
    audit(db, client, "plant.allocation.created", "plant_allocation", al.id, a.code, "%s as %s, %s shift, from %s" % (employee_card(e)["name"], body.role, body.shift, start), actor, request)
    db.commit()
    return {"ok": True, "message": "%s is on %s as %s." % (employee_card(e)["name"], a.code, body.role.lower())}


def _allocation_or_404(db, client_id, aid):
    al = db.query(models.DBPlantAllocation).filter(models.DBPlantAllocation.id == aid, models.DBPlantAllocation.client_id == client_id).first()
    if not al:
        raise HTTPException(404, "Allocation not found")
    return al


@router.post("/api/plant/allocations/{aid}/end")
def end_allocation(aid: int, body: EndIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, ALLOCATE)
    al = _allocation_or_404(db, client.id, aid)
    if al.status != "Active":
        raise HTTPException(409, "That allocation has already ended.")
    on = clean_day(body.on, "end date") or today()
    if on < al.start_date:
        raise HTTPException(400, "It cannot end before it started (%s)." % al.start_date)
    al.status, al.end_date, al.ended_reason = "Ended", on, (body.reason or "").strip()[:200]
    audit(db, client, "plant.allocation.ended", "plant_allocation", al.id, "", "Ended %s. %s" % (on, al.ended_reason), actor, request)
    db.commit()
    return {"ok": True, "message": "Allocation ended."}


@router.post("/api/plant/allocations/{aid}/reassign")
def reassign_allocation(aid: int, body: ReassignIn, request: Request, db: Session = Depends(get_db)):
    """The machine, shift and role go to someone else from a date; the first allocation ends the day before - both kept."""
    client, _, actor = wo_actor(request, db, ALLOCATE)
    al = _allocation_or_404(db, client.id, aid)
    if al.status != "Active":
        raise HTTPException(409, "That allocation has already ended.")
    e = employee_or_400(db, client.id, body.employee_id)
    if e.id == al.employee_id:
        raise HTTPException(400, "That is the person already on it.")
    on = clean_day(body.on, "date") or today()
    if on < al.start_date:
        raise HTTPException(400, "The new person cannot start before the allocation did.")
    a = asset_or_404(db, client.id, al.asset_id)
    _check_allocation(db, client.id, a, e.id, al.role, al.shift, on, al.end_date, skip_id=al.id)
    prev_end = (datetime.strptime(on, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
    old_end = al.end_date or ""
    al.status, al.end_date, al.ended_reason = "Ended", max(prev_end, al.start_date), ("Reassigned. " + (body.reason or "")).strip()[:200]
    new = models.DBPlantAllocation(client_id=client.id, asset_id=al.asset_id, employee_id=e.id, job_id=al.job_id, role=al.role, shift=al.shift,
                                   allocated_on=today(), start_date=on, end_date=al.end_date if al.end_date > on else "", supervisor_id=al.supervisor_id,
                                   status="Active", notes=al.notes, created_by=actor)
    new.end_date = old_end if old_end >= on else ""
    db.add(new)
    db.flush()
    audit(db, client, "plant.allocation.reassigned", "plant_allocation", new.id, a.code, "To %s from %s" % (employee_card(e)["name"], on), actor, request)
    db.commit()
    return {"ok": True, "message": "%s now on %s." % (employee_card(e)["name"], a.code)}


# ---- logbook -------------------------------------------------------------------------------------

def log_dict(l, assets, staff, jobs):
    a = assets.get(l.asset_id)
    return {"id": l.id, "log_date": l.log_date, "asset_id": l.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
            "employee": employee_card(staff.get(l.employee_id)) or ({"name": l.operator, "mobile": ""} if l.operator else None),
            "project": job_label(jobs, l.job_id), "shift": l.shift or "", "start_time": l.start_time or "", "end_time": l.end_time or "",
            "break_minutes": l.break_minutes or 0, "opening_meter": l.opening_meter, "closing_meter": l.closing_meter,
            "operating_hours": l.hours_worked or 0, "idle_hours": l.idle_hours or 0, "breakdown_hours": l.breakdown_hours or 0,
            "attendance_hours": l.attendance_hours or 0, "regular_hours": l.regular_hours or 0, "overtime_hours": l.overtime_hours or 0,
            "work_done": l.work_done or "", "fuel_litres": l.fuel_litres or 0, "supervisor_remarks": l.supervisor_remarks or "",
            "approval_status": l.approval_status or "Recorded", "approved_by": l.approved_by or "", "recorded_by": l.recorded_by_name or ""}


@router.get("/api/plant/logs")
def list_logs(request: Request, date_from: str = "", date_to: str = "", asset_id: int = 0, employee_id: int = 0, status: str = "",
              db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    L = models.DBAssetLog
    q = db.query(L).filter(L.client_id == client.id)
    if date_from:
        q = q.filter(L.log_date >= date_from[:10])
    if date_to:
        q = q.filter(L.log_date <= date_to[:10])
    if asset_id:
        q = q.filter(L.asset_id == asset_id)
    if employee_id:
        q = q.filter(L.employee_id == employee_id)
    if status:
        q = q.filter(L.approval_status == status)
    rows = q.order_by(L.log_date.desc(), L.id.desc()).limit(1000).all()
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    staff = people(db, client.id, [r.employee_id for r in rows])
    jobs = jobs_of(db, client.id)
    return {"logs": [log_dict(r, assets, staff, jobs) for r in rows], "regular_hours": regular_hours(db, client.id)}


def _work_out(db, client_id, a, body, skip_id=None):
    """Every figure on a logbook line, from what was entered, checked."""
    on = clean_day(body.log_date, "work date") or today()
    if on > today():
        raise HTTPException(400, "A day cannot be logged before it has happened.")
    if body.shift not in SHIFTS:
        raise HTTPException(400, "The shift is one of: %s." % ", ".join(SHIFTS))
    s, e = shift_span(body.start_time, body.end_time)
    brk = int(body.break_minutes or 0)
    if brk < 0 or brk >= e - s:
        raise HTTPException(400, "The break is longer than the shift.")
    duty = round((e - s - brk) / 60.0, 2)
    if duty > 20:
        raise HTTPException(400, "%g hours on duty in one shift is more than a day's work - check the times." % duty)
    if body.opening_meter is not None and body.closing_meter is not None:
        if body.closing_meter < body.opening_meter:
            raise HTTPException(400, "The closing meter reading (%g) is below the opening one (%g)." % (body.closing_meter, body.opening_meter))
        if body.opening_meter < 0:
            raise HTTPException(400, "A meter reading cannot be negative.")
        operating = round(body.closing_meter - body.opening_meter, 2) if (a.meter_unit or "Hours") == "Hours" else float(body.operating_hours or 0)
    elif body.opening_meter is not None or body.closing_meter is not None:
        raise HTTPException(400, "Give both meter readings, opening and closing - or neither.")
    else:
        operating = float(body.operating_hours or 0)
    span_h = (e - s) / 60.0
    if operating < 0 or operating > span_h + 0.01:
        raise HTTPException(400, "The machine ran %g hours, longer than the %g-hour shift." % (operating, round(span_h, 2)))
    breakdown = float(body.breakdown_hours or 0)
    if breakdown < 0 or operating + breakdown > span_h + 0.01:
        raise HTTPException(400, "Running and breakdown hours add up to more than the shift.")
    if operating > 0 and a.status in DOWN:
        raise HTTPException(409, "%s is %s - log the breakdown hours, not running hours, until it is back in service." % (a.code, a.status.lower()))
    idle = float(body.idle_hours) if body.idle_hours is not None else max(0.0, round(duty - operating - breakdown, 2))
    if idle < 0 or operating + idle + breakdown > span_h + 0.01:
        raise HTTPException(400, "Running, idle and breakdown hours add up to more than the shift.")
    rule = regular_hours(db, client_id)
    reg, ot = min(duty, rule), max(0.0, round(duty - rule, 2))
    # One person, one shift a day, and no two shifts of theirs that overlap.
    L = models.DBAssetLog
    q = db.query(L).filter(L.client_id == client_id, L.employee_id == body.employee_id, L.log_date.in_([
        on, (datetime.strptime(on, "%Y-%m-%d").date() - timedelta(days=1)).isoformat(),
        (datetime.strptime(on, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()]), L.approval_status != "Rejected")
    if skip_id:
        q = q.filter(L.id != skip_id)
    day0 = datetime.strptime(on, "%Y-%m-%d").date()
    for o in q.all():
        if not o.start_time or not o.end_time:
            continue
        if o.log_date == on and (o.shift or "") == body.shift:
            raise HTTPException(409, "That person already has a %s-shift log for %s." % (body.shift.lower(), on))
        os_, oe = shift_span(o.start_time, o.end_time)
        off = (datetime.strptime(o.log_date, "%Y-%m-%d").date() - day0).days * 1440
        if s < oe + off and os_ + off < e:
            raise HTTPException(409, "That overlaps their %s-shift log of %s (%s-%s)." % ((o.shift or "").lower(), o.log_date, o.start_time, o.end_time))
    return {"log_date": on, "shift": body.shift, "start_time": body.start_time.strip(), "end_time": body.end_time.strip(), "break_minutes": brk,
            "opening_meter": body.opening_meter, "closing_meter": body.closing_meter, "hours_worked": operating, "idle_hours": idle,
            "breakdown_hours": breakdown, "attendance_hours": duty, "regular_hours": reg, "overtime_hours": ot,
            "work_done": (body.work_done or "").strip()[:300], "fuel_litres": max(0.0, float(body.fuel_litres or 0)),
            "supervisor_remarks": (body.supervisor_remarks or "").strip()[:300]}


@router.post("/api/plant/logs")
def create_log(body: LogbookIn, request: Request, db: Session = Depends(get_db)):
    """One person's shift on one machine. The employee's hours on duty and the machine's running hours are kept apart:
    a machine stands idle while its operator is still at work."""
    client, _, actor = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, body.asset_id)
    usable(a, "logging")
    e = employee_or_400(db, client.id, body.employee_id)
    v = _work_out(db, client.id, a, body)
    L = models.DBAssetLog
    twin = db.query(L).filter(L.asset_id == a.id, L.log_date == v["log_date"], L.shift == v["shift"], L.approval_status != "Rejected").first()
    log = L(client_id=client.id, asset_id=a.id, job_id=a.current_job_id, employee_id=e.id, operator=employee_card(e)["name"],
            recorded_by_name=actor, approval_status="Submitted", fuel_rate=0, fuel_cost=0, **v)
    # Hire is charged once a machine-day-shift, whoever else logged it.
    log.hire_cost = 0.0 if twin else hire_cost_for(a, v["hours_worked"])
    if v["closing_meter"] is not None and v["closing_meter"] > (a.meter_reading or 0):
        a.meter_reading = v["closing_meter"]
    elif v["closing_meter"] is None and (a.meter_unit or "Hours") == "Hours" and v["hours_worked"] and not twin:
        a.meter_reading = (a.meter_reading or 0) + v["hours_worked"]
    db.add(log)
    db.flush()
    audit(db, client, "plant.log.created", "plant_log", log.id, a.code, "%s %s shift %s-%s: %g h on duty, machine %g h" % (
        employee_card(e)["name"], v["shift"], v["start_time"], v["end_time"], v["attendance_hours"], v["hours_worked"]), actor, request)
    db.commit()
    return {"ok": True, "id": log.id, "message": "Logged: %g h on duty (%g overtime), machine ran %g h." % (v["attendance_hours"], v["overtime_hours"], v["hours_worked"])}


@router.put("/api/plant/logs/{lid}")
def correct_log(lid: int, body: LogbookIn, request: Request, db: Session = Depends(get_db)):
    """A correction, with the reason and what changed in the trail. An approved day is changed only by whoever approves."""
    client, _, actor = wo_actor(request, db, "site.record")
    L = models.DBAssetLog
    log = db.query(L).filter(L.id == lid, L.client_id == client.id).first()
    if not log:
        raise HTTPException(404, "Log not found")
    if log.approval_status == "Approved":
        wo_actor(request, db, "site.signoff")
    if not (body.correction_reason or "").strip():
        raise HTTPException(400, "Say why it is being corrected - it goes on the record.")
    a = asset_or_404(db, client.id, log.asset_id)
    employee_or_400(db, client.id, body.employee_id)
    v = _work_out(db, client.id, a, body, skip_id=log.id)
    before = "%s %s-%s machine %g h duty %g h" % (log.log_date, log.start_time, log.end_time, log.hours_worked or 0, log.attendance_hours or 0)
    for k, val in v.items():
        setattr(log, k, val)
    log.employee_id = body.employee_id
    log.approval_status, log.approved_by, log.approved_on = "Submitted", "", ""
    audit(db, client, "plant.log.corrected", "plant_log", log.id, a.code, "Was: %s. Now: %s %s-%s machine %g h duty %g h. Why: %s" % (
        before, v["log_date"], v["start_time"], v["end_time"], v["hours_worked"], v["attendance_hours"], body.correction_reason.strip()), actor, request)
    db.commit()
    return {"ok": True, "message": "Corrected - it goes back for approval."}


@router.post("/api/plant/logs/{lid}/decision")
def decide_log(lid: int, body: DecisionIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    log = db.query(models.DBAssetLog).filter(models.DBAssetLog.id == lid, models.DBAssetLog.client_id == client.id).first()
    if not log:
        raise HTTPException(404, "Log not found")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "Approve or reject.")
    if body.decision == "reject" and not (body.remarks or "").strip():
        raise HTTPException(400, "Say what is wrong with it.")
    log.approval_status = "Approved" if body.decision == "approve" else "Rejected"
    log.approved_by, log.approved_on = actor, today()
    if (body.remarks or "").strip():
        log.supervisor_remarks = body.remarks.strip()[:300]
    audit(db, client, "plant.log." + log.approval_status.lower(), "plant_log", log.id, "", body.remarks or "", actor, request)
    db.commit()
    return {"ok": True, "message": "Day %s." % log.approval_status.lower()}


@router.get("/api/plant/settings")
def plant_settings(request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return {"regular_hours": regular_hours(db, client.id)}


@router.put("/api/plant/settings")
def save_plant_settings(body: HoursRuleIn, request: Request, db: Session = Depends(get_db)):
    """How many hours of a shift are regular; the rest is overtime."""
    client, _, actor = wo_actor(request, db, MANAGE)
    if not 1 <= body.regular_hours <= 16:
        raise HTTPException(400, "Regular hours a day between 1 and 16.")
    S = models.DBSettings
    row = db.query(S).filter(S.client_id == client.id, S.key == "plant_regular_hours").first()
    if not row:
        row = S(client_id=client.id, key="plant_regular_hours", description="Equipment logbook: regular hours a shift")
        db.add(row)
    row.value = str(body.regular_hours)
    log_audit(db, client.id, "plant.settings.hours", entity_type="plant_settings", details="Regular hours %g" % body.regular_hours, request=request, user_name=actor)
    db.commit()
    return {"ok": True, "regular_hours": body.regular_hours, "message": "Overtime now counts after %g hours." % body.regular_hours}


# ---- fuel ----------------------------------------------------------------------------------------

def fuel_dict(f, assets, jobs):
    a = assets.get(f.asset_id)
    return {"id": f.id, "number": f.number, "asset_id": f.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
            "project": job_label(jobs, f.job_id), "filled_at": f.filled_at, "fuel_type": f.fuel_type, "litres": f.litres, "rate": f.rate,
            "amount": f.amount, "supplier": f.supplier or "", "voucher_no": f.voucher_no or "", "meter_reading": f.meter_reading,
            "notes": f.notes or "", "recorded_by": f.recorded_by or ""}


@router.get("/api/plant/fuel")
def list_fuel(request: Request, date_from: str = "", date_to: str = "", asset_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    F = models.DBPlantFuel
    q = db.query(F).filter(F.client_id == client.id)
    if asset_id:
        q = q.filter(F.asset_id == asset_id)
    rows = [f for f in q.order_by(F.filled_at.desc()).limit(2000).all() if in_range(f.filled_at, date_from[:10], date_to[:10])]
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    c = costs(db, client.id, date_from[:10], date_to[:10], asset_id)
    by_machine = [{"asset_id": k, "code": v["code"], "name": v["name"], "litres": v["fuel_litres"], "amount": v["fuel"],
                   "operating_hours": v["operating_hours"], "litres_per_hour": v["litres_per_hour"], "cost_per_hour": v["fuel_per_hour"]}
                  for k, v in c.items() if v["fuel"] or v["fuel_litres"]]
    by_day = {}
    for f in rows:
        d = by_day.setdefault(f.filled_at[:10], {"day": f.filled_at[:10], "litres": 0.0, "amount": 0.0})
        d["litres"] += f.litres or 0
        d["amount"] += f.amount or 0
    return {"fuel": [fuel_dict(f, assets, jobs_of(db, client.id)) for f in rows], "fuel_types": list(FUEL_TYPES),
            "by_machine": sorted(by_machine, key=lambda x: -x["amount"]), "by_day": sorted(by_day.values(), key=lambda x: x["day"], reverse=True),
            "totals": {"litres": round(sum(f.litres or 0 for f in rows), 2), "amount": money(sum(f.amount or 0 for f in rows))}}


@router.post("/api/plant/fuel")
def create_fuel(body: FuelIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, ("site.record", "stores.manage"))
    a = asset_or_404(db, client.id, body.asset_id)
    usable(a, "fuelling")
    day = clean_day(body.filled_on, "date") or today()
    if day > today():
        raise HTTPException(400, "Fuel cannot be recorded before it is put in.")
    tm = (body.filled_time or "").strip() or "00:00"
    if not (len(tm) == 5 and tm[2] == ":" and tm[:2].isdigit() and tm[3:].isdigit() and int(tm[:2]) < 24 and int(tm[3:]) < 60):
        raise HTTPException(400, "The time as 07:30.")
    if body.fuel_type not in FUEL_TYPES:
        raise HTTPException(400, "The fuel type is one of: %s." % ", ".join(FUEL_TYPES))
    if not 0 < body.litres <= 5000:
        raise HTTPException(400, "The quantity in litres, more than 0 and at most 5,000 at a time.")
    if not 0 < body.rate <= 1000:
        raise HTTPException(400, "The price a litre.")
    amount = money(body.litres * body.rate)
    if body.amount is not None and abs(body.amount - amount) > 1:
        raise HTTPException(400, "%g litres at %g is %s, not %s." % (body.litres, body.rate, amount, body.amount))
    if body.meter_reading is not None and body.meter_reading < 0:
        raise HTTPException(400, "A meter reading cannot be negative.")
    voucher = check_invoice_unique(db, client.id, body.voucher_no)
    F = models.DBPlantFuel
    f = F(client_id=client.id, number=number_for(db, F, client.id, "FUEL"), asset_id=a.id, job_id=a.current_job_id, filled_at="%s %s" % (day, tm),
          fuel_type=body.fuel_type, litres=round(body.litres, 2), rate=body.rate, amount=amount, supplier=(body.supplier or "").strip()[:120],
          voucher_no=voucher, meter_reading=body.meter_reading, notes=(body.notes or "").strip(), recorded_by=actor)
    if body.meter_reading is not None and body.meter_reading > (a.meter_reading or 0):
        a.meter_reading = body.meter_reading
    db.add(f)
    db.flush()
    audit(db, client, "plant.fuel.recorded", "plant_fuel", f.id, f.number, "%s: %g L %s at %g = %s" % (a.code, f.litres, f.fuel_type, f.rate, f.amount), actor, request)
    db.commit()
    return {"ok": True, "fuel": fuel_dict(f, {a.id: a}, {}), "message": "%s: %g L for %s." % (f.number, f.litres, a.code)}


@router.delete("/api/plant/fuel/{fid}")
def delete_fuel(fid: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    f = db.query(models.DBPlantFuel).filter(models.DBPlantFuel.id == fid, models.DBPlantFuel.client_id == client.id).first()
    if not f:
        raise HTTPException(404, "Fuel entry not found")
    audit(db, client, "plant.fuel.removed", "plant_fuel", f.id, f.number, "%g L, %s" % (f.litres, f.amount), actor, request)
    db.delete(f)
    db.commit()
    return {"ok": True, "message": "%s removed." % f.number}


# ---- maintenance -----------------------------------------------------------------------------------

def maint_dict(s, assets):
    a = assets.get(s.asset_id)
    hours = 0.0
    if s.downtime_start and s.downtime_end:
        try:
            hours = round((datetime.fromisoformat(s.downtime_end) - datetime.fromisoformat(s.downtime_start)).total_seconds() / 3600, 1)
        except ValueError:
            hours = 0.0
    return {"id": s.id, "number": s.number or ("SVC-%d" % s.id), "asset_id": s.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
            "availability": a.status if a else "", "kind": s.kind, "priority": s.priority or "Normal", "status": s.status or "Completed",
            "reported_on": s.reported_on or s.service_on, "scheduled_on": s.scheduled_on or "", "completed_on": s.completed_on or (s.service_on if (s.status or "Completed") == "Completed" else ""),
            "description": s.description or "", "mechanic": s.mechanic or s.vendor or "", "parts_used": s.parts_used or "",
            "parts_cost": s.parts_cost or 0, "labour_cost": s.labour_cost or 0, "total_cost": s.total_cost or 0,
            "downtime_start": s.downtime_start or "", "downtime_end": s.downtime_end or "", "downtime_hours": s.downtime_hours or hours,
            "work_performed": s.work_performed or "", "invoice_no": s.invoice_no or "", "next_service_on": s.next_service_on or "",
            "next_service_meter": s.next_service_meter, "approval_status": s.approval_status or "", "approved_by": s.approved_by or "",
            "overdue": (s.status in ("Requested", "Scheduled")) and bool(s.scheduled_on) and s.scheduled_on < today()}


@router.get("/api/plant/maintenance")
def list_maintenance(request: Request, asset_id: int = 0, status: str = "", date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    S = models.DBAssetService
    q = db.query(S).filter(S.client_id == client.id)
    if asset_id:
        q = q.filter(S.asset_id == asset_id)
    if status == "open":
        q = q.filter(S.status.in_(("Requested", "Scheduled", "In progress")))
    elif status:
        q = q.filter(S.status == status)
    rows = [s for s in q.order_by(S.id.desc()).limit(2000).all() if in_range(s.reported_on or s.service_on, date_from[:10], date_to[:10])]
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    return {"maintenance": [maint_dict(s, assets) for s in rows], "kinds": list(MAINT_KINDS), "priorities": list(PRIORITIES)}


def _settle_status(db, a):
    """A machine is down while any job on it keeps it down; when the last is done it goes back to where it was."""
    open_ = db.query(models.DBAssetService).filter(models.DBAssetService.asset_id == a.id,
                                                   models.DBAssetService.status.in_(("Requested", "Scheduled", "In progress"))).all()
    if any(s.status == "In progress" for s in open_):
        a.status = "Under repair"
    elif any((s.kind in ("Corrective", "Emergency", "Breakdown")) and s.downtime_start and not s.downtime_end for s in open_):
        a.status = "Breakdown"
    elif a.status in DOWN:
        a.status = "Deployed" if a.current_job_id else "Available"


@router.post("/api/plant/maintenance")
def raise_maintenance(body: MaintenanceIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, body.asset_id)
    usable(a, "maintenance")
    if body.kind not in MAINT_KINDS:
        raise HTTPException(400, "Preventive, corrective or emergency.")
    if not (body.description or "").strip():
        raise HTTPException(400, "Describe the problem or the work to be done.")
    pr = body.priority or "Normal"
    if pr not in PRIORITIES:
        raise HTTPException(400, "Priority is one of: %s." % ", ".join(PRIORITIES))
    reported = clean_day(body.reported_on, "reported date") or today()
    scheduled = clean_day(body.scheduled_on, "scheduled date")
    if scheduled and scheduled < reported:
        raise HTTPException(400, "It cannot be scheduled before it was reported.")
    if body.next_service_meter is not None and body.next_service_meter < (a.meter_reading or 0):
        raise HTTPException(400, "The meter already reads %g." % (a.meter_reading or 0))
    S = models.DBAssetService
    if body.kind == "Preventive":
        dup = db.query(S).filter(S.asset_id == a.id, S.kind == "Preventive", S.status.in_(("Requested", "Scheduled", "In progress"))).first()
        if dup:
            raise HTTPException(409, "%s already has a preventive service open (%s). Complete or update that one." % (a.code, dup.number))
    s = S(client_id=client.id, asset_id=a.id, job_id=a.current_job_id, number=number_for(db, S, client.id, "MNT"), kind=body.kind, priority=pr,
          status="Scheduled" if scheduled else "Requested", reported_on=reported, service_on=reported, scheduled_on=scheduled,
          description=body.description.strip(), mechanic=(body.mechanic or "").strip()[:120], vendor=(body.mechanic or "").strip()[:120],
          next_service_meter=body.next_service_meter, total_cost=0, parts_cost=0, labour_cost=0, recorded_by_name=actor)
    if body.out_of_service and body.kind in ("Corrective", "Emergency"):
        s.downtime_start = "%s %s" % (reported, datetime.now().strftime("%H:%M"))
    db.add(s)
    db.flush()
    _settle_status(db, a)
    audit(db, client, "plant.maintenance.raised", "plant_maintenance", s.id, s.number, "%s %s: %s" % (a.code, body.kind, s.description[:200]), actor, request)
    db.commit()
    return {"ok": True, "id": s.id, "message": "%s raised for %s%s." % (s.number, a.code, " - off work" if a.status in DOWN else "")}


def _maint_or_404(db, client_id, mid):
    s = db.query(models.DBAssetService).filter(models.DBAssetService.id == mid, models.DBAssetService.client_id == client_id).first()
    if not s:
        raise HTTPException(404, "Maintenance job not found")
    return s


@router.put("/api/plant/maintenance/{mid}")
def update_maintenance(mid: int, body: MaintenanceUpdateIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.record")
    s = _maint_or_404(db, client.id, mid)
    if (s.status or "Completed") == "Completed":
        raise HTTPException(409, "%s is completed." % (s.number or "That job"))
    a = asset_or_404(db, client.id, s.asset_id)
    if body.status is not None:
        if body.status not in ("Requested", "Scheduled", "In progress"):
            raise HTTPException(400, "Requested, scheduled or in progress - completing it has its own step.")
        s.status = body.status
        if body.status == "In progress" and not s.downtime_start:
            s.downtime_start = now()[:16]
    if body.scheduled_on is not None:
        s.scheduled_on = clean_day(body.scheduled_on, "scheduled date")
    if body.priority is not None:
        if body.priority not in PRIORITIES:
            raise HTTPException(400, "Priority is one of: %s." % ", ".join(PRIORITIES))
        s.priority = body.priority
    for f in ("mechanic", "parts_used", "work_performed"):
        val = getattr(body, f)
        if val is not None:
            setattr(s, f, val.strip())
    if body.downtime_start is not None:
        s.downtime_start = body.downtime_start.strip()[:16]
    if body.invoice_no is not None:
        s.invoice_no = check_invoice_unique(db, client.id, body.invoice_no, ("maintenance", s.id))
    for f in ("parts_cost", "labour_cost"):
        val = getattr(body, f)
        if val is not None:
            if val < 0:
                raise HTTPException(400, "A cost cannot be negative.")
            setattr(s, f, money(val))
    s.total_cost = money((s.parts_cost or 0) + (s.labour_cost or 0))
    _settle_status(db, a)
    audit(db, client, "plant.maintenance.updated", "plant_maintenance", s.id, s.number, "Status %s" % s.status, actor, request)
    db.commit()
    return {"ok": True, "message": "%s updated - %s is %s." % (s.number, a.code, a.status.lower())}


@router.post("/api/plant/maintenance/{mid}/complete")
def complete_maintenance(mid: int, body: MaintenanceDoneIn, request: Request, db: Session = Depends(get_db)):
    """Done: what was done, what it cost, how long the machine was down, and when it is next due."""
    client, _, actor = wo_actor(request, db, "site.record")
    s = _maint_or_404(db, client.id, mid)
    if (s.status or "Completed") == "Completed":
        raise HTTPException(409, "%s is already completed." % (s.number or "That job"))
    a = asset_or_404(db, client.id, s.asset_id)
    done = clean_day(body.completed_on, "completion date") or today()
    if done < (s.reported_on or done):
        raise HTTPException(400, "It cannot be completed before it was reported.")
    if not (body.work_performed or "").strip():
        raise HTTPException(400, "Say what was done.")
    for v in (body.parts_cost, body.labour_cost):
        if (v or 0) < 0:
            raise HTTPException(400, "A cost cannot be negative.")
    start, end = (body.downtime_start or s.downtime_start or "").strip()[:16], (body.downtime_end or "").strip()[:16]
    if start and end:
        try:
            if datetime.fromisoformat(end) < datetime.fromisoformat(start):
                raise HTTPException(400, "Downtime cannot end before it started.")
            s.downtime_hours = round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600, 1)
        except ValueError:
            raise HTTPException(400, "Downtime as date and time: 2026-10-13 08:30.")
    nxt = clean_day(body.next_service_on, "next service date")
    if nxt and nxt <= done:
        raise HTTPException(400, "The next service is after this one.")
    meter = body.meter_at_service if body.meter_at_service is not None else a.meter_reading
    if body.next_service_meter is not None and body.next_service_meter <= (meter or 0):
        raise HTTPException(400, "The next service reading is above the meter now (%g)." % (meter or 0))
    s.invoice_no = check_invoice_unique(db, client.id, body.invoice_no, ("maintenance", s.id))
    before = schedule_snapshot(a)
    if s.kind == "Preventive":
        # A preventive job is the scheduled service: the clock starts again from it, the interval unchanged.
        nxt_meter, nxt = record_service_done(a, done, meter, body.next_service_meter, nxt)
    else:
        nxt_meter = body.next_service_meter
        if meter is not None and meter > (a.meter_reading or 0):
            a.meter_reading = meter
        # A repair leaves the schedule where it was, unless it says when the next service is due.
        if nxt_meter is not None:
            a.next_service_meter = float(nxt_meter)
        if nxt:
            a.next_service_on = nxt
    s.status, s.completed_on, s.service_on = "Completed", done, done
    s.work_performed = body.work_performed.strip()
    s.parts_used = (body.parts_used or s.parts_used or "").strip()
    s.parts_cost, s.labour_cost = money(body.parts_cost or 0), money(body.labour_cost or 0)
    s.total_cost = money(s.parts_cost + s.labour_cost)
    s.downtime_start, s.downtime_end = start, end
    s.meter_at_service = meter
    s.next_service_on, s.next_service_meter = nxt or "", nxt_meter
    after = schedule_snapshot(a)
    changed = {k: (before[k], after[k]) for k in after if before[k] != after[k]}
    if changed:
        audit(db, client, "plant.service.completed" if s.kind == "Preventive" else "plant.schedule.changed", "equipment", a.id, a.code,
              "%s: %s" % (s.number, describe_changes(changed)), actor, request)
    db.flush()
    _settle_status(db, a)
    audit(db, client, "plant.maintenance.completed", "plant_maintenance", s.id, s.number, "%s: %s, cost %s, down %g h" % (a.code, s.work_performed[:150], s.total_cost, s.downtime_hours or 0), actor, request)
    db.commit()
    return {"ok": True, "message": "%s completed - %s is %s." % (s.number, a.code, a.status.lower())}


@router.post("/api/plant/maintenance/{mid}/approve")
def approve_maintenance(mid: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    s = _maint_or_404(db, client.id, mid)
    if (s.status or "Completed") != "Completed":
        raise HTTPException(409, "Approve it once it is completed.")
    if s.approval_status == "Approved":
        raise HTTPException(409, "Already approved.")
    s.approval_status, s.approved_by = "Approved", actor
    audit(db, client, "plant.maintenance.approved", "plant_maintenance", s.id, s.number, "", actor, request)
    db.commit()
    return {"ok": True, "message": "%s approved." % (s.number or "Job")}


# ---- rentals ---------------------------------------------------------------------------------------

def provider_dict(p):
    return {"id": p.id, "name": p.name, "contact_person": p.contact_person or "", "mobile": p.mobile or "", "email": p.email or "",
            "address": p.address or "", "supplier_id": p.supplier_id}


@router.get("/api/plant/rental-providers")
def list_providers(request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    rows = db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.client_id == client.id).order_by(models.DBPlantRentalProvider.name).all()
    sup = [{"id": s.id, "name": s.name} for s in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client.id).order_by(models.DBSupplier.name).all()]
    return {"providers": [provider_dict(p) for p in rows], "suppliers": sup}


def _provider_fields(db, client_id, body, p):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "The provider's name.")
    mobile = (body.mobile or "").strip()
    if mobile and not (7 <= len([c for c in mobile if c.isdigit()]) <= 15):
        raise HTTPException(400, "The mobile number, 10 digits.")
    email = (body.email or "").strip()
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise HTTPException(400, "That email address does not look right.")
    if body.supplier_id and not db.query(models.DBSupplier).filter(models.DBSupplier.id == body.supplier_id, models.DBSupplier.client_id == client_id).first():
        raise HTTPException(400, "That supplier is not on the supplier list.")
    from sqlalchemy import func
    clash = db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.client_id == client_id, func.lower(models.DBPlantRentalProvider.name) == name.lower())
    if p.id:
        clash = clash.filter(models.DBPlantRentalProvider.id != p.id)
    if clash.first():
        raise HTTPException(409, "%s is already a provider." % name)
    p.name, p.contact_person, p.mobile, p.email = name[:120], (body.contact_person or "").strip()[:120], mobile[:20], email[:120]
    p.address, p.supplier_id = (body.address or "").strip(), body.supplier_id or None


@router.post("/api/plant/rental-providers")
def create_provider(body: ProviderIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    p = models.DBPlantRentalProvider(client_id=client.id)
    _provider_fields(db, client.id, body, p)
    db.add(p)
    db.flush()
    audit(db, client, "plant.provider.created", "plant_provider", p.id, p.name, "", actor, request)
    db.commit()
    return {"ok": True, "provider": provider_dict(p), "message": "%s added." % p.name}


@router.put("/api/plant/rental-providers/{pid}")
def update_provider(pid: int, body: ProviderIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    p = db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.id == pid, models.DBPlantRentalProvider.client_id == client.id).first()
    if not p:
        raise HTTPException(404, "Provider not found")
    _provider_fields(db, client.id, body, p)
    audit(db, client, "plant.provider.updated", "plant_provider", p.id, p.name, "", actor, request)
    db.commit()
    return {"ok": True, "provider": provider_dict(p), "message": "%s saved." % p.name}


def rental_dict(db, r, assets, providers):
    a = assets.get(r.asset_id)
    ext = db.query(models.DBPlantRentalExtension).filter(models.DBPlantRentalExtension.rental_id == r.id).order_by(models.DBPlantRentalExtension.id).all()
    inv = db.query(models.DBPlantRentalInvoice).filter(models.DBPlantRentalInvoice.rental_id == r.id).order_by(models.DBPlantRentalInvoice.invoice_date).all()
    end = r.actual_return or today()
    logs = [l for l in db.query(models.DBAssetLog).filter(models.DBAssetLog.asset_id == r.asset_id).all()
            if r.start_date <= (l.log_date or "") <= end and (l.approval_status or "") != "Rejected"]
    used = round(sum(h["operating"] for h in machine_hours(logs)), 1)
    billed = round(sum(i.billed_hours or 0 for i in inv), 1)
    amount, paid = money(sum(i.amount or 0 for i in inv)), money(sum(i.paid or 0 for i in inv))
    st = rental_status(r, bool(ext))
    p = providers.get(r.provider_id)
    days_left = (datetime.strptime(r.expected_return, "%Y-%m-%d").date() - date.today()).days if r.expected_return and not r.actual_return else None
    return {"id": r.id, "number": r.number, "asset_id": r.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
            "category": a.category if a else "", "reg_no": a.reg_no if a else "", "provider": provider_dict(p) if p else None,
            "agreement_no": r.agreement_no, "start_date": r.start_date, "expected_return": r.expected_return, "actual_return": r.actual_return or "",
            "rate": r.rate, "billing": r.billing, "min_billable_hours": r.min_billable_hours or 0, "overtime_rate": r.overtime_rate or 0,
            "transport_charges": r.transport_charges or 0, "deposit": r.deposit or 0, "advance": r.advance or 0,
            "fuel_included": bool(r.fuel_included), "operator_included": bool(r.operator_included), "notes": r.notes or "",
            "status": st, "days_left": days_left,
            "extensions": [{"from": x.from_date, "to": x.to_date, "reason": x.reason or "", "by": x.by_name or "", "at": (x.created_at or "")[:10]} for x in ext],
            "invoices": [{"id": i.id, "invoice_no": i.invoice_no, "invoice_date": i.invoice_date, "period_from": i.period_from or "", "period_to": i.period_to or "",
                          "billed_hours": i.billed_hours or 0, "amount": i.amount, "paid": i.paid or 0, "outstanding": money((i.amount or 0) - (i.paid or 0)),
                          "paid_on": i.paid_on or "", "payment_ref": i.payment_ref or ""} for i in inv],
            "billed": amount, "paid": paid, "outstanding": money(amount - paid), "used_hours": used, "billed_hours": billed,
            "hours_gap": round(billed - used, 1)}


@router.get("/api/plant/rentals")
def list_rentals(request: Request, status: str = "", provider_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    R = models.DBPlantRental
    q = db.query(R).filter(R.client_id == client.id)
    if provider_id:
        q = q.filter(R.provider_id == provider_id)
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    providers = {p.id: p for p in db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.client_id == client.id).all()}
    rows = [rental_dict(db, r, assets, providers) for r in q.order_by(R.id.desc()).limit(1000).all()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"rentals": rows, "billing": list(BILLING),
            "summary": {k: len([r for r in rows if r["status"] == k]) for k in ("Upcoming", "Active", "Extended", "Overdue", "Returned")} | {
                "outstanding": money(sum(r["outstanding"] for r in rows))}}


def _rental_or_404(db, client_id, rid):
    r = db.query(models.DBPlantRental).filter(models.DBPlantRental.id == rid, models.DBPlantRental.client_id == client_id).first()
    if not r:
        raise HTTPException(404, "Rental not found")
    return r


@router.post("/api/plant/rentals")
def create_rental(body: RentalIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    a = asset_or_404(db, client.id, body.asset_id)
    usable(a, "hire")
    if a.ownership == "Owned":
        raise HTTPException(409, "%s is owned by the company - only a machine hired in has a rental agreement. Mark it Rented first." % a.code)
    p = db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.id == body.provider_id, models.DBPlantRentalProvider.client_id == client.id).first()
    if not p:
        raise HTTPException(400, "Choose the rental provider.")
    ag = (body.agreement_no or "").strip()
    if not ag:
        raise HTTPException(400, "The rental agreement number.")
    from sqlalchemy import func
    R = models.DBPlantRental
    if db.query(R).filter(R.client_id == client.id, func.lower(R.agreement_no) == ag.lower()).first():
        raise HTTPException(409, "Agreement %s is already recorded." % ag)
    start = clean_day(body.start_date, "rental start date", required=True)
    ret = clean_day(body.expected_return, "expected return date", required=True)
    if ret < start:
        raise HTTPException(400, "It cannot go back before it arrives.")
    for o in db.query(R).filter(R.client_id == client.id, R.asset_id == a.id, R.actual_return == "").all():
        if _overlaps(start, ret, o.start_date, o.expected_return):
            raise HTTPException(409, "%s already has agreement %s for those dates." % (a.code, o.agreement_no))
    if body.billing not in BILLING:
        raise HTTPException(400, "Billed hourly, daily, weekly or monthly.")
    if not body.rate > 0:
        raise HTTPException(400, "The rental rate.")
    for what, v in (("minimum billable hours", body.min_billable_hours), ("overtime rate", body.overtime_rate), ("transport charges", body.transport_charges),
                    ("deposit", body.deposit), ("advance", body.advance)):
        if (v or 0) < 0:
            raise HTTPException(400, "The %s cannot be negative." % what)
    r = R(client_id=client.id, number=number_for(db, R, client.id, "RNT"), asset_id=a.id, provider_id=p.id, agreement_no=ag[:60], start_date=start,
          expected_return=ret, actual_return="", rate=money(body.rate), billing=body.billing, min_billable_hours=body.min_billable_hours or 0,
          overtime_rate=money(body.overtime_rate or 0), transport_charges=money(body.transport_charges or 0), deposit=money(body.deposit or 0),
          advance=money(body.advance or 0), fuel_included=bool(body.fuel_included), operator_included=bool(body.operator_included),
          notes=(body.notes or "").strip(), created_by=actor)
    # The register shows who it is hired from and on what terms.
    a.hired_from = p.name
    a.hire_rate = money(body.rate)
    a.hire_basis = {"Hourly": "Hour", "Daily": "Day", "Weekly": "Day", "Monthly": "Month"}[body.billing]
    if body.billing == "Weekly":
        a.hire_rate = money(body.rate / 7.0)
    if a.status == "Returned":
        a.status = "Available"
    db.add(r)
    db.flush()
    audit(db, client, "plant.rental.created", "plant_rental", r.id, r.number, "%s from %s, %s to %s at %s %s" % (a.code, p.name, start, ret, r.rate, r.billing.lower()), actor, request)
    db.commit()
    return {"ok": True, "id": r.id, "message": "%s recorded: %s from %s." % (r.number, a.code, p.name)}


@router.post("/api/plant/rentals/{rid}/extend")
def extend_rental(rid: int, body: ExtendIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    r = _rental_or_404(db, client.id, rid)
    if r.actual_return:
        raise HTTPException(409, "%s has been returned." % r.number)
    to = clean_day(body.to_date, "new return date", required=True)
    if to <= r.expected_return:
        raise HTTPException(400, "The new return date is after %s." % r.expected_return)
    db.add(models.DBPlantRentalExtension(rental_id=r.id, from_date=r.expected_return, to_date=to, reason=(body.reason or "").strip()[:200], by_name=actor))
    audit(db, client, "plant.rental.extended", "plant_rental", r.id, r.number, "%s to %s. %s" % (r.expected_return, to, body.reason or ""), actor, request)
    r.expected_return = to
    db.commit()
    return {"ok": True, "message": "%s extended to %s." % (r.number, to)}


@router.post("/api/plant/rentals/{rid}/return")
def return_rental(rid: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    """Back to its owner: off any site, nobody allocated to it, and no longer available - all in one change."""
    client, _, actor = wo_actor(request, db, MANAGE)
    r = _rental_or_404(db, client.id, rid)
    if r.actual_return:
        raise HTTPException(409, "%s was returned on %s." % (r.number, r.actual_return))
    on = clean_day(body.returned_on, "return date") or today()
    if on < r.start_date:
        raise HTTPException(400, "It cannot go back before it arrived (%s)." % r.start_date)
    if on > today():
        raise HTTPException(400, "Record the return on the day it goes back.")
    a = asset_or_404(db, client.id, r.asset_id)
    ended = 0
    for al in db.query(models.DBPlantAllocation).filter(models.DBPlantAllocation.asset_id == a.id, models.DBPlantAllocation.status == "Active").all():
        al.status, al.end_date, al.ended_reason = "Ended", max(on, al.start_date), "Machine returned to its owner"
        ended += 1
    if a.current_job_id:
        db.add(models.DBAssetMove(client_id=client.id, asset_id=a.id, from_job_id=a.current_job_id, to_job_id=None, moved_on=on,
                                  note="Returned to %s" % (r.agreement_no or "owner"), by_name=actor))
    a.current_job_id, a.status = None, "Returned"
    r.actual_return = on
    audit(db, client, "plant.rental.returned", "plant_rental", r.id, r.number, "%s returned %s; %d allocation(s) ended" % (a.code, on, ended), actor, request)
    db.commit()
    return {"ok": True, "message": "%s returned on %s%s." % (a.code, on, ("; %d allocation%s ended" % (ended, "" if ended == 1 else "s")) if ended else "")}


@router.post("/api/plant/rentals/{rid}/invoices")
def add_rental_invoice(rid: int, body: RentalInvoiceIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    r = _rental_or_404(db, client.id, rid)
    no = check_invoice_unique(db, client.id, body.invoice_no)
    if not no:
        raise HTTPException(400, "The invoice number.")
    on = clean_day(body.invoice_date, "invoice date") or today()
    pf, pt = clean_day(body.period_from, "period start"), clean_day(body.period_to, "period end")
    if pf and pt and pt < pf:
        raise HTTPException(400, "The billing period ends before it starts.")
    if not body.amount > 0:
        raise HTTPException(400, "The amount billed.")
    paid = float(body.paid or 0)
    if paid < 0 or paid > body.amount + 0.001:
        raise HTTPException(400, "The amount paid is between 0 and the amount billed.")
    if (body.billed_hours or 0) < 0:
        raise HTTPException(400, "Billed hours cannot be negative.")
    inv = models.DBPlantRentalInvoice(client_id=client.id, rental_id=r.id, invoice_no=no[:60], invoice_date=on, period_from=pf, period_to=pt,
                                      billed_hours=body.billed_hours or 0, amount=money(body.amount), paid=money(paid),
                                      paid_on=clean_day(body.paid_on, "payment date") if paid else "", payment_ref=(body.payment_ref or "").strip()[:80], recorded_by=actor)
    db.add(inv)
    db.flush()
    audit(db, client, "plant.rental.invoiced", "plant_rental", r.id, r.number, "Invoice %s for %s, paid %s" % (no, inv.amount, inv.paid), actor, request)
    db.commit()
    return {"ok": True, "message": "Invoice %s recorded: %s outstanding." % (no, money(inv.amount - inv.paid))}


@router.post("/api/plant/rental-invoices/{iid}/payment")
def pay_rental_invoice(iid: int, body: PaymentIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    inv = db.query(models.DBPlantRentalInvoice).filter(models.DBPlantRentalInvoice.id == iid, models.DBPlantRentalInvoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    due = money((inv.amount or 0) - (inv.paid or 0))
    if not 0 < body.amount <= due + 0.001:
        raise HTTPException(400, "Pay between 0 and what is outstanding (%s)." % due)
    inv.paid = money((inv.paid or 0) + body.amount)
    inv.paid_on = clean_day(body.paid_on, "payment date") or today()
    if (body.payment_ref or "").strip():
        inv.payment_ref = body.payment_ref.strip()[:80]
    audit(db, client, "plant.rental.paid", "plant_rental", inv.rental_id, inv.invoice_no, "Paid %s on %s" % (body.amount, inv.paid_on), actor, request)
    db.commit()
    return {"ok": True, "message": "Payment recorded: %s outstanding." % money(inv.amount - inv.paid)}


# ---- expenses ----------------------------------------------------------------------------------------

def expense_dict(e, assets, jobs):
    a = assets.get(e.asset_id)
    return {"id": e.id, "number": e.number, "source": "expense", "asset_id": e.asset_id, "code": a.code if a else "", "machine": a.name if a else "",
            "project": job_label(jobs, e.job_id), "category": e.category, "spent_on": e.spent_on, "description": e.description or "",
            "quantity": e.quantity or 0, "unit_rate": e.unit_rate or 0, "amount": e.amount, "vendor": e.vendor or "", "invoice_no": e.invoice_no or "",
            "payment_status": e.payment_status, "payment_ref": e.payment_ref or "", "approval_status": e.approval_status, "approved_by": e.approved_by or "",
            "recorded_by": e.recorded_by or ""}


@router.get("/api/plant/expenses")
def list_expenses(request: Request, date_from: str = "", date_to: str = "", asset_id: int = 0, category: str = "", db: Session = Depends(get_read_db)):
    """One register of every machine cost: what is entered here, and - read-only, from their own registers - fuel,
    maintenance and rental bills, so each appears once."""
    client = require_erp_read(request, db)
    df, dt = date_from[:10], date_to[:10]
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    jobs = jobs_of(db, client.id)
    rows = [expense_dict(e, assets, jobs) for e in db.query(models.DBPlantExpense).filter(models.DBPlantExpense.client_id == client.id).order_by(
        models.DBPlantExpense.spent_on.desc()).all() if in_range(e.spent_on, df, dt) and (not asset_id or e.asset_id == asset_id)]
    code = lambda aid: (assets[aid].code, assets[aid].name) if aid in assets else ("", "")
    for f in db.query(models.DBPlantFuel).filter(models.DBPlantFuel.client_id == client.id).all():
        if in_range(f.filled_at, df, dt) and (not asset_id or f.asset_id == asset_id):
            rows.append({"id": f.id, "number": f.number, "source": "fuel", "asset_id": f.asset_id, "code": code(f.asset_id)[0], "machine": code(f.asset_id)[1],
                         "project": job_label(jobs, f.job_id), "category": "Fuel and diesel", "spent_on": f.filled_at[:10], "description": "%g L %s" % (f.litres, f.fuel_type),
                         "quantity": f.litres, "unit_rate": f.rate, "amount": f.amount, "vendor": f.supplier or "", "invoice_no": f.voucher_no or "",
                         "payment_status": "", "payment_ref": "", "approval_status": "Recorded", "approved_by": "", "recorded_by": f.recorded_by or ""})
    for s in db.query(models.DBAssetService).filter(models.DBAssetService.client_id == client.id, models.DBAssetService.total_cost > 0).all():
        if in_range(s.completed_on or s.service_on, df, dt) and (not asset_id or s.asset_id == asset_id):
            rows.append({"id": s.id, "number": s.number or ("SVC-%d" % s.id), "source": "maintenance", "asset_id": s.asset_id, "code": code(s.asset_id)[0],
                         "machine": code(s.asset_id)[1], "project": job_label(jobs, s.job_id), "category": "Maintenance and repairs",
                         "spent_on": s.completed_on or s.service_on, "description": (s.work_performed or s.description or "")[:200], "quantity": 0, "unit_rate": 0,
                         "amount": s.total_cost, "vendor": s.mechanic or s.vendor or "", "invoice_no": s.invoice_no or "", "payment_status": "", "payment_ref": "",
                         "approval_status": s.approval_status or "Recorded", "approved_by": s.approved_by or "", "recorded_by": s.recorded_by_name or ""})
    rentals = {r.id: r for r in db.query(models.DBPlantRental).filter(models.DBPlantRental.client_id == client.id).all()}
    for i in db.query(models.DBPlantRentalInvoice).filter(models.DBPlantRentalInvoice.client_id == client.id).all():
        r = rentals.get(i.rental_id)
        if r and in_range(i.invoice_date, df, dt) and (not asset_id or r.asset_id == asset_id):
            rows.append({"id": i.id, "number": r.number, "source": "rental", "asset_id": r.asset_id, "code": code(r.asset_id)[0], "machine": code(r.asset_id)[1],
                         "project": "", "category": "Rental charges", "spent_on": i.invoice_date, "description": "Hire %s to %s" % (i.period_from or "", i.period_to or ""),
                         "quantity": i.billed_hours or 0, "unit_rate": 0, "amount": i.amount, "vendor": "", "invoice_no": i.invoice_no,
                         "payment_status": "Paid" if (i.paid or 0) >= (i.amount or 0) else ("Part paid" if i.paid else "Unpaid"),
                         "payment_ref": i.payment_ref or "", "approval_status": "Recorded", "approved_by": "", "recorded_by": i.recorded_by or ""})
    if category:
        rows = [r for r in rows if r["category"] == category]
    rows.sort(key=lambda r: r["spent_on"], reverse=True)
    counted = [r for r in rows if r["approval_status"] != "Rejected"]
    by_cat = {}
    for r in counted:
        by_cat[r["category"]] = money(by_cat.get(r["category"], 0) + r["amount"])
    return {"expenses": rows, "categories": list(EXPENSE_CATEGORIES), "all_categories": list(EXPENSE_CATEGORIES) + list(DERIVED_CATEGORIES),
            "by_category": by_cat, "total": money(sum(r["amount"] for r in counted))}


def _expense_fields(db, client_id, body, e):
    if body.category in DERIVED_CATEGORIES:
        raise HTTPException(400, "%s is recorded in %s, so it is counted once." % (body.category, DERIVED_CATEGORIES[body.category]))
    if body.category not in EXPENSE_CATEGORIES:
        raise HTTPException(400, "The category is one of: %s." % ", ".join(EXPENSE_CATEGORIES))
    on = clean_day(body.spent_on, "date") or today()
    if on > today():
        raise HTTPException(400, "An expense cannot be dated in the future.")
    if not (body.description or "").strip():
        raise HTTPException(400, "Describe the expense.")
    qty, rate = float(body.quantity or 0), float(body.unit_rate or 0)
    if qty < 0 or rate < 0:
        raise HTTPException(400, "Quantity and rate cannot be negative.")
    amount = money(qty * rate) if qty and rate else money(body.amount or 0)
    if body.amount is not None and qty and rate and abs(body.amount - amount) > 1:
        raise HTTPException(400, "%g at %g is %s." % (qty, rate, amount))
    if not amount > 0:
        raise HTTPException(400, "The amount.")
    if body.payment_status not in ("Unpaid", "Part paid", "Paid"):
        raise HTTPException(400, "Unpaid, part paid or paid.")
    e.invoice_no = check_invoice_unique(db, client_id, body.invoice_no, ("expense", e.id) if e.id else None)
    # The same cost typed twice - same machine, day, category and amount, with no voucher to tell them apart.
    if not e.invoice_no:
        q = db.query(models.DBPlantExpense).filter(models.DBPlantExpense.client_id == client_id, models.DBPlantExpense.asset_id == body.asset_id,
                                                   models.DBPlantExpense.spent_on == on, models.DBPlantExpense.category == body.category,
                                                   models.DBPlantExpense.amount == amount, models.DBPlantExpense.approval_status != "Rejected",
                                                   models.DBPlantExpense.invoice_no == "")
        if e.id:
            q = q.filter(models.DBPlantExpense.id != e.id)
        twin = q.first()
        if twin:
            raise HTTPException(409, "%s is the same expense - same machine, day, category and amount. Give the invoice number if it really is another." % twin.number)
    e.category, e.spent_on, e.description = body.category, on, body.description.strip()[:500]
    e.quantity, e.unit_rate, e.amount = qty, rate, amount
    e.vendor, e.payment_status, e.payment_ref = (body.vendor or "").strip()[:120], body.payment_status, (body.payment_ref or "").strip()[:80]


@router.post("/api/plant/expenses")
def create_expense(body: ExpenseIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    a = asset_or_404(db, client.id, body.asset_id)
    E = models.DBPlantExpense
    e = E(client_id=client.id, asset_id=a.id, job_id=a.current_job_id, recorded_by=actor, approval_status="Pending")
    _expense_fields(db, client.id, body, e)
    e.number = number_for(db, E, client.id, "EXP")
    db.add(e)
    db.flush()
    audit(db, client, "plant.expense.recorded", "plant_expense", e.id, e.number, "%s %s %s" % (a.code, e.category, e.amount), actor, request)
    db.commit()
    return {"ok": True, "id": e.id, "message": "%s recorded: %s." % (e.number, e.amount)}


def _expense_or_404(db, client_id, eid):
    e = db.query(models.DBPlantExpense).filter(models.DBPlantExpense.id == eid, models.DBPlantExpense.client_id == client_id).first()
    if not e:
        raise HTTPException(404, "Expense not found")
    return e


@router.put("/api/plant/expenses/{eid}")
def update_expense(eid: int, body: ExpenseIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    e = _expense_or_404(db, client.id, eid)
    if e.approval_status == "Approved":
        raise HTTPException(409, "%s is approved - it is the record now." % e.number)
    asset_or_404(db, client.id, body.asset_id)
    e.asset_id = body.asset_id
    _expense_fields(db, client.id, body, e)
    e.approval_status = "Pending"
    audit(db, client, "plant.expense.updated", "plant_expense", e.id, e.number, "%s %s" % (e.category, e.amount), actor, request)
    db.commit()
    return {"ok": True, "message": "%s saved." % e.number}


@router.post("/api/plant/expenses/{eid}/decision")
def decide_expense(eid: int, body: DecisionIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, "site.signoff")
    e = _expense_or_404(db, client.id, eid)
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "Approve or reject.")
    if body.decision == "reject" and not (body.remarks or "").strip():
        raise HTTPException(400, "Say why it is rejected.")
    e.approval_status, e.approved_by = ("Approved" if body.decision == "approve" else "Rejected"), actor
    audit(db, client, "plant.expense." + e.approval_status.lower(), "plant_expense", e.id, e.number, body.remarks or "", actor, request)
    db.commit()
    return {"ok": True, "message": "%s %s." % (e.number, e.approval_status.lower())}


@router.delete("/api/plant/expenses/{eid}")
def delete_expense(eid: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    e = _expense_or_404(db, client.id, eid)
    if e.approval_status == "Approved":
        raise HTTPException(409, "%s is approved - reject it instead of deleting it." % e.number)
    audit(db, client, "plant.expense.removed", "plant_expense", e.id, e.number, "%s %s" % (e.category, e.amount), actor, request)
    db.delete(e)
    db.commit()
    return {"ok": True, "message": "%s removed." % e.number}


# ---- reports --------------------------------------------------------------------------------------

REPORTS = {
    "register": "Equipment register", "allocations": "Allocation history", "employee-hours": "Employee working hours",
    "machine-hours": "Machine operating hours", "fuel": "Fuel consumption and expenditure", "maintenance": "Maintenance and breakdown history",
    "rentals": "Rental agreements and returns", "rental-invoices": "Rental invoices and outstanding", "expenses": "Equipment expenses",
    "overtime": "Employee overtime",
}


@router.get("/api/plant/reports/{kind}.xlsx")
def plant_report(kind: str, request: Request, date_from: str = "", date_to: str = "", asset_id: int = 0, employee_id: int = 0,
                 ownership: str = "", status: str = "", provider_id: int = 0, db: Session = Depends(get_db)):
    """Each report through the same reads the screens use, so it shows what the person asking may see. A .pdf of each
    is served beside it."""
    client = require_erp_read(request, db)
    if kind not in REPORTS:
        raise HTTPException(404, "No such report")
    df, dt = date_from[:10], date_to[:10]
    if kind == "register":
        rows = []
        for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).order_by(models.DBAsset.code).all():
            d = asset_dict(db, a)
            if (asset_id and a.id != asset_id) or (ownership and d["ownership_label"] != ownership and d["ownership"] != ownership) or (status and a.status != status):
                continue
            sch = d["service"]["schedule"]
            rows.append((d["code"], d["name"], d["category"], d["ownership_label"], d["brand"], d["model"], d["reg_no"], d["status"],
                         d["condition"], d["where"], d["meter_reading"], sch["status"],
                         "" if sch["next_meter"] is None else sch["next_meter"], sch["next_on"] or "",
                         "; ".join(d["service"]["reasons"]), "Archived" if d["is_archived"] else ""))
        head = ("ID", "Machine", "Category", "Ownership", "Brand", "Model", "Registration", "Status", "Condition", "Where", "Meter",
                "Service status", "Next service at", "Next service on", "Service", "")
    elif kind == "allocations":
        d = list_allocations(request, asset_id, employee_id, status, db)["allocations"]
        rows = [(r["code"], r["machine"], (r["employee"] or {}).get("code", ""), (r["employee"] or {}).get("name", ""), (r["employee"] or {}).get("mobile", ""),
                 r["role"], r["shift"], r["project"], r["start_date"], r["end_date"], (r["supervisor"] or {}).get("name", ""), r["status"], r["ended_reason"])
                for r in d if (not df or (r["end_date"] or "9999") >= df) and (not dt or r["start_date"] <= dt)]
        head = ("Machine ID", "Machine", "Employee ID", "Employee", "Mobile", "Role", "Shift", "Project", "From", "To", "Supervisor", "Status", "Ended because")
    elif kind in ("employee-hours", "overtime"):
        logs = [l for l in list_logs(request, df, dt, asset_id, employee_id, status, db)["logs"] if l["employee"]]
        by = {}
        for l in logs:
            key = (l["employee"].get("name", ""), l["log_date"][:7] if kind == "employee-hours" else l["log_date"])
            b = by.setdefault(key, [l["employee"].get("name", ""), l["employee"].get("mobile", ""), key[1], 0.0, 0.0, 0.0, 0])
            b[3] += l["attendance_hours"]
            b[4] += l["regular_hours"]
            b[5] += l["overtime_hours"]
            b[6] += 1
        rows = [tuple(v) for v in sorted(by.values(), key=lambda v: (v[0], v[2])) if kind == "employee-hours" or v[5] > 0]
        head = ("Employee", "Mobile", "Month" if kind == "employee-hours" else "Day", "Hours on duty", "Regular", "Overtime", "Shifts")
    elif kind == "machine-hours":
        rows = [(v["code"], v["name"], v["operating_hours"], v["idle_hours"], v["breakdown_hours"], round(v["idle_share"] * 100, 1))
                for v in costs(db, client.id, df, dt, asset_id).values()]
        head = ("Machine ID", "Machine", "Operating hours", "Idle hours", "Breakdown hours", "Idle %")
    elif kind == "fuel":
        d = list_fuel(request, df, dt, asset_id, db)
        rows = [(f["number"], f["filled_at"], f["code"], f["machine"], f["fuel_type"], f["litres"], f["rate"], f["amount"], f["supplier"], f["voucher_no"], f["meter_reading"] if f["meter_reading"] is not None else "", f["recorded_by"]) for f in d["fuel"]]
        head = ("Fuel ID", "When", "Machine ID", "Machine", "Fuel", "Litres", "Rate", "Amount", "Supplier", "Voucher", "Meter", "Recorded by")
    elif kind == "maintenance":
        d = list_maintenance(request, asset_id, status, df, dt, db)["maintenance"]
        rows = [(m["number"], m["code"], m["machine"], m["kind"], m["priority"], m["status"], m["reported_on"], m["scheduled_on"], m["completed_on"], m["description"], m["mechanic"],
                 m["parts_cost"], m["labour_cost"], m["total_cost"], m["downtime_hours"], m["invoice_no"]) for m in d]
        head = ("Request", "Machine ID", "Machine", "Type", "Priority", "Status", "Reported", "Scheduled", "Completed", "Problem", "Mechanic", "Parts", "Labour", "Total", "Down h", "Invoice")
    elif kind == "rentals":
        d = list_rentals(request, status, provider_id, db)["rentals"]
        rows = [(r["number"], r["agreement_no"], r["code"], r["machine"], (r["provider"] or {}).get("name", ""), r["start_date"], r["expected_return"], r["actual_return"], r["rate"],
                 r["billing"], r["status"], r["used_hours"], r["billed_hours"], r["billed"], r["paid"], r["outstanding"]) for r in d]
        head = ("Rental", "Agreement", "Machine ID", "Machine", "Provider", "Start", "Return due", "Returned", "Rate", "Billing", "Status", "Hours used", "Hours billed", "Billed", "Paid", "Outstanding")
    elif kind == "rental-invoices":
        rows = []
        for r in list_rentals(request, status, provider_id, db)["rentals"]:
            for i in r["invoices"]:
                if in_range(i["invoice_date"], df, dt):
                    rows.append((r["number"], (r["provider"] or {}).get("name", ""), r["code"], i["invoice_no"], i["invoice_date"], i["period_from"], i["period_to"],
                                 i["billed_hours"], i["amount"], i["paid"], i["outstanding"], i["paid_on"], i["payment_ref"]))
        head = ("Rental", "Provider", "Machine ID", "Invoice", "Date", "From", "To", "Hours", "Amount", "Paid", "Outstanding", "Paid on", "Reference")
    else:
        d = list_expenses(request, df, dt, asset_id, "", db)["expenses"]
        rows = [(e["number"], e["spent_on"], e["code"], e["machine"], e["category"], e["description"], e["quantity"] or "", e["unit_rate"] or "", e["amount"], e["vendor"],
                 e["invoice_no"], e["payment_status"], e["approval_status"]) for e in d]
        head = ("ID", "Date", "Machine ID", "Machine", "Category", "Description", "Qty", "Rate", "Amount", "Vendor", "Invoice", "Payment", "Approval")
    from app.documents.forms import _pre
    return sheet_response(head, rows, "plant-%s.xlsx" % kind, preamble=_pre(client, REPORTS[kind].upper()), portrait=True)
