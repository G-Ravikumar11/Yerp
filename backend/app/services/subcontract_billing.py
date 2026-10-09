"""The rules and workings behind the subcontract billing endpoints."""
import os
import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import or_

from app import models

from app.constants.approvals import GONE_STATUSES
from app.constants.common import SUB_TRANSITIONS
from app.constants.projects import JOB_FINISHED
from app.core.audit import log_audit
from app.core.auth import STAFF_VIEWER, current_role
from app.core.currency import amount_in_words, format_money_plain, inr, money, rupees, unit_rate
from app.core.dates import months_after
from app.core.gst import GST_STATES, WORKS_CONTRACT_SAC, our_state, split_gst, supply_state_for_job
from app.core.permissions import employee_can
from app.core.queries import by_id, chain_rows, forget_chain
from app.services.compliance import contractor_compliance


#
# Same rule as a work order: the owner's alone, with a preview of what goes, and what hangs off it goes with it.
def _is_owner(request, db):
    try:
        return current_role(request, db) == "owner"
    except HTTPException:
        return False


def dimension_quantity(d):
    """No x L x B x D, using only the dimensions that were given.

    A blank dimension is one that does not apply - an area has no depth, a
    count has no length - not a zero. A zero that was typed is a zero: it is
    a line that measures nothing, and it is refused below rather than
    silently multiplied away.
    """
    if getattr(d, "is_heading", False):
        return 0.0
    given = [v for v in (getattr(d, "nom", None), d.length, d.breadth, d.depth) if v is not None]
    qty = float(d.nos) if d.nos is not None else 1.0
    for v in given:
        qty *= float(v)
    return round(qty, 3)


def dimension_total(dims):
    """What the dimension lines come to, signed, having checked each one.

    A row with no figures on it is a row somebody meant to fill in, and a
    negative figure is a deduction written the wrong way; both are refused
    rather than quietly multiplied into the total.
    """
    total = 0.0
    for index, d in enumerate(dims or []):
        if getattr(d, "is_heading", False):
            if not (d.particulars or "").strip():
                raise HTTPException(400, "Heading line %d has no words on it." % (index + 1))
            continue
        if all(v is None for v in (d.nos, getattr(d, "nom", None), d.length, d.breadth, d.depth)):
            raise HTTPException(400, "Dimension line %d has no figures on it." % (index + 1))
        for name, v in (("nos", d.nos), ("NoM", getattr(d, "nom", None)), ("length", d.length),
                        ("breadth", d.breadth), ("depth", d.depth)):
            if v is not None and v < 0:
                raise HTTPException(400, "Dimension line %d: %s cannot be negative. "
                                         "Mark the line as a deduction instead."
                                         % (index + 1, name))
        qty = dimension_quantity(d)
        if not qty:
            raise HTTPException(400, "Dimension line %d comes to nothing." % (index + 1))
        total += -qty if d.deduct else qty
    return round(total, 3)


def write_dimensions(db, client_id, dims, measurement_id=None, sub_measurement_id=None):
    """The dimension lines, written against the entry they belong to."""
    for index, d in enumerate(dims or []):
        qty = dimension_quantity(d)
        heading = bool(getattr(d, "is_heading", False))
        db.add(models.DBMeasurementDimension(
            client_id=client_id, measurement_id=measurement_id,
            sub_measurement_id=sub_measurement_id,
            particulars=(d.particulars or "").strip(),
            nos=None if heading else d.nos, nom=None if heading else getattr(d, "nom", None),
            length=None if heading else d.length, breadth=None if heading else d.breadth,
            depth=None if heading else d.depth, deduct=bool(d.deduct) and not heading,
            is_heading=heading, quantity=-qty if (d.deduct and not heading) else qty,
            display_order=index))


# SUBCONTRACTOR MEASUREMENT AND BILLS - THE MONEY GOING OUT
#
# A work order is what the client buys from us; an RA bill against it is money
# coming in. A subcontract order is what we buy from a gang, and until now it
# could be signed but never measured or billed. The money going out to the
# people actually doing the work was not in the app, and the P&L was
# flattered by exactly that amount.
#
# Same shape as the client side on purpose. The difference is who holds the
# retention: here it is us, and TDS is what we withhold and remit.
def past_tense(action):
    """"cannot be certified", not "certifyed": the word an action turns into once done."""
    word = (action or "").lower()
    return {"submit": "submitted", "certify": "certified", "reject": "sent back", "pay": "paid",
            "cancel": "cancelled", "post": "posted", "approve": "approved"}.get(word, word + "ed")


def sub_measured_to_date(db, order_id):
    totals = {}
    for m in db.query(models.DBSubMeasurement).filter(
            models.DBSubMeasurement.order_id == order_id).all():
        totals[m.item_id] = totals.get(m.item_id, 0.0) + (m.quantity or 0.0)
    return totals


def sub_billed_to_date(db, order_id, exclude_bill_id=None):
    live = db.query(models.DBSubBill).filter(
        models.DBSubBill.order_id == order_id,
        models.DBSubBill.status != "CANCELLED").all()
    ids = [b.id for b in live if b.id != exclude_bill_id]
    totals = {}
    if not ids:
        return totals
    for l in db.query(models.DBSubBillLine).filter(
            models.DBSubBillLine.sub_bill_id.in_(ids)).all():
        totals[l.item_id] = totals.get(l.item_id, 0.0) + (l.this_bill_qty or 0.0)
    return totals


def sub_bill_or_404(db, client_id, bill_id):
    row = db.query(models.DBSubBill).filter(
        models.DBSubBill.id == bill_id,
        models.DBSubBill.client_id == client_id).first()
    if not row or not sub_bill_visible(db, row, STAFF_VIEWER.get()):
        raise HTTPException(404, "Bill not found")
    return row


def sub_bill_visible_ids(db, client_id, emp_id):
    """The bills a member of staff may see: those of orders they have a hand in, or that they sent or have to sign."""
    orders = wo_involved_ids(db, client_id, emp_id)
    ids = {r[0] for r in db.query(models.DBSubBill.id).filter(
        models.DBSubBill.client_id == client_id,
        or_(models.DBSubBill.order_id.in_(list(orders) or [0]), models.DBSubBill.submitted_by == emp_id)).all()}
    ids |= {r[0] for r in db.query(models.DBApprovalChain.entity_id).filter(
        models.DBApprovalChain.entity_type == "sub_bill", models.DBApprovalChain.approver_id == emp_id).all()}
    return ids


