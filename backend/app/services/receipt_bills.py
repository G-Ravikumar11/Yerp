"""The supplier bill drawn from a goods receipt, so accounts check a bill rather than retype one.

Both kinds of receipt are billed alike: the old store's (goods_receipts) and the Store Hub's (store_grn). They are told
apart the way the invoice tracker tells them apart: an old receipt by its own id, a Hub receipt by minus its id, and the
same for their lines. The bill keeps that signed id, and each of its lines the signed id of the receipt line it bills.

A receipt line is billed for what was accepted into stock, less what live bills (not cancelled or rejected) already
bill of it. So a second bill for the same delivery is refused, while a draft cut down by accounts leaves the rest to be
billed later.
"""
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import or_

from app import models
from app.core.audit import log_audit
from app.core.currency import inr, money, tax_percent_of, unit_rate
from app.core.dates import days_after
from app.core.serials import next_sequence_number
from app.models.store_inward import DBStoreGrn, DBStoreGrnLine
from app.services.invoicing import BILL_DEAD
from app.services.procurement import supplier_payment_days

# Less than this left on a line is rounding, not material still to bill.
QTY_SLACK = 0.0005


def _live(q):
    return q.filter(or_(models.DBBill.status.is_(None), ~models.DBBill.status.in_(BILL_DEAD)))


def receipt_for_bill(db, client_id, grn_id, lock=False):
    """The receipt behind a signed id, shaped alike for both kinds, or a 404. `lock` holds its row until the commit, so
    two people pressing the button at once cannot both bill it."""
    if grn_id < 0:
        q = db.query(DBStoreGrn).filter(DBStoreGrn.id == -grn_id, DBStoreGrn.client_id == client_id)
        g = (q.with_for_update() if lock else q).first()
        if not g:
            raise HTTPException(404, "Goods receipt not found")
        rows = db.query(DBStoreGrnLine).filter(DBStoreGrnLine.grn_id == g.id).order_by(
            DBStoreGrnLine.line_no, DBStoreGrnLine.id).all()
        items = {i.id: i for i in db.query(models.DBItem).filter(
            models.DBItem.id.in_({l.item_id for l in rows})).all()} if rows else {}
        lines = [SimpleNamespace(id=-l.id, po_line_id=l.po_line_id, accepted_qty=float(l.accepted_qty or 0),
                                 rate=float(l.rate or 0),
                                 description=(items[l.item_id].item_name or items[l.item_id].item_code or "")
                                 if l.item_id in items else "") for l in rows]
        return SimpleNamespace(id=grn_id, number=g.number or "", posted=(g.status or "") == "POSTED",
                               supplier_name=g.supplier_name or "", purchase_order_id=g.po_id, job_id=g.project_id,
                               challan=g.challan_no or "", lines=lines)
    q = db.query(models.DBGoodsReceipt).filter(models.DBGoodsReceipt.id == grn_id,
                                               models.DBGoodsReceipt.client_id == client_id)
    g = (q.with_for_update() if lock else q).first()
    if not g:
        raise HTTPException(404, "Goods receipt not found")
    rows = db.query(models.DBGoodsReceiptLine).filter(models.DBGoodsReceiptLine.goods_receipt_id == g.id).order_by(
        models.DBGoodsReceiptLine.display_order, models.DBGoodsReceiptLine.id).all()
    lines = [SimpleNamespace(id=l.id, po_line_id=l.po_line_id, accepted_qty=float(l.accepted_qty or 0),
                             rate=float(l.rate or 0), description=l.description or l.item_code or "") for l in rows]
    return SimpleNamespace(id=g.id, number=g.number or "", posted=(g.status or "") == "POSTED",
                           supplier_name=g.supplier_name or "", purchase_order_id=g.purchase_order_id, job_id=g.job_id,
                           challan=g.challan_number or "", lines=lines)


def billed_qty(db, client_id, line_ids):
    """{signed receipt line id: quantity live bills already bill of it}."""
    if not line_ids:
        return {}
    out = {}
    rows = _live(db.query(models.DBBillLineItem.grn_line_id, models.DBBillLineItem.qty).join(
        models.DBBill, models.DBBill.id == models.DBBillLineItem.bill_id).filter(
        models.DBBill.client_id == client_id, models.DBBillLineItem.grn_line_id.in_(list(line_ids)))).all()
    for line_id, qty in rows:
        out[line_id] = out.get(line_id, 0.0) + (qty or 0)
    return out


