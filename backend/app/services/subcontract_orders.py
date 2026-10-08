"""The rules and workings behind the subcontract orders endpoints."""
import json
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, func as sqlfunc, or_
from sqlalchemy.exc import IntegrityError

from app.documents import form_pdf
from app import models

from app.constants.approvals import GONE_STATUSES
from app.constants.subcontract_orders import (
    DOCUMENT_UPLOAD_TYPES,
    OWNED_BY_AN_ORDER,
    REGISTRATION_DECLARATION,
    REGISTRATION_DOCUMENTS,
    REGISTRATION_FIELDS,
    UNREGISTERED_VENDOR_LIMIT,
    WO_ACTION_PAST,
    WO_BILLING_CYCLES,
    WO_COMMITTED_STATUSES,
    WO_DEFAULT_WORK_TYPES,
    WO_DEPARTMENTS,
    WO_EDITABLE,
    WO_TRACKED,
    WO_TRANSITIONS,
    _FK_CACHE,
)
from app.core.audit import log_audit
from app.core.auth import STAFF_VIEWER, get_client_user, require_items_access, require_owner
from app.core.config import logger
from app.core.currency import format_money_plain, inr, money, qty_text, unit_rate
from app.core.gst import our_state, split_gst, state_from_gstin, supply_state_for_job
from app.core.permissions import employee_can
from app.core.queries import by_id, chain_rows, forget_chain
from app.core.serials import next_sequence_number
from app.core.tenant_settings import tenant_setting


def work_order_to_dict(db, wo, detail=False, pre=None):
    if pre is not None:
        job = pre["jobs"].get(wo.job_id)
        cost = money(pre["cost"].get(wo.id, 0.0))
        line_count = int(pre["lines"].get(wo.id, 0))
    else:
        job = db.query(models.DBJob).filter(models.DBJob.id == wo.job_id).first()
        cost = money(sum(b.amount or 0 for b in db.query(models.DBBomLine).filter(
            models.DBBomLine.work_order_id == wo.id).all()))
        line_count = db.query(models.DBWorkOrderLine).filter(
            models.DBWorkOrderLine.work_order_id == wo.id).count()
    value = money(wo.total_value or 0)
    row = {
        "id": wo.id, "number": wo.number, "job_id": wo.job_id,
        "job_name": f"{job.number} {job.name}" if job else "",
        "customer_name": job.customer_name if job else "",
        "order_date": wo.order_date or "", "reference": wo.reference or "",
        "notes": wo.notes or "", "status": wo.status or "Draft",
        "total_value": value, "budget_cost": cost,
        "margin": money(value - cost),
        "margin_percent": round((value - cost) / value * 100, 1) if value else 0.0,
        "budgeted": cost > 0,
        "approval_status": wo.approval_status or "none",
        "current_step": wo.current_approval_step or 0,
        "rejection_reason": wo.rejection_reason or "",
        "line_count": line_count,
        "waiting_on": "",
    }
    if (wo.approval_status or "") == "pending":
        step = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "work_order", models.DBApprovalChain.entity_id == wo.id,
            models.DBApprovalChain.step == (wo.current_approval_step or 0)).first()
        total = db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "work_order",
            models.DBApprovalChain.entity_id == wo.id).count()
        if step is not None:
            row["waiting_on"] = (owner_label(db, wo.client_id) if step.approver_id is None
                                 else _person(db, step.approver_id))
            row["waiting_step"] = "%d of %d" % (step.step, total) if total > 1 else ""
            row["waiting_owner"] = step.approver_id is None
    if detail:
        row["lines"] = [{"id": l.id, "fg_code": l.fg_code, "item_name": l.item_name,
                         "description": l.description, "qty": l.qty, "uom": l.uom,
                         "rate": l.rate, "amount": l.amount}
                        for l in db.query(models.DBWorkOrderLine).filter(
                            models.DBWorkOrderLine.work_order_id == wo.id).all()]
        row["bom"] = [{"fg_code": b.fg_code, "rm_code": b.rm_code, "rm_name": b.rm_name,
                       "qty": b.qty, "uom": b.uom, "rate": b.rate, "amount": b.amount}
                      for b in db.query(models.DBBomLine).filter(
                          models.DBBomLine.work_order_id == wo.id).all()]
        row["approval_history"] = get_approval_chain_history("work_order", wo.id, db)
    return row


def work_order_or_404(db, client_id, wo_id):
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == wo_id,
        models.DBWorkOrder.client_id == client_id).first()
    if not wo:
        raise HTTPException(404, "Work order not found")
    return wo


def erp_wo_delete_report(db, client, wo):
    bills = db.query(models.DBRABill).filter(models.DBRABill.work_order_id == wo.id).all()
    blockers = []
    for b in bills:
        got = settled_on(db, client.id, "ra_bill", b.id)
        if got > 0:
            blockers.append("%s has %s received against it - those receipts are deleted too." % (b.number, inr(got)))
        if active_irn(db, client.id, "ra_bill", b.id):
            blockers.append("%s is registered on the e-invoice portal - cancel the IRN there as well, the portal keeps its own copy." % b.number)
    if db.query(models.DBRetentionRelease).filter(
            models.DBRetentionRelease.work_order_id == wo.id,
            models.DBRetentionRelease.status != "CANCELLED").count():
        blockers.append("Retention has been released against it - the release is deleted too.")
    variations = db.query(models.DBVariationOrder.id).filter(models.DBVariationOrder.work_order_id == wo.id).all()
    return {
        "bills": bills, "variation_ids": [v.id for v in variations], "blockers": [], "warnings": blockers,
        "counts": {
            "lines": db.query(models.DBWorkOrderLine).filter(models.DBWorkOrderLine.work_order_id == wo.id).count(),
            "measurements": db.query(models.DBMeasurement).filter(models.DBMeasurement.work_order_id == wo.id).count(),
            "bills": len(bills), "variations": len(variations),
        },
    }


def wo_department_choices(db, client_id):
    """The departments an order can be raised for: the ones the owner has created.

    A business that has not created any yet gets the six trades it would have had, so the
    picker is never empty. Any department already on an order stays in the list, so an
    old order can still be opened and saved after a department has been renamed or removed."""
    made = [d.name for d in db.query(models.DBDepartment).filter(
        models.DBDepartment.client_id == client_id).order_by(models.DBDepartment.name).all() if (d.name or "").strip()]
    names = made or list(WO_DEPARTMENTS)
    used = db.query(models.DBSubcontractOrder.department).filter(
        models.DBSubcontractOrder.client_id == client_id).distinct().all()
    for (dept,) in used:
        if dept and dept not in names:
            names.append(dept)
    return names


def recost_order(db, order):
    """Total the BOQ, then apply GST and TDS.

    GST is charged on top of the gross and TDS is withheld out of it, so they
    are not two halves of one number. Netting them against each other is the
    mistake this exists to make impossible.

    Retention and the mobilization advance are worked out here too, but they
    stay out of the order value. Retention is held back from each bill and
    handed over later; the advance is paid up front and taken back out of the
    bills. Both are timing, not price - subtracting them would state a
    contract value the contractor is not being offered, and it is the figure
    they price the next job from.
    """
    gross = money(sum(
        (i.total_amount or 0) for i in db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == order.id).all()))
    order.gross_amount = gross
    order.gst_amount = money(gross * (order.gst_rate or 0) / 100.0)
    order.tds_amount = money(gross * (order.tds_rate or 0) / 100.0)
    # Labour cess comes off the same way TDS does: withheld from the bill and
    # remitted on the contractor's behalf, never money they receive.
    order.labour_cess_amount = money(gross * (order.labour_cess_percent or 0) / 100.0)
    order.net_order_value = money(gross + order.gst_amount - order.tds_amount
                                  - order.labour_cess_amount)
    order.retention_amount = money(gross * (order.retention_percent or 0) / 100.0)
    order.mobilization_advance_amount = money(
        gross * (order.mobilization_advance_percent or 0) / 100.0)
    order.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return order


def wo_or_404(db, client_id, order_id):
    row = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id == order_id,
        models.DBSubcontractOrder.client_id == client_id).first()
    viewer = STAFF_VIEWER.get()
    if row and viewer:
        # What this person may see, worked out once - it takes several queries.
        seen = wo_involved_ids(db, client_id, viewer)
        if row.id not in seen and (row.status or "") == "PROVISIONAL" and not wo_chain_rows(db, row.id):
            # An order sent before routes existed has none until somebody looks; whoever is on it may then see it.
            ensure_wo_chain(db, db.query(models.DBClient).filter(models.DBClient.id == client_id).first(), row)
            seen = wo_involved_ids(db, client_id, viewer)
        if row.id not in seen:
            row = None
    if not row:
        raise HTTPException(404, "Work order not found")
    return row


def wo_involved_ids(db, client_id, emp_id):
    """The orders a member of staff has a hand in: made, sent or acted on by them, or with them on its
    route to sign - and every version of such an order, so an amendment is not lost to the one who
    raised the original."""
    mine = {r[0] for r in db.query(models.DBSubcontractOrder.id).filter(
        models.DBSubcontractOrder.client_id == client_id,
        models.DBSubcontractOrder.submitted_by == emp_id).all()}
    mine |= {r[0] for r in db.query(models.DBApprovalChain.entity_id).filter(
        models.DBApprovalChain.entity_type == "subcontract_order",
        models.DBApprovalChain.approver_id == emp_id).all()}
    mine |= {r[0] for r in db.query(models.DBSubcontractApproval.order_id).filter(
        models.DBSubcontractApproval.client_id == client_id,
        models.DBSubcontractApproval.actor_id == emp_id).all()}
    mine |= {r[0] for r in db.query(models.DBOrderAccess.order_id).filter(
        models.DBOrderAccess.client_id == client_id, models.DBOrderAccess.employee_id == emp_id).all()}
    # A bill to sign, or one they sent, brings its order with it.
    on_bills = {r[0] for r in db.query(models.DBApprovalChain.entity_id).filter(
        models.DBApprovalChain.entity_type == "sub_bill", models.DBApprovalChain.approver_id == emp_id).all()}
    mine |= {r[0] for r in db.query(models.DBSubBill.order_id).filter(
        models.DBSubBill.client_id == client_id,
        or_(models.DBSubBill.submitted_by == emp_id, models.DBSubBill.id.in_(list(on_bills) or [0]))).all() if r[0]}
    if not mine:
        return set()
    seen = set(mine)
    while True:
        more = {r[0] for r in db.query(models.DBSubcontractOrder.id).filter(
            models.DBSubcontractOrder.client_id == client_id,
            or_(models.DBSubcontractOrder.supersedes_id.in_(seen),
                models.DBSubcontractOrder.id.in_(
                    [r[0] for r in db.query(models.DBSubcontractOrder.supersedes_id).filter(
                        models.DBSubcontractOrder.id.in_(seen)).all() if r[0]]))).all()} - seen
        if not more:
            return seen
        seen |= more


