"""The rules and workings behind the projects endpoints."""
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, func as sqlfunc

from app import models

from app.constants.client_billing import RA_CREDIT_DAYS
from app.constants.invoicing import EWAY_THRESHOLD
from app.constants.projects import JOB_FINISHED
from app.constants.quality import SERIOUS_KINDS
from app.core.config import logger
from app.core.currency import inr, money, unit_rate
from app.core.dates import _days_until, ageing_bucket
from app.core.queries import by_id, on_job
from app.services.assets import asset_service_state, equipment_cost_by_job
from app.services.stores import stock_balances, stocked_share_of_bills


def job_or_404(db, client_id, job_id):
    job = db.query(models.DBJob).filter(
        models.DBJob.id == job_id, models.DBJob.client_id == client_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def resolve_job_id(db, client_id, job_id):
    """Check a job reference off a document before it is stored.

    Returning None for a blank keeps every document's job optional; raising for
    a wrong one stops a cost being filed against another company's site.
    """
    if job_id in (None, "", 0):
        return None
    try:
        job_id = int(job_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Unknown job")
    job_or_404(db, client_id, job_id)
    return job_id


def invoice_total(inv) -> float:
    """What an invoice is worth. Invoices keep paid/due rather than a total, so
    the value of one is what has been settled plus what is still owed."""
    return money((inv.paid or 0) + (inv.due or 0))


def hourly_rates(db, client_id):
    """Each person's hourly rate, read once per request."""
    held = db.info.setdefault("hourly_rates", {})
    if client_id not in held:
        held[client_id] = {e.id: (e.hourly_rate or 0.0) for e in db.query(
            models.DBEmployee.id, models.DBEmployee.hourly_rate).filter(models.DBEmployee.client_id == client_id).all()}
    return held[client_id]


def labour_cost_for_job(db, client_id, job_id):
    """Hours booked to a job, costed at each person's hourly rate.

    Salaried people have no hourly rate, so their time shows as hours with no
    money against it rather than as a guess at what an hour of them costs.
    """
    rows = on_job(db, models.DBAttendance, client_id, job_id)
    if not rows:
        return 0.0, 0.0
    rates = hourly_rates(db, client_id)
    hours = sum(r.total_hours or 0.0 for r in rows)
    cost = sum((r.total_hours or 0.0) * rates.get(r.employee_id, 0.0) for r in rows)
    return money(cost), round(hours, 2)


def job_costing(db, client_id, job):
    """Quoted, committed, spent, invoiced - and what is left of it.

    "Committed" is approved purchase orders that no bill has arrived for yet.
    Counting a PO and its bill both as spend would double the cost of every
    delivery, and ignoring open POs would show a job as profitable right up to
    the day the invoices land.
    """
    invoices = on_job(db, models.DBInvoice, client_id, job.id)
    live_invoices = [i for i in invoices if i.status != "Void"]
    invoiced = money(sum(invoice_total(i) for i in live_invoices))
    received = money(sum(i.paid or 0 for i in live_invoices))

    bills = on_job(db, models.DBBill, client_id, job.id)
    # A rejected cost is not a cost; it was refused.
    real_bills = [b for b in bills if (b.approval_status or "none") != "rejected"
                  and b.status != "Cancelled"]
    spent = money(sum(b.total or 0 for b in real_bills))
    unpaid = money(sum((b.total or 0) - (b.amount_paid or 0) for b in real_bills))

    billed_po_ids = {b.purchase_order_id for b in real_bills if b.purchase_order_id}
    orders = [o for o in on_job(db, models.DBPurchaseOrder, client_id, job.id)
              if o.approval_status == "approved"]
    committed = money(sum(o.total or 0 for o in orders
                          if o.id not in billed_po_ids
                          and o.status not in ("Closed", "Cancelled")))

    labour, hours = labour_cost_for_job(db, client_id, job.id)

    # Work orders are the priced scope actually sold on this job, and their
    # BOM is what that scope is budgeted to cost. Both are forward-looking:
    # they say what the job is worth and what it should take, before any of it
    # has been invoiced or bought.
    work_orders = on_job(db, models.DBWorkOrder, client_id, job.id)
    live_orders = [o for o in work_orders if (o.approval_status or "none") != "rejected"]
    ordered = money(sum(o.total_value or 0 for o in live_orders))
    if not live_orders:
        budgeted = 0.0
    elif db.info.get("by_job") is not None:
        pre = db.info["by_job"]
        if "bom" not in pre:
            pre["bom"] = dict(db.query(models.DBBomLine.work_order_id,
                                       func.coalesce(func.sum(models.DBBomLine.amount), 0.0)).filter(
                models.DBBomLine.client_id == client_id).group_by(models.DBBomLine.work_order_id).all())
        budgeted = money(sum(float(pre["bom"].get(o.id) or 0) for o in live_orders))
    else:
        budgeted = money(sum(
            b.amount or 0 for b in db.query(models.DBBomLine).filter(
                models.DBBomLine.work_order_id.in_([o.id for o in live_orders])).all()))

    quoted = money(job.quoted_value or 0)
    if not quoted and ordered:
        quoted = ordered
    if not quoted:
        # Fall back to what was actually quoted for this job and accepted.
        accepted = [q for q in on_job(db, models.DBQuote, client_id, job.id)
                    if q.status in ("Accepted", "Invoiced")]
        quoted = money(sum(q.total or 0 for q in accepted))

    total_cost = money(spent + labour)
    # Profit is measured against what has been invoiced, not what was quoted:
    # quoting a job well is not the same as having earned it.
    profit = money(invoiced - total_cost)
    margin = round((profit / invoiced * 100), 1) if invoiced else 0.0
    budget = money(job.budget or 0)

    return {
        "quoted": quoted,
        "budget": budget,
        "invoiced": invoiced,
        "received": received,
        "outstanding": money(invoiced - received),
        "spent": spent,
        "unpaid_bills": unpaid,
        "committed": committed,
        "labour_cost": labour,
        "labour_hours": hours,
        "total_cost": total_cost,
        # What the job will have cost if every open order lands in full.
        "forecast_cost": money(total_cost + committed),
        "profit": profit,
        "margin_percent": margin,
        "budget_remaining": money(budget - total_cost - committed) if budget else 0.0,
        "over_budget": bool(budget and (total_cost + committed) > budget),
        # Sold scope and its budget, from the work orders on this job.
        "ordered": ordered,
        "budgeted": budgeted,
        "expected_margin": money(ordered - budgeted) if budgeted else 0.0,
        "counts": {
            "invoices": len(live_invoices),
            "bills": len(real_bills),
            "open_orders": len([o for o in orders if o.id not in billed_po_ids]),
            "work_orders": len(live_orders),
        },
    }


def job_to_dict(db, job, costing=False):
    row = {
        "id": job.id, "number": job.number, "name": job.name,
        "customer_name": job.customer_name or "", "contact_id": job.contact_id,
        "site_address": job.site_address or "",
        "state_code": job.state_code or "", "description": job.description or "",
        "status": job.status or "quoting",
        "start_date": job.start_date or "", "target_end_date": job.target_end_date or "",
        "completed_at": job.completed_at or "",
        "quoted_value": job.quoted_value or 0.0, "budget": job.budget or 0.0,
            "retention_percent": job.retention_percent or 0.0,
        "currency": job.currency or "", "reference": job.reference or "",
        "manager_id": job.manager_id,
        "created_at": job.created_at or "",
    }
    if job.manager_id:
        row["manager_name"] = employee_name(by_id(db, models.DBEmployee, job.manager_id))
    else:
        row["manager_name"] = ""
    if costing:
        row["costing"] = job_costing(db, job.client_id, job)
    return row


def clamp_percent(value) -> float:
    """A percentage that cannot be nonsense. Retention outside 0-100 is a typo,
    and a negative one would quietly increase what the job appears to collect."""
    try:
        return round(min(100.0, max(0.0, float(value or 0))), 2)
    except (TypeError, ValueError):
        return 0.0


def cost_jobs(db, client_id, jobs):
    """Every job on the list, costed, in a fixed number of queries.

    Same figures as job_costing produces one at a time; this reads each table
    once for the whole set and buckets the rows by job. Kept beside it rather
    than replacing it, because a single job opened on its own is still cheaper
    to cost directly.
    """
    if not jobs:
        return []
    ids = [j.id for j in jobs]

    def bucket(rows, key="job_id"):
        out = {}
        for row in rows:
            out.setdefault(getattr(row, key), []).append(row)
        return out

    invoices = bucket(db.query(models.DBInvoice).filter(
        models.DBInvoice.client_id == client_id,
        models.DBInvoice.job_id.in_(ids)).all())
    bills = bucket(db.query(models.DBBill).filter(
        models.DBBill.client_id == client_id,
        models.DBBill.job_id.in_(ids)).all())
    orders = bucket(db.query(models.DBPurchaseOrder).filter(
        models.DBPurchaseOrder.client_id == client_id,
        models.DBPurchaseOrder.job_id.in_(ids)).all())
    work_orders = bucket(db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client_id,
        models.DBWorkOrder.job_id.in_(ids)).all())
    attendance = bucket(db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client_id,
        models.DBAttendance.job_id.in_(ids)).all())

    wo_ids = [w.id for group in work_orders.values() for w in group]
    bom_by_wo = {}
    if wo_ids:
        for line in db.query(models.DBBomLine).filter(
                models.DBBomLine.work_order_id.in_(wo_ids)).all():
            bom_by_wo.setdefault(line.work_order_id, []).append(line)

    rates = {e.id: (e.hourly_rate or 0.0) for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id).all()}
    managers = {e.id: employee_name(e) for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client_id).all()}

    out = []
    for job in jobs:
        live_invoices = [i for i in invoices.get(job.id, []) if i.status != "Void"]
        invoiced = money(sum(invoice_total(i) for i in live_invoices))
        received = money(sum(i.paid or 0 for i in live_invoices))

        real_bills = [b for b in bills.get(job.id, [])
                      if (b.approval_status or "none") != "rejected" and b.status != "Cancelled"]
        spent = money(sum(b.total or 0 for b in real_bills))
        unpaid = money(sum((b.total or 0) - (b.amount_paid or 0) for b in real_bills))
        billed_po_ids = {b.purchase_order_id for b in real_bills if b.purchase_order_id}

        open_orders = [o for o in orders.get(job.id, [])
                       if (o.approval_status or "none") == "approved"
                       and o.id not in billed_po_ids
                       and o.status not in ("Closed", "Cancelled")]
        committed = money(sum(o.total or 0 for o in open_orders))

        days = attendance.get(job.id, [])
        hours = round(sum(d.total_hours or 0.0 for d in days), 2)
        labour = money(sum((d.total_hours or 0.0) * rates.get(d.employee_id, 0.0) for d in days))

        live_wos = [w for w in work_orders.get(job.id, [])
                    if (w.approval_status or "none") != "rejected"]
        ordered = money(sum(w.total_value or 0 for w in live_wos))
        budgeted = money(sum(l.amount or 0 for w in live_wos
                             for l in bom_by_wo.get(w.id, [])))

        quoted = money(job.quoted_value or 0) or ordered
        total_cost = money(spent + labour)
        profit = money(invoiced - total_cost)
        budget = money(job.budget or 0)

        out.append({
            "id": job.id, "number": job.number, "name": job.name,
            "customer_name": job.customer_name or "", "contact_id": job.contact_id,
            "site_address": job.site_address or "", "description": job.description or "",
            "status": job.status or "quoting",
            "start_date": job.start_date or "", "target_end_date": job.target_end_date or "",
            "completed_at": job.completed_at or "",
            "quoted_value": job.quoted_value or 0.0, "budget": job.budget or 0.0,
            "retention_percent": job.retention_percent or 0.0,
            "currency": job.currency or "", "reference": job.reference or "",
            "manager_id": job.manager_id,
            "manager_name": managers.get(job.manager_id, ""),
            "created_at": job.created_at or "",
            "costing": {
                "quoted": quoted, "budget": budget,
                "invoiced": invoiced, "received": received,
                "outstanding": money(invoiced - received),
                "spent": spent, "unpaid_bills": unpaid, "committed": committed,
                "labour_cost": labour, "labour_hours": hours,
                "total_cost": total_cost,
                "forecast_cost": money(total_cost + committed),
                "profit": profit,
                "margin_percent": round(profit / invoiced * 100, 1) if invoiced else 0.0,
                "budget_remaining": money(budget - total_cost - committed) if budget else 0.0,
                "over_budget": bool(budget and (total_cost + committed) > budget),
                "ordered": ordered, "budgeted": budgeted,
                "expected_margin": money(ordered - budgeted) if budgeted else 0.0,
                "counts": {
                    "invoices": len(live_invoices), "bills": len(real_bills),
                    "open_orders": len(open_orders), "work_orders": len(live_wos),
                },
            },
        })
    return out


