"""Serial codes and document numbers."""
import re
from datetime import datetime

from fastapi import HTTPException

from app import models

from app.core.dates import financial_year_label
from app.core.tenant_settings import tenant_setting


def invoice_prefix_for(db, client_id):
    """The tenant's own numbering prefix.

    Stored as a setting for a long time and read by nothing, so every tenant
    was stuck on INV- whatever they put in the box.
    """
    raw = str(tenant_setting(db, client_id, "invoice_prefix", "INV-")).strip()
    # A prefix has to be something numbers can follow, and the sequence reader
    # splits on "-", so keep it simple rather than accept anything at all.
    cleaned = "".join(c for c in raw if c.isalnum() or c in "-_/")[:12]
    return cleaned or "INV-"


def next_sequence_number(db, model, client_id, prefix, field="number"):
    """Next number in a per-tenant sequence, based on the highest number ever
    issued. Counting rows breaks as soon as one is deleted.

    `field` names the column holding the sequence (invoices and payslips call
    it `number`; job requisitions call it `reference`)."""
    column = getattr(model, field)
    rows = db.query(column).filter(model.client_id == client_id).all()
    max_num = 0
    for row in rows:
        num_str = getattr(row, field) or ""
        if not num_str.startswith(prefix):
            continue
        tail = num_str[len(prefix):].split("-")[0].strip()
        try:
            max_num = max(max_num, int(tail))
        except (TypeError, ValueError):
            continue
    return f"{prefix}{max_num + 1:04d}"


def allocate_job_number(db, client_id) -> str:
    last = db.query(models.DBJob).filter(
        models.DBJob.client_id == client_id).order_by(models.DBJob.id.desc()).first()
    if last and last.number:
        try:
            return f"JOB-{int(str(last.number).replace('JOB-', '').replace('JOB', '')) + 1:04d}"
        except (ValueError, TypeError):
            pass
    return "JOB-0001"


# ENTERING THIS DATA WITHOUT A SPREADSHEET
#
# A sheet is a poor instrument for master data: it happily accepts a code that
# already exists, a unit that is not a unit, or an FG code on a job that never
# sold it, and only says so afterwards. Entered here, the invalid options are
# never offered and the code is issued rather than typed, so those mistakes
# stop being possible instead of being caught. Upload stays for bulk migration
# out of another system.
#
# Six characters, issued in sequence, unique across the whole system.
#
# The alphabet is Crockford's base 32: the digits plus the letters, with I, L,
# O and U left out. I and 1, O and 0 are the pairs people mistype off a printed
# delivery note, and U is dropped because a random run of letters should not be
# able to spell something unfortunate. Thirty-two symbols in six places is a
# little over a billion codes, which is more than any one business will issue.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 6
CODE_CAPACITY = len(CODE_ALPHABET) ** CODE_LENGTH
# What a person might type instead, when reading a code off paper.
CODE_CONFUSIONS = {"I": "1", "L": "1", "O": "0", "U": "V"}


def encode_serial(number: int) -> str:
    """A counter as six symbols, most significant first, so codes sort in the
    order they were issued."""
    if number < 0 or number >= CODE_CAPACITY:
        raise HTTPException(500, "The code series is exhausted.")
    out = []
    for _ in range(CODE_LENGTH):
        number, remainder = divmod(number, len(CODE_ALPHABET))
        out.append(CODE_ALPHABET[remainder])
    return "".join(reversed(out))


def normalise_code(raw) -> str:
    """Read a code the way somebody typed it.

    Lower case, spaces and hyphens are tidied away, and the four characters
    that do not exist in the alphabet are mapped to the ones they are always
    mistaken for - so 'rm-0O1' finds RM001 rather than nothing.
    """
    text = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    return "".join(CODE_CONFUSIONS.get(c, c) for c in text)


def next_serial(db, series: str = "item") -> int:
    """Take the next number in a series, under a lock.

    SELECT ... FOR UPDATE holds the row for the length of the transaction, so
    two requests arriving together queue rather than both reading the same
    value. SQLite ignores the hint and serialises writes anyway.
    """
    row = db.query(models.DBCodeSequence).filter(
        models.DBCodeSequence.name == series).with_for_update().first()
    if not row:
        row = models.DBCodeSequence(name=series, next_value=1)
        db.add(row)
        db.flush()
    value = row.next_value or 1
    row.next_value = value + 1
    row.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return value


# STAFF COSTS - a bill raised by an employee, approved up the reporting line
#
# The money never moves here. Approval marks a bill "Approved for payment";
# finance still has to pay it through the existing bills screen. Rejection
# hands it back to whoever raised it, with the reason, to fix and send again.
def allocate_bill_number(db, client_id) -> str:
    last = db.query(models.DBBill).filter(
        models.DBBill.client_id == client_id).order_by(models.DBBill.id.desc()).first()
    if last and last.number:
        try:
            num = int(str(last.number).replace("BILL-", "").replace("BILL", ""))
            return f"BILL-{num + 1:04d}"
        except (ValueError, TypeError):
            pass
    return "BILL-0001"


# PURCHASE ORDERS
#
# The bill chain asks "should we have spent this" once the money is already
# owed. An order asks the same question while the answer can still change
# anything. Approved orders are committed cost on the job; when the bill turns
# up it is matched to the order and any overspend is flagged.
def allocate_po_number(db, client_id) -> str:
    last = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == client_id).order_by(
            models.DBPurchaseOrder.id.desc()).first()
    if last and last.number:
        try:
            return f"PO-{int(str(last.number).replace('PO-', '').replace('PO', '')) + 1:04d}"
        except (ValueError, TypeError):
            pass
    return "PO-0001"


def next_wo_number(db, client_id, department, on_date=None):
    """WO/2026-27/STP/001 - the serial runs per year and per department.

    Restarting the count each year and each discipline is what the site office
    already does on paper, and a number that does not match the file it is
    filed in is worse than no number at all.
    """
    year = financial_year_label(on_date)
    dept = re.sub(r"[^A-Z0-9]", "", (department or "GEN").upper())[:6] or "GEN"
    stem = "WO/%s/%s/" % (year, dept)
    highest = 0
    for (num,) in db.query(models.DBSubcontractOrder.wo_number).filter(
            models.DBSubcontractOrder.client_id == client_id,
            models.DBSubcontractOrder.wo_number.like(stem + "%")).all():
        match = re.search(r"(\d+)$", num or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return "%s%03d" % (stem, highest + 1)


# A receipt may only be taken against an order that was actually placed -
# see order_is_committed. Receiving against a draft would let material arrive
# for something nobody ever committed to buy.
def allocate_grn_number(db, client_id) -> str:
    last = db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.client_id == client_id).order_by(
            models.DBGoodsReceipt.id.desc()).first()
    if last and last.number:
        try:
            return "GRN-%04d" % (int(str(last.number).replace("GRN-", "")) + 1)
        except (ValueError, TypeError):
            pass
    return "GRN-0001"


def next_number(db, model, client_id, stem):
    n = db.query(model).filter(model.client_id == client_id).count() + 1
    return "%s-%04d" % (stem, n)
