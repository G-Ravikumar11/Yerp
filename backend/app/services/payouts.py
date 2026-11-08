"""Paying out: the bank's bulk payment file, MSME suppliers' 45 days, cheque books and post-dated cheques, and staff
expense claims.

A payment file is not a payment. It is written for the bank's upload; once the bank has made the transfers it is marked
paid here, and only then does each line go into the bank book as an ordinary payment - through the same door as a payment
typed by hand, so every rule a payment answers to (approval, what is still owed, a contractor's papers) still applies.

MSME (Income-tax section 43B(h), MSMED Act section 15): a bill from a micro or small enterprise is paid within the days
agreed in writing, and never more than 45 days from acceptance; past that the expense is disallowed for the year it
stays unpaid and interest is owed. Here it is flagged and warned, not blocked.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core.currency import money
from app.models.payouts import (DBChequeBook, DBChequeSpoilt, DBExpenseClaim, DBPaymentBatch, DBPaymentBatchLine,
                                DBPostDatedCheque)

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
RTGS_FROM = 200000.0
MSME_DAYS = 45
MSME_KINDS = ("micro", "small")            # 43B(h) covers micro and small enterprises; a medium one is outside it


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _day(value, what="The date"):
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise HTTPException(400, "%s is a date like 2026-11-09." % what)


def next_number(db, model, client_id, stem):
    top = 0
    for (n,) in db.query(model.number).filter(model.client_id == client_id, model.number.like(stem + "%")).all():
        tail = (n or "")[len(stem):]
        if tail.isdigit():
            top = max(top, int(tail))
    return "%s%04d" % (stem, top + 1)


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# --- MSME ---------------------------------------------------------------------------------------------------------------

def clean_msme(kind, udyam):
    kind = (kind or "").strip().lower()
    if kind not in ("", "micro", "small", "medium"):
        raise HTTPException(400, "MSME type is micro, small or medium (or blank when they are not registered).")
    udyam = re.sub(r"\s", "", (udyam or "")).upper()
    if udyam and not re.match(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$", udyam):
        raise HTTPException(400, "A Udyam registration number reads like UDYAM-TS-02-0012345.")
    if udyam and not kind:
        raise HTTPException(400, "Say whether the enterprise is micro, small or medium, as its Udyam certificate does.")
    return kind, udyam


def msme_parties(db, client_id):
    """{(party_type, normalised name): (kind, udyam, payment days)} for every supplier and contractor marked MSME."""
    out = {}
    for s in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client_id, models.DBSupplier.msme_type != "").all():
        out[("supplier", norm(s.name))] = (s.msme_type, s.udyam_no or "", s.payment_days or 0)
    for c in db.query(models.DBContractor).filter(models.DBContractor.client_id == client_id, models.DBContractor.msme_type != "").all():
        out[("contractor", norm(c.company_name))] = (c.msme_type, c.udyam_no or "", 0)
    return out


def msme_due(start, agreed_days):
    """The last day an MSME bill may be paid: the days agreed, never past 45 (15 when nothing was agreed in writing -
    taken here as the 45, as most purchase orders state their terms)."""
    try:
        d = date.fromisoformat((start or "")[:10])
    except ValueError:
        return ""
    days = min(agreed_days, MSME_DAYS) if agreed_days else MSME_DAYS
    return (d + timedelta(days=days)).isoformat()


def msme_flag(parties, party_type, party, start, today=None):
    """{"kind", "udyam", "due", "days_left"} for a bill to an MSME (micro or small) party, or None."""
    hit = parties.get((party_type, norm(party)))
    if not hit or hit[0] not in MSME_KINDS:
        return None
    due = msme_due(start, hit[2])
    if not due:
        return None
    left = (date.fromisoformat(due) - (today or date.today())).days
    return {"kind": hit[0], "udyam": hit[1], "due": due, "days_left": left}


# --- beneficiaries ------------------------------------------------------------------------------------------------------

def beneficiary(db, client_id, party_type, party_name, party_id=None):
    """(account, ifsc, bank, email) from the supplier, contractor or staff master."""
    if party_type == "contractor":
        q = db.query(models.DBContractor).filter(models.DBContractor.client_id == client_id)
        c = q.filter(models.DBContractor.id == party_id).first() if party_id else None
        c = c or next((x for x in q.all() if norm(x.company_name) == norm(party_name)), None)
        if c:
            return c.bank_account or "", c.bank_ifsc or "", c.bank_name or "", c.email or ""
    elif party_type == "supplier":
        s = next((x for x in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client_id).all()
                  if norm(x.name) == norm(party_name)), None)
        if s:
            return s.bank_account or "", s.bank_ifsc or "", s.bank_name or "", s.email or ""
    elif party_type == "staff":
        from app.services.hr import employee_name
        e = db.get(models.DBEmployee, party_id) if party_id else None
        e = e or next((x for x in db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
                       if norm(employee_name(x)) == norm(party_name)), None)
        if e and e.client_id == client_id:
            return e.bank_account or "", e.bank_ifsc or "", "", e.email or ""
    return "", "", "", ""


def beneficiary_problem(account, ifsc, amount):
    if not re.sub(r"\s", "", account or ""):
        return "no bank account number on file"
    if not ifsc:
        return "no IFSC on file"
    if not IFSC_RE.match(ifsc.strip().upper()):
        return "IFSC %s is not of the right form" % ifsc
    if money(amount) <= 0:
        return "nothing to pay"
    return ""


# --- the bank's file ----------------------------------------------------------------------------------------------------

FORMATS = {
    "hdfc": "HDFC Bank - Enet bulk upload",
    "icici": "ICICI Bank - CIB bulk payments",
    "sbi": "SBI - CINB bulk upload",
    "axis": "Axis Bank - CIB bulk payments",
    "csv": "Any bank - plain spreadsheet",
}


def pay_mode(our_ifsc, their_ifsc, amount):
    """Within the bank when both accounts are at the same bank, RTGS from two lakh, NEFT below."""
    if our_ifsc and their_ifsc and our_ifsc[:4].upper() == their_ifsc[:4].upper():
        return "IFT"
    return "RTGS" if amount >= RTGS_FROM else "NEFT"


def _narr(batch, line, n=30):
    return re.sub(r"[^A-Za-z0-9 /.-]", " ", ("%s %s" % (batch.number, line.doc_number or line.party_name)))[:n].strip()


def file_rows(batch, lines, ours):
    """(header row or None, rows) in the batch's bank layout. ours: our bank account (number and IFSC)."""
    fmt = batch.bank_format
    on = date.fromisoformat(batch.pay_on[:10]) if batch.pay_on else date.today()
    our_no, our_ifsc = re.sub(r"\s", "", ours.account_no or ""), (ours.ifsc or "").upper()
    out = []
    for l in lines:
        acct, ifsc, amt = re.sub(r"\s", "", l.beneficiary_account), l.beneficiary_ifsc.upper(), "%.2f" % l.amount
        mode = pay_mode(our_ifsc, ifsc, l.amount)
        name = re.sub(r"[^A-Za-z0-9 .&-]", " ", l.party_name or "")[:35].strip()
        if fmt == "hdfc":
            # Enet, no header, 28 fields: type (N = NEFT, R = RTGS, I = within HDFC), beneficiary code, account, amount,
            # name, drawee and print location, address 1-5, instruction and customer reference, payment details 1-7,
            # cheque number, date, MICR, IFSC, bank, branch, email.
            row = [{"IFT": "I", "RTGS": "R"}.get(mode, "N"), "", acct, amt, name, "", ""] + [""] * 5 + \
                  [batch.number, _narr(batch, l, 20), _narr(batch, l)] + [""] * 6 + \
                  ["", on.strftime("%d/%m/%Y"), "", ifsc, l.beneficiary_bank[:40], "", l.beneficiary_email]
            out.append(row)
        elif fmt == "icici":
            out.append([our_no, acct, name, amt, {"IFT": "I", "RTGS": "R"}.get(mode, "N"), on.strftime("%d-%b-%Y"), ifsc,
                        "", "", "", l.beneficiary_email, "", "", "", "", _narr(batch, l)])
        elif fmt == "sbi":
            out.append([name, acct, ifsc, amt, {"IFT": "INTRA"}.get(mode, mode), _narr(batch, l), l.beneficiary_email])
        elif fmt == "axis":
            out.append([{"IFT": "FT"}.get(mode, mode), amt, on.strftime("%d-%m-%Y"), name, acct, ifsc, our_no,
                        batch.number, l.beneficiary_email, _narr(batch, l)])
        else:
            out.append([name, acct, ifsc, l.beneficiary_bank, amt, mode, on.isoformat(), _narr(batch, l), l.beneficiary_email])
    header = {
        "hdfc": None,
        "icici": ["Debit Ac No", "Beneficiary Ac No", "Beneficiary Name", "Amt", "Pay Mod", "Date", "IFSC", "Payable Location",
                  "Print Location", "Bene Mobile No.", "Bene Email ID", "Bene add1", "Bene add2", "Bene add3", "Bene add4", "Remarks"],
        "sbi": ["Beneficiary Name", "Beneficiary Account No", "IFSC", "Amount", "Transaction Type", "Narration", "Email"],
        "axis": ["Payment Mode", "Amount", "Value Date", "Beneficiary Name", "Beneficiary Account No", "IFSC", "Debit Account No",
                 "Customer Reference No", "Beneficiary Email", "Remarks"],
    }.get(fmt, ["Beneficiary Name", "Account No", "IFSC", "Bank", "Amount", "Mode", "Date", "Reference", "Email"])
    return header, out


