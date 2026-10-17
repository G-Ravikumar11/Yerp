"""Store module - control slice (transfers, stock counts, adjustments, scrap). Owned by P4.

Rules that matter:
  * Transfer: POST takes the stock out of the sender (TRANSFER_OUT, at its average) and it is IN TRANSIT until the receiving
    store confirms (receive_transfer): what arrives goes in at the rate it left at (TRANSFER_IN); anything short goes back to the
    sender. Inter-project transfers and those of high value need store.control.approve_high_value to approve.
  * Count: creating a count FREEZES the store and snapshots the books; counters do not see the system quantity unless they hold
    store.control.reveal_count. Posting unfreezes and posts each difference (ADJUST_IN at the average / ADJUST_OUT).
  * Adjustment: STOCK (ADJUST_IN/OUT), WASTAGE (WASTAGE_OUT, charged to a project or cost head) or WRITEOFF (closes the
    outward slice's write-off requests; no stock moves because the material left the store when it was issued).
  * Scrap: SCRAP_OUT at book value; what it fetched is recorded on the line.
  * Nothing here commits: the caller owns the transaction (see routers/store_control.py).
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import List

from fastapi import HTTPException

from app import models
from app.models.store_core import (
    CostHead, DBStore, DBStoreBin, DBStoreFreeze, DBStoreItemSettings, DBStoreStockBalance, DocStatus, MovementType, StoreError,
)
from app.models.store_control import (
    AdjustmentReason, ScrapClass, WastageReason, DBStoreAdjustment, DBStoreAdjustmentLine, DBStoreControlLog, DBStoreCount, DBStoreCountLine, DBStoreScrap,
    DBStoreScrapLine, DBStoreTransfer, DBStoreTransferLine,
)
from app.schemas.store_contracts import CountVarianceLine, InTransitLine, ScrapLine
from app.services import store_outward
from app.services import store_inward
from app.services.stock_ledger import convert_to_base, freeze_store, get_balance, post_movement, reverse_document, unfreeze_store
from app.services.store_numbering import next_doc_number

ZERO = Decimal("0")
_Q3, _R4, _V2 = Decimal("0.001"), Decimal("0.0001"), Decimal("0.01")
S = DocStatus
HIGH_VALUE_LIMIT = Decimal("100000")        # a transfer, adjustment or count difference worth this much (or an inter-project transfer) needs approve_high_value
NEXT = {"submit": (S.DRAFT, S.SUBMITTED), "approve": (S.SUBMITTED, S.APPROVED), "post": (S.APPROVED, S.POSTED)}
PAST = {"submit": "submitted", "approve": "approved", "post": "posted"}


def dec(v, what="Quantity") -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        raise HTTPException(400, "%s is not a number." % what) from None


def q3(v) -> Decimal:
    return dec(v).quantize(_Q3, rounding=ROUND_HALF_UP)


def v2(v) -> Decimal:
    return dec(v).quantize(_V2, rounding=ROUND_HALF_UP)


def to_date(v, what):
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "%s must be a date like 2026-04-01." % what) from None


def _past(d, what):
    if d > date.today():
        raise HTTPException(400, "%s cannot be in the future." % what)
    return d


def _iso(d):
    return d.isoformat() if d else None


def log_status(db, doc_type, doc, new_status, actor, note=""):
    db.add(DBStoreControlLog(doc_type=doc_type, doc_id=doc.id, from_status=doc.status or "", to_status=new_status, user_id=actor.user_id,
                             user_name=actor.name, note=note or ""))
    doc.status = new_status


def doc_log(db, doc_type, doc_id):
    rows = db.query(DBStoreControlLog).filter(DBStoreControlLog.doc_type == doc_type, DBStoreControlLog.doc_id == doc_id).order_by(DBStoreControlLog.id).all()
    return [{"from": r.from_status, "to": r.to_status, "user": r.user_name, "at": _iso(r.at), "note": r.note} for r in rows]


def _item(db, client_id, item_id):
    item = db.get(models.DBItem, item_id) if item_id else None
    if item is None or item.client_id != client_id:
        raise HTTPException(404, "Item %s not found" % item_id)
    return item


def _qty(db, item, ln, n, key="qty"):
    """A line's quantity in the base unit (the line may name another unit with `uom`)."""
    typed = q3(ln.get(key))
    if typed <= 0:
        raise HTTPException(400, "Line %d: the quantity must be more than zero." % n)
    if not ln.get("uom"):
        return typed
    try:
        base = convert_to_base(db, item.id, typed, ln["uom"])
    except Exception as exc:
        raise HTTPException(400, "Line %d: %s" % (n, exc)) from None
    if base <= 0:
        raise HTTPException(400, "Line %d: that quantity is too small to count in the base unit." % n)
    return base


def _names(db, ids):
    return {i.id: i for i in db.query(models.DBItem).filter(models.DBItem.id.in_(ids or [0])).all()}


def _cancel(db, actor, doc_type, ref_type, doc, reason, guard=None, has_stock_effect=True):
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "A reason is needed to cancel.")
    if doc.status == S.CANCELLED.value:
        raise HTTPException(409, "%s is already cancelled." % doc.number)
    if doc.status == S.POSTED.value:
        if guard:
            guard()
        from app.models.store_core import DBStoreStockLedger
        if has_stock_effect and db.query(DBStoreStockLedger.id).filter(DBStoreStockLedger.ref_doc_type == ref_type, DBStoreStockLedger.ref_doc_id == doc.id).first():
            reverse_document(db, ref_doc_type=ref_type, ref_doc_id=doc.id, user_id=actor.user_id, reason=reason)
    doc.cancel_reason = reason
    log_status(db, doc_type, doc, S.CANCELLED.value, actor, reason)


def _step(doc, action, label):
    frm, to = NEXT[action]
    if doc.status != frm.value:
        raise HTTPException(409, "%s %s is %s; it cannot be %s now." % (label, doc.number, doc.status, PAST[action]))
    return to


