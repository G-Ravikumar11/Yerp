"""Bank reconciliation and the cheque register.

The bank's statement is read in as it comes from the bank's site - Excel, old Excel or CSV, whatever the bank calls its
columns - and each line is matched to the entry in the books it is: the same account, the same direction, the same
amount, on or after the day it was entered (a cheque clears days after it is written), the cheque or UTR number in the
narration settling a tie. Matched, the entry is cleared on the bank's date. What is left over is the reconciliation:
cheques written and not yet presented, deposits not yet credited, and what the bank booked on its own (charges,
interest) - which can be booked from the line in one go.

A cheque register is every cheque written or received, with where it stands: pending, cleared, bounced, or stale -
written more than three months ago and never presented, so the bank will not honour it.
"""
import csv
import io
import re
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from app import models
from app.core.currency import money

MATCH_DAYS_BEFORE = 3       # a line may be dated a little before the entry (entered late in the books)
MATCH_DAYS_AFTER = 45       # and well after it (a cheque presented weeks later)
STALE_DAYS = 90             # a cheque is valid for three months

HEADS = {
    "date": ("txn date", "transaction date", "tran date", "value date", "date", "posting date", "value dt", "txn dt"),
    "narration": ("narration", "description", "particulars", "transaction details", "remarks", "details", "transaction remarks"),
    "reference": ("chq / ref", "chq/ref", "cheque no", "chq no", "chq. no", "ref no", "reference", "utr", "instrument", "chq"),
    "debit": ("withdrawal amt", "withdrawal", "debit amount", "debit", "dr amount", "dr", "withdrawals"),
    "credit": ("deposit amt", "deposit", "credit amount", "credit", "cr amount", "cr", "deposits"),
    "balance": ("closing balance", "balance", "running balance", "available balance"),
    "amount": ("amount", "transaction amount", "amt"),
    "drcr": ("dr/cr", "cr/dr", "type", "debit/credit", "dr / cr"),
}


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v
    return str(v).strip()


def _rows_of(data, name):
    """Every row of the first sheet (or the CSV), as lists of cells."""
    low = (name or "").lower()
    if low.endswith(".csv") or low.endswith(".txt"):
        text = data.decode("utf-8-sig", errors="replace")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    if low.endswith(".xls"):
        import xlrd
        book = xlrd.open_workbook(file_contents=data)
        sh = book.sheet_by_index(0)
        out = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                else:
                    row.append(cell.value)
            out.append(row)
        return out
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    except Exception:
        raise HTTPException(400, "Could not read that file. Download the statement from the bank as Excel (.xlsx or .xls) or CSV.")


def _norm(v):
    return re.sub(r"[^a-z/ ]", "", str(v or "").lower()).strip()


def _find_header(rows):
    """The row that names the columns, and which column is which. Banks put a title block above it."""
    for i, row in enumerate(rows[:40]):
        cells = [_norm(c) for c in row]
        cols = {}
        for key, names in HEADS.items():
            for j, c in enumerate(cells):
                if c and j not in cols.values() and any(c == n or (len(n) > 3 and c.startswith(n)) for n in names):
                    cols.setdefault(key, j)
                    break
        if "date" in cols and (("debit" in cols and "credit" in cols) or "amount" in cols):
            return i, cols
    raise HTTPException(400, "Could not find the statement's columns. It needs a date, and either Debit and Credit "
                             "(Withdrawal and Deposit) columns or an Amount column.")


def _date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"\d{5}(\.0+)?", s):                       # an Excel day number that came through as text
        return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    s = s.split(" ")[0] if re.match(r"\d{1,4}[-/.]", s) else s
    for f in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y",
              "%d-%b-%y", "%d %b %y", "%d/%b/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, f).date().isoformat()
        except ValueError:
            continue
    return ""


def _amount(v):
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return abs(float(v))
    s = str(v).replace(",", "").replace("₹", "").replace("INR", "").strip()
    s = re.sub(r"\s*(dr|cr)\.?$", "", s, flags=re.I)
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


