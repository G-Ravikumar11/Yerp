"""The rules and workings behind the procurement endpoints."""
import re
from datetime import datetime

from fastapi import HTTPException

from app import models

from app.constants.common import GRN_EDITABLE, GRN_TRANSITIONS
from app.core.audit import log_audit
from app.core.auth import wo_actor
from app.core.currency import lines_money, money, unit_rate
from app.core.gst import state_from_gstin
from app.core.units import canonical_unit
from app.services.stores import stock_movement


def supplier_payment_days(db, client_id, name):
    """What the supplier list says this supplier is paid in; 30 days when it
    is not on the list or says nothing."""
    for x in db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client_id).all():
        if norm_name(x.name) == norm_name(name):
            return x.payment_days if x.payment_days is not None else 30
    return 30


def resolve_po_line_id(db, purchase_order_id, raw):
    """The order line this bill line settles, only if it is on that order.

    Accepting the number as given would let a bill claim against somebody
    else's order, which is exactly the mismatch the match report exists to
    catch.
    """
    if not raw or not purchase_order_id:
        return None
    try:
        line_id = int(raw)
    except (TypeError, ValueError):
        return None
    hit = db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.id == line_id,
        models.DBPurchaseOrderLineItem.order_id == purchase_order_id).first()
    return hit.id if hit else None


def order_is_committed(order):
    """Has this order actually been agreed with anybody?

    Two routes lead there: a member of staff raises one and it walks up the
    approval chain, or the account holder raises it and marks it approved
    themselves. Only the first was recognised, so the owner could not match a
    bill to an order they had placed and approved on their own screen.
    """
    return ((order.approval_status or "none") == "approved"
            or (order.status or "") in ("Approved", "Closed"))


def resolve_order_id(db, client_id, order_id):
    """Check a purchase order reference before a bill is filed against it.

    Only an approved order can be matched: settling a bill against an order
    nobody agreed to would let the order step be skipped entirely.
    """
    if order_id in (None, "", 0):
        return None
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Unknown purchase order")
    order = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == order_id,
        models.DBPurchaseOrder.client_id == client_id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if not order_is_committed(order):
        raise HTTPException(
            status_code=409,
            detail=f"{order.number} has not been approved yet, so a bill cannot be matched to it.")
    return order.id


def purchase_order_to_dict(db, o, include_chain=False):
    submitter = db.query(models.DBEmployee).filter(
        models.DBEmployee.id == o.submitted_by).first() if o.submitted_by else None
    job = db.query(models.DBJob).filter(models.DBJob.id == o.job_id).first() if o.job_id else None
    billed = db.query(models.DBBill).filter(
        models.DBBill.purchase_order_id == o.id).all()
    row = {
        "id": o.id, "number": o.number,
        "supplier_name": o.supplier_name or "", "supplier_email": o.supplier_email or "",
        "issue_date": o.issue_date or "", "needed_by": o.needed_by or "",
        "amount": o.amount or 0.0, "tax_amount": o.tax_amount or 0.0,
        "total": o.total or 0.0,
        "status": o.status or "Draft", "category": o.category or "general",
        "reference": o.reference or "", "notes": o.notes or "",
        "approval_status": o.approval_status or "none",
        "current_step": o.current_approval_step or 0,
        "rejection_reason": o.rejection_reason or "",
        "submitted_by": o.submitted_by, "submitted_by_name": employee_name(submitter),
        "job_id": o.job_id,
        "job_name": f"{job.number} {job.name}" if job else "",
        # What has actually landed against it, so a part-delivered order is
        # visible as such rather than looking untouched.
        "billed_total": money(sum(b.total or 0 for b in billed)),
        "billed_count": len(billed),
        "created_at": o.created_at or "",
    }
    row["remaining"] = money((o.total or 0) - row["billed_total"])

    # What has physically arrived, alongside what has been billed. An order
    # showing a bill and no receipt is the one worth looking at before paying.
    got = received_to_date(db, o.id)
    row["received_total"] = money(sum(
        got.get(l.id, 0.0) * (l.price or 0)
        for l in db.query(models.DBPurchaseOrderLineItem).filter(
            models.DBPurchaseOrderLineItem.order_id == o.id).all()))
    row["receipt_count"] = db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.purchase_order_id == o.id,
        models.DBGoodsReceipt.status != "CANCELLED").count()
    row["line_items"] = [{
        "id": l.id, "description": l.description or "",
        "item_code": getattr(l, "item_code", "") or "",
        "uom": getattr(l, "uom", "") or "",
        "qty": l.qty or 0.0, "price": l.price or 0.0,
        "tax_rate": l.tax_rate or "",
        "received_qty": money(got.get(l.id, 0.0)),
    } for l in db.query(models.DBPurchaseOrderLineItem).filter(
        models.DBPurchaseOrderLineItem.order_id == o.id).order_by(
            models.DBPurchaseOrderLineItem.id).all()]
    if include_chain:
        row["chain"] = get_approval_chain_history("purchase_order", o.id, db)
    return row