def file_text(batch, lines, ours):
    header, rows = file_rows(batch, lines, ours)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    if header:
        w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def payable_items(db, client):
    """What can go in a payment file: approved payment requests waiting to be paid when payments need approval,
    otherwise every supplier and contractor bill (and approved expense claim) with money still to pay - with whose
    bank account it goes to, and why not when it cannot."""
    from app.routers.money import payables_payload
    from app.services import payment_requests as preq
    already = {(l.doc_type, l.doc_id) for l, b in db.query(DBPaymentBatchLine, DBPaymentBatch).join(
        DBPaymentBatch, DBPaymentBatch.id == DBPaymentBatchLine.batch_id).filter(
        DBPaymentBatch.client_id == client.id, DBPaymentBatch.status == "DRAFT").all()}
    rules = preq.approval_rules(db, client.id)
    items = []
    if rules["on"]:
        for r in db.query(models.DBPaymentRequest).filter(models.DBPaymentRequest.client_id == client.id,
                                                         models.DBPaymentRequest.status == "APPROVED").all():
            if r.doc_type in ("expense",):
                continue                         # an expense voucher is paid to whoever was there, not a bank account on file
            items.append({"doc_type": r.doc_type or "on_account", "doc_id": r.doc_id, "doc_number": r.doc_number or "",
                          "request_id": r.id, "request_number": r.number, "party_type": r.party_type or "",
                          "party_name": r.party_name or "", "party_id": r.party_id, "job_id": r.job_id, "amount": money(r.amount)})
    else:
        pay = payables_payload(db, client)
        for b in pay["bills"]:
            if b["doc_type"] not in ("supplier_bill", "sub_bill") or b["outstanding"] <= 0:
                continue
            items.append({"doc_type": b["doc_type"], "doc_id": b["id"], "doc_number": b["number"], "request_id": None,
                          "request_number": "", "party_type": "supplier" if b["doc_type"] == "supplier_bill" else "contractor",
                          "party_name": b["party"], "party_id": None, "job_id": None, "amount": b["outstanding"]})
        for c in db.query(DBExpenseClaim).filter(DBExpenseClaim.client_id == client.id, DBExpenseClaim.status == "APPROVED").all():
            left = claim_left(db, c)
            if left > 0:
                items.append({"doc_type": "expense_claim", "doc_id": c.id, "doc_number": c.number, "request_id": None, "request_number": "",
                              "party_type": "staff", "party_name": c.employee_name, "party_id": c.employee_id, "job_id": c.job_id, "amount": left})
    out = []
    for it in items:
        acct, ifsc, bank, email = beneficiary(db, client.id, it["party_type"], it["party_name"], it["party_id"])
        it.update(account=acct, ifsc=ifsc, bank=bank, email=email, problem=beneficiary_problem(acct, ifsc, it["amount"]),
                  in_a_file=(it["doc_type"], it["doc_id"]) in already and it["doc_id"] is not None)
        out.append(it)
    return {"items": out, "approval_on": bool(rules["on"])}