def _avg(db, store_id, item_id):
    return get_balance(db, store_id, item_id).avg_rate


# =============================================================================================== transfer
def _transfer_lines(db, t):
    return db.query(DBStoreTransferLine).filter(DBStoreTransferLine.transfer_id == t.id).order_by(DBStoreTransferLine.id).all()


def _fill_transfer_lines(db, actor, t, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    db.query(DBStoreTransferLine).filter(DBStoreTransferLine.transfer_id == t.id).delete(synchronize_session=False)
    seen = set()
    for n, ln in enumerate(lines_in, 1):
        item = _item(db, actor.client.id, ln.get("item_id"))
        if item.id in seen:
            raise HTTPException(400, "Line %d: %s is already on the transfer." % (n, item.item_name))
        seen.add(item.id)
        db.add(DBStoreTransferLine(transfer_id=t.id, item_id=item.id, qty=_qty(db, item, ln, n), remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def _destination(db, actor, store, to_store_id):
    to = db.get(DBStore, to_store_id) if to_store_id else None
    if to is None or to.client_id != actor.client.id or not to.is_active:
        raise HTTPException(400, "Choose the store the stock is going to.")
    if to.id == store.id:
        raise HTTPException(400, "A transfer needs two different stores.")
    return to


def create_transfer(db, actor, store, body):
    to = _destination(db, actor, store, body.get("to_store_id"))
    d = _past(to_date(body.get("trf_date") or date.today(), "Date"), "Date")
    t = DBStoreTransfer(client_id=actor.client.id, store_id=store.id, to_store_id=to.id, trf_date=d, inter_project=(store.project_id != to.project_id),
                        vehicle_no=(body.get("vehicle_no") or "").strip(), driver_name=(body.get("driver_name") or "").strip(),
                        challan_no=(body.get("challan_no") or "").strip(), challan_date=to_date(body["challan_date"], "Challan date") if body.get("challan_date") else None,
                        remarks=body.get("remarks") or "", status=S.DRAFT.value, created_by=actor.user_id, created_by_name=actor.name, number="")
    db.add(t)
    db.flush()
    t.number = next_doc_number(db, "TRF", store.id, on_date=d)
    _fill_transfer_lines(db, actor, t, body.get("lines") or [])
    log_status(db, "TRF", t, S.DRAFT.value, actor, "Created")
    return t


def update_transfer(db, actor, t, store, body):
    if t.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft transfer can be edited.")
    if body.get("to_store_id"):
        to = _destination(db, actor, store, body["to_store_id"])
        t.to_store_id, t.inter_project = to.id, (store.project_id != to.project_id)
    if body.get("trf_date"):
        t.trf_date = _past(to_date(body["trf_date"], "Date"), "Date")
    for f in ("vehicle_no", "driver_name", "challan_no", "remarks"):
        if body.get(f) is not None:
            setattr(t, f, body[f])
    if "challan_date" in body:
        t.challan_date = to_date(body["challan_date"], "Challan date") if body["challan_date"] else None
    if body.get("lines") is not None:
        _fill_transfer_lines(db, actor, t, body["lines"])


def _transfer_value(db, t, lines):
    return sum((l.qty * _avg(db, t.store_id, l.item_id) for l in lines), ZERO).quantize(_V2, rounding=ROUND_HALF_UP)


def transfer_action(db, actor, t, action, reason="", can_high=False):
    lines = _transfer_lines(db, t)
    if action == "cancel":
        return _cancel(db, actor, "TRF", "TRANSFER", t, reason)
    to_status = _step(t, action, "Transfer")
    src, dst = db.get(DBStore, t.store_id), db.get(DBStore, t.to_store_id)
    if action == "submit":
        if not lines:
            raise HTTPException(400, "A transfer needs at least one line.")
    elif action == "approve":
        value = _transfer_value(db, t, lines)
        if (t.inter_project or value >= HIGH_VALUE_LIMIT) and not can_high:
            raise HTTPException(403, "This %s transfer (worth about %s) needs the right to approve high-value transfers." % ("inter-project" if t.inter_project else "high-value", value))
    else:
        for l in lines:
            e = post_movement(db, movement_type=MovementType.TRANSFER_OUT, store_id=src.id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=t.trf_date,
                              project_id=src.project_id, ref_doc_type="TRANSFER", ref_doc_id=t.id, ref_line_id=l.id, user_id=actor.user_id,
                              remarks="Transfer %s to %s" % (t.number, dst.code))
            l.rate, l.value = e.rate, e.value
        t.posted_at = datetime.now()
    log_status(db, "TRF", t, to_status.value, actor)


def _reason(code, enum, what):
    code = (code or "").strip().upper()
    try:
        return enum(code).value
    except ValueError:
        raise HTTPException(400, "%s must be one of %s." % (what, ", ".join(e.value for e in enum))) from None


def receive_transfer(db, actor, t, received, losses=None, remarks=""):
    """The receiving store confirms. `received` maps line id -> quantity that arrived (default: all of it). Whatever did not arrive
    is a loss in transit and must be given with a reason - `losses` maps line id -> {qty, reason, remarks}; if only `received` is
    given the shortfall is the loss. Received + loss must equal what was sent. The loss is posted as wastage once it is approved
    (approve_transfer_loss); until then it stays in the in-transit register."""
    losses = losses or {}
    if t.status != S.POSTED.value:
        raise HTTPException(409, "Transfer %s is %s; only a dispatched transfer can be received." % (t.number, t.status))
    if t.received_at is not None:
        raise HTTPException(409, "Transfer %s has already been received." % t.number)
    src, dst = db.get(DBStore, t.store_id), db.get(DBStore, t.to_store_id)
    day = date.today()
    lines = _transfer_lines(db, t)
    unknown = (set(received) | set(losses)) - {l.id for l in lines}
    if unknown:
        raise HTTPException(400, "Line %s is not on this transfer." % sorted(unknown)[0])
    plan = []
    for l in lines:
        loss_in = losses.get(l.id) or {}
        if l.id in received and received[l.id] not in (None, ""):
            got = q3(received[l.id])
        elif loss_in.get("qty") not in (None, ""):
            got = l.qty - q3(loss_in["qty"])
        else:
            got = l.qty
        loss = q3(loss_in["qty"]) if loss_in.get("qty") not in (None, "") else l.qty - got
        if got < 0 or loss < 0:
            raise HTTPException(400, "Received and lost quantities cannot be negative.")
        if got + loss != l.qty:
            raise HTTPException(400, "Received %s + lost in transit %s must equal the %s sent." % (got, loss, l.qty))
        reason = _reason(loss_in.get("reason"), WastageReason, "The reason for the loss") if loss > 0 else ""
        plan.append((l, got, loss, reason, (loss_in.get("remarks") or "").strip()))
    for l, got, loss, reason, note in plan:
        l.received_qty, l.loss_qty, l.loss_reason, l.loss_remarks = got, loss, reason, note
        if got > 0:
            post_movement(db, movement_type=MovementType.TRANSFER_IN, store_id=dst.id, item_id=l.item_id, qty=got, rate=l.rate, txn_date=day,
                          project_id=dst.project_id, ref_doc_type="TRANSFER", ref_doc_id=t.id, ref_line_id=l.id, user_id=actor.user_id,
                          remarks="Transfer %s from %s" % (t.number, src.code))
    t.received_at, t.received_by_name, t.received_on = datetime.now(), actor.name, day
    lost = [x for x in plan if x[2] > 0]
    t.loss_status = "PENDING" if lost else ""
    db.add(DBStoreControlLog(doc_type="TRF", doc_id=t.id, from_status=t.status, to_status=t.status, user_id=actor.user_id, user_name=actor.name,
                             note="Received%s%s" % (" - loss in transit awaiting approval" if lost else "", (": " + remarks) if remarks else "")))


def approve_transfer_loss(db, actor, t, can_high=False):
    """Approve the loss reported at receipt: the lost goods are posted as WASTAGE_OUT on the transfer document (they pass through the
    receiving store - TRANSFER_IN then WASTAGE_OUT - so the stock there is unchanged and the cost lands on its project)."""
    if t.loss_status != "PENDING":
        raise HTTPException(409, "Transfer %s has no loss waiting for approval." % t.number)
    dst = db.get(DBStore, t.to_store_id)
    lines = [l for l in _transfer_lines(db, t) if l.loss_qty > 0]
    worth = sum((l.loss_qty * l.rate for l in lines), ZERO).quantize(_V2, rounding=ROUND_HALF_UP)
    if worth >= HIGH_VALUE_LIMIT and not can_high:
        raise HTTPException(403, "A loss worth %s needs the right to approve high-value transfers." % worth)
    day = date.today()
    head = None if dst.project_id else CostHead.OVERHEAD.value
    for l in lines:
        post_movement(db, movement_type=MovementType.TRANSFER_IN, store_id=dst.id, item_id=l.item_id, qty=l.loss_qty, rate=l.rate, txn_date=day,
                      project_id=dst.project_id, ref_doc_type="TRANSFER", ref_doc_id=t.id, ref_line_id=l.id, user_id=actor.user_id,
                      remarks="Transfer %s: lost in transit, taken to wastage" % t.number)
        post_movement(db, movement_type=MovementType.WASTAGE_OUT, store_id=dst.id, item_id=l.item_id, qty=l.loss_qty, rate=None, txn_date=day,
                      project_id=dst.project_id, cost_head=head, ref_doc_type="TRANSFER", ref_doc_id=t.id, ref_line_id=l.id, user_id=actor.user_id,
                      remarks="Transfer %s: %s" % (t.number, l.loss_reason))
    t.loss_status, t.loss_approved_at, t.loss_approved_by_name = "APPROVED", datetime.now(), actor.name
    db.add(DBStoreControlLog(doc_type="TRF", doc_id=t.id, from_status=t.status, to_status=t.status, user_id=actor.user_id, user_name=actor.name,
                             note="Loss in transit approved and posted as wastage (%s)" % worth))


def get_in_transit(db, project_id=None) -> List[InTransitLine]:
    """Stock sent from one store and not yet accounted for: dispatched and not received, or received short with the loss not yet approved."""
    rows = db.query(DBStoreTransferLine, DBStoreTransfer).join(DBStoreTransfer, DBStoreTransfer.id == DBStoreTransferLine.transfer_id).filter(
        DBStoreTransfer.status == S.POSTED.value).order_by(DBStoreTransfer.trf_date, DBStoreTransferLine.id).all()
    out = []
    for l, t in rows:
        if t.received_at is None:
            qty = l.qty
        elif t.loss_status == "PENDING":
            qty = l.loss_qty
        else:
            continue
        if qty <= 0:
            continue
        if project_id and project_id not in {db.get(DBStore, t.store_id).project_id, db.get(DBStore, t.to_store_id).project_id}:
            continue
        out.append(InTransitLine(transfer_id=t.id, from_store_id=t.store_id, to_store_id=t.to_store_id, item_id=l.item_id, qty=qty, value=(qty * l.rate).quantize(_V2, rounding=ROUND_HALF_UP),
                                 dispatched_on=t.trf_date, inter_project=bool(t.inter_project)))
    return out


def transfer_dict(db, t, with_lines=True):
    src, dst = db.get(DBStore, t.store_id), db.get(DBStore, t.to_store_id)
    lines = _transfer_lines(db, t)
    state = "IN_TRANSIT" if (t.status == S.POSTED.value and t.received_at is None) else ("RECEIVED" if t.received_at else "")
    out = {"id": t.id, "number": t.number, "store_id": t.store_id, "store_code": src.code, "store_name": src.name, "to_store_id": t.to_store_id, "to_store_code": dst.code,
           "to_store_name": dst.name, "trf_date": _iso(t.trf_date), "inter_project": bool(t.inter_project), "vehicle_no": t.vehicle_no or "", "driver_name": t.driver_name or "",
           "challan_no": t.challan_no or "", "challan_date": _iso(t.challan_date), "remarks": t.remarks or "", "status": t.status, "transit": state,
           "loss_status": t.loss_status or "", "cancel_reason": t.cancel_reason or "", "created_by": t.created_by_name or "", "received_on": _iso(t.received_on),
           "received_by": t.received_by_name or "", "line_count": len(lines), "total_value": str(sum((l.value for l in lines), ZERO)),
           "loss_value": str(sum((l.loss_qty * l.rate for l in lines), ZERO).quantize(_V2, rounding=ROUND_HALF_UP))}
    if with_lines:
        items = _names(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "qty": str(l.qty),
                         "rate": str(l.rate), "value": str(l.value), "received_qty": str(l.received_qty) if l.received_qty is not None else None,
                         "loss_qty": str(l.loss_qty), "loss_reason": l.loss_reason or "", "loss_remarks": l.loss_remarks or "",
                         "on_hand": str(get_balance(db, t.store_id, l.item_id).qty), "remarks": l.remarks or ""} for l in lines]
        out["log"] = doc_log(db, "TRF", t.id)
    return out


# =============================================================================================== stock count
def count_lines(db, c):
    return db.query(DBStoreCountLine).filter(DBStoreCountLine.count_id == c.id).order_by(DBStoreCountLine.id).all()


def _snapshot_line(db, c, item_id):
    b = get_balance(db, c.store_id, item_id)
    db.add(DBStoreCountLine(count_id=c.id, item_id=item_id, system_qty=b.qty, system_value=b.value, avg_rate=b.avg_rate))


def create_count(db, actor, store, body):
    d = _past(to_date(body.get("count_date") or date.today(), "Date"), "Date")
    cats = [x.strip().upper() for x in (body.get("categories") or []) if x and x.strip()]
    from app.models.store_core import ItemCategory
    bad = [x for x in cats if x not in {e.value for e in ItemCategory}]
    if bad:
        raise HTTPException(400, "Unknown item category %s." % bad[0])
    bin_id = body.get("bin_id") or None
    if bin_id and not db.query(DBStoreBin.id).filter(DBStoreBin.id == bin_id, DBStoreBin.store_id == store.id).first():
        raise HTTPException(400, "That bin is not in this store.")
    c = DBStoreCount(client_id=actor.client.id, store_id=store.id, count_date=d, remarks=body.get("remarks") or "", status=S.DRAFT.value,
                     created_by=actor.user_id, created_by_name=actor.name, number="", categories=",".join(cats), bin_id=bin_id)
    db.add(c)
    db.flush()
    c.number = next_doc_number(db, "CNT", store.id, on_date=d)
    fr = freeze_store(db, store.id, "Stock count %s" % c.number, actor.user_id)       # nothing may move while the count is on
    c.freeze_id = fr.id
    wanted = body.get("item_ids")
    if wanted:
        for iid in dict.fromkeys(wanted):
            _item(db, actor.client.id, iid)
            _snapshot_line(db, c, iid)
    else:
        q = db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == store.id, DBStoreStockBalance.qty > 0)
        if cats:
            q = q.join(DBStoreItemSettings, DBStoreItemSettings.item_id == DBStoreStockBalance.item_id).filter(DBStoreItemSettings.category.in_(cats))
        for b in q.order_by(DBStoreStockBalance.item_id).all():
            _snapshot_line(db, c, b.item_id)
    db.flush()
    if not count_lines(db, c):
        raise HTTPException(400, "Nothing to count here%s; name the items to count." % (" in those categories" if cats else ""))
    log_status(db, "CNT", c, S.DRAFT.value, actor, "Created; store frozen")
    return c


def update_count(db, actor, c, store, body):
    """Enter what was counted: lines [{item_id, counted_qty, remarks}]. An item not on the sheet is added (found in the store)."""
    if c.status != S.DRAFT.value:
        raise HTTPException(409, "Counts can only be entered on a draft count sheet.")
    if body.get("remarks") is not None:
        c.remarks = body["remarks"]
    have = {l.item_id: l for l in count_lines(db, c)}
    for n, ln in enumerate(body.get("lines") or [], 1):
        item = _item(db, actor.client.id, ln.get("item_id"))
        line = have.get(item.id)
        if line is None:
            _snapshot_line(db, c, item.id)
            db.flush()
            line = [l for l in count_lines(db, c) if l.item_id == item.id][0]
            have[item.id] = line
        raw = ln.get("counted_qty")
        if raw in (None, ""):
            line.counted_qty = None
        else:
            q = q3(raw)
            if q < 0:
                raise HTTPException(400, "Line %d: a count cannot be negative." % n)
            line.counted_qty = q
        if ln.get("remarks") is not None:
            line.remarks = ln["remarks"]
    db.flush()


def request_recount(db, actor, c, line_ids, reason=""):
    """The reviewer is not satisfied with some counts: those lines go back to be counted again (the first count is kept) and the
    sheet returns to DRAFT for the counters. The store stays frozen."""
    if c.status != S.SUBMITTED.value:
        raise HTTPException(409, "A recount can be asked for on a submitted count; this one is %s." % c.status)
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "Say why a recount is needed.")
    lines = {l.id: l for l in count_lines(db, c)}
    chosen = [lines[i] for i in dict.fromkeys(line_ids or [])] if all(i in lines for i in (line_ids or [])) else None
    if not chosen:
        raise HTTPException(400, "Choose the lines to count again (they must be on this sheet).")
    for l in chosen:
        if l.first_count_qty is None:
            l.first_count_qty = l.counted_qty
        l.counted_qty, l.recount, l.recounts = None, True, (l.recounts or 0) + 1
        l.variance_qty, l.variance_value = ZERO, ZERO
    c.recount_rounds = (c.recount_rounds or 0) + 1
    log_status(db, "CNT", c, S.DRAFT.value, actor, "Recount asked for %d line(s): %s" % (len(chosen), reason))