def purchase_order_or_404(db, client_id, order_id):
    order = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == order_id,
        models.DBPurchaseOrder.client_id == client_id,
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return order


def apply_order_fields(db, client_id, order, body):
    supplier = (body.get("supplier_name") or "").strip()
    if not supplier:
        raise HTTPException(status_code=400, detail="Who is this order with?")
    # Where there is a schedule, the schedule is the money. The header total
    # is only believed on an order that has no lines at all.
    from_lines = lines_money(body)
    if from_lines and from_lines[0] > 0:
        amount, tax, total = from_lines
    else:
        amount, tax, total = bill_money_from(body)
    order.supplier_name = supplier
    order.supplier_email = (body.get("supplier_email") or "").strip()
    order.amount, order.tax_amount, order.total = amount, tax, total
    order.issue_date = body.get("issue_date") or datetime.now().strftime("%Y-%m-%d")
    order.needed_by = body.get("needed_by") or ""
    order.category = body.get("category") or "general"
    order.reference = (body.get("reference") or "").strip()
    order.notes = (body.get("notes") or "").strip()
    order.job_id = resolve_job_id(db, client_id, body.get("job_id"))
    return order


def grn_or_404(db, client_id, grn_id):
    row = db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.id == grn_id,
        models.DBGoodsReceipt.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Goods receipt not found")
    return row


def recost_grn(db, grn):
    lines = db.query(models.DBGoodsReceiptLine).filter(
        models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all()
    grn.received_value = money(sum((l.received_qty or 0) * (l.rate or 0) for l in lines))
    grn.accepted_value = money(sum((l.accepted_qty or 0) * (l.rate or 0) for l in lines))
    grn.rejected_value = money(sum((l.rejected_qty or 0) * (l.rate or 0) for l in lines))
    for l in lines:
        l.amount = money((l.accepted_qty or 0) * (l.rate or 0))
    grn.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return grn


def grn_dict(db, grn, detail=False):
    po = db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.id == grn.purchase_order_id).first()
    job = db.query(models.DBJob).filter(models.DBJob.id == grn.job_id).first()
    row = {
        "id": grn.id, "number": grn.number or "",
        "purchase_order_id": grn.purchase_order_id,
        "purchase_order": po.number if po else "",
        "job_id": grn.job_id,
        "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
        "supplier_name": grn.supplier_name or "",
        "received_on": grn.received_on or "",
        "challan_number": grn.challan_number or "",
        "invoice_number": grn.invoice_number or "",
        "vehicle_number": grn.vehicle_number or "",
        "status": grn.status or "DRAFT",
        "received_value": money(grn.received_value),
        "accepted_value": money(grn.accepted_value),
        "rejected_value": money(grn.rejected_value),
        "received_by_name": grn.received_by_name or "",
        "inspected_by": grn.inspected_by or "",
        "store_location": grn.store_location or "",
        "remarks": grn.remarks or "",
        "posted_at": grn.posted_at or "",
        "created_at": grn.created_at or "",
        "editable": (grn.status or "DRAFT") in GRN_EDITABLE,
        "actions": sorted(GRN_TRANSITIONS.get(grn.status or "DRAFT", {}).keys()),
    }
    if detail:
        row["lines"] = [{
            "id": l.id, "po_line_id": l.po_line_id,
            "item_code": l.item_code or "", "description": l.description or "",
            "uom": l.uom or "", "ordered_qty": money(l.ordered_qty),
            "previously_received": money(l.previously_received),
            "received_qty": money(l.received_qty),
            "accepted_qty": money(l.accepted_qty),
            "rejected_qty": money(l.rejected_qty),
            "rejection_reason": l.rejection_reason or "",
            "rate": unit_rate(l.rate), "amount": money(l.amount),
        } for l in db.query(models.DBGoodsReceiptLine).filter(
            models.DBGoodsReceiptLine.goods_receipt_id == grn.id).order_by(
                models.DBGoodsReceiptLine.display_order,
                models.DBGoodsReceiptLine.id).all()]
    return row