def make_batch(db, client, body, who):
    from app.services.money import refuse_if_locked
    acc = db.query(models.DBBankAccount).filter(models.DBBankAccount.id == int(body.get("account_id") or 0),
                                                models.DBBankAccount.client_id == client.id).first()
    if acc is None or acc.kind == "Cash":
        raise HTTPException(400, "Choose the bank account the money goes out of.")
    if not re.sub(r"\s", "", acc.account_no or ""):
        raise HTTPException(400, "%s has no account number on file; the bank's file needs it. Add it under Ledgers & Bank." % acc.name)
    fmt = (body.get("bank_format") or "csv").lower()
    if fmt not in FORMATS:
        raise HTTPException(400, "Choose the bank's layout.")
    on = _day(body.get("pay_on") or date.today().isoformat(), "The payment date")
    refuse_if_locked(db, client.id, on)
    wanted = body.get("items") or []
    if not wanted:
        raise HTTPException(400, "Choose the bills to pay.")
    known = {(i["doc_type"], i["doc_id"], i["request_id"]): i for i in payable_items(db, client)["items"]}
    lines, problems = [], []
    for w in wanted:
        key = (w.get("doc_type"), w.get("doc_id"), w.get("request_id"))
        it = known.get(key)
        if it is None:
            raise HTTPException(409, "%s is no longer waiting to be paid." % (w.get("doc_number") or "A bill"))
        if it["in_a_file"]:
            raise HTTPException(409, "%s is already in a payment file not yet paid." % (it["doc_number"] or it["party_name"]))
        amount = money(w.get("amount") or it["amount"])
        if amount <= 0 or amount > it["amount"] + 0.009:
            raise HTTPException(400, "%s: pay between 0 and %s." % (it["doc_number"] or it["party_name"], "{:,.2f}".format(it["amount"])))
        if it["request_id"] and abs(amount - it["amount"]) > 0.009:
            raise HTTPException(400, "%s: an approved request is paid in full, as approved." % it["request_number"])
        why = beneficiary_problem(it["account"], it["ifsc"], amount)
        if why:
            problems.append("%s - %s" % (it["party_name"], why))
            continue
        lines.append((it, amount))
    if problems:
        raise HTTPException(400, "Put their bank details in first: %s." % "; ".join(problems))
    b = DBPaymentBatch(client_id=client.id, number=next_number(db, DBPaymentBatch, client.id, "PB-"), account_id=acc.id,
                       bank_format=fmt, pay_on=on, note=(body.get("note") or "").strip()[:200], made_by_name=who)
    db.add(b)
    db.flush()
    for it, amount in lines:
        db.add(DBPaymentBatchLine(batch_id=b.id, doc_type=it["doc_type"], doc_id=it["doc_id"], doc_number=it["doc_number"],
                                  request_id=it["request_id"], party_type=it["party_type"], party_name=it["party_name"],
                                  job_id=it["job_id"], amount=amount, beneficiary_account=re.sub(r"\s", "", it["account"]),
                                  beneficiary_ifsc=it["ifsc"].strip().upper(), beneficiary_bank=it["bank"], beneficiary_email=it["email"]))
    db.flush()
    return b


