"""The assets endpoints."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db, get_read_db

from app.constants.assets import ASSET_BOOK_DEFAULTS, ASSET_CATEGORIES, BOOK_METHODS, HIRE_BASES
from app.core.audit import log_audit
from app.core.auth import require_erp_read, require_items_access, wo_actor
from app.core.currency import inr, money
from app.core.dates import _parse_date
from app.core.sheets import sheet_response
from app.schemas.assets import (
    AssetBookIn,
    AssetDisposalIn,
    AssetIn,
    AssetLogIn,
    AssetMoveIn,
    AssetServiceIn,
    ServiceDoneIn,
    TaxBlockIn,
)
from app.services.plant import check_invoice_unique, number_for
from app.services.assets import (
    UNIT_WORD,
    _apply_asset,
    _apply_book,
    apply_location,
    apply_schedule,
    describe_changes,
    interval_type,
    record_service_done,
    schedule_snapshot,
    asset_book_or_none,
    asset_costs,
    asset_dict,
    asset_or_404,
    asset_service_state,
    check_unique_asset,
    book_dict,
    book_schedule,
    default_book,
    ensure_tax_blocks,
    fy_label,
    fy_start_year,
    hire_cost_for,
    next_asset_code,
    tax_block_schedule,
)
from app.services.projects import job_or_404


router = APIRouter()


@router.get("/api/assets")
def list_assets(request: Request, status: str = "", job_id: int = 0, archived: bool = False, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id,
                                        models.DBAsset.is_archived.is_(True) if archived else models.DBAsset.is_archived.isnot(True))
    if status:
        q = q.filter(models.DBAsset.status == status)
    if job_id:
        q = q.filter(models.DBAsset.current_job_id == job_id)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    costs = asset_costs(db, client.id)
    rows = [asset_dict(db, a, jobs, costs) for a in q.order_by(models.DBAsset.code).all()]
    live = [r for r in rows if r["status"] != "Disposed"]
    return {"assets": rows, "categories": list(ASSET_CATEGORIES), "hire_bases": list(HIRE_BASES),
            "summary": {
                "machines": len(live),
                "deployed": len([r for r in live if r["status"] == "Deployed"]),
                "idle_in_yard": len([r for r in live if r["status"] == "Available"]),
                "under_repair": len([r for r in live if r["status"] == "Under repair"]),
                "service_due": len([r for r in live if r["service"]["due"]]),
                "service_soon": len([r for r in live if r["service"]["soon"]]),
                "service_status": {k: len([r for r in live if r["service"]["status"] == k])
                                   for k in ("Upcoming", "Due soon", "Service due", "Overdue", "Incomplete", "Not scheduled")},
                "hired": len([r for r in live if r["ownership"] == "Hired"]),
                "cost_to_date": money(sum(r["cost_to_date"] for r in rows))}}


@router.post("/api/assets")
def create_asset(body: AssetIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, ("stores.manage", "workorders.manage"))
    code = (body.code or "").strip().upper()
    a = models.DBAsset(client_id=client.id, code=code or next_asset_code(db, client.id), status="Available")
    before = schedule_snapshot(a)
    _apply_asset(a, body)
    check_unique_asset(db, client.id, a)
    if (body.meter_reading or 0) < 0:
        raise HTTPException(400, "A meter reading cannot be negative.")
    a.meter_reading = float(body.meter_reading or 0)
    a.last_service_on = (body.last_service_on or "").strip()[:10]
    # Left blank on a new machine, the schedule counts from the reading it comes in at - said so on the form.
    a.last_service_meter = (float(body.last_service_meter) if body.last_service_meter is not None
                            else a.meter_reading)
    changes = apply_schedule(a, body, before)
    db.add(a)
    db.flush()
    apply_location(db, client.id, a, body, actor_name)
    log_audit(db, client.id, "plant.machine.created", "equipment", a.id, a.code, a.name, request=request, user_name=actor_name)
    if a.service_interval_type != "None":
        log_audit(db, client.id, "plant.schedule.set", "equipment", a.id, a.code, describe_changes(changes),
                  request=request, user_name=actor_name)
    db.commit()
    db.refresh(a)
    return asset_dict(db, a)


@router.put("/api/assets/{asset_id}")
def update_asset(asset_id: int, body: AssetIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, ("stores.manage", "workorders.manage"))
    a = asset_or_404(db, client.id, asset_id)
    before = schedule_snapshot(a)
    _apply_asset(a, body)
    code = (body.code or "").strip().upper()
    if code:
        a.code = code
    check_unique_asset(db, client.id, a)
    log_audit(db, client.id, "plant.machine.updated", "equipment", a.id, a.code, a.name, request=request, user_name=actor_name)
    # The form shows when it was last serviced; an edit that corrects it used
    # to be dropped without a word, and the service warning kept counting
    # from the wrong date. The meter itself moves with the daily log.
    if body.last_service_on is not None:
        a.last_service_on = (body.last_service_on or "").strip()[:10]
    if body.last_service_meter is not None:
        if body.last_service_meter < 0:
            raise HTTPException(400, "A meter reading cannot be negative.")
        a.last_service_meter = float(body.last_service_meter)
    changes = apply_schedule(a, body, before)
    apply_location(db, client.id, a, body, actor_name)
    if changes:
        log_audit(db, client.id, "plant.schedule.changed", "equipment", a.id, a.code, describe_changes(changes),
                  request=request, user_name=actor_name)
    db.commit()
    return asset_dict(db, a)


@router.post("/api/assets/{asset_id}/archive")
def archive_asset(asset_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Off the working register - its logs, costs and history stay. Not while it is on a site or someone is on it."""
    client, _, actor_name = wo_actor(request, db, ("stores.manage", "workorders.manage"))
    a = asset_or_404(db, client.id, asset_id)
    back = bool((body or {}).get("restore"))
    if not back:
        if a.current_job_id:
            raise HTTPException(409, "%s is on a site. Bring it back to the yard before archiving it." % a.code)
        if db.query(models.DBPlantAllocation).filter(models.DBPlantAllocation.asset_id == a.id,
                                                     models.DBPlantAllocation.status == "Active").first():
            raise HTTPException(409, "%s still has people allocated to it. End those first." % a.code)
    a.is_archived = not back
    log_audit(db, client.id, "plant.machine.restored" if back else "plant.machine.archived", "equipment", a.id, a.code, a.name,
              request=request, user_name=actor_name)
    db.commit()
    return {"ok": True, "asset": asset_dict(db, a), "message": "%s %s." % (a.code, "back on the register" if back else "archived")}