def wo_visible_to(db, order, emp_id):
    """Whether a member of staff may see this order.

    Only the ones they have a hand in: they made it, sent it, or have it to sign (now or already).
    Nobody sees the business's whole book but the owner.
    """
    if not emp_id:
        return True
    return order.id in wo_involved_ids(db, order.client_id, emp_id)


def record_wo_action(db, client, order, actor_id, actor_name, action, was, comments=""):
    db.add(models.DBSubcontractApproval(
        order_id=order.id, client_id=client.id, actor_id=actor_id,
        actor_name=actor_name, action=action, from_status=was,
        to_status=order.status, comments=(comments or "").strip()))


def wo_item_dict(i):
    return {"id": i.id, "activity_no": i.activity_no or "", "item_code": i.item_code or "",
            "item_description": i.item_description or "",
            "technical_spec": i.technical_spec or "", "uom": i.uom or "",
            "quantity": money(i.quantity), "unit_rate": unit_rate(i.unit_rate),
            "total_amount": money(i.total_amount), "budget_id": i.budget_id,
            "cost_centre": i.cost_centre or "",
            "display_order": i.display_order or 0,
            "is_header": bool(i.is_header),
            "tolerance_percent": i.tolerance_percent or 0,
            "boq_key": i.boq_key or "",
            "max_quantity": item_ceiling(i)}


def item_ceiling(item):
    """The most that may be measured against a line: the ordered quantity
    plus its tolerance. Past this the order is amended, not the book."""
    return money((item.quantity or 0) * (1.0 + (item.tolerance_percent or 0) / 100.0))


def contractor_state(db, contractor_id):
    """The state the gang is registered in, read off their GSTIN. It is their
    supply, so it is their state against the site's that decides the split."""
    con = db.query(models.DBContractor).filter(
        models.DBContractor.id == contractor_id).first() if contractor_id else None
    return state_from_gstin(con.gst_number) if con else ""


def wo_billing_schedule(db, order):
    """The order's money as the schedule of heads a bill will be built on.

    One row per head, in the order they are applied, so what the contractor
    is shown on the order is the same table that appears on every RA bill
    against it. The GST split is decided here from the contractor's state and
    the site's, and shown as the two halves or the one whole it will be.
    """
    gross = money(order.gross_amount)
    supply = supply_state_for_job(db, order.job_id)
    origin = contractor_state(db, order.contractor_id) or our_state(db, order.client_id)
    gst = split_gst(gross, order.gst_rate or 0, origin, supply)
    rows = [{"head": "Basic value of work", "rate": None, "amount": gross, "kind": "base"}]
    if gst["intra_state"]:
        half = money((order.gst_rate or 0) / 2.0)
        rows.append({"head": "CGST", "rate": half, "amount": gst["cgst"], "kind": "add"})
        rows.append({"head": "SGST", "rate": half, "amount": gst["sgst"], "kind": "add"})
    else:
        rows.append({"head": "IGST", "rate": order.gst_rate or 0, "amount": gst["igst"],
                     "kind": "add"})
    rows.append({"head": "Gross", "rate": None,
                 "amount": money(gross + gst["total"]), "kind": "total"})
    if order.mobilization_advance_percent:
        rows.append({"head": "Mobilization advance", "rate": order.mobilization_advance_percent,
                     "amount": money(order.mobilization_advance_amount), "kind": "info",
                     "note": "paid up front, recovered %s%% of the advance (%s) on each bill"
                             % (order.advance_recovery_percent or 0,
                                inr((order.mobilization_advance_amount or 0)
                                    * (order.advance_recovery_percent or 0) / 100.0))})
    if order.retention_percent:
        rows.append({"head": "Retention", "rate": order.retention_percent,
                     "amount": money(order.retention_amount), "kind": "hold",
                     "note": "withheld from each bill, released after the defect period"})
    rows.append({"head": "TDS on contractors (194C)", "rate": order.tds_rate or 0,
                 "amount": money(order.tds_amount), "kind": "less"})
    if order.labour_cess_percent:
        rows.append({"head": "Labour welfare cess (BOCW)", "rate": order.labour_cess_percent,
                     "amount": money(order.labour_cess_amount), "kind": "less"})
    rows.append({"head": "Net order value payable", "rate": None,
                 "amount": money(order.net_order_value), "kind": "net"})
    return {"rows": rows, "intra_state": gst["intra_state"],
            "place_of_supply": supply, "contractor_state": origin}


def wo_pending_with(db, client_id, raised_by=None):
    """Who an order awaiting approval is waiting on - named, so the person
    who raised it knows whose desk to walk to. Not the person who raised it:
    they may not approve their own order."""
    names = []
    for emp in holders_of(db, client_id, "subcontracts.approve", exclude={raised_by}):
        names.append(("%s %s" % (emp.first_name or "", emp.last_name or "")).strip()
                     or emp.email or "")
    if not names:
        # The account holder can always approve. Leaving them off told an
        # owner working alone that nobody could sign their own order - with
        # the Approve button right there on the same screen.
        owner = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
        names.append("%s (Master)" % ((owner.contact_name or owner.email or "the account holder")
                                     if owner else "the account holder"))
    return names


def wo_item_count(db, order_id):
    """How many lines an order has: from the batch a list has already read, else one count."""
    counts = db.info.get("wo_item_counts")
    if counts is not None and order_id in counts:
        return counts[order_id]
    return db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order_id).count()


def prime_wo_item_counts(db, order_ids):
    """Count the lines of many orders in one query, for a list that would otherwise count them one by one."""
    ids = list(order_ids)
    if not ids:
        return
    got = dict(db.query(models.DBSubcontractItem.order_id, func.count(models.DBSubcontractItem.id)).filter(
        models.DBSubcontractItem.order_id.in_(ids)).group_by(models.DBSubcontractItem.order_id).all())
    db.info["wo_item_counts"] = {i: got.get(i, 0) for i in ids}


def wo_dict(db, order, detail=False):
    bu = by_id(db, models.DBBusinessUnit, order.business_unit_id)
    con = by_id(db, models.DBContractor, order.contractor_id)
    job = by_id(db, models.DBJob, order.job_id)
    row = {
        "id": order.id, "wo_number": order.wo_number or "", "status": order.status,
        "submitted_by": order.submitted_by,
        "amendment_no": order.amendment_no or 0, "supersedes_id": order.supersedes_id,
        "business_unit_id": order.business_unit_id, "business_unit": bu.name if bu else "",
        "contractor_id": order.contractor_id, "contractor": con.company_name if con else "",
        "vendor_code": (con.vendor_code or "") if con else "",
        "job_id": order.job_id,
        "project": ("%s %s" % (job.number, job.name)).strip() if job else "",
        "work_type": order.work_type or "", "department": order.department or "",
        "subject": order.subject or "", "scope_of_work": order.scope_of_work or "",
        "commencement_date": order.commencement_date or "",
        "completion_date": order.completion_date or "",
        "duration_months": order.duration_months or 0,
        "defect_liability_months": order.defect_liability_months or 0,
        "bank_guarantee_applicable": bool(order.bank_guarantee_applicable),
        "bank_guarantee_amount": money(order.bank_guarantee_amount),
        "bank_guarantee_validity": order.bank_guarantee_validity or "",
        "gross_amount": money(order.gross_amount), "gst_rate": order.gst_rate or 0,
        "gst_amount": money(order.gst_amount), "tds_rate": order.tds_rate or 0,
        "tds_amount": money(order.tds_amount),
        "net_order_value": money(order.net_order_value),
        "retention_percent": order.retention_percent or 0,
        "retention_amount": money(order.retention_amount),
        "mobilization_advance_percent": order.mobilization_advance_percent or 0,
        "mobilization_advance_amount": money(order.mobilization_advance_amount),
        "advance_recovery_percent": order.advance_recovery_percent or 0,
        "labour_cess_percent": order.labour_cess_percent or 0,
        "labour_cess_amount": money(order.labour_cess_amount),
        "billing_cycle": order.billing_cycle or "",
        "payment_days": order.payment_days or 0,
        "copied_from_id": order.copied_from_id,
        "rejection_reason": order.rejection_reason or "",
        "approved_at": order.approved_at or "", "executed_at": order.executed_at or "",
        "created_at": order.created_at or "",
        "editable": order.status in WO_EDITABLE,
        "actions": sorted(WO_TRANSITIONS.get(order.status, {}).keys()),
        "provisional": order.status == "PROVISIONAL",
        "item_count": wo_item_count(db, order.id),
    }
    if detail:
        row["items"] = [wo_item_dict(i) for i in db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == order.id).order_by(
                models.DBSubcontractItem.display_order,
                models.DBSubcontractItem.id).all()]
        row["terms"] = [{"id": t.id, "clause_category": t.clause_category or "",
                         "clause_text": t.clause_text or "",
                         "display_order": t.display_order or 0}
                        for t in db.query(models.DBSubcontractTerm).filter(
                            models.DBSubcontractTerm.order_id == order.id).order_by(
                                models.DBSubcontractTerm.display_order,
                                models.DBSubcontractTerm.id).all()]
        row["history"] = [{"action": h.action, "actor": h.actor_name or "",
                           "from_status": h.from_status, "to_status": h.to_status,
                           "comments": h.comments or "", "at": h.created_at or ""}
                          for h in db.query(models.DBSubcontractApproval).filter(
                              models.DBSubcontractApproval.order_id == order.id).order_by(
                                  models.DBSubcontractApproval.id).all()]
        # What this order does to the project's allocations. Reported on the
        # order rather than fetched separately, so the figure an approver is
        # looking at is the one the approval will actually be checked against.
        row["billing_schedule"] = wo_billing_schedule(db, order)
        row["advance_paid"] = advance_paid(db, order.client_id, order.id)
        owner_client = db.query(models.DBClient).filter(models.DBClient.id == order.client_id).first()
        row["pending_with"] = wo_waiting_names(db, owner_client, order)
        row["approval_route"] = wo_route(db, order)
        row["revision_blockers"] = wo_revision_blockers(db, order)
        if order.copied_from_id:
            src = db.query(models.DBSubcontractOrder.wo_number).filter(
                models.DBSubcontractOrder.id == order.copied_from_id).first()
            row["copied_from"] = src[0] if src else ""
        row["budgets"] = (wo_budget_rows(db, order.client_id, order.job_id, order)
                          if order.job_id else [])
        row["budget_warnings"] = [
            "%s is allocated %s; this order takes it to %s."
            % (b["name"] or b["code"] or "A cost centre",
               format_money_plain(b["allocated"]),
               format_money_plain(b["committed"] + b["this_order"]))
            for b in row["budgets"] if b["over"] and b["this_order"] > 0]
        row["business_unit_detail"] = {
            "name": bu.name if bu else "", "gstin": bu.gstin if bu else "",
            "pan": bu.pan if bu else "", "address": bu.address if bu else "",
            "logo_url": (bu.logo_url if bu else "") or ""}
        row["contractor_detail"] = {
            "company_name": con.company_name if con else "",
            "vendor_code": con.vendor_code if con else "",
            "gst_number": con.gst_number if con else "",
            "pan": con.pan if con else "", "address": con.address if con else "",
            "contact_person": con.contact_person if con else "",
            "phone_number": con.phone_number if con else ""}
    return row


