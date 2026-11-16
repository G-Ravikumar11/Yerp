"""Opening balances for parties: what a client, supplier or contractor owed - or was owed - on the day these books begin.

A company moving onto the ERP midway has parties with balances that no bill here explains: the supplier it still owes for
March's cement, the client who has not yet paid a bill raised on paper. Without a way to enter them, the party's ledger,
its statement of account, the balance sheet and Tally all start from nothing and are wrong from the first day.

An opening balance is one line at the head of the party's ledger (`_ledger_rows` reads it as billed, or as moved when it is
an advance), so everything that reads the ledger - the Parties list, the statement, the balance sheet, the supplier's own
portal - has it without being told. It goes to Tally as a journal against one offset ledger, the usual way a ledger's
opening balance is carried into a new set of books.

It does not touch the profit and loss: an opening balance is not income or cost, only what was already owed.
"""
import re
from datetime import datetime

from fastapi import HTTPException

from app import models
from app.core import checks
from app.core.auth import owned_or_404
from app.core.currency import money
from app.models.party_openings import DBPartyOpening

PARTY_TYPES = ("client", "supplier", "contractor")
SIDES = ("owed", "advance")
LARGEST = 100_000_000_000          # a hundred thousand crore: a slip of a zero, not a balance


def number_of(o):
    return "OB-%04d" % o.id


def _name(raw):
    return re.sub(r"\s+", " ", raw or "").strip()


def _key(name):
    from app.services.crm import norm_name
    return norm_name(name)


def effect(o):
    """What it does to the party's balance (billed less moved): up when it is owed, down when it is an advance."""
    return money(o.amount) if o.side == "owed" else -money(o.amount)


def wording(party_type, side):
    """What the balance means, in the words the party's own type uses."""
    if party_type == "client":
        return "They owe us" if side == "owed" else "They paid us ahead"
    return "We owe them" if side == "owed" else "We paid them ahead"


def opening_dict(o, jobs=None):
    job = (jobs or {}).get(o.job_id)
    return {"id": o.id, "number": number_of(o), "party_type": o.party_type, "party": o.party_name, "side": o.side,
            "means": wording(o.party_type, o.side), "amount": money(o.amount), "balance": effect(o), "as_on": o.as_on,
            "job_id": o.job_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "note": o.note or "", "created_by_name": o.created_by_name or "", "created_at": o.created_at or ""}


def one_dict(db, o):
    """One opening balance as the list gives it, its project named."""
    job = db.get(models.DBJob, o.job_id) if o.job_id else None
    return opening_dict(o, {job.id: job} if job else None)


def list_openings(db, client_id):
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    rows = db.query(DBPartyOpening).filter(DBPartyOpening.client_id == client_id).order_by(
        DBPartyOpening.as_on.desc(), DBPartyOpening.id.desc()).all()
    return [opening_dict(o, jobs) for o in rows]


def opening_or_404(db, client_id, opening_id):
    o = db.query(DBPartyOpening).filter(DBPartyOpening.id == opening_id, DBPartyOpening.client_id == client_id).first()
    if not o:
        raise HTTPException(404, "Opening balance not found")
    return o


def apply_opening(db, client_id, o, body, who, creating):
    """Check what the form sent and put it on the opening balance. On a change, what was left out stays as it was."""
    from app.services.money import refuse_if_locked

    def given(field):
        return getattr(body, field, None) is not None

    if creating or given("party_type"):
        if body.party_type not in PARTY_TYPES:
            raise HTTPException(400, "An opening balance is for a client, a supplier or a contractor.")
        o.party_type = body.party_type
    if creating or given("party_name"):
        name = _name(body.party_name)
        if not name:
            raise HTTPException(400, "Say whose balance it is.")
        if len(name) > 120:
            raise HTTPException(400, "The name is too long.")
        o.party_name = name
    if creating or given("side"):
        if body.side not in SIDES:
            raise HTTPException(400, "Say which way the balance runs.")
        o.side = body.side
    if creating or given("amount"):
        amount = checks.between(body.amount, "balance", 0, LARGEST, unit="rupees", blank_ok=False)
        if money(amount) <= 0:
            raise HTTPException(400, "The balance has to be more than nothing. A party who owes nothing needs no opening balance.")
        o.amount = money(amount)
    if creating or given("as_on"):
        o.as_on = checks.day(body.as_on, "date it stood at", required=True, not_future=True)
    if given("job_id"):
        o.job_id = owned_or_404(db, models.DBJob, client_id, body.job_id, "Project") or None
    elif creating:
        o.job_id = None
    if given("note"):
        o.note = _name(body.note)[:300]
    refuse_if_locked(db, client_id, o.as_on, "booked")
    # One opening balance for a party on a project: a second would double what they owed. Edit the first.
    for other in db.query(DBPartyOpening).filter(DBPartyOpening.client_id == client_id, DBPartyOpening.party_type == o.party_type,
                                                 DBPartyOpening.job_id.is_(None) if o.job_id is None else DBPartyOpening.job_id == o.job_id).all():
        if other.id != o.id and _key(other.party_name) == _key(o.party_name):
            raise HTTPException(409, "%s already has an opening balance (%s) %s. Change that one, so what they owed is not counted twice."
                                % (other.party_name, number_of(other), "for this project" if o.job_id else "for the head office"))
    if creating:
        o.created_by_name = who
    else:
        o.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def opening_ledger_rows(db, client_id):
    """Every opening balance as the first line of its party's ledger: billed when it is owed, moved when it is an advance."""
    rows = []
    for o in db.query(DBPartyOpening).filter(DBPartyOpening.client_id == client_id).all():
        rows.append({"party_type": o.party_type, "party": o.party_name, "date": o.as_on, "kind": "Opening balance",
                     "number": number_of(o), "doc_type": "opening", "doc_id": o.id,
                     "billed": money(o.amount) if o.side == "owed" else 0.0,
                     "moved": money(o.amount) if o.side == "advance" else 0.0,
                     "job_id": o.job_id, "against": (o.note or "")[:80]})
    return rows
