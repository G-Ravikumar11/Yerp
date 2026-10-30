"""The rules and workings behind the client billing endpoints."""
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func

from app import models

from app.constants.client_billing import RA_EDITABLE, RA_TRANSITIONS, VO_TRANSITIONS
from app.core.audit import log_audit
from app.core.auth import wo_actor
from app.core.currency import amount_in_words, inr, money, unit_rate
from app.core.gst import GST_STATES, our_state, split_gst, supply_state_for_job
from app.core.tenant_settings import tenant_setting
from app.services.credit_notes import bill_credit_summary, credited_qty_by_item


def measured_to_date(db, work_order_id):
    """Quantity measured against each line, summed over the whole book."""
    totals = {}
    for m in db.query(models.DBMeasurement).filter(
            models.DBMeasurement.work_order_id == work_order_id).all():
        totals[m.line_id] = totals.get(m.line_id, 0.0) + (m.quantity or 0.0)
    return totals


def billed_qty_to_date(db, work_order_id, exclude_bill_id=None):
    """Quantity already claimed on earlier bills.

    A cancelled bill claimed nothing, so it must not hold quantity back from
    the next one - that is how work gets measured, cancelled, and then never
    paid for.
    """
    live = db.query(models.DBRABill).filter(
        models.DBRABill.work_order_id == work_order_id,
        models.DBRABill.status != "CANCELLED").all()
    ids = [b.id for b in live if b.id != exclude_bill_id]
    totals = {}
    if not ids:
        return totals
    for l in db.query(models.DBRABillLine).filter(
            models.DBRABillLine.ra_bill_id.in_(ids)).all():
        totals[l.line_id] = totals.get(l.line_id, 0.0) + (l.this_bill_qty or 0.0)
    # Work a credit note took back is no longer claimed: it can be measured and billed again.
    for line_id, qty in credited_qty_by_item(db, "client", work_order_id).items():
        if line_id in totals:
            totals[line_id] = max(0.0, totals[line_id] - qty)
    return totals


def claimable_lines(db, work_order, exclude_bill_id=None):
    """Each ordered line with something measured that no live bill has claimed.

    Returned as (position, line, measured, already billed, this claim) so the
    caller can build rows from it without repeating the subtraction, which is
    the one piece of arithmetic in this module that must not be written twice.
    """
    measured = measured_to_date(db, work_order.id)
    billed = billed_qty_to_date(db, work_order.id, exclude_bill_id=exclude_bill_id)
    out = []
    for index, l in enumerate(db.query(models.DBWorkOrderLine).filter(
            models.DBWorkOrderLine.work_order_id == work_order.id).all()):
        done = money(measured.get(l.id, 0.0))
        already = money(billed.get(l.id, 0.0))
        this = money(done - already)
        if this <= 0:                     # nothing new measured on this line
            continue
        out.append((index, l, done, already, this))
    return out


def write_ra_bill_lines(db, bill, claimable):
    """Replace a bill's lines with what it may claim now."""
    db.query(models.DBRABillLine).filter(
        models.DBRABillLine.ra_bill_id == bill.id).delete()
    for index, l, done, already, this in claimable:
        db.add(models.DBRABillLine(
            ra_bill_id=bill.id, line_id=l.id, fg_code=l.fg_code or "",
            description=l.description or l.item_name or "", uom=l.uom or "",
            ordered_qty=money(l.qty), measured_to_date=done,
            previously_billed_qty=already, this_bill_qty=this,
            rate=unit_rate(l.rate), amount=money(this * unit_rate(l.rate)),
            display_order=index))
    db.flush()
    prior = billed_qty_to_date(db, bill.work_order_id, exclude_bill_id=bill.id)
    rates = {l.id: unit_rate(l.rate) for l in db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == bill.work_order_id).all()}
    bill.previously_billed = money(sum(money(q) * rates.get(lid, 0.0) for lid, q in prior.items()))
    return recost_ra_bill(db, bill)


DEFAULT_RETENTION_PERCENT = 5.0  # when the project states no retention
DEFAULT_GST_PERCENT = 18.0     # works contract, when the company has set no default rate
DEFAULT_TDS_PERCENT = 2.0      # 194C, a payment to a company or a firm (1% is for an individual or HUF)
TDS_SETTING_KEY = "ra_tds_percent"   # the company's own default, when its clients deduct at another rate
GST_RATES = (0.0, 5.0, 12.0, 18.0, 28.0)