def older_bills(db, client_id, receipts):
    """{receipt id: bill} for old store receipts billed before bills named their receipt: a live bill with the receipt's
    number as its reference and no receipt of its own. It is taken to bill all of the receipt, as it did."""
    numbers = {r.number: r.id for r in receipts if r.id > 0 and r.number}
    if not numbers:
        return {}
    out = {}
    for b in _live(db.query(models.DBBill).filter(models.DBBill.client_id == client_id, models.DBBill.grn_id.is_(None),
                                                  models.DBBill.reference.in_(list(numbers)))).order_by(models.DBBill.id).all():
        out.setdefault(numbers[b.reference], b)
    return out


def _older_bill(db, client_id, receipt):
    return older_bills(db, client_id, [receipt]).get(receipt.id)


def bills_by_receipt(db, client_id, grn_ids):
    """{signed receipt id: [{id, number, status, total}]} - the live bills drawn from each receipt."""
    if not grn_ids:
        return {}
    out = {}
    for b in _live(db.query(models.DBBill).filter(models.DBBill.client_id == client_id,
                                                  models.DBBill.grn_id.in_(list(grn_ids)))).order_by(models.DBBill.id).all():
        out.setdefault(b.grn_id, []).append({"id": b.id, "number": b.number or "", "status": b.status or "",
                                             "total": money(b.total)})
    return out


def unbilled_lines(db, client_id, receipt):
    """[(line, quantity still to bill)] for the lines with something accepted and not yet billed."""
    if _older_bill(db, client_id, receipt) is not None:
        return []
    done = billed_qty(db, client_id, [l.id for l in receipt.lines])
    out = []
    for l in receipt.lines:
        left = money(l.accepted_qty - done.get(l.id, 0.0))
        if left > QTY_SLACK:
            out.append((l, left))
    return out


def receipt_bill_state(db, client_id, grn_id):
    """What the button on a receipt needs: the bills drawn from it and whether anything is left to bill."""
    receipt = receipt_for_bill(db, client_id, grn_id)
    bills = bills_by_receipt(db, client_id, [grn_id]).get(grn_id, [])
    older = _older_bill(db, client_id, receipt)
    if older is not None:
        bills = [{"id": older.id, "number": older.number or "", "status": older.status or "",
                  "total": money(older.total)}] + bills
    return {"grn_id": grn_id, "posted": receipt.posted, "bills": bills,
            "billable": receipt.posted and bool(unbilled_lines(db, client_id, receipt))}


def _tax_rates(db, purchase_order_id, lines):
    """{line id: GST label}, at the rate each line was ordered at. Orders saved before a rate was asked for carry a label
    that does not account for the tax the order was agreed at; for those the order's own rate is used."""
    po_lines = db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.order_id == purchase_order_id).all() if purchase_order_id else []
    po_rates = {pl.id: (pl.tax_rate or "0%") for pl in po_lines}
    po = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == purchase_order_id).first() if purchase_order_id else None
    by_lines = money(sum((pl.qty or 0) * (pl.price or 0) * tax_percent_of(pl.tax_rate) / 100.0 for pl in po_lines))
    agreed_tax = money(po.tax_amount or 0) if po else 0.0
    if po and abs(by_lines - agreed_tax) > 1.0:
        flat = round(agreed_tax / po.amount * 100.0, 2) if po.amount else 0.0
        po_rates = {k: "%g%%" % flat for k in po_rates}
    return {l.id: po_rates.get(l.po_line_id, "0%") for l in lines}


def _tracker_extras(db, client_id, grn_id):
    """The supplier invoice's own date and charges, where the store keyed them into the invoice tracker."""
    inv = db.query(models.DBTrackerInvoice).filter(models.DBTrackerInvoice.client_id == client_id,
                                                   models.DBTrackerInvoice.grn_id == grn_id).first()
    charges = [("Freight", money(inv.freight if inv else 0))]
    for c in db.query(models.DBTrackerCharge).filter(models.DBTrackerCharge.client_id == client_id,
                                                     models.DBTrackerCharge.grn_id == grn_id).all():
        charges.append(((c.kind or "").capitalize(), money(c.amount)))
    return ((inv.invoice_date or "") if inv else ""), [(k, v) for k, v in charges if v > 0]


