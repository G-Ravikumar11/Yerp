"""Shuttering and scaffolding hired for a project: what came in, what went back, and what it cost.

Hire is charged a return at a time: the quantity that left the site, at the agreed day rate, for the days it was out. What
is still out runs up day by day and is shown as accrued. A piece lost is charged once, at the replacement cost, and its
hire stops on the day it is written off. Who may do what is checked here:
  reading                       anyone signed in to the company
  a hire                        stores.manage or workorders.manage
  a return                      those, or site.record
  a payment                     those, accounts.manage or bills.pay
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from app import models
from app.core.audit import log_audit
from app.core.auth import require_erp_read, wo_actor
from app.core.currency import money
from app.core.dates import _parse_date
from app.core.sheets import sheet_response
from app.db import get_db, get_read_db
from app.services.plant import clean_day, number_for, today
from app.services.plant_checks import jobs_of, job_label

router = APIRouter()
KINDS = ("Shuttering", "Scaffolding")
MANAGE = ("stores.manage", "workorders.manage")
QTY_ROUND = 3


class HireIn(BaseModel):
    job_id: int
    kind: str
    provider_id: int
    description: str = ""
    quantity: float
    uom: str = "Sqm"
    start_date: str = ""
    expected_return: str = ""
    daily_rate: float
    replacement_cost: float = 0
    remarks: Optional[str] = ""


class ReturnIn(BaseModel):
    return_key: str                             # one per return form: saving it twice records it once
    returned_on: str = ""
    returned_qty: float = 0
    damaged_qty: float = 0
    lost_qty: float = 0
    damage_charge: float = 0
    remarks: Optional[str] = ""
    preview: bool = False                       # work out the charges and save nothing


class HirePaymentIn(BaseModel):
    amount: float
    paid_on: str = ""
    reference: Optional[str] = ""


def billing_rule(db, client_id):
    """Whether the day it went back is a billed day: "inclusive" (the default) or "exclusive"."""
    row = db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id, models.DBSettings.key == "formwork_billing_days").first()
    return "exclusive" if row and row.value == "exclusive" else "inclusive"


def billable_days(start, end, rule):
    """The days a piece was out, by the company's rule. Never under one: hired for a day is a day."""
    days = (_parse_date(end) - _parse_date(start)).days + (1 if rule == "inclusive" else 0)
    return max(1, days)


def hire_state(h, returns, payments, rule, on=None):
    """Everything worked out from the stored hire and its returns."""
    on = on or today()
    back = sum(r.returned_qty + r.damaged_qty + r.lost_qty for r in returns)
    out = round(h.quantity - back, QTY_ROUND)
    charged = sum(r.hire_charge for r in returns)
    loss, damage = sum(r.loss_charge for r in returns), sum(r.damage_charge for r in returns)
    accrued = money(out * h.daily_rate * billable_days(h.start_date, max(on, h.start_date), rule)) if out > 0 else 0.0
    paid = sum(p.amount for p in payments)
    overdue = out > 0 and bool(h.expected_return) and h.expected_return < on
    status = "Fully returned" if out <= 0 else "Overdue" if overdue else "Partially returned" if returns else "On hire"
    total = money(charged + accrued)
    return {"out": out, "returned": round(sum(r.returned_qty for r in returns), QTY_ROUND), "damaged": round(sum(r.damaged_qty for r in returns), QTY_ROUND),
            "lost": round(sum(r.lost_qty for r in returns), QTY_ROUND), "hire_charged": money(charged), "accrued": accrued, "total_hire": total, "loss_charge": money(loss),
            "damage_charge": money(damage), "payable": money(total + loss + damage), "paid": money(paid), "balance": money(total + loss + damage - paid), "status": status,
            "actual_return": max((r.returned_on for r in returns), default="") if out <= 0 else ""}


def _children(db, model, client_id):
    by = {}
    for x in db.query(model).filter(model.client_id == client_id).order_by(model.id).all():
        by.setdefault(x.hire_id, []).append(x)
    return by


def hire_rows(db, client_id):
    """[(hire, returns, payments, state)] for the company."""
    rule = billing_rule(db, client_id)
    returns = _children(db, models.DBFormworkReturn, client_id)
    payments = _children(db, models.DBFormworkPayment, client_id)
    return [(h, returns.get(h.id, []), payments.get(h.id, []), hire_state(h, returns.get(h.id, []), payments.get(h.id, []), rule))
            for h in db.query(models.DBFormworkHire).filter(models.DBFormworkHire.client_id == client_id).order_by(models.DBFormworkHire.id.desc()).all()]