def grn_actor(request, db):
    """The tenant plus who is at the gate, for the receipt's signature."""
    return wo_actor(request, db, "stores.receive")


def grn_apply(db, client_id, grn, action, request=None, actor_name="", comments=""):
    """The single door every status change goes through."""
    state = grn.status or "DRAFT"
    allowed = GRN_TRANSITIONS.get(state, {})
    if action not in allowed:
        raise HTTPException(
            409, "A %s receipt cannot be %s." % (state.lower(), past_tense(action)))
    grn.status = allowed[action]
    if action == "POST":
        grn.posted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Accepted material becomes stock here, and only here. Rejected
        # material never enters the store, so it is not booked in and does
        # not have to be found and taken out again later.
        for l in db.query(models.DBGoodsReceiptLine).filter(
                models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all():
            if (l.accepted_qty or 0) > 0:
                stock_movement(db, client_id, l.item_code or "", "RECEIPT",
                               l.accepted_qty, l.rate, item_name=l.description,
                               uom=l.uom, store=grn.store_location or "Main store",
                               moved_on=grn.received_on, source_type="goods_receipt",
                               source_id=grn.id, source_ref=grn.number or "",
                               job_id=grn.job_id, recorded_by_name=actor_name)
    if action == "CANCEL" and state == "POSTED":
        # Cancelling a posted receipt takes the material back out, otherwise
        # the store keeps stock that was never really there.
        for l in db.query(models.DBGoodsReceiptLine).filter(
                models.DBGoodsReceiptLine.goods_receipt_id == grn.id).all():
            if (l.accepted_qty or 0) > 0:
                stock_movement(db, client_id, l.item_code or "", "ADJUSTMENT",
                               -l.accepted_qty, l.rate, item_name=l.description,
                               uom=l.uom, store=grn.store_location or "Main store",
                               source_type="goods_receipt", source_id=grn.id,
                               source_ref=(grn.number or "") + " cancelled",
                               remarks="Receipt cancelled",
                               recorded_by_name=actor_name)
    grn.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client_id, "grn_%s" % action.lower(), "goods_receipt",
              grn.id, grn.number or "", ("%s %s" % (actor_name, comments)).strip(),
              request)
    return grn


def billed_against_po(db, purchase_order_id):
    """Value and quantity billed against an order, ignoring rejected bills.

    A bill that was thrown out is not a claim on anything, and counting it
    would make an order look fully billed when nobody has been paid.
    """
    bills = db.query(models.DBBill).filter(
        models.DBBill.purchase_order_id == purchase_order_id,
        models.DBBill.status != "Rejected").all()
    ids = [b.id for b in bills]
    per_line = {}
    if ids:
        for l in db.query(models.DBBillLineItem).filter(
                models.DBBillLineItem.bill_id.in_(ids)).all():
            key = getattr(l, "po_line_id", None)
            if key:
                per_line[key] = per_line.get(key, 0.0) + (l.qty or 0.0)
    return {
        "bills": bills,
        # Before tax, as the ordered and received figures it is set against
        # are. Counted with GST, every bill drawn from a receipt looked
        # over-billed by exactly its tax.
        "value": money(sum((b.amount if b.amount else b.total) or 0 for b in bills)),
        "paid": money(sum(b.amount_paid or 0 for b in bills)),
        "per_line": per_line,
    }


def match_verdict(ordered, received, billed):
    """What the three numbers say, in the order a buyer would ask.

    The two that cost money come first, most specific one leading: a bill with
    nothing at all received is a different conversation from a bill that runs
    ahead of a part delivery, and saying so is more use than a figure.
    """
    if received <= 0.01 and billed > 0.01:
        return ("AWAITING_RECEIPT",
                "Billed with nothing recorded as received. Check the gate before paying.")
    if billed > received + 0.01:
        return ("OVER_BILLED",
                "Billed for more than was received. Do not pay until this is explained.")
    if received > ordered + 0.01:
        return ("OVER_RECEIVED",
                "More arrived than was ordered. Agree a variation before billing it.")
    if received <= 0.01 and billed <= 0.01:
        return ("AWAITING_DELIVERY", "Ordered. Nothing has arrived yet.")
    if billed <= 0.01:
        return ("AWAITING_BILL", "Received and not yet billed. An accrual is owed.")
    if billed < received - 0.01:
        return ("PART_BILLED", "Part billed against what was received.")
    return ("MATCHED", "Ordered, received and billed agree.")