def customer_for_name(db, client_id, name):
    """The customer of that name, put on the customer list if it is not there.

    A project raised against a client typed by name left the customer list
    empty: nowhere to put the client's GSTIN and address, which every bill
    and e-invoice for that project needs. Matched without regard to case, so
    one business stays one customer."""
    name = (name or "").strip()
    known = db.query(models.DBContact).filter(
        models.DBContact.client_id == client_id,
        sqlfunc.lower(models.DBContact.name) == name.lower()).first()
    if known:
        return known
    contact = models.DBContact(client_id=client_id, code=next_customer_code(db, client_id),
                               name=name, is_active=True)
    db.add(contact)
    db.flush()
    return contact


# SEARCH - one box that actually finds things
def _hit(kind, label, sub="", number="", record_id=None):
    return {"type": kind, "label": label, "sub": sub,
            "number": number, "id": record_id}


def job_label_for(db, job_id):
    if not job_id:
        return ""
    job = by_id(db, models.DBJob, job_id)
    return f"{job.number} {job.name}" if job else ""


def measured_and_billed_for_all(db, client_id):
    """Measured and billed quantity per line, across every order at once.

    The dashboard used to ask this two queries at a time per order. For a
    hundred orders that was two hundred queries before it had drawn a single
    number; now it is two.
    """
    from sqlalchemy import func
    measured = {}
    for line_id, qty in db.query(models.DBMeasurement.line_id,
                                 func.sum(models.DBMeasurement.quantity)).filter(
            models.DBMeasurement.client_id == client_id).group_by(
                models.DBMeasurement.line_id).all():
        measured[line_id] = float(qty or 0.0)
    billed = {}
    live_ids = [b.id for b in db.query(models.DBRABill.id).filter(
        models.DBRABill.client_id == client_id,
        models.DBRABill.status != "CANCELLED").all()]
    if live_ids:
        for line_id, qty in db.query(models.DBRABillLine.line_id,
                                     func.sum(models.DBRABillLine.this_bill_qty)).filter(
                models.DBRABillLine.ra_bill_id.in_(live_ids)).group_by(
                    models.DBRABillLine.line_id).all():
            billed[line_id] = float(qty or 0.0)
    return measured, billed


def diary_or_404(db, client_id, diary_id):
    row = db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.id == diary_id,
        models.DBSiteDiary.client_id == client_id).first()
    if not row:
        raise HTTPException(404, "Diary not found")
    return row