def _variance(l):
    l.variance_qty = (l.counted_qty - l.system_qty) if l.counted_qty is not None else ZERO
    l.variance_value = (l.variance_qty * l.avg_rate).quantize(_V2, rounding=ROUND_HALF_UP)


def _release_freeze(db, c, actor):
    fr = db.get(DBStoreFreeze, c.freeze_id) if c.freeze_id else None
    if fr is not None and fr.unfrozen_at is None:
        unfreeze_store(db, c.store_id, actor.user_id)


def count_action(db, actor, c, action, reason="", can_high=False):
    lines = count_lines(db, c)
    if action == "cancel":
        def guard():
            pass
        _cancel(db, actor, "CNT", "COUNT", c, reason, guard)
        if c.status == S.CANCELLED.value:
            _release_freeze(db, c, actor)
        return
    to_status = _step(c, action, "Count")
    if action == "submit":
        missing = [l for l in lines if l.counted_qty is None]
        if missing:
            raise HTTPException(400, "%d item(s) have not been counted yet." % len(missing))
        for l in lines:
            l.recount = False
            _variance(l)
    elif action == "approve":
        worth = sum((abs(l.variance_value) for l in lines), ZERO)
        if worth >= HIGH_VALUE_LIMIT and not can_high:
            raise HTTPException(403, "Differences worth %s need the right to approve high-value adjustments." % worth)
    else:
        _release_freeze(db, c, actor)                    # the freeze goes first so the differences can post
        for l in lines:
            if l.variance_qty == 0:
                continue
            up = l.variance_qty > 0
            post_movement(db, movement_type=MovementType.ADJUST_IN if up else MovementType.ADJUST_OUT, store_id=c.store_id, item_id=l.item_id, qty=abs(l.variance_qty),
                          rate=l.avg_rate if up else None, txn_date=c.count_date, project_id=db.get(DBStore, c.store_id).project_id, ref_doc_type="COUNT",
                          ref_doc_id=c.id, ref_line_id=l.id, user_id=actor.user_id, remarks="Count %s: counted %s against %s" % (c.number, l.counted_qty, l.system_qty))
        c.posted_at = datetime.now()
    log_status(db, "CNT", c, to_status.value, actor)