def hire_dict(h, returns, payments, s, jobs, providers):
    return {"id": h.id, "number": h.number, "job_id": h.job_id, "project": job_label(jobs, h.job_id), "kind": h.kind, "provider_id": h.provider_id, "supplier": providers.get(h.provider_id, ""),
            "description": h.description or "", "quantity": h.quantity, "uom": h.uom or "", "start_date": h.start_date, "expected_return": h.expected_return or "",
            "daily_rate": h.daily_rate, "replacement_cost": h.replacement_cost or 0, "remarks": h.remarks or "", **s,
            "returns": [{"id": r.id, "returned_on": r.returned_on, "returned_qty": r.returned_qty, "damaged_qty": r.damaged_qty, "lost_qty": r.lost_qty, "billable_days": r.billable_days,
                         "hire_charge": r.hire_charge, "loss_charge": r.loss_charge, "damage_charge": r.damage_charge, "remarks": r.remarks or "", "by": r.recorded_by or ""} for r in returns],
            "payments": [{"id": p.id, "paid_on": p.paid_on, "amount": p.amount, "reference": p.reference or "", "by": p.recorded_by or ""} for p in payments]}


def _names(db, client_id):
    return {p.id: p.name for p in db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.client_id == client_id).all()}


@router.get("/api/plant/formwork")
def list_hires(request: Request, job_id: int = 0, kind: str = "", status: str = "", db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    jobs, providers = jobs_of(db, client.id), _names(db, client.id)
    rows = [hire_dict(*r, jobs, providers) for r in hire_rows(db, client.id)]
    if job_id:
        rows = [r for r in rows if r["job_id"] == job_id]
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    counts = {k: len([r for r in rows if r["status"] == k]) for k in ("On hire", "Partially returned", "Fully returned", "Overdue")}
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"hires": rows, "counts": counts, "kinds": list(KINDS), "billing_rule": billing_rule(db, client.id)}


def _check(db, client_id, body):
    if body.kind not in KINDS:
        raise HTTPException(400, "Shuttering or scaffolding.")
    if not db.query(models.DBJob).filter(models.DBJob.id == body.job_id, models.DBJob.client_id == client_id).first():
        raise HTTPException(400, "Choose the project.")
    if not db.query(models.DBPlantRentalProvider).filter(models.DBPlantRentalProvider.id == body.provider_id, models.DBPlantRentalProvider.client_id == client_id).first():
        raise HTTPException(400, "Choose the supplier.")
    if not (body.description or "").strip():
        raise HTTPException(400, "Describe what is hired.")
    if not body.quantity > 0:
        raise HTTPException(400, "The quantity hired.")
    if not body.daily_rate > 0:
        raise HTTPException(400, "The daily hire rate.")
    if (body.replacement_cost or 0) < 0:
        raise HTTPException(400, "The replacement cost cannot be negative.")
    start = clean_day(body.start_date, "hire start date", required=True)
    ret = clean_day(body.expected_return, "expected return date")
    if ret and ret < start:
        raise HTTPException(400, "It cannot be due back before it arrives.")
    return start, ret


@router.post("/api/plant/formwork")
def create_hire(body: HireIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE)
    start, ret = _check(db, client.id, body)
    H = models.DBFormworkHire
    h = H(client_id=client.id, number=number_for(db, H, client.id, "FWH"), job_id=body.job_id, kind=body.kind, provider_id=body.provider_id, description=body.description.strip()[:300],
          quantity=round(body.quantity, QTY_ROUND), uom=(body.uom or "").strip()[:20], start_date=start, expected_return=ret, daily_rate=body.daily_rate, replacement_cost=body.replacement_cost or 0,
          remarks=(body.remarks or "").strip(), created_by=actor)
    db.add(h)
    db.flush()
    log_audit(db, client.id, "plant.formwork.hired", entity_type="formwork_hire", entity_id=h.id, entity_name=h.number, details="%s %g %s at %g a day" % (h.kind, h.quantity, h.uom, h.daily_rate), request=request, user_name=actor)
    db.commit()
    return {"ok": True, "id": h.id, "message": "%s recorded." % h.number}