def recost_diary(db, diary):
    """A manday is a head for the site's working day, not for a clock hour.

    Half a day is half a manday, and overtime shows up as more than one -
    which is what makes the labour histogram comparable across weeks where
    the site worked different hours.
    """
    labour = db.query(models.DBDiaryLabour).filter(
        models.DBDiaryLabour.site_diary_id == diary.id).all()
    plant = db.query(models.DBDiaryPlant).filter(
        models.DBDiaryPlant.site_diary_id == diary.id).all()
    day = diary.working_hours or 8.0

    mandays = 0.0
    for l in labour:
        heads = l.headcount or 0
        share = (l.hours or day) / day if day else 1.0
        mandays += heads * share
        l.amount = money(heads * share * (l.rate or 0))
    for p in plant:
        # Idle time is charged too. Plant that stood all day still costs
        # money, and hiding it is how a hire bill becomes a surprise.
        p.amount = money(((p.worked_hours or 0) + (p.idle_hours or 0)) * (p.rate or 0))

    diary.total_mandays = money(mandays)
    diary.labour_cost = money(sum(l.amount or 0 for l in labour))
    diary.plant_cost = money(sum(p.amount or 0 for p in plant))
    diary.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return diary


def diary_dict(db, d, detail=False):
    job = db.query(models.DBJob).filter(models.DBJob.id == d.job_id).first()
    wo = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.id == d.work_order_id).first() if d.work_order_id else None
    row = {
        "id": d.id, "job_id": d.job_id,
        "project": ("%s %s" % (job.number or "", job.name or "")).strip() if job else "",
        "work_order_id": d.work_order_id, "work_order": wo.number if wo else "",
        "diary_date": d.diary_date or "", "weather": d.weather or "Clear",
        "rain_hours": money(d.rain_hours), "working_hours": money(d.working_hours),
        "work_done": d.work_done or "", "holdups": d.holdups or "",
        "instructions": d.instructions or "", "visitors": d.visitors or "",
        "safety_note": d.safety_note or "",
        "labour_cost": money(d.labour_cost), "plant_cost": money(d.plant_cost),
        "day_cost": money((d.labour_cost or 0) + (d.plant_cost or 0)),
        "total_mandays": money(d.total_mandays),
        "status": d.status or "DRAFT", "prepared_by_name": d.prepared_by_name or "",
        "submitted_at": d.submitted_at or "",
        "editable": (d.status or "DRAFT") == "DRAFT",
        # A day the site was rained off is worth seeing at a glance.
        "lost_to_weather": bool((d.rain_hours or 0) >= (d.working_hours or 8) / 2),
        "created_at": d.created_at or "",
    }
    if detail:
        row["labour"] = [{
            "id": l.id, "trade": l.trade or "", "agency": l.agency or "Own",
            "headcount": money(l.headcount), "hours": money(l.hours),
            "rate": money(l.rate), "amount": money(l.amount),
        } for l in db.query(models.DBDiaryLabour).filter(
            models.DBDiaryLabour.site_diary_id == d.id).order_by(
                models.DBDiaryLabour.display_order, models.DBDiaryLabour.id).all()]
        row["plant"] = [{
            "id": p.id, "plant": p.plant or "",
            "worked_hours": money(p.worked_hours), "idle_hours": money(p.idle_hours),
            "rate": money(p.rate), "amount": money(p.amount),
            "remarks": p.remarks or "",
        } for p in db.query(models.DBDiaryPlant).filter(
            models.DBDiaryPlant.site_diary_id == d.id).order_by(
                models.DBDiaryPlant.display_order, models.DBDiaryPlant.id).all()]
    return row


def _replace_diary_lines(db, diary, labour, plant):
    if labour is not None:
        db.query(models.DBDiaryLabour).filter(
            models.DBDiaryLabour.site_diary_id == diary.id).delete()
        for i, l in enumerate((labour or [])[:60]):
            heads = money(l.get("headcount") or 0)
            if not heads:
                continue
            db.add(models.DBDiaryLabour(
                site_diary_id=diary.id, trade=(l.get("trade") or "")[:80],
                agency=(l.get("agency") or "Own")[:120], headcount=heads,
                hours=money(l.get("hours") if l.get("hours") is not None
                            else (diary.working_hours or 8)),
                rate=money(l.get("rate") or 0), display_order=i))
    if plant is not None:
        db.query(models.DBDiaryPlant).filter(
            models.DBDiaryPlant.site_diary_id == diary.id).delete()
        for i, p in enumerate((plant or [])[:60]):
            name = (p.get("plant") or "").strip()
            if not name:
                continue
            db.add(models.DBDiaryPlant(
                site_diary_id=diary.id, plant=name[:160],
                worked_hours=money(p.get("worked_hours") or 0),
                idle_hours=money(p.get("idle_hours") or 0),
                rate=money(p.get("rate") or 0),
                remarks=(p.get("remarks") or "")[:300], display_order=i))
    db.flush()
    recost_diary(db, diary)


def preload_pnl_for_job(db, client_id, job_id):
    from collections import defaultdict
    def one(rows):
        return {job_id: rows}
    wos = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client_id,
        models.DBWorkOrder.job_id == job_id).all()
    bom = defaultdict(float)
    ids = [w.id for w in wos]
    if ids:
        from sqlalchemy import func
        for wo_id, amt in db.query(models.DBBomLine.work_order_id,
                                   func.coalesce(func.sum(models.DBBomLine.amount), 0.0)).filter(
                models.DBBomLine.work_order_id.in_(ids)).group_by(
                    models.DBBomLine.work_order_id).all():
            bom[wo_id] = float(amt or 0)
    return {
        "wos": one(wos), "bom": bom,
        "invoices": one(db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client_id, models.DBInvoice.job_id == job_id).all()),
        "ra": one(db.query(models.DBRABill).filter(
            models.DBRABill.job_id == job_id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all()),
        "bills": one(db.query(models.DBBill).filter(
            models.DBBill.client_id == client_id, models.DBBill.job_id == job_id).all()),
        "moves": one(db.query(models.DBStockMovement).filter(
            models.DBStockMovement.client_id == client_id,
            models.DBStockMovement.job_id == job_id,
            models.DBStockMovement.kind.in_(("ISSUE", "RETURN"))).all()),
        "diaries": one(db.query(models.DBSiteDiary).filter(
            models.DBSiteDiary.client_id == client_id, models.DBSiteDiary.job_id == job_id).all()),
        "pos": one(db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.client_id == client_id,
            models.DBPurchaseOrder.job_id == job_id).all()),
        "sub": one(db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client_id, models.DBSubBill.job_id == job_id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all()),
        "released": one([r for r in _live_releases(db, client_id, "client") if r.job_id == job_id]),
        "equipment": {job_id: equipment_cost_by_job(db, client_id).get(job_id, 0.0)},
        "recovered": material_recovered_by_job(db, client_id, job_id),
        "stocked": stocked_share_of_bills(db, client_id),
        "attendance": one(db.query(models.DBAttendance).filter(
            models.DBAttendance.client_id == client_id, models.DBAttendance.job_id == job_id).all()),
        "subs": one(db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client_id, models.DBSubcontractOrder.job_id == job_id).all()),
        "settled": settled_amounts(db, client_id),
    }


