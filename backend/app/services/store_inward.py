"""Store module - inward slice (GRN, quality check, returns to supplier). Owned by P2.

Rules that matter:
  * Only a GRN line's ACCEPTED quantity reaches the stock ledger (GRN_IN, at the line's rate). Rejected goods are recorded
    on the line and never enter stock. Items that need a quality check must have it recorded before the GRN is approved.
  * A GRN line against a purchase order may not take the order past its quantity plus the item's over-receipt tolerance
    (posted receipts counted).
  * A purchase return sends accepted stock back (PURCHASE_RETURN_OUT, valued at the store's average) and, when it names a
    GRN line, cannot return more than that line accepted less what has already been returned.
  * Nothing here commits: the caller owns the transaction (see routers/store_inward.py).
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from fastapi import HTTPException

from app import models
from app.models.store_core import DBStore, DBStoreBin, DBStoreItemSettings, DocStatus, MovementType
from app.models.store_inward import (
    DBStoreGrn, DBStoreGrnLine, DBStoreInwardLog, DBStorePurchaseReturn, DBStorePurchaseReturnLine,
)
from app.schemas.store_contracts import PoLineReceipt
from app.services.stock_ledger import convert_to_base, post_movement, reverse_document
from app.services.store_numbering import next_doc_number

ZERO = Decimal("0")
_Q3, _R4 = Decimal("0.001"), Decimal("0.0001")
S = DocStatus

# status a document may move to, by the action name the screens use
NEXT = {"submit": (S.DRAFT, S.SUBMITTED), "approve": (S.SUBMITTED, S.APPROVED), "post": (S.APPROVED, S.POSTED)}


def dec(v, what="Quantity") -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        raise HTTPException(400, "%s is not a number." % what) from None


def q3(v) -> Decimal:
    return dec(v).quantize(_Q3, rounding=ROUND_HALF_UP)


def _po_base_qty(db, item_id, line) -> Decimal:
    """What a purchase-order line ordered, in the item's base unit (the line's own unit when no conversion is set)."""
    ordered = dec(line.qty or 0)
    try:
        return convert_to_base(db, item_id, ordered, line.uom or "")
    except Exception:
        return q3(ordered)


def _item_for_po_line(db, client_id, line) -> Optional[int]:
    if not line.item_code:
        return None
    it = db.query(models.DBItem).filter(models.DBItem.client_id == client_id, models.DBItem.item_code == line.item_code).first()
    return it.id if it else None


def _received(db, po_line_id, exclude_grn_id=None):
    """(received, accepted, rejected) base quantities on posted GRNs against a purchase-order line."""
    q = db.query(DBStoreGrnLine).join(DBStoreGrn, DBStoreGrn.id == DBStoreGrnLine.grn_id).filter(
        DBStoreGrnLine.po_line_id == po_line_id, DBStoreGrn.status == S.POSTED.value)
    if exclude_grn_id:
        q = q.filter(DBStoreGrn.id != exclude_grn_id)
    rows = q.all()
    return (sum((r.received_qty for r in rows), ZERO), sum((r.accepted_qty for r in rows), ZERO), sum((r.rejected_qty for r in rows), ZERO))


# ------------------------------------------------------------------------------------------------ cross-slice
def get_po_receipt_summary(db, po_id) -> List[PoLineReceipt]:
    """What has been received, accepted, rejected and is still pending on each line of a purchase order (posted GRNs only)."""
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None:
        return []
    out = []
    for line in db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po_id).order_by(
            models.DBPurchaseOrderLineItem.id).all():
        item_id = _item_for_po_line(db, po.client_id, line)
        ordered = _po_base_qty(db, item_id, line) if item_id else q3(line.qty or 0)
        got, ok, bad = _received(db, line.id)
        out.append(PoLineReceipt(po_line_id=line.id, item_id=item_id, ordered_qty=ordered, received_qty=got, accepted_qty=ok,
                                 rejected_qty=bad, pending_qty=max(ordered - ok, ZERO)))
    return out


def po_lines_for_receipt(db, client_id, po_id):
    """The lines of an approved purchase order with what is still to come, for starting a GRN from it."""
    po = db.get(models.DBPurchaseOrder, po_id)
    if po is None or po.client_id != client_id:
        raise HTTPException(404, "Purchase order not found")
    summary = {r.po_line_id: r for r in get_po_receipt_summary(db, po_id)}
    lines = []
    for line in db.query(models.DBPurchaseOrderLineItem).filter(models.DBPurchaseOrderLineItem.order_id == po_id).order_by(
            models.DBPurchaseOrderLineItem.id).all():
        r = summary[line.id]
        item = db.get(models.DBItem, r.item_id) if r.item_id else None
        st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == r.item_id).first() if r.item_id else None
        lines.append({"po_line_id": line.id, "item_id": r.item_id, "item_code": item.item_code if item else line.item_code,
                      "item_name": item.item_name if item else line.description, "po_uom": line.uom or "",
                      "base_uom": (st.base_uom if st else (item.units_of_measure if item else "")) or "", "ordered_qty": str(r.ordered_qty),
                      "received_qty": str(r.received_qty), "accepted_qty": str(r.accepted_qty), "pending_qty": str(r.pending_qty),
                      "price": str(dec(line.price or 0)), "in_item_master": item is not None})
    return {"po": {"id": po.id, "number": po.number, "supplier_name": po.supplier_name or "", "status": po.status, "project_id": po.job_id}, "lines": lines}


# ------------------------------------------------------------------------------------------------ shared
def log_status(db, doc_type, doc, new_status, actor, note=""):
    db.add(DBStoreInwardLog(doc_type=doc_type, doc_id=doc.id, from_status=doc.status or "", to_status=new_status, user_id=actor.user_id,
                            user_name=actor.name, note=note or ""))
    doc.status = new_status


def _bin_ok(db, store_id, bin_id):
    if bin_id and not db.query(DBStoreBin.id).filter(DBStoreBin.id == bin_id, DBStoreBin.store_id == store_id).first():
        raise HTTPException(400, "That bin is not in this store.")


def _item(db, client_id, item_id):
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id:
        raise HTTPException(404, "Item %s not found" % item_id)
    return item


def _date(v, what):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s must be a date like 2026-04-01." % what) from None


def _not_future(d, what):
    if d > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)


# ------------------------------------------------------------------------------------------------ GRN
def _fill_grn_lines(db, actor, grn, store, po, lines_in):
    """Replace the GRN's lines with `lines_in` (dicts), checking each one."""
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id).delete(synchronize_session=False)
    seen = set()
    for n, ln in enumerate(lines_in, 1):
        po_line = None
        if ln.get("po_line_id"):
            if po is None:
                raise HTTPException(400, "Line %d names a purchase-order line but the GRN has no purchase order." % n)
            po_line = db.get(models.DBPurchaseOrderLineItem, ln["po_line_id"])
            if po_line is None or po_line.order_id != po.id:
                raise HTTPException(400, "Line %d is not on purchase order %s." % (n, po.number))
            if ln["po_line_id"] in seen:
                raise HTTPException(400, "Purchase-order line %s appears twice." % ln["po_line_id"])
            seen.add(ln["po_line_id"])
        item = _item(db, actor.client.id, ln.get("item_id") or (_item_for_po_line(db, actor.client.id, po_line) if po_line else None))
        entered = q3(ln.get("qty"))
        if entered <= 0:
            raise HTTPException(400, "Line %d: the quantity must be more than zero." % n)
        uom = (ln.get("uom") or "").strip() or (po_line.uom if po_line else "")
        try:
            base = convert_to_base(db, item.id, entered, uom)
        except Exception as exc:
            raise HTTPException(400, "Line %d: %s" % (n, exc)) from None
        if base <= 0:
            raise HTTPException(400, "Line %d: that quantity is too small to count in the base unit." % n)
        rate_in = ln.get("rate")
        rate_entered = dec(rate_in, "Rate") if rate_in not in (None, "") else (dec(po_line.price or 0) if po_line else ZERO)
        if rate_entered < 0:
            raise HTTPException(400, "Line %d: the rate cannot be negative." % n)
        rate = (rate_entered * entered / base).quantize(_R4, rounding=ROUND_HALF_UP)
        _bin_ok(db, store.id, ln.get("bin_id"))
        st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == item.id).first()
        needs_qc = bool(st and st.qc_required)
        db.add(DBStoreGrnLine(grn_id=grn.id, po_line_id=po_line.id if po_line else None, item_id=item.id, uom=uom, entered_qty=entered,
                              received_qty=base, accepted_qty=ZERO if needs_qc else base, rejected_qty=ZERO, rate=rate,
                              bin_id=ln.get("bin_id") or None, batch_no=(ln.get("batch_no") or "").strip(), qc_done=not needs_qc,
                              remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def create_grn(db, actor, store, body) -> DBStoreGrn:
    po = None
    if body.get("po_id"):
        po = db.get(models.DBPurchaseOrder, body["po_id"])
        if po is None or po.client_id != actor.client.id:
            raise HTTPException(404, "Purchase order not found")
        if po.status not in ("Approved", "Closed"):
            raise HTTPException(400, "Purchase order %s is %s; only an approved order can be received against." % (po.number, po.status))
    grn_date = _date(body.get("grn_date") or date.today(), "GRN date")
    _not_future(grn_date, "GRN date")
    challan_date = _date(body["challan_date"], "Challan date") if body.get("challan_date") else None
    grn = DBStoreGrn(client_id=actor.client.id, store_id=store.id, grn_date=grn_date, po_id=po.id if po else None,
                     supplier_name=(body.get("supplier_name") or (po.supplier_name if po else "") or "").strip(),
                     challan_no=(body.get("challan_no") or "").strip(), challan_date=challan_date, vehicle_no=(body.get("vehicle_no") or "").strip(),
                     remarks=body.get("remarks") or "", status=S.DRAFT.value, created_by=actor.user_id, created_by_name=actor.name, number="")
    db.add(grn)
    db.flush()
    grn.number = next_doc_number(db, "GRN", store.id, on_date=grn_date)
    _fill_grn_lines(db, actor, grn, store, po, body.get("lines") or [])
    log_status(db, "GRN", grn, S.DRAFT.value, actor, "Created")
    return grn


def update_grn(db, actor, grn, store, body):
    if grn.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft GRN can be edited.")
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn.po_id else None
    if "grn_date" in body and body["grn_date"]:
        grn.grn_date = _date(body["grn_date"], "GRN date")
        _not_future(grn.grn_date, "GRN date")
    for f in ("supplier_name", "challan_no", "vehicle_no", "remarks"):
        if f in body and body[f] is not None:
            setattr(grn, f, body[f])
    if "challan_date" in body:
        grn.challan_date = _date(body["challan_date"], "Challan date") if body["challan_date"] else None
    if body.get("lines") is not None:
        _fill_grn_lines(db, actor, grn, store, po, body["lines"])


def _check_over_receipt(db, grn, lines):
    for ln in lines:
        if not ln.po_line_id:
            continue
        po_line = db.get(models.DBPurchaseOrderLineItem, ln.po_line_id)
        ordered = _po_base_qty(db, ln.item_id, po_line)
        st = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == ln.item_id).first()
        tol = dec(st.over_receipt_tolerance_pct or 0) if st else ZERO
        limit = (ordered * (1 + tol / 100)).quantize(_Q3, rounding=ROUND_HALF_UP)
        got = _received(db, ln.po_line_id, exclude_grn_id=grn.id)[0] + ln.received_qty
        if got > limit:
            raise HTTPException(409, "%s would take the order to %s against %s ordered (tolerance %s%%)." % (
                po_line.description or "A line", got, ordered, tol))


def grn_lines(db, grn):
    return db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == grn.id).order_by(DBStoreGrnLine.id).all()