def _apply_supplier(db, client_id, s, body):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "What is the supplier called?")
    clash = [x for x in db.query(models.DBSupplier).filter(
        models.DBSupplier.client_id == client_id).all()
        if norm_name(x.name) == norm_name(name) and x.id != s.id]
    if clash:
        raise HTTPException(409, "%s is already on file as %s." % (name, clash[0].code))
    gstin = (body.gstin or "").strip().upper()
    if gstin and (len(gstin) != 15 or not state_from_gstin(gstin)):
        raise HTTPException(400, "A GSTIN is fifteen characters and starts with a state code.")
    pan = (body.pan or "").strip().upper()
    if not pan and gstin:
        pan = gstin[2:12]           # the PAN is inside the GSTIN
    if pan and not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan):
        raise HTTPException(400, "A PAN is five letters, four digits and a letter.")
    s.name = name
    s.contact_person = (body.contact_person or "").strip()
    s.phone = (body.phone or "").strip()
    s.email = (body.email or "").strip()
    s.gstin, s.pan = gstin, pan
    s.state_code = state_from_gstin(gstin)
    s.address = (body.address or "").strip()
    s.bank_name = (body.bank_name or "").strip()
    s.bank_account = (body.bank_account or "").strip()
    s.bank_ifsc = (body.bank_ifsc or "").strip().upper()
    s.payment_days = max(0, int(body.payment_days or 0))
    s.supplies = (body.supplies or "").strip()
    s.is_active = bool(body.is_active) if body.is_active is not None else True


def next_supplier_code(db, client_id):
    n = db.query(models.DBSupplier).filter(models.DBSupplier.client_id == client_id).count()
    return "SUP-%04d" % (n + 1)


def rfq_or_404(db, client_id, rfq_id):
    r = db.query(models.DBRfq).filter(models.DBRfq.id == rfq_id,
                                      models.DBRfq.client_id == client_id).first()
    if not r:
        raise HTTPException(404, "Enquiry not found")
    return r


def next_rfq_number(db, client_id):
    n = db.query(models.DBRfq).filter(models.DBRfq.client_id == client_id).count()
    return "RFQ-%04d" % (n + 1)


def _rfq_lines(db, rfq_id):
    return db.query(models.DBRfqLine).filter(models.DBRfqLine.rfq_id == rfq_id).order_by(
        models.DBRfqLine.display_order, models.DBRfqLine.id).all()


def _rfq_quotes(db, rfq_id):
    quotes = db.query(models.DBRfqQuote).filter(models.DBRfqQuote.rfq_id == rfq_id).order_by(
        models.DBRfqQuote.id).all()
    rates = {}
    if quotes:
        for ql in db.query(models.DBRfqQuoteLine).filter(
                models.DBRfqQuoteLine.quote_id.in_([q.id for q in quotes])).all():
            rates[(ql.quote_id, ql.rfq_line_id)] = ql
    return quotes, rates


