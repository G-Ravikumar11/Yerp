"""What is already being bought: the thread from an indent to the enquiry raised for it and the purchase order awarded
from that, and the quantity still on its way.

An indent line the store cannot fill is bought through an enquiry, and the enquiry's award becomes purchase orders.
Each enquiry line names the indent line it was raised for; each purchase-order line names the enquiry line and the
indent line. With that thread kept, what is "short" is what nobody is buying yet - an indent asked for twice is not
bought twice, and the reorder list does not ask again for what is already coming.

On order = open enquiry lines (not yet awarded) + live purchase-order lines less what has been received on them, in the
item's base unit.
"""
from decimal import Decimal

from app import models
from app.models.store_outward import DBStoreIndentLine
from app.services.stock_ledger import InvalidMovementError, convert_to_base

ZERO = Decimal("0")
DEAD_PO = ("Cancelled", "Rejected", "Closed")


def _base(db, item_id, qty, uom):
    """`qty` in `uom` as the item's base unit; an unknown unit is taken as the base unit rather than dropped."""
    try:
        return convert_to_base(db, item_id, qty, uom or "")
    except InvalidMovementError:
        return Decimal(str(qty or 0))


def _items_by_code(db, client_id, codes):
    codes = {c for c in codes if c}
    if not codes:
        return {}
    return {i.item_code: i.id for i in db.query(models.DBItem.id, models.DBItem.item_code).filter(
        models.DBItem.client_id == client_id, models.DBItem.item_code.in_(codes)).all()}


def on_order(db, client_id):
    """Everything this company is already buying, in two views:

    ({indent_line_id: {"qty": base qty, "refs": ["RFQ-0003", "PO-0012"]}}, {item_id: base qty})."""
    from app.services.procurement import OrderPrefetch
    by_indent, by_item = {}, {}

    def add(item_id, indent_line_id, qty, ref):
        if qty <= 0:
            return
        if item_id:
            by_item[item_id] = by_item.get(item_id, ZERO) + qty
        if indent_line_id:
            slot = by_indent.setdefault(indent_line_id, {"qty": ZERO, "refs": []})
            slot["qty"] += qty
            if ref not in slot["refs"]:
                slot["refs"].append(ref)

    rfq_rows = (db.query(models.DBRfqLine, models.DBRfq.number).join(models.DBRfq, models.DBRfq.id == models.DBRfqLine.rfq_id)
                .filter(models.DBRfq.client_id == client_id, models.DBRfq.status == "OPEN", models.DBRfqLine.po_id.is_(None)).all())
    orders = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id,
                                                     models.DBPurchaseOrder.status.notin_(DEAD_PO)).all()
    pre = OrderPrefetch(db, orders) if orders else None
    po_rows = [(po, l) for po in orders for l in pre.lines.get(po.id, [])] if pre else []
    indent_ids = {l.indent_line_id for l, _n in rfq_rows if l.indent_line_id} | {l.indent_line_id for _p, l in po_rows if l.indent_line_id}
    indent_item = {i: it for i, it in db.query(DBStoreIndentLine.id, DBStoreIndentLine.item_id).filter(
        DBStoreIndentLine.id.in_(indent_ids or {0})).all()}
    code_item = _items_by_code(db, client_id, {l.item_code for l, _n in rfq_rows} | {l.item_code for _p, l in po_rows})

    for l, number in rfq_rows:
        item_id = indent_item.get(l.indent_line_id) or code_item.get(l.item_code)
        add(item_id, l.indent_line_id, _base(db, item_id, l.qty, l.uom) if item_id else Decimal(str(l.qty or 0)), number)
    for po, l in po_rows:
        left = max(0.0, (l.qty or 0) - pre.received(po.id).get(l.id, 0.0))
        item_id = l.item_id or indent_item.get(l.indent_line_id) or code_item.get(l.item_code)
        add(item_id, l.indent_line_id, _base(db, item_id, left, l.uom) if item_id else Decimal(str(left)), po.number or "PO")
    return by_indent, by_item


def check_indent_lines(db, client_id, lines):
    """The enquiry lines that name an indent line: each must be this company's, and not be bought already. Returns
    (lines to raise, [(description, refs)] left out because they are already on an enquiry or order)."""
    named = {l["indent_line_id"] for l in lines if l.get("indent_line_id")}
    if not named:
        return lines, []
    from app.models.store_outward import DBStoreIndent
    mine = {i for (i,) in db.query(DBStoreIndentLine.id).join(DBStoreIndent, DBStoreIndent.id == DBStoreIndentLine.indent_id)
            .filter(DBStoreIndent.client_id == client_id, DBStoreIndentLine.id.in_(named)).all()}
    if named - mine:
        from fastapi import HTTPException
        raise HTTPException(404, "That indent line is not on file.")
    buying, _ = on_order(db, client_id)
    keep, skipped = [], []
    for l in lines:
        got = buying.get(l.get("indent_line_id")) if l.get("indent_line_id") else None
        if got and got["qty"] > 0:
            skipped.append((l.get("description") or "", got["refs"]))
        else:
            keep.append(l)
    return keep, skipped