def record_qc(db, actor, grn, results):
    """Record the quality check: per line, how much of what arrived is accepted and how much rejected (base unit)."""
    if grn.status not in (S.SUBMITTED.value, S.APPROVED.value):
        raise HTTPException(409, "The quality check is recorded on a submitted GRN, before it is posted.")
    lines = {l.id: l for l in grn_lines(db, grn)}
    for r in results:
        line = lines.get(r.get("line_id"))
        if line is None:
            raise HTTPException(400, "Line %s is not on this GRN." % r.get("line_id"))
        ok, bad = q3(r.get("accepted_qty")), q3(r.get("rejected_qty") or 0)
        if ok < 0 or bad < 0:
            raise HTTPException(400, "Quantities cannot be negative.")
        if ok + bad != line.received_qty:
            raise HTTPException(400, "Accepted %s + rejected %s must equal the %s received." % (ok, bad, line.received_qty))
        line.accepted_qty, line.rejected_qty, line.qc_done, line.qc_remarks = ok, bad, True, (r.get("remarks") or "").strip()


def grn_action(db, actor, grn, action, reason=""):
    """submit / approve / post / cancel. The caller commits (or rolls back on any error)."""
    lines = grn_lines(db, grn)
    store = db.get(DBStore, grn.store_id)
    if action == "cancel":
        return _cancel(db, actor, "GRN", grn, reason, lambda: _block_cancel_grn(db, grn))
    frm, to = NEXT[action]
    if grn.status != frm.value:
        raise HTTPException(409, "GRN %s is %s; it cannot be %s now." % (grn.number, grn.status, {"submit": "submitted", "approve": "approved", "post": "posted"}[action]))
    if action == "submit":
        if not lines:
            raise HTTPException(400, "A GRN needs at least one line.")
        _check_over_receipt(db, grn, lines)
    elif action == "approve":
        if any(not l.qc_done for l in lines):
            raise HTTPException(409, "Record the quality check on every line that needs one before approving.")
    else:
        if not any(l.accepted_qty > 0 for l in lines):
            raise HTTPException(400, "Nothing was accepted, so there is nothing to post.")
        _check_over_receipt(db, grn, lines)
        for l in lines:
            if l.accepted_qty > 0 and l.rate <= 0:
                raise HTTPException(400, "Every accepted line needs a rate before it is posted.")
        for l in lines:
            if l.accepted_qty > 0:
                post_movement(db, movement_type=MovementType.GRN_IN, store_id=store.id, item_id=l.item_id, qty=l.accepted_qty, rate=l.rate,
                              txn_date=grn.grn_date, project_id=store.project_id, ref_doc_type="GRN", ref_doc_id=grn.id, ref_line_id=l.id,
                              user_id=actor.user_id, remarks="GRN %s" % grn.number)
        grn.posted_at = datetime.now()
    log_status(db, "GRN", grn, to.value, actor)