def read_statement(data, name):
    """The statement's lines: date, narration, reference, debit, credit, balance. Rows that are not transactions
    (totals, opening balance, blank) are left out."""
    rows = _rows_of(data, name)
    head, cols = _find_header(rows)
    out = []
    for row in rows[head + 1:]:
        get = lambda k: _cell(row[cols[k]]) if k in cols and cols[k] < len(row) else ""
        on = _date(get("date"))
        if not on:
            continue
        narration = str(get("narration") or "")[:300]
        if "amount" in cols and not ("debit" in cols and "credit" in cols):
            amt = _amount(get("amount"))
            kind = str(get("drcr") or get("amount")).strip().lower()
            debit, credit = (amt, 0.0) if ("dr" in kind or "debit" in kind or str(get("amount")).strip().startswith("-")) else (0.0, amt)
        else:
            debit, credit = _amount(get("debit")), _amount(get("credit"))
        if not debit and not credit:
            continue
        bal = get("balance")
        out.append({"txn_date": on, "narration": narration, "reference": str(get("reference") or "")[:80],
                    "debit": money(debit), "credit": money(credit),
                    "balance": money(_amount(bal)) if bal not in ("", None) else None})
    if not out:
        raise HTTPException(400, "No transactions were found under the statement's headings.")
    return out


def bank_account_or_404(db, client_id, account_id):
    a = db.query(models.DBBankAccount).filter(models.DBBankAccount.id == account_id,
                                              models.DBBankAccount.client_id == client_id).first()
    if a is None:
        raise HTTPException(404, "That bank account is not on file.")
    return a


def import_statement(db, client_id, account, lines, file_name, who):
    """Store the lines not already stored (a statement downloaded twice, or overlapping months), then match.

    Lines are counted, not just compared: two identical lines in one file are two transactions (two equal charges on
    one day, on a statement without a balance column), so a line is skipped only while the account already holds as
    many lines like it as have been seen so far in this file."""
    have = Counter((l.txn_date, money(l.debit), money(l.credit), (l.narration or "")[:120],
                    money(l.balance) if l.balance is not None else None)
                   for l in db.query(models.DBBankStatementLine).filter(
                       models.DBBankStatementLine.client_id == client_id,
                       models.DBBankStatementLine.account_id == account.id).all())
    seen = Counter()
    added = 0
    for l in lines:
        key = (l["txn_date"], l["debit"], l["credit"], l["narration"][:120], l["balance"])
        seen[key] += 1
        if seen[key] <= have[key]:
            continue
        db.add(models.DBBankStatementLine(client_id=client_id, account_id=account.id, file_name=(file_name or "")[:200],
                                          imported_by_name=who, **l))
        added += 1
    db.flush()
    matched = auto_match(db, client_id, account)
    return added, len(lines) - added, matched


def _digits(s):
    return set(re.findall(r"\d{4,}", s or ""))


def _candidates(db, client_id, account):
    return db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.account_id == account.id,
        models.DBMoneyEntry.voided.isnot(True), models.DBMoneyEntry.statement_line_id.is_(None),
        (models.DBMoneyEntry.cleared_on.is_(None)) | (models.DBMoneyEntry.cleared_on == "")).all()


def score(line, e):
    """How well an entry fits a statement line; None when it cannot be the same money."""
    incoming = line.credit > 0                           # a credit on the statement is money into the account
    if (e.direction == "IN") != incoming or abs(money(e.amount) - money(line.credit or line.debit)) > 0.009:
        return None
    try:
        gap = (date.fromisoformat(line.txn_date) - date.fromisoformat(e.paid_on[:10])).days
    except ValueError:
        return None
    if gap < -MATCH_DAYS_BEFORE or gap > MATCH_DAYS_AFTER:
        return None
    ref = e.reference or ""
    named = bool(_digits(ref) & (_digits(line.narration) | _digits(line.reference)))
    return (0 if named else 1, abs(gap))                 # a cheque/UTR number in the narration first, then nearest day


def auto_match(db, client_id, account):
    """Every unmatched line with exactly one best entry is matched to it, best fits first, each entry used once."""
    lines = db.query(models.DBBankStatementLine).filter(
        models.DBBankStatementLine.client_id == client_id, models.DBBankStatementLine.account_id == account.id,
        models.DBBankStatementLine.status == "UNMATCHED").order_by(models.DBBankStatementLine.txn_date,
                                                                    models.DBBankStatementLine.id).all()
    by_money = {}                       # an entry can only be a line's if direction and amount agree: look in that bucket
    for e in _candidates(db, client_id, account):
        by_money.setdefault((e.direction == "IN", round(money(e.amount) * 100)), []).append(e)
    pairs = []
    for l in lines:
        for e in by_money.get((l.credit > 0, round(money(l.credit or l.debit) * 100)), ()):
            s = score(l, e)
            if s is not None:
                pairs.append((s, l.id, e.id, l, e))
    pairs.sort(key=lambda p: (p[0], p[1], p[2]))
    used_l, used_e, n = set(), set(), 0
    for _, lid, eid, l, e in pairs:
        if lid in used_l or eid in used_e:
            continue
        used_l.add(lid)
        used_e.add(eid)
        match(l, e)
        n += 1
    db.flush()
    return n