@router.get("/api/assets/{asset_id}")
def get_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    a = asset_or_404(db, client.id, asset_id)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    label = lambda jid: ("%s %s" % (jobs[jid].number, jobs[jid].name)) if jid in jobs else "Yard"
    d = asset_dict(db, a, jobs, asset_costs(db, client.id))
    d["moves"] = [{"moved_on": m.moved_on, "from": label(m.from_job_id) if m.from_job_id else "Yard",
                   "to": label(m.to_job_id) if m.to_job_id else "Yard", "note": m.note or "",
                   "by": m.by_name or ""}
                  for m in db.query(models.DBAssetMove).filter(
                      models.DBAssetMove.asset_id == a.id).order_by(models.DBAssetMove.id.desc()).all()]
    d["logs"] = [{"id": l.id, "log_date": l.log_date, "job": label(l.job_id) if l.job_id else "",
                  "hours_worked": l.hours_worked or 0, "idle_hours": l.idle_hours or 0,
                  "fuel_litres": l.fuel_litres or 0, "fuel_cost": money(l.fuel_cost),
                  "hire_cost": money(l.hire_cost), "meter_reading": l.meter_reading,
                  "operator": l.operator or "", "work_done": l.work_done or ""}
                 for l in db.query(models.DBAssetLog).filter(
                     models.DBAssetLog.asset_id == a.id).order_by(
                         models.DBAssetLog.log_date.desc()).limit(120).all()]
    S = models.DBAssetService
    d["services"] = [{"id": s.id, "number": s.number or "", "service_on": s.completed_on or s.service_on, "kind": s.kind,
                      "status": s.status or "Completed",
                      "description": s.description or "", "vendor": s.vendor or s.mechanic or "",
                      "work_performed": s.work_performed or "", "parts_used": s.parts_used or "",
                      "parts_cost": money(s.parts_cost), "labour_cost": money(s.labour_cost),
                      "total_cost": money(s.total_cost), "downtime_hours": s.downtime_hours or 0,
                      "meter_at_service": s.meter_at_service,
                      "next_service_meter": s.next_service_meter, "next_service_on": s.next_service_on or "",
                      "by": s.recorded_by_name or "",
                      "job": label(s.job_id) if s.job_id else ""}
                     for s in db.query(S).filter(S.asset_id == a.id, (S.status == "Completed") | (S.status.is_(None))).order_by(
                         S.service_on.desc(), S.id.desc()).all()]
    # Every change to the schedule and every service that reset it, as the audit trail has them.
    L = models.DBAuditLog
    d["schedule_history"] = [{"at": str(x.created_at or "")[:16], "action": x.action, "details": x.details or "", "by": x.user_name or ""}
                             for x in db.query(L).filter(L.client_id == client.id, L.entity_type == "equipment", L.entity_id == a.id,
                                                         L.action.in_(("plant.schedule.set", "plant.schedule.changed", "plant.service.completed"))
                                                         ).order_by(L.id.desc()).limit(50).all()]
    # How hard it worked: hours against the hours it stood on a site.
    worked = sum(l["hours_worked"] for l in d["logs"])
    idle = sum(l["idle_hours"] for l in d["logs"])
    d["utilisation_percent"] = round(worked / (worked + idle) * 100, 1) if (worked + idle) else 0.0
    d["litres_per_hour"] = round(sum(l["fuel_litres"] for l in d["logs"]) / worked, 2) if worked else 0.0
    return d