def preload_pnl(db, client_id):
    """Every table the P&L reads, loaded once and grouped by project.

    The portfolio used to ask nine questions per project, one project at a
    time; twenty projects was a hundred and eighty queries. Now it is nine,
    and the per-project figures come out of these dicts.
    """
    from collections import defaultdict
    def by_job(rows, key="job_id"):
        out = defaultdict(list)
        for r in rows:
            out[getattr(r, key)].append(r)
        return out
    wos = by_job(db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client_id).all())
    wo_ids = [w.id for lst in wos.values() for w in lst]
    bom = defaultdict(float)
    if wo_ids:
        from sqlalchemy import func
        for wo_id, amt in db.query(models.DBBomLine.work_order_id,
                                   func.coalesce(func.sum(models.DBBomLine.amount), 0.0)).filter(
                models.DBBomLine.work_order_id.in_(wo_ids)).group_by(
                    models.DBBomLine.work_order_id).all():
            bom[wo_id] = float(amt or 0)
    return {
        "wos": wos, "bom": bom,
        "invoices": by_job(db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client_id).all()),
        "ra": by_job(db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client_id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all()),
        "bills": by_job(db.query(models.DBBill).filter(
            models.DBBill.client_id == client_id).all()),
        "moves": by_job(db.query(models.DBStockMovement).filter(
            models.DBStockMovement.client_id == client_id,
            models.DBStockMovement.kind.in_(("ISSUE", "RETURN"))).all()),
        "diaries": by_job(db.query(models.DBSiteDiary).filter(
            models.DBSiteDiary.client_id == client_id).all()),
        "pos": by_job(db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.client_id == client_id).all()),
        "sub": by_job(db.query(models.DBSubBill).filter(
            models.DBSubBill.client_id == client_id,
            models.DBSubBill.status.in_(("CERTIFIED", "PAID"))).all()),
        "released": by_job(_live_releases(db, client_id, "client")),
        "equipment": equipment_cost_by_job(db, client_id),
        "recovered": material_recovered_by_job(db, client_id),
        "stocked": stocked_share_of_bills(db, client_id),
        "attendance": by_job(db.query(models.DBAttendance).filter(
            models.DBAttendance.client_id == client_id).all()),
        "subs": by_job(db.query(models.DBSubcontractOrder).filter(
            models.DBSubcontractOrder.client_id == client_id).all()),
        "settled": settled_amounts(db, client_id),
    }


def project_pnl(db, client_id, job, pre=None):
    if pre is None:
        # A single project: the same nine questions, asked for one job only.
        pre = preload_pnl_for_job(db, client_id, job.id)
    wos = pre["wos"].get(job.id, [])
    live = [w for w in wos if (w.approval_status or "none") != "rejected"]
    wo_ids = [w.id for w in live]
    order_value = money(sum(w.total_value or 0 for w in live))

    # --- earned ----------------------------------------------------------
    invoices = [i for i in pre["invoices"].get(job.id, [])
                if (i.status or "") not in ("Draft", "Cancelled", "Void")]
    invoiced = money(sum(invoice_total(i) for i in invoices))
    collected = money(sum(i.paid or 0 for i in invoices))

    bills = pre["ra"].get(job.id, [])
    certified = money(sum(b.this_bill or 0 for b in bills))
    retention = money(sum(b.retention_amount or 0 for b in bills)
                      - sum(r.amount or 0 for r in (pre.get("released") or {}).get(job.id, [])))

    # --- what it cost ----------------------------------------------------
    supplier_bills = [b for b in pre["bills"].get(job.id, [])
                      if (b.approval_status or "none") != "rejected"
                      and (b.status or "") != "Cancelled"]
    # Material that went into the store is stock until it is issued, and the
    # issue is what charges it to the job. Counting the supplier's bill as
    # well charged it twice: 100 bags bought for a job and 60 issued showed
    # as 64,000 of cost for 24,000 of cement used. What a bill spent on
    # stocked items comes off here; its hire, transport and services stay.
    stocked = pre.get("stocked") or {}
    bill_cost = money(sum((b.total or 0) * (1.0 - stocked.get(b.id, 0.0)) for b in supplier_bills))

    # Material actually drawn from the store for this job. Issues are negative
    # and returns positive, so the negated sum is what the site consumed and a
    # cancelled issue costs nothing.
    material = money(-sum(m.value or 0 for m in pre["moves"].get(job.id, [])))

    diaries = pre["diaries"].get(job.id, [])
    labour = money(sum(d.labour_cost or 0 for d in diaries))
    plant = money(sum(d.plant_cost or 0 for d in diaries))
    mandays = money(sum(d.total_mandays or 0 for d in diaries))

    # A purchase order stops being a commitment the moment a bill references
    # it, so the same spend is never counted twice.
    billed_pos = {b.purchase_order_id for b in supplier_bills if b.purchase_order_id}
    committed = money(sum(
        p.total or 0 for p in pre["pos"].get(job.id, [])
        if p.id not in billed_pos
        and (p.status or "") in ("Approved", "Awaiting Approval")))

    # What the gangs have billed us for and we have agreed to pay. This was
    # missing entirely, which flattered every project by the whole of its
    # subcontract cost.
    subcontract = money(sum(b.this_bill or 0 for b in pre["sub"].get(job.id, [])))

    # Diesel, hire and repairs on the machines that worked this site - kept
    # in the equipment register, so the diary lists only plant that is not.
    equipment = money((pre.get("equipment") or {}).get(job.id, 0.0))

    # Material issued to a gang and taken back out of their bill: its cost is
    # inside what they billed, so it comes off here or it is counted twice.
    recovered = money((pre.get("recovered") or {}).get(job.id, 0.0))

    incurred = money(bill_cost + material + labour + plant + subcontract + equipment - recovered)
    budgeted = money(sum(pre["bom"].get(i, 0.0) for i in wo_ids)) if wo_ids else 0.0

    revenue = money(max(invoiced, certified))
    margin = money(revenue - incurred)

    return {
        "job": {"id": job.id, "number": job.number or "", "name": job.name or "",
                "customer_name": job.customer_name or "", "status": job.status or "",
                "site_address": job.site_address or ""},
        "value": {
            "order_value": order_value,
            "quoted_value": money(job.quoted_value),
            "budgeted_cost": budgeted,
        },
        "earned": {
            "invoiced": invoiced, "collected": collected,
            "outstanding": money(invoiced - collected),
            "certified": certified, "retention_held": retention,
            "revenue": revenue,
        },
        "cost": {
            "supplier_bills": bill_cost,
            "subcontractors": subcontract,
            "material_from_store": material,
            "labour": labour,
            "plant": plant,
            "equipment": equipment,
            "material_recovered_from_gangs": recovered,
            "incurred": incurred,
            "committed_not_yet_billed": committed,
            "forecast": money(incurred + committed),
        },
        "result": {
            "margin": margin,
            "margin_percent": round(margin / revenue * 100, 1) if revenue else 0.0,
            "cost_per_manday": money(incurred / mandays) if mandays else 0.0,
            "mandays": mandays,
            # Costing more than it was budgeted to is the earliest warning
            # there is, and it arrives long before the revenue does.
            "over_budget": bool(budgeted) and incurred > budgeted,
            "budget_used_percent": (round(incurred / budgeted * 100, 1)
                                    if budgeted else 0.0),
        },
    }