def _hire(db, client_id, hid, lock=False):
    q = db.query(models.DBFormworkHire).filter(models.DBFormworkHire.id == hid, models.DBFormworkHire.client_id == client_id)
    h = (q.with_for_update() if lock else q).first()
    if not h:
        raise HTTPException(404, "Hire not found")
    return h


@router.put("/api/plant/formwork/{hid}")
def update_hire(hid: int, body: HireIn, request: Request, db: Session = Depends(get_db)):
    """Terms can be put right until the first return: after that the charges already worked out rest on them."""
    client, _, actor = wo_actor(request, db, MANAGE)
    h = _hire(db, client.id, hid, lock=True)
    if db.query(models.DBFormworkReturn).filter(models.DBFormworkReturn.hire_id == h.id).first():
        raise HTTPException(409, "%s has returns against it, so its terms can no longer change." % h.number)
    start, ret = _check(db, client.id, body)
    before = "%g at %g, from %s" % (h.quantity, h.daily_rate, h.start_date)
    h.job_id, h.kind, h.provider_id, h.description, h.quantity, h.uom = body.job_id, body.kind, body.provider_id, body.description.strip()[:300], round(body.quantity, QTY_ROUND), (body.uom or "").strip()[:20]
    h.start_date, h.expected_return, h.daily_rate, h.replacement_cost, h.remarks = start, ret, body.daily_rate, body.replacement_cost or 0, (body.remarks or "").strip()
    log_audit(db, client.id, "plant.formwork.updated", entity_type="formwork_hire", entity_id=h.id, entity_name=h.number, details="Was %s" % before, request=request, user_name=actor)
    db.commit()
    return {"ok": True, "message": "%s saved." % h.number}