def batch_or_404(db, client_id, bid):
    b = db.query(DBPaymentBatch).filter(DBPaymentBatch.id == bid, DBPaymentBatch.client_id == client_id).first()
    if not b:
        raise HTTPException(404, "Payment file not found")
    return b


def batch_lines(db, bid):
    return db.query(DBPaymentBatchLine).filter(DBPaymentBatchLine.batch_id == bid).order_by(DBPaymentBatchLine.id).all()


def batch_dict(db, b, accounts=None):
    ls = batch_lines(db, b.id)
    acc = (accounts or {}).get(b.account_id) or db.get(models.DBBankAccount, b.account_id)
    return {"id": b.id, "number": b.number, "account_id": b.account_id, "account": acc.name if acc else "", "bank_format": b.bank_format,
            "format_label": FORMATS.get(b.bank_format, b.bank_format), "pay_on": b.pay_on, "status": b.status, "note": b.note,
            "made_by_name": b.made_by_name, "made_at": b.made_at, "paid_by_name": b.paid_by_name, "paid_at": b.paid_at,
            "total": money(sum(l.amount or 0 for l in ls)), "count": len(ls),
            "lines": [{"id": l.id, "doc_type": l.doc_type, "doc_id": l.doc_id, "doc_number": l.doc_number, "party_type": l.party_type,
                       "party_name": l.party_name, "amount": money(l.amount), "account": l.beneficiary_account, "ifsc": l.beneficiary_ifsc,
                       "mode": pay_mode((acc.ifsc or "") if acc else "", l.beneficiary_ifsc, l.amount),
                       "status": l.status, "error": l.error, "entry_id": l.entry_id} for l in ls]}