def sub_bill_visible(db, bill, emp_id):
    if not emp_id:
        return True
    return bill.id in sub_bill_visible_ids(db, bill.client_id, emp_id)


def recost_sub_bill(db, bill):
    """The Certificate of Payment's arithmetic, row for row.

    4.01 is the work measured in this bill, and it is the base for every tax:
    GST (4.05 to 4.08), retention (5.03), TDS (5.04) and labour cess are all
    on it. Recoveries in debit notes (4.04) come off the payable, not off the
    value the tax is charged on - the gang's invoice is for the whole of the
    work; what we hold back is not a discount on it. Then the deductions: the advance and
    the material or other recoveries (5.01, 5.02), retention (5.03) and TDS
    (5.04), both on the value of the work, and the labour cess where the
    order carries one. Every figure after the work itself is in whole
    rupees, as the certificate rounds them.
    """
    lines = db.query(models.DBSubBillLine).filter(
        models.DBSubBillLine.sub_bill_id == bill.id).all()
    this_bill = money(sum(l.amount or 0 for l in lines))
    bill.this_bill = this_bill
    if bill.id:
        # An earlier bill cancelled since this one was drawn up has handed its work to it: it is no longer "claimed before".
        bill.previously_billed = money(sum(b.this_bill or 0 for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.order_id == bill.order_id, models.DBSubBill.id < bill.id,
            models.DBSubBill.status != "CANCELLED").all()))
    bill.gross_to_date = money((bill.previously_billed or 0) + this_bill)
    bill.debit_notes = money(getattr(bill, "debit_notes", 0) or 0)
    gross = rupees(this_bill - bill.debit_notes)
    supply = supply_state_for_job(db, bill.job_id)
    # It is the gang's supply, so it is their registration against the site
    # that decides the split - ours only when they have none on file.
    origin = contractor_state(db, bill.contractor_id) or our_state(db, bill.client_id)
    gst = split_gst(rupees(this_bill), bill.gst_percent or 0, origin, supply)
    bill.cgst_amount, bill.sgst_amount, bill.igst_amount = (
        rupees(gst["cgst"]), rupees(gst["sgst"]), rupees(gst["igst"]))
    bill.gst_amount = money(bill.cgst_amount + bill.sgst_amount + bill.igst_amount)
    bill.place_of_supply = supply
    bill.retention_amount = rupees(this_bill * (bill.retention_percent or 0) / 100.0)
    bill.tds_amount = rupees(this_bill * (bill.tds_percent or 0) / 100.0)
    bill.labour_cess_amount = rupees(this_bill * (bill.labour_cess_percent or 0) / 100.0)
    deductions = ((bill.advance_recovery or 0) + (bill.other_deductions or 0) + (bill.back_charges or 0) + bill.retention_amount
                  + bill.tds_amount + bill.labour_cess_amount)
    bill.net_payable = rupees(gross + bill.gst_amount - deductions)
    bill.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return bill


def sub_bill_room(bill):
    """What more this bill can have taken off it: the gross, less everything
    already deducted. The GST on top is left alone - it is the gang's to pay
    over to the government, and recovering an advance out of it leaves them
    owing tax on money they never received."""
    return money(rupees((bill.this_bill or 0) - (bill.debit_notes or 0))
                 - (bill.advance_recovery or 0) - (bill.other_deductions or 0) - (bill.back_charges or 0)
                 - (bill.retention_amount or 0) - (bill.tds_amount or 0)
                 - (bill.labour_cess_amount or 0))


def bill_scan_required():
    """A contractor's bill must have its hard copy attached before it is sent for approval. (Switched off only for the
    test suite, whose bills have no paper behind them.)"""
    return os.getenv("REQUIRE_BILL_SCAN", "1").strip() not in ("0", "false", "no")


