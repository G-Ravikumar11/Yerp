"""The projects endpoints."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func as sqlfunc, or_
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.constants.common import DRAWING_STATUSES
from app.constants.crm import OPEN_INVOICE_STATUSES
from app.constants.projects import DRAWING_DISCIPLINES, JOB_CLOSED_STATUSES, JOB_FINISHED, WEATHER
from app.core.audit import log_audit
from app.core.auth import get_client_user, owned_or_404, require_erp_read, require_items_access, wo_actor
from app.core.cache import cached_read
from app.core.currency import DEFAULT_CURRENCY, money, totals_by_currency
from app.core.gst import GST_STATES
from app.core.queries import prime
from app.core.serials import allocate_job_number
from app.core.sheets import sheet_response
from app.routers.files import list_files
from app.schemas.projects import (
    ActivityIn,
    DiaryIn,
    DrawingIn,
    FromWorkOrderIn,
    JobIn,
    JobStateIn,
    ProgressIn,
    SiteLocationIn,
)
from app.services.assets import asset_costs, asset_dict
from app.services.crm import invoice_overdue_days, quote_display_status
from app.services.employee_portal import bill_to_employee_dict
from app.services.procurement import purchase_order_to_dict
from app.services.projects import (
    _apply_activity,
    _d,
    _hit,
    _replace_diary_lines,
    attention_payload,
    clamp_percent,
    cost_jobs,
    customer_for_name,
    diary_dict,
    diary_or_404,
    drawing_dict,
    invoice_total,
    job_or_404,
    job_to_dict,
    parse_position,
    preload_pnl,
    project_pnl,
    schedule_view,
)
from app.services.subcontract_orders import work_order_or_404
from app.validators.common import validate_job_money, validate_job_status


router = APIRouter()


@router.get("/api/dashboard-summary")
def get_dashboard_summary(request: Request, db: Session = Depends(get_db)):

    from datetime import datetime, timedelta

    client = require_items_access(request, db, "reports.view")
    all_invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()

    today = datetime.now().date()
    invoices_owed = sum(inv.due or 0 for inv in all_invoices if inv.status in OPEN_INVOICE_STATUSES)
    total_revenue = sum(inv.paid or 0 for inv in all_invoices if inv.status != "Draft")
    total_invoiced = sum((inv.paid or 0) + (inv.due or 0) for inv in all_invoices if inv.status != "Draft")
    paid_count = sum(1 for inv in all_invoices if inv.status == "Paid")
    pending_count = sum(1 for inv in all_invoices if inv.status in OPEN_INVOICE_STATUSES)
    draft_count = sum(1 for inv in all_invoices if inv.status == "Draft")
    overdue = [inv for inv in all_invoices if invoice_overdue_days(inv, today) > 0]
    overdue_amount = sum(inv.due or 0 for inv in overdue)

    months = []
    now = datetime.now()
    for i in range(5, -1, -1):
        d = now - timedelta(days=30 * i)
        months.append(d.strftime("%b %Y"))

    # Charting several currencies on one axis says nothing, so the chart is
    # the base currency and the label says so.
    base_currency = (client.currency or DEFAULT_CURRENCY).upper()

    def in_base(inv):
        return (inv.currency or base_currency).upper() == base_currency

    money_in = [0.0] * 6
    money_out = [0.0] * 6

    for inv in all_invoices:
        if not inv.issue_date or not in_base(inv):
            continue
        try:
            inv_date = datetime.strptime(inv.issue_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        for i in range(6):
            d = now - timedelta(days=30 * (5 - i))
            month_start = d.replace(day=1)
            next_month = (month_start + timedelta(days=32)).replace(day=1)
            if month_start <= inv_date < next_month:
                money_in[i] += inv.paid or 0
                if inv.status in OPEN_INVOICE_STATUSES:
                    money_out[i] += inv.due or 0
                break

    short_months = [datetime.strptime(m, "%b %Y").strftime("%b") for m in months]

    def split(rows, amount):
        return totals_by_currency(
            [{"currency": i.currency, "total": amount(i)} for i in rows],
            fallback=base_currency)

    open_invoices = [i for i in all_invoices if i.status in OPEN_INVOICE_STATUSES]
    issued = [i for i in all_invoices if i.status != "Draft"]

    return {
        "summary": {
            "total_invoiced": round(total_invoiced, 2),
            "total_revenue": round(total_revenue, 2),
            "invoices_owed": round(invoices_owed, 2),
            "paid_count": paid_count,
            "pending_count": pending_count,
            "draft_count": draft_count,
            "overdue_count": len(overdue),
            "overdue_amount": round(overdue_amount, 2),
            "total_count": len(all_invoices),
            # The figures the cards actually show. A single total across
            # currencies would be a number nobody can act on.
            "by_currency": {
                "total_invoiced": split(issued, lambda i: (i.paid or 0) + (i.due or 0)),
                "total_revenue": split(issued, lambda i: i.paid or 0),
                "invoices_owed": split(open_invoices, lambda i: i.due or 0),
                "overdue_amount": split(overdue, lambda i: i.due or 0),
            },
        },
        "base_currency": base_currency,
        "currencies_used": sorted({(i.currency or base_currency).upper()
                                   for i in all_invoices}),
        "cash_flow": {
            "money_in": [round(x, 2) for x in money_in],
            "money_out": [round(x, 2) for x in money_out],
            "months": short_months,
            "currency": base_currency,
        }
    }


@router.get("/api/jobs")
def list_jobs(request: Request, status: str = "", q: str = "", open_only: bool = False, costing: bool = True,
              db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("reports.view", "bills.view_all", "workorders.manage"))
    query = db.query(models.DBJob).filter(models.DBJob.client_id == client.id)
    if status:
        query = query.filter(models.DBJob.status == validate_job_status(status))
    if open_only:
        query = query.filter(~models.DBJob.status.in_(JOB_CLOSED_STATUSES))
    if q:
        query = query.filter(or_(
            models.DBJob.name.ilike(f"%{q}%"),
            models.DBJob.number.ilike(f"%{q}%"),
            models.DBJob.customer_name.ilike(f"%{q}%"),
            models.DBJob.site_address.ilike(f"%{q}%"),
        ))
    jobs = query.order_by(models.DBJob.id.desc()).all()
    prime(db, models.DBEmployee, [j.manager_id for j in jobs])
    if costing:
        db.info["by_job"] = {}      # each table read once for every project, not once per project
    return {"jobs": [job_to_dict(db, j, costing=costing) for j in jobs]}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    """The job, its money, and everything filed against it."""
    client = require_items_access(request, db, ("reports.view", "bills.view_all", "workorders.manage"))
    job = job_or_404(db, client.id, job_id)
    row = job_to_dict(db, job, costing=True)

    row["invoices"] = [
        {"id": i.id, "number": i.number, "to_contact": i.to_contact,
         "issue_date": i.issue_date, "status": i.status,
         "total": invoice_total(i), "paid": i.paid or 0.0, "due": i.due or 0.0}
        for i in db.query(models.DBInvoice).filter(
            models.DBInvoice.client_id == client.id,
            models.DBInvoice.job_id == job.id).order_by(models.DBInvoice.id.desc()).all()
    ]
    row["bills"] = [
        bill_to_employee_dict(db, b)
        for b in db.query(models.DBBill).filter(
            models.DBBill.client_id == client.id,
            models.DBBill.job_id == job.id).order_by(models.DBBill.id.desc()).all()
    ]
    row["purchase_orders"] = [
        purchase_order_to_dict(db, o)
        for o in db.query(models.DBPurchaseOrder).filter(
            models.DBPurchaseOrder.client_id == client.id,
            models.DBPurchaseOrder.job_id == job.id).order_by(
                models.DBPurchaseOrder.id.desc()).all()
    ]
    row["quotes"] = [
        {"id": qu.id, "number": qu.number, "status": qu.status,
         "total": qu.total or 0.0, "issue_date": qu.issue_date}
        for qu in db.query(models.DBQuote).filter(
            models.DBQuote.client_id == client.id,
            models.DBQuote.job_id == job.id).order_by(models.DBQuote.id.desc()).all()
    ]
    return row


@router.post("/api/jobs")
def create_job(body: JobIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "workorders.manage")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the job a name")
    if len(name) > 160:
        raise HTTPException(status_code=400, detail="Job name must be 160 characters or fewer")

    customer_name = (body.customer_name or "").strip()
    contact_id = None
    if body.contact_id:
        contact = db.query(models.DBContact).filter(
            models.DBContact.id == body.contact_id,
            models.DBContact.client_id == client.id).first()
        if not contact:
            raise HTTPException(status_code=400, detail="Unknown customer")
        contact_id = contact.id
        customer_name = customer_name or contact.name
    elif customer_name:
        # Named but not picked. The jobs screen only ever asks for a name, so
        # without this a project raised there belongs to a customer the
        # customer record never hears about - and the same business ends up
        # on both sides of the system with nothing joining them.
        contact_id = customer_for_name(db, client.id, customer_name).id

    job = models.DBJob(
        client_id=client.id,
        number=allocate_job_number(db, client.id),
        name=name,
        contact_id=contact_id,
        customer_name=customer_name,
        site_address=(body.site_address or "").strip(),
        description=(body.description or "").strip(),
        status=validate_job_status(body.status),
        start_date=body.start_date or "",
        target_end_date=body.target_end_date or "",
        quoted_value=validate_job_money("Quoted value", body.quoted_value),
        budget=validate_job_money("Budget", body.budget),
        retention_percent=clamp_percent(body.retention_percent),
        currency=(body.currency or client.currency or "").upper(),
        reference=(body.reference or "").strip(),
        manager_id=owned_or_404(db, models.DBEmployee, client.id, body.manager_id, "Project manager"),
        state_code=(body.state_code or "").strip(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    log_audit(db, client.id, "job_created", "job", job.id, job.number,
              f"{job.name} for {job.customer_name or 'no customer'}", request)
    db.commit()
    return job_to_dict(db, job, costing=True)


@router.put("/api/jobs/{job_id}")
def update_job(job_id: int, body: JobIn, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "workorders.manage")
    job = job_or_404(db, client.id, job_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the job a name")

    was_open = job.status not in JOB_CLOSED_STATUSES
    job.name = name
    job.customer_name = (body.customer_name or "").strip()
    # The jobs screen sends a name, never an id; taking the missing id as
    # "no customer" cut every edited project off its client record - and
    # with it the GSTIN the bill and the e-invoice need. The link follows
    # the name unless an id is actually picked.
    if body.contact_id:
        picked = db.query(models.DBContact).filter(
            models.DBContact.id == body.contact_id,
            models.DBContact.client_id == client.id).first()
        if not picked:
            raise HTTPException(status_code=400, detail="Unknown customer")
        job.contact_id = picked.id
        job.customer_name = job.customer_name or picked.name
    else:
        job.contact_id = (customer_for_name(db, client.id, job.customer_name).id
                          if job.customer_name else None)
    job.site_address = (body.site_address or "").strip()
    job.description = (body.description or "").strip()
    job.status = validate_job_status(body.status)
    if getattr(body, "state_code", None) is not None:
        job.state_code = (body.state_code or "").strip()
    job.start_date = body.start_date or ""
    job.target_end_date = body.target_end_date or ""
    job.quoted_value = validate_job_money("Quoted value", body.quoted_value)
    job.budget = validate_job_money("Budget", body.budget)
    job.retention_percent = clamp_percent(body.retention_percent)
    job.reference = (body.reference or "").strip()
    job.manager_id = owned_or_404(db, models.DBEmployee, client.id, body.manager_id, "Project manager")
    if was_open and job.status == "complete" and not job.completed_at:
        job.completed_at = datetime.now().strftime("%Y-%m-%d")
    log_audit(db, client.id, "job_updated", "job", job.id, job.number, job.status, request)
    db.commit()
    return job_to_dict(db, job, costing=True)


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    """Only while nothing has been filed against it.

    Deleting a job that documents point at would silently detach real money
    from the only thing explaining what it was for. A finished job is marked
    complete, not deleted.
    """
    client = get_client_user(request, db)
    job = job_or_404(db, client.id, job_id)
    attached = []
    for model, label in ((models.DBInvoice, "invoice"), (models.DBBill, "bill"),
                         (models.DBQuote, "quote"), (models.DBPurchaseOrder, "purchase order"),
                         (models.DBAttendance, "timesheet entry")):
        count = db.query(model).filter(
            model.client_id == client.id, model.job_id == job.id).count()
        if count:
            attached.append(f"{count} {label}{'s' if count != 1 else ''}")
    if attached:
        raise HTTPException(
            status_code=409,
            detail=f"This job has {', '.join(attached)} against it. "
                   "Mark it complete instead of deleting it.")
    log_audit(db, client.id, "job_deleted", "job", job.id, job.number, "", request)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.get("/api/jobs-summary")
def jobs_summary(request: Request, db: Session = Depends(get_db)):
    """The board: every live job with what it is making, worst margin first.

    Costed in bulk. Asking job_costing for each job in turn issued roughly
    seven queries per row, so a business with fifty live jobs spent three
    hundred and fifty round trips drawing one screen - and every job added made
    it worse. Everything is read once here and grouped in memory instead.
    """
    client = require_items_access(request, db, ("reports.view", "bills.view_all", "workorders.manage"))
    jobs = db.query(models.DBJob).filter(
        models.DBJob.client_id == client.id,
        ~models.DBJob.status.in_(JOB_CLOSED_STATUSES),
    ).all()
    rows = cost_jobs(db, client.id, jobs)
    rows.sort(key=lambda r: r["costing"]["margin_percent"])
    totals = {
        "invoiced": money(sum(r["costing"]["invoiced"] for r in rows)),
        "cost": money(sum(r["costing"]["total_cost"] for r in rows)),
        "committed": money(sum(r["costing"]["committed"] for r in rows)),
        "profit": money(sum(r["costing"]["profit"] for r in rows)),
    }
    return {
        "jobs": rows,
        "totals": totals,
        "over_budget": [r["number"] for r in rows if r["costing"]["over_budget"]],
    }


@router.get("/api/search")
def global_search(request: Request, q: str = "", limit: int = 8,
                  db: Session = Depends(get_db)):
    """Search everything the tenant owns, on the server.

    The old search ran in the browser over whatever lists happened to be
    loaded, so employees were unfindable until you had opened the Employees
    tab, and quotes and recurring invoices were never searched at all. It also
    matched invoices on fields the API does not return, which meant customer
    names never matched anything.
    """
    client = get_client_user(request, db)
    term = (q or "").strip()
    if len(term) < 2:
        return {"query": term, "results": []}

    like = f"%{term.lower()}%"
    cap = max(1, min(limit, 25))
    results = []

    def matches(*fields):
        return or_(*[sqlfunc.lower(sqlfunc.coalesce(f, "")).like(like) for f in fields])

    for inv in db.query(models.DBInvoice).filter(
        models.DBInvoice.client_id == client.id,
        matches(models.DBInvoice.number, models.DBInvoice.to_contact,
                models.DBInvoice.email, models.DBInvoice.ref, models.DBInvoice.status),
    ).order_by(models.DBInvoice.id.desc()).limit(cap).all():
        results.append(_hit("invoice", f"{inv.number} - {inv.to_contact or 'No customer'}",
                            f"{inv.status or ''}", inv.number, inv.id))

    for q_row in db.query(models.DBQuote).filter(
        models.DBQuote.client_id == client.id,
        matches(models.DBQuote.number, models.DBQuote.to_contact,
                models.DBQuote.email, models.DBQuote.title, models.DBQuote.ref),
    ).order_by(models.DBQuote.id.desc()).limit(cap).all():
        results.append(_hit("quote", f"{q_row.number} - {q_row.to_contact or 'No customer'}",
                            q_row.title or quote_display_status(q_row), q_row.number, q_row.id))

    for c in db.query(models.DBContact).filter(
        models.DBContact.client_id == client.id,
        matches(models.DBContact.name, models.DBContact.email,
                models.DBContact.phone_number),
    ).limit(cap).all():
        results.append(_hit("contact", c.name or c.email or "Unknown",
                            c.email or c.phone_number or "", "", c.id))

    for e in db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id,
        matches(models.DBEmployee.first_name, models.DBEmployee.last_name,
                models.DBEmployee.email, models.DBEmployee.job_title,
                models.DBEmployee.employee_id),
    ).limit(cap).all():
        results.append(_hit("employee", f"{e.first_name} {e.last_name}".strip(),
                            e.job_title or e.email or "", e.employee_id or "", e.id))

    for r in db.query(models.DBRecurringInvoice).filter(
        models.DBRecurringInvoice.client_id == client.id,
        matches(models.DBRecurringInvoice.name, models.DBRecurringInvoice.to_contact,
                models.DBRecurringInvoice.email),
    ).limit(cap).all():
        results.append(_hit("recurring", r.name or r.to_contact or "Recurring",
                            f"every {r.frequency}", "", r.id))

    # Payslips carry an employee_id, not a name, so the name is searched
    # through the employee record rather than a column that does not exist.
    for p, emp in db.query(models.DBPayslip, models.DBEmployee).join(
        models.DBEmployee, models.DBPayslip.employee_id == models.DBEmployee.id
    ).filter(
        models.DBPayslip.client_id == client.id,
        matches(models.DBPayslip.number, models.DBPayslip.status,
                models.DBEmployee.first_name, models.DBEmployee.last_name),
    ).order_by(models.DBPayslip.id.desc()).limit(cap).all():
        who = f"{emp.first_name} {emp.last_name}".strip() or "Unknown"
        results.append(_hit("payslip", f"{who} - {p.number or ''}",
                            p.status or "", p.number or "", p.id))

    return {"query": term, "results": results}


@router.put("/api/jobs/{job_id}/place-of-supply")
def set_job_state(job_id: int, body: JobStateIn, request: Request,
                  db: Session = Depends(get_db)):
    client = require_items_access(request, db, ("accounts.manage", "workorders.manage"))
    job = job_or_404(db, client.id, job_id)
    code = (body.state_code or "").strip()
    if code and code not in GST_STATES:
        raise HTTPException(400, "Not a GST state code: %s" % code)
    job.state_code = code
    db.commit()
    return {"ok": True, "state_code": code, "state": GST_STATES.get(code, "")}


@router.get("/api/diary")
def list_diaries(request: Request, job_id: int = 0, date_from: str = "",
                 date_to: str = "", db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    q = db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.client_id == client.id)
    if job_id:
        q = q.filter(models.DBSiteDiary.job_id == job_id)
    if date_from:
        q = q.filter(models.DBSiteDiary.diary_date >= date_from)
    if date_to:
        q = q.filter(models.DBSiteDiary.diary_date <= date_to)
    rows = [diary_dict(db, d) for d in q.order_by(
        models.DBSiteDiary.diary_date.desc(),
        models.DBSiteDiary.id.desc()).limit(400).all()]
    return {
        "diaries": rows,
        "summary": {
            "days_recorded": len(rows),
            "mandays": money(sum(r["total_mandays"] for r in rows)),
            "labour_cost": money(sum(r["labour_cost"] for r in rows)),
            "plant_cost": money(sum(r["plant_cost"] for r in rows)),
            "days_lost_to_weather": len([r for r in rows if r["lost_to_weather"]]),
            "not_yet_submitted": len([r for r in rows if r["status"] == "DRAFT"]),
        },
    }


@router.post("/api/diary")
def create_diary(body: DiaryIn, request: Request, db: Session = Depends(get_db)):
    client, actor_id, actor_name = wo_actor(request, db, "site.record")
    if not body.job_id:
        raise HTTPException(400, "A diary belongs to a site.")
    job = db.query(models.DBJob).filter(
        models.DBJob.id == body.job_id,
        models.DBJob.client_id == client.id).first()
    if not job:
        raise HTTPException(404, "Project not found")

    on = (body.diary_date or datetime.now().strftime("%Y-%m-%d"))[:10]
    # One diary per site per day. Two records for the same day is how a delay
    # claim gets thrown out, so the second attempt reopens the first rather
    # than quietly creating a rival.
    existing = db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.client_id == client.id,
        models.DBSiteDiary.job_id == job.id,
        models.DBSiteDiary.diary_date == on).first()
    if existing:
        raise HTTPException(
            409, "There is already a diary for %s on %s. Open that one."
                 % (job.name or "this site", on))

    diary = models.DBSiteDiary(
        client_id=client.id, job_id=job.id, work_order_id=body.work_order_id,
        diary_date=on,
        weather=(body.weather if body.weather in WEATHER else "Clear"),
        rain_hours=money(body.rain_hours or 0),
        working_hours=money(body.working_hours if body.working_hours else 8),
        work_done=(body.work_done or "").strip(),
        holdups=(body.holdups or "").strip(),
        instructions=(body.instructions or "").strip(),
        visitors=(body.visitors or "").strip(),
        safety_note=(body.safety_note or "").strip(),
        status="DRAFT", prepared_by=actor_id, prepared_by_name=actor_name)
    db.add(diary)
    db.flush()
    _replace_diary_lines(db, diary, body.labour, body.plant)
    db.commit()
    db.refresh(diary)
    return {"ok": True, "diary": diary_dict(db, diary, detail=True),
            "message": "Diary opened for %s." % on}


@router.get("/api/diary/{diary_id}")
def get_diary(diary_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return diary_dict(db, diary_or_404(db, client.id, diary_id), detail=True)


@router.put("/api/diary/{diary_id}")
def update_diary(diary_id: int, body: DiaryIn, request: Request,
                 db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "site.record")
    diary = diary_or_404(db, client.id, diary_id)
    if (diary.status or "DRAFT") != "DRAFT":
        raise HTTPException(
            409, "This day has been signed off. A diary that can be rewritten "
                 "afterwards is worth nothing in a claim.")
    if body.weather in WEATHER:
        diary.weather = body.weather
    for field in ("rain_hours", "working_hours"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(diary, field, money(val))
    for field in ("work_done", "holdups", "instructions", "visitors",
                  "safety_note"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(diary, field, val.strip())
    if body.work_order_id is not None:
        diary.work_order_id = owned_or_404(db, models.DBWorkOrder, client.id, body.work_order_id, "Work order")
    _replace_diary_lines(db, diary, body.labour, body.plant)
    db.commit()
    db.refresh(diary)
    return {"ok": True, "diary": diary_dict(db, diary, detail=True)}


@router.post("/api/diary/{diary_id}/submit")
def submit_diary(diary_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db, "site.signoff")
    diary = diary_or_404(db, client.id, diary_id)
    if (diary.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "Already signed off.")
    if not (diary.work_done or "").strip():
        raise HTTPException(
            400, "Say what was done. A day with no record of the work is not "
                 "a diary entry.")
    diary.status = "SUBMITTED"
    diary.submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_audit(db, client.id, "diary_submitted", "site_diary", diary.id,
              diary.diary_date or "", actor_name, request)
    db.commit()
    db.refresh(diary)
    return {"ok": True, "diary": diary_dict(db, diary, detail=True),
            "message": "%s signed off." % diary.diary_date}


@router.delete("/api/diary/{diary_id}")
def delete_diary(diary_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db, "site.record")
    diary = diary_or_404(db, client.id, diary_id)
    if (diary.status or "DRAFT") != "DRAFT":
        raise HTTPException(409, "A signed off day cannot be deleted.")
    db.query(models.DBDiaryLabour).filter(
        models.DBDiaryLabour.site_diary_id == diary.id).delete()
    db.query(models.DBDiaryPlant).filter(
        models.DBDiaryPlant.site_diary_id == diary.id).delete()
    db.delete(diary)
    db.commit()
    return {"ok": True, "message": "Draft diary removed."}


@router.get("/api/diary-labour/{job_id}")
def labour_history(job_id: int, request: Request, db: Session = Depends(get_db)):
    """Who has been on this site, by trade, over its whole life.

    The question a project manager asks on a Monday - am I carrying more
    masons than the work needs - and it cannot be answered from one day.
    """
    client = require_erp_read(request, db)
    job = db.query(models.DBJob).filter(
        models.DBJob.id == job_id, models.DBJob.client_id == client.id).first()
    if not job:
        raise HTTPException(404, "Project not found")

    diaries = db.query(models.DBSiteDiary).filter(
        models.DBSiteDiary.client_id == client.id,
        models.DBSiteDiary.job_id == job.id).order_by(
            models.DBSiteDiary.diary_date).all()
    ids = [d.id for d in diaries]
    trades, agencies = {}, {}
    if ids:
        day_of = {d.id: (d.working_hours or 8.0) for d in diaries}
        for l in db.query(models.DBDiaryLabour).filter(
                models.DBDiaryLabour.site_diary_id.in_(ids)).all():
            day = day_of.get(l.site_diary_id, 8.0) or 8.0
            md = (l.headcount or 0) * ((l.hours or day) / day)
            t = trades.setdefault(l.trade or "Unstated",
                                  {"trade": l.trade or "Unstated",
                                   "mandays": 0.0, "cost": 0.0})
            t["mandays"] = money(t["mandays"] + md)
            t["cost"] = money(t["cost"] + (l.amount or 0))
            a = agencies.setdefault(l.agency or "Own",
                                    {"agency": l.agency or "Own",
                                     "mandays": 0.0, "cost": 0.0})
            a["mandays"] = money(a["mandays"] + md)
            a["cost"] = money(a["cost"] + (l.amount or 0))

    daily = [{"diary_date": d.diary_date or "", "mandays": money(d.total_mandays),
              "labour_cost": money(d.labour_cost), "plant_cost": money(d.plant_cost),
              "weather": d.weather or "", "rain_hours": money(d.rain_hours)}
             for d in diaries]
    worked = [d for d in daily if d["mandays"] > 0]
    return {
        "job": {"id": job.id, "number": job.number or "", "name": job.name or ""},
        "by_trade": sorted(trades.values(), key=lambda r: -r["mandays"]),
        "by_agency": sorted(agencies.values(), key=lambda r: -r["mandays"]),
        "daily": daily,
        "summary": {
            "days_recorded": len(daily),
            "days_worked": len(worked),
            "mandays": money(sum(r["mandays"] for r in daily)),
            "labour_cost": money(sum(r["labour_cost"] for r in daily)),
            "plant_cost": money(sum(r["plant_cost"] for r in daily)),
            "average_gang": (round(sum(r["mandays"] for r in worked) / len(worked), 1)
                             if worked else 0.0),
            "rain_hours": money(sum(r["rain_hours"] for r in daily)),
        },
    }


@router.get("/api/diary/{diary_id}/export.xlsx")
def diary_export(diary_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    d = diary_or_404(db, client.id, diary_id)
    row = diary_dict(db, d, detail=True)
    preamble = [
        ("DAILY PROGRESS REPORT", client.company_name or ""),
        ("Site", row["project"], "Date", row["diary_date"]),
        ("Weather", "%s (%s h rain)" % (row["weather"], row["rain_hours"]),
         "Working hours", row["working_hours"]),
        ("Prepared by", row["prepared_by_name"], "Status", row["status"]),
        (),
        ("Work done", row["work_done"]),
        ("Held up by", row["holdups"] or "-"),
        ("Instructions", row["instructions"] or "-"),
        ("Visitors", row["visitors"] or "-"),
        ("Safety", row["safety_note"] or "-"),
        (),
        ("LABOUR",),
    ]
    headers = ("Trade", "Agency", "Number", "Hours", "Rate", "Amount")
    rows = [(l["trade"], l["agency"], l["headcount"], l["hours"], l["rate"],
             l["amount"]) for l in row["labour"]]
    closing = [(), ("Mandays", row["total_mandays"], "", "", "Labour",
                    row["labour_cost"])]
    if row["plant"]:
        closing += [(), ("PLANT",),
                    ("Plant", "Worked", "Idle", "Rate", "Amount", "Remarks")]
        closing += [(p["plant"], p["worked_hours"], p["idle_hours"], p["rate"],
                     p["amount"], p["remarks"]) for p in row["plant"]]
        closing += [("", "", "", "Plant", row["plant_cost"])]
    closing += [(), ("Cost of the day", row["day_cost"])]
    return sheet_response(headers, rows,
                          "dpr_%s.xlsx" % (row["diary_date"] or "day"),
                          preamble=preamble, closing=closing)


@router.get("/api/jobs/{job_id}/pnl")
def job_pnl(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "reports.view")
    job = db.query(models.DBJob).filter(
        models.DBJob.id == job_id, models.DBJob.client_id == client.id).first()
    if not job:
        raise HTTPException(404, "Project not found")
    return project_pnl(db, client.id, job)


@router.get("/api/jobs-pnl")
def portfolio_pnl(request: Request, db: Session = Depends(get_db)):
    """Every live project on one line, worst margin first.

    An owner does not want to open eleven screens to find the one job that is
    losing money, so the one that is losing money is at the top.
    """
    client = require_items_access(request, db, "reports.view")
    rows = []
    pre = preload_pnl(db, client.id)
    for job in db.query(models.DBJob).filter(
            models.DBJob.client_id == client.id).order_by(models.DBJob.id).all():
        p = project_pnl(db, client.id, job, pre=pre)
        rows.append({
            "job_id": job.id, "number": job.number or "", "name": job.name or "",
            "customer_name": job.customer_name or "", "status": job.status or "",
            "order_value": p["value"]["order_value"],
            "revenue": p["earned"]["revenue"],
            "incurred": p["cost"]["incurred"],
            "committed": p["cost"]["committed_not_yet_billed"],
            "margin": p["result"]["margin"],
            "margin_percent": p["result"]["margin_percent"],
            "mandays": p["result"]["mandays"],
            "over_budget": p["result"]["over_budget"],
            "outstanding": p["earned"]["outstanding"],
            "losing": p["result"]["margin"] < 0,
        })
    rows.sort(key=lambda r: r["margin"])
    return {
        "projects": rows,
        "summary": {
            "projects": len(rows),
            "order_value": money(sum(r["order_value"] for r in rows)),
            "revenue": money(sum(r["revenue"] for r in rows)),
            "incurred": money(sum(r["incurred"] for r in rows)),
            "margin": money(sum(r["margin"] for r in rows)),
            "losing_money": len([r for r in rows if r["losing"]]),
            "owed_to_us": money(sum(r["outstanding"] for r in rows)),
        },
    }


@router.get("/api/jobs/{job_id}/pnl.xlsx")
def job_pnl_export(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_items_access(request, db, "reports.view")
    job = db.query(models.DBJob).filter(
        models.DBJob.id == job_id, models.DBJob.client_id == client.id).first()
    if not job:
        raise HTTPException(404, "Project not found")
    p = project_pnl(db, client.id, job)
    e, c, r = p["earned"], p["cost"], p["result"]
    preamble = [
        ("PROJECT PROFIT AND LOSS", client.company_name or ""),
        ("Project", "%s %s" % (job.number or "", job.name or "")),
        ("Client", job.customer_name or "", "Status", job.status or ""),
        (),
    ]
    rows = [
        ("Order value", p["value"]["order_value"]),
        ("Invoiced", e["invoiced"]),
        ("Collected", e["collected"]),
        ("Certified on RA bills", e["certified"]),
        ("Retention held", e["retention_held"]),
        ("Revenue recognised", e["revenue"]),
        ("", ""),
        ("Supplier bills", c["supplier_bills"]),
        ("Material from the store", c["material_from_store"]),
        ("Labour", c["labour"]),
        ("Plant", c["plant"]),
        ("Incurred", c["incurred"]),
        ("Committed, not yet billed", c["committed_not_yet_billed"]),
        ("Forecast cost", c["forecast"]),
        ("", ""),
        ("Margin", r["margin"]),
        ("Margin %", r["margin_percent"]),
        ("Mandays", r["mandays"]),
        ("Cost per manday", r["cost_per_manday"]),
    ]
    return sheet_response(("Item", "Amount"), rows,
                          "pnl_%s.xlsx" % (job.number or "project"),
                          preamble=preamble)


@router.get("/api/attention")
def whats_worth_a_look(request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return cached_read(("attention", client.id), lambda: attention_payload(db, client.id))


@router.get("/api/jobs/{job_id}/equipment")
def job_equipment(job_id: int, request: Request, db: Session = Depends(get_db)):
    """The machines on one site and what they have cost it."""
    client = require_erp_read(request, db)
    job_or_404(db, client.id, job_id)
    costs = asset_costs(db, client.id, job_id)
    jobs = {j.id: j for j in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all()}
    here = {a.id: a for a in db.query(models.DBAsset).filter(
        models.DBAsset.client_id == client.id, models.DBAsset.current_job_id == job_id).all()}
    for aid in costs:
        if aid not in here:
            a = db.query(models.DBAsset).filter(models.DBAsset.id == aid).first()
            if a:
                here[aid] = a
    rows = []
    for a in here.values():
        c = costs.get(a.id, {})
        d = asset_dict(db, a, jobs)
        d.update({"on_site_now": a.current_job_id == job_id, "fuel": money(c.get("fuel", 0)),
                  "hire": money(c.get("hire", 0)), "service_cost": money(c.get("service", 0)),
                  "cost_here": money(c.get("total", 0)), "hours_here": money(c.get("hours", 0)),
                  "idle_here": money(c.get("idle", 0))})
        rows.append(d)
    rows.sort(key=lambda r: -r["cost_here"])
    return {"assets": rows, "total": money(sum(r["cost_here"] for r in rows))}


@router.get("/api/jobs/{job_id}/schedule")
def job_schedule(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    return schedule_view(db, client.id, job_or_404(db, client.id, job_id))


@router.post("/api/jobs/{job_id}/schedule/activities")
def add_activity(job_id: int, body: ActivityIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    n = db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.job_id == job.id).count()
    a = models.DBScheduleActivity(client_id=client.id, job_id=job.id, display_order=n)
    db.add(a)
    db.flush()
    _apply_activity(db, client.id, job, a, body)
    if not a.code:
        a.code = "A%d" % ((n + 1) * 10)
    db.commit()
    return {"ok": True, "schedule": schedule_view(db, client.id, job)}


@router.put("/api/schedule/activities/{activity_id}")
def edit_activity(activity_id: int, body: ActivityIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    a = db.query(models.DBScheduleActivity).filter(
        models.DBScheduleActivity.id == activity_id,
        models.DBScheduleActivity.client_id == client.id).first()
    if not a:
        raise HTTPException(404, "Activity not found")
    job = job_or_404(db, client.id, a.job_id)
    _apply_activity(db, client.id, job, a, body)
    db.commit()
    return {"ok": True, "schedule": schedule_view(db, client.id, job)}


@router.delete("/api/schedule/activities/{activity_id}")
def delete_activity(activity_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    a = db.query(models.DBScheduleActivity).filter(
        models.DBScheduleActivity.id == activity_id,
        models.DBScheduleActivity.client_id == client.id).first()
    if not a:
        raise HTTPException(404, "Activity not found")
    db.query(models.DBScheduleActivity).filter(
        models.DBScheduleActivity.depends_on_id == a.id).update(
            {"depends_on_id": a.depends_on_id}, synchronize_session=False)
    db.query(models.DBScheduleProgress).filter(
        models.DBScheduleProgress.activity_id == a.id).delete()
    job_id = a.job_id
    db.delete(a)
    db.commit()
    return {"ok": True, "schedule": schedule_view(db, client.id, job_or_404(db, client.id, job_id))}


@router.post("/api/schedule/activities/{activity_id}/progress")
def report_progress(activity_id: int, body: ProgressIn, request: Request, db: Session = Depends(get_db)):
    """For an activity the book does not measure. Dated, never overwritten."""
    client, _, actor_name = wo_actor(request, db, "site.record")
    a = db.query(models.DBScheduleActivity).filter(
        models.DBScheduleActivity.id == activity_id,
        models.DBScheduleActivity.client_id == client.id).first()
    if not a:
        raise HTTPException(404, "Activity not found")
    if a.work_order_line_id:
        raise HTTPException(409, "%s takes its progress from the measurement book. "
                                 "Measure the work instead." % (a.code or a.name))
    pct = float(body.percent or 0)
    if pct < 0 or pct > 100:
        raise HTTPException(400, "Progress is a percentage between 0 and 100.")
    on = (body.reported_on or datetime.now().strftime("%Y-%m-%d"))[:10]
    db.add(models.DBScheduleProgress(client_id=client.id, activity_id=a.id, reported_on=on,
                                     percent=pct, note=(body.note or "").strip(), by_name=actor_name))
    if pct > 0 and not a.actual_start:
        a.actual_start = on
    if pct >= 100 and not a.actual_finish:
        a.actual_finish = on
    db.commit()
    return {"ok": True, "schedule": schedule_view(db, client.id, job_or_404(db, client.id, a.job_id))}


@router.post("/api/jobs/{job_id}/schedule/from-work-order/{wo_id}")
def schedule_from_work_order(job_id: int, wo_id: int, body: FromWorkOrderIn, request: Request,
                             db: Session = Depends(get_db)):
    """One activity per line of the order, weighted by what it is worth and
    tied to the book, spread end to end across the span given. A first draft
    to be moved about, not a programme - but its progress is real from the
    first measurement."""
    client, _, _ = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    wo = work_order_or_404(db, client.id, wo_id)
    if wo.job_id != job.id:
        raise HTTPException(400, "%s is not on this project." % wo.number)
    s, f = _d(body.start), _d(body.finish)
    if not s or not f or f <= s:
        raise HTTPException(400, "Give the span the work runs across.")
    lines = db.query(models.DBWorkOrderLine).filter(
        models.DBWorkOrderLine.work_order_id == wo.id).order_by(models.DBWorkOrderLine.id).all()
    have = {a.work_order_line_id for a in db.query(models.DBScheduleActivity).filter(
        models.DBScheduleActivity.job_id == job.id).all()}
    lines = [l for l in lines if l.id not in have]
    if not lines:
        raise HTTPException(409, "Every line of %s is already on the schedule." % wo.number)
    total = sum(l.amount or 0 for l in lines) or 1.0
    span = (f - s).days
    cur, prev = s, None
    n = db.query(models.DBScheduleActivity).filter(models.DBScheduleActivity.job_id == job.id).count()
    for i, l in enumerate(lines):
        share = max(1, round(span * (l.amount or 0) / total))
        fin = min(f, cur + timedelta(days=share - 1)) if i < len(lines) - 1 else f
        a = models.DBScheduleActivity(
            client_id=client.id, job_id=job.id, code="A%d" % ((n + i + 1) * 10),
            name=(l.description or l.item_name or l.fg_code or "").split("\n")[0][:200],
            planned_start=cur.isoformat(), planned_finish=fin.isoformat(),
            weight=money(l.amount), work_order_line_id=l.id, depends_on_id=prev,
            display_order=n + i)
        db.add(a)
        db.flush()
        prev = a.id
        cur = min(f, fin + timedelta(days=1))
    db.commit()
    return {"ok": True, "schedule": schedule_view(db, client.id, job),
            "message": "%d activities drawn from %s." % (len(lines), wo.number)}


@router.get("/api/schedule-overview")
def schedule_overview(request: Request, db: Session = Depends(get_db)):
    """Every live project's planned against actual, worst first."""
    client = require_erp_read(request, db)
    out = []
    planned = {r[0] for r in db.query(models.DBScheduleActivity.job_id).filter(
        models.DBScheduleActivity.client_id == client.id).distinct().all()}
    for job in db.query(models.DBJob).filter(models.DBJob.client_id == client.id).all():
        if (job.status or "") in (JOB_FINISHED, "cancelled"):
            continue
        if job.id not in planned:
            continue
        v = schedule_view(db, client.id, job)
        out.append(dict(v["summary"], job_id=job.id, number=job.number, name=job.name))
    out.sort(key=lambda r: r["variance"])
    return {"projects": out}