def default_tds_percent(db, client_id):
    """The TDS a client is expected to deduct from our bills: the company's setting, else 2% (194C, company/firm)."""
    raw = tenant_setting(db, client_id, TDS_SETTING_KEY, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TDS_PERCENT
    return value if 0 <= value <= 100 else DEFAULT_TDS_PERCENT


def contract_rates(db, work_order):
    """The retention, GST and TDS a new bill on this order is drawn at.

    Retention is a term of the contract, kept on the project: when the project states one - 0 included, a contract
    with no retention - that is used. A project that states none is billed at the usual 5%, and the draft can be
    changed. GST is the company's default tax rate (Settings > Tax rates), and TDS the company's default (2% under
    194C unless it has set another). A screen that sends nothing therefore gets the contract's terms where there are
    any, not a fixed 5 / 18 / 2 whatever the project says.
    """
    job = db.query(models.DBJob).filter(models.DBJob.id == work_order.job_id).first() if work_order.job_id else None
    retention = float(job.retention_percent or 0.0) if job else 0.0
    stated = bool(job and (job.retention_stated or retention > 0))
    if not stated:
        retention = DEFAULT_RETENTION_PERCENT
    default_tax = db.query(models.DBTaxRate).filter(
        models.DBTaxRate.client_id == work_order.client_id, models.DBTaxRate.is_default.is_(True)).first()
    gst = float(default_tax.percent) if default_tax and default_tax.percent else DEFAULT_GST_PERCENT
    return {"retention_percent": retention, "tax_percent": gst,
            "tds_percent": default_tds_percent(db, work_order.client_id)}


def check_rates(retention_percent=None, tax_percent=None, tds_percent=None, advance_recovery=None,
                other_deductions=None):
    """What a bill's deductions may be: nothing negative, a percentage between 0 and 100, GST at a rate GST has."""
    for label, value in (("Retention", retention_percent), ("TDS", tds_percent)):
        if value is not None and not (0 <= float(value) <= 100):
            raise HTTPException(400, "%s has to be between 0 and 100%%; %s is not." % (label, value))
    if tax_percent is not None and float(tax_percent) not in GST_RATES:
        raise HTTPException(400, "GST is charged at 0, 5, 12, 18 or 28%%; %s is not one of them." % tax_percent)
    for label, value in (("Advance recovery", advance_recovery), ("Other deductions", other_deductions)):
        if value is not None and float(value) < 0:
            raise HTTPException(400, "%s cannot be negative." % label)


def _party(name):
    """A party's name as the ledgers compare it (norm_name): case, spacing and full stops do not make two clients."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def client_advance_available(db, bill):
    """What the client has paid us on account (an advance) that bills have not already recovered.

    The advance is what the ledger shows came in on account from the project's client, less what went back to them
    on account; every other live bill to the same client that recovers advance takes its share."""
    job = db.query(models.DBJob).filter(models.DBJob.id == bill.job_id).first() if bill.job_id else None
    who = _party(job.customer_name if job else "")
    if not who:
        return 0.0
    got = 0.0
    for e in db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.client_id == bill.client_id, models.DBMoneyEntry.doc_type == "on_account",
            models.DBMoneyEntry.party_type == "client", models.DBMoneyEntry.voided.isnot(True)).all():
        if _party(e.party_name) == who:
            got += (e.amount or 0) if e.direction == "IN" else -(e.amount or 0)
    jobs = [j.id for j in db.query(models.DBJob).filter(models.DBJob.client_id == bill.client_id).all()
            if _party(j.customer_name) == who]
    used = sum((b.advance_recovery or 0) for b in db.query(models.DBRABill).filter(
        models.DBRABill.client_id == bill.client_id, models.DBRABill.job_id.in_(jobs or [0]),
        models.DBRABill.status != "CANCELLED").all() if b.id != bill.id)
    return money(got - used)


def check_deductions(db, bill, advance=True):
    """After a bill is costed: its rates are rates, the bill does not ask the client for less than nothing, and (when
    it goes up for signature) an advance recovered is one the client actually paid. A draft may carry an advance the
    ledger does not show yet - the receipt can be recorded before it is submitted."""
    check_rates(bill.retention_percent, bill.tax_percent, bill.tds_percent, bill.advance_recovery,
                bill.other_deductions)
    if advance and money(bill.advance_recovery) > 0:
        room = client_advance_available(db, bill)
        if money(bill.advance_recovery) > room + 0.009:
            raise HTTPException(
                400, "Only %s of advance from the client is on the ledger and not yet recovered; %s is more than "
                     "that. Record the advance as a receipt on account first." % (inr(max(room, 0.0)),
                                                                                  inr(bill.advance_recovery)))
    if money(bill.net_payable) < 0:
        raise HTTPException(400, "The deductions come to more than the bill: it would ask the client for %s."
                                 % inr(bill.net_payable))


def over_order_lines(db, bill):
    """Lines of this bill that take what has been billed past the quantity ordered. An approved variation raises the
    order line's quantity (apply_variation), so agreed extra work is inside the cap."""
    ordered = {l.id: money(l.qty) for l in db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == bill.work_order_id).all()}
    out = []
    for l in db.query(models.DBRABillLine).filter(models.DBRABillLine.ra_bill_id == bill.id).all():
        cap = ordered.get(l.line_id, 0.0)
        total = money((l.previously_billed_qty or 0) + (l.this_bill_qty or 0))
        if total > cap + 0.0001:
            out.append({"line_id": l.line_id, "description": (l.description or "").split("\n")[0][:60],
                        "ordered": cap, "billed": total, "over": money(total - cap)})
    return out


