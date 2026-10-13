"""The rules and workings behind the stores endpoints."""
from datetime import datetime

from fastapi import HTTPException

from app import models

from app.core.config import logger
from app.core.currency import money, unit_rate


def stock_movement(db, client_id, item_code, kind, quantity, rate, **kw):
    """Write one row. The only way stock ever changes."""
    item = db.query(models.DBItem).filter(
        models.DBItem.client_id == client_id,
        models.DBItem.item_code == item_code).first()
    row = models.DBStockMovement(
        client_id=client_id, item_code=item_code,
        item_name=kw.get("item_name") or (item.item_name if item else ""),
        uom=kw.get("uom") or (item.units_of_measure if item else ""),
        store=kw.get("store") or "Main store",
        kind=kind, quantity=money(quantity), rate=unit_rate(rate),
        value=money(money(quantity) * unit_rate(rate)),
        moved_on=kw.get("moved_on") or datetime.now().strftime("%Y-%m-%d"),
        source_type=kw.get("source_type") or "manual",
        source_id=kw.get("source_id"), source_ref=kw.get("source_ref") or "",
        work_order_id=kw.get("work_order_id"), job_id=kw.get("job_id"),
        remarks=(kw.get("remarks") or "")[:400],
        recorded_by=kw.get("recorded_by"),
        recorded_by_name=kw.get("recorded_by_name") or "")
    db.add(row)
    apply_to_balance(db, client_id, row)
    return row


def apply_to_balance(db, client_id, m):
    """Fold one movement into the item's running balance."""
    bal = db.query(models.DBStockBalance).filter(
        models.DBStockBalance.client_id == client_id,
        models.DBStockBalance.item_code == m.item_code).first()
    if bal is None:
        bal = models.DBStockBalance(client_id=client_id, item_code=m.item_code,
                                    item_name=m.item_name or "", uom=m.uom or "")
        db.add(bal)
    if m.item_name and not bal.item_name:
        bal.item_name = m.item_name
    if m.uom and not bal.uom:
        bal.uom = m.uom
    qty = m.quantity or 0.0
    moved = (m.kind or "").startswith("TRANSFER")
    bal.movements = (bal.movements or 0) + 1
    if qty > 0:
        if not moved:
            bal.received = money((bal.received or 0) + qty)
        bal.value = money((bal.value or 0) + (m.value or 0))
        bal.on_hand = money((bal.on_hand or 0) + qty)
        bal.rate = unit_rate(bal.value / bal.on_hand) if bal.on_hand else 0.0
    else:
        if not moved:
            bal.issued = money((bal.issued or 0) - qty)
        bal.on_hand = money((bal.on_hand or 0) + qty)
        bal.value = money(bal.on_hand * (bal.rate or 0))
    bal.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return bal


def rebuild_stock_balances(db, client_id):
    """Replay the ledger from the start and overwrite every balance.

    The one door for doubt: if a balance is ever questioned, this makes it
    agree with the ledger again, because the ledger is the truth.
    """
    replayed = replay_stock_ledger(db, client_id)
    db.query(models.DBStockBalance).filter(
        models.DBStockBalance.client_id == client_id).delete()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for code, a in replayed.items():
        db.add(models.DBStockBalance(
            client_id=client_id, item_code=code, item_name=a["item_name"],
            uom=a["uom"], on_hand=money(a["on_hand"]), rate=unit_rate(a["rate"]),
            value=money(a["value"]), received=money(a["received"]),
            issued=money(a["issued"]), movements=a["movements"], updated_at=now))
    db.flush()
    return len(replayed)