def mark_paid(db, request, client, b, on, reference, who):
    """The bank has made the transfers: each line becomes a payment in the bank book. A line the rules refuse (paid
    already by hand, a contractor's papers lapsed) is kept as failed with the reason; the rest are paid."""
    from app.routers.money import record_money
    from app.schemas.money import MoneyIn
    if b.status != "DRAFT":
        raise HTTPException(409, "%s is %s." % (b.number, b.status.lower()))
    on = _day(on or b.pay_on, "The day the bank paid")
    bid, number, account_id = b.id, b.number, b.account_id
    ids = [l.id for l in batch_lines(db, bid) if l.status != "PAID"]
    paid = failed = 0
    for lid in ids:
        l = db.get(DBPaymentBatchLine, lid)
        body = MoneyIn(doc_type=l.doc_type, doc_id=l.doc_id, amount=l.amount, paid_on=on, mode="Bank transfer",
                       reference=(reference or number)[:80], account_id=account_id, note="Paid by bank file %s" % number,
                       request_id=l.request_id, direction="OUT", party_type=l.party_type, party_name=l.party_name, job_id=l.job_id)
        try:
            res = record_money(body, request, db)
            l = db.get(DBPaymentBatchLine, lid)
            l.status, l.entry_id, l.error = "PAID", res["entry"]["id"], ""
            paid += 1
        except HTTPException as exc:
            db.rollback()
            l = db.get(DBPaymentBatchLine, lid)
            l.status, l.error = "FAILED", str(exc.detail)[:300]
            failed += 1
        db.commit()
    b = db.get(DBPaymentBatch, bid)
    if failed == 0:
        b.status, b.paid_by_name, b.paid_at = "PAID", who, _now()
    db.commit()
    return paid, failed


# --- cheque books and post-dated cheques --------------------------------------------------------------------------------

def _leaf(reference):
    digits = re.sub(r"\D", "", reference or "")
    return int(digits) if digits and len(digits) <= 9 else None


def book_leaves(db, client_id, book):
    """Every leaf of a book: written (and what for), given post-dated, spoilt, or blank."""
    used = {}
    for e in db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.account_id == book.account_id,
                                                  models.DBMoneyEntry.mode == "Cheque", models.DBMoneyEntry.direction == "OUT").all():
        n = _leaf(e.reference)
        if n is not None and book.first_no <= n <= book.last_no:
            used[n] = {"status": "VOID" if e.voided else ("CLEARED" if e.cleared_on else "ISSUED"), "party": e.party_name or "",
                       "amount": money(e.amount), "date": e.paid_on or "", "ref": e.number or ""}
    for p in db.query(DBPostDatedCheque).filter(DBPostDatedCheque.client_id == client_id, DBPostDatedCheque.direction == "OUT",
                                                DBPostDatedCheque.account_id == book.account_id).all():
        n = _leaf(p.cheque_no)
        if n is not None and book.first_no <= n <= book.last_no and n not in used:
            used[n] = {"status": "POST-DATED" if p.status == "HELD" else p.status, "party": p.party_name, "amount": money(p.amount),
                       "date": p.cheque_date, "ref": "PDC"}
    for s in db.query(DBChequeSpoilt).filter(DBChequeSpoilt.book_id == book.id).all():
        used.setdefault(s.number, {"status": "SPOILT", "party": "", "amount": 0.0, "date": (s.created_at or "")[:10], "ref": s.reason})
    return [dict(number=n, **used.get(n, {"status": "BLANK", "party": "", "amount": 0.0, "date": "", "ref": ""}))
            for n in range(book.first_no, book.last_no + 1)]


def book_dict(db, client_id, book, accounts):
    leaves = book_leaves(db, client_id, book)
    blank = [l["number"] for l in leaves if l["status"] == "BLANK"]
    acc = accounts.get(book.account_id)
    return {"id": book.id, "account_id": book.account_id, "account": acc.name if acc else "", "first_no": book.first_no,
            "last_no": book.last_no, "received_on": book.received_on, "note": book.note, "leaves": len(leaves),
            "blank": len(blank), "next_leaf": blank[0] if blank else None,
            "spoilt": len([l for l in leaves if l["status"] == "SPOILT"])}