# WHAT NEEDS LOOKING AT TODAY
#
# Every figure below already exists on some screen. The point of gathering
# them is that nobody opens eleven screens on a Monday morning, so the things
# that quietly cost money - work built and never billed, a bill sitting
# uncertified, a store that has gone negative, a site that has not filed a
# diary - were only ever found by accident.
#
# Ordered by what it costs to ignore, not by which module it came from.
def attention_items(db, client_id):
    items = []
    jobs = {j.id: j for j in db.query(models.DBJob).filter(
        models.DBJob.client_id == client_id).all()}

    # --- work built and not yet claimed ---------------------------------
    unbilled_total, unbilled_orders = 0.0, 0
    over_run_total, over_run_orders = 0.0, 0
    placed = {w.id for w in db.query(models.DBWorkOrder.id).filter(
        models.DBWorkOrder.client_id == client_id,
        models.DBWorkOrder.status != "Draft").all()}
    if placed:
        measured, billed = measured_and_billed_for_all(db, client_id)
        per_order = {}
        for l in db.query(models.DBWorkOrderLine).filter(
                models.DBWorkOrderLine.work_order_id.in_(list(placed))).all():
            rate = unit_rate(l.rate)
            done = money(measured.get(l.id, 0.0))
            acc = per_order.setdefault(l.work_order_id, [0.0, 0.0])
            acc[0] += money(done - money(billed.get(l.id, 0.0))) * rate
            if done > money(l.qty):
                acc[1] += money(done - money(l.qty)) * rate
        for unbilled, over in per_order.values():
            if unbilled > 0:
                unbilled_total += unbilled
                unbilled_orders += 1
            if over > 0:
                over_run_total += over
                over_run_orders += 1

    if unbilled_total > 0:
        items.append({
            "kind": "unbilled", "severity": "money", "value": money(unbilled_total),
            "count": unbilled_orders, "view": "measurement-view",
            "title": "Work measured but not billed",
            "detail": "%s across %d order%s. It is already paid for in wages "
                      "and material." % (inr(unbilled_total), unbilled_orders,
                                         "" if unbilled_orders == 1 else "s"),
        })
    if over_run_total > 0:
        items.append({
            "kind": "over_run", "severity": "money", "value": money(over_run_total),
            "count": over_run_orders, "view": "measurement-view",
            "title": "Built past the order",
            "detail": "%s of work nothing covers. Raise a variation and it "
                      "becomes billable." % inr(over_run_total),
        })

    # --- bills waiting on somebody --------------------------------------
    waiting = db.query(models.DBRABill).filter(
        models.DBRABill.client_id == client_id,
        models.DBRABill.status == "SUBMITTED").all()
    if waiting:
        items.append({
            "kind": "certify", "severity": "action",
            "value": money(sum(b.this_bill or 0 for b in waiting)),
            "count": len(waiting), "view": "measurement-view",
            "title": "RA bills awaiting certification",
            "detail": "%d bill%s worth %s cannot be paid until somebody signs."
                      % (len(waiting), "" if len(waiting) == 1 else "s",
                         inr(sum(b.this_bill or 0 for b in waiting))),
        })

    pending_vo = db.query(models.DBVariationOrder).filter(
        models.DBVariationOrder.client_id == client_id,
        models.DBVariationOrder.status == "SUBMITTED").all()
    if pending_vo:
        items.append({
            "kind": "variations", "severity": "action",
            "value": money(sum(v.value or 0 for v in pending_vo)),
            "count": len(pending_vo), "view": "measurement-view",
            "title": "Variations awaiting approval",
            "detail": "%s of extra work still to be agreed."
                      % inr(sum(v.value or 0 for v in pending_vo)),
        })

    # --- the store -------------------------------------------------------
    balances = stock_balances(db, client_id)
    levels = {i.item_code: (i.reorder_level or 0.0)
              for i in db.query(models.DBItem).filter(
                  models.DBItem.client_id == client_id).all()}
    negative = [a for a in balances.values() if a["on_hand"] < 0]
    low = [a for code, a in balances.items()
           if levels.get(code, 0) and 0 <= a["on_hand"] < levels[code]]
    if negative:
        items.append({
            "kind": "negative_stock", "severity": "wrong",
            "value": 0.0, "count": len(negative), "view": "stock-view",
            "title": "The store has gone negative",
            "detail": "%d item%s issued that was never booked in. Either a "
                      "delivery is unrecorded or something has walked."
                      % (len(negative), "" if len(negative) == 1 else "s"),
        })
    if low:
        items.append({
            "kind": "low_stock", "severity": "notice",
            "value": 0.0, "count": len(low), "view": "stock-view",
            "title": "Running low in the store",
            "detail": "%d item%s below the level somebody set."
                      % (len(low), "" if len(low) == 1 else "s"),
        })

    # --- the paperwork the site owes -------------------------------------
    drafts = db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.client_id == client_id,
        models.DBSiteDiary.status == "DRAFT").all()
    if drafts:
        items.append({
            "kind": "diaries", "severity": "notice", "value": 0.0,
            "count": len(drafts), "view": "diary-view",
            "title": "Site diaries not signed off",
            "detail": "%d day%s still in draft. An unsigned day is worth "
                      "nothing in a claim." % (len(drafts),
                                               "" if len(drafts) == 1 else "s"),
        })

    grn_drafts = db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.client_id == client_id,
        models.DBGoodsReceipt.status == "DRAFT").count()
    if grn_drafts:
        items.append({
            "kind": "receipts", "severity": "notice", "value": 0.0,
            "count": grn_drafts, "view": "stores-view",
            "title": "Deliveries not posted",
            "detail": "%d receipt%s open. Material is not in the store until "
                      "it is posted." % (grn_drafts,
                                         "" if grn_drafts == 1 else "s"),
        })

    # --- money -----------------------------------------------------------
    today = date.today()
    overdue_in = 0.0
    for inv in db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client_id).all():
        if (inv.status or "") in ("Draft", "Paid", "Cancelled", "Void"):
            continue
        if money(inv.due) > 0 and ageing_bucket(inv.due_date, today)[0] != "Not due":
            overdue_in += money(inv.due)
    if overdue_in > 0:
        items.append({
            "kind": "receivables", "severity": "money", "value": money(overdue_in),
            "count": 0, "view": "money-view",
            "title": "Owed to us, past due",
            "detail": "%s the customer should already have paid." % inr(overdue_in),
        })

    held = money(sum(b.retention_amount or 0 for b in db.query(
        models.DBRABill).filter(
            models.DBRABill.client_id == client_id,
            models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all()))
    finished = {j.id for j in jobs.values()
                if (j.status or "").lower() == JOB_FINISHED}
    if held > 0 and finished:
        on_finished = money(sum(b.retention_amount or 0 for b in db.query(
            models.DBRABill).filter(
                models.DBRABill.client_id == client_id,
                models.DBRABill.job_id.in_(list(finished)),
                models.DBRABill.status.in_(("CERTIFIED", "PAID"))).all()))
        gone = released_by_job(db, client_id)
        on_finished = money(on_finished - sum(v for k, v in gone.items() if k in finished))
        if on_finished > 0:
            items.append({
                "kind": "retention", "severity": "money", "value": on_finished,
                "count": len(finished), "view": "money-view",
                "title": "Retention on finished jobs",
                "detail": "%s earned and still held back on work that is done."
                          % inr(on_finished),
            })

    items.extend(attention_elsewhere(db, client_id, jobs, today))

    # Worth money first, then things that are simply wrong, then the rest.
    rank = {"money": 0, "wrong": 1, "action": 2, "notice": 3}
    items.sort(key=lambda i: (rank.get(i["severity"], 9), -i["value"]))
    return items


def setup_progress(db, client_id):
    """How far a new business has got through setting itself up.

    A brand new account used to open on "nothing needs chasing - everything
    measured has been billed", which is true in the way that an empty ledger
    balances. It read as reassurance when the person looking at it had no
    idea where to start. These are the steps in the order a site actually
    takes them, each one done or not, with where to go to do it.
    """
    n = lambda q: q.count()
    jobs = n(db.query(models.DBJob).filter(models.DBJob.client_id == client_id))
    items = n(db.query(models.DBItem).filter(models.DBItem.client_id == client_id))
    wos = db.query(models.DBWorkOrder).filter(
        models.DBWorkOrder.client_id == client_id).all()
    placed = len([w for w in wos if (w.status or "") != "Draft"])
    measured = n(db.query(models.DBMeasurement).filter(
        models.DBMeasurement.client_id == client_id))
    billed = n(db.query(models.DBRABill).filter(
        models.DBRABill.client_id == client_id))
    received = n(db.query(models.DBGoodsReceipt).filter(
        models.DBGoodsReceipt.client_id == client_id,
        models.DBGoodsReceipt.status == "POSTED"))
    diaries = n(db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.client_id == client_id))

    tenders = n(db.query(models.DBEstimate).filter(
        models.DBEstimate.client_id == client_id))
    steps = [
        {"key": "tender", "done": tenders > 0, "view": "estimates-view",
         "title": "Price a tender",
         "hint": "Build each rate up from material, labour and plant, add the margin, and submit. Winning it makes the work order."},
        {"key": "project", "done": jobs > 0, "view": "jobs-view",
         "title": "Set up a project",
         "hint": "The site the work is on and the customer it is for. A won tender opens one for you."},
        {"key": "items", "done": items > 0, "view": "workorders-view",
         "title": "Name what you sell and what you buy",
         "hint": "Deliverables get a code when you first price one on a work order. Materials can be added from a spreadsheet under Store."},
        {"key": "order", "done": len(wos) > 0, "view": "workorders-view",
         "title": "Build a work order",
         "hint": "What was sold, line by line, with a rate against each."},
        {"key": "placed", "done": placed > 0, "view": "workorders-view",
         "title": "Place it",
         "hint": "Placing commits the prices. Until then it cannot be measured or billed."},
        {"key": "measured", "done": measured > 0, "view": "measurement-view",
         "title": "Record what has been built",
         "hint": "The measurement book. Bills are drawn from it, not typed."},
        {"key": "billed", "done": billed > 0, "view": "measurement-view",
         "title": "Draw up the first RA bill",
         "hint": "It claims whatever has been measured and not yet claimed."},
        {"key": "received", "done": received > 0, "view": "stores-view",
         "title": "Book a delivery into the store",
         "hint": "Raise a purchase order, then post the receipt when the lorry comes. Stock starts here."},
        {"key": "diary", "done": diaries > 0, "view": "diary-view",
         "title": "Keep the site diary",
         "hint": "Who turned up, what got built, what stopped it. Labour cost comes from here."},
    ]
    done = len([s for s in steps if s["done"]])
    return {"steps": steps, "done": done, "of": len(steps),
            "complete": done == len(steps),
            "next": next((s for s in steps if not s["done"]), None)}


