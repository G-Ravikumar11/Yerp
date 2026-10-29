"""Document numbers for the Store module: GRN/CS01/26-27/00042 - type, store code, Indian financial year (April to
March), then a running number that restarts each year for each store and each kind of document."""
import re

from sqlalchemy.exc import IntegrityError

from app.core.dates import financial_year_label
from app.models.store_core import DBStore, DBStoreDocSequence, InvalidMovementError

_DOC_TYPE = re.compile(r"^[A-Z][A-Z0-9_]{1,11}$")


def _row(db, doc_type, store_id, fy):
    return (db.query(DBStoreDocSequence)
            .filter(DBStoreDocSequence.doc_type == doc_type, DBStoreDocSequence.store_id == store_id, DBStoreDocSequence.fy == fy)
            .with_for_update().first())


def next_doc_number(db, doc_type, store_id, *, on_date=None) -> str:
    """The next number for `doc_type` in this store, for the financial year of `on_date` (today when omitted).
    Takes a lock on the sequence row, so two documents never get the same number. Flushes; never commits - a document
    that is rolled back gives its number back."""
    if not _DOC_TYPE.match(doc_type or ""):
        raise InvalidMovementError("Document type must be capital letters, like GRN: %r" % (doc_type,))
    store = db.get(DBStore, store_id)
    if store is None:
        raise InvalidMovementError("Store %s does not exist." % store_id)
    fy = financial_year_label(on_date)[2:]         # 2026-27 -> 26-27
    row = _row(db, doc_type, store.id, fy)
    if row is None:
        try:
            with db.begin_nested():
                db.add(DBStoreDocSequence(doc_type=doc_type, store_id=store.id, fy=fy, last_no=0))
                db.flush()
        except IntegrityError:
            pass
        row = _row(db, doc_type, store.id, fy)
    row.last_no = (row.last_no or 0) + 1
    db.flush()
    return "%s/%s/%s/%05d" % (doc_type, store.code, fy, row.last_no)