def ra_bill_or_404(db, client_id, bill_id):
    row = db.query(models.DBRABill).filter(
        models.DBRABill.id == bill_id,
        models.DBRABill.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Bill not found")
    return row


def recost_ra_bill(db, bill):
    """Total the lines, then apply the deductions in the order they are made.

    The work measured in this bill is the base for every tax: GST goes on it, and
    retention and TDS are taken on it. Retention, the advance and other
    deductions then come off what is payable - they do not shrink the value the
    tax is charged on. Written once, here.
    """
    lines = db.query(models.DBRABillLine).filter(
        models.DBRABillLine.ra_bill_id == bill.id).all()
    this_bill = money(sum(l.amount or 0 for l in lines))

    bill.this_bill = this_bill
    bill.gross_to_date = money(bill.previously_billed + this_bill)
    bill.retention_amount = money(this_bill * (bill.retention_percent or 0) / 100.0)

    after_retention = money(this_bill - bill.retention_amount -
                            (bill.advance_recovery or 0) - (bill.other_deductions or 0))
    # Split the way the return needs it. Place of supply for a works contract
    # is the site, so the job's state is what our state is compared with.
    supply = supply_state_for_job(db, bill.job_id)
    gst = split_gst(this_bill, bill.tax_percent or 0,
                    our_state(db, bill.client_id), supply)
    bill.tax_amount = gst["total"]
    bill.cgst_amount, bill.sgst_amount, bill.igst_amount = gst["cgst"], gst["sgst"], gst["igst"]
    bill.place_of_supply = supply
    bill.tds_amount = money(this_bill * (bill.tds_percent or 0) / 100.0)
    bill.net_payable = money(after_retention + bill.tax_amount - bill.tds_amount)
    bill.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return bill


def ra_bill_dict(db, bill, detail=False, credits=None):
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == bill.work_order_id).first()
    job = db.query(models.DBJob).filter(models.DBJob.id == bill.job_id).first()
    row = {
        "id": bill.id, "number": bill.number or "", "sequence": bill.sequence or 1,
        "work_order_id": bill.work_order_id,
        "work_order": wo.number if wo else "",
        "job_id": bill.job_id, "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
        "customer": (job.customer_name or "") if job else "",
        "status": bill.status or "DRAFT",
        "period_from": bill.period_from or "", "period_to": bill.period_to or "",
        "gross_to_date": money(bill.gross_to_date),
        "previously_billed": money(bill.previously_billed),
        "this_bill": money(bill.this_bill),
        "retention_percent": bill.retention_percent or 0,
        "retention_amount": money(bill.retention_amount),
        "advance_recovery": money(bill.advance_recovery),
        "other_deductions": money(bill.other_deductions),
        "deduction_notes": bill.deduction_notes or "",
        "tax_percent": bill.tax_percent or 0, "tax_amount": money(bill.tax_amount),
        "cgst_amount": money(bill.cgst_amount), "sgst_amount": money(bill.sgst_amount),
        "igst_amount": money(bill.igst_amount), "place_of_supply": bill.place_of_supply or "",
        "cgst_percent": (bill.tax_percent or 0) / 2.0 if (bill.cgst_amount or bill.sgst_amount) else 0,
        "sgst_percent": (bill.tax_percent or 0) / 2.0 if (bill.cgst_amount or bill.sgst_amount) else 0,
        "igst_percent": (bill.tax_percent or 0) if bill.igst_amount else 0,
        "taxable_value": money(bill.this_bill),
        "tds_percent": bill.tds_percent or 0, "tds_amount": money(bill.tds_amount),
        "net_payable": money(bill.net_payable),
        "certified_by_name": bill.certified_by_name or "",
        "certified_at": bill.certified_at or "", "paid_at": bill.paid_at or "",
        "remarks": bill.remarks or "",
        "editable": (bill.status or "DRAFT") in RA_EDITABLE,
        "actions": sorted(RA_TRANSITIONS.get(bill.status or "DRAFT", {}).keys()),
        "created_at": bill.created_at or "",
    }
    if not detail:
        # A list passes one batched {bill id: totals}; a lone row has none to show.
        c = (credits or {}).get(bill.id, {})
        row["credited"] = c.get("taxable", 0.0)
        row["credited_net"] = c.get("net", 0.0)
    row["can_credit"] = (bill.status or "") in ("CERTIFIED", "PAID")
    if detail:
        credit =bill_credit_summary(db, "client", bill)
        row["credited"] = credit["credited"]
        row["credited_net"] = credit["credited_net"]
        row["credit_notes"] = credit["credit_notes"]
        row["lines"] = [{
            "id": l.id, "line_id": l.line_id, "fg_code": l.fg_code or "",
            "description": (l.description or "").split("\n")[0],
            "uom": l.uom or "", "ordered_qty": money(l.ordered_qty),
            "measured_to_date": money(l.measured_to_date),
            "previously_billed_qty": money(l.previously_billed_qty),
            "this_bill_qty": money(l.this_bill_qty),
            "rate": unit_rate(l.rate), "amount": money(l.amount),
            "upto_date_amount": money(money(l.measured_to_date) * unit_rate(l.rate)),
            "credited_qty": money(credit["credited_qty"].get(l.id, 0.0)),
            "creditable_qty": money((l.this_bill_qty or 0) - credit["credited_qty"].get(l.id, 0.0)),
            "over_order": money(money(l.previously_billed_qty) + money(l.this_bill_qty)) > money(l.ordered_qty) + 0.0001,
        } for l in db.query(models.DBRABillLine).filter(
            models.DBRABillLine.ra_bill_id == bill.id).order_by(
                models.DBRABillLine.display_order, models.DBRABillLine.id).all()]
        # What the printed bill needs beyond the figures: who it is from, who
        # it is to, where the work is, and the amount stated twice.
        row["our"] = our_party(db, bill.client_id)
        row["client_party"] = {"name": job.customer_name if job else "",
                               "site": job.site_address if job else ""}
        row["place_of_supply_name"] = GST_STATES.get(bill.place_of_supply or "", "")
        row["amount_in_words"] = amount_in_words(bill.net_payable)
        row["work_order_detail"] = ({"number": wo.number, "date": wo.order_date or "",
                                     "reference": wo.reference or "",
                                     "value": money(wo.total_value)} if wo else {})
        row["einvoice"] = irn_brief(db, bill.client_id, "ra_bill", bill.id)
    return row