def attention_payload(db, client_id):
    items = attention_items(db, client_id)
    return {
        "items": items,
        "setup": setup_progress(db, client_id),
        "summary": {
            "items": len(items),
            "money_at_stake": money(sum(i["value"] for i in items
                                        if i["severity"] == "money")),
            "needs_a_decision": len([i for i in items
                                     if i["severity"] == "action"]),
            "looks_wrong": len([i for i in items if i["severity"] == "wrong"]),
        },
    }


# PROJECT SCHEDULE: PLANNED AGAINST ACTUAL
#
# Each activity has its planned dates and, where it is a work order line, its
# progress read from the measurement book - on any date, because every entry
# in the book is dated. Where it is not, progress is reported and dated too.
# So the S-curve for any week in the past is what was true that week, and a
# late activity pushes its successors out by exactly how late it is.
def _d(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def planned_percent(a, on):
    """Linear across the planned span; a milestone is all or nothing."""
    s, f = _d(a.planned_start), _d(a.planned_finish)
    if not s or not f:
        return 0.0
    if on < s:
        return 0.0
    if on >= f:
        return 100.0
    if a.is_milestone:
        return 0.0
    span = (f - s).days or 1
    return round((on - s).days / span * 100.0, 1)


class ScheduleContext:
    """Everything the progress of a job's activities is read from, loaded once."""

    def __init__(self, db, client_id, job_id):
        self.acts = db.query(models.DBScheduleActivity).filter(
            models.DBScheduleActivity.client_id == client_id,
            models.DBScheduleActivity.job_id == job_id).order_by(
                models.DBScheduleActivity.display_order, models.DBScheduleActivity.id).all()
        line_ids = [a.work_order_line_id for a in self.acts if a.work_order_line_id]
        self.ordered, self.measures = {}, {}
        if line_ids:
            for l in db.query(models.DBWorkOrderLine).filter(
                    models.DBWorkOrderLine.id.in_(line_ids)).all():
                self.ordered[l.id] = l.qty or 0
            for m in db.query(models.DBMeasurement).filter(
                    models.DBMeasurement.line_id.in_(line_ids)).all():
                self.measures.setdefault(m.line_id, []).append((m.measured_on or "", m.quantity or 0))
        self.reports = {}
        ids = [a.id for a in self.acts]
        if ids:
            for p in db.query(models.DBScheduleProgress).filter(
                    models.DBScheduleProgress.activity_id.in_(ids)).order_by(
                        models.DBScheduleProgress.reported_on, models.DBScheduleProgress.id).all():
                self.reports.setdefault(p.activity_id, []).append((p.reported_on or "", p.percent or 0))

    def actual(self, a, on):
        """Done, as a percentage, on a given date."""
        iso = on.isoformat()
        if a.work_order_line_id and self.ordered.get(a.work_order_line_id):
            done = sum(q for d, q in self.measures.get(a.work_order_line_id, []) if d <= iso)
            pct = min(100.0, max(0.0, done / self.ordered[a.work_order_line_id] * 100.0))
        else:
            pct = 0.0
            for d, p in self.reports.get(a.id, []):
                if d <= iso:
                    pct = p
        if a.actual_finish and a.actual_finish <= iso:
            pct = 100.0
        return round(pct, 1)


def schedule_view(db, client_id, job):
    """The activities with their planned and actual progress, the forecast
    that follows from both, and the curve."""
    ctx = ScheduleContext(db, client_id, job.id)
    today = date.today()
    by_id = {a.id: a for a in ctx.acts}
    rows, forecast_finish = [], {}

    def forecast(a):
        """When it will finish: late predecessors push it; progress so far
        tells how fast it is going once it has started."""
        if a.id in forecast_finish:
            return forecast_finish[a.id]
        s, f = _d(a.planned_start), _d(a.planned_finish)
        if not s or not f:
            forecast_finish[a.id] = None
            return None
        dur = (f - s).days
        pred = by_id.get(a.depends_on_id)
        start = s
        if pred and pred.id != a.id:
            pf = forecast(pred)
            if pf and pf >= start:
                start = pf + timedelta(days=1)
        done = ctx.actual(a, today)
        if done >= 100:
            fin = _d(a.actual_finish) or min(today, f)
        elif done > 0 and _d(a.actual_start):
            elapsed = max(1, (today - _d(a.actual_start)).days)
            fin = today + timedelta(days=round(elapsed * (100 - done) / done))
            fin = max(fin, start + timedelta(days=dur)) if start > today else fin
        else:
            begin = max(start, today) if start <= today and done == 0 else start
            fin = begin + timedelta(days=dur)
        forecast_finish[a.id] = fin
        return fin

    total_weight = sum(a.weight or 0 for a in ctx.acts) or float(len(ctx.acts) or 1)
    for a in ctx.acts:
        w = (a.weight or 0) if any(x.weight for x in ctx.acts) else 1.0
        plan = planned_percent(a, today)
        done = ctx.actual(a, today)
        fin = forecast(a)
        pf = _d(a.planned_finish)
        slip = (fin - pf).days if fin and pf else 0
        state = ("done" if done >= 100 else
                 "late" if pf and today > pf else
                 "behind" if plan - done > 10 else
                 "not started" if done == 0 and plan == 0 else "on track")
        pred = by_id.get(a.depends_on_id)
        rows.append({
            "id": a.id, "code": a.code or "", "name": a.name or "",
            "planned_start": a.planned_start or "", "planned_finish": a.planned_finish or "",
            "actual_start": a.actual_start or "", "actual_finish": a.actual_finish or "",
            "weight": money(a.weight), "share_percent": round(w / total_weight * 100, 1),
            "depends_on_id": a.depends_on_id, "depends_on": pred.code or pred.name if pred else "",
            "work_order_line_id": a.work_order_line_id, "is_milestone": bool(a.is_milestone),
            "progress_from": "measurement book" if a.work_order_line_id else "reported",
            "planned_percent": plan, "actual_percent": done,
            "forecast_finish": fin.isoformat() if fin else "", "slip_days": slip, "state": state})

    def overall(on):
        if not ctx.acts:
            return 0.0, 0.0
        weights = [(a.weight or 0) if any(x.weight for x in ctx.acts) else 1.0 for a in ctx.acts]
        tw = sum(weights) or 1.0
        p = sum(w * planned_percent(a, on) for a, w in zip(ctx.acts, weights)) / tw
        d_ = sum(w * ctx.actual(a, on) for a, w in zip(ctx.acts, weights)) / tw
        return round(p, 1), round(d_, 1)

    starts = [_d(a.planned_start) for a in ctx.acts if _d(a.planned_start)]
    finishes = [_d(a.planned_finish) for a in ctx.acts if _d(a.planned_finish)]
    curve = []
    if starts and finishes:
        cur, end = min(starts), max(max(finishes), today)
        while cur <= end + timedelta(days=6):
            p, d_ = overall(cur)
            curve.append({"week": cur.isoformat(), "planned": p,
                          "actual": d_ if cur <= today else None})
            cur += timedelta(days=7)
    plan_now, done_now = overall(today)
    project_finish = max([f for f in forecast_finish.values() if f] or [None]) if forecast_finish else None
    planned_end = max(finishes) if finishes else None
    return {
        "job": {"id": job.id, "number": job.number, "name": job.name},
        "activities": rows, "curve": curve,
        "summary": {
            "activities": len(rows), "planned_percent": plan_now, "actual_percent": done_now,
            "variance": round(done_now - plan_now, 1),
            "late": len([r for r in rows if r["state"] == "late"]),
            "behind": len([r for r in rows if r["state"] == "behind"]),
            "done": len([r for r in rows if r["state"] == "done"]),
            "planned_finish": planned_end.isoformat() if planned_end else "",
            "forecast_finish": project_finish.isoformat() if project_finish else "",
            "slip_days": (project_finish - planned_end).days if project_finish and planned_end else 0}}


def _apply_activity(db, client_id, job, a, body):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "What is the activity?")
    s, f = _d(body.planned_start), _d(body.planned_finish)
    if not s or not f:
        raise HTTPException(400, "An activity needs its planned start and finish.")
    if f < s:
        raise HTTPException(400, "It cannot finish before it starts.")
    if body.depends_on_id:
        pred = db.query(models.DBScheduleActivity).filter(
            models.DBScheduleActivity.id == body.depends_on_id,
            models.DBScheduleActivity.job_id == job.id).first()
        if not pred:
            raise HTTPException(400, "It can only follow an activity on the same project.")
        # Refuse a loop: A after B after A would never start.
        seen, cur = {a.id}, pred
        while cur is not None:
            if cur.id in seen:
                raise HTTPException(400, "That would make the activities wait on each other for ever.")
            seen.add(cur.id)
            cur = db.query(models.DBScheduleActivity).filter(
                models.DBScheduleActivity.id == cur.depends_on_id).first() if cur.depends_on_id else None
    if body.work_order_line_id:
        line = db.query(models.DBWorkOrderLine).join(
            models.DBWorkOrder, models.DBWorkOrder.id == models.DBWorkOrderLine.work_order_id).filter(
            models.DBWorkOrderLine.id == body.work_order_line_id,
            models.DBWorkOrder.client_id == client_id, models.DBWorkOrder.job_id == job.id).first()
        if not line:
            raise HTTPException(400, "That work order line is not on this project.")
    a.name, a.code = name, (body.code or "").strip()
    a.planned_start, a.planned_finish = s.isoformat(), f.isoformat()
    a.weight = max(0.0, float(body.weight or 0))
    a.depends_on_id = body.depends_on_id or None
    a.work_order_line_id = body.work_order_line_id or None
    a.is_milestone = bool(body.is_milestone)
    a.actual_start = (body.actual_start or "").strip()
    a.actual_finish = (body.actual_finish or "").strip()


