"""Document numbers for the Store module: GRN/CS01/26-27/00042 - type, store code, Indian financial year (April to
March), then a running number that restarts each year for each store and each kind of document.

Safe under concurrency on Postgres and SQLite alike: the number is taken by one UPDATE ... SET last_no = last_no + 1
on the store + type + year row, which the database serialises (a row lock on Postgres, the single writer on SQLite),
and read back inside the same transaction. Two documents never get the same number, and a document that rolls back
gives its number back, because the increment rolls back with it."""
import re
from datetime import date, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.models.store_core import DBStore, DBStoreDocSequence, InvalidMovementError

_DOC_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{1,11}$")


def financial_year(on_date=None) -> str:
    """26-27 for any day from 1 April 2026 to 31 March 2027. Today when `on_date` is empty; an unreadable date is an
    error rather than quietly today, so a document is never numbered into the wrong year."""
    if on_date in (None, ""):
        d = date.today()
    elif isinstance(on_date, datetime):
        d = on_date.date()
    elif isinstance(on_date, date):
        d = on_date
    else:
        try:
            d = datetime.strptime(str(on_date)[:10], "%Y-%m-%d").date()
        except ValueError:
            raise InvalidMovementError("Not a date: %r" % (on_date,)) from None
    start = d.year if d.month >= 4 else d.year - 1
    return "%02d-%02d" % (start % 100, (start + 1) % 100)


def _bump(db, doc_type, store_id, fy) -> int:
    """Add one to the row's last_no and return the new value; 0 when there is no row yet."""
    hit = db.execute(update(DBStoreDocSequence)
                     .where(DBStoreDocSequence.doc_type == doc_type, DBStoreDocSequence.store_id == store_id,
                            DBStoreDocSequence.fy == fy)
                     .values(last_no=DBStoreDocSequence.last_no + 1)
                     .execution_options(synchronize_session=False)).rowcount
    if not hit:
        return 0
    return db.query(DBStoreDocSequence.last_no).filter(
        DBStoreDocSequence.doc_type == doc_type, DBStoreDocSequence.store_id == store_id,
        DBStoreDocSequence.fy == fy).scalar()


def next_doc_number(db, doc_type, store_id, *, on_date=None) -> str:
    """The next number for `doc_type` in this store, for the financial year of `on_date` (today when omitted).
    Takes a lock on the sequence row, so two documents never get the same number. Flushes; never commits - a document
    that is rolled back gives its number back."""
    if not _DOC_TYPE.match(doc_type or ""):
        raise InvalidMovementError("Document type must be capital letters, like GRN: %r" % (doc_type,))
    store = db.get(DBStore, store_id) if store_id else None
    if store is None:
        raise InvalidMovementError("Store %s does not exist." % store_id)
    fy = financial_year(on_date)
    n = _bump(db, doc_type, store.id, fy)
    if not n:
        # The first of its kind this year. Two may start it at once: the unique key lets one insert win, and the
        # other, finding the row there, takes the next number from it.
        try:
            with db.begin_nested():
                db.add(DBStoreDocSequence(doc_type=doc_type, store_id=store.id, fy=fy, last_no=1))
                db.flush()
            n = 1
        except IntegrityError:
            n = _bump(db, doc_type, store.id, fy)
    # Whatever this session already holds of the row is now behind the database; let it read again when asked.
    for obj in [o for o in db.identity_map.values() if isinstance(o, DBStoreDocSequence)]:
        db.expire(obj)
    return "%s/%s/%s/%05d" % (doc_type, store.code, fy, n)
