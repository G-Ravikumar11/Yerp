"""Paying out: bank payment files, MSME bills, cheque books and post-dated cheques, staff expense claims."""
from datetime import date

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import models
from app.core.audit import log_audit
from app.core.auth import require_items_access, session_person, wo_actor
from app.core.currency import inr
from app.core.notifications import tell_approvers
from app.db import get_db, get_read_db
from app.services import payouts as po
from app.services.site_cash import CHECKERS

router = APIRouter()
READ, PAY = "bills.view_all", "bills.pay"


def _accounts(db, client_id):
    return {a.id: a for a in db.query(models.DBBankAccount).filter(models.DBBankAccount.client_id == client_id).all()}


def _jobs(db, client_id):
    return {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}


# --- bank payment files ---------------------------------------------------------------------------------------------------

@router.get("/api/payment-batches")
def list_batches(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    accounts = _accounts(db, client.id)
    bs = db.query(po.DBPaymentBatch).filter(po.DBPaymentBatch.client_id == client.id).order_by(po.DBPaymentBatch.id.desc()).limit(200).all()
    return {"batches": [po.batch_dict(db, b, accounts) for b in bs],
            "formats": [{"key": k, "label": v} for k, v in po.FORMATS.items()],
            "accounts": [{"id": a.id, "name": a.name, "has_number": bool((a.account_no or "").strip()), "ifsc": a.ifsc or ""}
                         for a in accounts.values() if a.kind != "Cash" and a.is_active is not False]}


@router.get("/api/payment-batches/candidates")
def batch_candidates(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, PAY)
    return po.payable_items(db, client)


@router.post("/api/payment-batches")
def create_batch(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    b = po.make_batch(db, client, body, who)
    d = po.batch_dict(db, b)
    log_audit(db, client.id, "payment_file_made", "payment_batch", b.id, b.number, "%d payments, %s" % (d["count"], inr(d["total"])),
              request=request, user_name=who)
    db.commit()
    return dict(po.batch_dict(db, b), message="%s: %d payments, %s. Download the file and upload it at the bank." % (b.number, d["count"], inr(d["total"])))


@router.get("/api/payment-batches/{bid}")
def get_batch(bid: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    return po.batch_dict(db, po.batch_or_404(db, client.id, bid))


@router.get("/api/payment-batches/{bid}/file")
def batch_file(bid: int, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    b = po.batch_or_404(db, client.id, bid)
    ours = db.get(models.DBBankAccount, b.account_id)
    text = po.file_text(b, po.batch_lines(db, b.id), ours)
    log_audit(db, client.id, "payment_file_downloaded", "payment_batch", b.id, b.number, b.bank_format, request=request, user_name=who)
    db.commit()
    ext = "txt" if b.bank_format == "hdfc" else "csv"
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s_%s.%s"' % (b.number, b.bank_format, ext)})


@router.post("/api/payment-batches/{bid}/paid")
def batch_paid(bid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    b = po.batch_or_404(db, client.id, bid)
    paid, failed = po.mark_paid(db, request, client, b, (body or {}).get("paid_on"), (body or {}).get("reference"), who)
    b = po.batch_or_404(db, client.id, bid)
    log_audit(db, client.id, "payment_file_paid", "payment_batch", b.id, b.number, "%d paid, %d failed" % (paid, failed),
              request=request, user_name=who)
    db.commit()
    msg = "%s: %d payments entered in the bank book." % (b.number, paid)
    if failed:
        msg += " %d could not be - see the reason on each; pay them by hand or take them out." % failed
    return dict(po.batch_dict(db, b), message=msg)


@router.post("/api/payment-batches/{bid}/cancel")
def batch_cancel(bid: int, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    b = po.batch_or_404(db, client.id, bid)
    if b.status != "DRAFT":
        raise HTTPException(409, "%s is %s." % (b.number, b.status.lower()))
    if any(l.status == "PAID" for l in po.batch_lines(db, b.id)):
        # Part of it went through: the paid lines stay paid, and the file is closed with them.
        b.status = "PAID"
    else:
        b.status = "CANCELLED"
    log_audit(db, client.id, "payment_file_cancelled", "payment_batch", b.id, b.number, "", request=request, user_name=who)
    db.commit()
    return dict(po.batch_dict(db, b), message="%s closed." % b.number)


# --- cheque books and post-dated cheques ------------------------------------------------------------------------------------

@router.get("/api/cheque-books")
def list_books(request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    accounts = _accounts(db, client.id)
    books = db.query(po.DBChequeBook).filter(po.DBChequeBook.client_id == client.id).order_by(po.DBChequeBook.id.desc()).all()
    return {"books": [po.book_dict(db, client.id, b, accounts) for b in books]}


@router.post("/api/cheque-books")
def add_book(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    b = po.add_book(db, client.id, body)
    log_audit(db, client.id, "cheque_book_added", "cheque_book", b.id, "%d-%d" % (b.first_no, b.last_no), "", request=request, user_name=who)
    db.commit()
    return po.book_dict(db, client.id, b, _accounts(db, client.id))


def _book(db, client_id, book_id):
    b = db.query(po.DBChequeBook).filter(po.DBChequeBook.id == book_id, po.DBChequeBook.client_id == client_id).first()
    if not b:
        raise HTTPException(404, "Cheque book not found")
    return b


@router.get("/api/cheque-books/{book_id}/leaves")
def book_leaves(book_id: int, request: Request, db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    return {"leaves": po.book_leaves(db, client.id, _book(db, client.id, book_id))}


@router.post("/api/cheque-books/{book_id}/spoil")
def spoil(book_id: int, request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    b = _book(db, client.id, book_id)
    try:
        n = int(body.get("number"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Which leaf?")
    po.spoil_leaf(db, client.id, b, n, body.get("reason"), who)
    log_audit(db, client.id, "cheque_spoilt", "cheque_book", b.id, str(n), body.get("reason") or "", request=request, user_name=who)
    db.commit()
    return {"ok": True, "message": "Leaf %d marked spoilt." % n}


@router.get("/api/pdcs")
def list_pdcs(request: Request, status: str = "", db: Session = Depends(get_read_db)):
    client = require_items_access(request, db, READ)
    q = db.query(po.DBPostDatedCheque).filter(po.DBPostDatedCheque.client_id == client.id)
    if status:
        q = q.filter(po.DBPostDatedCheque.status == status.upper())
    rows = [po.pdc_dict(p, _accounts(db, client.id), _jobs(db, client.id)) for p in q.order_by(po.DBPostDatedCheque.cheque_date).all()]
    held = [r for r in rows if r["status"] == "HELD"]
    week = (date.today().toordinal() + 7)
    return {"cheques": rows, "summary": {
        "given": sum(r["amount"] for r in held if r["direction"] == "OUT"),
        "held": sum(r["amount"] for r in held if r["direction"] == "IN"),
        "due": len([r for r in held if r["due"]]),
        "this_week": len([r for r in held if date.fromisoformat(r["cheque_date"]).toordinal() <= week])}}


@router.post("/api/pdcs")
def add_pdc(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    p = po.add_pdc(db, client.id, body, who)
    log_audit(db, client.id, "pdc_added", "pdc", p.id, p.cheque_no, "%s %s %s" % (p.direction, p.party_name, inr(p.amount)),
              request=request, user_name=who)
    db.commit()
    return dict(po.pdc_dict(p, _accounts(db, client.id), _jobs(db, client.id)),
                message="Cheque %s dated %s kept on the list." % (p.cheque_no, p.cheque_date))


@router.post("/api/pdcs/{pid}/bank")
def bank_pdc(pid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    p = po.bank_pdc(db, request, client, po.pdc_or_404(db, client.id, pid), (body or {}).get("on"), (body or {}).get("account_id"))
    return dict(po.pdc_dict(p, _accounts(db, client.id), _jobs(db, client.id)),
                message="Cheque %s is in the bank book." % p.cheque_no)


@router.post("/api/pdcs/{pid}/close")
def close_pdc(pid: int, request: Request, body: dict = Body(default={}), db: Session = Depends(get_db)):
    """Given back (or bounced before it was banked), or cancelled - it never becomes money."""
    client, _, who = wo_actor(request, db, PAY)
    p = po.pdc_or_404(db, client.id, pid)
    if p.status != "HELD":
        raise HTTPException(409, "Cheque %s is %s." % (p.cheque_no, p.status.lower()))
    status = ((body or {}).get("status") or "CANCELLED").upper()
    reason = ((body or {}).get("reason") or "").strip()
    if status not in ("RETURNED", "CANCELLED") or len(reason) < 3:
        raise HTTPException(400, "Returned or cancelled, and why.")
    p.status, p.closed_reason = status, reason[:200]
    log_audit(db, client.id, "pdc_closed", "pdc", p.id, p.cheque_no, "%s: %s" % (status, reason), request=request, user_name=who)
    db.commit()
    return dict(po.pdc_dict(p, _accounts(db, client.id), _jobs(db, client.id)), message="Cheque %s %s." % (p.cheque_no, status.lower()))


# --- staff expense claims ---------------------------------------------------------------------------------------------------

def _who(db, client, emp):
    from app.services.hr import employee_name
    return employee_name(emp) if emp is not None else (client.contact_name or client.company_name or "Master")


def _checker(emp):
    from app.core.permissions import employee_can
    return emp is None or any(employee_can(emp, p) for p in CHECKERS)


def _photos(db, client_id, ids):
    out = {}
    for f in db.query(models.DBFile).filter(models.DBFile.client_id == client_id, models.DBFile.attached_type == "expense_claim",
                                            models.DBFile.attached_id.in_(list(ids) or [0])).all():
        out.setdefault(f.attached_id, []).append({"id": f.id, "name": f.name})
    return out


@router.get("/api/expense-claims")
def list_claims(request: Request, mine: bool = False, status: str = "", job_id: int = 0, db: Session = Depends(get_read_db)):
    client, emp = session_person(request, db)
    q = db.query(po.DBExpenseClaim).filter(po.DBExpenseClaim.client_id == client.id)
    everyone = _checker(emp) and not mine
    if not everyone:
        if emp is None:
            raise HTTPException(400, "The Master has no claims of their own.")
        q = q.filter(po.DBExpenseClaim.employee_id == emp.id)
    if status:
        q = q.filter(po.DBExpenseClaim.status == status.upper())
    if job_id:
        q = q.filter(po.DBExpenseClaim.job_id == job_id)
    cs = q.order_by(po.DBExpenseClaim.id.desc()).limit(500).all()
    photos = _photos(db, client.id, [c.id for c in cs])
    jobs = _jobs(db, client.id)
    return {"claims": [dict(po.claim_dict(c, jobs, photos), left=po.claim_left(db, c) if c.status == "APPROVED" else 0.0) for c in cs],
            "can_decide": _checker(emp), "me": emp.id if emp is not None else None}


@router.post("/api/expense-claims")
def submit_claim(request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    if emp is None:
        require_items_access(request, db, PAY)            # entered by accounts for somebody, from their bills
    who = _who(db, client, emp)
    c = po.submit_claim(db, client.id, emp, body, who)
    tell_approvers(db, client.id, "Expense claim to check: %s" % c.number, "%s spent %s on %s (%s)." % (c.employee_name, inr(c.amount), c.head, c.description[:120]),
                   rights=CHECKERS, exclude=[c.employee_id], owner=True)
    log_audit(db, client.id, "expense_claimed", "expense_claim", c.id, c.number, "%s %s" % (c.head, inr(c.amount)), request=request, user_name=who)
    db.commit()
    return dict(po.claim_dict(c, _jobs(db, client.id)), message="%s claimed: %s. Add the bill's photo; accounts will check it." % (c.number, inr(c.amount)))


@router.post("/api/expense-claims/{cid}/photo")
def claim_photo(cid: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    from app.core.files import store_file
    client, emp = session_person(request, db)
    c = po.claim_or_404(db, client.id, cid)
    if emp is not None and emp.id != c.employee_id and not _checker(emp):
        raise HTTPException(403, "That is somebody else's claim.")
    if c.status not in ("SUBMITTED",):
        raise HTTPException(409, "%s is already %s." % (c.number, c.status.lower()))
    f = store_file(db, client.id, file, file.file.read(), job_id=c.job_id, attached_type="expense_claim", attached_id=c.id,
                   kind="bill", caption="Bill for %s, %s" % (c.number, c.employee_name), by=_who(db, client, emp))
    db.commit()
    return {"ok": True, "photo": {"id": f.id, "name": f.name}, "message": "Bill kept with %s." % c.number}


def decide_claim(cid, approve, note, request, db):
    client, emp = session_person(request, db)
    if not _checker(emp):
        raise HTTPException(403, "Accounts check expense claims.")
    c = po.claim_or_404(db, client.id, cid)
    who = _who(db, client, emp)
    po.decide_claim(db, c, approve, who, note, deciding_emp=emp)
    log_audit(db, client.id, "expense_claim_" + ("approved" if approve else "rejected"), "expense_claim", c.id, c.number, note or "",
              request=request, user_name=who)
    db.commit()
    msg = ("%s approved: %s owed to %s. Reimburse it, or set it against an advance they hold." % (c.number, inr(c.amount), c.employee_name)
           if approve else "%s sent back to %s." % (c.number, c.employee_name))
    return dict(po.claim_dict(c, _jobs(db, client.id)), message=msg)


@router.post("/api/expense-claims/{cid}/decide")
def claim_decide(cid: int, request: Request, body: dict = Body(...), db: Session = Depends(get_db)):
    decision = (body.get("decision") or "").lower()
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "Approve or send back?")
    return decide_claim(cid, decision == "approve", body.get("note") or "", request, db)


@router.post("/api/expense-claims/{cid}/against-advance")
def claim_against_advance(cid: int, request: Request, db: Session = Depends(get_db)):
    client, _, who = wo_actor(request, db, PAY)
    c = po.claim_or_404(db, client.id, cid)
    took = po.set_against_advance(db, c)
    log_audit(db, client.id, "expense_claim_set_off", "expense_claim", c.id, c.number, inr(took), request=request, user_name=who)
    db.commit()
    left = po.claim_left(db, c)
    return dict(po.claim_dict(c, _jobs(db, client.id)), message="%s set against %s's advance%s." % (
        inr(took), c.employee_name, (" - %s still to reimburse" % inr(left)) if left > 0 else ""))


@router.post("/api/expense-claims/{cid}/cancel")
def claim_cancel(cid: int, request: Request, db: Session = Depends(get_db)):
    client, emp = session_person(request, db)
    c = po.claim_or_404(db, client.id, cid)
    if emp is not None and emp.id != c.employee_id:
        raise HTTPException(403, "That is somebody else's claim.")
    if c.status != "SUBMITTED":
        raise HTTPException(409, "%s is %s; only a claim not yet checked is withdrawn." % (c.number, c.status.lower()))
    c.status = "CANCELLED"
    db.commit()
    return dict(po.claim_dict(c, _jobs(db, client.id)), message="%s withdrawn." % c.number)