def bill_from_receipt(db, client_id, grn_id, body=None, request=None):
    """A draft supplier bill for what a posted receipt took in and no bill has billed yet: its lines at the receipt's
    rates and the order's GST, tied to the order, the project and the receipt lines. Committed here."""
    receipt = receipt_for_bill(db, client_id, grn_id, lock=True)
    if not receipt.posted:
        raise HTTPException(409, "Post the receipt first. A bill drawn from a draft is a bill for material nobody has "
                                 "confirmed arrived.")
    if not any(l.accepted_qty > QTY_SLACK for l in receipt.lines):
        raise HTTPException(400, "Nothing on this receipt was accepted, so there is nothing to pay for.")
    older = _older_bill(db, client_id, receipt)
    prior = bills_by_receipt(db, client_id, [grn_id]).get(grn_id, [])
    todo = unbilled_lines(db, client_id, receipt)
    if not todo:
        named = [b["number"] or "unnumbered" for b in prior]
        if older is not None:
            named.insert(0, older.number or "unnumbered")
        raise HTTPException(409, "%s already has a bill (%s) for everything accepted on it. Two bills against one "
                                 "delivery is how a supplier gets paid twice."
                                 % (receipt.number or "This receipt", ", ".join(named)))

    rate_of = _tax_rates(db, receipt.purchase_order_id, [l for l, _ in todo])
    invoice_date, charges = _tracker_extras(db, client_id, grn_id)
    # The bill's charges (freight, insurance, hamali) go on the first bill only, at no GST - as the tracker adds them.
    charges = [] if prior else charges
    amount = money(sum(qty * unit_rate(l.rate) for l, qty in todo) + sum(v for _, v in charges))
    tax = money(sum(qty * unit_rate(l.rate) * tax_percent_of(rate_of[l.id]) / 100.0 for l, qty in todo))
    body = body or {}
    today = datetime.now().strftime("%Y-%m-%d")
    issued = invoice_date or today
    part = len(prior) + 1
    bill = models.DBBill(
        client_id=client_id, job_id=receipt.job_id, grn_id=grn_id,
        number=next_sequence_number(db, models.DBBill, client_id, "BILL-"),
        vendor_name=receipt.supplier_name,
        issue_date=issued,
        # Undated, a bill is filed as the oldest debt there is; the supplier's own terms say when it is really due.
        due_date=body.get("due_date") or days_after(issued, supplier_payment_days(db, client_id, receipt.supplier_name)),
        amount=amount, tax_amount=tax, total=money(amount + tax),
        status="Draft", category="material",
        reference=receipt.number if part == 1 else "%s/%d" % (receipt.number, part),
        notes="Raised from %s%s. Check it against the supplier's invoice before accepting it."
              % (receipt.number or "a receipt", " - challan %s" % receipt.challan if receipt.challan else ""),
        purchase_order_id=receipt.purchase_order_id)
    db.add(bill)
    db.flush()
    for l, qty in todo:
        db.add(models.DBBillLineItem(bill_id=bill.id, po_line_id=l.po_line_id, grn_line_id=l.id,
                                     description=l.description[:500], qty=qty, price=unit_rate(l.rate),
                                     tax_rate=rate_of[l.id] or "0%"))
    for label, value in charges:
        db.add(models.DBBillLineItem(bill_id=bill.id, description=label, qty=1, price=value, tax_rate="0%"))
    log_audit(db, client_id, "bill_from_receipt", "bill", bill.id, bill.number or "",
              "%s %s" % (receipt.number, inr(amount)), request)
    db.commit()
    db.refresh(bill)
    n = len(todo)
    return {"ok": True,
            "bill": {"id": bill.id, "number": bill.number or "", "vendor_name": bill.vendor_name or "",
                     "total": money(bill.total), "status": bill.status or "", "reference": bill.reference or "",
                     "purchase_order_id": bill.purchase_order_id, "job_id": bill.job_id, "grn_id": bill.grn_id},
            "message": "%s drawn up for %s from what actually arrived - %s across %d line%s%s. It is a draft for "
                       "accounts to check." % (bill.number, bill.vendor_name, inr(amount), n, "" if n == 1 else "s",
                                               (", %s with GST" % inr(amount + tax)) if tax else "")}