def sub_bill_dict(db, bill, detail=False):
    order = by_id(db, models.DBSubcontractOrder, bill.order_id)
    con = by_id(db, models.DBContractor, bill.contractor_id)
    job = by_id(db, models.DBJob, bill.job_id)
    row = {
        "id": bill.id, "number": bill.number or "", "sequence": bill.sequence or 1,
        "order_id": bill.order_id, "order": order.wo_number if order else "",
        "contractor": con.company_name if con else "",
        "job_id": bill.job_id,
        "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
        "status": bill.status or "DRAFT",
        "period_from": bill.period_from or "", "period_to": bill.period_to or "",
        "gross_to_date": money(bill.gross_to_date),
        "previously_billed": money(bill.previously_billed),
        "this_bill": money(bill.this_bill),
        "retention_percent": bill.retention_percent or 0,
        "retention_amount": money(bill.retention_amount),
        "advance_recovery": money(bill.advance_recovery),
        "other_deductions": money(bill.other_deductions),
        "back_charges": money(bill.back_charges),
        "deduction_notes": bill.deduction_notes or "",
        "gst_percent": bill.gst_percent or 0, "gst_amount": money(bill.gst_amount),
        "cgst_amount": money(bill.cgst_amount), "sgst_amount": money(bill.sgst_amount),
        "igst_amount": money(bill.igst_amount), "place_of_supply": bill.place_of_supply or "",
        "cgst_percent": (bill.gst_percent or 0) / 2.0 if (bill.cgst_amount or bill.sgst_amount) else 0,
        "sgst_percent": (bill.gst_percent or 0) / 2.0 if (bill.cgst_amount or bill.sgst_amount) else 0,
        "igst_percent": (bill.gst_percent or 0) if bill.igst_amount else 0,
        "taxable_value": money(bill.this_bill),
        "tds_percent": bill.tds_percent or 0, "tds_amount": money(bill.tds_amount),
        "labour_cess_percent": bill.labour_cess_percent or 0,
        "labour_cess_amount": money(bill.labour_cess_amount),
        "net_payable": money(bill.net_payable),
        "certified_by_name": bill.certified_by_name or "",
        "certified_at": bill.certified_at or "", "paid_at": bill.paid_at or "",
        "paid_reference": bill.paid_reference or "", "remarks": bill.remarks or "",
        "editable": (bill.status or "DRAFT") == "DRAFT",
        "actions": sorted(SUB_TRANSITIONS.get(bill.status or "DRAFT", {}).keys()),
        "created_at": bill.created_at or "",
        "vendor_code": (con.vendor_code or "") if con else "",
        "bill_date": getattr(bill, "bill_date", "") or (bill.created_at or "")[:10],
        "work_type": getattr(bill, "work_type", "") or "",
        "work_name": getattr(bill, "work_name", "") or "",
        "hsn_sac": getattr(bill, "hsn_sac", "") or "",
        "debit_notes": money(getattr(bill, "debit_notes", 0)),
        "gross_value": rupees((bill.this_bill or 0) - (getattr(bill, "debit_notes", 0) or 0)),
        "submitted_by_name": getattr(bill, "submitted_by_name", "") or "",
        "submitted_at": getattr(bill, "submitted_at", "") or "",
        "approved_by_name": getattr(bill, "approved_by_name", "") or "",
        "accepted_by_name": getattr(bill, "accepted_by_name", "") or "",
        "accepted_at": getattr(bill, "accepted_at", "") or "",
        "entry_mode": bill.entry_mode or "",
        "scan_required": bill_scan_required(),
        "hardcopy": ({"name": bill.scan_name or "", "type": bill.scan_type or "", "size": bill.scan_size or 0,
                      "amount": bill.scan_amount, "by": bill.scan_by_name or "", "at": bill.scan_at or "",
                      "difference": money((bill.this_bill or 0) - bill.scan_amount) if bill.scan_amount is not None else None}
                     if bill.scan_file_id else None),
    }
    if (bill.status or "") == "SUBMITTED":
        ensure_sub_bill_chain(db, bill)
    route = sub_bill_route(db, bill)
    row["route"] = route
    row["waiting_on"] = next((r["name"] for r in route if r["status"] == "waiting"), "")
    row["waiting_on_id"] = next((r["approver_id"] for r in route if r["status"] == "waiting"), None)
    if detail:
        # What would make paying them unsafe - a lapsed licence, a missing registration - shown where the bill is read.
        row["compliance_warnings"] = contractor_compliance(db, bill.client_id, bill.contractor_id)["warnings"]
        row["open_back_charges"] = [{"id": c.id, "number": c.number, "kind": c.kind, "reason": c.reason, "amount": money(c.amount)}
                                    for c in db.query(models.DBBackCharge).filter(
                                        models.DBBackCharge.client_id == bill.client_id,
                                        models.DBBackCharge.contractor_id == bill.contractor_id,
                                        models.DBBackCharge.status == "OPEN").all()]
        row["applied_back_charges"] = [{"id": c.id, "number": c.number, "kind": c.kind, "reason": c.reason, "amount": money(c.amount)}
                                       for c in db.query(models.DBBackCharge).filter(
                                           models.DBBackCharge.applied_bill_id == bill.id,
                                           models.DBBackCharge.status == "APPLIED").all()]
        row["lines"] = [{
            "id": l.id, "item_id": l.item_id, "activity_no": l.activity_no or "",
            "description": (l.description or "").split("\n")[0], "uom": l.uom or "",
            "ordered_qty": money(l.ordered_qty), "measured_to_date": money(l.measured_to_date),
            "previously_billed_qty": money(l.previously_billed_qty),
            "this_bill_qty": money(l.this_bill_qty), "rate": unit_rate(l.rate),
            "amount": money(l.amount),
            "upto_date_amount": money(money(l.measured_to_date) * unit_rate(l.rate)),
        } for l in db.query(models.DBSubBillLine).filter(
            models.DBSubBillLine.sub_bill_id == bill.id).order_by(
                models.DBSubBillLine.display_order, models.DBSubBillLine.id).all()]
        row["entries"] = [{"id": m.id, "code": m.code or "", "kind": m.kind or "", "quantity": money(m.quantity),
                           "activity_no": m.activity_no or "", "location": m.location or "", "measured_on": m.measured_on or ""}
                          for m in db.query(models.DBSubMeasurement).filter(
                              models.DBSubMeasurement.sub_bill_id == bill.id).order_by(
                                  models.DBSubMeasurement.code_no, models.DBSubMeasurement.id).limit(500).all()]
        row["our"] = our_party(db, bill.client_id)
        row["contractor_detail"] = ({"name": con.company_name or "", "gstin": con.gst_number or "",
                                     "pan": con.pan or "", "address": con.address or "",
                                     "contact": con.contact_person or ""} if con else {})
        row["site"] = job.site_address if job else ""
        row["place_of_supply_name"] = GST_STATES.get(bill.place_of_supply or "", "")
        row["amount_in_words"] = amount_in_words(bill.net_payable)
        row["material_recovered"] = money(sum(r.amount or 0 for r in db.query(models.DBMaterialRecovery).filter(
            models.DBMaterialRecovery.client_id == bill.client_id,
            models.DBMaterialRecovery.sub_bill_id == bill.id).all()))
        row["order_detail"] = ({"number": order.wo_number, "subject": order.subject or "",
                                "value": money(order.net_order_value),
                                "retention_percent": order.retention_percent or 0,
                                "commencement_date": order.commencement_date or "",
                                "completion_date": order.completion_date or ""} if order else {})
    return row


def sub_measure_multiplier(value):
    try:
        m = float(value if value not in (None, "") else 1)
    except (TypeError, ValueError):
        raise HTTPException(400, "The number of blocks has to be a number.")
    if m <= 0:
        raise HTTPException(400, "The number of blocks has to be one or more.")
    return m


