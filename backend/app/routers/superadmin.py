"""The superadmin endpoints."""
import os
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, func as sqlfunc
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

from app.core.audit import log_audit, log_login
from app.core.auth import require_superadmin
from app.core.currency import DEFAULT_CURRENCY, PLATFORM_CURRENCY, currency_symbol, money, to_major, to_minor
from app.core.scheduler import run_due_jobs
from app.core.security import hash_password, rate_limiter, verify_password
from app.schemas.superadmin import PricingRuleIn
from app.services.crm import invoice_overdue_days
from app.services.wallet_ai import (
    credit_wallet,
    enabled_providers,
    gateway_config,
    get_wallet,
    seed_pricing_rules,
)


router = APIRouter()


@router.post("/api/superadmin/login")
def superadmin_login(request: Request, body: dict = None, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(f"sa_login:{ip}", max_requests=5, window=60):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    body = body or {}
    identifier = (body.get("identifier") or body.get("username") or "").strip().lower()
    password = body.get("password", "")
    env_pwd = os.getenv("SUPERADMIN_PASSWORD", "")
    sa = None
    if identifier:
        sa = db.query(models.DBSuperAdmin).filter(
            (models.DBSuperAdmin.email == identifier) | (models.DBSuperAdmin.username == identifier)
        ).first()
    if sa:
        ok = False
        if sa.password_hash:
            ok = verify_password(password, sa.password_hash)
        elif env_pwd:
            ok = verify_password(password, hash_password(env_pwd))
        if ok:
            request.session['superadmin_id'] = sa.id
            log_login(db, None, identifier or sa.email, "superadmin", "password", request, "success")
            return {"ok": True, "username": sa.username, "email": sa.email}
    log_login(db, None, identifier or "superadmin", "superadmin", "password", request, "failed")
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/api/superadmin/change-password")
def superadmin_change_password(request: Request, body: dict = None, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    body = body or {}
    new_pwd = body.get("new_password", "")
    if len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    admin = db.query(models.DBSuperAdmin).filter(models.DBSuperAdmin.id == sa_id).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Not found")
    admin.password_hash = hash_password(new_pwd)
    db.commit()
    return {"message": "Password updated"}


@router.post("/api/superadmin/logout")
def superadmin_logout(request: Request):
    request.session.pop("superadmin_id", None)
    return {"message": "Logged out"}


@router.get("/api/superadmin/me")
def superadmin_me(request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    admin = db.query(models.DBSuperAdmin).filter(models.DBSuperAdmin.id == sa_id).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Not found")
    return {"username": admin.username, "email": admin.email}


@router.get("/api/superadmin/platform-stats")
def superadmin_platform_stats(request: Request, db: Session = Depends(get_db)):
    """Platform-wide numbers across every module, not just invoicing.

    The original insights endpoint only counted invoices, so HR and
    recruitment usage was invisible to the operator.
    """
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")

    def count(model):
        return db.query(model).count()

    paid_total = db.query(sqlfunc.coalesce(sqlfunc.sum(models.DBInvoice.paid), 0)).scalar() or 0
    outstanding = db.query(sqlfunc.coalesce(sqlfunc.sum(models.DBInvoice.due), 0)).filter(
        models.DBInvoice.status.notin_(["Draft", "Paid", "Void"])
    ).scalar() or 0
    payroll_total = db.query(sqlfunc.coalesce(sqlfunc.sum(models.DBPayslip.net_pay), 0)).filter(
        models.DBPayslip.status == "Paid"
    ).scalar() or 0

    now = datetime.now()
    month_prefix = now.strftime("%Y-%m")
    # Super admin and employee logins carry a NULL client_id; counting them
    # would inflate the tenant activity figure.
    active_30d = db.query(models.DBClientLoginLog.client_id).filter(
        models.DBClientLoginLog.status == "success",
        models.DBClientLoginLog.user_type == "client",
        models.DBClientLoginLog.client_id.isnot(None),
        models.DBClientLoginLog.created_at >= (now - timedelta(days=30)).strftime("%Y-%m-%d"),
    ).distinct().count()

    return {
        "tenants": {
            "total": count(models.DBClient),
            "active": db.query(models.DBClient).filter(models.DBClient.is_active == True).count(),
            "onboarded": db.query(models.DBClient).filter(models.DBClient.is_onboarded == True).count(),
            "active_last_30_days": active_30d,
        },
        "invoicing": {
            "invoices": count(models.DBInvoice),
            "bills": count(models.DBBill),
            "collected": money(paid_total),
            "outstanding": money(outstanding),
            "invoices_this_month": db.query(models.DBInvoice).filter(
                models.DBInvoice.issue_date.like(month_prefix + "%")
            ).count(),
        },
        "hr": {
            "employees": count(models.DBEmployee),
            "departments": count(models.DBDepartment),
            "payslips": count(models.DBPayslip),
            "payroll_paid": money(payroll_total),
            "leave_requests": count(models.DBLeaveRequest),
            "attendance_records": count(models.DBAttendance),
        },
        "recruitment": {
            "jobs": count(models.DBJobRequisition),
            "open_jobs": db.query(models.DBJobRequisition).filter(
                models.DBJobRequisition.status == "open"
            ).count(),
            "applications": count(models.DBFormSubmission),
            "interviews": count(models.DBInterview),
            "offers": count(models.DBOffer),
            "hires": db.query(models.DBFormSubmission).filter(
                models.DBFormSubmission.hired_employee_id.isnot(None)
            ).count(),
        },
    }


@router.get("/api/superadmin/clients/{client_id}/overview")
def superadmin_client_overview(client_id: int, request: Request, db: Session = Depends(get_db)):
    """Everything the operator needs to answer 'how is this tenant doing?'
    without impersonating them."""
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    def tenant_count(model):
        return db.query(model).filter(model.client_id == client_id).count()

    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client_id).all()
    employees = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client_id).all()
    today = datetime.now().date()
    overdue = [i for i in invoices if invoice_overdue_days(i, today) > 0]

    last_activity = ""
    latest_login = db.query(models.DBClientLoginLog).filter(
        models.DBClientLoginLog.client_id == client_id,
        models.DBClientLoginLog.status == "success",
    ).order_by(models.DBClientLoginLog.id.desc()).first()
    if latest_login:
        last_activity = latest_login.created_at

    return {
        "id": client.id,
        "company_name": client.company_name or "",
        "email": client.email,
        "is_active": client.is_active,
        "is_onboarded": client.is_onboarded,
        "currency": client.currency or DEFAULT_CURRENCY,
        "created_at": client.created_at,
        "last_login": client.last_login or "",
        "login_count": client.login_count or 0,
        "last_activity": last_activity,
        "invoicing": {
            "invoices": len(invoices),
            "collected": money(sum(i.paid or 0 for i in invoices)),
            "outstanding": money(sum(i.due or 0 for i in invoices if i.status not in ("Draft", "Paid", "Void"))),
            "overdue_count": len(overdue),
            "bills": tenant_count(models.DBBill),
            "contacts": tenant_count(models.DBContact),
        },
        "hr": {
            "employees": len(employees),
            "active_employees": sum(1 for e in employees if e.status == "active"),
            "onboarding": sum(1 for e in employees if e.status == "onboarding"),
            "departments": tenant_count(models.DBDepartment),
            "payslips": tenant_count(models.DBPayslip),
            "pending_leave": db.query(models.DBLeaveRequest).filter(
                models.DBLeaveRequest.client_id == client_id,
                models.DBLeaveRequest.status == "pending",
            ).count(),
        },
        "recruitment": {
            "jobs": tenant_count(models.DBJobRequisition),
            "open_jobs": db.query(models.DBJobRequisition).filter(
                models.DBJobRequisition.client_id == client_id,
                models.DBJobRequisition.status == "open",
            ).count(),
            "applications": tenant_count(models.DBFormSubmission),
            "interviews": tenant_count(models.DBInterview),
        },
        "portals": {
            "invoicing": "/next/",
            "hr": "/next/people/employees",
            "employee": "/employee-login.html",
            "job_board": f"/jobs.html?c={client.id}",
        },
    }


@router.get("/api/superadmin/clients")
def superadmin_clients(request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    results = (
        db.query(
            models.DBClient,
            func.count(models.DBInvoice.id).label('invoice_count'),
            func.count(func.nullif(models.DBInvoice.status, 'Paid')).label('unpaid_count'),
            func.coalesce(func.sum(func.nullif(models.DBInvoice.due, 0)), 0).label('outstanding')
        )
        .outerjoin(models.DBInvoice, models.DBInvoice.client_id == models.DBClient.id)
        .group_by(models.DBClient.id)
        .all()
    )
    return [{
        "id": c.id,
        "email": c.email,
        "company_name": c.company_name,
        "contact_name": c.contact_name,
        "phone_number": c.phone_number,
        "is_active": c.is_active,
        "is_onboarded": c.is_onboarded,
        "last_login": c.last_login or "",
        "login_count": c.login_count or 0,
        "created_at": c.created_at,
        "invoice_count": invoice_count,
        "paid_count": invoice_count - unpaid_count,
        "outstanding": round(float(outstanding), 2),
    } for c, invoice_count, unpaid_count, outstanding in results]


@router.get("/api/superadmin/insights")
def superadmin_insights(request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    total_clients = db.query(models.DBClient).count()
    active_clients = db.query(models.DBClient).filter(models.DBClient.is_active == True).count()
    onboarded = db.query(models.DBClient).filter(models.DBClient.is_onboarded == True).count()
    total_invoices = db.query(models.DBInvoice).count()
    total_revenue = db.query(func.coalesce(func.sum(models.DBInvoice.due), 0)).filter(models.DBInvoice.status == "Paid").scalar()
    total_outstanding = db.query(func.coalesce(func.sum(models.DBInvoice.due), 0)).filter(models.DBInvoice.status != "Paid").scalar()
    return {
        "total_clients": total_clients,
        "active_clients": active_clients,
        "onboarded_clients": onboarded,
        "total_invoices": total_invoices,
        "total_revenue": round(float(total_revenue), 2),
        "total_outstanding": round(float(total_outstanding), 2),
    }


@router.get("/api/superadmin/login-logs")
def superadmin_login_logs(request: Request, limit: int = 100, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    logs = db.query(models.DBClientLoginLog).order_by(models.DBClientLoginLog.created_at.desc()).limit(limit).all()
    return [{
        "id": l.id, "client_id": l.client_id, "email": l.email,
        "user_type": l.user_type, "login_type": l.login_type,
        "ip_address": l.ip_address, "device_info": l.device_info,
        "status": l.status, "created_at": l.created_at,
    } for l in logs]


@router.get("/api/superadmin/login-stats")
def superadmin_login_stats(request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    from datetime import timedelta
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    total_logs = db.query(models.DBClientLoginLog).count()
    today_logs = db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.created_at.like(today + "%")).count()
    week_logs = db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.created_at >= week_ago).count()
    month_logs = db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.created_at >= month_ago).count()
    failed_logs = db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.status == "failed").count()
    google_logins = db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.login_type == "google").count()
    password_logins = db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.login_type == "password").count()
    clients_with_logins = db.query(models.DBClient).filter(models.DBClient.login_count > 0).count()
    never_logged_in = db.query(models.DBClient).filter(models.DBClient.login_count == 0).count()
    return {
        "total_logins": total_logs,
        "today_logins": today_logs,
        "week_logins": week_logs,
        "month_logins": month_logs,
        "failed_logins": failed_logs,
        "google_logins": google_logins,
        "password_logins": password_logins,
        "clients_with_logins": clients_with_logins,
        "clients_never_logged_in": never_logged_in,
    }