def ensure_company_unit(db, client):
    """The company itself, as the business unit its orders are issued by.

    One company issuing its own orders had to invent a "business unit" before
    the first subcontract order could be raised: the picker opened empty and
    nothing said what belonged in it. The answer is always the company, so
    it is on file from the start - named, with the GSTIN, PAN and address the
    company already gave - and any of those given later fill in what is
    blank. A group with several trading names still adds the others."""
    name = (client.company_name or "").strip()
    if not name:
        return
    gstin = (client.gstin or "").strip().upper()
    fill = {"gstin": gstin, "pan": gstin[2:12] if len(gstin) == 15 else "",
            "address": company_address(db, client)}
    rows = db.query(models.DBBusinessUnit).filter(
        models.DBBusinessUnit.client_id == client.id).all()
    if not rows:
        db.add(models.DBBusinessUnit(client_id=client.id, name=name, **fill))
        db.commit()
        return
    own = next((b for b in rows if norm_name(b.name) == norm_name(name)), None)
    if own and any(v and not (getattr(own, k) or "").strip() for k, v in fill.items()):
        for k, v in fill.items():
            if v and not (getattr(own, k) or "").strip():
                setattr(own, k, v)
        db.commit()


def contractor_dict(c):
    docs = [d for d in (c.documents or "").split(",") if d]
    try:
        doc_files = json.loads(c.document_names or "{}")
    except Exception:
        doc_files = {}
    return {"id": c.id, "company_name": c.company_name or "",
            "document_files": doc_files,
            "vendor_code": c.vendor_code or "", "contact_person": c.contact_person or "",
            "email": c.email or "", "phone_number": c.phone_number or "",
            "pan": c.pan or "", "gst_number": c.gst_number or "",
            "bank_name": c.bank_name or "", "bank_account": c.bank_account or "",
            "bank_ifsc": c.bank_ifsc or "", "address": c.address or "",
            "registered_project": c.registered_project or "", "joining_date": c.joining_date or "",
            "pin_code": c.pin_code or "", "city": c.city or "", "state": c.state or "",
            "nature_of_work": c.nature_of_work or "", "entity_type": c.entity_type or "",
            "aadhaar": c.aadhaar or "", "bank_branch": c.bank_branch or "",
            "documents": docs, "declaration_signed": bool(c.declaration_signed),
            "registration_status": c.registration_status or "APPROVED",
            "registered_by_name": c.registered_by_name or "", "approved_by_name": c.approved_by_name or "",
            "approved_at": c.approved_at or "", "rejection_reason": c.rejection_reason or "",
            "created_at": c.created_at or "", "is_active": c.is_active is not False}


def next_vendor_code(db, client_id):
    """The next number in the series the vendor codes already run in - IV0001,
    IV0002 as the registration forms are numbered - or the prefix set in
    Settings. A code can be referred to on a site instruction without anybody
    having to look the name up."""
    codes = [(c or "").strip().upper() for (c,) in db.query(models.DBContractor.vendor_code).filter(
        models.DBContractor.client_id == client_id).all() if c]
    prefix = (tenant_setting(db, client_id, "vendor_code_prefix", "") or "").strip().upper()
    if not prefix:
        counts = {}
        for code in codes:
            m = re.match(r"^([A-Z]+-?)0*(\d+)$", code)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        prefix = max(sorted(counts), key=lambda k: counts[k]) if counts else "IV"
    highest = 0
    for code in codes:
        m = re.match(r"^%s0*(\d+)$" % re.escape(prefix), code)
        if m:
            highest = max(highest, int(m.group(1)))
    return "%s%04d" % (prefix, highest + 1)


def contractor_form_fields(con, body, fill_blanks_only=False):
    """The registration form's own boxes from a request onto the record."""
    for key in REGISTRATION_FIELDS:
        v = getattr(body, key, None)
        if v is None:
            continue
        v = str(v).strip()
        if key == "aadhaar":
            v = re.sub(r"\s", "", v)
            if v and not re.match(r"^\d{12}$", v):
                raise HTTPException(400, "An Aadhaar number is twelve digits.")
        if key == "pin_code" and v and not re.match(r"^\d{6}$", v):
            raise HTTPException(400, "A PIN code is six digits.")
        setattr(con, key, v[:300])
    if body.documents is not None:
        known = [k for k, _ in REGISTRATION_DOCUMENTS]
        con.documents = ",".join(k for k in known if k in set(body.documents or []))
    if body.document_files is not None:
        known = {k for k, _ in REGISTRATION_DOCUMENTS}
        try:
            cur = json.loads(con.document_files or "{}")
        except Exception:
            cur = {}
        for k, v in (body.document_files or {}).items():
            if k not in known:
                continue
            if not v or not v.get("data"):
                cur.pop(k, None)
                continue
            data = v["data"]
            if not re.match(r"^data:[\w./+-]+;base64,", data):
                raise HTTPException(400, "That does not look like an uploaded file.")
            if data[5:data.index(";")].lower() not in DOCUMENT_UPLOAD_TYPES:
                raise HTTPException(400, "Send the document as a PDF or a photo (JPG or PNG).")
            if len(data) > 7_000_000:
                raise HTTPException(400, "That file is too large - keep it under 5 MB.")
            cur[k] = {"name": (v.get("name") or "")[:200], "data": data}
        con.document_files = json.dumps(cur)
        con.document_names = json.dumps({k: v.get("name") or "" for k, v in cur.items()})
    if body.declaration_signed is not None:
        con.declaration_signed = bool(body.declaration_signed)


def may_administer(request, db, permission="people.manage"):
    """Whether this caller holds a right, asked rather than demanded.

    The same check as require_items_access, but answering the question instead
    of refusing the request - the work type screen has to show an engineer the
    list without showing them the buttons they cannot use.
    """
    try:
        require_items_access(request, db, permission)
        return True
    except HTTPException:
        return False


def seed_work_types(db, client_id):
    """The trades this business already works in, the first time it looks.

    Seeded rather than left empty because an empty required dropdown on the
    first screen of the first order is a dead end, and the eleven below are
    the ones every order in this trade is raised against.
    """
    if db.query(models.DBWorkType).filter(
            models.DBWorkType.client_id == client_id).count():
        return
    for code, name, department in WO_DEFAULT_WORK_TYPES:
        db.add(models.DBWorkType(client_id=client_id, code=code, name=name,
                                 department=department, status="active"))
    db.commit()


def work_type_dict(w):
    return {"id": w.id, "name": w.name or "", "code": w.code or "",
            "department": w.department or "", "status": w.status or "active",
            "requested_by_name": w.requested_by_name or "",
            "request_reason": w.request_reason or "",
            "decided_by_name": w.decided_by_name or "",
            "created_at": w.created_at or ""}


def budget_breaks_vendor_limit(db, client_id, order_id, allocated):
    """Stop a budget set from an order whose contractor has no GSTIN from going over what that contractor may be given."""
    if not order_id:
        return
    order = wo_or_404(db, client_id, order_id)
    con = by_id(db, models.DBContractor, order.contractor_id)
    if con is None or (con.gst_number or "").strip() or money(allocated or 0) <= UNREGISTERED_VENDOR_LIMIT:
        return
    raise HTTPException(409, "%s has no GST registration, so the budget set from their order cannot be more than %s - this one is %s. "
                             "Add their GSTIN to their registration form, or bring the budget down." % (
                                 con.company_name, inr(UNREGISTERED_VENDOR_LIMIT), inr(allocated)))


def wo_committed_by_budget(db, client_id, exclude_order_id=None):
    """Rupees already committed against each allocation, from the orders."""
    query = (db.query(models.DBSubcontractItem.budget_id,
                      sqlfunc.sum(models.DBSubcontractItem.total_amount))
             .join(models.DBSubcontractOrder,
                   models.DBSubcontractOrder.id == models.DBSubcontractItem.order_id)
             .filter(models.DBSubcontractOrder.client_id == client_id,
                     models.DBSubcontractOrder.status.in_(WO_COMMITTED_STATUSES),
                     models.DBSubcontractItem.budget_id.isnot(None)))
    if exclude_order_id:
        query = query.filter(models.DBSubcontractOrder.id != exclude_order_id)
    return {budget_id: money(total or 0)
            for budget_id, total in query.group_by(
                models.DBSubcontractItem.budget_id).all()}