def add_sub_measurement(db, client, order, item, body, actor_id, actor_name):
    """One entry in the gang's book, checked and written."""
    if item.is_header:
        raise HTTPException(400, "%s is a heading, not a measurable item."
                                 % (item.activity_no or "That line"))
    multiplier = sub_measure_multiplier(getattr(body, "multiplier", 1))
    quantity = money(body.quantity or 0)
    if body.dimensions:
        quantity = money(dimension_total(body.dimensions))
    quantity = money(quantity * multiplier)
    if not quantity:
        raise HTTPException(400, "A measurement of nothing is not a measurement")
    # The order plus its tolerance is the ceiling. Past it the order is amended
    # and the extra measured against the amendment - the book does not quietly
    # commit the business to more than anybody signed for. A correction
    # (a negative entry) always goes in.
    if quantity > 0:
        done = money(sub_gross_measured(db, order.id).get(item.id, 0.0))
        ceiling = item_ceiling(item)
        if money(done + quantity) > ceiling + 0.0001:
            raise HTTPException(
                409, "%s: %s already measured; %s more would make %s against %s "
                     "ordered%s. Amend the order to measure beyond it."
                     % (item.activity_no or "Item", done, quantity,
                        money(done + quantity), money(item.quantity),
                        " (+%g%% tolerance = %s)" % (item.tolerance_percent, ceiling)
                        if item.tolerance_percent else ""))
    entry = models.DBSubMeasurement(
        client_id=client.id, order_id=order.id, item_id=item.id,
        activity_no=item.activity_no or "", quantity=quantity, multiplier=multiplier,
        measured_on=(body.measured_on or datetime.now().strftime("%Y-%m-%d")),
        mb_ref=(body.mb_ref or "").strip(), location=(body.location or "").strip()[:200],
        remarks=(body.remarks or "").strip(),
        section=(body.section or "").strip()[:200], block_label=(body.block_label or "").strip()[:20],
        group_ref=(body.group_ref or "").strip()[:40],
        recorded_by=actor_id, recorded_by_name=actor_name)
    db.add(entry)
    db.flush()
    write_dimensions(db, client.id, body.dimensions, sub_measurement_id=entry.id)
    return entry


def mb_item_label(it):
    """An item as it is named when somebody has to choose it: code, activity number, then the words."""
    return " ".join(x for x in ((it.item_code or "").strip(), (it.activity_no or "").strip(),
                                (it.item_description or "").split("\n")[0].strip()) if x)


def mb_match_item(items, description, sno=""):
    """The order's item a section of the book is for. By code first - the section's number or a
    code written in its heading, against the item's code or activity number - then by its
    description: the same words, one inside the other, then the most words in common.
    None when nothing is close enough to say."""
    def squash(t):
        return re.sub(r"[^a-z0-9]+", "", (t or "").lower())
    coded = [(it, {squash(it.item_code), squash(it.activity_no)} - {""}) for it in items]
    # A serial number in the sheet is not an activity number - section "2" is not the order's line 2 -
    # so only an item code is matched against it.
    key = squash(sno)
    if key and not key.isdigit():
        hit = [it for it in items if squash(it.item_code) == key]
        if len(hit) == 1:
            return hit[0]
    heading = {squash(w) for w in re.sub(r"[^a-z0-9]+", " ", (description or "").lower()).split()}
    hit = [it for it, codes in coded if any(c in heading for c in codes if len(c) >= 3)]
    if len(hit) == 1:
        return hit[0]
    want = re.sub(r"[^a-z0-9]+", " ", (description or "").lower()).strip()
    if not want:
        return None
    def words(t):
        return set(re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split())
    plain = [(it, re.sub(r"[^a-z0-9]+", " ", (it.item_description or "").split("\n")[0].lower()).strip())
             for it in items]
    same = [it for it, d in plain if d == want]
    if len(same) == 1:
        return same[0]
    inside = [it for it, d in plain if d and (want in d or d in want)]
    if len(inside) == 1:
        return inside[0]
    best, score = None, 0.0
    w = words(want)
    for it, d in plain:
        common = len(w & words(d)) / float(len(w | words(d)) or 1)
        if common > score:
            best, score = it, common
    return best if score >= 0.5 else None


#
# Work that is measured but not yet to be paid for - the share held for finishes and handing over,
# say - is held in the book. A hold is an entry of its own that takes the quantity out of what can
# be billed, with the reason beside it; releasing it puts the quantity back as a new entry, so the
# next bill picks it up. The book keeps both, so what is held, and why, can always be read back.
def sub_held_to_date(db, order_id):
    """What is still held, by item: each hold less whatever has been released from it."""
    held, released = {}, {}
    for m in db.query(models.DBSubMeasurement).filter(
            models.DBSubMeasurement.order_id == order_id,
            models.DBSubMeasurement.kind.in_(("hold", "release"))).all():
        if m.kind == "hold":
            held[m.id] = (m.item_id, -(m.quantity or 0.0))
        else:
            released[m.hold_of] = released.get(m.hold_of, 0.0) + (m.quantity or 0.0)
    out = {}
    for hid, (item_id, qty) in held.items():
        out[item_id] = out.get(item_id, 0.0) + max(0.0, qty - released.get(hid, 0.0))
    return out


def sub_gross_measured(db, order_id):
    """What has been measured, held or not - the figure the order's ceiling is held against."""
    net = sub_measured_to_date(db, order_id)
    for item_id, qty in sub_held_to_date(db, order_id).items():
        net[item_id] = net.get(item_id, 0.0) + qty
    return net


def sub_hold_remaining(db, hold):
    got = sum((m.quantity or 0.0) for m in db.query(models.DBSubMeasurement).filter(
        models.DBSubMeasurement.kind == "release", models.DBSubMeasurement.hold_of == hold.id).all())
    return money(max(0.0, -(hold.quantity or 0.0) - got))


def sub_claimable_lines(db, order, exclude_bill_id=None):
    measured = sub_measured_to_date(db, order.id)
    billed = sub_billed_to_date(db, order.id, exclude_bill_id)
    out = []
    for it in db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == order.id).order_by(
                models.DBSubcontractItem.display_order, models.DBSubcontractItem.id).all():
        if it.is_header:
            continue
        done = money(measured.get(it.id, 0.0))
        prior = money(billed.get(it.id, 0.0))
        this = money(done - prior)
        if this <= 0:
            continue
        out.append((it, done, prior, this))
    return out