def get_count_variances(db, store_id, from_date, to_date_) -> List[CountVarianceLine]:
    """What stock counts found against the books, between two dates (posted counts, differences only)."""
    q = db.query(DBStoreCountLine, DBStoreCount).join(DBStoreCount, DBStoreCount.id == DBStoreCountLine.count_id).filter(
        DBStoreCount.status == S.POSTED.value, DBStoreCountLine.variance_qty != 0)
    if store_id:
        q = q.filter(DBStoreCount.store_id == store_id)
    if from_date:
        q = q.filter(DBStoreCount.count_date >= to_date(from_date, "From date"))
    if to_date_:
        q = q.filter(DBStoreCount.count_date <= to_date(to_date_, "To date"))
    return [CountVarianceLine(count_id=c.id, item_id=l.item_id, system_qty=l.system_qty, counted_qty=l.counted_qty, variance_qty=l.variance_qty,
                              variance_value=l.variance_value) for l, c in q.order_by(DBStoreCount.count_date, DBStoreCountLine.id).all()]


def count_dict(db, c, with_lines=True, reveal=False):
    """`reveal` shows the books while counting; once the count is approved everyone sees the result."""
    store = db.get(DBStore, c.store_id)
    lines = count_lines(db, c)
    show = reveal or c.status in (S.APPROVED.value, S.POSTED.value, S.CANCELLED.value)
    counted = sum(1 for l in lines if l.counted_qty is not None)
    out = {"id": c.id, "number": c.number, "store_id": c.store_id, "store_code": store.code, "store_name": store.name, "count_date": _iso(c.count_date),
           "remarks": c.remarks or "", "status": c.status, "cancel_reason": c.cancel_reason or "", "created_by": c.created_by_name or "", "line_count": len(lines),
           "counted_count": counted, "revealed": show, "categories": [x for x in (c.categories or "").split(",") if x], "bin_id": c.bin_id,
           "bin_code": (db.get(DBStoreBin, c.bin_id).code if c.bin_id else ""), "recount_rounds": c.recount_rounds or 0,
           "variance_value": str(sum((l.variance_value for l in lines), ZERO)) if show else None}
    if with_lines:
        items = _names(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name,
                         "counted_qty": str(l.counted_qty) if l.counted_qty is not None else None, "remarks": l.remarks or "",
                         "first_count_qty": str(l.first_count_qty) if l.first_count_qty is not None else None, "recount": bool(l.recount), "recounts": l.recounts or 0,
                         "system_qty": str(l.system_qty) if show else None, "variance_qty": str(l.variance_qty) if show else None,
                         "variance_value": str(l.variance_value) if show else None} for l in lines]
        out["log"] = doc_log(db, "CNT", c.id)
    return out