def attention_elsewhere(db, client_id, jobs, today):
    items = []

    # --- certified RA bills not yet paid in full ------------------------
    settled = settled_amounts(db, client_id)
    owed, bills, oldest = 0.0, 0, 0
    for r in db.query(models.DBRABill).filter(
            models.DBRABill.client_id == client_id,
            models.DBRABill.status == "CERTIFIED").all():
        left = money((r.net_payable or 0) - settled.get(("ra_bill", r.id), 0.0))
        if left <= 0:
            continue
        # Client orders carry no payment term; thirty days from the signature
        # is what the standard conditions allow, and a list that flags a bill
        # certified this morning is a list nobody reads.
        bucket, days = ageing_bucket(r.certified_at, today)
        if days is not None and days <= RA_CREDIT_DAYS:
            continue
        owed = money(owed + left)
        bills += 1
        oldest = max(oldest, days or 0)
    if owed > 0:
        items.append({
            "kind": "ra_receivable", "severity": "money", "value": owed,
            "count": bills, "view": "ledger-view",
            "title": "Certified and not paid",
            "detail": "%s on %d RA bill%s certified more than %d days ago; the "
                      "oldest has waited %d days." % (inr(owed), bills,
                                                     "" if bills == 1 else "s",
                                                     RA_CREDIT_DAYS, oldest),
        })

    # --- earnest money left with the client ------------------------------
    stuck, stuck_n = 0.0, 0
    bids_due = []
    for l in db.query(models.DBLead).filter(models.DBLead.client_id == client_id).all():
        sync_lead_from_estimate(db, l)
        if (l.emd_amount or 0) > 0 and l.emd_paid_on and not l.emd_returned_on \
                and l.status in ("WON", "LOST", "DROPPED"):
            stuck = money(stuck + l.emd_amount)
            stuck_n += 1
        if l.status in ("NEW", "QUALIFIED", "ESTIMATING"):
            left = _days_until(l.bid_due_on)
            if left is not None and 0 <= left <= 7:
                bids_due.append((left, l))
    if stuck > 0:
        items.append({
            "kind": "emd", "severity": "money", "value": stuck, "count": stuck_n,
            "view": "leads-view",
            "title": "Earnest money not back",
            "detail": "%s of EMD on %d tender%s already decided. Ask for it; "
                      "nobody sends it unasked." % (inr(stuck), stuck_n,
                                                   "" if stuck_n == 1 else "s"),
        })
    if bids_due:
        bids_due.sort(key=lambda x: x[0])
        first_left, first = bids_due[0]
        items.append({
            "kind": "bids_due", "severity": "action", "value": 0.0,
            "count": len(bids_due), "view": "leads-view",
            "title": "Bids due this week",
            "detail": "%d tender%s to submit; %s is due %s." % (
                len(bids_due), "" if len(bids_due) == 1 else "s",
                first.title or first.number,
                "today" if first_left == 0 else "in %d day%s" % (first_left, "" if first_left == 1 else "s")),
        })

    # --- the programme ---------------------------------------------------
    late_acts, slipped = 0, []
    with_plan = {j for (j,) in db.query(models.DBScheduleActivity.job_id).filter(
        models.DBScheduleActivity.client_id == client_id).distinct().all()}
    for job_id in with_plan:
        job = jobs.get(job_id)
        if not job or (job.status or "") in (JOB_FINISHED, "cancelled"):
            continue
        s = schedule_view(db, client_id, job)["summary"]
        late_acts += s["late"]
        if s["slip_days"] > 0:
            slipped.append((s["slip_days"], job))
    if late_acts or slipped:
        slipped.sort(key=lambda x: -x[0])
        worst = ("; %s finishes %d days after plan" % (slipped[0][1].name, slipped[0][0])
                 if slipped else "")
        items.append({
            "kind": "programme", "severity": "wrong" if slipped else "action", "value": 0.0,
            "count": late_acts, "view": "schedule-view",
            "title": "The programme is slipping",
            "detail": "%d activit%s past their planned finish%s." % (
                late_acts, "y" if late_acts == 1 else "ies", worst),
        })

    # --- plant -----------------------------------------------------------
    due = [a for a in db.query(models.DBAsset).filter(
        models.DBAsset.client_id == client_id,
        models.DBAsset.status != "Disposed").all() if asset_service_state(a)["due"]]
    if due:
        items.append({
            "kind": "plant", "severity": "action", "value": 0.0, "count": len(due),
            "view": "equipment-view",
            "title": "Plant past its service or papers",
            "detail": "%s%s. A machine that breaks on site stops the contractor with it." % (
                ", ".join(a.name or a.code for a in due[:3]),
                " and %d more" % (len(due) - 3) if len(due) > 3 else ""),
        })

    # --- quality: cubes to crush, non-conformances past their date --------
    try:
        cubes = list_cubes_for(db, client_id)
        due = [d for c in cubes for d in c["due"] if d["overdue"] or d["today"]]
        below = [c for c in cubes if c["status"] == "below grade"]
        if due:
            items.append({"kind": "cubes_due", "severity": "action", "value": 0.0, "count": len(due),
                          "view": "quality-view", "title": "Cubes to crush",
                          "detail": "%d cube test%s due or overdue. A result nobody took is a pour "
                                    "nobody can vouch for." % (len(due), "" if len(due) == 1 else "s")})
        if below:
            items.append({"kind": "cubes_below", "severity": "wrong", "value": 0.0, "count": len(below),
                          "view": "quality-view", "title": "Concrete below grade",
                          "detail": ", ".join("%s %s" % (c["number"], c["location"]) for c in below[:3])})
        late = db.query(models.DBNcr).filter(models.DBNcr.client_id == client_id,
                                             models.DBNcr.status == "OPEN",
                                             models.DBNcr.target_date != "",
                                             models.DBNcr.target_date < today.isoformat()).count()
        if late:
            items.append({"kind": "ncr_overdue", "severity": "action", "value": 0.0, "count": late,
                          "view": "quality-view", "title": "Non-conformances past their date",
                          "detail": "%d NCR%s still open after the date set to put it right."
                                    % (late, "" if late == 1 else "s")})
    except Exception as exc:
        logger.error("Quality items failed: %s", exc)

    # --- safety: permits run out and still open, injuries not closed -----
    stale = db.query(models.DBWorkPermit).filter(
        models.DBWorkPermit.client_id == client_id, models.DBWorkPermit.status == "ACTIVE",
        models.DBWorkPermit.valid_to != "",
        models.DBWorkPermit.valid_to < datetime.now().strftime("%Y-%m-%d %H:%M")).count()
    if stale:
        items.append({"kind": "permits_expired", "severity": "wrong", "value": 0.0, "count": stale,
                      "view": "safety-view", "title": "Permits run out, still open",
                      "detail": "%d permit%s to work past their time and not closed. Either the work "
                                "stopped and nobody closed it, or it is going on without a permit."
                                % (stale, "" if stale == 1 else "s")})
    serious = db.query(models.DBSafetyIncident).filter(
        models.DBSafetyIncident.client_id == client_id, models.DBSafetyIncident.status == "OPEN",
        models.DBSafetyIncident.kind.in_(SERIOUS_KINDS)).count()
    if serious:
        items.append({"kind": "incidents_open", "severity": "wrong", "value": 0.0, "count": serious,
                      "view": "safety-view", "title": "Serious incidents not closed",
                      "detail": "%d lost-time injur%s or dangerous occurrence%s without a root cause "
                                "and a fix on record." % (serious, "y" if serious == 1 else "ies",
                                                          "" if serious == 1 else "s")})

    # --- goods on the road without an e-way bill --------------------------
    covered = {r for (r,) in db.query(models.DBEwayBill.source_ref).filter(
        models.DBEwayBill.client_id == client_id,
        models.DBEwayBill.status != "CANCELLED").all() if r}
    moved = {}
    for m in db.query(models.DBStockMovement).filter(
            models.DBStockMovement.client_id == client_id,
            models.DBStockMovement.kind == "TRANSFER_OUT").all():
        moved[m.source_ref] = money(moved.get(m.source_ref, 0.0) - (m.value or 0))
    bare = [ref for ref, v in moved.items() if v > EWAY_THRESHOLD and ref not in covered]
    if bare:
        items.append({
            "kind": "eway", "severity": "wrong", "value": 0.0, "count": len(bare),
            "view": "eway-view",
            "title": "Moved without an e-way bill",
            "detail": "%s: over fifty thousand rupees of goods on the road with no "
                      "e-way bill recorded. A lorry stopped without one is fined." % ", ".join(sorted(bare)[:4]),
        })

    # --- enquiries that will not make a comparison ------------------------
    thin = []
    for r in db.query(models.DBRfq).filter(models.DBRfq.client_id == client_id,
                                           models.DBRfq.status == "OPEN").all():
        quotes = db.query(models.DBRfqQuote).filter(models.DBRfqQuote.rfq_id == r.id).count()
        left = _days_until(r.needed_by)
        if quotes < 3 and (left is None or left <= 7):
            thin.append(r)
    if thin:
        items.append({
            "kind": "rfq", "severity": "notice", "value": 0.0, "count": len(thin),
            "view": "rfq-view",
            "title": "Enquiries short of three quotes",
            "detail": "%d enquir%s with fewer than three prices in. One price "
                      "is not a comparison." % (len(thin), "y" if len(thin) == 1 else "ies"),
        })
    items.extend(release_attention(db, client_id, today))
    items.extend(fixed_asset_attention(db, client_id))
    return items


