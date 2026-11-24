"""A page of a Store document list, read in a fixed number of queries.

A list shows up to 200 documents, each with its line count, value and the names of what it points at (its store, purchase
order, project...). Built one document at a time that was three or four queries a row - 600 for a page of receipts. While
a list builds its rows inside `page(...)`:

- every line of every document on the page is read in one query, and the line readers (grn_lines, issue_lines, ...) answer
  from it, in the same order they would have read it;
- every row a document points at by a foreign key (its store, order, project, work order...) is read in one query per
  table and kept, so `db.get` finds it in the session instead of asking the database again.

Nothing is cached beyond the request: the page is dropped when the list is built, and a reader asked about a document not
on the page reads it as it always did.
"""
from contextlib import contextmanager

_KEY = "store_page_lines"


def cached_lines(db, line_model, doc_id):
    """The lines of a document on the page being built, or None to read them from the database as usual."""
    pages = db.info.get(_KEY)
    if not pages:
        return None
    by_doc = pages.get(line_model)
    if by_doc is None or doc_id not in by_doc:
        return None
    return list(by_doc[doc_id])


def referenced(db, model, rows, only=None):
    """Every row the given rows point at through a foreign key on `model` (to a table's id), one query per table."""
    if not rows:
        return []
    by_table = {m.local_table.name: m.class_ for m in model.registry.mappers}
    out = []
    for fk in model.__table__.foreign_keys:
        col = fk.parent.name
        if (only is not None and col not in only) or fk.column.name != "id" or col in ("client_id",):
            continue
        target = by_table.get(fk.column.table.name)
        ids = sorted({getattr(r, col) for r in rows if getattr(r, col, None)})
        for n in range(0, len(ids), 500):
            out += db.query(target).filter(target.id.in_(ids[n:n + 500])).all() if target is not None else []
    return out


@contextmanager
def page(db, kind, rows, order_by, follow=()):
    """Build a page of `kind` documents (`rows`) with their lines and what they point at read up front.

    `order_by` is the order the kind's own line reader uses (so the lines come back exactly as before); `follow` names
    further hops, as (model, column) pairs, read from the rows found on the way - a purchase return's receipt's order."""
    keep = list(rows)
    ids = [r.id for r in rows]
    by_doc = {i: [] for i in ids}
    if ids:
        fk = getattr(kind.line, kind.fk)
        for n in range(0, len(ids), 500):
            for l in db.query(kind.line).filter(fk.in_(ids[n:n + 500])).order_by(*order_by).all():
                by_doc[getattr(l, kind.fk)].append(l)
        found = referenced(db, kind.header, rows)
        keep += found
        for model, col in follow:
            keep += referenced(db, model, [x for x in found if isinstance(x, model)], only=(col,))
    keep += [l for ls in by_doc.values() for l in ls]
    pages = dict(db.info.get(_KEY) or {})
    before = db.info.get(_KEY)
    pages[kind.line] = by_doc
    db.info[_KEY] = pages
    try:
        yield keep                       # held for the life of the page, so the session keeps what was read
    finally:
        if before is None:
            db.info.pop(_KEY, None)
        else:
            db.info[_KEY] = before
