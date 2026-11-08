"""Journal vouchers and supplier debit notes: what they are allowed to say, and what they change once they count.

A journal counts once the Master approves it (and stops if it is cancelled):
    a party line         moves that party's ledger - a debit to a supplier, contractor or member of staff takes off what we
                         owe them; a debit to a client adds to what they owe us
    an expense head line moves the project's cost (Cost by Project, Project Profit) - debit adds, credit takes off
    an account or ledger line is for the books (Tally) and moves nothing in the app on its own

A debit note to a supplier counts as soon as it is issued: it comes off the bill it names - what is still to be paid on it,
in Money to Pay and in the payment box - or, naming no bill, off the supplier's account.
"""
from datetime import date, datetime

from fastapi import HTTPException

from app import models
from app.constants.money import EXPENSE_HEADS, INCOME_HEADS, PARTY_TYPES
from app.core.currency import money
from app.models.journals import DBJournal, DBJournalLine, DBSupplierDebitNote

KINDS = ("party", "head", "account", "ledger")
LIVE = "APPROVED"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def next_number(db, model, client_id, stem):
    top = 0
    for (n,) in db.query(model.number).filter(model.client_id == client_id, model.number.like(stem + "%")).all():
        tail = (n or "")[len(stem):]
        if tail.isdigit():
            top = max(top, int(tail))
    return "%s%04d" % (stem, top + 1)


def _day(value, what):
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(400, "%s is a date like 2026-11-09." % what)