# =============================================================================================== adjustment
KINDS = ("STOCK", "WASTAGE", "WRITEOFF")


def adjustment_lines(db, a):
    return db.query(DBStoreAdjustmentLine).filter(DBStoreAdjustmentLine.adjustment_id == a.id).order_by(DBStoreAdjustmentLine.id).all()


def _fill_adjustment_lines(db, actor, a, store, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    db.query(DBStoreAdjustmentLine).filter(DBStoreAdjustmentLine.adjustment_id == a.id).delete(synchronize_session=False)
    if a.kind == "WRITEOFF":
        open_ = {r.request_id: r for r in store_outward.list_writeoff_requests(db, "OPEN")}
        seen = set()
        for n, ln in enumerate(lines_in, 1):
            r = open_.get(ln.get("writeoff_request_id"))
            if r is None or r.store_id != store.id:
                raise HTTPException(400, "Line %d: that write-off request is not open in this store." % n)
            if r.request_id in seen:
                raise HTTPException(400, "Line %d: that request is on the adjustment twice." % n)
            seen.add(r.request_id)
            db.add(DBStoreAdjustmentLine(adjustment_id=a.id, item_id=r.item_id, direction="OUT", qty=r.qty, writeoff_request_id=r.request_id, remarks=r.reason))
        db.flush()
        return
    for n, ln in enumerate(lines_in, 1):
        item = _item(db, actor.client.id, ln.get("item_id"))
        direction = "OUT" if a.kind == "WASTAGE" else (ln.get("direction") or "").upper()
        if direction not in ("IN", "OUT"):
            raise HTTPException(400, "Line %d: choose whether stock goes IN or OUT." % n)
        rate = ZERO
        if direction == "IN" and ln.get("rate") not in (None, ""):
            rate = dec(ln["rate"], "Rate").quantize(_R4, rounding=ROUND_HALF_UP)
            if rate < 0:
                raise HTTPException(400, "Line %d: the rate cannot be negative." % n)
        db.add(DBStoreAdjustmentLine(adjustment_id=a.id, item_id=item.id, direction=direction, qty=_qty(db, item, ln, n), rate=rate, remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def _adj_header(db, actor, a, store, body):
    if body.get("reason") is not None:
        a.reason = body["reason"].strip()
    if not a.reason:
        raise HTTPException(400, "A remark is mandatory: say what happened.")
    if body.get("reason_code") is not None:
        a.reason_code = body["reason_code"]
    a.reason_code = _reason(a.reason_code, AdjustmentReason if a.kind == "STOCK" else WastageReason, "The reason code")
    if body.get("attachment_ref") is not None:
        a.attachment_ref = body["attachment_ref"].strip()
    if not a.attachment_ref:
        raise HTTPException(400, "Give the reference of the paper that supports this adjustment (report, survey note, photo).")
    if a.kind == "WASTAGE":
        pid = body.get("project_id") or a.project_id or store.project_id
        head = body.get("cost_head", a.cost_head)
        if pid and not db.query(models.DBJob.id).filter(models.DBJob.id == pid, models.DBJob.client_id == actor.client.id).first():
            raise HTTPException(404, "Project not found")
        if head:
            try:
                head = CostHead(head).value
            except ValueError:
                raise HTTPException(400, "Unknown cost head.") from None
        if not (pid or head):
            raise HTTPException(400, "Wastage is a cost: say which project or cost head bears it.")
        a.project_id, a.cost_head = pid, head


def create_adjustment(db, actor, store, body):
    kind = (body.get("kind") or "STOCK").upper()
    if kind not in KINDS:
        raise HTTPException(400, "Kind must be one of %s." % ", ".join(KINDS))
    d = _past(to_date(body.get("adj_date") or date.today(), "Date"), "Date")
    a = DBStoreAdjustment(client_id=actor.client.id, store_id=store.id, adj_date=d, kind=kind, status=S.DRAFT.value, created_by=actor.user_id,
                          created_by_name=actor.name, number="")
    db.add(a)
    db.flush()
    _adj_header(db, actor, a, store, body)
    a.number = next_doc_number(db, "ADJ", store.id, on_date=d)
    _fill_adjustment_lines(db, actor, a, store, body.get("lines") or [])
    log_status(db, "ADJ", a, S.DRAFT.value, actor, "Created")
    return a


def update_adjustment(db, actor, a, store, body):
    if a.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft adjustment can be edited.")
    if body.get("adj_date"):
        a.adj_date = _past(to_date(body["adj_date"], "Date"), "Date")
    _adj_header(db, actor, a, store, body)
    if body.get("lines") is not None:
        _fill_adjustment_lines(db, actor, a, store, body["lines"])


def _adjustment_value(db, a, lines):
    total = ZERO
    for l in lines:
        rate = l.rate if (l.direction == "IN" and l.rate > 0) else _avg(db, a.store_id, l.item_id)
        total += l.qty * rate
    return total.quantize(_V2, rounding=ROUND_HALF_UP)


def adjustment_action(db, actor, a, action, reason="", can_high=False):
    lines = adjustment_lines(db, a)
    if action == "cancel":
        def guard():
            if a.kind == "WRITEOFF":
                raise HTTPException(409, "A posted write-off cannot be undone: the requests it closed stay closed.")
        return _cancel(db, actor, "ADJ", "ADJUST", a, reason, guard, has_stock_effect=a.kind != "WRITEOFF")
    to_status = _step(a, action, "Adjustment")
    store = db.get(DBStore, a.store_id)
    if action == "submit":
        if not lines:
            raise HTTPException(400, "An adjustment needs at least one line.")
    elif action == "approve":
        worth = _adjustment_value(db, a, lines)
        a.high_value = worth >= HIGH_VALUE_LIMIT
        if a.high_value and not can_high:
            raise HTTPException(403, "An adjustment worth %s needs the right to approve high-value adjustments." % worth)
    else:
        for l in lines:
            if a.kind == "WRITEOFF":
                store_outward.close_writeoff_request(db, l.writeoff_request_id, "ADJUST", a.id, actor.user_id)
                l.rate = _avg(db, a.store_id, l.item_id)
                l.value = (l.qty * l.rate).quantize(_V2, rounding=ROUND_HALF_UP)
                continue
            if l.direction == "IN":
                rate = l.rate if l.rate > 0 else _avg(db, a.store_id, l.item_id)
                if rate <= 0:
                    raise HTTPException(400, "Give a rate for stock being added where the store has none of the item.")
                e = post_movement(db, movement_type=MovementType.ADJUST_IN, store_id=store.id, item_id=l.item_id, qty=l.qty, rate=rate, txn_date=a.adj_date,
                                  project_id=store.project_id, ref_doc_type="ADJUST", ref_doc_id=a.id, ref_line_id=l.id, user_id=actor.user_id, remarks=a.reason)
            else:
                wastage = a.kind == "WASTAGE"
                e = post_movement(db, movement_type=MovementType.WASTAGE_OUT if wastage else MovementType.ADJUST_OUT, store_id=store.id, item_id=l.item_id, qty=l.qty,
                                  rate=None, txn_date=a.adj_date, project_id=(a.project_id or store.project_id), cost_head=a.cost_head if wastage else None,
                                  ref_doc_type="ADJUST", ref_doc_id=a.id, ref_line_id=l.id, user_id=actor.user_id, remarks=a.reason)
            l.rate, l.value = e.rate, e.value
        a.posted_at = datetime.now()
    log_status(db, "ADJ", a, to_status.value, actor)


def adjustment_dict(db, a, with_lines=True):
    store = db.get(DBStore, a.store_id)
    lines = adjustment_lines(db, a)
    job = db.get(models.DBJob, a.project_id) if a.project_id else None
    out = {"id": a.id, "number": a.number, "store_id": a.store_id, "store_code": store.code, "store_name": store.name, "adj_date": _iso(a.adj_date), "kind": a.kind,
           "reason": a.reason or "", "reason_code": a.reason_code or "", "attachment_ref": a.attachment_ref or "", "project_id": a.project_id, "project_name": job.name if job else "", "cost_head": a.cost_head, "high_value": bool(a.high_value),
           "status": a.status, "cancel_reason": a.cancel_reason or "", "created_by": a.created_by_name or "", "line_count": len(lines),
           "total_value": str(sum((l.value for l in lines), ZERO))}
    if with_lines:
        items = _names(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "direction": l.direction,
                         "qty": str(l.qty), "rate": str(l.rate), "value": str(l.value), "writeoff_request_id": l.writeoff_request_id, "remarks": l.remarks or ""} for l in lines]
        out["log"] = doc_log(db, "ADJ", a.id)
    return out


# =============================================================================================== scrap
def scrap_lines(db, s):
    return db.query(DBStoreScrapLine).filter(DBStoreScrapLine.scrap_id == s.id).order_by(DBStoreScrapLine.id).all()


def _fill_scrap_lines(db, actor, s, lines_in):
    if not lines_in:
        raise HTTPException(400, "Add at least one line.")
    db.query(DBStoreScrapLine).filter(DBStoreScrapLine.scrap_id == s.id).delete(synchronize_session=False)
    for n, ln in enumerate(lines_in, 1):
        item = _item(db, actor.client.id, ln.get("item_id"))
        klass = _reason(ln.get("scrap_class") or ScrapClass.OTHER.value, ScrapClass, "The scrap class")
        realised = v2(ln.get("realised_value") or 0)
        if realised < 0:
            raise HTTPException(400, "Line %d: the amount realised cannot be negative." % n)
        db.add(DBStoreScrapLine(scrap_id=s.id, item_id=item.id, qty=_qty(db, item, ln, n), scrap_class=klass, realised_value=realised, remarks=(ln.get("remarks") or "").strip()))
    db.flush()


def _scrap_header(db, actor, s, store, body):
    pid = body.get("project_id") or s.project_id or store.project_id
    if pid and not db.query(models.DBJob.id).filter(models.DBJob.id == pid, models.DBJob.client_id == actor.client.id).first():
        raise HTTPException(404, "Project not found")
    s.project_id = pid
    for f in ("buyer", "reason", "gate_pass_no"):
        if body.get(f) is not None:
            setattr(s, f, body[f].strip())
    if not s.reason:
        raise HTTPException(400, "Say why the material is scrap.")


def create_scrap(db, actor, store, body):
    d = _past(to_date(body.get("scrap_date") or date.today(), "Date"), "Date")
    s = DBStoreScrap(client_id=actor.client.id, store_id=store.id, scrap_date=d, status=S.DRAFT.value, created_by=actor.user_id, created_by_name=actor.name, number="")
    db.add(s)
    db.flush()
    _scrap_header(db, actor, s, store, body)
    s.number = next_doc_number(db, "SCR", store.id, on_date=d)
    _fill_scrap_lines(db, actor, s, body.get("lines") or [])
    log_status(db, "SCR", s, S.DRAFT.value, actor, "Created")
    return s


def update_scrap(db, actor, s, store, body):
    if s.status != S.DRAFT.value:
        raise HTTPException(409, "Only a draft scrap note can be edited.")
    if body.get("scrap_date"):
        s.scrap_date = _past(to_date(body["scrap_date"], "Date"), "Date")
    _scrap_header(db, actor, s, store, body)
    if body.get("lines") is not None:
        _fill_scrap_lines(db, actor, s, body["lines"])


def scrap_action(db, actor, s, action, reason=""):
    lines = scrap_lines(db, s)
    if action == "cancel":
        return _cancel(db, actor, "SCR", "SCRAP", s, reason)
    to_status = _step(s, action, "Scrap note")
    if action == "submit":
        if not lines:
            raise HTTPException(400, "A scrap note needs at least one line.")
        if not (s.buyer or "").strip():
            raise HTTPException(400, "Name the buyer or the party the scrap goes to.")
        if not (s.gate_pass_no or "").strip():
            raise HTTPException(400, "Give the gate pass number the scrap leaves under.")
    if action == "post":
        for l in lines:
            e = post_movement(db, movement_type=MovementType.SCRAP_OUT, store_id=s.store_id, item_id=l.item_id, qty=l.qty, rate=None, txn_date=s.scrap_date,
                              project_id=s.project_id, ref_doc_type="SCRAP", ref_doc_id=s.id, ref_line_id=l.id, user_id=actor.user_id, remarks="Scrap %s: %s" % (s.number, s.reason))
            l.book_value = e.value
        s.posted_at = datetime.now()
    log_status(db, "SCR", s, to_status.value, actor)


def get_scrap_realisation(db, project_id, from_date, to_date_) -> List[ScrapLine]:
    """Scrap taken out for a project: book value against what it fetched (posted scrap notes)."""
    q = db.query(DBStoreScrapLine, DBStoreScrap).join(DBStoreScrap, DBStoreScrap.id == DBStoreScrapLine.scrap_id).filter(DBStoreScrap.status == S.POSTED.value)
    if project_id:
        q = q.filter(DBStoreScrap.project_id == project_id)
    if from_date:
        q = q.filter(DBStoreScrap.scrap_date >= to_date(from_date, "From date"))
    if to_date_:
        q = q.filter(DBStoreScrap.scrap_date <= to_date(to_date_, "To date"))
    return [ScrapLine(scrap_doc_id=s.id, item_id=l.item_id, qty=l.qty, book_value=l.book_value, realised_value=l.realised_value) for l, s in q.order_by(DBStoreScrap.scrap_date, DBStoreScrapLine.id).all()]


def scrap_dict(db, s, with_lines=True):
    store = db.get(DBStore, s.store_id)
    lines = scrap_lines(db, s)
    job = db.get(models.DBJob, s.project_id) if s.project_id else None
    out = {"id": s.id, "number": s.number, "store_id": s.store_id, "store_code": store.code, "store_name": store.name, "scrap_date": _iso(s.scrap_date),
           "project_id": s.project_id, "project_name": job.name if job else "", "buyer": s.buyer or "", "gate_pass_no": s.gate_pass_no or "", "reason": s.reason or "", "status": s.status,
           "cancel_reason": s.cancel_reason or "", "created_by": s.created_by_name or "", "line_count": len(lines),
           "book_value": str(sum((l.book_value for l in lines), ZERO)), "realised_value": str(sum((l.realised_value for l in lines), ZERO)),
           "difference": str(sum((l.realised_value - l.book_value for l in lines), ZERO))}
    if with_lines:
        items = _names(db, [l.item_id for l in lines])
        out["lines"] = [{"id": l.id, "item_id": l.item_id, "item_code": items[l.item_id].item_code, "item_name": items[l.item_id].item_name, "qty": str(l.qty), "scrap_class": l.scrap_class or "OTHER",
                         "book_value": str(l.book_value), "realised_value": str(l.realised_value), "difference": str(l.realised_value - l.book_value), "remarks": l.remarks or "",
                         "on_hand": str(get_balance(db, s.store_id, l.item_id).qty)} for l in lines]
        out["log"] = doc_log(db, "SCR", s.id)
    return out


# =============================================================================================== reorder alerts
def _pending_po_by_item(db, client_id, project_id):
    """Quantity still to arrive on approved purchase orders, per item (base unit), through the inward slice's get_po_receipt_summary.
    A store on a project counts that project's orders and those with no project; a store with no project counts all."""
    q = db.query(models.DBPurchaseOrder).filter(models.DBPurchaseOrder.client_id == client_id, models.DBPurchaseOrder.status == "Approved")
    if project_id:
        q = q.filter((models.DBPurchaseOrder.job_id == project_id) | (models.DBPurchaseOrder.job_id.is_(None)))
    pending = {}
    for po in q.all():
        for r in store_inward.get_po_receipt_summary(db, po.id):
            if r.item_id and r.pending_qty > 0:
                pending[r.item_id] = pending.get(r.item_id, ZERO) + r.pending_qty
    return pending


def get_reorder_alerts(db, client_id, stores):
    """Items at or below their reorder level in each store, with the quantity to order = maximum - (on hand + pending on purchase orders).
    Read-only: it creates no purchase document."""
    rows, cache = [], {}
    for st in stores:
        pend = cache.setdefault(st.project_id, _pending_po_by_item(db, client_id, st.project_id))
        for b in db.query(DBStoreStockBalance).filter(DBStoreStockBalance.store_id == st.id).all():
            cfg = db.query(DBStoreItemSettings).filter(DBStoreItemSettings.item_id == b.item_id).first()
            level = (cfg.reorder_level or ZERO) if cfg else ZERO
            if not cfg or level <= 0 or b.qty > level:
                continue
            item = db.get(models.DBItem, b.item_id)
            top, due = (cfg.max_qty or ZERO), pend.get(b.item_id, ZERO)
            rows.append({"store_id": st.id, "store_code": st.code, "item_id": b.item_id, "item_code": item.item_code, "item_name": item.item_name, "uom": cfg.base_uom,
                         "on_hand": str(b.qty), "reorder_level": str(level), "min_qty": str(cfg.min_qty or ZERO), "max_qty": str(top), "pending_po": str(due),
                         "suggested": str(max(top - (b.qty + due), ZERO)) if top > 0 else "", "below_min": bool(cfg.min_qty and b.qty < cfg.min_qty)})
    rows.sort(key=lambda r: (r["store_code"], r["item_name"]))
    return rows


def reorder_xlsx(rows, company=""):
    """The alerts as an Excel file for the purchase team (numbers are numbers)."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Reorder"
    ws.append([company or "Store"])
    ws.append(["Items to reorder, as on %s" % date.today().isoformat()])
    ws.append([])
    head = ["Store", "Item code", "Item", "Unit", "On hand", "Reorder level", "Minimum", "Maximum", "Pending on POs", "Suggested order qty"]
    ws.append(head)
    for c in ws[4]:
        c.font = Font(bold=True)
    ws["A1"].font = Font(bold=True, size=13)
    num = lambda v: float(v) if v not in ("", None) else ""    # noqa: E731
    for r in rows:
        ws.append([r["store_code"], r["item_code"], r["item_name"], r["uom"], num(r["on_hand"]), num(r["reorder_level"]), num(r["min_qty"]), num(r["max_qty"]), num(r["pending_po"]), num(r["suggested"])])
    for col, w in zip("ABCDEFGHIJ", (10, 16, 30, 8, 12, 14, 12, 12, 16, 18)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