def wo_budget_rows(db, client_id, job_id, order=None):
    """Every allocation on a project, with what is left of it.

    When an order is passed, its own lines are reported separately from what
    everything else has committed - so the wizard can say "this order takes
    the last 40,000 of it" while it is still being priced, rather than only
    once it is too late to change.
    """
    budgets = db.query(models.DBProjectBudget).filter(
        models.DBProjectBudget.client_id == client_id,
        models.DBProjectBudget.job_id == job_id,
        models.DBProjectBudget.is_active == True).order_by(  # noqa: E712
            models.DBProjectBudget.code, models.DBProjectBudget.id).all()

    committed = wo_committed_by_budget(db, client_id,
                                       exclude_order_id=order.id if order else None)
    mine = {}
    if order is not None:
        for budget_id, total in db.query(
                models.DBSubcontractItem.budget_id,
                sqlfunc.sum(models.DBSubcontractItem.total_amount)).filter(
                    models.DBSubcontractItem.order_id == order.id,
                    models.DBSubcontractItem.budget_id.isnot(None)).group_by(
                        models.DBSubcontractItem.budget_id).all():
            mine[budget_id] = money(total or 0)

    rows = []
    for b in budgets:
        allocated = money(b.allocated_amount)
        elsewhere = committed.get(b.id, 0.0)
        this_order = mine.get(b.id, 0.0)
        rows.append({
            "id": b.id, "code": b.code or "", "name": b.name or "",
            "department": b.department or "", "notes": b.notes or "",
            "allocated": allocated,
            "committed": elsewhere,
            "this_order": this_order,
            "available": money(allocated - elsewhere - this_order),
            # An allocation of zero is one nobody has set yet, not one that is
            # fully spent, so it is never reported as over budget.
            "over": bool(allocated > 0 and (elsewhere + this_order) > allocated),
        })
    return rows


def wo_valid_budget_id(db, client_id, order, budget_id):
    """A line may only spend an allocation belonging to its own project.

    Silently dropped rather than refused: the cost centre picker empties when
    the project on the order changes, and a schedule of two hundred lines
    should not be rejected wholesale because one of them still points at the
    allocation of a project it no longer belongs to.
    """
    if not budget_id:
        return None
    row = db.query(models.DBProjectBudget).filter(
        models.DBProjectBudget.id == budget_id,
        models.DBProjectBudget.client_id == client_id,
        models.DBProjectBudget.job_id == order.job_id).first()
    return row.id if row else None


def wo_budget_breaches(db, client, order):
    """Which allocations this order would overrun, in words an approver can act on."""
    if not order.job_id:
        return []
    breaches = []
    for row in wo_budget_rows(db, client.id, order.job_id, order):
        if row["over"] and row["this_order"] > 0:
            breaches.append(
                "%s is allocated %s and this order would take it to %s"
                % (row["name"] or row["code"] or "a cost centre",
                   format_money_plain(row["allocated"]),
                   format_money_plain(row["committed"] + row["this_order"])))
    return breaches


def wo_copy_lines(db, source, target):
    """Every schedule line and clause of one order onto another, as they are."""
    for i in db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == source.id).order_by(
                models.DBSubcontractItem.display_order, models.DBSubcontractItem.id).all():
        db.add(models.DBSubcontractItem(
            order_id=target.id, activity_no=i.activity_no, item_code=i.item_code,
            item_description=i.item_description, technical_spec=i.technical_spec,
            uom=i.uom, quantity=i.quantity,
            unit_rate=i.unit_rate, total_amount=i.total_amount,
            budget_id=i.budget_id, cost_centre=i.cost_centre,
            display_order=i.display_order, is_header=bool(i.is_header),
            tolerance_percent=i.tolerance_percent or 0, boq_key=i.boq_key or ""))
    for t in db.query(models.DBSubcontractTerm).filter(
            models.DBSubcontractTerm.order_id == source.id).all():
        db.add(models.DBSubcontractTerm(
            order_id=target.id, clause_category=t.clause_category,
            clause_text=t.clause_text, display_order=t.display_order))


def wo_matches(row, q):
    """The register's search: number, contractor, project, subject, type."""
    needle = (q or "").strip().lower()
    if not needle:
        return True
    hay = " ".join([row["wo_number"], row["contractor"], row["project"], row["subject"],
                    row["work_type"], row["department"], row["status"]]).lower()
    return needle in hay


def wo_percent(value, what):
    try:
        pct = float(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, "The %s is a percentage." % what)
    if pct < 0 or pct > 100:
        raise HTTPException(400, "The %s is a percentage between 0 and 100." % what)
    return pct


def wo_billing_cycle(value):
    cycle = (value or "").strip()
    if cycle not in WO_BILLING_CYCLES:
        raise HTTPException(400, "The billing cycle is one of: " +
                            ", ".join(c for c in WO_BILLING_CYCLES if c) + ".")
    return cycle


def wo_snapshot(order):
    return {field: getattr(order, field) for field, _ in WO_TRACKED}


def wo_shown(value):
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, float):
        return "%g" % value
    return str(value) if value not in (None, "") else "(blank)"


def wo_changes(before, order):
    """What moved between two saves, in words. Recorded into the history so
    the question "who changed the completion date, and when" has an answer."""
    out = []
    for field, label in WO_TRACKED:
        was, now = before.get(field), getattr(order, field)
        blank = (None, "", 0, 0.0, False)
        if was == now or (was in blank and now in blank):
            continue
        out.append("%s: %s -> %s" % (label, wo_shown(was), wo_shown(now)))
    return out


def wo_ready_to_submit(db, order):
    """What is still missing before anybody can be asked to sign this.

    Checked on submission rather than on save, because a draft is allowed to
    be half finished - that is what a draft is for. It is the asking somebody
    to approve it that requires the document to be complete.
    """
    missing = []
    if not order.contractor_id:
        missing.append("the contractor it is issued to")
    if not order.business_unit_id:
        missing.append("the business unit issuing it")
    if not (order.subject or "").strip():
        missing.append("a subject")
    if not db.query(models.DBSubcontractItem).filter(
            models.DBSubcontractItem.order_id == order.id).count():
        missing.append("at least one schedule item")
    if money(order.gross_amount) <= 0:
        missing.append("a value above zero")
    if not (order.commencement_date or "").strip():
        missing.append("a commencement date")
    if not (order.completion_date or "").strip():
        missing.append("a completion date")
    missing += wo_budget_missing(db, order)
    return missing


def wo_budget_missing(db, order):
    """Every order spends a budget, and says which.

    The project has to have money allocated, and every priced line of the
    schedule has to be charged to one of its cost centres - otherwise the
    approver is signing a figure with nothing to hold it against, and the
    overrun check has nothing to check.
    """
    if not order.job_id:
        return ["the project it is for, so it can be held against that project's budget"]
    heads = {b.id: b for b in db.query(models.DBProjectBudget).filter(
        models.DBProjectBudget.client_id == order.client_id,
        models.DBProjectBudget.job_id == order.job_id,
        models.DBProjectBudget.is_active == True).all()}  # noqa: E712
    if not heads:
        return ["a budget on the project - press Set the budget on the schedule step and say how much is set aside"]
    lines = [i for i in db.query(models.DBSubcontractItem).filter(
        models.DBSubcontractItem.order_id == order.id).all()
        if not i.is_header and money(i.total_amount or 0) > 0]
    uncharged = [i for i in lines if not i.budget_id or i.budget_id not in heads]
    out = []
    if uncharged:
        out.append("a budget head on %d line%s of the schedule - charge them on the schedule step" % (
            len(uncharged), "" if len(uncharged) == 1 else "s"))
    unset = sorted({heads[i.budget_id].name or heads[i.budget_id].code or "a cost centre"
                    for i in lines if i.budget_id in heads and money(heads[i.budget_id].allocated_amount or 0) <= 0})
    if unset:
        out.append("an amount allocated to " + ", ".join(unset))
    return out


def wo_budget_summary(db, order):
    """The cost centres this order spends, as an approver reads them."""
    if not order.job_id:
        return []
    return ["%s: allocated %s, this order %s, left after it %s" % (
                r["name"] or r["code"] or "Cost centre", format_money_plain(r["allocated"]),
                format_money_plain(r["this_order"]), format_money_plain(r["available"]))
            for r in wo_budget_rows(db, order.client_id, order.job_id, order) if r["this_order"] > 0]


def wo_notify(db, client, order, action, actor_id, actor_name, comments=""):
    """Tell whoever the order is now waiting on.

    Sent on the moves that hand the document to somebody else and on no
    others: an order that sits in a queue nobody is told about is an order
    that sits in a queue. Best effort throughout - a notice that could not be
    written must never be the reason a submission or an approval fails.
    """
    try:
        if action == "SUBMIT":
            # The first person on its route, and nobody else yet.
            first = wo_current_step(db, order)
            for emp in [db.query(models.DBEmployee).filter(models.DBEmployee.id == first.approver_id).first()] \
                    if first is not None and first.approver_id else []:
                if not emp or emp.id == actor_id:
                    continue
                notify_employee(
                    db, client.id, emp.id, "Work order awaiting approval",
                    "%s to %s, %s, raised by %s." % (
                        order.wo_number,
                        wo_dict(db, order).get("contractor") or "a contractor",
                        format_money_plain(order.net_order_value), actor_name),
                    link="/next/approvals")
        elif action in ("APPROVE", "REJECT", "CANCEL") and order.submitted_by:
            if order.submitted_by == actor_id:
                return
            wording = {"APPROVE": "approved", "REJECT": "sent back",
                       "CANCEL": "cancelled"}[action]
            notify_employee(
                db, client.id, order.submitted_by,
                "Work order " + wording,
                "%s was %s by %s.%s" % (order.wo_number, wording, actor_name,
                                        " " + comments.strip() if comments else ""),
                link="/next/subcontractors/work-orders")
    except Exception:
        logger.exception("Could not queue work order notifications for %s",
                         order.wo_number)


def wo_item_key(item):
    return ((item.activity_no or "").strip().lower(),
            re.sub(r"[^a-z0-9]+", " ", (item.item_description or "").split("\n")[0].lower()).strip())