def stock_balances(db, client_id, item_code=None, store=None, item_codes=None):
    """On hand per item, from the running balance.

    Falls back to replaying the ledger only when asked for one store, which
    the balance does not split by, or when the balance table is empty and the
    ledger is not - which is the first request after this table was added.
    """
    if store:
        return replay_stock_ledger(db, client_id, item_code=item_code,
                                   store=store, item_codes=item_codes)
    q = db.query(models.DBStockBalance).filter(
        models.DBStockBalance.client_id == client_id)
    if item_code:
        q = q.filter(models.DBStockBalance.item_code == item_code)
    elif item_codes is not None:
        if not item_codes:
            return {}
        q = q.filter(models.DBStockBalance.item_code.in_(list(item_codes)))
    rows = q.all()
    if not rows and item_code is None and item_codes is None:
        # Nothing summarised yet. If there is a ledger, this is the migration
        # moment: build the balances once, then serve from them for ever.
        if db.query(models.DBStockMovement.id).filter(
                models.DBStockMovement.client_id == client_id).first():
            rebuild_stock_balances(db, client_id)
            db.commit()
            rows = q.all()
    return {b.item_code: {
        "item_code": b.item_code, "item_name": b.item_name or "", "uom": b.uom or "",
        "received": money(b.received), "issued": money(b.issued),
        "on_hand": money(b.on_hand), "value": money(b.value),
        "rate": unit_rate(b.rate), "movements": b.movements or 0,
    } for b in rows}


def replay_stock_ledger(db, client_id, item_code=None, store=None, item_codes=None):
    """On hand per item, replayed from every movement in order.

    The slow path, and the authoritative one. Valued at what it actually cost:

    Weighted average, not the last rate paid: cement bought at three prices
    over a month is one heap in the yard, and issuing it at whichever price
    happened to be last makes the job cost jump for no reason on site.
    """
    q = db.query(models.DBStockMovement).filter(
        models.DBStockMovement.client_id == client_id)
    if item_code:
        q = q.filter(models.DBStockMovement.item_code == item_code)
    elif item_codes is not None:
        # Only the heaps that were asked about. A five-line issue note used to
        # walk the whole year's ledger to price its five items.
        if not item_codes:
            return {}
        q = q.filter(models.DBStockMovement.item_code.in_(list(item_codes)))
    if store:
        q = q.filter(models.DBStockMovement.store == store)

    acc = {}
    for m in q.order_by(models.DBStockMovement.id).all():
        a = acc.setdefault(m.item_code, {
            "item_code": m.item_code, "item_name": m.item_name or "",
            "uom": m.uom or "", "received": 0.0, "issued": 0.0,
            "on_hand": 0.0, "value": 0.0, "rate": 0.0, "movements": 0})
        a["movements"] += 1
        if m.item_name and not a["item_name"]:
            a["item_name"] = m.item_name
        qty = m.quantity or 0.0
        moved = (m.kind or "").startswith("TRANSFER")
        if qty > 0:
            if not moved:
                a["received"] += qty
            # Incoming stock re-averages the heap.
            a["value"] = money(a["value"] + (m.value or 0.0))
            a["on_hand"] = money(a["on_hand"] + qty)
            a["rate"] = unit_rate(a["value"] / a["on_hand"]) if a["on_hand"] else 0.0
        else:
            if not moved:
                a["issued"] += -qty
            # Going out at the average, so the heap's rate does not move.
            a["on_hand"] = money(a["on_hand"] + qty)
            a["value"] = money(a["on_hand"] * a["rate"])
    return acc


def item_rate(db, client_id, item_code):
    """What one unit is currently worth, for issuing at cost."""
    bal = stock_balances(db, client_id, item_code=item_code).get(item_code)
    return unit_rate(bal["rate"]) if bal else 0.0