def chosen_entries_for_bill(db, order, entry_ids):
    """The entries a bill for chosen entries takes: the ones asked for; the whole group of blocks that shares a
    hold with any of them (a hold is on the group, so the group is billed together); and that group's holds and
    their releases. Refuses an entry that is not in this order's book or is already on a bill."""
    rows = db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id == order.id).all()
    by_id = {r.id: r for r in rows}
    chosen = {}
    for i in entry_ids:
        r = by_id.get(i)
        if r is None:
            raise HTTPException(404, "Entry %s is not in this order's measurement book." % i)
        if r.sub_bill_id:
            raise HTTPException(409, "%s is already on a bill." % (r.code or "Entry %s" % i))
        chosen[r.id] = r
    groups = {(r.item_id, r.group_ref) for r in chosen.values() if r.group_ref}
    for r in rows:
        if r.group_ref and (r.item_id, r.group_ref) in groups and not r.sub_bill_id:
            chosen[r.id] = r
    holds = {r.id for r in chosen.values() if r.kind == "hold"}
    for r in rows:
        if r.kind == "release" and r.hold_of in holds and not r.sub_bill_id:
            chosen[r.id] = r
    return list(chosen.values())


def chosen_claims(db, order, entries, exclude_bill_id=None):
    """(item, measured to date, billed before, this claim) for the items the entries touch. The claim is what the
    entries come to, and may not be nothing or more than the item has left to bill."""
    measured = sub_measured_to_date(db, order.id)
    billed = sub_billed_to_date(db, order.id, exclude_bill_id)
    claim = {}
    for e in entries:
        claim[e.item_id] = money(claim.get(e.item_id, 0.0) + (e.quantity or 0.0))
    out = []
    for it in db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == order.id,
            models.DBSubcontractItem.id.in_(list(claim) or [0])).order_by(
                models.DBSubcontractItem.display_order, models.DBSubcontractItem.id).all():
        this = claim[it.id]
        done = money(measured.get(it.id, 0.0))
        prior = money(billed.get(it.id, 0.0))
        label = it.activity_no or "Item"
        if this <= 0:
            raise HTTPException(409, "%s: the entries chosen come to nothing to bill. Choose the work itself, "
                                     "not only a hold on it." % label)
        if this > money(done - prior) + 0.0001:
            raise HTTPException(409, "%s: those entries come to %s but only %s is left to bill - some of it is held "
                                     "back or already billed. Release the hold, or include it in the choice."
                                % (label, this, money(done - prior)))
        out.append((it, done, prior, this))
    return out


def draw_sub_bill_lines(db, bill, order, entry_ids=None):
    db.query(models.DBSubBillLine).filter(
        models.DBSubBillLine.sub_bill_id == bill.id).delete()
    if entry_ids is not None or (bill.entry_mode or "") == "chosen":
        # A bill of chosen entries keeps exactly those, however long it waits - nothing measured since joins it.
        if entry_ids is not None:
            entries = chosen_entries_for_bill(db, order, entry_ids)
        else:
            entries = db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.sub_bill_id == bill.id).all()
        claims = chosen_claims(db, order, entries, exclude_bill_id=bill.id)
        bill.entry_mode = "chosen"
        ids = [e.id for e in entries]
        db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.id.in_(ids or [0])).update(
            {"sub_bill_id": bill.id}, synchronize_session=False)
    else:
        claims = sub_claimable_lines(db, order, exclude_bill_id=bill.id)
    for i, (it, done, prior, this) in enumerate(claims):
        rate = unit_rate(it.unit_rate)
        db.add(models.DBSubBillLine(
            sub_bill_id=bill.id, item_id=it.id, activity_no=it.activity_no or "",
            description=it.item_description or "", uom=it.uom or "",
            ordered_qty=money(it.quantity), measured_to_date=done,
            previously_billed_qty=prior, this_bill_qty=this, rate=rate,
            amount=money(this * rate), display_order=i))
    if (bill.entry_mode or "") != "chosen":
        # Pin the measurements this bill claims.
        db.query(models.DBSubMeasurement).filter(
            models.DBSubMeasurement.order_id == order.id,
            models.DBSubMeasurement.sub_bill_id.is_(None)).update(
                {"sub_bill_id": bill.id}, synchronize_session=False)
    db.flush()


def sub_advance_recovery(db, order, bill, asked=None):
    """How much of the mobilisation advance this bill takes back.

    The instalment is the agreed share of the advance - unless the person
    raising the bill says otherwise - but never more than is still owed, and
    never more than the bill can bear after retention. A first bill for a
    small month's work does not come out negative; the shortfall waits for
    the next one.
    """
    # What was actually handed over, not what the order allows. Recovering
    # the agreed figure took an advance back out of a gang's bill that had
    # never been paid to them.
    advance = min(money(order.mobilization_advance_amount or 0),
                  advance_paid(db, order.client_id, order.id))
    if not advance:
        return 0.0
    recovered = money(sum((b.advance_recovery or 0) for b in db.query(models.DBSubBill).filter(
        models.DBSubBill.order_id == order.id, models.DBSubBill.id != bill.id,
        models.DBSubBill.status != "CANCELLED").all()))
    balance = max(0.0, money(advance - recovered))
    instalment = (money(asked) if asked is not None
                  else money(advance * (order.advance_recovery_percent or 0) / 100.0))
    # What the bill can bear: its gross less retention, TDS, cess and the
    # other deductions, so the net is never below its GST. Whatever
    # this bill was already taking back is counted as room, since it is the
    # figure being decided.
    bearable = max(0.0, money(sub_bill_room(bill) + (bill.advance_recovery or 0) - 0.5))
    return money(max(0.0, min(instalment, balance, bearable)))


def sub_bill_chain_rows(db, bill_id):
    return chain_rows(db, "sub_bill", bill_id)


def sub_bill_start_chain(db, client_id, bill, submitter_id):
    forget_chain(db, "sub_bill", bill.id)
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "sub_bill",
        models.DBApprovalChain.entity_id == bill.id).delete(synchronize_session=False)
    if submitter_id and not raised_by_owner(db, client_id, submitter_id):
        rungs = hierarchy_chain(db, client_id, submitter_id, "subcontracts.approve", bill.job_id,
                                owner_signs=sub_bill_owner_signs(db, client_id))
    else:
        rungs = []
    rungs = rungs or [chain_rung(None, db, client_id)]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i, rung in enumerate(rungs, 1):
        db.add(models.DBApprovalChain(
            client_id=client_id, entity_type="sub_bill", entity_id=bill.id,
            employee_id=submitter_id, approver_id=rung["employee_id"], level=rung["level"],
            step=i, status="pending", created_at=now))
    db.flush()
    return rungs