@router.get("/api/jobs/{job_id}/photos")
def job_photos(job_id: int, request: Request, kind: str = "photo", q: str = "", date_from: str = "",
               date_to: str = "", by: str = "", source: str = "", db: Session = Depends(get_db)):
    """Every photograph taken on a project - and, asked for, its drawings and
    documents too - newest first, with what each was of: a diary day, a
    variation, a work order. Filtered by type, words, dates, who added them
    and where they were kept."""
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    got = list_files(request, job_id=job.id, kind=kind, q=q, date_from=date_from, date_to=date_to,
                     by=by, attached_type=source, db=db)
    files = got["files"]
    labels = {}
    for d in db.query(models.DBSiteDiary).filter(models.DBSiteDiary.job_id == job.id).all():
        labels[("diary", d.id)] = "Diary %s" % (d.diary_date or "")
    for v in db.query(models.DBVariationOrder).filter(models.DBVariationOrder.job_id == job.id).all():
        labels[("variation", v.id)] = "Variation %s" % (v.number or "")
    for o in db.query(models.DBSubcontractOrder).filter(models.DBSubcontractOrder.job_id == job.id).all():
        labels[("subcontract_order", o.id)] = "Work order %s" % (o.wo_number or "")
    for w in db.query(models.DBWorkOrder).filter(models.DBWorkOrder.job_id == job.id).all():
        labels[("work_order", w.id)] = "Client WO %s" % (getattr(w, "number", "") or "")
    for f in files:
        f["of"] = labels.get((f["attached_type"], f["attached_id"]),
                             "Measurement" if f["attached_type"] == "measurement" else "Project")
    return {"photos": files, "summary": got["summary"],
            "job": {"id": job.id, "number": job.number, "name": job.name}}