def wo_map_items(old_items, new_items):
    """Each line of an order to the same line on its revision: by number and
    description, then number alone, then description alone - and only where
    exactly one line answers, so nothing is carried to a guess."""
    new = [i for i in new_items if not i.is_header]
    out = {}
    for old in old_items:
        if old.is_header:
            continue
        num, desc = wo_item_key(old)
        tests = (lambda n: wo_item_key(n) == (num, desc),
                 lambda n: bool(num) and wo_item_key(n)[0] == num,
                 lambda n: bool(desc) and wo_item_key(n)[1] == desc)
        for test in tests:
            hits = [n for n in new if test(n)]
            if len(hits) == 1:
                out[old.id] = hits[0]
                break
    return out


def wo_revision_blockers(db, order):
    """What would stop this revision being approved right now, in the words approval would use.

    A revision takes over the work measured and billed on the order it replaces, and approval refuses
    where that cannot be done cleanly. Said on the revision itself, so nobody finds out only when the
    approver clicks Approve and is told no."""
    if not order.supersedes_id or (order.status or "") not in ("DRAFT", "PROVISIONAL"):
        return []
    old = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id == order.supersedes_id,
        models.DBSubcontractOrder.client_id == order.client_id).first()
    if not old:
        return []
    entries = db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id == old.id).all()
    bills = db.query(models.DBSubBill).filter(models.DBSubBill.order_id == old.id).all()
    advances = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == order.client_id, models.DBMoneyEntry.doc_type == "sub_advance",
        models.DBMoneyEntry.doc_id == old.id).all()
    if not entries and not bills and not advances:
        return []
    out = ["%s is still open on %s. Certify or cancel it before this revision can be approved." % (b.number, old.wo_number)
           for b in bills if (b.status or "") in ("DRAFT", "SUBMITTED")]
    if (old.contractor_id or None) != (order.contractor_id or None):
        out.append("%s already has work measured or billed for its sub contractor. A revision keeps the same sub "
                   "contractor - raise a new order for a different one." % old.wo_number)
    old_items = db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == old.id).all()
    new_items = db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == order.id).all()
    mapping = wo_map_items(old_items, new_items)
    live_ids = [b.id for b in bills if (b.status or "") != "CANCELLED"]
    lines = db.query(models.DBSubBillLine).filter(
        models.DBSubBillLine.sub_bill_id.in_([b.id for b in bills] or [0])).all()
    used = {e.item_id for e in entries} | {l.item_id for l in lines if l.sub_bill_id in live_ids and l.item_id}
    missing = [i for i in old_items if i.id in used and i.id not in mapping]
    if missing:
        out.append("Lines measured or billed on %s are not on this revision: %s. Keep them - the quantity can come "
                   "down to what is done, not below." % (old.wo_number, ", ".join(
                       (i.activity_no or (i.item_description or "")[:40]) for i in missing)))
    measured = sub_gross_measured(db, old.id)
    for o, n in [(i, mapping[i.id]) for i in old_items if i.id in mapping]:
        if money(measured.get(o.id, 0.0)) > item_ceiling(n) + 0.0001:
            out.append("%s is measured to %s but the revision orders %s." % (
                o.activity_no or "A line", qty_text(measured.get(o.id, 0.0)), qty_text(n.quantity)))
    return out


def wo_take_over_history(db, client, revision):
    """A revision, on approval, carries on from the order it replaces.

    The measurement book, the RA bills and their numbering, material
    recovered, retention released and the advance paid all move across line
    for line. Left behind, the revision started again at nothing: its first
    bill had nothing previously billed, and work already paid for could be
    measured and paid a second time. Returns the order being replaced."""
    old = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id == revision.supersedes_id,
        models.DBSubcontractOrder.client_id == client.id).first()
    if not old:
        return None
    entries = db.query(models.DBSubMeasurement).filter(
        models.DBSubMeasurement.order_id == old.id).all()
    bills = db.query(models.DBSubBill).filter(models.DBSubBill.order_id == old.id).all()
    advances = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.doc_type == "sub_advance",
        models.DBMoneyEntry.doc_id == old.id).all()
    if not entries and not bills and not advances:
        return old

    open_bill = next((b for b in bills if (b.status or "") in ("DRAFT", "SUBMITTED")), None)
    if open_bill:
        raise HTTPException(409, "%s is still open on %s. Certify or cancel it before approving the revision."
                                 % (open_bill.number, old.wo_number))
    if (old.contractor_id or None) != (revision.contractor_id or None):
        raise HTTPException(409, "%s already has work measured or billed for its sub contractor. A revision "
                                 "keeps the same sub contractor - raise a new order for a different one."
                                 % old.wo_number)

    old_items = db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == old.id).all()
    new_items = db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id == revision.id).all()
    mapping = wo_map_items(old_items, new_items)
    live_ids = [b.id for b in bills if (b.status or "") != "CANCELLED"]
    lines = db.query(models.DBSubBillLine).filter(
        models.DBSubBillLine.sub_bill_id.in_([b.id for b in bills] or [0])).all()
    used = {e.item_id for e in entries} | {l.item_id for l in lines if l.sub_bill_id in live_ids and l.item_id}
    missing = [i for i in old_items if i.id in used and i.id not in mapping]
    if missing:
        raise HTTPException(409, "These lines are measured or billed on %s but not on the revision: %s. Keep them "
                                 "on it - the quantity can come down to what is done, not below."
                                 % (old.wo_number, ", ".join((i.activity_no or (i.item_description or "")[:40])
                                                             for i in missing)))
    measured = sub_gross_measured(db, old.id)
    short = [(i, mapping[i.id]) for i in old_items
             if i.id in mapping and money(measured.get(i.id, 0.0)) > item_ceiling(mapping[i.id]) + 0.0001]
    if short:
        raise HTTPException(409, "The revision orders less than is already measured: %s."
                                 % "; ".join("%s %s measured, %s on the revision" % (
                                     o.activity_no or "item", qty_text(measured.get(o.id, 0.0)),
                                     qty_text(n.quantity)) for o, n in short))

    for e in entries:
        e.order_id = revision.id
        e.item_id = mapping[e.item_id].id
    for b in bills:
        b.order_id = revision.id
    for l in lines:
        if l.item_id in mapping:
            l.item_id = mapping[l.item_id].id
    for r in db.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.order_id == old.id).all():
        r.order_id = revision.id
    for r in db.query(models.DBRetentionRelease).filter(models.DBRetentionRelease.sub_order_id == old.id).all():
        r.sub_order_id = revision.id
    for m in advances:
        m.doc_id = revision.id
    db.flush()
    return old


def unregistered_vendor_breach(db, order):
    """The reason an order may not go ahead because its contractor has no GSTIN and the order is too big, or None."""
    con = by_id(db, models.DBContractor, order.contractor_id)
    if con is None or (con.gst_number or "").strip():
        return None
    value = money(order.gross_amount or 0)
    if value <= UNREGISTERED_VENDOR_LIMIT:
        return None
    return ("%s has no GST registration, so an order to them cannot be worth more than %s - this one is %s. "
            "Add their GSTIN to their registration form, or bring the order down." % (
                con.company_name, inr(UNREGISTERED_VENDOR_LIMIT), inr(value)))


def wo_apply(db, client, order, action, actor_id, actor_name, comments="",
             override=False, quiet=False):
    """One door for every state change, so the rules cannot disagree."""
    was = order.status
    predecessor = None
    allowed = WO_TRANSITIONS.get(was, {})
    if action not in allowed:
        raise HTTPException(
            409, "%s is %s, so it cannot be %s from there." %
                 (order.wo_number, was.lower(),
                  WO_ACTION_PAST.get(action, action.lower())))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if action == "SUBMIT":
        missing = wo_ready_to_submit(db, order)
        if missing:
            raise HTTPException(
                400, "This order still needs " + ", ".join(missing) + ".")
        too_big = unregistered_vendor_breach(db, order)
        if too_big:
            raise HTTPException(409, too_big)
        order.submitted_by = actor_id
    elif action == "REJECT":
        if not (comments or "").strip():
            raise HTTPException(
                400, "Say why it is going back, so it can be corrected.")
        order.rejection_reason = (comments or "").strip()
    elif action == "APPROVE":
        # The person who priced it is not the person who commits the business
        # to it - that is what the provisional state is for. The owner, who
        # answers to nobody, may approve an order they raised themselves.
        if actor_id and order.submitted_by == actor_id:
            raise HTTPException(
                403, "You raised this order, so somebody else has to approve it. "
                     "It is waiting with: " + ", ".join(
                         wo_pending_with(db, client.id, actor_id)) + ".")
        # An order is issued only to a sub contractor whose registration form
        # has been signed off - otherwise the gang is taken on by whoever
        # typed their name, PAN and bank account.
        too_big = unregistered_vendor_breach(db, order)
        if too_big:
            raise HTTPException(409, too_big)
        con = db.query(models.DBContractor).filter(models.DBContractor.id == order.contractor_id).first() \
            if order.contractor_id else None
        if con is not None and (con.registration_status or "APPROVED") != "APPROVED":
            raise HTTPException(
                409, "%s (%s) is not yet a registered sub contractor - the registration form is %s. "
                     "Approve it in Approvals first." % (
                         con.company_name, con.vendor_code or "no code",
                         "waiting for approval" if con.registration_status == "PENDING" else "sent back"))
        # The budget is checked here and nowhere earlier. A draft may be priced
        # at any figure - finding out it is too big is what pricing it is for -
        # but approving it is the moment the business is committed, so it is
        # the moment somebody has to knowingly overrun the allocation.
        breaches = wo_budget_breaches(db, client, order)
        if breaches and not override:
            raise HTTPException(
                409, "This order overruns the project allocation: "
                     + "; ".join(breaches) + ". Approve with an override, "
                     "saying why, to commit it anyway.")
        if breaches:
            if not (comments or "").strip():
                raise HTTPException(
                    400, "An overrun has to be explained. Say why the "
                         "allocation is being exceeded.")
            comments = "Budget override - " + comments.strip() + \
                       " (" + "; ".join(breaches) + ")"
        if order.supersedes_id:
            predecessor = wo_take_over_history(db, client, order)
        order.approved_by = actor_id
        order.approved_at = now
        order.rejection_reason = ""
    elif action == "EXECUTE":
        order.executed_at = now
    elif action == "CANCEL":
        # Work measured, billed or advanced against an order is a running
        # account with the gang; cancelling the order left it pointing at
        # nothing, with bills still certifiable against it.
        billed = [b.number for b in db.query(models.DBSubBill).filter(
            models.DBSubBill.order_id == order.id, models.DBSubBill.status != "CANCELLED").all()]
        if billed:
            raise HTTPException(409, "%s has RA bills against it (%s). Cancel any still open; work already "
                                     "certified is closed by amending the order down to it, not by cancelling."
                                     % (order.wo_number, ", ".join(billed)))
        if db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id == order.id).count():
            raise HTTPException(409, "%s has work measured against it. Remove those entries from the "
                                     "measurement book first, or amend the order down to what was done."
                                     % order.wo_number)
        if advance_paid(db, client.id, order.id) > 0:
            raise HTTPException(409, "An advance of %s has been paid on %s. Void it under Payments & Ledgers "
                                     "before cancelling." % (inr(advance_paid(db, client.id, order.id)), order.wo_number))

    order.status = allowed[action]
    order.updated_at = now
    if predecessor is not None and "AMEND" in WO_TRANSITIONS.get(predecessor.status or "", {}):
        before = predecessor.status
        predecessor.status = "AMENDED"
        predecessor.updated_at = now
        record_wo_action(db, client, predecessor, actor_id, actor_name, "AMEND", before,
                         "Superseded by " + (order.wo_number or ""))
    if action == "SUBMIT":
        wo_start_chain(db, client, order, actor_id)
    elif action in ("APPROVE", "REJECT", "CANCEL"):
        # Whoever had not yet signed does not need to now.
        for row in wo_chain_rows(db, order.id):
            if row.status == "pending":
                row.status = "skipped" if action == "APPROVE" else "cancelled"
                row.decided_at = now
    record_wo_action(db, client, order, actor_id, actor_name, action, was, comments)
    if not quiet:
        wo_notify(db, client, order, action, actor_id, actor_name, comments)
    return order