def ensure_sub_bill_chain(db, bill):
    """A bill sent before routes existed gets one the first time it is looked for."""
    if (bill.status or "") == "SUBMITTED" and not sub_bill_chain_rows(db, bill.id):
        sub_bill_start_chain(db, bill.client_id, bill, bill.submitted_by)


def sub_bill_current_step(db, bill, rows=None):
    """The step the bill waits at. An approver who has left, or no longer
    holds the right, is passed over rather than left to block it."""
    for row in (rows if rows is not None else sub_bill_chain_rows(db, bill.id)):
        if row.status != "pending":
            continue
        if row.approver_id is None:
            return row
        emp = by_id(db, models.DBEmployee, row.approver_id)
        if emp and (emp.status or "active") not in GONE_STATUSES and employee_can(emp, "subcontracts.approve"):
            return row
        row.status, row.notes = "skipped", "No longer able to certify bills"
        row.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return None


def sub_bill_step_name(db, row):
    if row is None:
        return ""
    return owner_label(db, row.client_id) if row.approver_id is None else _person(db, row.approver_id)


def sub_bill_route(db, bill):
    rows = sub_bill_chain_rows(db, bill.id)
    current = sub_bill_current_step(db, bill, rows) if (bill.status or "") == "SUBMITTED" else None
    return [{"step": r.step, "name": sub_bill_step_name(db, r), "owner": r.approver_id is None,
             "approver_id": r.approver_id,
             "status": "waiting" if current is not None and r.id == current.id else r.status,
             "notes": r.notes or "", "decided_at": r.decided_at or ""} for r in rows]


def sub_bill_signed(db, bill):
    """Who signed the certificate, as its signature row reads: the steps
    signed before the last are Certified By, the last is Approved By."""
    rows = [r for r in sub_bill_chain_rows(db, bill.id) if r.status == "approved"]
    if (bill.status or "") not in ("CERTIFIED", "PAID"):
        return {"certified": [sub_bill_step_name(db, r) for r in rows], "approved": ""}
    if not rows:
        return {"certified": [], "approved": bill.approved_by_name or bill.certified_by_name or ""}
    return {"certified": [sub_bill_step_name(db, r) for r in rows[:-1]],
            "approved": bill.approved_by_name or sub_bill_step_name(db, rows[-1])}


def sub_bill_decide(db, client, bill, actor_id, actor_name, approve, comments=""):
    """One signature on a bill climbing its route. Returns True when that
    signature certified it."""
    ensure_sub_bill_chain(db, bill)
    step = sub_bill_current_step(db, bill)
    owner = actor_id is None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not owner and approve and bill.submitted_by and bill.submitted_by == actor_id:
        raise HTTPException(403, "You prepared this bill, so somebody else has to certify it. It is waiting with %s."
                                 % (sub_bill_step_name(db, step) or "the Master"))
    if not owner and (step is None or step.approver_id != actor_id):
        later = any(r.approver_id == actor_id and r.status == "pending" for r in sub_bill_chain_rows(db, bill.id))
        raise HTTPException(403, "%s is waiting with %s.%s" % (
            bill.number, sub_bill_step_name(db, step) or "the Master",
            " It comes to you after that." if later else " It is not on your list to certify."))
    if not approve:
        if step is not None:
            step.status, step.notes, step.decided_at = "rejected", (comments or "").strip(), now
        return False
    if owner:
        for row in sub_bill_chain_rows(db, bill.id):
            if row.status == "pending":
                if row.approver_id is None:
                    row.status, row.notes, row.decided_at = "approved", (comments or "").strip(), now
                else:
                    row.status, row.notes, row.decided_at = "skipped", "Signed over by the Master", now
        if not any(r.approver_id is None and r.status == "approved" for r in sub_bill_chain_rows(db, bill.id)):
            # The owner signing a bill whose route never reached them: their
            # signature goes on it as the last word all the same.
            last = max([r.step for r in sub_bill_chain_rows(db, bill.id)] or [0])
            db.add(models.DBApprovalChain(
                client_id=client.id, entity_type="sub_bill", entity_id=bill.id,
                employee_id=bill.submitted_by, approver_id=None, level="owner", step=last + 1,
                status="approved", notes=(comments or "").strip(), decided_at=now, created_at=now))
    elif step is not None:
        step.status, step.notes, step.decided_at = "approved", (comments or "").strip(), now
    db.flush()
    nxt = None if owner else sub_bill_current_step(db, bill)
    if nxt is not None:
        log_audit(db, client.id, "sub_bill_recommended", "sub_bill", bill.id, bill.number or "",
                  "%s signed, passed to %s" % (actor_name, sub_bill_step_name(db, nxt)), None)
        if nxt.approver_id:
            notify_employee(db, client.id, nxt.approver_id, "Subcontractor bill awaiting your certification",
                            "%s - %s of work, net %s. Signed by %s and now with you." % (
                                bill.number, format_money_plain(bill.this_bill),
                                format_money_plain(bill.net_payable), actor_name),
                            link="/next/approvals")
        return False
    return True


def sub_order_or_404(db, client_id, order_id):
    o = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id == order_id,
        models.DBSubcontractOrder.client_id == client_id).first()
    if not o:
        raise HTTPException(404, "Subcontract order not found")
    return o


def material_recovery_dict(r):
    return {"id": r.id, "order_id": r.order_id, "issue_number": r.issue_number,
            "item_code": r.item_code, "item_name": r.item_name, "uom": r.uom,
            "quantity": money(r.quantity), "rate": unit_rate(r.rate), "amount": money(r.amount),
            "issued_on": r.issued_on, "sub_bill_id": r.sub_bill_id,
            "state": "recovered" if r.sub_bill_id else "waiting"}