def dimensions_for(db, entry_ids, column):
    """The dimension lines of many entries in one query, keyed by entry."""
    out = {}
    if not entry_ids:
        return out
    for d in db.query(models.DBMeasurementDimension).filter(
            column.in_(entry_ids)).order_by(
                models.DBMeasurementDimension.display_order,
                models.DBMeasurementDimension.id).all():
        out.setdefault(getattr(d, column.key), []).append({
            "particulars": d.particulars or "", "nos": d.nos, "nom": getattr(d, "nom", None),
            "length": d.length, "breadth": d.breadth, "depth": d.depth, "deduct": bool(d.deduct),
            "is_heading": bool(getattr(d, "is_heading", False)), "quantity": d.quantity or 0,
        })
    return out


def ra_apply(db, client, bill, action, actor_id, actor_name, comments=""):
    """One door for every state change on a bill."""
    was = bill.status or "DRAFT"
    allowed = RA_TRANSITIONS.get(was, {})
    if action == "CANCEL" and was in ("CERTIFIED", "PAID"):
        raise HTTPException(
            409, "%s is %s and is not cancelled: its GST and TDS are in the returns. Take back what was "
                 "over-billed with a credit note." % (bill.number, was.lower()))
    if action not in allowed:
        raise HTTPException(
            409, "%s is %s; it cannot be %s from there." %
                 (bill.number, was.lower(),
                  {"SUBMIT": "submitted", "CERTIFY": "certified", "REJECT": "sent back",
                   "PAY": "paid", "CANCEL": "cancelled"}.get(action, action.lower())))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if action == "SUBMIT":
        # Redrawn from the book as it stands, because a draft can sit for days
        # while the site corrects what it measured. Submitting the figures the
        # draft was born with would send an approver a claim for work the book
        # no longer says was done.
        wo = db.query(models.DBWorkOrder).filter(
            models.DBWorkOrder.id == bill.work_order_id).first()
        if wo:
            write_ra_bill_lines(db, bill, claimable_lines(
                db, wo, exclude_bill_id=bill.id))
        bill.submitted_by = actor_id
        if money(bill.this_bill) <= 0:
            raise HTTPException(
                400, "There is nothing left to claim - the measurements behind "
                     "this bill have been withdrawn since it was drawn up.")
        over = over_order_lines(db, bill)
        if over:
            raise HTTPException(
                409, "%s claims past the order: %s. Raise a variation for the extra work and have it approved, "
                     "then redraw the bill." % (bill.number, "; ".join(
                         "'%s' %s billed against %s ordered" % (o["description"], o["billed"], o["ordered"])
                         for o in over)))
        check_deductions(db, bill)
        # The measurements behind it are pinned to the bill, so a later entry
        # cannot quietly join a claim that has already gone up for signature.
        for line in db.query(models.DBRABillLine).filter(
                models.DBRABillLine.ra_bill_id == bill.id).all():
            db.query(models.DBMeasurement).filter(
                models.DBMeasurement.work_order_id == bill.work_order_id,
                models.DBMeasurement.line_id == line.line_id,
                models.DBMeasurement.ra_bill_id.is_(None)).update(
                    {"ra_bill_id": bill.id}, synchronize_session=False)
    elif action == "REJECT":
        if not (comments or "").strip():
            raise HTTPException(400, "Say why it is going back, so it can be corrected.")
        bill.remarks = (comments or "").strip()
        db.query(models.DBMeasurement).filter(
            models.DBMeasurement.ra_bill_id == bill.id).update(
                {"ra_bill_id": None}, synchronize_session=False)
    elif action == "CERTIFY":
        bill.certified_by, bill.certified_by_name = actor_id, actor_name
        bill.certified_at = now
        bill.remarks = (comments or "").strip() or bill.remarks
    elif action == "PAY":
        bill.paid_at = now
    elif action == "CANCEL":
        if not (comments or "").strip():
            raise HTTPException(400, "Say why it is being cancelled.")
        bill.remarks = (comments or "").strip()
        # The work was still done; it goes back to the pool for the next bill.
        db.query(models.DBMeasurement).filter(
            models.DBMeasurement.ra_bill_id == bill.id).update(
                {"ra_bill_id": None}, synchronize_session=False)

    bill.status = allowed[action]
    bill.updated_at = now
    return bill