@router.get("/api/jobs/{job_id}/drawings")
def list_drawings(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    rows = [drawing_dict(db, d) for d in db.query(models.DBDrawing).filter(
        models.DBDrawing.job_id == job.id).order_by(models.DBDrawing.discipline, models.DBDrawing.number).all()]
    return {"drawings": rows, "statuses": list(DRAWING_STATUSES), "disciplines": list(DRAWING_DISCIPLINES),
            "summary": {"drawings": len(rows),
                        "gfc": len([r for r in rows if r["good_for_construction"]]),
                        "awaiting": len([r for r in rows if r["status"] == "For approval"])}}


@router.post("/api/jobs/{job_id}/drawings")
def add_drawing(job_id: int, body: DrawingIn, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    number = (body.number or "").strip().upper()
    if not number:
        raise HTTPException(400, "The drawing number, as it is printed on the sheet.")
    if db.query(models.DBDrawing).filter(models.DBDrawing.job_id == job.id,
                                         sqlfunc.upper(models.DBDrawing.number) == number).first():
        raise HTTPException(409, "%s is already on this project's register - add a revision to it." % number)
    d = models.DBDrawing(client_id=client.id, job_id=job.id, number=number,
                         title=(body.title or "").strip(),
                         discipline=body.discipline if body.discipline in DRAWING_DISCIPLINES else "Other")
    db.add(d)
    db.commit()
    return {"drawing": drawing_dict(db, d, detail=True)}


@router.get("/api/jobs/{job_id}/site-location")
def get_site_location(job_id: int, request: Request, db: Session = Depends(get_db)):
    client = require_erp_read(request, db)
    job = job_or_404(db, client.id, job_id)
    g = db.query(models.DBSiteGeofence).filter(models.DBSiteGeofence.job_id == job.id).first()
    if not g:
        return {"set": False, "job_id": job.id}
    return {"set": True, "job_id": job.id, "lat": g.lat, "lng": g.lng, "radius_m": g.radius_m,
            "set_by_name": g.set_by_name or "", "updated_at": g.updated_at or "",
            "map": "https://www.google.com/maps?q=%s,%s" % (g.lat, g.lng)}


@router.put("/api/jobs/{job_id}/site-location")
def set_site_location(job_id: int, body: SiteLocationIn, request: Request, db: Session = Depends(get_db)):
    client, _, actor_name = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    lat, lng = body.lat, body.lng
    if (lat is None or lng is None) and body.position:
        got = parse_position(body.position)
        if not got:
            raise HTTPException(400, "Paste the position as 17.4239, 78.3413 or a Google Maps link to the site.")
        lat, lng = got
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        raise HTTPException(400, "Where is the site? Use your location on site, or paste it from Google Maps.")
    radius = max(50.0, min(5000.0, float(body.radius_m or 300)))
    g = db.query(models.DBSiteGeofence).filter(models.DBSiteGeofence.job_id == job.id).first()
    if not g:
        g = models.DBSiteGeofence(client_id=client.id, job_id=job.id)
        db.add(g)
    g.lat, g.lng, g.radius_m = round(lat, 6), round(lng, 6), radius
    g.set_by_name, g.updated_at = actor_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return get_site_location(job_id, request, db)


@router.delete("/api/jobs/{job_id}/site-location")
def clear_site_location(job_id: int, request: Request, db: Session = Depends(get_db)):
    client, _, _ = wo_actor(request, db)
    job = job_or_404(db, client.id, job_id)
    db.query(models.DBSiteGeofence).filter(models.DBSiteGeofence.job_id == job.id).delete()
    db.commit()
    return {"set": False, "job_id": job.id}