def apply_material_recovery(db, client_id, order, bill):
    """Take what the gang owes for material off this bill, as far as it can
    bear - the rest waits for the next one, the way an advance does."""
    waiting = db.query(models.DBMaterialRecovery).filter(
        models.DBMaterialRecovery.client_id == client_id,
        models.DBMaterialRecovery.order_id == order.id,
        models.DBMaterialRecovery.sub_bill_id.is_(None)).order_by(
            models.DBMaterialRecovery.id).all()
    if not waiting:
        return 0.0
    room = money(sub_bill_room(bill) - 0.5)
    taken, notes = 0.0, []
    for r in waiting:
        if room <= 0.009:
            break
        if r.amount > room + 0.009:
            # Split: this bill takes what it can bear, the remainder waits.
            share = room / r.amount
            db.add(models.DBMaterialRecovery(
                client_id=r.client_id, order_id=r.order_id, job_id=r.job_id,
                stock_issue_id=r.stock_issue_id, issue_number=r.issue_number,
                item_code=r.item_code, item_name=r.item_name, uom=r.uom,
                quantity=money(r.quantity * (1 - share)), rate=r.rate,
                amount=money(r.amount - room), issued_on=r.issued_on))
            r.quantity = money(r.quantity * share)
            r.amount = money(room)
        r.sub_bill_id = bill.id
        taken = money(taken + r.amount)
        room = money(room - r.amount)
        notes.append("%s %s %g %s" % (r.issue_number, r.item_name or r.item_code,
                                     r.quantity, r.uom or ""))
    if taken:
        bill.other_deductions = money((bill.other_deductions or 0) + taken)
        line = "Material issued and recovered: " + "; ".join(notes[:6]) + \
               (" and %d more" % (len(notes) - 6) if len(notes) > 6 else "")
        bill.deduction_notes = ((bill.deduction_notes or "") + ("; " if bill.deduction_notes else "") + line)[:500]
    return taken


def release_material_recovery(db, client_id, bill_id):
    db.query(models.DBMaterialRecovery).filter(
        models.DBMaterialRecovery.client_id == client_id,
        models.DBMaterialRecovery.sub_bill_id == bill_id).update(
            {"sub_bill_id": None}, synchronize_session=False)


def _live_releases(db, client_id, side=None):
    q = db.query(models.DBRetentionRelease).filter(
        models.DBRetentionRelease.client_id == client_id,
        models.DBRetentionRelease.status != "CANCELLED")
    if side:
        q = q.filter(models.DBRetentionRelease.side == side)
    return q.all()


def released_retention(db, client_id, side):
    """{order id: retention released on it} - the client's work orders, or
    the gangs' subcontract orders. Cancelled releases gave nothing back."""
    out = {}
    for r in _live_releases(db, client_id, side):
        key = r.work_order_id if side == "client" else r.sub_order_id
        out[key] = money(out.get(key, 0.0) + (r.amount or 0))
    return out


def released_by_job(db, client_id, side="client"):
    out = {}
    for r in _live_releases(db, client_id, side):
        out[r.job_id] = money(out.get(r.job_id, 0.0) + (r.amount or 0))
    return out


def release_or_404(db, client_id, release_id):
    r = db.query(models.DBRetentionRelease).filter(
        models.DBRetentionRelease.id == release_id,
        models.DBRetentionRelease.client_id == client_id).first()
    if not r:
        raise HTTPException(404, "Release not found")
    return r


def release_party(db, r):
    """(party type, name, id) - the client of the job, or the gang."""
    if r.side == "client":
        job = db.query(models.DBJob).filter(models.DBJob.id == r.job_id).first()
        return "client", (job.customer_name if job else ""), None
    con = db.query(models.DBContractor).filter(
        models.DBContractor.id == r.contractor_id).first() if r.contractor_id else None
    return "contractor", (con.company_name if con else ""), r.contractor_id


def _order_number(db, r):
    if r.side == "client":
        wo = db.query(models.DBWorkOrder).filter(models.DBWorkOrder.id == r.work_order_id).first()
        return wo.number if wo else ""
    o = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id == r.sub_order_id).first()
    return (o.wo_number or "") if o else ""


def release_dict(db, r, settled=None):
    got = (settled.get(("retention_release", r.id), 0.0) if settled is not None
           else settled_on(db, r.client_id, "retention_release", r.id))
    job = db.query(models.DBJob).filter(models.DBJob.id == r.job_id).first()
    party_type, party, _ = release_party(db, r)
    return {
        "id": r.id, "number": r.number or "", "side": r.side,
        "stage": r.stage or "", "release_on": r.release_on or "",
        "order_id": r.work_order_id if r.side == "client" else r.sub_order_id,
        "order_number": _order_number(db, r),
        "job_id": r.job_id, "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
        "party": party, "party_type": party_type,
        "amount": money(r.amount), "gst_percent": r.gst_percent or 0,
        "gst_amount": money(r.gst_amount), "cgst_amount": money(r.cgst_amount),
        "sgst_amount": money(r.sgst_amount), "igst_amount": money(r.igst_amount),
        "place_of_supply": r.place_of_supply or "",
        "net_amount": money(r.net_amount),
        "settled": money(got),
        "outstanding": money(max(0.0, (r.net_amount or 0) - got)) if r.status != "CANCELLED" else 0.0,
        "status": r.status or "CERTIFIED", "notes": r.notes or "",
        "cancel_reason": r.cancel_reason or "",
        "created_by_name": r.created_by_name or "", "paid_at": r.paid_at or "",
        "created_at": r.created_at or "",
    }


