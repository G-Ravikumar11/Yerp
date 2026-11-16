"""Salary advances, and taking them back through the payroll.

An advance to a member of staff is money paid to them on account (Accounts > Advances, party type Staff): it sits in
their ledger until it comes back - in cash, or taken from their salary. The payroll is where the second happens. HR
types the month's recovery on the payslip, against the balance the person holds; when the payslip is released (marked
paid, on its own or with its month) an adjustment receipt is written for it, which is what brings the balance down.
The receipt is the same document Accounts would have entered by hand, so Advances, the ledger and the bank book all
read the same as before - the payroll just stops anybody having to type it twice.
"""
from datetime import date

from fastapi import HTTPException

from app import models
from app.core.currency import inr, money
from app.services.crm import norm_name
from app.services.hr import employee_name
from app.services.money import next_money_number

RECOVERY_NOTE = "Salary advance recovered on payslip %s"


def balances(db, client_id):
    """{normalised name: advance still out} for every member of staff with money on account - paid out, less what
    has come back. Names, not ids: an on-account entry names its party and carries no id."""
    out = {}
    for e in db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.party_type == "staff",
            models.DBMoneyEntry.doc_type == "on_account", models.DBMoneyEntry.voided.isnot(True)).all():
        key = norm_name(e.party_name)
        if key:
            out[key] = money(out.get(key, 0.0) + (e.amount or 0) * (1 if e.direction == "OUT" else -1))
    return out


def pending_recoveries(db, client_id, exclude_id=None):
    """{normalised name: recovery typed on payslips not yet released} - spoken for, though not yet taken back."""
    out = {}
    q = db.query(models.DBPayslip).filter(
        models.DBPayslip.client_id == client_id, models.DBPayslip.status != "Void",
        models.DBPayslip.advance_recovery > 0, models.DBPayslip.advance_entry_id.is_(None))
    if exclude_id:
        q = q.filter(models.DBPayslip.id != exclude_id)
    for ps in q.all():
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == ps.employee_id).first()
        key = norm_name(employee_name(emp))
        if key:
            out[key] = money(out.get(key, 0.0) + (ps.advance_recovery or 0))
    return out


def balance_for(db, client_id, emp, held=None):
    """The advance this person holds: what was paid out less what has come back."""
    held = balances(db, client_id) if held is None else held
    return max(0.0, held.get(norm_name(employee_name(emp)), 0.0))


def check_recovery(db, client_id, emp, amount, held=None, pending=None, exclude_id=None):
    """The recovery HR typed, refused (400) when it is more than the advance the person still holds, less what other
    unreleased payslips already take back."""
    amount = money(amount or 0)
    if amount < 0:
        raise HTTPException(status_code=400, detail="The advance recovery cannot be negative.")
    if amount <= 0:
        return 0.0
    held = balances(db, client_id) if held is None else held
    pending = pending_recoveries(db, client_id, exclude_id=exclude_id) if pending is None else pending
    key = norm_name(employee_name(emp))
    out = max(0.0, held.get(key, 0.0))
    spoken_for = pending.get(key, 0.0)
    left = money(out - spoken_for)
    if amount > left + 0.009:
        if out <= 0:
            why = "%s holds no advance to take back." % employee_name(emp)
        elif spoken_for:
            why = ("%s holds an advance of %s, of which %s is already being taken back on another payslip not yet "
                   "released: at most %s can be recovered here." % (employee_name(emp), inr(out), inr(spoken_for), inr(max(left, 0.0))))
        else:
            why = "%s holds an advance of %s: at most that can be recovered." % (employee_name(emp), inr(out))
        raise HTTPException(status_code=400, detail=why)
    return amount


def recover_on_release(db, client_id, slips, by_name):
    """For every payslip released with a recovery on it and no receipt yet: an adjustment receipt from the person, on
    account, dated today, which sets that much of their advance off. Returns the entries made. Adds, never commits."""
    made = []
    today = date.today().isoformat()
    for ps in slips:
        if (ps.advance_recovery or 0) <= 0 or ps.advance_entry_id:
            continue
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == ps.employee_id).first()
        name = employee_name(emp)
        if not name:
            continue
        e = models.DBMoneyEntry(
            client_id=client_id, number=next_money_number(db, client_id, "IN"), direction="IN",
            party_type="staff", party_name=name, party_id=None, doc_type="on_account", doc_id=None,
            doc_number=ps.number or "", job_id=None, account_id=None, amount=money(ps.advance_recovery),
            paid_on=today, mode="Adjustment", reference=ps.number or "",
            note=RECOVERY_NOTE % (ps.number or ""), recorded_by_name=by_name or "")
        db.add(e)
        db.flush()
        ps.advance_entry_id = e.id
        made.append(e)
    return made


def undo_recovery(db, client_id, ps, why):
    """A released payslip taken back (reopened, or deleted): its receipt is voided, with the reason, so the advance is
    owed again; the payslip may be released afresh. Nothing when it had none."""
    if not ps.advance_entry_id:
        return None
    e = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == ps.advance_entry_id,
                                             models.DBMoneyEntry.client_id == client_id).first()
    ps.advance_entry_id = None
    if e and not e.voided:
        e.voided, e.void_reason = True, (why or "")[:300]
    return e