def add_book(db, client_id, body):
    acc = db.query(models.DBBankAccount).filter(models.DBBankAccount.id == int(body.get("account_id") or 0),
                                                models.DBBankAccount.client_id == client_id).first()
    if acc is None or acc.kind == "Cash":
        raise HTTPException(400, "Choose the bank account the cheque book is for.")
    try:
        first, last = int(body.get("first_no")), int(body.get("last_no"))
    except (TypeError, ValueError):
        raise HTTPException(400, "The first and last cheque numbers, as printed.")
    if first <= 0 or last < first or last - first > 999:
        raise HTTPException(400, "A cheque book runs from its first leaf to its last - at most a thousand leaves.")
    for b in db.query(DBChequeBook).filter(DBChequeBook.client_id == client_id, DBChequeBook.account_id == acc.id).all():
        if first <= b.last_no and b.first_no <= last:
            raise HTTPException(409, "Leaves %d to %d are already in a book for %s." % (b.first_no, b.last_no, acc.name))
    book = DBChequeBook(client_id=client_id, account_id=acc.id, first_no=first, last_no=last,
                        received_on=_day(body.get("received_on") or date.today().isoformat()), note=(body.get("note") or "")[:200])
    db.add(book)
    db.flush()
    return book


def spoil_leaf(db, client_id, book, number, reason, who):
    if not (book.first_no <= number <= book.last_no):
        raise HTTPException(400, "Leaf %d is not in this book (%d to %d)." % (number, book.first_no, book.last_no))
    if len((reason or "").strip()) < 3:
        raise HTTPException(400, "Say what happened to it: torn, written wrong, lost.")
    leaf = next(l for l in book_leaves(db, client_id, book) if l["number"] == number)
    if leaf["status"] != "BLANK":
        raise HTTPException(409, "Leaf %d is %s." % (number, leaf["status"].lower()))
    db.add(DBChequeSpoilt(book_id=book.id, number=number, reason=reason.strip()[:200], by_name=who))


def pdc_dict(p, accounts=None, jobs=None):
    acc = (accounts or {}).get(p.account_id)
    j = (jobs or {}).get(p.job_id)
    try:
        days = (date.fromisoformat(p.cheque_date[:10]) - date.today()).days
    except ValueError:
        days = None
    return {"id": p.id, "direction": p.direction, "cheque_no": p.cheque_no, "cheque_date": p.cheque_date, "drawn_on": p.drawn_on,
            "account_id": p.account_id, "account": acc.name if acc else "", "party_type": p.party_type, "party_name": p.party_name,
            "doc_type": p.doc_type, "doc_id": p.doc_id, "doc_number": p.doc_number, "job_id": p.job_id,
            "project": ("%s %s" % (j.number or "", j.name or "")).strip() if j else "", "amount": money(p.amount), "note": p.note,
            "status": p.status, "entry_id": p.entry_id, "closed_reason": p.closed_reason, "made_by_name": p.made_by_name,
            "days_to_go": days, "due": p.status == "HELD" and days is not None and days <= 0}


def add_pdc(db, client_id, body, who):
    from app.services.money import _doc_for
    from app.constants.money import PARTY_TYPES
    direction = (body.get("direction") or "").upper()
    if direction not in ("IN", "OUT"):
        raise HTTPException(400, "Is it a cheque we gave, or one we hold?")
    no = re.sub(r"\s", "", body.get("cheque_no") or "")
    if not no:
        raise HTTPException(400, "The cheque number.")
    on = _day(body.get("cheque_date"), "The date on the cheque")
    amount = money(body.get("amount") or 0)
    if amount <= 0:
        raise HTTPException(400, "How much is it for?")
    acc_id = int(body.get("account_id") or 0) or None
    if acc_id and not db.query(models.DBBankAccount).filter(models.DBBankAccount.id == acc_id, models.DBBankAccount.client_id == client_id).first():
        raise HTTPException(404, "That bank account is not on file.")
    if direction == "OUT" and not acc_id:
        raise HTTPException(400, "Which of our accounts is it drawn on?")
    p = DBPostDatedCheque(client_id=client_id, direction=direction, cheque_no=no[:20], cheque_date=on, drawn_on=(body.get("drawn_on") or "")[:80],
                          account_id=acc_id, amount=amount, note=(body.get("note") or "").strip()[:200], made_by_name=who)
    if body.get("doc_type") and body.get("doc_id"):
        doc, worth, way, ptype, pname, pid, job = _doc_for(db, client_id, body["doc_type"], int(body["doc_id"]))
        if way != direction:
            raise HTTPException(400, "%s is paid the other way." % (doc.number or "That bill"))
        p.doc_type, p.doc_id, p.doc_number, p.party_type, p.party_name, p.job_id = body["doc_type"], doc.id, doc.number or "", ptype, pname, job
    else:
        p.party_type = body.get("party_type") if body.get("party_type") in PARTY_TYPES else "other"
        p.party_name = (body.get("party_name") or "").strip()[:200]
        p.job_id = int(body.get("job_id") or 0) or None
        if not p.party_name:
            raise HTTPException(400, "Whose cheque is it, or who is it to?")
    if db.query(DBPostDatedCheque.id).filter(DBPostDatedCheque.client_id == client_id, DBPostDatedCheque.direction == direction,
                                             DBPostDatedCheque.cheque_no == p.cheque_no, DBPostDatedCheque.status == "HELD",
                                             DBPostDatedCheque.party_name == p.party_name).first():
        raise HTTPException(409, "Cheque %s is already on the list." % p.cheque_no)
    db.add(p)
    db.flush()
    return p


