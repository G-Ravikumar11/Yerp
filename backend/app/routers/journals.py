"""Journal vouchers (approved by the Master only) and debit notes to suppliers."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_items_access, require_owner, wo_actor
from app.core.currency import inr
from app.core.notifications import notify
from app.db import get_db, get_read_db
from app.documents.forms import form_pdf_response, journal_voucher_spec, supplier_debit_note_spec
from app.services import journals as jv
from app.services import tally

router = APIRouter()
READ, WRITE = "money.view", "accounts.manage"


def _lookups(db, client_id):
    accounts = {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client_id).all()}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    return accounts, jobs


def _master_name(request, db, client):
    return client.contact_name or client.company_name or "Master"


@router.get("/api/journals")
def list_journals(request: Request, status: str = "", job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    q = db.query(jv.DBJournal).filter(jv.DBJournal.client_id == client.id)
    if status:
        q = q.filter(jv.DBJournal.status == status.upper())
    js = q.order_by(jv.DBJournal.voucher_date.desc(), jv.DBJournal.id.desc()).all()
    lines = jv.lines_of(db, [j.id for j in js])
    if job_id:
        js = [j for j in js if any(l.job_id == job_id for l in lines.get(j.id, []))]
    accounts, jobs = _lookups(db, client.id)
    return {"journals": [jv.journal_dict(db, j, lines.get(j.id, []), accounts, jobs) for j in js],
            "ledgers": [{"key": k, "label": tally.LABELS.get(k, k)} for k in tally.LEDGERS],
            "can_approve": _is_master(request, db)}


def _is_master(request, db):
    try:
        require_owner(request, db)
        return True
    except HTTPException:
        return False


@router.post("/api/journals")
def create_journal(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    j = jv.raise_journal(db, client.id, body, who)
    total = sum(l.debit or 0 for l in jv.lines_of(db, [j.id]).get(j.id, []))
    log_audit(db, client.id, "journal_raised", "journal", j.id, j.number, "%s: %s" % (inr(total), j.narration[:200]),
              request=request, user_name=who)
    notify(db, client.id, "approval", "Journal %s waits for your approval" % j.number,
           "%s - %s, raised by %s." % (inr(total), j.narration[:200], who), view="/money/adjustments", ref_type="journal", ref_id=j.id)
    db.commit()
    accounts, jobs = _lookups(db, client.id)
    return jv.journal_dict(db, j, None, accounts, jobs)


@router.get("/api/journals/{jid}")
def get_journal(jid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    accounts, jobs = _lookups(db, client.id)
    return jv.journal_dict(db, jv.journal_or_404(db, client.id, jid), None, accounts, jobs)


def decide_journal(jid, approve, note, request, db):
    """Only the Master approves or sends back a journal - on this page or from the approvals inbox."""
    require_owner(request, db)
    client = require_items_access(request, db, READ)
    j = jv.journal_or_404(db, client.id, jid)
    who = _master_name(request, db, client)
    jv.decide(db, j, approve, who, note)
    log_audit(db, client.id, "journal_approved" if approve else "journal_rejected", "journal", j.id, j.number, note or "",
              request=request, user_name=who)
    db.commit()
    accounts, jobs = _lookups(db, client.id)
    return jv.journal_dict(db, j, None, accounts, jobs)


@router.post("/api/journals/{jid}/approve")
def approve_journal(jid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    return decide_journal(jid, True, (body or {}).get("note", ""), request, db)


@router.post("/api/journals/{jid}/reject")
def reject_journal(jid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    return decide_journal(jid, False, (body or {}).get("note", ""), request, db)


@router.post("/api/journals/{jid}/cancel")
def cancel_journal(jid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    """A journal still waiting may be withdrawn by accounts; an approved one is cancelled by the Master alone."""
    client, _, who = wo_actor(request, db, WRITE)
    j = jv.journal_or_404(db, client.id, jid)
    if j.status == jv.LIVE:
        require_owner(request, db)
        who = _master_name(request, db, client)
    jv.cancel(db, j, who, (body or {}).get("reason", ""))
    log_audit(db, client.id, "journal_cancelled", "journal", j.id, j.number, j.decision_note, request=request, user_name=who)
    db.commit()
    accounts, jobs = _lookups(db, client.id)
    return jv.journal_dict(db, j, None, accounts, jobs)


@router.get("/api/journals/{jid}/voucher.pdf")
def journal_pdf(jid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    accounts, jobs = _lookups(db, client.id)
    d = jv.journal_dict(db, jv.journal_or_404(db, client.id, jid), None, accounts, jobs)
    return form_pdf_response(journal_voucher_spec(db, client, d), d["number"])


# --- debit notes to suppliers ---------------------------------------------------------------------------------------------

def _note_or_404(db, client_id, nid):
    n = db.query(jv.DBSupplierDebitNote).filter(jv.DBSupplierDebitNote.id == nid, jv.DBSupplierDebitNote.client_id == client_id).first()
    if not n:
        raise HTTPException(404, "Debit note not found")
    return n


def _note_out(db, client_id, notes):
    bill_ids = {n.bill_id for n in notes if n.bill_id}
    bills = {b.id: b for b in db.query(models.DBBill).filter(models.DBBill.id.in_(list(bill_ids) or [0])).all()}
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    return [jv.debit_note_dict(n, bills, jobs) for n in notes]


@router.get("/api/supplier-debit-notes")
def list_debit_notes(request: Request, supplier: str = "", job_id: int = 0, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    q = db.query(jv.DBSupplierDebitNote).filter(jv.DBSupplierDebitNote.client_id == client.id)
    if supplier:
        q = q.filter(jv.DBSupplierDebitNote.supplier_name == supplier)
    if job_id:
        q = q.filter(jv.DBSupplierDebitNote.job_id == job_id)
    notes = q.order_by(jv.DBSupplierDebitNote.note_date.desc(), jv.DBSupplierDebitNote.id.desc()).all()
    return {"notes": _note_out(db, client.id, notes), "returns": jv.returns_without_note(db, client.id)}


@router.post("/api/supplier-debit-notes")
def create_debit_note(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    n = jv.raise_debit_note(db, client.id, body, who)
    log_audit(db, client.id, "debit_note_raised", "supplier_debit_note", n.id, n.number,
              "%s to %s: %s" % (inr(n.total), n.supplier_name, n.reason[:200]), request=request, user_name=who)
    db.commit()
    return _note_out(db, client.id, [n])[0]


@router.post("/api/supplier-debit-notes/{nid}/cancel")
def cancel_debit_note(nid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, WRITE)
    n = _note_or_404(db, client.id, nid)
    jv.cancel_debit_note(db, n, (body or {}).get("reason", ""))
    log_audit(db, client.id, "debit_note_cancelled", "supplier_debit_note", n.id, n.number, n.cancel_reason, request=request, user_name=who)
    db.commit()
    return _note_out(db, client.id, [n])[0]


@router.get("/api/supplier-debit-notes/{nid}/note.pdf")
def debit_note_pdf(nid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    d = _note_out(db, client.id, [_note_or_404(db, client.id, nid)])[0]
    return form_pdf_response(supplier_debit_note_spec(db, client, d), d["number"])