def comparative_statement(db, rfq):
    """Every line against every supplier, the lowest named, and each
    supplier's total landed at site - basic, tax and freight together,
    because a cheaper rate with a lorry charge on top is not cheaper."""
    lines = _rfq_lines(db, rfq.id)
    quotes, rates = _rfq_quotes(db, rfq.id)
    suppliers = []
    for q in quotes:
        basic = tax = 0.0
        quoted = 0
        for l in lines:
            ql = rates.get((q.id, l.id))
            if ql and ql.rate > 0:
                amt = (l.qty or 0) * ql.rate
                basic += amt
                tax += amt * (ql.tax_percent or 0) / 100.0
                quoted += 1
        suppliers.append({
            "quote_id": q.id, "supplier_name": q.supplier_name, "quote_ref": q.quote_ref or "",
            "quote_date": q.quote_date or "", "delivery_days": q.delivery_days or 0,
            "payment_terms": q.payment_terms or "", "freight": money(q.freight),
            "valid_until": q.valid_until or "", "notes": q.notes or "",
            "lines_quoted": quoted, "complete": quoted == len(lines),
            "basic": money(basic), "tax": money(tax),
            "landed": money(basic + tax + (q.freight or 0))})
    rows = []
    for l in lines:
        offers = []
        for q in quotes:
            ql = rates.get((q.id, l.id))
            if ql and ql.rate > 0:
                offers.append({"supplier_name": q.supplier_name, "rate": unit_rate(ql.rate),
                               "tax_percent": ql.tax_percent or 0,
                               "amount": money((l.qty or 0) * ql.rate),
                               "remarks": ql.remarks or ""})
        low = min(offers, key=lambda o: o["rate"]) if offers else None
        high = max(offers, key=lambda o: o["rate"]) if offers else None
        rows.append({
            "rfq_line_id": l.id, "item_code": l.item_code or "", "description": l.description,
            "uom": l.uom or "", "qty": money(l.qty), "offers": offers,
            "lowest": low["supplier_name"] if low else "", "lowest_rate": low["rate"] if low else 0,
            "spread_percent": (round((high["rate"] - low["rate"]) / low["rate"] * 100, 1)
                               if low and low["rate"] else 0.0),
            "awarded_supplier": l.awarded_supplier or "", "awarded_rate": unit_rate(l.awarded_rate),
            "po_id": l.po_id})
    complete = [s for s in suppliers if s["complete"]]
    best = min(complete, key=lambda s: s["landed"]) if complete else None
    per_line_total = money(sum(r["lowest_rate"] * r["qty"] for r in rows))
    for s in suppliers:
        s["is_l1"] = bool(best and s["quote_id"] == best["quote_id"])
    ranked = sorted(complete, key=lambda s: s["landed"])
    for i, s in enumerate(ranked):
        s["rank"] = "L%d" % (i + 1)
    return {"rfq": rfq_dict(db, rfq), "lines": rows, "suppliers": suppliers,
            "l1": best["supplier_name"] if best else "",
            "l1_landed": best["landed"] if best else 0.0,
            "lowest_per_line_basic": per_line_total,
            "saving_vs_l2": money(ranked[1]["landed"] - ranked[0]["landed"]) if len(ranked) > 1 else 0.0}


def rfq_dict(db, r):
    job = db.query(models.DBJob).filter(models.DBJob.id == r.job_id).first() if r.job_id else None
    return {"id": r.id, "number": r.number, "title": r.title or "", "job_id": r.job_id,
            "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
            "work_order_id": r.work_order_id, "needed_by": r.needed_by or "",
            "status": r.status, "notes": r.notes or "", "award_reason": r.award_reason or "",
            "created_by_name": r.created_by_name or "", "awarded_at": r.awarded_at or "",
            "created_at": r.created_at or "",
            "lines": db.query(models.DBRfqLine).filter(models.DBRfqLine.rfq_id == r.id).count(),
            "quotes": db.query(models.DBRfqQuote).filter(models.DBRfqQuote.rfq_id == r.id).count()}


def _make_rfq(db, client, actor_name, title, job_id, needed_by, notes, lines, work_order_id=None):
    lines = [l for l in lines if (l["description"] or "").strip() and (l["qty"] or 0) > 0]
    if not lines:
        raise HTTPException(400, "An enquiry needs at least one line with a quantity.")
    if job_id:
        job_or_404(db, client.id, job_id)
    r = models.DBRfq(client_id=client.id, number=next_rfq_number(db, client.id),
                     job_id=job_id, work_order_id=work_order_id, title=title.strip(),
                     needed_by=(needed_by or "").strip(), notes=(notes or "").strip(),
                     status="OPEN", created_by_name=actor_name)
    db.add(r)
    db.flush()
    for i, l in enumerate(lines[:200]):
        db.add(models.DBRfqLine(rfq_id=r.id, item_code=(l.get("item_code") or "").strip(),
                                description=l["description"].strip(),
                                uom=canonical_unit(l.get("uom")) or (l.get("uom") or ""),
                                qty=money(l["qty"]), display_order=i))
    return r


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.approvals import get_approval_chain_history
from app.services.client_billing import received_to_date
from app.services.crm import norm_name
from app.services.employee_portal import bill_money_from
from app.services.hr import employee_name
from app.services.projects import job_or_404, resolve_job_id
from app.services.subcontract_billing import past_tense