@router.post("/api/assets/{asset_id}/move")
def move_asset(asset_id: int, body: AssetMoveIn, request: Request, db: Session = Depends(get_db)):
    """To a site, between sites, or back to the yard."""
    client, actor_id, actor_name = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, asset_id)
    if a.status == "Disposed":
        raise HTTPException(409, "%s has been disposed of." % a.code)
    if a.status in ("Under repair", "Breakdown"):
        raise HTTPException(409, "%s is %s. Put it back in service first." % (a.code, a.status.lower()))
    if a.status == "Returned" or a.is_archived:
        raise HTTPException(409, "%s is %s - it cannot be deployed." % (a.code, "returned to its owner" if a.status == "Returned" else "archived"))
    if body.to_job_id:
        job = job_or_404(db, client.id, body.to_job_id)
        if a.current_job_id == job.id:
            raise HTTPException(409, "%s is already on %s." % (a.code, job.name))
    elif not a.current_job_id:
        raise HTTPException(409, "%s is already in the yard." % a.code)
    on = (body.moved_on or datetime.now().strftime("%Y-%m-%d"))[:10]
    db.add(models.DBAssetMove(client_id=client.id, asset_id=a.id, from_job_id=a.current_job_id,
                              to_job_id=body.to_job_id, moved_on=on,
                              note=(body.note or "").strip(), by_name=actor_name))
    a.current_job_id = body.to_job_id or None
    a.status = "Deployed" if body.to_job_id else "Available"
    a.location_type = "Site" if body.to_job_id else "Yard"
    db.commit()
    return {"ok": True, "asset": asset_dict(db, a),
            "message": "%s %s." % (a.code, ("moved to " + asset_dict(db, a)["current_job"])
                                   if body.to_job_id else "back in the yard")}


