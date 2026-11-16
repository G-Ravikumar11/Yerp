"""Loans and EMIs: entered once with their terms, repaid by instalments paid like any bill."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.core import checks
from app.core.audit import log_audit
from app.core.auth import require_items_access, wo_actor
from app.core.currency import inr, money
from app.db import get_db, get_read_db
from app.models.loans import DBLoanInstalment
from app.schemas.loans import InstalmentIn, LoanIn
from app.schemas.money import MoneyIn
from app.services.loans import (create_loan, disbursed_ids, due_instalments, instalment_dict, instalment_or_404, list_loans, loan_dict, loan_or_404,
                                loans_outstanding)

router = APIRouter()
WRITE = "accounts.manage"


def _detail(db, loan, today=None):
    rows = db.query(DBLoanInstalment).filter(DBLoanInstalment.loan_id == loan.id).order_by(DBLoanInstalment.seq).all()
    return loan_dict(loan, rows, today or date.today(), loan.opening or loan.id in disbursed_ids(db, loan.client_id), detail=True)


@router.get("/api/loans")
def loans(request: Request, db: Session = Depends(get_read_db)):
    """Every loan with what is left on it and its next instalment, and what is due."""
    client = require_items_access(request, db, "bills.view_all")
    today = date.today()
    rows = list_loans(db, client.id, today)
    soon, late = due_instalments(db, client.id, today)

    def total(pairs):
        return money(sum((i.principal or 0) + (i.interest or 0) for _, i in pairs))

    live = [r for r in rows if r["status"] == "ACTIVE"]
    return {"loans": rows, "summary": {
        "outstanding": loans_outstanding(db, client.id), "active": len(live), "closed": len(rows) - len(live),
        "emi_a_month": money(sum(r["emi"] for r in live)), "due_week": len(soon), "due_week_amount": total(soon),
        "overdue": len(late), "overdue_amount": total(late), "interest_paid": money(sum(r["interest_paid"] for r in rows)),
        "interest_to_come": money(sum(r["interest_to_come"] for r in live)),
        "next_due": min([r["next"]["due_on"] for r in live if r["next"]] or [""])}}


@router.get("/api/loans/{loan_id}")
def loan(loan_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, "bills.view_all")
    return _detail(db, loan_or_404(db, client.id, loan_id))


@router.post("/api/loans")
def add_loan(body: LoanIn, request: Request, db: Session = Depends(get_db)):
    """A new loan, with its instalments worked out. When the money has just been received it goes into the bank book as a
    receipt against the loan; one already running before these books began is entered with what was left of it."""
    client, _, who = wo_actor(request, db, WRITE)
    made, rows = create_loan(db, client.id, body, who)
    log_audit(db, client.id, "loan_added", "loan", made.id, made.number, "%s %s: %s over %d instalments at %s%%" % (
        made.lender, made.name, inr(made.principal), len(rows), made.annual_rate), request=request, user_name=who)
    if made.opening:
        db.commit()
    else:
        # The receipt is the ordinary one: the same checks (the books lock, the account) and the same bank book. If it is refused,
        # nothing here is kept: the loan is not left standing with its money unrecorded.
        from app.routers.money import record_money
        record_money(MoneyIn(doc_type="loan_disbursal", doc_id=made.id, amount=made.principal, paid_on=made.taken_on, mode=body.mode or "Bank transfer",
                             reference=body.reference or "", account_id=body.account_id, note=("Loan received: %s %s" % (made.lender, made.name))[:300]),
                     request, db)
    return {"ok": True, "loan": _detail(db, made), "message": "%s entered: %s over %d instalments, EMI %s, first on %s.%s" % (
        made.number, inr(made.principal), len(rows), inr(made.emi), rows[0].due_on,
        "" if made.opening else " The money received is in the bank book.")}


@router.put("/api/loans/{loan_id}")
def change_loan(loan_id: int, body: LoanIn, request: Request, db: Session = Depends(get_db)):
    """Only the note: a loan's terms are what the bank signed. A wrong one is taken away and entered again (before anything is paid)."""
    client, _, who = wo_actor(request, db, WRITE)
    found = loan_or_404(db, client.id, loan_id)
    if body.note is not None:
        found.note = " ".join((body.note or "").split())[:300]
    log_audit(db, client.id, "loan_changed", "loan", found.id, found.number, "note", request=request, user_name=who)
    db.commit()
    return {"ok": True, "loan": _detail(db, found), "message": "%s saved." % found.number}


@router.put("/api/loans/{loan_id}/instalments/{instalment_id}")
def change_instalment(loan_id: int, instalment_id: int, body: InstalmentIn, request: Request, db: Session = Depends(get_db)):
    """Put an instalment right before it is paid: the bank's own split, or the day it moved to. A paid one is never rewritten."""
    client, _, who = wo_actor(request, db, WRITE)
    found = loan_or_404(db, client.id, loan_id)
    i = instalment_or_404(db, client.id, instalment_id)
    if i.loan_id != found.id:
        raise HTTPException(404, "Instalment not found")
    if i.status == "PAID":
        raise HTTPException(409, "%s is paid. Void its payment first if it was entered wrong." % i.number)
    if body.due_on is not None:
        i.due_on = checks.day(body.due_on, "due date", required=True)
    for field, label in (("principal", "principal"), ("interest", "interest")):
        value = getattr(body, field)
        if value is not None:
            setattr(i, field, money(checks.between(value, label, 0, 100_000_000_000, unit="rupees", blank_ok=False)))
    if (i.principal or 0) + (i.interest or 0) <= 0:
        raise HTTPException(400, "An instalment has to be more than nothing.")
    log_audit(db, client.id, "loan_instalment_changed", "loan", found.id, i.number, "%s: principal %s, interest %s, due %s" % (
        found.number, inr(i.principal), inr(i.interest), i.due_on), request=request, user_name=who)
    db.commit()
    return {"ok": True, "instalment": instalment_dict(i, date.today()), "loan": _detail(db, found), "message": "%s saved." % i.number}


@router.delete("/api/loans/{loan_id}")
def delete_loan(loan_id: int, request: Request, db: Session = Depends(get_db)):
    """Takes a loan away - only while the books hold nothing against it. The money received, or an instalment paid, is voided first."""
    client, _, who = wo_actor(request, db, WRITE)
    found = loan_or_404(db, client.id, loan_id)
    ids = [i for (i,) in db.query(DBLoanInstalment.id).filter(DBLoanInstalment.loan_id == found.id).all()]
    held = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.voided.is_(False),
        ((models.DBMoneyEntry.doc_type == "loan_disbursal") & (models.DBMoneyEntry.doc_id == found.id))
        | ((models.DBMoneyEntry.doc_type == "loan_instalment") & (models.DBMoneyEntry.doc_id.in_(ids or [0])))).first()
    if held is not None:
        raise HTTPException(409, "%s still has %s on the books. Void that entry first, then take the loan away." % (found.number, held.number))
    log_audit(db, client.id, "loan_deleted", "loan", found.id, found.number, "%s %s %s" % (found.lender, found.name, inr(found.principal)),
              request=request, user_name=who)
    number = found.number
    db.query(DBLoanInstalment).filter(DBLoanInstalment.loan_id == found.id).delete(synchronize_session=False)
    db.delete(found)
    db.commit()
    return {"ok": True, "message": "%s taken away." % number}