@router.put("/api/superadmin/clients/{client_id}/toggle")
def superadmin_toggle_client(client_id: int, request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client.is_active = not client.is_active
    log_audit(db, client.id, "client_" + ("enabled" if client.is_active else "disabled"), "client", client.id, client.company_name or client.email, "", request, user_type="superadmin", user_name="superadmin")
    db.commit()
    return {"message": "Client " + ("enabled" if client.is_active else "disabled"), "is_active": client.is_active}


@router.delete("/api/superadmin/clients/{client_id}")
def superadmin_delete_client(client_id: int, request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    invoice_ids = db.query(models.DBInvoice.id).filter(models.DBInvoice.client_id == client_id)
    db.query(models.DBLineItem).filter(models.DBLineItem.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
    db.query(models.DBPayment).filter(models.DBPayment.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
    db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client_id).delete()
    db.query(models.DBContact).filter(models.DBContact.client_id == client_id).delete()
    db.query(models.DBSettings).filter(models.DBSettings.client_id == client_id).delete()
    db.delete(client)
    log_audit(db, client_id, "client_deleted", "client", client_id, "", "Client and all data deleted", request, user_type="superadmin", user_name="superadmin")
    db.commit()
    return {"message": "Client deleted"}


@router.post("/api/superadmin/impersonate/{client_id}")
def superadmin_impersonate(client_id: int, request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if not client.is_active:
        raise HTTPException(status_code=400, detail="Client account is disabled")
    request.session.pop('employee_id', None)
    request.session.pop('employee_client_id', None)
    request.session['client_id'] = client.id
    log_audit(db, client.id, "impersonate", "client", client.id, client.company_name or client.email, "Super admin logged in as client", request, user_type="superadmin", user_name="superadmin")
    db.commit()
    return {"message": "Now acting as " + (client.company_name or client.email), "client_id": client.id}


@router.get("/api/superadmin/trends")
def superadmin_trends(request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    from datetime import timedelta
    from collections import defaultdict
    now = datetime.now()
    months = [(now - timedelta(days=30 * i)).strftime("%Y-%m") for i in range(5, -1, -1)]
    revenue_by_month = defaultdict(float)
    logins_by_month = defaultdict(int)
    for inv in db.query(models.DBInvoice).filter(models.DBInvoice.status == "Paid").all():
        m = inv.issue_date[:7] if inv.issue_date and len(inv.issue_date) >= 7 else None
        if m in months:
            revenue_by_month[m] += (inv.paid or 0)
    for l in db.query(models.DBClientLoginLog).filter(models.DBClientLoginLog.status == "success").all():
        m = l.created_at[:7] if l.created_at and len(l.created_at) >= 7 else None
        if m in months:
            logins_by_month[m] += 1
    return {
        "months": months,
        "revenue": [round(revenue_by_month.get(m, 0), 2) for m in months],
        "active_users": [logins_by_month.get(m, 0) for m in months],
        "total_revenue": round(sum(inv.paid or 0 for inv in db.query(models.DBInvoice).filter(models.DBInvoice.status == "Paid").all()), 2),
    }


@router.get("/api/superadmin/clients/{client_id}")
def superadmin_get_client(client_id: int, request: Request, db: Session = Depends(get_db)):
    sa_id = request.session.get("superadmin_id")
    if not sa_id:
        raise HTTPException(status_code=401, detail="Not authorized")
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client_id).all()
    return {
        "id": client.id,
        "email": client.email,
        "company_name": client.company_name,
        "contact_name": client.contact_name,
        "phone_number": client.phone_number,
        "address": client.address,
        "website": client.website,
        "abn": client.abn,
        "industry": client.industry,
        "is_active": client.is_active,
        "is_onboarded": client.is_onboarded,
        "created_at": client.created_at,
        "invoices": [{"number": i.number, "status": i.status, "due": i.due, "date": i.issue_date} for i in invoices],
    }


@router.post("/api/superadmin/run-jobs")
def superadmin_run_jobs(request: Request, job: str = ""):
    """Run the scheduled work now, for an operator who does not want to wait
    for the next tick. Still claims the period, so this cannot double-send."""
    require_superadmin(request)
    return {"results": run_due_jobs(only=job or None)}


@router.get("/api/superadmin/job-runs")
def superadmin_job_runs(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    require_superadmin(request)
    rows = db.query(models.DBJobRun).order_by(
        models.DBJobRun.id.desc()).limit(min(limit, 200)).all()
    return [{
        "id": r.id, "job": r.job_name, "period": r.period_key, "status": r.status,
        "detail": r.detail or "", "started_at": r.started_at,
        "finished_at": r.finished_at or "",
    } for r in rows]


@router.get("/api/superadmin/migration-warnings")
def superadmin_migration_warnings(request: Request):
    """The schema steps that failed at boot.

    /api/health reports only a count, because the messages carry table and
    column names and it is a public endpoint. The operator needs the actual
    errors to tell an expected failure (dropping an index that was already
    dropped) from a migration that genuinely did not run.
    """
    require_superadmin(request)
    try:
        from app.db import migration_report
        problems = migration_report()
    except Exception:
        problems = []
    return {"count": len(problems), "warnings": problems}


@router.get("/api/superadmin/environment")
def superadmin_environment(request: Request):
    """Which settings production is actually running with.

    Never returns a value, only whether one is present - this is a page an
    operator reads to answer "did that variable take effect?", and secrets do
    not belong in an HTTP response even behind an admin check.
    """
    require_superadmin(request)

    def state(name, ok, why, fix):
        return {"name": name, "ok": bool(ok), "detail": why, "fix": fix}

    checks = [
        state("SECRET_KEY", bool(os.getenv("SECRET_KEY")),
              "Sessions survive a redeploy."
              if os.getenv("SECRET_KEY") else
              "Not set, so a new key is generated on every boot and every "
              "signed-in user is signed out on each redeploy.",
              "Set SECRET_KEY to a long random string in the host environment."),
        state("GROQ_API_KEY", bool(os.getenv("GROQ_API_KEY")),
              "The AI features can reach the model."
              if os.getenv("GROQ_API_KEY") else
              "Not set, so every AI feature fails at the point of use.",
              "Set GROQ_API_KEY in the host environment."),
        state("DATABASE_URL", bool(os.getenv("DATABASE_URL")),
              "Using the configured database."
              if os.getenv("DATABASE_URL") else
              "Not set, so the app is on a local SQLite file that a redeploy "
              "discards along with all of its data.",
              "Point DATABASE_URL at the Postgres instance."),
        state("Payment gateways",
              any(os.getenv(k) for k in
                  ("STRIPE_SECRET_KEY", "RAZORPAY_KEY_SECRET", "PAYPAL_CLIENT_SECRET")),
              "At least one gateway is configured.",
              "Set the keys for whichever gateway you intend to take money with."),
    ]
    return {
        "checks": checks,
        "ready": all(c["ok"] for c in checks),
        "outstanding": [c["name"] for c in checks if not c["ok"]],
    }


@router.get("/api/superadmin/ai-status")
def tenant_ai_status(request: Request):
    """Whether the AI features can actually run, without exposing the key.

    All five AI endpoints degrade to a canned response when the key is absent,
    which is safe but indistinguishable from a broken model - this says which.
    """
    require_superadmin(request)
    from app.integrations import llm
    key = llm.GROQ_API_KEY or ""
    configured = bool(key)
    looks_valid = key.startswith("gsk_") and len(key) > 20

    reachable, detail = False, "Not configured"
    if configured:
        try:
            probe = llm.llm_chat([{"role": "user", "content": "ping"}], max_tokens=5)
            reachable = probe is not None
            detail = "Model responded" if reachable else "Key set but the API call failed - check the key and quota"
        except Exception as exc:
            detail = f"Call failed: {exc}"[:160]

    return {
        "provider": "groq",
        "model": llm.MODEL,
        "configured": configured,
        "key_format_ok": looks_valid,
        "reachable": reachable,
        "detail": detail if configured else "GROQ_API_KEY is not set. AI features return a fallback response.",
        "env_var": "GROQ_API_KEY",
        "key_hint": "Groq keys begin with gsk_ and are issued at console.groq.com/keys",
        "features": [
            "AI resume screening", "AI onboarding checklist",
            "AI invoice email drafting", "AI payment follow-up",
            "AI attendance summary",
        ],
    }


@router.get("/api/superadmin/pricing")
def list_pricing(request: Request, db: Session = Depends(get_db)):
    require_superadmin(request)
    rows = db.query(models.DBPricingRule).order_by(
        models.DBPricingRule.sort_order.asc(), models.DBPricingRule.id.asc()
    ).all()
    if not rows:
        rows = seed_pricing_rules(db)
        db.commit()
    return [{
        "id": r.id, "action_key": r.action_key, "label": r.label,
        "description": r.description, "module": r.module,
        "unit_price": to_major(r.unit_price_minor, r.currency),
        "unit_price_minor": r.unit_price_minor, "currency": r.currency,
        "free_allowance": r.free_allowance, "is_active": bool(r.is_active),
        "sort_order": r.sort_order, "updated_at": r.updated_at,
    } for r in rows]


@router.put("/api/superadmin/pricing/{rule_id}")
def update_pricing(rule_id: int, request: Request, body: PricingRuleIn,
                   db: Session = Depends(get_db)):
    require_superadmin(request)
    rule = db.query(models.DBPricingRule).filter(models.DBPricingRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    if body.unit_price is not None:
        price = float(body.unit_price)
        if price < 0:
            raise HTTPException(status_code=400, detail="Price cannot be negative")
        if price > 1000:
            raise HTTPException(status_code=400, detail="That price looks wrong - over 1000 per action")
        rule.unit_price_minor = to_minor(price, rule.currency)
    if body.free_allowance is not None:
        allowance = int(body.free_allowance)
        if allowance < 0 or allowance > 100000:
            raise HTTPException(status_code=400, detail="Free allowance must be between 0 and 100000")
        rule.free_allowance = allowance
    if body.label:
        rule.label = body.label.strip()
    if body.description is not None:
        rule.description = body.description
    if body.is_active is not None:
        rule.is_active = bool(body.is_active)
    if body.sort_order is not None:
        rule.sort_order = int(body.sort_order)
    rule.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    return {"message": f"{rule.label} updated", "unit_price": to_major(rule.unit_price_minor, rule.currency)}


@router.post("/api/superadmin/pricing")
def create_pricing(request: Request, body: PricingRuleIn, db: Session = Depends(get_db)):
    require_superadmin(request)
    key = (body.action_key or "").strip().lower().replace(" ", "_")
    if not key:
        raise HTTPException(status_code=400, detail="An action key is required")
    if db.query(models.DBPricingRule).filter(models.DBPricingRule.action_key == key).first():
        raise HTTPException(status_code=400, detail=f"'{key}' already has a price")
    price = float(body.unit_price or 0)
    if price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    rule = models.DBPricingRule(
        action_key=key, label=(body.label or key).strip(),
        description=body.description or "", module=body.module or "platform",
        unit_price_minor=to_minor(price, PLATFORM_CURRENCY), currency=PLATFORM_CURRENCY,
        free_allowance=int(body.free_allowance or 0), is_active=bool(body.is_active),
        sort_order=int(body.sort_order or 0),
    )
    db.add(rule)
    db.commit()
    return {"message": f"{rule.label} added", "id": rule.id}


@router.get("/api/superadmin/wallets")
def list_wallets(request: Request, db: Session = Depends(get_db)):
    require_superadmin(request)
    clients = db.query(models.DBClient).all()
    wallets = {w.client_id: w for w in db.query(models.DBWallet).all()}
    out = []
    for c in clients:
        w = wallets.get(c.id)
        out.append({
            "client_id": c.id,
            "company_name": c.company_name or c.email,
            "email": c.email,
            "balance": to_major(w.balance_minor, w.currency) if w else 0.0,
            "currency": w.currency if w else PLATFORM_CURRENCY,
            "is_low": bool(w and w.balance_minor <= (w.low_balance_minor or 0)),
            "lifetime_topped_up": to_major(w.lifetime_topped_up_minor, w.currency) if w else 0.0,
            "lifetime_spent": to_major(w.lifetime_spent_minor, w.currency) if w else 0.0,
            "is_suspended": bool(w and w.is_suspended),
        })
    out.sort(key=lambda r: r["balance"])
    return out


@router.post("/api/superadmin/wallets/{client_id}/adjust")
def adjust_wallet(client_id: int, request: Request, body: dict = None,
                  db: Session = Depends(get_db)):
    """Operator credit or debit: refunds, goodwill, corrections. Every
    adjustment is a ledger row, never a silent balance edit."""
    require_superadmin(request)
    body = body or {}
    client = db.query(models.DBClient).filter(models.DBClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Amount must be a number")
    if amount == 0:
        raise HTTPException(status_code=400, detail="Amount cannot be zero")
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Give a reason - this lands on the tenant's statement")

    wallet = get_wallet(db, client_id)
    amount_minor = to_minor(abs(amount), wallet.currency)
    if amount > 0:
        credit_wallet(db, client_id, amount_minor, reason, performed_by="superadmin",
                      action_key="adjustment")
    else:
        if wallet.balance_minor < amount_minor:
            raise HTTPException(status_code=400, detail="That would take the balance below zero")
        wallet.balance_minor -= amount_minor
        wallet.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.add(models.DBWalletTransaction(
            client_id=client_id, wallet_id=wallet.id, direction="debit",
            amount_minor=amount_minor, balance_after_minor=wallet.balance_minor,
            currency=wallet.currency, action_key="adjustment", module="platform",
            description=reason, performed_by="superadmin",
        ))
    log_audit(db, client_id, "wallet_adjusted", "wallet", client_id,
              client.company_name or client.email, f"{amount:+.2f}: {reason}",
              request, user_type="superadmin", user_name="superadmin")
    db.commit()
    return {
        "message": "Wallet adjusted",
        "balance": to_major(wallet.balance_minor, wallet.currency),
    }


@router.get("/api/superadmin/revenue")
def platform_revenue(request: Request, months: int = 6, db: Session = Depends(get_db)):
    """What the platform has actually earned, by month and by action."""
    require_superadmin(request)
    months = max(1, min(months, 24))
    cutoff = (datetime.now() - timedelta(days=31 * months)).strftime("%Y-%m")
    rows = db.query(models.DBWalletTransaction).filter(
        models.DBWalletTransaction.created_at >= cutoff
    ).all()

    spend_by_month, topup_by_month, by_action = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        month = (r.created_at or "")[:7]
        if r.direction == "debit" and r.action_key != "adjustment":
            spend_by_month[month] += r.amount_minor or 0
            by_action[r.action_key or "other"] += r.amount_minor or 0
        elif r.direction == "credit" and r.action_key == "topup":
            topup_by_month[month] += r.amount_minor or 0

    all_months = sorted(set(spend_by_month) | set(topup_by_month))
    outstanding = db.query(sqlfunc.coalesce(sqlfunc.sum(models.DBWallet.balance_minor), 0)).scalar() or 0
    return {
        "currency": PLATFORM_CURRENCY,
        "symbol": currency_symbol(PLATFORM_CURRENCY),
        "total_topped_up": to_major(sum(topup_by_month.values()), PLATFORM_CURRENCY),
        "total_consumed": to_major(sum(spend_by_month.values()), PLATFORM_CURRENCY),
        "outstanding_liability": to_major(outstanding, PLATFORM_CURRENCY),
        "months": [{
            "month": m,
            "topped_up": to_major(topup_by_month.get(m, 0), PLATFORM_CURRENCY),
            "consumed": to_major(spend_by_month.get(m, 0), PLATFORM_CURRENCY),
        } for m in all_months],
        "by_action": [{"action_key": k, "revenue": to_major(v, PLATFORM_CURRENCY)}
                      for k, v in sorted(by_action.items(), key=lambda kv: -kv[1])],
    }


@router.get("/api/superadmin/gateways")
def superadmin_gateways(request: Request):
    """Which providers this deployment can actually take money with, so the
    operator can see what still needs keys."""
    require_superadmin(request)
    cfg = gateway_config()
    enabled = enabled_providers()
    return {
        "platform_currency": PLATFORM_CURRENCY,
        "providers": [
            {"key": "stripe", "enabled": enabled["stripe"],
             "webhook_ready": bool(cfg["stripe"]["webhook_secret"]),
             "required_env": ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"],
             "webhook_url": "/api/wallet/webhook/stripe"},
            {"key": "razorpay", "enabled": enabled["razorpay"],
             "webhook_ready": bool(cfg["razorpay"]["webhook_secret"]),
             "required_env": ["RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"],
             "webhook_url": "/api/wallet/webhook/razorpay"},
            {"key": "paypal", "enabled": enabled["paypal"],
             "webhook_ready": True,   # capture is verified server-side, no webhook needed
             "required_env": ["PAYPAL_CLIENT_ID", "PAYPAL_SECRET", "PAYPAL_MODE"],
             "webhook_url": ""},
        ],
    }