@router.post("/api/assets/{asset_id}/logs")
def log_asset_day(asset_id: int, body: AssetLogIn, request: Request, db: Session = Depends(get_db)):
    """One machine, one day - on the site it is deployed to."""
    client, actor_id, actor_name = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, asset_id)
    if a.status != "Deployed" or not a.current_job_id:
        raise HTTPException(409, "%s is not on a site. Deploy it before logging its day." % a.code)
    on = (body.log_date or datetime.now().strftime("%Y-%m-%d"))[:10]
    if db.query(models.DBAssetLog).filter(models.DBAssetLog.asset_id == a.id,
                                          models.DBAssetLog.log_date == on).first():
        raise HTTPException(409, "%s already has a log for %s." % (a.code, on))
    worked, idle = float(body.hours_worked or 0), float(body.idle_hours or 0)
    if worked < 0 or idle < 0 or worked + idle > 24:
        raise HTTPException(400, "Hours worked and idle add up to more than a day.")
    if body.meter_reading is not None:
        if body.meter_reading < (a.meter_reading or 0):
            raise HTTPException(400, "The meter reads %g now; %g would run it backwards."
                                     % (a.meter_reading or 0, body.meter_reading))
        a.meter_reading = float(body.meter_reading)
    elif a.meter_unit == "Hours" and worked:
        a.meter_reading = (a.meter_reading or 0) + worked
    litres = max(0.0, float(body.fuel_litres or 0))
    rate = max(0.0, float(body.fuel_rate or 0))
    log = models.DBAssetLog(
        client_id=client.id, asset_id=a.id, job_id=a.current_job_id, log_date=on,
        hours_worked=worked, idle_hours=idle, fuel_litres=litres, fuel_rate=rate,
        fuel_cost=money(litres * rate), hire_cost=hire_cost_for(a, worked),
        meter_reading=a.meter_reading, operator=(body.operator or "").strip(),
        work_done=(body.work_done or "").strip()[:300], recorded_by_name=actor_name)
    db.add(log)
    db.commit()
    state = asset_service_state(a)
    return {"ok": True, "cost": money(log.fuel_cost + log.hire_cost), "service": state,
            "message": "%s logged for %s: %g h worked%s." % (
                a.code, on, worked, (" - " + "; ".join(state["reasons"])) if state["reasons"] else "")}


@router.post("/api/assets/{asset_id}/services")
def service_asset(asset_id: int, body: AssetServiceIn, request: Request, db: Session = Depends(get_db)):
    """A service resets the clock; a breakdown may take the machine off work
    until it is put back."""
    client, actor_id, actor_name = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, asset_id)
    kind = body.kind if body.kind in ("Preventive", "Breakdown", "Repair") else "Repair"
    on = (body.service_on or datetime.now().strftime("%Y-%m-%d"))[:10]
    meter = body.meter_at_service if body.meter_at_service is not None else a.meter_reading
    if (body.parts_cost or 0) < 0 or (body.labour_cost or 0) < 0:
        raise HTTPException(400, "A cost cannot be negative.")
    total = money((body.parts_cost or 0) + (body.labour_cost or 0))
    s = models.DBAssetService(
        client_id=client.id, asset_id=a.id, job_id=a.current_job_id, service_on=on, kind=kind,
        description=(body.description or "").strip(), vendor=(body.vendor or "").strip(),
        parts_cost=money(body.parts_cost or 0), labour_cost=money(body.labour_cost or 0),
        total_cost=total, downtime_hours=max(0.0, float(body.downtime_hours or 0)),
        meter_at_service=meter, recorded_by_name=actor_name, completed_on=on)
    if kind == "Preventive":
        # The same reset the scheduled-service step makes, with the same checks.
        s.next_service_meter, s.next_service_on = record_service_done(a, on, meter)
    elif meter is not None and meter > (a.meter_reading or 0):
        a.meter_reading = float(meter)
    db.add(s)
    if kind == "Breakdown" and body.out_of_service:
        a.status = "Under repair"
    db.commit()
    return {"ok": True, "asset": asset_dict(db, a),
            "message": "%s %s recorded%s." % (a.code, kind.lower(),
                                              ", off work until it is repaired" if a.status == "Under repair" else "")}