def refuse_cancel_with_money(db, client_id, doc_type, bill, verb):
    """A bill with money against it is not cancelled out from under it: the
    receipts would stay in the ledger and the bank book against a bill that
    no longer counts, and the party's balance would be off by exactly them."""
    got = money(settled_on(db, client_id, doc_type, bill.id))
    if got > 0:
        raise HTTPException(409, "%s has %s %s against it. Void those entries under "
                                 "Payments & Ledgers before cancelling it."
                                 % (bill.number, inr(got), verb))


def _ra_action(bill_id, action, body, request, db, permission="billing.manage"):
    client, actor_id, actor_name = wo_actor(request, db, permission)
    bill = ra_bill_or_404(db, client.id, bill_id)
    if action == "CERTIFY" and actor_id is not None and bill.submitted_by == actor_id:
        raise HTTPException(403, "You raised this bill, so somebody else has to certify it.")
    if action == "CANCEL" and (bill.status or "") not in ("CERTIFIED", "PAID"):
        refuse_cancel_with_money(db, client.id, "ra_bill", bill, "received")
        refuse_cancel_with_irn(db, client.id, "ra_bill", bill)
    ra_apply(db, client, bill, action, actor_id, actor_name, body.comments)
    log_audit(db, client.id, "ra_bill_" + action.lower(), "ra_bill", bill.id,
              bill.number, (body.comments or "").strip(), request)
    db.commit()
    db.refresh(bill)
    if action in ("SUBMIT", "CERTIFY"):
        job = db.query(models.DBJob).filter(models.DBJob.id == bill.job_id).first()
        if action == "SUBMIT":
            notify(db, client.id, "ra_bill_submitted", "%s is waiting to be certified" % bill.number,
                   "%s of work claimed on %s." % (inr(bill.this_bill), job.name if job else "the project"),
                   view="measurement-view", ref_type="ra_bill", ref_id=bill.id, severity="action")
        else:
            notify(db, client.id, "ra_bill_certified", "%s certified" % bill.number,
                   "%s to receive from %s, net of retention and TDS." % (
                       inr(bill.net_payable), (job.customer_name if job else "") or "the client"),
                   view="ledger-view", ref_type="ra_bill", ref_id=bill.id, severity="money")
        db.refresh(bill)
    return {"bill": ra_bill_dict(db, bill, detail=True),
            "message": "%s %s." % (bill.number, bill.status.lower())}