def _block_cancel_grn(db, grn):
    live = db.query(DBStorePurchaseReturn).filter(DBStorePurchaseReturn.grn_id == grn.id, DBStorePurchaseReturn.status != S.CANCELLED.value).first()
    if live is not None:
        raise HTTPException(409, "Purchase return %s was made against this GRN; cancel it first." % live.number)


def _cancel(db, actor, doc_type, doc, reason, guard):
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is needed to cancel.")
    if doc.status == S.CANCELLED.value:
        raise HTTPException(409, "%s is already cancelled." % doc.number)
    if doc.status == S.POSTED.value:
        guard()
        # An all-rejected GRN or an empty return posted nothing, so it has nothing to undo.
        from app.models.store_core import DBStoreStockLedger
        if db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.ref_doc_type == doc_type, DBStoreStockLedger.ref_doc_id == doc.id).first():
            reverse_document(db, ref_doc_type=doc_type, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
    doc.cancel_reason = reason
    log_status(db, doc_type, doc, S.CANCELLED.value, actor, reason)


# ------------------------------------------------------------------------------------------------ purchase return
def _returned(db, grn_line_id, exclude_return_id=None):
    q = db.query(DBStorePurchaseReturnLine).join(DBStorePurchaseReturn, DBStorePurchaseReturn.id == DBStorePurchaseReturnLine.return_id).filter(
        DBStorePurchaseReturnLine.grn_line_id == grn_line_id, DBStorePurchaseReturn.status != S.CANCELLED.value)
    if exclude_return_id:
        q = q.filter(DBStorePurchaseReturn.id != exclude_return_id)
    return sum((r.qty for r in q.all()), ZERO)


def _fill_return_lines(db, actor, prn, store, grn, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    db.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id == prn.id).delete(synchronize_session=False)
    wanted = {}
    for n, ln in enumerate(lines_in, 1):
        gl = None
        if ln.get("grn_line_id"):
            gl = db.get(DBStoreGrnLine, ln["grn_line_id"])
            if gl is None or grn is None or gl.grn_id != grn.id:
                raise HTTPException(400, "Line %d is not on GRN %s." % (n, grn.number if grn else "(none)"))
        item = _item(db, actor.client.id, ln.get("item_id") or (gl.item_id if gl else None))
        if gl and gl.item_id != item.id:
            raise HTTPException(400, "Line %d: the item does not match the GRN line." % n)
        qty = q3(ln.get("qty"))
        if qty <= 0:
            raise HTTPException(400, "Line %d: the quantity must be more than zero." % n)
        if gl:
            wanted[gl.id] = wanted.get(gl.id, ZERO) + qty
            room = gl.accepted_qty - _returned(db, gl.id, exclude_return_id=prn.id)
            if wanted[gl.id] > room:
                raise HTTPException(409, "Line %d: only %s of that GRN line can still be returned." % (n, max(room, ZERO)))
        db.add(DBStorePurchaseReturnLine(return_id=prn.id, grn_line_id=gl.id if gl else None, item_id=item.id, qty=qty, remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def create_return(db, actor, store, body) -> DBStorePurchaseReturn:
    grn = None
    if body.get("grn_id"):
        grn = db.get(DBStoreGrn, body["grn_id"])
        if grn is None or grn.client_id != actor.client.id:
            raise HTTPException(404, "GRN not found")
        if grn.status != S.POSTED.value:
            raise HTTPException(409, "Only goods from a posted GRN can be returned.")
        if grn.store_id != store.id:
            raise HTTPException(400, "That GRN was received into a different store.")
    d = _date(body.get("return_date") or date.today(), "Return date")
    _not_future(d, "Return date")
    prn = DBStorePurchaseReturn(client_id=actor.client.id, store_id=store.id, return_date=d, grn_id=grn.id if grn else None,
                                supplier_name=(body.get("supplier_name") or (grn.supplier_name if grn else "") or "").strip(),
                                reason=(body.get("reason") or "").strip(), remarks=body.get("remarks") or "", status=S.DRAFT.value,
                                created_by=actor.user_id, created_by_name=actor.name, number="")
    if not prn.reason:
        raise HTTPException(400, "Say why the goods are being returned.")
    db.add(prn)
    db.flush()
    prn.number = next_doc_number(db, "PRN", store.id, on_date=d)
    _fill_return_lines(db, actor, prn, store, grn, body.get("lines") or [])
    log_status(db, "PRN", prn, S.DRAFT.value, actor, "Created")
    return prn


def update_return(db, actor, prn, store, body):
    if prn.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft return can be edited.")
    grn = db.get(DBStoreGrn, prn.grn_id) if prn.grn_id else None
    if body.get("return_date"):
        prn.return_date = _date(body["return_date"], "Return date")
        _not_future(prn.return_date, "Return date")
    for f in ("supplier_name", "reason", "remarks"):
        if f in body and body[f] is not None:
            setattr(prn, f, body[f])
    if not (prn.reason or "").strip():
        raise HTTPException(400, "Say why the goods are being returned.")
    if body.get("lines") is not None:
        _fill_return_lines(db, actor, prn, store, grn, body["lines"])


def return_lines(db, prn):
    return db.query(DBStorePurchaseReturnLine).filter(DBStorePurchaseReturnLine.return_id == prn.id).order_by(DBStorePurchaseReturnLine.id).all()


def return_action(db, actor, prn, action, reason=""):
    store = db.get(DBStore, prn.store_id)
    lines = return_lines(db, prn)
    if action == "cancel":
        return _cancel(db, actor, "PRN", prn, reason, lambda: None)
    frm, to = NEXT[action]
    if prn.status != frm.value:
        raise HTTPException(409, "Return %s is %s; it cannot be %s now." % (prn.number, prn.status, {"submit": "submitted", "approve": "approved", "post": "posted"}[action]))
    if action == "submit" and not lines:
        raise HTTPException(400, "A return needs at least one line.")
    if action == "post":
        for l in lines:
            if l.grn_line_id:                       # re-check: another return may have been posted since this was drafted
                gl = db.get(DBStoreGrnLine, l.grn_line_id)
                if l.qty > gl.accepted_qty - _returned(db, gl.id, exclude_return_id=prn.id):
                    raise HTTPException(409, "More than the GRN line accepted would be returned.")
        for l in lines:
            e = post_movement(db, movement_type=MovementType.PURCHASE_RETURN_OUT, store_id=store.id, item_id=l.item_id, qty=l.qty, rate=None,
                              txn_date=prn.return_date, project_id=store.project_id, ref_doc_type="PRN", ref_doc_id=prn.id, ref_line_id=l.id,
                              user_id=actor.user_id, remarks="Return %s: %s" % (prn.number, prn.reason))
            l.value = e.value
        prn.posted_at = datetime.now()
    log_status(db, "PRN", prn, to.value, actor)


# ------------------------------------------------------------------------------------------------ views
def doc_log(db, doc_type, doc_id):
    rows = db.query(DBStoreInwardLog).filter(DBStoreInwardLog.doc_type == doc_type, DBStoreInwardLog.doc_id == doc_id).order_by(DBStoreInwardLog.id).all()
    return [{"from": r.from_status, "to": r.to_status, "user": r.user_name, "at": r.at.isoformat() if r.at else None, "note": r.note} for r in rows]


def _item_info(db, ids):
    items = {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(ids or [0])).all()}
    sets = {s.item_id: s for s in db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id.in_(ids or [0])).all()}
    return items, sets


def _iso(d):
    return d.isoformat() if d else None


def grn_dict(db, grn, with_lines=True):
    store = db.get(DBStore, grn.store_id)
    po = db.get(models.DBPurchaseOrder, grn.po_id) if grn.po_id else None
    lines = grn_lines(db, grn)
    out = {"id": grn.id, "number": grn.number, "store_id": grn.store_id, "store_code": store.code, "store_name": store.name,
           "grn_date": _iso(grn.grn_date), "po_id": grn.po_id, "po_number": po.number if po else "", "supplier_name": grn.supplier_name or "",
           "challan_no": grn.challan_no or "", "challan_date": _iso(grn.challan_date), "vehicle_no": grn.vehicle_no or "",
           "remarks": grn.remarks or "", "status": grn.status, "cancel_reason": grn.cancel_reason or "", "created_by": grn.created_by_name or "",
           "created_at": _iso(grn.created_at), "line_count": len(lines),
           "total_value": str(sum((l.accepted_qty * l.rate for l in lines), ZERO).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))}
    if with_lines:
        items, sets = _item_info(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "po_line_id": l.po_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code,
                         "item_name": items[l.item_id].item_name, "base_uom": (sets[l.item_id].base_uom if l.item_id in sets else items[l.item_id].units_of_measure) or "",
                         "qc_required": bool(sets[l.item_id].qc_required) if l.item_id in sets else False, "uom": l.uom,
                         "entered_qty": str(l.entered_qty), "received_qty": str(l.received_qty), "accepted_qty": str(l.accepted_qty),
                         "rejected_qty": str(l.rejected_qty), "rate": str(l.rate), "bin_id": l.bin_id, "batch_no": l.batch_no or "",
                         "qc_done": bool(l.qc_done), "qc_remarks": l.qc_remarks or "", "remarks": l.remarks or ""} for l in lines]
        out["log"] = doc_log(db, "GRN", grn.id)
    return out


