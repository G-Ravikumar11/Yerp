"""Equipment & Plant's own checks: project costs, meter gaps and history, fuel flags, rental bills against their
agreements, and the alerts.

Who may do what - checked here, not on the screen:
  reading                            anyone signed in to the company
  a meter gap, a fuel flag, an alert site.signoff, stores.manage or workorders.manage
  a rental bill that differs         accounts.manage or bills.pay
Every decision is written to the audit trail.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.db import get_db, get_read_db
from app.schemas.plant import AlertReviewIn, FuelFlagReviewIn, GapResolveIn, InvoiceVerifyIn
from app.services.assets import asset_or_404
from app.services.plant import clean_day, now, plant_cost_breakdown, today
from app.services.plant_checks import (
    alert_dict, duplicate_days, fuel_monitor, jobs_of, job_label, meter_gaps, meter_history, rental_rows, review_fuel_flag,
)

router = APIRouter()
REVIEW = ("site.signoff", "stores.manage", "workorders.manage")
FINANCE = ("accounts.manage", "bills.pay")


def audit(db, client, action, kind, rec_id, name, details, actor, request):
    log_audit(db, client.id, action, entity_type=kind, entity_id=rec_id, entity_name=name or "", details=(details or "")[:1000],
              request=request, user_name=actor)


@router.get("/api/plant/project-costs")
def project_plant_costs(request: Request, job_id: int = 0, date_from: str = "", date_to: str = "", db: Session = Depends(get_read_db)):
    """What the machines cost each project, and every line behind the figure with the record it came from."""
    client = require_erp_read(request, db)
    jobs = jobs_of(db, client.id)
    costs = plant_cost_breakdown(db, client.id, date_from[:10], date_to[:10], lines=True)
    rows = [dict(v, project=job_label(jobs, k) or "Not yet charged to a project") for k, v in costs.items() if not job_id or k == job_id]
    return {"projects": sorted(rows, key=lambda r: -r["total"])}


@router.get("/api/plant/logs/duplicates")
def possible_duplicate_days(request: Request, db: Session = Depends(get_read_db)):
    """Days that may be logged twice, for somebody to look at. Nothing is removed by this."""
    client = require_erp_read(request, db)
    return {"days": duplicate_days(db, client.id)}


@router.get("/api/plant/meter-gaps")
def list_meter_gaps(request: Request, asset_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return {"gaps": meter_gaps(db, client.id, asset_id)}


@router.post("/api/plant/meter-gaps/resolve")
def resolve_meter_gap(body: GapResolveIn, request: Request, db: Session = Depends(get_db)):
    """Say why a gap is there (the machine stood in the yard, say). A gap filled with its missing days clears by itself."""
    client, _, actor = wo_actor(request, db, REVIEW)
    a = asset_or_404(db, client.id, body.asset_id)
    note = (body.note or "").strip()
    if not note:
        raise HTTPException(400, "Say what was found - it goes on the record.")
    start, end = clean_day(body.from_date, "gap start", required=True), clean_day(body.to_date, "gap end", required=True)
    if not any(g["from"] == start and g["to"] == end for g in meter_gaps(db, client.id, a.id)):
        raise HTTPException(404, "That gap is not on the record.")
    M = models.DBPlantMeterEvent
    row = db.query(M).filter(M.asset_id == a.id, M.kind == "GapResolved", M.on_date == start, M.to_date == end).first()
    if row:
        row.reason, row.by_name = note[:300], actor
    else:
        db.add(M(client_id=client.id, asset_id=a.id, kind="GapResolved", on_date=start, to_date=end, reason=note[:300], by_name=actor))
    audit(db, client, "plant.meter.gap_resolved", "equipment", a.id, a.code, "%s to %s: %s" % (start, end, note), actor, request)
    db.commit()
    return {"ok": True, "message": "Gap reviewed."}


@router.get("/api/plant/machines/{asset_id}/meter-history")
def machine_meter_history(asset_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    a = asset_or_404(db, client.id, asset_id)
    return {"history": meter_history(db, client.id, a), "gaps": meter_gaps(db, client.id, a.id), "unit": (a.meter_unit or "Hours").lower(), "reading": a.meter_reading or 0}


@router.get("/api/plant/fuel-monitor")
def fuel_consumption(request: Request, date_from: str = "", date_to: str = "", asset_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return fuel_monitor(db, client.id, date_from[:10], date_to[:10], asset_id)


@router.post("/api/plant/fuel-flags/review")
def review_fuel(body: FuelFlagReviewIn, request: Request, db: Session = Depends(get_db)):
    """A flag is a question, not a finding: somebody looks into it and says what they found."""
    client, _, actor = wo_actor(request, db, REVIEW)
    f, r = review_fuel_flag(db, client.id, body, actor)
    audit(db, client, "plant.fuel.flag_reviewed", "plant_fuel", f.id, f.number, "%s: %s. %s" % (body.reason, r.status, r.note), actor, request)
    db.commit()
    return {"ok": True, "message": "%s: %s." % (f.number, r.status.lower())}


@router.get("/api/plant/rental-verification")
def rental_verification(request: Request, month: str = "", rental_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return rental_rows(db, client.id, month[:7], rental_id)


@router.post("/api/plant/rental-invoices/{iid}/verify")
def verify_rental_invoice(iid: int, body: InvoiceVerifyIn, request: Request, db: Session = Depends(get_db)):
    """Finance's decision on a bill. The billed amount is left as it is: expected and actual stay apart."""
    client, _, actor = wo_actor(request, db, FINANCE)
    I = models.DBPlantRentalInvoice
    inv = db.query(I).filter(I.id == iid, I.client_id == client.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if body.decision not in ("approve", "dispute"):
        raise HTTPException(400, "Approve or dispute.")
    note = (body.note or "").strip()
    if body.decision == "dispute" and not note:
        raise HTTPException(400, "Say what is wrong with the bill.")
    row = next((x for x in rental_rows(db, client.id, rental_id=inv.rental_id)["rows"] if x["invoice_id"] == iid), None)
    inv.verification_status = "Approved" if body.decision == "approve" else "Disputed"
    inv.expected_at_review = row["expected"] if row else None
    inv.verified_by, inv.verified_on, inv.verification_note = actor, today(), note[:1000]
    audit(db, client, "plant.rental.invoice_" + inv.verification_status.lower(), "plant_rental", inv.rental_id, inv.invoice_no,
          "Billed %s, expected %s. %s" % (inv.amount, inv.expected_at_review, note), actor, request)
    db.commit()
    return {"ok": True, "message": "Invoice %s %s." % (inv.invoice_no, inv.verification_status.lower())}


@router.get("/api/plant/alerts")
def list_alerts(request: Request, kind: str = "", status: str = "", db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    P = models.DBPlantAlert
    q = db.query(P).filter(P.client_id == client.id)
    if kind:
        q = q.filter(P.kind == kind)
    if status:
        q = q.filter(P.status == status)
    rows = q.order_by(P.id.desc()).limit(500).all()
    assets = {a.id: a for a in db.query(models.DBAsset).filter(models.DBAsset.client_id == client.id).all()}
    return {"alerts": [alert_dict(x, assets) for x in rows],
            "open": db.query(P.id).filter(P.client_id == client.id, P.status == "Open").count()}


@router.post("/api/plant/alerts/{alert_id}/review")
def review_alert(alert_id: int, body: AlertReviewIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, REVIEW + FINANCE)
    P = models.DBPlantAlert
    x = db.query(P).filter(P.id == alert_id, P.client_id == client.id).first()
    if not x:
        raise HTTPException(404, "Alert not found")
    if body.status not in ("Reviewed", "Resolved"):
        raise HTTPException(400, "Reviewed or resolved.")
    x.status, x.reviewed_by, x.reviewed_at, x.review_note = body.status, actor, now(), (body.note or "").strip()[:1000]
    audit(db, client, "plant.alert." + body.status.lower(), "plant_alert", x.id, x.title, x.review_note, actor, request)
    db.commit()
    return {"ok": True, "message": "Alert %s." % body.status.lower()}