def received_to_date(db, purchase_order_id, exclude_grn_id=None):
    """Quantity accepted against each order line, over every live receipt.

    Cancelled receipts are excluded: a delivery that was cancelled did not
    arrive, and holding its quantity back would stop the replacement delivery
    from ever being recorded.
    """
    live = db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.purchase_order_id == purchase_order_id,
        models.DBGoodsReceipt.status != "CANCELLED").all()
    ids = [g.id for g in live if g.id != exclude_grn_id]
    # What the Store Hub has received against the order counts too, in the order line's unit.
    from app.services.store_integration import hub_received_on_orders
    totals = dict(hub_received_on_orders(db, [purchase_order_id])[0].get(purchase_order_id, {}))
    if not ids:
        return totals
    for l in db.query(models.DBGoodsReceiptLine).filter(
            models.DBGoodsReceiptLine.goods_receipt_id.in_(ids)).all():
        totals[l.po_line_id] = totals.get(l.po_line_id, 0.0) + (l.accepted_qty or 0.0)
    return totals


def next_vo_number(db, work_order):
    n = (db.query(func.max(models.DBVariationOrder.sequence)).filter(
        models.DBVariationOrder.work_order_id == work_order.id).scalar() or 0) + 1
    while db.query(models.DBVariationOrder.id).filter(
            models.DBVariationOrder.client_id == work_order.client_id,
            models.DBVariationOrder.number == "%s/VO-%02d" % (work_order.number or "WO", n)).first():
        n += 1
    return "%s/VO-%02d" % (work_order.number or "WO", n), n


def vo_or_404(db, client_id, vo_id):
    row = db.query(models.DBVariationOrder).filter(
        models.DBVariationOrder.id == vo_id,
        models.DBVariationOrder.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Variation not found")
    return row


def over_measured_lines(db, work_order):
    """Every line the site has built past its ordered quantity.

    This is the whole input to a variation, and it is already sitting in the
    measurement book. Nobody should have to read it off a screen and type it
    back in.
    """
    measured = measured_to_date(db, work_order.id)
    out = []
    for l in db.query(models.DBWorkOrderLine).filter(
            models.DBWorkOrderLine.work_order_id == work_order.id).order_by(
                models.DBWorkOrderLine.id).all():
        done, ordered = money(measured.get(l.id, 0.0)), money(l.qty)
        if done > ordered:
            extra = money(done - ordered)
            out.append({
                "line_id": l.id, "fg_code": l.fg_code or "",
                "description": (l.description or l.item_name or "").split("\n")[0],
                "uom": l.uom or "", "ordered_qty": ordered, "measured_qty": done,
                "extra_qty": extra, "rate": unit_rate(l.rate),
                "amount": money(extra * unit_rate(l.rate)),
            })
    return out


def recost_variation(db, vo):
    lines = db.query(models.DBVariationLine).filter(
        models.DBVariationLine.variation_order_id == vo.id).all()
    vo.value = money(sum(l.amount or 0 for l in lines))
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == vo.work_order_id).first()
    vo.order_value_before = money(wo.total_value if wo else 0)
    vo.order_value_after = money(vo.order_value_before + vo.value)
    vo.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return vo