def _amount(v, what):
    try:
        n = round(float(v or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(400, "%s is a number." % what)
    if n < 0 or n > 1e12:
        raise HTTPException(400, "%s has to be from 0 up." % what)
    return n


# --- journal vouchers ----------------------------------------------------------------------------------------------------

def clean_lines(db, client_id, rows):
    from app.services import tally
    accounts = {a.id for a in db.query(models.DBBankAccount.id).filter(models.DBBankAccount.client_id == client_id).all()}
    jobs = {j for (j,) in db.query(models.DBJob.id).filter(models.DBJob.client_id == client_id).all()}
    out = []
    for n, r in enumerate(rows or [], 1):
        where = "Line %d" % n
        kind = (r.get("kind") or "party").strip()
        if kind not in KINDS:
            raise HTTPException(400, "%s: a line is a party, an expense or income head, a bank or cash account, or a ledger." % where)
        dr, cr = _amount(r.get("debit"), where + " debit"), _amount(r.get("credit"), where + " credit")
        if (dr > 0) == (cr > 0):
            raise HTTPException(400, "%s: give a debit or a credit, not both and not neither." % where)
        line = {"kind": kind, "party_type": "", "party_name": "", "head": "", "account_id": None, "ledger_key": "",
                "debit": dr, "credit": cr, "note": (r.get("note") or "").strip()[:200], "job_id": None}
        if kind == "party":
            line["party_type"] = (r.get("party_type") or "").strip()
            line["party_name"] = (r.get("party_name") or "").strip()[:200]
            if line["party_type"] not in PARTY_TYPES or not line["party_name"]:
                raise HTTPException(400, "%s: whose account - a client, supplier, contractor, member of staff or other - and their name." % where)
        elif kind == "head":
            line["head"] = (r.get("head") or "").strip()
            if line["head"] not in EXPENSE_HEADS + INCOME_HEADS:
                raise HTTPException(400, "%s: choose an expense or income head." % where)
        elif kind == "account":
            line["account_id"] = int(r.get("account_id") or 0) or None
            if line["account_id"] not in accounts:
                raise HTTPException(400, "%s: choose one of the company's bank accounts or cash boxes." % where)
        else:
            line["ledger_key"] = (r.get("ledger_key") or "").strip()
            if line["ledger_key"] not in tally.LEDGERS:
                raise HTTPException(400, "%s: choose one of the books' ledgers." % where)
        job = int(r.get("job_id") or 0) or None
        if job is not None and job not in jobs:
            raise HTTPException(400, "%s: that project is not this company's." % where)
        line["job_id"] = job
        out.append(line)
    if len(out) < 2:
        raise HTTPException(400, "A journal has at least two lines: what is debited and what is credited.")
    dr, cr = money(sum(l["debit"] for l in out)), money(sum(l["credit"] for l in out))
    if abs(dr - cr) >= 0.01:
        raise HTTPException(400, "The debits (%s) and the credits (%s) have to be equal." % ("{:,.2f}".format(dr), "{:,.2f}".format(cr)))
    return out


def raise_journal(db, client_id, body, who):
    from app.services.money import refuse_if_locked
    on = _day(body.get("voucher_date") or date.today().isoformat(), "The date")
    refuse_if_locked(db, client_id, on)
    narration = (body.get("narration") or "").strip()
    if len(narration) < 3:
        raise HTTPException(400, "Say what the journal is for: the narration goes in the books with it.")
    lines = clean_lines(db, client_id, body.get("lines"))
    j = DBJournal(client_id=client_id, number=next_number(db, DBJournal, client_id, "JV-"), voucher_date=on,
                  narration=narration[:1000], status="PENDING", raised_by_name=who)
    db.add(j)
    db.flush()
    for n, l in enumerate(lines):
        db.add(DBJournalLine(journal_id=j.id, display_order=n, **l))
    db.flush()
    return j


def journal_or_404(db, client_id, jid):
    j = db.query(DBJournal).filter(DBJournal.id == jid, DBJournal.client_id == client_id).first()
    if not j:
        raise HTTPException(404, "Journal not found")
    return j


def lines_of(db, ids):
    out = {}
    for l in db.query(DBJournalLine).filter(DBJournalLine.journal_id.in_(list(ids) or [0])).order_by(DBJournalLine.display_order).all():
        out.setdefault(l.journal_id, []).append(l)
    return out


def line_label(l, accounts=None, jobs=None):
    from app.services import tally
    if l.kind == "party":
        what = "%s (%s)" % (l.party_name, l.party_type)
    elif l.kind == "head":
        what = l.head
    elif l.kind == "account":
        a = (accounts or {}).get(l.account_id)
        what = a.name if a else "Bank or cash"
    else:
        what = tally.LABELS.get(l.ledger_key, l.ledger_key)
    j = (jobs or {}).get(l.job_id)
    return what + ((" - %s %s" % (j.number or "", j.name or "")).rstrip() if j else "")


def journal_dict(db, j, lines=None, accounts=None, jobs=None):
    lines = lines if lines is not None else lines_of(db, [j.id]).get(j.id, [])
    total = money(sum(l.debit or 0 for l in lines))
    return {"id": j.id, "number": j.number, "voucher_date": j.voucher_date, "narration": j.narration, "status": j.status,
            "raised_by_name": j.raised_by_name, "raised_at": j.raised_at, "decided_by_name": j.decided_by_name,
            "decided_at": j.decided_at, "decision_note": j.decision_note, "total": total,
            "lines": [{"kind": l.kind, "party_type": l.party_type, "party_name": l.party_name, "head": l.head,
                       "account_id": l.account_id, "ledger_key": l.ledger_key, "job_id": l.job_id, "debit": money(l.debit),
                       "credit": money(l.credit), "note": l.note, "label": line_label(l, accounts, jobs)} for l in lines]}


def decide(db, j, approve, who, note=""):
    if j.status != "PENDING":
        raise HTTPException(409, "%s is %s, not waiting for a decision." % (j.number, j.status.lower()))
    if not approve and len((note or "").strip()) < 3:
        raise HTTPException(400, "Say why it is sent back.")
    if approve:
        from app.services.money import refuse_if_locked
        refuse_if_locked(db, j.client_id, j.voucher_date)
    j.status = LIVE if approve else "REJECTED"
    j.decided_by_name, j.decided_at, j.decision_note = who, _now(), (note or "").strip()[:300]


def cancel(db, j, who, reason):
    if j.status == "CANCELLED":
        raise HTTPException(409, "%s is already cancelled." % j.number)
    if len((reason or "").strip()) < 3:
        raise HTTPException(400, "Say why it is being cancelled.")
    from app.services.money import refuse_if_locked
    refuse_if_locked(db, j.client_id, j.voucher_date)
    j.status, j.decided_by_name, j.decided_at, j.decision_note = "CANCELLED", who, _now(), reason.strip()[:300]


def live_lines(db, client_id):
    """(journal, line) for every line of every approved journal."""
    return (db.query(DBJournal, DBJournalLine).join(DBJournalLine, DBJournalLine.journal_id == DBJournal.id)
            .filter(DBJournal.client_id == client_id, DBJournal.status == LIVE).all())


def journal_ledger_rows(db, client_id):
    """Approved journals' party lines, as the party ledgers read them: for a client a debit is billed to them and a credit
    received; for everybody else a credit is what we owe and a debit what has gone to them."""
    rows = []
    for j, l in live_lines(db, client_id):
        if l.kind != "party":
            continue
        client = l.party_type == "client"
        rows.append({"party_type": l.party_type, "party": l.party_name, "date": j.voucher_date, "kind": "Journal",
                     "number": j.number, "doc_type": "journal", "doc_id": j.id,
                     "billed": money(l.debit if client else l.credit), "moved": money(l.credit if client else l.debit),
                     "job_id": l.job_id, "against": j.narration[:80]})
    return rows


def journal_costs_by_job(db, client_id, job_ids=None):
    """{job_id: amount} that approved journals put on (debit) or took off (credit) each project's expense heads."""
    out = {}
    for j, l in live_lines(db, client_id):
        if l.kind == "head" and l.head in EXPENSE_HEADS and l.job_id and (job_ids is None or l.job_id in job_ids):
            out[l.job_id] = out.get(l.job_id, 0.0) + (l.debit or 0) - (l.credit or 0)
    return out


# --- supplier debit notes ------------------------------------------------------------------------------------------------

def debited_by_bill(db, client_id, bill_ids=None):
    q = db.query(DBSupplierDebitNote.bill_id, DBSupplierDebitNote.total).filter(
        DBSupplierDebitNote.client_id == client_id, DBSupplierDebitNote.status == "ISSUED", DBSupplierDebitNote.bill_id.isnot(None))
    if bill_ids is not None:
        q = q.filter(DBSupplierDebitNote.bill_id.in_(list(bill_ids) or [0]))
    out = {}
    for bid, total in q.all():
        out[bid] = money(out.get(bid, 0.0) + (total or 0))
    return out


def bill_debited(db, bill):
    return debited_by_bill(db, bill.client_id, [bill.id]).get(bill.id, 0.0)


def raise_debit_note(db, client_id, body, who):
    from app.services.money import refuse_if_locked
    on = _day(body.get("note_date") or date.today().isoformat(), "The date")
    refuse_if_locked(db, client_id, on)
    reason = (body.get("reason") or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "Say why: goods sent back, price above the order, short supply...")
    taxable, tax = _amount(body.get("taxable"), "The amount"), _amount(body.get("tax"), "The GST")
    if taxable <= 0:
        raise HTTPException(400, "How much is it for, before GST?")
    bill, ret, supplier, job = None, None, (body.get("supplier_name") or "").strip(), int(body.get("job_id") or 0) or None
    if body.get("purchase_return_id"):
        from app.models.store_core import DocStatus
        from app.models.store_inward import DBStoreGrn, DBStorePurchaseReturn
        ret = db.get(DBStorePurchaseReturn, int(body["purchase_return_id"]))
        grn = db.get(DBStoreGrn, ret.grn_id) if ret else None
        if ret is None or grn is None or ret.client_id != client_id or ret.status != DocStatus.POSTED.value:
            raise HTTPException(404, "That purchase return is not posted in this company's store.")
        if db.query(DBSupplierDebitNote.id).filter(DBSupplierDebitNote.purchase_return_id == ret.id, DBSupplierDebitNote.status == "ISSUED").first():
            raise HTTPException(409, "A debit note has already been raised for %s." % ret.number)
        supplier = supplier or ret.supplier_name or ""
        job = job or grn.project_id
    if body.get("bill_id"):
        bill = db.query(models.DBBill).filter(models.DBBill.id == int(body["bill_id"]), models.DBBill.client_id == client_id).first()
        if bill is None:
            raise HTTPException(404, "Bill not found")
        supplier = supplier or bill.vendor_name or ""
        job = job or bill.job_id
        from app.services.money import already_settled
        left = money((bill.total or bill.amount or 0) - bill_debited(db, bill) - already_settled(db, client_id, "supplier_bill", bill, bill.total or 0))
        if taxable + tax > left + 0.009:
            raise HTTPException(409, "Only %s is still to be paid on %s; a debit note can take off no more. Raise the rest on the supplier's account (no bill)." % (
                "{:,.2f}".format(left), bill.number or "the bill"))
    if not supplier:
        raise HTTPException(400, "Which supplier is it to?")
    n = DBSupplierDebitNote(client_id=client_id, number=next_number(db, DBSupplierDebitNote, client_id, "DN-"), note_date=on,
                            supplier_name=supplier[:200], bill_id=bill.id if bill else None, purchase_return_id=ret.id if ret else None,
                            job_id=job, reason=reason[:300], taxable=taxable, tax=tax, total=money(taxable + tax), raised_by_name=who)
    db.add(n)
    db.flush()
    if bill is not None:
        _resettle(db, client_id, bill)
    return n


def _resettle(db, client_id, bill):
    from app.services.money import _settle_doc
    _settle_doc(db, client_id, "supplier_bill", bill, money((bill.total or bill.amount or 0) - bill_debited(db, bill)), "")


def cancel_debit_note(db, n, reason):
    if n.status == "CANCELLED":
        raise HTTPException(409, "%s is already cancelled." % n.number)
    if len((reason or "").strip()) < 3:
        raise HTTPException(400, "Say why it is being cancelled.")
    from app.services.money import refuse_if_locked
    refuse_if_locked(db, n.client_id, n.note_date)
    n.status, n.cancel_reason = "CANCELLED", reason.strip()[:300]
    db.flush()
    if n.bill_id:
        bill = db.get(models.DBBill, n.bill_id)
        if bill is not None:
            _resettle(db, n.client_id, bill)


def debit_note_dict(n, bills=None, jobs=None):
    b = (bills or {}).get(n.bill_id)
    j = (jobs or {}).get(n.job_id)
    return {"id": n.id, "number": n.number, "note_date": n.note_date, "supplier_name": n.supplier_name, "bill_id": n.bill_id,
            "bill_number": (b.number or "") if b else "", "purchase_return_id": n.purchase_return_id, "job_id": n.job_id,
            "project": ("%s %s" % (j.number or "", j.name or "")).strip() if j else "", "reason": n.reason, "taxable": money(n.taxable),
            "tax": money(n.tax), "total": money(n.total), "status": n.status, "cancel_reason": n.cancel_reason,
            "raised_by_name": n.raised_by_name, "created_at": n.created_at}


def debit_note_ledger_rows(db, client_id):
    """Issued debit notes in the supplier's ledger: what we owe them goes down."""
    return [{"party_type": "supplier", "party": n.supplier_name, "date": n.note_date, "kind": "Debit note", "number": n.number,
             "doc_type": "supplier_debit_note", "doc_id": n.id, "billed": -money(n.total), "moved": 0.0, "job_id": n.job_id,
             "against": n.reason[:80]}
            for n in db.query(DBSupplierDebitNote).filter(DBSupplierDebitNote.client_id == client_id, DBSupplierDebitNote.status == "ISSUED").all()]


def returns_without_note(db, client_id):
    """Posted purchase returns no debit note has been raised for yet - each one owed back by its supplier."""
    from app.models.store_core import DocStatus
    from app.models.store_inward import DBStoreGrn, DBStorePurchaseReturn
    noted = {r for (r,) in db.query(DBSupplierDebitNote.purchase_return_id).filter(
        DBSupplierDebitNote.client_id == client_id, DBSupplierDebitNote.status == "ISSUED", DBSupplierDebitNote.purchase_return_id.isnot(None)).all()}
    out = []
    for r, grn in (db.query(DBStorePurchaseReturn, DBStoreGrn).join(DBStoreGrn, DBStoreGrn.id == DBStorePurchaseReturn.grn_id)
                   .filter(DBStorePurchaseReturn.client_id == client_id, DBStorePurchaseReturn.status == DocStatus.POSTED.value).all()):
        if r.id in noted:
            continue
        bills = db.query(models.DBBill).filter(models.DBBill.client_id == client_id, models.DBBill.purchase_order_id == grn.po_id,
                                               models.DBBill.status.notin_(("Cancelled", "Rejected", "Draft"))).all() if grn.po_id else []
        out.append({"id": r.id, "number": r.number, "date": r.return_date.isoformat() if r.return_date else "", "supplier_name": r.supplier_name or "",
                    "reason": r.reason or "", "taxable": money(float(r.debit_value or 0)), "tax": money(float(r.tax_value or 0)),
                    "total": money(float(r.debit_value or 0) + float(r.tax_value or 0)), "job_id": grn.project_id,
                    "bills": [{"id": b.id, "number": b.number or "", "total": money(b.total or 0)} for b in bills]})
    return out


def debit_notes_by_job(db, client_id, job_ids=None):
    """{job_id: amount} issued debit notes took back off each project's purchases - the whole note, GST included, as a
    bill's cost is counted with its GST."""
    out = {}
    for jid, total in db.query(DBSupplierDebitNote.job_id, DBSupplierDebitNote.total).filter(
            DBSupplierDebitNote.client_id == client_id, DBSupplierDebitNote.status == "ISSUED", DBSupplierDebitNote.job_id.isnot(None)).all():
        if job_ids is None or jid in job_ids:
            out[jid] = out.get(jid, 0.0) + (total or 0)
    return out