def return_dict(db, prn, with_lines=True):
    store = db.get(DBStore, prn.store_id)
    grn = db.get(DBStoreGrn, prn.grn_id) if prn.grn_id else None
    lines = return_lines(db, prn)
    out = {"id": prn.id, "number": prn.number, "store_id": prn.store_id, "store_code": store.code, "store_name": store.name,
           "return_date": _iso(prn.return_date), "grn_id": prn.grn_id, "grn_number": grn.number if grn else "", "supplier_name": prn.supplier_name or "",
           "reason": prn.reason or "", "remarks": prn.remarks or "", "status": prn.status, "cancel_reason": prn.cancel_reason or "",
           "created_by": prn.created_by_name or "", "created_at": _iso(prn.created_at), "line_count": len(lines),
           "total_value": str(sum((l.value for l in lines), ZERO))}
    if with_lines:
        items, sets = _item_info(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "grn_line_id": l.grn_line_id, "item_id": l.item_id, "item_code": items[l.item_id].item_code,
                         "item_name": items[l.item_id].item_name, "base_uom": (sets[l.item_id].base_uom if l.item_id in sets else items[l.item_id].units_of_measure) or "",
                         "qty": str(l.qty), "value": str(l.value), "remarks": l.remarks or ""} for l in lines]
        out["log"] = doc_log(db, "PRN", prn.id)
    return out