@router.post("/api/assets/{asset_id}/service-complete")
def complete_scheduled_service(asset_id: int, body: ServiceDoneIn, request: Request, db: Session = Depends(get_db)):
    """The scheduled service, done: it goes into the history, and the clock starts again from it.
    A preventive job already open for the machine is the one completed - not a second record beside it."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, asset_id)
    if a.is_archived or a.status in ("Disposed", "Returned"):
        raise HTTPException(409, "%s is %s." % (a.code, "archived" if a.is_archived else a.status.lower()))
    if interval_type(a) == "None":
        raise HTTPException(409, "%s has no service schedule. Set one on the machine first." % a.code)
    if not (body.work_performed or "").strip():
        raise HTTPException(400, "Say what was done.")
    if (body.parts_cost or 0) < 0 or (body.labour_cost or 0) < 0:
        raise HTTPException(400, "A cost cannot be negative.")
    before = schedule_snapshot(a)
    on = (body.completed_on or date.today().isoformat())[:10]
    nm, nd = record_service_done(a, on, body.meter_at_service, body.next_service_meter, (body.next_service_on or "").strip())
    S = models.DBAssetService
    s = db.query(S).filter(S.asset_id == a.id, S.kind == "Preventive",
                           S.status.in_(("Requested", "Scheduled", "In progress"))).order_by(S.id).first()
    if s is None:
        s = S(client_id=client.id, asset_id=a.id, job_id=a.current_job_id, kind="Preventive", number=number_for(db, S, client.id, "MNT"),
              reported_on=on, description="Scheduled service", recorded_by_name=actor_name)
        db.add(s)
    s.invoice_no = check_invoice_unique(db, client.id, body.invoice_no, ("maintenance", s.id) if s.id else None)
    s.status, s.service_on, s.completed_on = "Completed", on, on
    s.meter_at_service = body.meter_at_service
    s.work_performed = body.work_performed.strip()
    s.parts_used = (body.parts_used or "").strip()
    s.vendor = s.mechanic = (body.vendor or s.mechanic or "").strip()[:120]
    s.parts_cost, s.labour_cost = money(body.parts_cost or 0), money(body.labour_cost or 0)
    s.total_cost = money(s.parts_cost + s.labour_cost)
    s.next_service_meter, s.next_service_on = nm, nd
    db.flush()
    unit = UNIT_WORD.get(a.meter_unit or "Hours", "hours")
    nxt = " or ".join(x for x in (("%g %s" % (nm, unit)) if nm is not None else "", nd or "") if x)
    after = schedule_snapshot(a)
    changed = {k: (before[k], after[k]) for k in after if before[k] != after[k]}
    at = (" at %g %s" % (body.meter_at_service, unit)) if body.meter_at_service is not None else ""
    log_audit(db, client.id, "plant.service.completed", "equipment", a.id, a.code,
              "%s on %s%s, cost %s; %s" % (s.number, on, at, inr(s.total_cost), describe_changes(changed)),
              request=request, user_name=actor_name)
    db.commit()
    return {"ok": True, "asset": asset_dict(db, a), "id": s.id,
            "message": "%s service recorded. Next due %s." % (a.code, nxt or "when the schedule is set")}


@router.post("/api/assets/{asset_id}/back-in-service")
def asset_back(asset_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "site.record")
    a = asset_or_404(db, client.id, asset_id)
    if a.status not in ("Under repair", "Breakdown"):
        raise HTTPException(409, "%s is not under repair." % a.code)
    if db.query(models.DBAssetService).filter(models.DBAssetService.asset_id == a.id, models.DBAssetService.status == "In progress").first():
        raise HTTPException(409, "%s has maintenance in progress - complete that job to put it back." % a.code)
    a.status = "Deployed" if a.current_job_id else "Available"
    db.commit()
    return {"ok": True, "asset": asset_dict(db, a), "message": "%s back at work." % a.code}


@router.post("/api/assets/{asset_id}/dispose")
def dispose_asset(asset_id: int, request: Request, body: dict = None, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, ("stores.manage", "workorders.manage"))
    a = asset_or_404(db, client.id, asset_id)
    if a.current_job_id:
        raise HTTPException(409, "%s is still on a site. Bring it back to the yard first." % a.code)
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Say why - sold, scrapped, returned to the hirer.")
    a.status = "Disposed"
    a.notes = ((a.notes or "") + "\nDisposed %s: %s" % (date.today().isoformat(), reason)).strip()
    b = asset_book_or_none(db, client.id, a.id)
    if b and not b.disposed_on:
        b.disposed_on = date.today().isoformat()
        b.disposal_value = money((body or {}).get("value") or 0)
        b.disposal_note = reason[:300]
    db.commit()
    return {"ok": True, "message": "%s disposed of." % a.code}


@router.get("/api/fixed-assets")
def fixed_asset_register(request: Request, fy: str = "", db: Session = Depends(get_db)):
    """The fixed asset register for one financial year: every owned asset
    with a book, what it opened at, what was added, the year's depreciation,
    what went, and what it closes at."""
    client = require_items_access(request, db, "bills.view_all")
    year = fy_start_year(fy) if fy else fy_start_year(date.today())
    if year is None:
        raise HTTPException(400, "Financial year should read like 2026-27.")
    # The names are read before the commit: after it each block would be read back from the database one by one.
    block_names = [b.name for b in ensure_tax_blocks(db, client.id)]
    db.commit()
    books = {b.asset_id: b for b in db.query(models.DBAssetBook).filter(
        models.DBAssetBook.client_id == client.id).all()}
    rows, unset = [], []
    first = year
    for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).order_by(
            models.DBAsset.code).all():
        if (a.ownership or "Owned") != "Owned":
            continue
        b = books.get(a.id)
        if not b:
            d = default_book(a)
            unset.append({"asset_id": a.id, "code": a.code or "", "name": a.name or "",
                          "category": a.category or "", "status": a.status or "",
                          "suggest": d, "ready": bool(d["cost"] > 0 and d["put_to_use_on"])})
            continue
        d = book_dict(b, a, year)
        start = fy_start_year(b.opening_fy) if b.opening_fy else fy_start_year(b.put_to_use_on)
        if start is not None:
            first = min(first, start)
        if d["in_year"]:
            rows.append(d)
    ys = [r["year"] for r in rows]
    return {
        "fy": fy_label(year), "fys": [fy_label(y) for y in range(max(first, year - 15), fy_start_year(date.today()) + 2)][::-1],
        "assets": rows, "not_set_up": unset,
        "methods": list(BOOK_METHODS), "blocks": block_names,
        "defaults": {k: {"life_years": v[0], "tax_block": v[1]} for k, v in ASSET_BOOK_DEFAULTS.items()},
        "totals": {
            "cost": money(sum(r["cost"] for r in rows)),
            "opening": money(sum(y["opening"] for y in ys)),
            "added": money(sum(y["added"] for y in ys)),
            "depreciation": money(sum(y["depreciation"] for y in ys)),
            "disposed": money(sum(y["disposal_value"] for y in ys)),
            "gain": money(sum(y["gain"] for y in ys)),
            "closing": money(sum(y["closing"] for y in ys)),
            "accumulated": money(sum(y["accumulated"] for y in ys if not y["disposed"])),
            "assets": len(rows), "not_set_up": len(unset),
        },
    }


@router.put("/api/fixed-assets/{asset_id}/book")
def save_asset_book(asset_id: int, body: AssetBookIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "accounts.manage")
    a = asset_or_404(db, client.id, asset_id)
    if (a.ownership or "Owned") != "Owned":
        raise HTTPException(409, "%s is hired in. Only what the business owns is depreciated." % a.code)
    b = asset_book_or_none(db, client.id, a.id)
    if b and b.disposed_on:
        raise HTTPException(409, "%s was disposed of on %s; its book is closed." % (a.code, b.disposed_on))
    new = b is None
    if new:
        b = models.DBAssetBook(client_id=client.id, asset_id=a.id)
        db.add(b)
    _apply_book(db, client.id, a, b, body)
    log_audit(db, client.id, "asset_book_" + ("set" if new else "changed"), "asset", a.id, a.code,
              "%s %s yrs, cost %s" % (b.method, b.life_years, inr(b.cost)), request)
    db.commit()
    return {"book": book_dict(b, a, fy_start_year(date.today())),
            "message": "%s: %s over %g years from %s." % (a.code, b.method, b.life_years, b.put_to_use_on)}


@router.post("/api/fixed-assets/set-up-all")
def set_up_all_books(request: Request, db: Session = Depends(get_db)):
    """Every owned asset with a purchase value and date gets a book on its
    category's defaults. Anything missing either is left to be done by hand."""
    client, _, _ = wo_actor(request, db, "accounts.manage")
    have = {b.asset_id for b in db.query(models.DBAssetBook).filter(
        models.DBAssetBook.client_id == client.id).all()}
    made, skipped = [], []
    for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all():
        if (a.ownership or "Owned") != "Owned" or a.id in have:
            continue
        if not (a.purchase_value or 0) > 0 or not _parse_date(a.purchase_date):
            skipped.append(a.code)
            continue
        b = models.DBAssetBook(client_id=client.id, asset_id=a.id)
        db.add(b)
        _apply_book(db, client.id, a, b, AssetBookIn())
        made.append(a.code)
    log_audit(db, client.id, "asset_books_set_up", "asset", 0, "", "%d set up" % len(made), request)
    db.commit()
    return {"made": made, "skipped": skipped,
            "message": "%d asset%s set up on the usual lives%s." % (
                len(made), "" if len(made) == 1 else "s",
                ("; %d need a purchase value and date first" % len(skipped)) if skipped else "")}