def pdc_or_404(db, client_id, pid):
    p = db.query(DBPostDatedCheque).filter(DBPostDatedCheque.id == pid, DBPostDatedCheque.client_id == client_id).first()
    if not p:
        raise HTTPException(404, "Cheque not found")
    return p


def bank_pdc(db, request, client, p, on, account_id):
    """Its day has come: ours presented by the payee, theirs deposited by us. It goes in the bank book now."""
    from app.routers.money import record_money
    from app.schemas.money import MoneyIn
    if p.status != "HELD":
        raise HTTPException(409, "Cheque %s is %s." % (p.cheque_no, p.status.lower()))
    on = _day(on or date.today().isoformat(), "The day it went through the bank")
    if on < p.cheque_date:
        raise HTTPException(409, "Cheque %s is dated %s; it cannot be banked before then." % (p.cheque_no, p.cheque_date))
    acc = int(account_id or 0) or p.account_id
    if not acc:
        raise HTTPException(400, "Which of our accounts did it go into?")
    pid = p.id
    res = record_money(MoneyIn(doc_type=p.doc_type or "on_account", doc_id=p.doc_id, amount=p.amount, paid_on=on, mode="Cheque",
                               reference=p.cheque_no, account_id=acc, note="Post-dated cheque %s%s" % (p.cheque_no, (" - " + p.note) if p.note else ""),
                               direction=p.direction, party_type=p.party_type, party_name=p.party_name, job_id=p.job_id), request, db)
    p = db.get(DBPostDatedCheque, pid)
    p.status, p.entry_id, p.account_id = "BANKED", res["entry"]["id"], acc
    db.commit()
    return p


# --- staff expense claims -----------------------------------------------------------------------------------------------

def claim_or_404(db, client_id, cid):
    c = db.query(DBExpenseClaim).filter(DBExpenseClaim.id == cid, DBExpenseClaim.client_id == client_id).first()
    if not c:
        raise HTTPException(404, "Expense claim not found")
    return c


def claim_paid(db, c):
    from app.services.crm import settled_on
    return settled_on(db, c.client_id, "expense_claim", c.id)


def claim_left(db, c):
    return money((c.amount or 0) - (c.against_advance or 0) - claim_paid(db, c))


def submit_claim(db, client_id, emp, body, who):
    from app.constants.money import EXPENSE_HEADS
    from app.services.hr import employee_name
    from app.services.money import refuse_if_locked
    on = _day(body.get("spent_on"), "The day it was spent")
    if on > date.today().isoformat():
        raise HTTPException(400, "A claim is for money already spent.")
    refuse_if_locked(db, client_id, on)
    head = next((h for h in EXPENSE_HEADS if h.lower() == (body.get("head") or "").strip().lower()), "")
    if not head:
        raise HTTPException(400, "What was it for? Choose a head.")
    amount = money(body.get("amount") or 0)
    if amount <= 0 or amount > 500000:
        raise HTTPException(400, "How much was spent?")
    what = (body.get("description") or "").strip()
    if len(what) < 3:
        raise HTTPException(400, "Say what it was: the bus from Vizag to site, lunch for the inspection team...")
    job = int(body.get("job_id") or 0) or None
    if job and not db.query(models.DBJob.id).filter(models.DBJob.id == job, models.DBJob.client_id == client_id).first():
        raise HTTPException(404, "Project not found")
    if emp is None:
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == int(body.get("employee_id") or 0),
                                                 models.DBEmployee.client_id == client_id).first()
        if emp is None:
            raise HTTPException(400, "Whose claim is it?")
    bill = (body.get("bill_no") or "").strip()[:60]
    if bill and db.query(DBExpenseClaim.id).filter(DBExpenseClaim.client_id == client_id, DBExpenseClaim.employee_id == emp.id,
                                                   DBExpenseClaim.bill_no == bill, DBExpenseClaim.amount == amount,
                                                   DBExpenseClaim.status.notin_(("REJECTED", "CANCELLED"))).first():
        raise HTTPException(409, "Bill %s for that amount has already been claimed." % bill)
    c = DBExpenseClaim(client_id=client_id, number=next_number(db, DBExpenseClaim, client_id, "EC-"), employee_id=emp.id,
                       employee_name=employee_name(emp), spent_on=on, head=head, job_id=job, amount=amount, description=what[:1000],
                       bill_no=bill)
    db.add(c)
    db.flush()
    return c