@router.post("/api/plant/formwork/{hid}/returns")
def record_return(hid: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    """What came back, what came back damaged and what is gone. The row lock and the check are one step, so two people
    cannot return the same pieces; the same form saved twice is recorded once."""
    client, _, actor = wo_actor(request, db, MANAGE + ("site.record",))
    h = _hire(db, client.id, hid, lock=True)
    R = models.DBFormworkReturn
    key = (body.return_key or "").strip()[:80]
    if not key:
        raise HTTPException(400, "The return has no reference. Reopen the form.")
    if db.query(R).filter(R.client_id == client.id, R.return_key == key).first():
        raise HTTPException(409, "This return has already been recorded.")
    for what, v in (("returned", body.returned_qty), ("damaged", body.damaged_qty), ("lost", body.lost_qty), ("damage charge", body.damage_charge)):
        if (v or 0) < 0:
            raise HTTPException(400, "The %s cannot be negative." % what)
    qty = round((body.returned_qty or 0) + (body.damaged_qty or 0) + (body.lost_qty or 0), QTY_ROUND)
    if qty <= 0:
        raise HTTPException(400, "Enter what came back, what is damaged or what is lost.")
    if (body.damage_charge or 0) > 0 and not (body.damaged_qty or 0) > 0:
        raise HTTPException(400, "A damage charge goes with a damaged quantity.")
    on = clean_day(body.returned_on, "return date") or today()
    if on < h.start_date:
        raise HTTPException(400, "It cannot go back before it arrived (%s)." % h.start_date)
    if on > today():
        raise HTTPException(400, "Record the return on the day it goes back.")
    earlier = db.query(R).filter(R.hire_id == h.id).all()
    out = round(h.quantity - sum(r.returned_qty + r.damaged_qty + r.lost_qty for r in earlier), QTY_ROUND)
    if qty > out + 0.0005:
        raise HTTPException(409, "Only %g %s is still out." % (out, h.uom))
    days = billable_days(h.start_date, on, billing_rule(db, client.id))
    r = R(client_id=client.id, hire_id=h.id, return_key=key, returned_on=on, returned_qty=body.returned_qty or 0, damaged_qty=body.damaged_qty or 0, lost_qty=body.lost_qty or 0, billable_days=days,
          hire_charge=money(qty * h.daily_rate * days), loss_charge=money((body.lost_qty or 0) * (h.replacement_cost or 0)), damage_charge=money(body.damage_charge or 0),
          remarks=(body.remarks or "").strip(), recorded_by=actor)
    payable = money(r.hire_charge + r.loss_charge + r.damage_charge)
    if body.preview:
        return {"hire_charge": r.hire_charge, "loss_charge": r.loss_charge, "damage_charge": r.damage_charge, "billable_days": days, "payable": payable}
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This return has already been recorded.")
    log_audit(db, client.id, "plant.formwork.returned", entity_type="formwork_hire", entity_id=h.id, entity_name=h.number,
              details="%s: back %g, damaged %g, lost %g; hire %s for %d days, loss %s, damage %s" % (on, r.returned_qty, r.damaged_qty, r.lost_qty, r.hire_charge, days, r.loss_charge, r.damage_charge), request=request, user_name=actor)
    db.commit()
    return {"ok": True, "hire_charge": r.hire_charge, "loss_charge": r.loss_charge, "damage_charge": r.damage_charge, "billable_days": days, "payable": money(r.hire_charge + r.loss_charge + r.damage_charge),
            "message": "Return recorded: %s payable." % money(r.hire_charge + r.loss_charge + r.damage_charge)}


@router.post("/api/plant/formwork/{hid}/payments")
def record_payment(hid: int, body: HirePaymentIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor = wo_actor(request, db, MANAGE + ("accounts.manage", "bills.pay"))
    h = _hire(db, client.id, hid, lock=True)
    if not body.amount > 0:
        raise HTTPException(400, "The amount paid.")
    on = clean_day(body.paid_on, "payment date") or today()
    p = models.DBFormworkPayment(client_id=client.id, hire_id=h.id, paid_on=on, amount=money(body.amount), reference=(body.reference or "").strip()[:80], recorded_by=actor)
    db.add(p)
    db.flush()
    log_audit(db, client.id, "plant.formwork.paid", entity_type="formwork_hire", entity_id=h.id, entity_name=h.number, details="%s on %s" % (p.amount, on), request=request, user_name=actor)
    db.commit()
    return {"ok": True, "message": "Payment recorded."}


def report_of(db, client_id):
    jobs, providers = jobs_of(db, client_id), _names(db, client_id)
    projects, vendors, lost = {}, {}, []
    for h, returns, _, s in hire_rows(db, client_id):
        p = projects.setdefault(h.job_id, {"job_id": h.job_id, "project": job_label(jobs, h.job_id), "shuttering_qty": 0.0, "scaffolding_qty": 0.0, "daily_rental": 0.0, "outstanding_qty": 0.0,
                                           "total_hire": 0.0, "loss_charge": 0.0, "damage_charge": 0.0, "total_cost": 0.0})
        p["shuttering_qty" if h.kind == "Shuttering" else "scaffolding_qty"] += h.quantity
        p["outstanding_qty"] += max(0.0, s["out"])
        p["daily_rental"] += max(0.0, s["out"]) * h.daily_rate
        v = vendors.setdefault(h.provider_id, {"supplier": providers.get(h.provider_id, ""), "total_hire": 0.0, "loss_charge": 0.0, "damage_charge": 0.0, "total_cost": 0.0, "paid": 0.0})
        for row in (p, v):
            row["total_hire"] += s["total_hire"]
            row["loss_charge"] += s["loss_charge"]
            row["damage_charge"] += s["damage_charge"]
            row["total_cost"] += s["payable"]
        v["paid"] += s["paid"]
        if s["lost"] or s["damaged"]:
            lost.append({"number": h.number, "project": job_label(jobs, h.job_id), "kind": h.kind, "description": h.description or "", "lost": s["lost"], "damaged": s["damaged"], "uom": h.uom or "",
                         "replacement_cost": h.replacement_cost or 0, "loss_charge": s["loss_charge"], "damage_charge": s["damage_charge"]})
    tidy = lambda rows: [{k: (round(x, 2) if isinstance(x, float) else x) for k, x in r.items()} for r in rows]
    return {"projects": tidy(projects.values()), "vendors": tidy(vendors.values()), "lost_damaged": lost}


@router.get("/api/plant/formwork-report")
def hire_report(request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    return report_of(db, client.id)


@router.get("/api/plant/formwork-report.xlsx")
def hire_report_export(request: Request, db: Session = Depends(get_read_db)):
    client = require_erp_read(request, db)
    rows = report_of(db, client.id)["projects"]
    return sheet_response(("Project", "Shuttering hired", "Scaffolding hired", "Daily rental now", "Outstanding", "Hire cost", "Loss charges", "Damage charges", "Total cost"),
                          [(r["project"], r["shuttering_qty"], r["scaffolding_qty"], r["daily_rental"], r["outstanding_qty"], r["total_hire"], r["loss_charge"], r["damage_charge"], r["total_cost"]) for r in rows],
                          "shuttering_scaffolding_hire.xlsx")