def drawing_dict(db, d, detail=False):
    revs = db.query(models.DBDrawingRevision).filter(
        models.DBDrawingRevision.drawing_id == d.id).order_by(models.DBDrawingRevision.id.desc()).all()
    cur = revs[0] if revs else None
    out = {"id": d.id, "job_id": d.job_id, "number": d.number or "", "title": d.title or "",
           "discipline": d.discipline or "", "current_revision": d.current_revision or "",
           "status": d.status or "", "revisions": len(revs),
           "current_file_id": cur.file_id if cur else None,
           "received_on": cur.received_on if cur else "",
           "good_for_construction": (d.status or "") == "Good for construction"}
    if detail:
        names = {f.id: f.name for f in db.query(models.DBFile.id, models.DBFile.name).filter(
            models.DBFile.id.in_([r.file_id for r in revs if r.file_id] or [0])).all()}
        out["history"] = [{"id": r.id, "revision": r.revision, "status": r.status,
                           "received_on": r.received_on or "", "received_from": r.received_from or "",
                           "remarks": r.remarks or "", "file_id": r.file_id,
                           "file_name": names.get(r.file_id, ""),
                           "recorded_by_name": r.recorded_by_name or "",
                           "current": cur is not None and r.id == cur.id} for r in revs]
    return out


def parse_position(text):
    """A position from how people have one: "17.4239, 78.3413", or a Google
    Maps link with @17.4239,78.3413 or ?q=17.4239,78.3413 in it."""
    m = re.search(r"(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})", text or "")
    if not m:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def list_cubes_for(db, client_id):
    return [cube_dict(db, s) for s in db.query(models.DBCubeSet).filter(
        models.DBCubeSet.client_id == client_id).all()]


def fixed_asset_attention(db, client_id):
    have = {b.asset_id for b in db.query(models.DBAssetBook).filter(
        models.DBAssetBook.client_id == client_id).all()}
    bare = [a for a in db.query(models.DBAsset).filter(
        models.DBAsset.client_id == client_id, models.DBAsset.status != "Disposed").all()
        if (a.ownership or "Owned") == "Owned" and a.id not in have and (a.purchase_value or 0) > 0]
    if not bare:
        return []
    return [{"kind": "assets_unbooked", "severity": "notice", "value": 0.0, "count": len(bare),
             "view": "fixedassets-view", "title": "Owned assets with no depreciation",
             "detail": "%d owned asset%s carried at cost for ever. Set up the book so the "
                       "register shows what %s worth." % (len(bare), "" if len(bare) == 1 else "s",
                                                          "it is" if len(bare) == 1 else "they are")}]


# Names this module only needs once it is running. They come from modules that in turn need this one,
# so they are imported last, after everything above has been defined.
from app.services.crm import next_customer_code, settled_amounts, sync_lead_from_estimate
from app.services.hr import employee_name
from app.services.money import material_recovered_by_job
from app.services.quality import cube_dict
from app.services.subcontract_billing import _live_releases, release_attention, released_by_job