def decide_claim(db, c, approve, who, note, deciding_emp=None):
    if c.status != "SUBMITTED":
        raise HTTPException(409, "%s is %s." % (c.number, c.status.lower()))
    if deciding_emp is not None and deciding_emp.id == c.employee_id:
        raise HTTPException(403, "Your own claim is approved by somebody else.")
    if not approve and len((note or "").strip()) < 3:
        raise HTTPException(400, "Say why it is sent back.")
    if approve:
        from app.services.money import refuse_if_locked
        refuse_if_locked(db, c.client_id, c.spent_on, "booked")
    c.status = "APPROVED" if approve else "REJECTED"
    c.decided_by_name, c.decided_at, c.decision_note = who, _now(), (note or "").strip()[:300]


def staff_balance(db, client_id, name):
    """A member of staff's account: above nothing we owe them (claims not yet paid), below nothing they hold of ours
    (advances not yet spent, returned or set off)."""
    from app.services.crm import _ledger_rows
    return money(sum(r["billed"] - r["moved"] for r in _ledger_rows(db, client_id)
                     if r["party_type"] == "staff" and norm(r["party"]) == norm(name)))


def set_against_advance(db, c):
    """Settle the claim out of an advance the person holds, as far as it goes. Nothing moves in the bank: the claim,
    once approved, is owed to them, and the advance is owed by them - the two cancel in their account."""
    if c.status != "APPROVED":
        raise HTTPException(409, "%s is %s; only an approved claim is settled." % (c.number, c.status.lower()))
    left = claim_left(db, c)
    # The approved claim is already in their account as owed to them, so it has already been netted off the advance:
    # what they held before it is the advance showing now plus what is still open on this claim.
    held = money(left - staff_balance(db, c.client_id, c.employee_name))
    take = money(min(left, held))
    if take <= 0:
        raise HTTPException(409, "%s holds no advance to set it against. Reimburse it instead." % c.employee_name)
    c.against_advance = money((c.against_advance or 0) + take)
    if claim_left(db, c) <= 0.009:
        c.status = "SETTLED"
    return take


def claim_dict(c, jobs=None, photos=None):
    j = (jobs or {}).get(c.job_id)
    return {"id": c.id, "number": c.number, "employee_id": c.employee_id, "employee_name": c.employee_name, "spent_on": c.spent_on,
            "head": c.head, "job_id": c.job_id, "project": ("%s %s" % (j.number or "", j.name or "")).strip() if j else "",
            "amount": money(c.amount), "description": c.description, "bill_no": c.bill_no, "status": c.status,
            "submitted_at": c.submitted_at, "decided_by_name": c.decided_by_name, "decided_at": c.decided_at,
            "decision_note": c.decision_note, "against_advance": money(c.against_advance), "photos": (photos or {}).get(c.id, [])}


LIVE_CLAIMS = ("APPROVED", "SETTLED")


def claim_ledger_rows(db, client_id):
    """Approved claims in the staff ledger: owed to the person, until reimbursed or set against their advance."""
    return [{"party_type": "staff", "party": c.employee_name, "date": c.spent_on, "kind": "Expense claim", "number": c.number,
             "doc_type": "expense_claim", "doc_id": c.id, "billed": money(c.amount), "moved": 0.0, "job_id": c.job_id}
            for c in db.query(DBExpenseClaim).filter(DBExpenseClaim.client_id == client_id, DBExpenseClaim.status.in_(LIVE_CLAIMS)).all()]


def claims_by_job(db, client_id, job_ids=None):
    out = {}
    for jid, amount in db.query(DBExpenseClaim.job_id, DBExpenseClaim.amount).filter(
            DBExpenseClaim.client_id == client_id, DBExpenseClaim.status.in_(LIVE_CLAIMS), DBExpenseClaim.job_id.isnot(None)).all():
        if job_ids is None or jid in job_ids:
            out[jid] = out.get(jid, 0.0) + (amount or 0)
    return out