def match(line, e):
    line.status, line.entry_id = "MATCHED", e.id
    e.statement_line_id, e.cleared_on = line.id, line.txn_date


def unmatch(db, line):
    if line.entry_id:
        e = db.query(models.DBMoneyEntry).filter(models.DBMoneyEntry.id == line.entry_id).first()
        if e is not None:
            e.statement_line_id, e.cleared_on = None, ""
    line.status, line.entry_id = "UNMATCHED", None


def line_dict(l):
    return {"id": l.id, "txn_date": l.txn_date, "narration": l.narration or "", "reference": l.reference or "",
            "debit": money(l.debit), "credit": money(l.credit), "balance": l.balance, "status": l.status,
            "entry_id": l.entry_id, "file_name": l.file_name or ""}


def suggestions(db, client_id, account, lines):
    """For each unmatched line, the entries that could be it, best first - to match by hand."""
    entries = _candidates(db, client_id, account)
    out = {}
    for l in lines:
        fits = sorted(((score(l, e), e) for e in entries), key=lambda p: (p[0] is None, p[0] or (9, 9)))
        out[l.id] = [{"id": e.id, "number": e.number, "paid_on": e.paid_on, "party": e.party_name,
                      "reference": e.reference or ""} for s, e in fits if s is not None][:5]
    return out


def brs(db, client_id, account, as_of):
    """The bank reconciliation statement on a day: the balance in the books, the entries the bank has not moved by
    then (cheques not presented, deposits not credited), the balance the bank should show - and, when its statement
    is in, the balance it does show and any difference."""
    from app.services.money import account_balance, opening_day
    q = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client_id, models.DBMoneyEntry.account_id == account.id,
        models.DBMoneyEntry.voided.isnot(True), models.DBMoneyEntry.paid_on <= as_of)
    if opening_day(account):
        # The opening balance stands on the opening day: what moved before it is already inside that figure.
        q = q.filter(models.DBMoneyEntry.paid_on >= opening_day(account))
    entries = q.order_by(models.DBMoneyEntry.paid_on, models.DBMoneyEntry.id).all()
    books = money((account.opening_balance or 0) + sum(e.amount if e.direction == "IN" else -e.amount for e in entries))
    open_ = [e for e in entries if not e.cleared_on or e.cleared_on > as_of]
    issued = [e for e in open_ if e.direction == "OUT"]
    deposited = [e for e in open_ if e.direction == "IN"]
    bank = money(books + sum(e.amount for e in issued) - sum(e.amount for e in deposited))
    last = db.query(models.DBBankStatementLine).filter(
        models.DBBankStatementLine.client_id == client_id, models.DBBankStatementLine.account_id == account.id,
        models.DBBankStatementLine.txn_date <= as_of, models.DBBankStatementLine.balance.isnot(None)).order_by(
        models.DBBankStatementLine.txn_date.desc(), models.DBBankStatementLine.id.desc()).first()
    unbooked = db.query(models.DBBankStatementLine).filter(
        models.DBBankStatementLine.client_id == client_id, models.DBBankStatementLine.account_id == account.id,
        models.DBBankStatementLine.txn_date <= as_of, models.DBBankStatementLine.status == "UNMATCHED").all()
    row = lambda e: {"id": e.id, "number": e.number, "paid_on": e.paid_on, "party": e.party_name or "",
                     "mode": e.mode or "", "reference": e.reference or "", "amount": money(e.amount)}
    statement = money(last.balance) if last else None
    return {"as_of": as_of, "books": books, "today_books": account_balance(db, client_id, account),
            "not_presented": [row(e) for e in issued], "not_credited": [row(e) for e in deposited],
            "not_presented_total": money(sum(e.amount for e in issued)),
            "not_credited_total": money(sum(e.amount for e in deposited)),
            "bank_should_show": bank, "statement_balance": statement,
            "statement_date": last.txn_date if last else "",
            "difference": money(statement - bank) if statement is not None else None,
            "unbooked": [line_dict(l) for l in unbooked]}


def cheque_status(e, today):
    if e.voided:
        return "BOUNCED" if (e.void_reason or "").lower().startswith(("cheque bounced", "bounced")) else "CANCELLED"
    if e.cleared_on:
        return "CLEARED"
    try:
        if (today - date.fromisoformat(e.paid_on[:10])).days > STALE_DAYS:
            return "STALE"
    except ValueError:
        pass
    return "PENDING"