def store_holding(db, client_id, lines):
    """The store an issue with no store named is drawn from: the one that
    holds enough of everything on it, else the one holding most of the first
    item. It used to be "Main store" whatever - material received into a site
    store was issued out of an empty main store, which went negative while
    the site store never went down."""
    wanted = {}
    for l in lines or []:
        code = (l.get("item_code") or l.get("code") or "").strip()
        try:
            qty = float(l.get("quantity") if l.get("quantity") is not None else l.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if code and qty > 0:
            wanted[code] = wanted.get(code, 0.0) + qty
    if not wanted:
        return "Main store"
    names = sorted({s for (s,) in db.query(models.DBStockMovement.store).filter(
        models.DBStockMovement.client_id == client_id,
        models.DBStockMovement.item_code.in_(list(wanted))).distinct().all() if s})
    best, best_qty = "", -1.0
    first = next(iter(wanted))
    for name in names:
        held = replay_stock_ledger(db, client_id, store=name, item_codes=list(wanted))
        if all((held.get(c) or {}).get("on_hand", 0) >= q - 1e-9 for c, q in wanted.items()):
            return name
        have = (held.get(first) or {}).get("on_hand", 0)
        if have > best_qty:
            best, best_qty = name, have
    return best or "Main store"


def next_issue_number(db, client_id):
    n = db.query(models.DBStockIssue).filter(
        models.DBStockIssue.client_id == client_id).count() + 1
    return "ISS-%04d" % n


def issue_or_404(db, client_id, issue_id):
    row = db.query(models.DBStockIssue).filter(
        models.DBStockIssue.id == issue_id,
        models.DBStockIssue.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Issue note not found")
    return row


def issue_dict(db, issue, detail=False, wo_names=None):
    if wo_names is not None:
        wo = None
        wo_number = wo_names.get(issue.work_order_id, "")
    else:
        wo = db.query(models.DBWorkOrder).filter(
            models.DBWorkOrder.id == issue.work_order_id).first() if issue.work_order_id else None
        wo_number = wo.number if wo else ""
    row = {
        "id": issue.id, "number": issue.number or "",
        "work_order_id": issue.work_order_id,
        "work_order": wo_number,
        "issued_on": issue.issued_on or "", "store": issue.store or "",
        "status": issue.status or "DRAFT", "issued_to": issue.issued_to or "",
        "purpose": issue.purpose or "", "total_value": money(issue.total_value),
        "issued_by_name": issue.issued_by_name or "",
        "remarks": issue.remarks or "", "posted_at": issue.posted_at or "",
        "editable": (issue.status or "DRAFT") == "DRAFT",
        "created_at": issue.created_at or "",
    }
    if detail:
        lines = db.query(models.DBStockIssueLine).filter(
            models.DBStockIssueLine.stock_issue_id == issue.id).order_by(
                models.DBStockIssueLine.display_order,
                models.DBStockIssueLine.id).all()
        # One pass over the ledger for the items on the note - not one per line,
        # and not the whole year's movements for everything in the store.
        balances = stock_balances(db, issue.client_id,
                                  item_codes={l.item_code for l in lines}) if lines else {}
        row["lines"] = [{
            "id": l.id, "item_code": l.item_code or "", "item_name": l.item_name or "",
            "uom": l.uom or "", "quantity": money(l.quantity),
            "rate": unit_rate(l.rate), "amount": money(l.amount),
            "on_hand": money(balances.get(l.item_code, {}).get("on_hand", 0)),
        } for l in lines]
    return row


def _replace_issue_lines(db, client_id, issue, lines):
    db.query(models.DBStockIssueLine).filter(
        models.DBStockIssueLine.stock_issue_id == issue.id).delete()
    total = 0.0
    kept, refused = 0, []
    for i, l in enumerate(lines[:400]):
        code = (l.get("item_code") or l.get("code") or "").strip()
        # Every other document in this app calls it qty. An issue note that
        # accepted only "quantity" dropped the line, saved an empty note and
        # still answered "opened" - the mistake is only found later, when the
        # note refuses to be posted.
        raw_qty = l.get("quantity")
        if raw_qty is None:
            raw_qty = l.get("qty")
        qty = money(raw_qty or 0)
        if not code:
            refused.append("line %d has no item code" % (i + 1))
            continue
        if not qty:
            refused.append("%s has no quantity" % code)
            continue
        item = db.query(models.DBItem).filter(
            models.DBItem.client_id == client_id,
            models.DBItem.item_code == code).first()
        if not item:
            refused.append("%s is not in the item master" % code)
            continue
        # Priced from the store, not typed in: an issue is a transfer of value
        # out of stock, and letting somebody name the rate makes the store and
        # the job cost disagree.
        rate = unit_rate(l.get("rate") if l.get("rate") is not None
                         else item_rate(db, client_id, code))
        amount = money(qty * rate)
        total += amount
        db.add(models.DBStockIssueLine(
            stock_issue_id=issue.id, item_code=code,
            item_name=(l.get("item_name") or (item.item_name if item else ""))[:300],
            uom=(l.get("uom") or (item.units_of_measure if item else ""))[:40],
            quantity=qty, rate=rate, amount=amount, display_order=i))
        kept += 1
    # Lines that were sent and did not land must not disappear behind a
    # cheerful message. An empty note that says it opened is found later, at
    # the store, by somebody holding a lorry.
    if lines and not kept:
        raise HTTPException(400, "Nothing could be issued: " + "; ".join(refused[:5]) + ".")
    if refused:
        logger.warning("Issue note %s: %s", issue.number, "; ".join(refused[:10]))
    issue.total_value = money(total)
    issue.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.flush()
    return issue


# PROJECT PROFIT AND LOSS
#
# What a project earned against what it truly cost. The cost side had a hole
# in it until now: supplier bills were counted, but the material drawn out of
# the store and the labour standing on site were not, so a job could look
# profitable right up to the day the store was counted.
#
# Revenue is what has been certified, not what has been hoped for. A bill
# nobody has agreed to is not income, and treating it as such is how a
# contractor discovers a loss at the end instead of in the middle.
def stocked_share_of_bills(db, client_id):
    """{bill id: the share of the bill that paid for goods booked into the
    store} - its lines tied to order lines that carry a stock code and were
    received through a goods receipt. Bills typed in without lines are left
    whole; there is nothing to say what they bought."""
    bills = {b.id for b in db.query(models.DBBill.id).filter(
        models.DBBill.client_id == client_id,
        models.DBBill.purchase_order_id.isnot(None)).all()}
    if not bills:
        return {}
    stock_lines = {pl.id for pl in db.query(models.DBPurchaseOrderLineItem.id).join(
        models.DBPurchaseOrder, models.DBPurchaseOrder.id == models.DBPurchaseOrderLineItem.order_id).filter(
        models.DBPurchaseOrder.client_id == client_id,
        models.DBPurchaseOrderLineItem.item_code.isnot(None),
        models.DBPurchaseOrderLineItem.item_code != "").all()}
    received = {l.po_line_id for l in db.query(models.DBGoodsReceiptLine.po_line_id).join(
        models.DBGoodsReceipt, models.DBGoodsReceipt.id == models.DBGoodsReceiptLine.goods_receipt_id).filter(
        models.DBGoodsReceipt.client_id == client_id,
        models.DBGoodsReceipt.status == "POSTED").all() if l.po_line_id}
    whole, stock = {}, {}
    for l in db.query(models.DBBillLineItem).filter(models.DBBillLineItem.bill_id.in_(list(bills))).all():
        value = (l.qty or 0) * (l.price or 0)
        whole[l.bill_id] = whole.get(l.bill_id, 0.0) + value
        if l.po_line_id in stock_lines and l.po_line_id in received:
            stock[l.bill_id] = stock.get(l.bill_id, 0.0) + value
    return {b: min(1.0, stock[b] / whole[b]) for b in stock if whole.get(b)}


# THE HANDOFFS
#
# Every module in this app knew its own job and none of them handed over. The
# BOM knew a work order needed nine hundred bags of cement; nothing turned
# that into a purchase order. A posted receipt knew exactly what arrived and
# at what rate; somebody still retyped it as a supplier bill, which is where
# the figure quietly stops matching.
#
# Both of these are the same idea: the next document already exists inside
# the last one, so the app should draw it up and let a person correct it.
def material_required(db, client_id, wo):
    """What this order still needs bought, line by line.

    Needed by the BOM, less what is already in the store, less what is already
    on an open purchase order - so raising it twice is not the default
    behaviour of anybody who clicks the button twice.
    """
    needed = {}
    for b in db.query(models.DBBomLine).filter(
            models.DBBomLine.work_order_id == wo.id).all():
        row = needed.setdefault(b.rm_code, {
            "item_code": b.rm_code, "item_name": b.rm_name or "",
            "uom": b.uom or "", "needed": 0.0, "rate": unit_rate(b.rate)})
        row["needed"] = money(row["needed"] + (b.qty or 0))
        if b.rate:
            row["rate"] = unit_rate(b.rate)
    if not needed:
        return []

    balances = stock_balances(db, client_id, item_codes=set(needed))

    # Quantity sitting on purchase orders that have not been fully received.
    on_order = {}
    live = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == client_id,
        models.DBPurchaseOrder.status.in_(
            ("Draft", "Awaiting Approval", "Approved"))).all()
    if live:
        ids = [p.id for p in live]
        received = {}
        for grn in db.query(models.DBGoodsReceipt).filter(
                models.DBGoodsReceipt.client_id == client_id,
                models.DBGoodsReceipt.purchase_order_id.in_(ids),
                models.DBGoodsReceipt.status == "POSTED").all():
            for l in db.query(models.DBGoodsReceiptLine).filter(
                    models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all():
                received[l.item_code] = money(
                    received.get(l.item_code, 0.0) + (l.accepted_qty or 0))
        for l in db.query(models.DBPurchaseOrderLineItem).filter(
                models.DBPurchaseOrderLineItem.order_id.in_(ids)).all():
            code = (l.item_code or "").strip()
            if code:
                on_order[code] = money(on_order.get(code, 0.0) + (l.qty or 0))
        for code, got in received.items():
            if code in on_order:
                on_order[code] = money(max(0.0, on_order[code] - got))

    rows = []
    for code, r in sorted(needed.items()):
        in_store = money(balances.get(code, {}).get("on_hand", 0.0))
        ordered = money(on_order.get(code, 0.0))
        short = money(r["needed"] - in_store - ordered)
        # A rate the store has actually paid beats one typed into a budget
        # months ago; the budget rate is the fallback, not the truth.
        paid = unit_rate(balances.get(code, {}).get("rate", 0.0))
        rows.append({
            "item_code": code, "item_name": r["item_name"], "uom": r["uom"],
            "needed": r["needed"], "in_store": in_store, "on_order": ordered,
            "to_buy": max(0.0, short),
            "rate": paid or r["rate"], "budget_rate": r["rate"],
            "amount": money(max(0.0, short) * (paid or r["rate"])),
            "covered": short <= 0,
        })
    return rows


def next_transfer_number(db, client_id):
    refs = {r for (r,) in db.query(models.DBStockMovement.source_ref).filter(
        models.DBStockMovement.client_id == client_id,
        models.DBStockMovement.kind == "TRANSFER_OUT").all()}
    return "TRF-%04d" % (len(refs) + 1)


def charge_issue_to_gang(db, client_id, issue, order, markup_percent=0.0):
    """Every line on a posted issue, as material to be recovered from the gang."""
    lines = db.query(models.DBStockIssueLine).filter(
        models.DBStockIssueLine.stock_issue_id == issue.id).all()
    factor = 1.0 + (markup_percent or 0.0) / 100.0
    total = 0.0
    for l in lines:
        rate = unit_rate((l.rate or 0) * factor)
        amount = money((l.quantity or 0) * rate)
        total += amount
        db.add(models.DBMaterialRecovery(
            client_id=client_id, order_id=order.id, job_id=order.job_id,
            stock_issue_id=issue.id, issue_number=issue.number or "",
            item_code=l.item_code, item_name=l.item_name or "", uom=l.uom or "",
            quantity=l.quantity or 0, rate=rate, amount=amount, issued_on=issue.issued_on or ""))
    return money(total)