def _fk_map(db):
    """Every foreign key in the live database, by the table it points at. Reading the schema is slow, so it is
    kept until the set of tables changes - which is when it could have."""
    from sqlalchemy import inspect as sa_inspect
    bind = db.get_bind()
    insp = sa_inspect(bind)
    names = tuple(sorted(insp.get_table_names()))
    key = (str(bind.url), names)
    if key not in _FK_CACHE:
        _FK_CACHE.clear()
        graph = {}
        for table in names:
            nullable = {c["name"]: c.get("nullable", True) for c in insp.get_columns(table)}
            pk = insp.get_pk_constraint(table).get("constrained_columns") or []
            for fk in insp.get_foreign_keys(table):
                cols = fk.get("constrained_columns", [])
                if len(cols) == 1 and fk.get("referred_table"):
                    graph.setdefault(fk["referred_table"], []).append((table, cols[0], nullable.get(cols[0], True), pk))
        _FK_CACHE[key] = graph
    return _FK_CACHE[key]


def cascade_delete_referrers(db, parent, ids, _depth=0):
    """Everything in the live database that points at these rows, and what points at that, gone first.

    Read from the database's own constraints, so a link an older release left behind - or one a
    model never mentioned - cannot stop a delete. What belongs to the order is deleted; a record that
    merely mentions it (a stock issue, a diary day) is kept and unlinked."""
    from sqlalchemy import text, bindparam
    ids = list(ids)
    if not ids or _depth > 8:
        return
    for table, col, nullable, pk in _fk_map(db).get(parent, []):
        where = "%s IN :ids" % col
        bind = lambda sql: db.execute(text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": ids})
        if table == parent or (nullable and table not in OWNED_BY_AN_ORDER):
            bind("UPDATE %s SET %s = NULL WHERE %s" % (table, col, where))
            continue
        if len(pk) == 1:
            kids = [r[0] for r in bind("SELECT %s FROM %s WHERE %s" % (pk[0], table, where)).fetchall()]
            if kids:
                cascade_delete_referrers(db, table, kids, _depth + 1)
        bind("DELETE FROM %s WHERE %s" % (table, where))


def sweep_referrers(db, parents):
    """Whatever still points at rows about to be deleted. A column that may be empty is emptied; one that may
    not has its rows removed."""
    from sqlalchemy import text, bindparam
    graph = _fk_map(db)
    for parent, ids in parents.items():
        ids = list(ids or [])
        if not ids:
            continue
        for table, col, nullable, pk in graph.get(parent, []):
            if table == parent:
                continue
            sql = ("UPDATE %s SET %s = NULL WHERE %s IN :ids" if nullable else "DELETE FROM %s WHERE %s IN :ids") % (
                (table, col, col) if nullable else (table, col))
            db.execute(text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": ids})


def drop_alerts_about(db, ref_type, ref_ids):
    """The bell's alerts about these records, and who has read them, so nothing points at a record that is gone."""
    if not ref_ids:
        return
    alert_ids = [a.id for a in db.query(models.DBAlert.id).filter(
        models.DBAlert.ref_type == ref_type, models.DBAlert.ref_id.in_(ref_ids)).all()]
    if alert_ids:
        sweep_referrers(db, {"office_alerts": alert_ids})
        db.query(models.DBAlert).filter(models.DBAlert.id.in_(alert_ids)).delete(synchronize_session=False)


def wo_chain_ids(db, client_id, order):
    """Every version of an order: the original, its revisions, and theirs."""
    seen = {order.id}
    queue = [order]
    while queue:
        o = queue.pop()
        neighbours = db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client_id,
            or_(models.DBSubcontractOrder.supersedes_id == o.id,
                models.DBSubcontractOrder.id == (o.supersedes_id or 0))).all()
        for n in neighbours:
            if n.id not in seen:
                seen.add(n.id)
                queue.append(n)
    return sorted(seen)


def wo_delete_report(db, client, order):
    ids = wo_chain_ids(db, client.id, order)
    orders = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id.in_(ids)).order_by(models.DBSubcontractOrder.id).all()
    bills = db.query(models.DBSubBill).filter(models.DBSubBill.order_id.in_(ids)).all()
    blockers = []
    for o in orders:
        if settled_on(db, client.id, "sub_advance", o.id) > 0:
            blockers.append("%s has an advance paid against it - that payment is deleted too." % o.wo_number)
    for b in bills:
        got = settled_on(db, client.id, "sub_bill", b.id)
        if (b.status or "") == "PAID" or got > 0:
            blockers.append("%s is paid%s - the payments are deleted too." % (
                b.number, " (%s)" % inr(got) if got > 0 else ""))
    released = db.query(models.DBRetentionRelease).filter(
        models.DBRetentionRelease.sub_order_id.in_(ids),
        models.DBRetentionRelease.status != "CANCELLED").count()
    if released:
        blockers.append("Retention has been released against it - the release is deleted too.")
    count = lambda model, col: db.query(model).filter(col.in_(ids)).count()
    return {
        "ids": ids,
        "numbers": [o.wo_number for o in orders],
        "blockers": [], "warnings": blockers,
        "counts": {
            "versions": len(orders),
            "items": count(models.DBSubcontractItem, models.DBSubcontractItem.order_id),
            "measurements": count(models.DBSubMeasurement, models.DBSubMeasurement.order_id),
            "bills": len(bills),
            "files": db.query(models.DBFile).filter(
                models.DBFile.attached_type == "subcontract_order",
                models.DBFile.attached_id.in_(ids)).count(),
        },
    }


def wo_delete_order_now(order_id, request, db):
    client = get_client_user(request, db)
    require_owner(request, db)
    order = wo_or_404(db, client.id, order_id)
    rep = wo_delete_report(db, client, order)
    ids = rep["ids"]
    bill_ids = [b.id for b in db.query(models.DBSubBill.id).filter(models.DBSubBill.order_id.in_(ids)).all()]
    sub_meas = [m.id for m in db.query(models.DBSubMeasurement.id).filter(models.DBSubMeasurement.order_id.in_(ids)).all()]
    rel_ids = [r.id for r in db.query(models.DBRetentionRelease.id).filter(models.DBRetentionRelease.sub_order_id.in_(ids)).all()]
    drop = lambda q: q.delete(synchronize_session=False)
    cascade_delete_referrers(db, "subcontract_orders", ids)
    if bill_ids:
        drop_files_of(db, "sub_bill_scan", bill_ids)
        drop(db.query(models.DBSubBillLine).filter(models.DBSubBillLine.sub_bill_id.in_(bill_ids)))
        drop(db.query(models.DBApprovalChain).filter(
            models.DBApprovalChain.entity_type == "sub_bill", models.DBApprovalChain.entity_id.in_(bill_ids)))
        # Voided entries net to nothing; they would only point at a bill that is no longer there.
        drop(db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.doc_type == "sub_bill", models.DBMoneyEntry.doc_id.in_(bill_ids)))
        drop_alerts_about(db, "sub_bill", bill_ids)
    if sub_meas:
        drop(db.query(models.DBMeasurementDimension).filter(models.DBMeasurementDimension.sub_measurement_id.in_(sub_meas)))
        drop_files_of(db, "sub_measurement", sub_meas)
    drop(db.query(models.DBMaterialRecovery).filter(models.DBMaterialRecovery.order_id.in_(ids)))
    drop(db.query(models.DBSubMeasurement).filter(models.DBSubMeasurement.order_id.in_(ids)))
    drop(db.query(models.DBSubBill).filter(models.DBSubBill.order_id.in_(ids)))
    if rel_ids:
        drop(db.query(models.DBMoneyEntry).filter(
            models.DBMoneyEntry.doc_type == "retention_release", models.DBMoneyEntry.doc_id.in_(rel_ids)))
    drop(db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "subcontract_order", models.DBApprovalChain.entity_id.in_(ids)))
    drop(db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.doc_type == "sub_advance", models.DBMoneyEntry.doc_id.in_(ids)))
    drop_alerts_about(db, "subcontract_order", ids)
    drop_files_of(db, "subcontract_order", ids)
    drop(db.query(models.DBSubcontractApproval).filter(models.DBSubcontractApproval.order_id.in_(ids)))
    drop(db.query(models.DBSubcontractTerm).filter(models.DBSubcontractTerm.order_id.in_(ids)))
    drop(db.query(models.DBSubcontractItem).filter(models.DBSubcontractItem.order_id.in_(ids)))
    # Orders outside the chain that were copied from one inside it keep their own content.
    db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.copied_from_id.in_(ids),
        models.DBSubcontractOrder.id.notin_(ids)).update({"copied_from_id": None}, synchronize_session=False)
    db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.id.in_(ids)).update(
            {"supersedes_id": None, "copied_from_id": None}, synchronize_session=False)
    sweep_referrers(db, {"subcontract_orders": ids, "sub_bills": bill_ids, "sub_measurements": sub_meas})
    drop(db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.id.in_(ids)))
    log_audit(db, client.id, "subcontract_deleted", "subcontract_order", order.id,
              order.wo_number or "", "Deleted with %s" % ", ".join(rep["numbers"]), request)
    db.commit()
    return {"ok": True, "deleted": rep["numbers"],
            "message": "%s deleted%s." % (", ".join(rep["numbers"][:3]) + ("..." if len(rep["numbers"]) > 3 else ""),
                                          " everywhere" if rep["counts"]["bills"] or rep["counts"]["measurements"] else "")}