def vo_dict(db, vo, detail=False):
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == vo.work_order_id).first()
    row = {
        "id": vo.id, "number": vo.number or "", "sequence": vo.sequence or 1,
        "work_order_id": vo.work_order_id, "work_order": wo.number if wo else "",
        "status": vo.status or "DRAFT", "origin": vo.origin or "manual",
        "reason": vo.reason or "", "value": money(vo.value),
        "order_value_before": money(vo.order_value_before),
        "order_value_after": money(vo.order_value_after),
        "raised_by_name": vo.raised_by_name or "",
        "approved_by_name": vo.approved_by_name or "",
        "approved_at": vo.approved_at or "",
        "rejection_reason": vo.rejection_reason or "",
        "actions": sorted(VO_TRANSITIONS.get(vo.status or "DRAFT", {}).keys()),
        "editable": (vo.status or "DRAFT") == "DRAFT",
        "created_at": vo.created_at or "",
    }
    if detail:
        row["lines"] = [{
            "id": l.id, "line_id": l.line_id, "fg_code": l.fg_code or "",
            "description": l.description or "", "uom": l.uom or "",
            "ordered_qty": money(l.ordered_qty), "measured_qty": money(l.measured_qty),
            "extra_qty": money(l.extra_qty), "rate": unit_rate(l.rate),
            "amount": money(l.amount),
            "is_new_item": l.line_id is None,
        } for l in db.query(models.DBVariationLine).filter(
            models.DBVariationLine.variation_order_id == vo.id).order_by(
                models.DBVariationLine.display_order, models.DBVariationLine.id).all()]
    return row


def apply_variation(db, vo):
    """Raise the order to match what was agreed.

    An existing line has its quantity lifted to the measured figure; a new item
    becomes a real order line so the book can be kept against it from now on.
    Done once, on approval, and never again - applied_at is the guard.
    """
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == vo.work_order_id).first()
    for l in db.query(models.DBVariationLine).filter(
            models.DBVariationLine.variation_order_id == vo.id).all():
        if l.line_id:
            # Only a line of this order: a variation never reaches into another order, or another company's.
            line = db.query(models.DBWorkOrderLine).filter(
                models.DBWorkOrderLine.id == l.line_id,
                models.DBWorkOrderLine.work_order_id == wo.id).first()
            if not line:
                continue
            line.qty = money((line.qty or 0) + l.extra_qty)
            line.amount = money(line.qty * (line.rate or 0))
        else:
            db.add(models.DBWorkOrderLine(
                work_order_id=wo.id, fg_code=l.fg_code, item_name=l.description,
                description=l.description, qty=l.extra_qty, uom=l.uom,
                rate=l.rate, amount=l.amount))
    db.flush()
    total = sum(money(x.amount) for x in db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).all())
    wo.total_value = money(total)
    vo.applied_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return wo


def _words(value):
    text = amount_in_words(value)
    return re.sub(r"^Rupees\s+", "", text)


def order_variations(db, bill):
    """The variations to the BOQ agreed on the order a client bill is against, as they stood on the bill's date:
    the order's value as first placed, each variation up to that date, and the value as varied. None when the
    order was not drawn from a BOQ or has no approved variation."""
    wo = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == bill.work_order_id).first()
    if (bill.status or "") in ("CERTIFIED", "PAID"):
        cutoff = ((bill.certified_at or "") or bill.created_at or "")[:10]
    else:
        cutoff = datetime.now().strftime("%Y-%m-%d")
    return wo_variations(db, wo, cutoff)


def refuse_unapproved_order(wo, verb):
    """A client work order is measured and billed once it is approved - the
    budget and the margin have been looked at, and not before."""
    if (wo.approval_status or "") != "approved":
        where = {"pending": "It is waiting for approval.", "rejected": "It was sent back and has to be sent again."}.get(
            wo.approval_status or "", "Send it for approval first.")
        raise HTTPException(409, "Only an approved work order can be %s. %s" % (verb, where))


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.notifications import notify
from app.documents.letterhead import our_party
from app.services.crm import settled_on
from app.services.invoicing import irn_brief, refuse_cancel_with_irn
from app.services.subcontract_orders import wo_variations