@router.get("/api/fixed-assets/{asset_id}/schedule")
def asset_book_schedule(asset_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    a = asset_or_404(db, client.id, asset_id)
    b = asset_book_or_none(db, client.id, a.id)
    if not b:
        raise HTTPException(404, "%s has no book yet." % a.code)
    upto = fy_start_year(date.today())
    if b.disposed_on:
        upto = fy_start_year(b.disposed_on) or upto
    return {"book": book_dict(b, a, upto), "rows": book_schedule(b, upto)}


@router.post("/api/fixed-assets/{asset_id}/dispose")
def dispose_booked_asset(asset_id: int, body: AssetDisposalIn, request: Request,
                         db: Session = Depends(get_db)):
    """Sold or scrapped: depreciation stops that day, and what it fetched
    against what the books still carried is the gain or the loss."""
    client, _, actor_name = wo_actor(request, db, "accounts.manage")
    a = asset_or_404(db, client.id, asset_id)
    b = asset_book_or_none(db, client.id, a.id)
    if not b:
        raise HTTPException(404, "%s has no book yet. Set it up first, so the sale is set against "
                                 "what it was worth." % a.code)
    if b.disposed_on:
        raise HTTPException(409, "%s was already disposed of on %s." % (a.code, b.disposed_on))
    if a.current_job_id:
        raise HTTPException(409, "%s is still on a site. Bring it back to the yard first." % a.code)
    on = _parse_date(body.disposed_on)
    if not on:
        raise HTTPException(400, "When did it go? (YYYY-MM-DD)")
    if on < _parse_date(b.put_to_use_on):
        raise HTTPException(400, "It cannot go before it was put to use (%s)." % b.put_to_use_on)
    if on > date.today():
        raise HTTPException(400, "That date has not come yet.")
    value = money(body.disposal_value or 0)
    if value < 0:
        raise HTTPException(400, "What it fetched cannot be less than nothing.")
    b.disposed_on, b.disposal_value = on.isoformat(), value
    b.disposal_note = (body.note or "").strip()[:300]
    a.status = "Disposed"
    a.notes = ((a.notes or "") + "\nDisposed %s for %s%s" % (
        on.isoformat(), inr(value), (": " + b.disposal_note) if b.disposal_note else "")).strip()
    rows = book_schedule(b, fy_start_year(on))
    last = rows[-1] if rows else {"book_value_at_sale": 0.0, "gain": value}
    log_audit(db, client.id, "asset_disposed", "asset", a.id, a.code,
              "for %s, book %s" % (inr(value), inr(last.get("book_value_at_sale", 0))), request)
    db.commit()
    gain = last.get("gain", 0.0)
    return {"book": book_dict(b, a, fy_start_year(on)), "book_value": last.get("book_value_at_sale", 0.0),
            "gain": gain,
            "message": "%s disposed of for %s against a book value of %s: a %s of %s." % (
                a.code, inr(value), inr(last.get("book_value_at_sale", 0.0)),
                "profit" if gain >= 0 else "loss", inr(abs(gain)))}


@router.get("/api/fixed-assets/tax-blocks")
def tax_blocks(request: Request, fy: str = "", db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    year = fy_start_year(fy) if fy else fy_start_year(date.today())
    if year is None:
        raise HTTPException(400, "Financial year should read like 2026-27.")
    rows = tax_block_schedule(db, client.id, year)
    db.commit()
    return {"fy": fy_label(year), "blocks": rows, "totals": {
        k: money(sum(r[k] for r in rows)) for k in
        ("opening", "added_full", "added_half", "deleted", "depreciation", "closing",
         "short_term_gain", "short_term_loss")}}


@router.put("/api/fixed-assets/tax-blocks/{block_id}")
def save_tax_block(block_id: int, body: TaxBlockIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "accounts.manage")
    blk = db.query(models.DBTaxBlock).filter(models.DBTaxBlock.id == block_id,
                                             models.DBTaxBlock.client_id == client.id).first()
    if not blk:
        raise HTTPException(404, "Block not found")
    if body.rate is not None:
        if not 0 <= body.rate <= 100:
            raise HTTPException(400, "A rate is a percentage.")
        blk.rate = float(body.rate)
    if body.opening_fy:
        y = fy_start_year(body.opening_fy)
        if y is None:
            raise HTTPException(400, "Opening year should read like 2025-26.")
        if (body.opening_wdv or 0) < 0:
            raise HTTPException(400, "The written-down value cannot be below nought.")
        blk.opening_fy, blk.opening_wdv = fy_label(y), money(body.opening_wdv or 0)
    else:
        blk.opening_fy, blk.opening_wdv = "", 0.0
    log_audit(db, client.id, "tax_block_changed", "tax_block", blk.id, blk.name,
              "%s%% from %s at %s" % (blk.rate, blk.opening_fy or "purchase", inr(blk.opening_wdv)), request)
    db.commit()
    return {"ok": True, "message": "%s saved." % blk.name}


@router.get("/api/fixed-assets.xlsx")
def fixed_assets_export(request: Request, fy: str = "", db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    data = fixed_asset_register(request, fy, db)
    rows = [(r["code"], r["name"], r["category"], r["put_to_use_on"], r["cost"],
             "%s %s%%" % (r["method"], r["rate_percent"]) if r["method"] == "WDV" else "SLM %g yrs" % r["life_years"],
             r["year"]["opening"], r["year"]["added"], r["year"]["depreciation"],
             r["year"]["disposal_value"], r["year"]["gain"], r["year"]["closing"], r["year"]["accumulated"])
            for r in data["assets"]]
    t = data["totals"]
    return sheet_response(
        ("Code", "Asset", "Category", "In use from", "Cost", "Method", "Opening", "Added",
         "Depreciation", "Sold for", "Profit / loss on sale", "Closing", "Accumulated"),
        rows, "fixed_assets_%s.xlsx" % data["fy"],
        preamble=[("FIXED ASSET REGISTER", client.company_name or ""),
                  ("Financial year", data["fy"]), ("Depreciation as per the company's books",), ()],
        closing=[(), ("Total", "", "", "", t["cost"], "", t["opening"], t["added"], t["depreciation"],
                      t["disposed"], t["gain"], t["closing"])])


@router.get("/api/fixed-assets/tax-blocks.xlsx")
def tax_blocks_export(request: Request, fy: str = "", db: Session = Depends(get_db)):
    client = require_items_access(request, db, "bills.view_all")
    data = tax_blocks(request, fy, db)
    rows = [(r["block"], r["rate"], r["opening"], r["added_full"], r["added_half"], r["deleted"],
             r["depreciation"], r["closing"], r["short_term_gain"], r["short_term_loss"])
            for r in data["blocks"]]
    t = data["totals"]
    return sheet_response(
        ("Block", "Rate %", "Opening WDV", "Added, used 180 days or more", "Added, used under 180 days",
         "Sold", "Depreciation", "Closing WDV", "Short-term gain", "Short-term loss"),
        rows, "tax_depreciation_%s.xlsx" % data["fy"],
        preamble=[("DEPRECIATION AS PER THE INCOME-TAX ACT", client.company_name or ""),
                  ("Financial year", data["fy"]), ()],
        closing=[(), ("Total", "", t["opening"], t["added_full"], t["added_half"], t["deleted"],
                      t["depreciation"], t["closing"], t["short_term_gain"], t["short_term_loss"])])