def _vendor_report(db, client, con):
    orders = db.query(models.DBSubcontractOrder).filter(
        models.DBSubcontractOrder.client_id == client.id, models.DBSubcontractOrder.contractor_id == con.id).all()
    ids = sorted({i for o in orders for i in wo_chain_ids(db, client.id, o)})
    bills = db.query(models.DBSubBill).filter(models.DBSubBill.client_id == client.id, models.DBSubBill.contractor_id == con.id).count()
    money_rows = db.query(models.DBMoneyEntry).filter(
        models.DBMoneyEntry.client_id == client.id, models.DBMoneyEntry.party_type == "contractor",
        models.DBMoneyEntry.party_id == con.id, models.DBMoneyEntry.voided.is_(False)).all()
    paid = money(sum(abs(e.amount or 0) for e in money_rows))
    logins = db.query(models.DBPortalUser).filter(
        models.DBPortalUser.client_id == client.id, models.DBPortalUser.party_type == "contractor",
        models.DBPortalUser.party_id == con.id).count()
    return ids, bills, paid, logins


def _vendor_or_404(db, client, con_id):
    con = db.query(models.DBContractor).filter(models.DBContractor.id == con_id, models.DBContractor.client_id == client.id).first()
    if not con:
        raise HTTPException(404, "Vendor not found")
    return con


# THE WORK ORDER STATEMENT
#
# Everything this app knows about one order, reconciled down a single column:
# what was ordered, what was agreed on top of it, what has been built, what
# has been claimed, what has been certified, what has been paid, and what is
# still being held back.
#
# Each of those numbers already existed, on a different screen. The question a
# contractor actually asks - "where are we on this order" - could only be
# answered by opening four of them and doing the subtraction by hand, which is
# the same arithmetic error this app was built to stop.
def work_order_statement(db, client, wo):
    lines = db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).order_by(
            models.DBWorkOrderLine.id).all()
    measured = measured_to_date(db, wo.id)
    billed_qty = billed_qty_to_date(db, wo.id)

    # Variations that were agreed are already inside the order's own value -
    # approving one raises the lines - so the original is what is left when
    # they are taken back off. Counting them again here would double them.
    vos = db.query(models.DBVariationOrder).filter(
        models.DBVariationOrder.work_order_id == wo.id).all()
    agreed = money(sum(v.value or 0 for v in vos if (v.status or "") == "APPROVED"))
    pending_vo = money(sum(v.value or 0 for v in vos
                           if (v.status or "") in ("DRAFT", "SUBMITTED")))
    revised = money(wo.total_value)
    original = money(revised - agreed)

    rows, measured_value, unbilled_value, over_run = [], 0.0, 0.0, 0.0
    for l in lines:
        rate = unit_rate(l.rate)
        done = money(measured.get(l.id, 0.0))
        claimed = money(billed_qty.get(l.id, 0.0))
        ordered = money(l.qty)
        measured_value += done * rate
        unbilled_value += money(done - claimed) * rate
        if done > ordered:
            over_run += money(done - ordered) * rate
        rows.append({
            "fg_code": l.fg_code or "",
            "description": (l.description or l.item_name or "").split("\n")[0],
            "uom": l.uom or "", "ordered_qty": ordered, "rate": rate,
            "ordered_value": money(ordered * rate),
            "measured_qty": done, "measured_value": money(done * rate),
            "billed_qty": claimed, "billed_value": money(claimed * rate),
            "unbilled_qty": money(done - claimed),
            "unbilled_value": money(money(done - claimed) * rate),
            "percent_measured": round(done / ordered * 100, 1) if ordered else 0.0,
        })

    bills = db.query(models.DBRABill).filter(
        models.DBRABill.work_order_id == wo.id,
        models.DBRABill.status != "CANCELLED").all()
    claimed_value = money(sum(b.this_bill or 0 for b in bills))
    certified = money(sum(b.this_bill or 0 for b in bills
                          if (b.status or "") in ("CERTIFIED", "PAID")))
    paid = money(sum(b.net_payable or 0 for b in bills if (b.status or "") == "PAID"))
    awaiting = money(sum(b.net_payable or 0 for b in bills
                         if (b.status or "") == "CERTIFIED"))
    retention = money(sum(b.retention_amount or 0 for b in bills
                          if (b.status or "") in ("CERTIFIED", "PAID"))
                      - released_retention(db, wo.client_id, "client").get(wo.id, 0.0))
    tds = money(sum(b.tds_amount or 0 for b in bills if (b.status or "") == "PAID"))

    return {
        "work_order": work_order_to_dict(db, wo),
        "lines": rows,
        "order": {
            "original_value": original,
            "variations_agreed": agreed,
            "variations_pending": pending_vo,
            "revised_value": revised,
        },
        "progress": {
            "measured_value": money(measured_value),
            "percent_complete": round(measured_value / revised * 100, 1) if revised else 0.0,
            "left_to_build": money(revised - measured_value),
            "over_run_not_yet_varied": money(over_run),
        },
        "money": {
            "claimed": claimed_value,
            "certified": certified,
            "paid": paid,
            "awaiting_payment": awaiting,
            "retention_held": retention,
            "tds_deducted": tds,
            # Built, but not yet on any bill. The number worth chasing, because
            # it is work already paid for in wages and material.
            "measured_not_billed": money(unbilled_value),
        },
        "bills": [{
            "id": b.id, "number": b.number or "", "status": b.status or "",
            "this_bill": money(b.this_bill), "net_payable": money(b.net_payable),
        } for b in sorted(bills, key=lambda x: x.sequence or 0)],
        "variations": [{
            "id": v.id, "number": v.number or "", "status": v.status or "",
            "value": money(v.value),
        } for v in sorted(vos, key=lambda x: x.sequence or 0)],
    }


def work_order_from_estimate(db, client, est, request):
    """The priced schedule becomes the order. Nothing is retyped.

    Every item needs a code the order can carry; one that has none gets a
    finished-goods code issued now, the same way the work order builder
    would, so the measurement book can be kept against it later.
    """
    items = db.query(models.DBEstimateItem).filter(
        models.DBEstimateItem.estimate_id == est.id).order_by(
            models.DBEstimateItem.display_order, models.DBEstimateItem.id).all()
    if not items:
        raise HTTPException(409, "There is nothing on this tender to turn into an order.")
    wo = models.DBWorkOrder(
        client_id=client.id, job_id=est.job_id,
        number=next_sequence_number(db, models.DBWorkOrder, client.id, "WO-"),
        order_date=datetime.now().strftime("%Y-%m-%d"),
        reference=est.tender_reference or est.number or "",
        notes="From %s - %s" % (est.number, est.title or ""),
        status="Draft", total_value=0.0)
    db.add(wo)
    db.flush()
    total = 0.0
    for it in items:
        code = (it.fg_code or "").strip().upper()
        existing = db.query(models.DBItem).filter(
            models.DBItem.client_id == client.id,
            models.DBItem.item_code == code).first() if code else None
        if not existing:
            existing = models.DBItem(
                client_id=client.id, kind="FG",
                item_code=next_item_code(db, client.id),
                item_name=(it.description or "Tender item")[:200],
                description=it.description or "", category="FINISHED GOOD",
                sub_category="FG", units_of_measure=standard_unit(it.uom) or "Nos",
                item_type="Service", last_rate=it.quoted_rate or 0)
            db.add(existing)
            db.flush()
            it.fg_code = existing.item_code
        amount = money((it.quantity or 0) * (it.quoted_rate or 0))
        total += amount
        db.add(models.DBWorkOrderLine(
            work_order_id=wo.id, fg_code=existing.item_code,
            item_name=existing.item_name, description=it.description or "",
            qty=money(it.quantity), uom=standard_unit(it.uom) or existing.units_of_measure or "",
            rate=unit_rate(it.quoted_rate), amount=amount))
        existing.last_rate = unit_rate(it.quoted_rate)
    wo.total_value = money(total)
    log_audit(db, client.id, "work_order_from_estimate", "work_order", wo.id,
              wo.number, "%s -> %d line(s) %s" % (est.number, len(items), inr(total)), request)
    db.flush()
    return wo


#
# A list with hundreds of rows is cleared by ticking them, not by deleting one at a time. Each id goes through
# the very same delete as the single one - the same rules, the same owner-only checks, the same everything-
# attached-goes - and one that is refused or already gone does not stop the rest. The screen sends a few at
# a time so a large clearing never waits on one long request.
def run_bulk_delete(ids, delete_one, db):
    done, gone, failed = 0, 0, []
    seen = set()
    for raw in list(ids or [])[:200]:
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if i in seen:
            continue
        seen.add(i)
        try:
            delete_one(i)
            done += 1
        except HTTPException as exc:
            db.rollback()
            if exc.status_code == 404:
                gone += 1               # already gone - an earlier version of the same order took it with it
            else:
                failed.append({"id": i, "reason": str(exc.detail)})
        except IntegrityError as exc:
            db.rollback()
            failed.append({"id": i, "reason": "Could not delete it: %s" % str(getattr(exc, "orig", exc)).splitlines()[0][:200]})
    parts = ["%d deleted" % done]
    if gone:
        parts.append("%d already gone" % gone)
    if failed:
        parts.append("%d refused" % len(failed))
    return {"ok": not failed, "deleted": done, "gone": gone, "failed": failed, "message": ", ".join(parts) + "."}