def retention_positions(db, client_id, today=None):
    """Every order with retention on it, both ways: what its certified bills
    held back, what has been released, and what the next release would be.

    Half at practical completion and the rest at the end of the defects
    period is how most contracts read, so that is what is suggested - the
    amount stays the user's to change, and any release up to the balance can
    be raised."""
    today = today or date.today()
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client_id).all()}
    out = []

    def position(side, order_id, order_number, job, party, bills, rate_of, released, extra):
        held = money(sum(b.retention_amount or 0 for b in bills))
        if held <= 0:
            return
        gone = money(released.get(order_id, 0.0))
        balance = money(max(0.0, held - gone))
        latest = max(bills, key=lambda b: (b.sequence or 0, b.id))
        if gone <= 0:
            stage, suggest = "Practical completion", money(held / 2.0)
        else:
            stage, suggest = "End of defects period", balance
        row = {
            "side": side, "order_id": order_id, "order_number": order_number or "",
            "job_id": job.id if job else None,
            "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
            "job_status": (job.status or "") if job else "",
            "finished": bool(job and (job.status or "").lower() == JOB_FINISHED),
            "completed_at": ((job.completed_at or "")[:10]) if job else "",
            "party": party or "",
            "bills": len(bills), "claimed": money(sum(b.this_bill or 0 for b in bills)),
            "held": held, "released": gone, "balance": balance,
            "gst_percent": rate_of(latest) or 0,
            "suggest": {"stage": stage, "amount": min(suggest, balance)} if balance > 0 else None,
            "dlp_ends": "", "dlp_over": False,
        }
        row.update(extra)
        out.append(row)

    # The client's side: retention on our RA bills, per work order.
    ra_by_wo = {}
    for b in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client_id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all():
        ra_by_wo.setdefault(b.work_order_id, []).append(b)
    wos = {w.id: w for w in db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client_id).all()}
    released = released_retention(db, client_id, "client")
    for wo_id, bills in ra_by_wo.items():
        wo = wos.get(wo_id)
        job = jobs.get(wo.job_id if wo else bills[0].job_id)
        position("client", wo_id, wo.number if wo else "", job,
                 job.customer_name if job else "", bills,
                 lambda b: b.tax_percent, released, {})

    # The gangs' side: retention we held on their bills, per subcontract order.
    sub_by_order = {}
    for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client_id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all():
        sub_by_order.setdefault(b.order_id, []).append(b)
    orders = {o.id: o for o in db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.client_id == client_id).all()}
    contractors = {c.id: c for c in db.query(models.DBContractor).filter(
        models.DBContractor.client_id == client_id).all()}
    released = released_retention(db, client_id, "contractor")
    for order_id, bills in sub_by_order.items():
        o = orders.get(order_id)
        job = jobs.get(o.job_id if o else bills[0].job_id)
        con = contractors.get(o.contractor_id if o else bills[0].contractor_id)
        # The defects period runs from the order's completion; the second
        # half is theirs once it has run out.
        ends = months_after(o.completion_date, o.defect_liability_months) \
            if o and o.completion_date and (o.defect_liability_months or 0) > 0 else ""
        position("contractor", order_id, (o.wo_number if o else ""), job,
                 con.company_name if con else "", bills, lambda b: b.gst_percent, released,
                 {"contractor_id": con.id if con else None, "dlp_ends": ends,
                  "dlp_months": (o.defect_liability_months or 0) if o else 0,
                  "dlp_over": bool(ends and ends <= today.isoformat())})

    out.sort(key=lambda r: (r["side"] != "client", -r["balance"]))
    return out


def release_ledger_rows(db, client_id):
    """Releases in the party ledgers: a claim on the client, or a sum owed to
    a gang, the day it was raised."""
    rows = []
    for r in db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.client_id == client_id,
            models.DBRetentionRelease.status.in_(("CERTIFIED", "PAID"))).all():
        party_type, party, _ = release_party(db, r)
        rows.append({"party_type": party_type, "party": party, "date": r.release_on or (r.created_at or "")[:10],
                     "kind": "Retention released" if r.side == "client" else "Their retention released",
                     "number": r.number, "doc_type": "retention_release", "doc_id": r.id,
                     "billed": money(r.net_amount), "moved": 0.0, "job_id": r.job_id})
    return rows


def release_gst_rows(db, client_id, side, date_from="", date_to=""):
    """Releases as supplies for the GST registers - ours outward, the gangs'
    inward. Taxable is the retention released; the bills taxed the rest."""
    rows = []
    for r in db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.client_id == client_id,
            models.DBRetentionRelease.side == side,
            models.DBRetentionRelease.status.in_(("CERTIFIED", "PAID"))).all():
        on = (r.release_on or r.created_at or "")[:10]
        if (date_from and on < date_from) or (date_to and on > date_to):
            continue
        party_type, party, party_id = release_party(db, r)
        job = db.query(models.DBJob).filter(models.DBJob.id == r.job_id).first()
        row = {"kind": "Retention release", "number": r.number or "", "date": on,
               "party": party, "project": job.name if job else "",
               "place_of_supply": r.place_of_supply or "",
               "sac": WORKS_CONTRACT_SAC, "rate": r.gst_percent or 0,
               "taxable": money(r.amount), "cgst": money(r.cgst_amount), "sgst": money(r.sgst_amount),
               "igst": money(r.igst_amount), "tax": money(r.gst_amount),
               "total": money(r.net_amount)}
        if side == "contractor":
            con = db.query(models.DBContractor).filter(models.DBContractor.id == party_id).first() if party_id else None
            row["party_gstin"] = (con.gst_number or "") if con else ""
        rows.append(row)
    return rows


def release_attention(db, client_id, today):
    """A gang's defects period that has run out with their retention still
    held: they will be asking for it, and should be paid it on time."""
    over = [p for p in retention_positions(db, client_id, today)
            if p["side"] == "contractor" and p["dlp_over"] and p["balance"] > 0]
    if not over:
        return []
    return [{"kind": "retention_gangs", "severity": "action",
             "value": money(sum(p["balance"] for p in over)), "count": len(over),
             "view": "money-view", "title": "Contractors' retention due back",
             "detail": "%s held on %d order%s whose defects period has run out."
                       % (inr(sum(p["balance"] for p in over)), len(over), "" if len(over) == 1 else "s")}]


def portal_party(db, client_id, party_type, party_id):
    """(the contractor or supplier row, its name) - or (None, "")."""
    if party_type == "contractor":
        p = db.query(models.DBContractor).filter(models.DBContractor.id == party_id,
                                                 models.DBContractor.client_id == client_id).first()
        return p, ((p.company_name or "") if p else "")
    if party_type == "supplier":
        p = db.query(models.DBSupplier).filter(models.DBSupplier.id == party_id,
                                               models.DBSupplier.client_id == client_id).first()
        return p, ((p.name or "") if p else "")
    return None, ""


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.notifications import notify_employee
from app.documents.letterhead import our_party
from app.services.approvals import (
    _person,
    chain_rung,
    hierarchy_chain,
    owner_label,
    raised_by_owner,
    sub_bill_owner_signs,
)
from app.services.crm import advance_paid, settled_on
from app.services.subcontract_orders import contractor_state, item_ceiling, wo_involved_ids
