"""Recurring payments: set up once, raised for approval every month."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.auth import require_items_access, wo_actor
from app.core.currency import inr, money
from app.db import get_db, get_read_db
from app.models.recurring_payments import DBRecurringPayment, DBRecurringPaymentRun
from app.schemas.recurring_payments import RecurringPaymentIn
from app.services.recurring_payments import _day, apply_recurring, first_due, list_recurring, raise_due, recurring_or_404, schedule

router = APIRouter()
WRITE = "accounts.manage"


def _one(db, t):
    return next(r for r in list_recurring(db, t.client_id) if r["id"] == t.id)


def _raised(made):
    if not made:
        return ""
    return " Its request, %s, is raised now." % made[0].number if len(made) == 1 else " Requests %s are raised now." % ", ".join(r.number for r in made)


@router.get("/api/recurring-payments")
def recurring_payments(request: Request, db: Session = Depends(get_read_db)):
    """Every recurring payment, soonest due first, with where its last request stands, and what they come to a month."""
    client = require_items_access(request, db, "bills.view_all")
    rows = list_recurring(db, client.id)
    live = [r for r in rows if r["status"] == "Active"]
    return {"payments": rows, "summary": {
        "active": len(live), "paused": len([r for r in rows if r["status"] == "Paused"]), "ended": len([r for r in rows if r["status"] == "Ended"]),
        "monthly": money(sum(r["amount"] for r in live)), "next_due": min([r["next_due"] for r in live if r["next_due"]] or [""]),
        "failing": len([r for r in rows if r["last_error"]])}}


@router.post("/api/recurring-payments")
def add_recurring(body: RecurringPaymentIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    t = DBRecurringPayment(client_id=client.id)
    apply_recurring(db, client.id, t, body, who, creating=True)
    schedule(t)
    db.add(t)
    db.flush()
    made = raise_due(db, t, date.today())           # due today: raised now, not a day late
    log_audit(db, client.id, "recurring_payment_added", "recurring_payment", t.id, t.payee, "%s %s on day %d" % (t.head, inr(t.amount), t.day_of_month),
              request=request, user_name=who)
    db.commit()
    return {"ok": True, "payment": _one(db, t), "message": "%s set up: %s on day %d of every month, next %s.%s" % (
        t.payee, inr(t.amount), t.day_of_month, _day(t.next_due).strftime("%d %b %Y") if t.next_due else "-", _raised(made))}


@router.put("/api/recurring-payments/{rid}")
def change_recurring(rid: int, body: RecurringPaymentIn, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    t = recurring_or_404(db, client.id, rid)
    if apply_recurring(db, client.id, t, body, who, creating=False) and t.is_active:
        schedule(t)
    made = raise_due(db, t, date.today())
    log_audit(db, client.id, "recurring_payment_changed", "recurring_payment", t.id, t.payee, "%s %s on day %d" % (t.head, inr(t.amount), t.day_of_month),
              request=request, user_name=who)
    db.commit()
    return {"ok": True, "payment": _one(db, t), "message": "%s saved.%s" % (t.payee, _raised(made))}


@router.post("/api/recurring-payments/{rid}/pause")
def pause_recurring(rid: int, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    t = recurring_or_404(db, client.id, rid)
    if not t.next_due:
        raise HTTPException(409, "%s has ended." % t.payee)
    t.is_active = False
    log_audit(db, client.id, "recurring_payment_paused", "recurring_payment", t.id, t.payee, "", request=request, user_name=who)
    db.commit()
    return {"ok": True, "payment": _one(db, t), "message": "%s paused. Nothing is raised until it is resumed." % t.payee}


@router.post("/api/recurring-payments/{rid}/resume")
def resume_recurring(rid: int, request: Request, db: Session = Depends(get_db)):
    """Back on, from the next day it falls due: the months it was paused are not raised."""
    client, _, who = wo_actor(request, db, WRITE)
    t = recurring_or_404(db, client.id, rid)
    due = first_due(t.day_of_month, date.today())
    end = _day(t.end_date)
    if end and due > end:
        raise HTTPException(409, "%s ends on %s, so there is nothing left to raise. Change the last date to carry on." % (t.payee, end.strftime("%d %b %Y")))
    t.is_active, t.next_due = True, due.isoformat()
    made = raise_due(db, t, date.today())
    log_audit(db, client.id, "recurring_payment_resumed", "recurring_payment", t.id, t.payee, "next %s" % t.next_due, request=request, user_name=who)
    db.commit()
    return {"ok": True, "payment": _one(db, t), "message": "%s resumed: next %s.%s" % (t.payee, _day(t.next_due).strftime("%d %b %Y"), _raised(made))}


@router.delete("/api/recurring-payments/{rid}")
def delete_recurring(rid: int, request: Request, db: Session = Depends(get_db)):
    """Takes the schedule away. Requests it has already raised stay, and are approved or refused as they are."""
    client, _, who = wo_actor(request, db, WRITE)
    t = recurring_or_404(db, client.id, rid)
    payee = t.payee
    log_audit(db, client.id, "recurring_payment_deleted", "recurring_payment", t.id, payee, "%s %s" % (t.head, inr(t.amount)), request=request, user_name=who)
    db.query(DBRecurringPaymentRun).filter(DBRecurringPaymentRun.recurring_id == t.id).delete(synchronize_session=False)
    db.delete(t)
    db.commit()
    return {"ok": True, "message": "%s taken off the list. Requests already raised are still in Payment Approvals." % payee}