def contractor_released(db, client_id, order_id=0):
    return money(sum(r.amount or 0 for r in _live_releases(db, client_id, "contractor")
                     if not order_id or r.sub_order_id == order_id))


def wo_variations(db, wo, cutoff):
    """The variations agreed on a client order drawn from a BOQ, up to a date: the order's value as first placed, each
    variation, and the value as varied. None for an order with no BOQ or no approved variation by then."""
    if not wo or not wo.boq_id:
        return None
    every = db.query(models.DBBoqVariation).filter(models.DBBoqVariation.boq_id == wo.boq_id,
                                                   models.DBBoqVariation.status == "APPROVED").order_by(models.DBBoqVariation.id).all()
    if not every:
        return None
    original = money((wo.total_value or 0) - sum(v.value or 0 for v in every))
    out = []
    for v in every:
        if (v.approved_at or "")[:10] > cutoff:
            continue
        lines = db.query(models.DBBoqVariationLine).filter(models.DBBoqVariationLine.variation_id == v.id).order_by(
            models.DBBoqVariationLine.display_order, models.DBBoqVariationLine.id).all()
        what = "; ".join(
            ("%s %s%s" % (l.sno or "", l.description.split("\n")[0][:40],
                          (" (+%g)" % l.change_qty) if l.kind == "quantity" else (" (new, %g %s)" % (l.change_qty, l.uom)))).strip()
            for l in lines[:6]) + ("; ..." if len(lines) > 6 else "")
        out.append({"number": (v.number or "").rsplit("/", 1)[-1], "date": (v.approved_at or "")[:10], "reason": v.reason or "",
                    "what": what, "value": money(v.value)})
    if not out:
        return None
    return {"original": original, "variations": out, "varied": money(original + sum(x["value"] for x in out))}


def registration_form_data(db, client, con):
    """The form's boxes, filled - one description for the PDF and the workbook."""
    company = letterhead(db, client)["name"] or client.company_name or ""
    docs = set((con.documents or "").split(","))
    return {
        "company": company.upper(), "project": con.registered_project or "",
        "vendor_code": con.vendor_code or "", "name": con.company_name or "",
        "personal": [("Name of the Sub Contractor:", con.company_name or ""),
                     ("Residential Address:", con.address or ""),
                     ("Date of Joining :", form_pdf.date_text(con.joining_date) if re.match(
                         r"^\d{4}-\d{2}-\d{2}", con.joining_date or "") else (con.joining_date or "")),
                     ("Pin Code :", con.pin_code or ""), ("City :", con.city or ""), ("State :", con.state or ""),
                     ("Nature of Work :", con.nature_of_work or ""), ("Tel no. :", con.phone_number or ""),
                     ("E - mail Id :", con.email or ""), ("Name of Contact Person :", con.contact_person or ""),
                     ("Type of Entity : ", con.entity_type or ""), ("PAN no. :", con.pan or ""),
                     ("GST Reg No :", con.gst_number or ""), ("Aadhar Card :", con.aadhaar or "")],
        "bank": [("Bank Name :", con.bank_name or ""), ("Account no :", con.bank_account or ""),
                 ("IFSC Code :", con.bank_ifsc or ""), ("Branch :", con.bank_branch or "")],
        "documents": [(label, key in docs) for key, label in REGISTRATION_DOCUMENTS],
        "declaration": [line % company if "%s" in line else line for line in REGISTRATION_DECLARATION],
        "declaration_signed": bool(con.declaration_signed),
        "status": con.registration_status or "APPROVED",
        "approved_by": con.approved_by_name or "", "approved_at": con.approved_at or "",
    }


def contractor_or_404(db, client_id, con_id):
    con = db.query(models.DBContractor).filter(models.DBContractor.id == con_id,
                                               models.DBContractor.client_id == client_id).first()
    if not con:
        raise HTTPException(404, "Contractor not found")
    return con


def wo_chain_rows(db, order_id):
    return chain_rows(db, "subcontract_order", order_id)


def wo_start_chain(db, client, order, submitter_id):
    forget_chain(db, "subcontract_order", order.id)
    db.query(models.DBApprovalChain).filter(
        models.DBApprovalChain.entity_type == "subcontract_order",
        models.DBApprovalChain.entity_id == order.id).delete(synchronize_session=False)
    rungs = hierarchy_chain(db, client.id, submitter_id, "subcontracts.approve", order.job_id,
                            owner_signs=wo_owner_signs(db, client.id)) or [chain_rung(None, db, client.id)]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i, rung in enumerate(rungs, 1):
        db.add(models.DBApprovalChain(
            client_id=client.id, entity_type="subcontract_order", entity_id=order.id,
            employee_id=submitter_id, approver_id=rung["employee_id"], level=rung["level"],
            step=i, status="pending", created_at=now))
    db.flush()
    return rungs


def ensure_wo_chain(db, client, order):
    """An order sent before routes existed gets its route the first time
    anybody looks for it."""
    if (order.status or "") == "PROVISIONAL" and not wo_chain_rows(db, order.id):
        wo_start_chain(db, client, order, order.submitted_by)


def wo_current_step(db, order):
    """The step the order waits at. A step whose approver has left, or no
    longer holds the right, is passed over rather than left to block it."""
    for row in wo_chain_rows(db, order.id):
        if row.status != "pending":
            continue
        if row.approver_id is None:
            return row
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == row.approver_id).first()
        if emp and (emp.status or "active") not in GONE_STATUSES and employee_can(emp, "subcontracts.approve"):
            return row
        row.status, row.notes = "skipped", "No longer able to approve work orders"
        row.decided_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return None


def wo_step_name(db, row):
    if row is None:
        return ""
    return owner_label(db, row.client_id) if row.approver_id is None else _person(db, row.approver_id)


def wo_route(db, order):
    """The route as the order screen shows it: who, in what order, and where it is."""
    rows = wo_chain_rows(db, order.id)
    current = wo_current_step(db, order) if (order.status or "") == "PROVISIONAL" else None
    return [{"step": r.step, "name": wo_step_name(db, r), "owner": r.approver_id is None,
             "status": "waiting" if current is not None and r.id == current.id else r.status,
             "notes": r.notes or "", "decided_at": r.decided_at or ""} for r in rows]


def wo_waiting_names(db, client, order):
    if (order.status or "") != "PROVISIONAL":
        return []
    ensure_wo_chain(db, client, order)
    step = wo_current_step(db, order)
    return [wo_step_name(db, step)] if step is not None else []


def wo_decide_step(db, client, order, actor_id, actor_name, approve, comments="", override=False):
    """One approver's decision on a work order that is climbing its route.

    Each approver signs in turn. The owner may sign at any point, and their
    signature is the last word. The final signature is the approval, and it
    is there - not earlier - that an overrun has to be explained. Sending it
    back at any step returns it to the person who raised it.
    """
    if (order.status or "") != "PROVISIONAL":
        wo_apply(db, client, order, "APPROVE" if approve else "REJECT", actor_id, actor_name,
                 comments, override=override)
        return None
    ensure_wo_chain(db, client, order)
    step = wo_current_step(db, order)
    owner = actor_id is None
    if not owner and approve and order.submitted_by == actor_id:
        raise HTTPException(403, "You raised this order, so somebody else has to approve it. "
                                 "It is waiting with " + (wo_step_name(db, step) or "the Master") + ".")
    if not owner and (step is None or step.approver_id != actor_id):
        later = any(r.approver_id == actor_id and r.status == "pending" for r in wo_chain_rows(db, order.id))
        raise HTTPException(403, "%s is waiting with %s.%s" % (
            order.wo_number, wo_step_name(db, step) or "the Master",
            " It comes to you after that." if later else " It is not on your list to approve."))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not approve:
        if not (comments or "").strip():
            raise HTTPException(400, "Say why it is going back, so it can be corrected.")
        if step is not None:
            step.status, step.notes, step.decided_at = "rejected", comments.strip(), now
        wo_apply(db, client, order, "REJECT", actor_id, actor_name, comments)
        return None
    if owner:
        # The owner's signature is the last word: their own step is signed,
        # and anybody still to sign before it is recorded as passed over.
        for row in wo_chain_rows(db, order.id):
            if row.status == "pending":
                if row.approver_id is None:
                    row.status, row.notes, row.decided_at = "approved", (comments or "").strip(), now
                else:
                    row.status, row.notes, row.decided_at = "skipped", "Signed over by the Master", now
    elif step is not None:
        step.status, step.notes, step.decided_at = "approved", (comments or "").strip(), now
    db.flush()
    nxt = None if owner else wo_current_step(db, order)
    if nxt is None:
        wo_apply(db, client, order, "APPROVE", actor_id, actor_name, comments, override=override)
        return None
    record_wo_action(db, client, order, actor_id, actor_name, "RECOMMEND", "PROVISIONAL",
                     (comments or "").strip() or ("Approved and passed to " + wo_step_name(db, nxt)))
    if nxt.approver_id:
        notify_employee(db, client.id, nxt.approver_id, "Work order awaiting your approval",
                        "%s to %s, %s - approved by %s and now with you." % (
                            order.wo_number, wo_dict(db, order).get("contractor") or "a contractor",
                            format_money_plain(order.net_order_value), actor_name),
                        link="/next/approvals")
    return nxt


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.core.files import drop_files_of
from app.core.notifications import notify_employee
from app.documents.letterhead import company_address, letterhead
from app.services.approvals import (
    _person,
    chain_rung,
    get_approval_chain_history,
    hierarchy_chain,
    holders_of,
    owner_label,
    wo_owner_signs,
)
from app.services.client_billing import billed_qty_to_date, measured_to_date
from app.services.crm import advance_paid, next_item_code, norm_name, settled_on, standard_unit
from app.services.invoicing import active_irn
from app.services.subcontract_billing import _live_releases, released_retention, sub_gross_measured
