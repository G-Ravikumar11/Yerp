"""Store module - stock promised to approved indents. An approved indent that is still open or partly filled holds back what it has yet to be
issued, so the same stock is not given to someone else: available = on hand less reserved. An issue filling an indent uses its own reservation.
A leaf module over the tables; nothing here moves stock."""
from decimal import Decimal

from sqlalchemy import func, or_

from app.models.store_core import DocStatus
from app.models.store_outward import DBStoreIndent, DBStoreIndentLine, DBStoreIssue, DBStoreIssueLine

ZERO = Decimal("0")
LIVE_INDENT = ("OPEN", "PARTIAL")


def _live_indent_ids(db, store_ids, exclude_indent_id):
    q = db.query(DBStoreIndent.id).filter(DBStoreIndent.store_id.in_(store_ids), DBStoreIndent.status.in_(LIVE_INDENT),
                                         or_(DBStoreIndent.short_closed.is_(None), DBStoreIndent.short_closed == 0))
    if exclude_indent_id:
        q = q.filter(DBStoreIndent.id != exclude_indent_id)
    return [i for (i,) in q.all()]


def reserved_map(db, store_ids, item_ids=None, exclude_indent_id=None):
    """{(store_id, item_id): quantity still to be issued on open, approved indents}."""
    store_ids = list(store_ids)
    if not store_ids:
        return {}
    ids = _live_indent_ids(db, store_ids, exclude_indent_id)
    if not ids:
        return {}
    q = (db.query(DBStoreIndent.store_id, DBStoreIndentLine.item_id, func.sum(DBStoreIndentLine.approved_qty))
         .join(DBStoreIndentLine, DBStoreIndentLine.indent_id == DBStoreIndent.id)
         .filter(DBStoreIndent.id.in_(ids), DBStoreIndentLine.approved_qty.isnot(None)))
    if item_ids is not None:
        q = q.filter(DBStoreIndentLine.item_id.in_(list(item_ids) or [0]))
    approved = {(s, i): Decimal(str(n or 0)) for s, i, n in q.group_by(DBStoreIndent.store_id, DBStoreIndentLine.item_id).all()}
    if not approved:
        return {}
    q = (db.query(DBStoreIndent.store_id, DBStoreIndentLine.item_id, func.sum(DBStoreIssueLine.qty))
         .join(DBStoreIndentLine, DBStoreIndentLine.indent_id == DBStoreIndent.id)
         .join(DBStoreIssueLine, DBStoreIssueLine.indent_line_id == DBStoreIndentLine.id)
         .join(DBStoreIssue, DBStoreIssue.id == DBStoreIssueLine.issue_id)
         .filter(DBStoreIndent.id.in_(ids), DBStoreIssue.status == DocStatus.POSTED.value))
    if item_ids is not None:
        q = q.filter(DBStoreIndentLine.item_id.in_(list(item_ids) or [0]))
    issued = {(s, i): Decimal(str(n or 0)) for s, i, n in q.group_by(DBStoreIndent.store_id, DBStoreIndentLine.item_id).all()}
    out = {}
    for key, qty in approved.items():
        left = qty - issued.get(key, ZERO)
        if left > 0:
            out[key] = left
    return out


def reserved_qty(db, store_id, item_id, exclude_indent_id=None) -> Decimal:
    return reserved_map(db, [store_id], [item_id], exclude_indent_id).get((store_id, item_id), ZERO)
