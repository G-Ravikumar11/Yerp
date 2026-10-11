"""The wallet ai endpoints."""
import hashlib
import hmac
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.ai.assistant_llm import llm_chat, llm_configured, llm_error_message, llm_json

from app.constants.wallet_ai import ASSISTANT_SYSTEM, TOPUP_MAX_MAJOR, TOPUP_MIN_MAJOR
from app.core.auth import get_client_user
from app.core.config import logger
from app.core.currency import currency_symbol, to_major
from app.schemas.wallet_ai import AssistantQuery, TopUpIn
from app.services.crm import invoice_overdue_days
from app.services.wallet_ai import (
    _create_paypal_order,
    _create_razorpay_order,
    _create_stripe_checkout,
    _paypal_base,
    _paypal_token,
    as_list,
    as_text,
    build_business_context,
    charge_after_success,
    credit_topup_once,
    enabled_providers,
    ensure_can_afford,
    gateway_config,
    get_wallet,
    month_usage,
    quote_action,
    wallet_state,
)
from app.validators.common import valid_hex_colour, validate_topup_amount


router = APIRouter()


@router.get("/api/wallet")
def get_my_wallet(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    state = wallet_state(db, client)
    db.commit()
    return state


@router.get("/api/wallet/transactions")
def wallet_transactions(request: Request, limit: int = 100, direction: str = "",
                        db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    query = db.query(models.DBWalletTransaction).filter(
        models.DBWalletTransaction.client_id == client.id
    )
    if direction in ("credit", "debit"):
        query = query.filter(models.DBWalletTransaction.direction == direction)
    rows = query.order_by(models.DBWalletTransaction.id.desc()).limit(
        max(1, min(limit, 500))
    ).all()
    return [{
        "id": t.id, "direction": t.direction,
        "amount": to_major(t.amount_minor, t.currency),
        "balance_after": to_major(t.balance_after_minor, t.currency),
        "currency": t.currency, "action_key": t.action_key, "module": t.module,
        "description": t.description, "reference": t.reference,
        "quantity": t.quantity, "created_at": t.created_at,
    } for t in rows]


@router.get("/api/wallet/usage")
def wallet_usage(request: Request, months: int = 3, db: Session = Depends(get_db)):
    """What the tenant has actually spent, grouped by action and by month."""
    client = get_client_user(request, db)
    wallet = get_wallet(db, client.id)
    months = max(1, min(months, 12))
    cutoff = (datetime.now() - timedelta(days=31 * months)).strftime("%Y-%m")
    rows = db.query(models.DBWalletTransaction).filter(
        models.DBWalletTransaction.client_id == client.id,
        models.DBWalletTransaction.direction == "debit",
        models.DBWalletTransaction.created_at >= cutoff,
    ).all()

    by_action, by_month = defaultdict(lambda: {"units": 0, "spent_minor": 0}), defaultdict(int)
    for r in rows:
        slot = by_action[r.action_key or "other"]
        slot["units"] += r.quantity or 1
        slot["spent_minor"] += r.amount_minor or 0
        by_month[(r.created_at or "")[:7]] += r.amount_minor or 0

    return {
        "currency": wallet.currency,
        "symbol": currency_symbol(wallet.currency),
        "total_spent": to_major(sum(v["spent_minor"] for v in by_action.values()), wallet.currency),
        "by_action": [{
            "action_key": k, "units": v["units"],
            "spent": to_major(v["spent_minor"], wallet.currency),
        } for k, v in sorted(by_action.items(), key=lambda kv: -kv[1]["spent_minor"])],
        "by_month": [{"month": m, "spent": to_major(v, wallet.currency)}
                     for m, v in sorted(by_month.items())],
    }


@router.get("/api/wallet/quote")
def wallet_quote(request: Request, action: str, quantity: int = 1,
                 db: Session = Depends(get_db)):
    """What would this cost, and can I afford it? Lets the UI warn before the
    user commits to a bulk action such as a payroll run."""
    client = get_client_user(request, db)
    wallet = get_wallet(db, client.id)
    rule, chargeable, cost = quote_action(db, client.id, action, quantity)
    db.commit()
    return {
        "action": action,
        "label": rule.label if rule else action,
        "quantity": max(1, int(quantity or 1)),
        "chargeable_units": chargeable,
        "cost": to_major(cost, wallet.currency),
        "currency": wallet.currency,
        "symbol": currency_symbol(wallet.currency),
        "balance": to_major(wallet.balance_minor, wallet.currency),
        "affordable": wallet.balance_minor >= cost,
        "free_remaining": max(0, (rule.free_allowance or 0) - month_usage(db, client.id, action)) if rule else 0,
    }


@router.get("/api/wallet/providers")
def wallet_providers(request: Request, db: Session = Depends(get_db)):
    """What the top-up screen should offer. Being explicit about what is not
    configured beats a button that fails on click."""
    client = get_client_user(request, db)
    wallet = get_wallet(db, client.id)
    db.commit()
    enabled = enabled_providers()
    cfg = gateway_config()
    return {
        "currency": wallet.currency,
        "symbol": currency_symbol(wallet.currency),
        "min_amount": TOPUP_MIN_MAJOR,
        "max_amount": TOPUP_MAX_MAJOR,
        "suggested": [10, 25, 50, 100, 250],
        "providers": [
            {"key": "stripe", "label": "Card (Stripe)", "enabled": enabled["stripe"],
             "publishable_key": cfg["stripe"]["publishable"] if enabled["stripe"] else ""},
            {"key": "razorpay", "label": "Razorpay (UPI, cards, netbanking)",
             "enabled": enabled["razorpay"],
             "key_id": cfg["razorpay"]["key_id"] if enabled["razorpay"] else ""},
            {"key": "paypal", "label": "PayPal", "enabled": enabled["paypal"]},
        ],
        "any_enabled": any(enabled.values()),
    }


@router.post("/api/wallet/topup")
def create_topup(body: TopUpIn, request: Request, db: Session = Depends(get_db)):
    """Create a payment at the chosen provider and hand back what the browser
    needs to complete it. No credit is added here."""
    client = get_client_user(request, db)
    wallet = get_wallet(db, client.id)
    amount_minor = validate_topup_amount(body.amount, wallet.currency)
    provider = (body.provider or "").strip().lower()
    if provider not in ("stripe", "razorpay", "paypal"):
        raise HTTPException(status_code=400, detail="Choose Stripe, Razorpay or PayPal")

    order = models.DBTopUpOrder(
        client_id=client.id, provider=provider, amount_minor=amount_minor,
        currency=wallet.currency, status="created",
    )
    db.add(order)
    db.flush()

    try:
        if provider == "stripe":
            result = _create_stripe_checkout(order, client, request)
        elif provider == "razorpay":
            result = _create_razorpay_order(order, client)
        else:
            result = _create_paypal_order(order, client, request)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        logger.exception("Top-up creation failed at %s", provider)
        order.status = "failed"
        order.failure_reason = str(exc)[:200]
        db.commit()
        raise HTTPException(status_code=502, detail=f"{provider.title()} could not start the payment. Please try again.")

    order.status = "pending"
    db.commit()
    result.update({
        "order_id": order.id,
        "amount": to_major(amount_minor, wallet.currency),
        "currency": wallet.currency,
    })
    return result


# Only these add credit. Each verifies the message really came from the
# provider before touching a balance.
@router.post("/api/wallet/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    cfg = gateway_config()["stripe"]
    raw = await request.body()
    signature = request.headers.get("stripe-signature", "")

    if not cfg["webhook_secret"]:
        # Without the secret the message cannot be trusted, and an unverified
        # webhook would let anyone credit their own wallet.
        logger.error("Stripe webhook rejected: STRIPE_WEBHOOK_SECRET is not set")
        raise HTTPException(status_code=503, detail="Stripe webhooks are not configured")

    try:
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        timestamp, sent_sig = parts.get("t", ""), parts.get("v1", "")
        expected = hmac.new(
            cfg["webhook_secret"].encode(),
            f"{timestamp}.".encode() + raw,
            hashlib.sha256,
        ).hexdigest()
        if not sent_sig or not hmac.compare_digest(expected, sent_sig):
            raise ValueError("signature mismatch")
        # Reject anything older than five minutes, so a captured webhook
        # cannot be replayed later.
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("timestamp outside tolerance")
    except Exception as exc:
        logger.warning("Stripe webhook verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = json.loads(raw or b"{}")
    if event.get("type") not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return {"received": True, "ignored": event.get("type")}

    session = event.get("data", {}).get("object", {})
    order_id = (session.get("metadata") or {}).get("order_id") or session.get("client_reference_id")
    order = db.query(models.DBTopUpOrder).filter(models.DBTopUpOrder.id == int(order_id or 0)).first()
    if not order:
        logger.warning("Stripe webhook for unknown order %s", order_id)
        return {"received": True, "ignored": "unknown order"}
    if session.get("payment_status") != "paid":
        return {"received": True, "ignored": "not paid"}

    credited = credit_topup_once(db, order, session.get("payment_intent", ""))
    db.commit()
    return {"received": True, "credited": credited}


@router.post("/api/wallet/webhook/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    cfg = gateway_config()["razorpay"]
    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not cfg["webhook_secret"]:
        logger.error("Razorpay webhook rejected: RAZORPAY_WEBHOOK_SECRET is not set")
        raise HTTPException(status_code=503, detail="Razorpay webhooks are not configured")

    expected = hmac.new(cfg["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        logger.warning("Razorpay webhook signature mismatch")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = json.loads(raw or b"{}")
    if event.get("event") not in ("payment.captured", "order.paid"):
        return {"received": True, "ignored": event.get("event")}

    payload = event.get("payload", {})
    payment = (payload.get("payment") or {}).get("entity", {})
    provider_order_id = payment.get("order_id") or (payload.get("order") or {}).get("entity", {}).get("id")
    order = db.query(models.DBTopUpOrder).filter(
        models.DBTopUpOrder.provider_order_id == (provider_order_id or "")
    ).first()
    if not order:
        logger.warning("Razorpay webhook for unknown order %s", provider_order_id)
        return {"received": True, "ignored": "unknown order"}

    # Never credit more than the order was for, whatever the callback claims.
    if payment.get("amount") and int(payment["amount"]) < order.amount_minor:
        logger.error("Razorpay paid %s but order was %s", payment.get("amount"), order.amount_minor)
        return {"received": True, "ignored": "amount mismatch"}

    credited = credit_topup_once(db, order, payment.get("id", ""))
    db.commit()
    return {"received": True, "credited": credited}


@router.post("/api/wallet/topup/{order_id}/capture-paypal")
def capture_paypal(order_id: int, request: Request, db: Session = Depends(get_db)):
    """PayPal returns the buyer to us; the capture call to PayPal is what
    proves payment, not the redirect."""
    client = get_client_user(request, db)
    order = db.query(models.DBTopUpOrder).filter(
        models.DBTopUpOrder.id == order_id,
        models.DBTopUpOrder.client_id == client.id,
        models.DBTopUpOrder.provider == "paypal",
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Top-up not found")
    if order.credited:
        wallet = get_wallet(db, client.id)
        return {"message": "Already credited", "balance": to_major(wallet.balance_minor, wallet.currency)}

    token = _paypal_token()
    resp = httpx.post(
        f"{_paypal_base()}/v2/checkout/orders/{order.provider_order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=25,
    )
    if resp.status_code >= 400:
        logger.error("PayPal capture failed: %s", resp.text[:400])
        order.failure_reason = "capture failed"
        db.commit()
        raise HTTPException(status_code=502, detail="PayPal could not complete the payment.")
    data = resp.json()
    if data.get("status") != "COMPLETED":
        return {"message": f"Payment is {data.get('status', 'incomplete')}", "credited": False}

    capture_id = ""
    try:
        capture_id = data["purchase_units"][0]["payments"]["captures"][0]["id"]
    except (KeyError, IndexError):
        pass
    credit_topup_once(db, order, capture_id)
    db.commit()
    wallet = get_wallet(db, client.id)
    return {
        "message": "Wallet topped up",
        "credited": True,
        "balance": to_major(wallet.balance_minor, wallet.currency),
    }


@router.get("/api/wallet/topups")
def list_topups(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    rows = db.query(models.DBTopUpOrder).filter(
        models.DBTopUpOrder.client_id == client.id
    ).order_by(models.DBTopUpOrder.id.desc()).limit(max(1, min(limit, 200))).all()
    return [{
        "id": o.id, "provider": o.provider,
        "amount": to_major(o.amount_minor, o.currency), "currency": o.currency,
        "status": o.status, "credited": bool(o.credited),
        "checkout_url": o.checkout_url if o.status == "pending" else "",
        "failure_reason": o.failure_reason, "created_at": o.created_at,
    } for o in rows]


@router.get("/api/ai/status")
def ai_status_detail(request: Request, db: Session = Depends(get_db)):
    """Whether the AI is usable at all.

    The UI asks once and hides its AI buttons if not, rather than offering
    something that fails the moment anyone presses it.
    """
    get_client_user(request, db)
    configured = llm_configured()
    return {
        "configured": configured,
        "message": "" if configured else llm_error_message(),
    }


@router.post("/api/ai/screen-resume")
def screen_resume(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ensure_can_afford(db, client.id, "ai_resume_screen")
    if not body or not body.get("job_title"):
        raise HTTPException(status_code=400, detail="job_title required")
    job_title = body["job_title"]
    job_description = body.get("job_description", "")
    resume_text = body.get("resume_text", "")
    candidate_name = body.get("candidate_name", "Candidate")
    if not resume_text:
        return {"score": 0, "summary": "No resume text provided to analyze.", "strengths": [], "weaknesses": [], "recommendation": "Cannot screen without resume content."}
    messages = [
        {"role": "system", "content": "You are an expert HR recruiter. Analyze the resume against the job requirements and return JSON with: score (0-100), summary (1 sentence), strengths (list of up to 5), weaknesses (list of up to 5), recommendation (Hire/Interview/Reject with 1 sentence reason). Return ONLY valid JSON."},
        {"role": "user", "content": f"Job Title: {job_title}\nJob Description: {job_description}\n\nCandidate: {candidate_name}\nResume:\n{resume_text[:4000]}"}
    ]
    result = llm_json(messages)
    if not result:
        return {"score": 0, "summary": "AI service unavailable.", "strengths": [], "weaknesses": [], "recommendation": "Unable to screen at this time."}
    charge_after_success(db, client.id, "ai_resume_screen", 1, candidate_name)
    return {
        "score": result.get("score", 0),
        "summary": result.get("summary", ""),
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
        "recommendation": result.get("recommendation", ""),
    }


@router.post("/api/ai/generate-onboarding")
def generate_onboarding_checklist(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ensure_can_afford(db, client.id, "ai_onboarding")
    if not body or not body.get("job_title"):
        raise HTTPException(status_code=400, detail="job_title required")
    job_title = body["job_title"]
    department = body.get("department", "")
    seniority = body.get("seniority", "mid-level")
    messages = [
        {"role": "system", "content": "You are an HR onboarding specialist. Generate a custom onboarding checklist for a new hire. Return JSON with: items (list of objects with title, category, description, due_days from start). Categories: Legal, IT, HR, Social, Compliance, Training. Include 8-15 items. Return ONLY valid JSON."},
        {"role": "user", "content": f"Job Title: {job_title}\nDepartment: {department}\nSeniority: {seniority}"}
    ]
    result = llm_json(messages)
    if not result:
        return {"items": [
            {"title": "Sign employment contract", "category": "Legal", "description": "Review and sign employment agreement", "due_days": 1},
            {"title": "Provide government-issued ID", "category": "Legal", "description": "Submit ID for verification", "due_days": 1},
            {"title": "Submit bank details for payroll", "category": "Finance", "description": "Provide banking information", "due_days": 3},
            {"title": "IT equipment setup", "category": "IT", "description": "Laptop, email, system access", "due_days": 1},
            {"title": "Company policy acknowledgment", "category": "Compliance", "description": "Read and acknowledge policies", "due_days": 7},
        ]}
    charge_after_success(db, client.id, "ai_onboarding", 1, job_title)
    return {"items": result.get("items", [])}


@router.post("/api/ai/personalize-email")
def personalize_invoice_email(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ensure_can_afford(db, client.id, "ai_email_draft")
    if not body or not body.get("client_name"):
        raise HTTPException(status_code=400, detail="client_name required")
    client_name = body["client_name"]
    invoice_number = body.get("invoice_number", "")
    total = body.get("total", 0)
    due_date = body.get("due_date", "")
    is_first_time = body.get("is_first_time", False)
    tone = body.get("tone", "professional")
    messages = [
        {"role": "system", "content": f"You are a professional accounts receivable email writer. Write a short, {tone} invoice email. Include: greeting, invoice reference, amount, due date, payment link mention, and closing. Keep it under 100 words. Return ONLY the email body text, no subject line."},
        {"role": "user", "content": f"Client: {client_name}\nInvoice: {invoice_number}\nAmount: £{total}\nDue: {due_date}\nFirst time client: {is_first_time}"}
    ]
    result = llm_chat(messages)
    if not result:
        return {"subject": f"Invoice {invoice_number}", "body": f"Dear {client_name},\n\nPlease find invoice {invoice_number} for £{total}, due {due_date}.\n\nKind regards,\n{client.company_name or 'Accounts Team'}"}
    subject = f"Invoice {invoice_number}" if invoice_number else "Invoice"
    lines = result.strip().split("\n")
    for line in lines:
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            result = result.replace(line, "").strip()
            break
    charge_after_success(db, client.id, "ai_email_draft", 1, invoice_number)
    return {"subject": subject, "body": result}


@router.post("/api/ai/generate-followup")
def generate_followup_email(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ensure_can_afford(db, client.id, "ai_email_draft")
    if not body or not body.get("client_name"):
        raise HTTPException(status_code=400, detail="client_name required")
    client_name = body["client_name"]
    invoice_number = body.get("invoice_number", "")
    total = body.get("total", 0)
    days_overdue = body.get("days_overdue", 0)
    tone = body.get("tone", "polite")
    messages = [
        {"role": "system", "content": f"You are an accounts receivable specialist. Write a {tone} payment follow-up email for an overdue invoice. Be concise, professional, and clear about the amount owed and urgency. Keep under 80 words. Return ONLY the email body text."},
        {"role": "user", "content": f"Client: {client_name}\nInvoice: {invoice_number}\nAmount: £{total}\nDays overdue: {days_overdue}"}
    ]
    result = llm_chat(messages)
    if not result:
        return {"subject": f"Payment Reminder - {invoice_number}", "body": f"Dear {client_name},\n\nThis is a friendly reminder that invoice {invoice_number} for £{total} is now {days_overdue} days overdue.\n\nPlease arrange payment at your earliest convenience.\n\nKind regards,\n{client.company_name or 'Accounts Team'}"}
    subject = f"Payment Reminder - {invoice_number}" if invoice_number else "Payment Reminder"
    charge_after_success(db, client.id, "ai_email_draft", 1, invoice_number)
    return {"subject": subject, "body": result}


@router.get("/api/ai/payroll-anomalies")
def detect_payroll_anomalies(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    payslips = db.query(models.DBPayslip).filter(
        models.DBPayslip.client_id == client.id
    ).order_by(models.DBPayslip.employee_id, models.DBPayslip.period_start.desc()).all()
    by_emp = {}
    for p in payslips:
        if p.employee_id not in by_emp:
            by_emp[p.employee_id] = []
        by_emp[p.employee_id].append(p)
    anomalies = []
    for emp_id, ps_list in by_emp.items():
        if len(ps_list) < 2:
            continue
        latest = ps_list[0]
        prev = ps_list[1]
        if prev.net_pay and prev.net_pay > 0 and latest.net_pay:
            pct_change = abs(latest.net_pay - prev.net_pay) / prev.net_pay * 100
            if pct_change > 20:
                emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
                emp_name = f"{emp.first_name} {emp.last_name}" if emp else f"Employee #{emp_id}"
                direction = "increased" if latest.net_pay > prev.net_pay else "decreased"
                anomalies.append({
                    "employee_id": emp_id, "employee_name": emp_name,
                    "latest_net": round(float(latest.net_pay), 2),
                    "previous_net": round(float(prev.net_pay), 2),
                    "change_pct": round(pct_change, 1), "direction": direction,
                    "latest_period": latest.period_start or "",
                })
    anomalies.sort(key=lambda x: x["change_pct"], reverse=True)
    return {"anomalies": anomalies, "total_checked": len(by_emp)}


@router.get("/api/ai/attendance-alerts")
def detect_attendance_alerts(request: Request, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    from datetime import timedelta
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    records = db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client.id,
        models.DBAttendance.date >= thirty_days_ago,
    ).all()
    by_emp = {}
    for r in records:
        if r.employee_id not in by_emp:
            by_emp[r.employee_id] = []
        by_emp[r.employee_id].append(r)
    alerts = []
    for emp_id, recs in by_emp.items():
        emp = db.query(models.DBEmployee).filter(models.DBEmployee.id == emp_id).first()
        if not emp:
            continue
        emp_name = f"{emp.first_name} {emp.last_name}"
        late_count = 0
        absent_days = 0
        long_breaks = 0
        no_clockout = 0
        total_hours = 0
        for r in recs:
            if r.clock_in and r.clock_in > "09:15:00":
                late_count += 1
            if r.status == "absent" or (not r.clock_in and not r.clock_out):
                absent_days += 1
            if r.break_minutes and r.break_minutes > 90:
                long_breaks += 1
            if r.clock_in and not r.clock_out:
                no_clockout += 1
            if r.total_hours:
                total_hours += float(r.total_hours)
        emp_alerts = []
        if late_count >= 5:
            emp_alerts.append({"type": "late", "message": f"Late {late_count} times in 30 days", "severity": "warning"})
        if absent_days >= 5:
            emp_alerts.append({"type": "absent", "message": f"{absent_days} absent days in 30 days", "severity": "critical"})
        if long_breaks >= 3:
            emp_alerts.append({"type": "break", "message": f"{long_breaks} extended breaks (>90 min)", "severity": "warning"})
        if no_clockout >= 2:
            emp_alerts.append({"type": "clockout", "message": f"{no_clockout} missed clock-outs", "severity": "warning"})
        if recs and total_hours / len(recs) > 10:
            emp_alerts.append({"type": "overtime", "message": f"Avg {round(total_hours/len(recs), 1)}h/day — burnout risk", "severity": "critical"})
        if emp_alerts:
            alerts.append({"employee_id": emp_id, "employee_name": emp_name, "department": emp.department_id, "alerts": emp_alerts, "total_hours_30d": round(total_hours, 1)})
    alerts.sort(key=lambda x: len(x["alerts"]), reverse=True)
    return {"alerts": alerts, "period": "30 days", "employees_checked": len(by_emp)}


@router.post("/api/ai/summarize-attendance")
def summarize_attendance(request: Request, body: dict = None, db: Session = Depends(get_db)):
    client = get_client_user(request, db)
    ensure_can_afford(db, client.id, "ai_attendance_summary")
    from datetime import timedelta
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    records = db.query(models.DBAttendance).filter(
        models.DBAttendance.client_id == client.id,
        models.DBAttendance.date >= thirty_days_ago,
    ).all()
    total_employees = db.query(models.DBEmployee).filter(
        models.DBEmployee.client_id == client.id, models.DBEmployee.status == "active"
    ).count()
    total_records = len(records)
    present_days = sum(1 for r in records if r.status == "present")
    avg_hours = sum(float(r.total_hours or 0) for r in records) / max(total_records, 1)
    remote_count = sum(1 for r in records if r.check_type == "remote")
    office_count = sum(1 for r in records if r.check_type == "office")
    context = f"Period: last 30 days. Active employees: {total_employees}. Total attendance records: {total_records}. Present days: {present_days}. Avg hours/day: {round(avg_hours,1)}. Remote check-ins: {remote_count}. Office check-ins: {office_count}."
    messages = [
        {"role": "system", "content": "You are an HR analytics assistant. Summarize the attendance data in 2-3 bullet points. Be specific with numbers. Focus on actionable insights."},
        {"role": "user", "content": context}
    ]
    result = llm_chat(messages)
    if not result:
        result = f"• {present_days} present days recorded across {total_employees} employees.\n• Average daily hours: {round(avg_hours, 1)}h.\n• Remote: {remote_count}, Office: {office_count}."
    charge_after_success(db, client.id, "ai_attendance_summary")
    return {"summary": result, "stats": {"total_employees": total_employees, "total_records": total_records, "present_days": present_days, "avg_hours": round(avg_hours, 1), "remote": remote_count, "office": office_count}}


@router.post("/api/ai/assistant")
def ai_assistant(body: AssistantQuery, request: Request, db: Session = Depends(get_db)):
    """Answer a question about this tenant's own data."""
    client = get_client_user(request, db)
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="Please keep the question under 500 characters")

    ensure_can_afford(db, client.id, "ai_assistant")

    context = build_business_context(db, client)
    answer = llm_chat([
        {"role": "system", "content": ASSISTANT_SYSTEM},
        {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"},
    ], temperature=0.2, max_tokens=400)

    if not answer:
        return {
            "answer": "The AI assistant is not available right now. "
                      "An administrator needs to configure the AI key.",
            "available": False,
        }
    charge_after_success(db, client.id, "ai_assistant", 1, question[:60])
    return {"answer": answer, "available": True}


@router.get("/api/ai/suggestions")
def ai_suggestions(request: Request, db: Session = Depends(get_db)):
    """Starter questions worth asking, chosen from what is actually going on
    rather than a fixed list."""
    client = get_client_user(request, db)
    today = datetime.now().date()
    out = []

    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()
    if any(invoice_overdue_days(i, today) > 0 for i in invoices):
        out.append("Which invoices are overdue and by how long?")
    if invoices:
        out.append("How much am I owed in total?")

    if db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.client_id == client.id,
        models.DBLeaveRequest.status == "pending",
    ).count():
        out.append("Who has leave waiting for approval?")
    if db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).count():
        out.append("Who is off today?")
    if db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.client_id == client.id,
        models.DBDocumentRequest.status == "submitted",
    ).count():
        out.append("Which onboarding documents need reviewing?")
    if db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.client_id == client.id,
        models.DBJobRequisition.status == "open",
    ).count():
        out.append("What roles am I hiring for?")

    out.append("Summarise where the business stands today")
    return {"suggestions": out[:5]}


@router.get("/api/ai/insights")
def ai_insights(request: Request, db: Session = Depends(get_db)):
    """A short read on the business for the dashboard, from real figures."""
    client = get_client_user(request, db)
    ensure_can_afford(db, client.id, "ai_insights")

    context = build_business_context(db, client)
    result = llm_json([
        {"role": "system", "content":
            "You are a business analyst. Using ONLY the context, return JSON with: "
            "headline (one sentence on where the business stands), "
            "actions (list of up to 4 objects with 'text' and 'priority' of high|medium|low, "
            "each naming a specific figure or name from the context). "
            "Never invent data. Return ONLY valid JSON."},
        {"role": "user", "content": context},
    ])
    if not result:
        return {"available": False, "headline": "", "actions": []}
    charge_after_success(db, client.id, "ai_insights")
    return {
        "available": True,
        "headline": result.get("headline", ""),
        "actions": (result.get("actions") or [])[:4],
    }


@router.post("/api/ai/job-description")
def ai_job_description(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Draft a job advert from the requisition details."""
    client = get_client_user(request, db)
    body = body or {}
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="A job title is required")
    ensure_can_afford(db, client.id, "ai_job_description")

    detail = ", ".join(filter(None, [
        f"department: {body.get('department')}" if body.get("department") else "",
        f"level: {body.get('level')}" if body.get("level") else "",
        f"location: {body.get('location')}" if body.get("location") else "",
        f"work mode: {body.get('work_mode')}" if body.get("work_mode") else "",
        f"employment type: {body.get('employment_type')}" if body.get("employment_type") else "",
    ]))
    result = llm_json([
        {"role": "system", "content":
            "You write job adverts. Return ONLY valid JSON with keys: "
            "description (2-3 short paragraphs about the role and the team), "
            "requirements (list of 5-8 short bullet strings). "
            "Write plainly, avoid cliches, and do not invent salary, benefits or company history."},
        {"role": "user", "content":
            f"Company: {client.company_name or 'our company'}\nRole: {title}\n{detail}"},
    ])
    if not result:
        return {"available": False, "description": "", "requirements": []}
    charge_after_success(db, client.id, "ai_job_description", 1, title)
    return {
        "available": True,
        "description": as_text(result.get("description")),
        "requirements": as_list(result.get("requirements")),
    }


@router.post("/api/ai/brand-theme")
def ai_brand_theme(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Propose a whole branding theme instead of making somebody choose thirty
    settings one at a time.

    The colours come from the logo, not from the model - a palette sampled from
    the actual artwork is always closer than a guessed hex code, and it costs
    nothing. The model is used only for the wording, which is the part that
    genuinely needs writing: document titles, payment terms, a footer line.
    """
    client = get_client_user(request, db)
    body = body or {}

    # Sampled in the browser from the uploaded logo and posted here.
    palette = [valid_hex_colour(c, "") for c in (body.get("logo_colors") or [])]
    palette = [c for c in palette if c]

    industry = (body.get("industry") or client.industry or "").strip()[:80]
    tone = (body.get("tone") or "professional").strip()[:40]
    company = (client.company_name or "our company").strip()

    ensure_can_afford(db, client.id, "ai_brand_theme")

    result = llm_json([
        {"role": "system", "content":
            "You set the wording on a business's invoices. Return ONLY valid JSON "
            "with keys: approved_invoice_title, draft_invoice_title, quote_title, "
            "payment_terms, footer_note, rationale. "
            "Titles are short and conventional for the country and trade - most "
            "businesses want 'TAX INVOICE' or 'INVOICE', so do not be inventive. "
            "payment_terms is one or two plain sentences telling the customer how "
            "and by when to pay. footer_note is a single short line of thanks or "
            "contact detail. rationale is one sentence on why these suit the trade. "
            "Never invent a bank account, a registration number, a discount, or a "
            "number of days that was not given to you."},
        {"role": "user", "content":
            f"Business: {company}\nTrade: {industry or 'not stated'}\n"
            f"Tone wanted: {tone}"},
    ])

    if not result:
        return {"available": False, "reason": llm_error_message()}

    charge_after_success(db, client.id, "ai_brand_theme", 1, company)

    # The model never picks the colour. Sampling the logo keeps the invoice
    # matching the artwork the customer already recognises.
    suggestion = {
        "approved_invoice_title": as_text(result.get("approved_invoice_title"))[:60] or "TAX INVOICE",
        "draft_invoice_title": as_text(result.get("draft_invoice_title"))[:60] or "DRAFT INVOICE",
        "quote_title": as_text(result.get("quote_title"))[:60] or "QUOTE",
        "payment_terms": as_text(result.get("payment_terms"))[:600],
        "footer_note": as_text(result.get("footer_note"))[:200],
        "rationale": as_text(result.get("rationale"))[:300],
    }
    if palette:
        suggestion["brand_color"] = palette[0]
        suggestion["palette"] = palette[:5]

    return {"available": True, "suggestion": suggestion}


@router.post("/api/ai/interview-questions")
def ai_interview_questions(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Questions tailored to one candidate against one role."""
    client = get_client_user(request, db)
    body = body or {}
    job_title = (body.get("job_title") or "").strip()
    if not job_title:
        raise HTTPException(status_code=400, detail="A job title is required")
    ensure_can_afford(db, client.id, "ai_interview_questions")

    candidate = ""
    sub_id = body.get("submission_id")
    if sub_id:
        sub = db.query(models.DBFormSubmission).filter(
            models.DBFormSubmission.id == sub_id,
            models.DBFormSubmission.client_id == client.id,
        ).first()
        if sub:
            try:
                answers = json.loads(sub.answers or "{}")
                candidate = "\n".join(f"{k}: {v}" for k, v in answers.items())[:1500]
            except (ValueError, TypeError):
                candidate = ""

    result = llm_json([
        {"role": "system", "content":
            "You are an interviewer. Return ONLY valid JSON with key 'questions': a list of 6-8 objects, "
            "each with 'question', 'area' (technical|experience|behavioural|role fit) and "
            "'looking_for' (one line on what a good answer shows). "
            "Base them on the role and, where given, the candidate's own answers. "
            "Avoid anything touching age, health, family, religion or nationality."},
        {"role": "user", "content":
            f"Role: {job_title}\nRound: {body.get('round_name') or 'general interview'}\n"
            + (f"Candidate said:\n{candidate}" if candidate else "No candidate detail provided.")},
    ])
    if not result:
        return {"available": False, "questions": []}
    charge_after_success(db, client.id, "ai_interview_questions", 1, job_title)
    questions = result.get("questions") or []
    normalised = []
    for q in questions[:8]:
        if isinstance(q, dict):
            normalised.append({
                "question": as_text(q.get("question")),
                "area": as_text(q.get("area")),
                "looking_for": as_text(q.get("looking_for")),
            })
        else:
            normalised.append({"question": as_text(q), "area": "", "looking_for": ""})
    return {"available": True, "questions": normalised}


@router.post("/api/ai/describe-item")
def ai_describe_item(request: Request, body: dict = None, db: Session = Depends(get_db)):
    """Turn a rough note into a presentable invoice line description."""
    client = get_client_user(request, db)
    body = body or {}
    rough = (body.get("text") or "").strip()
    if not rough:
        raise HTTPException(status_code=400, detail="Write a few words first")
    ensure_can_afford(db, client.id, "ai_describe_item")

    answer = llm_chat([
        {"role": "system", "content":
            "Rewrite the user's rough note as a single clear invoice line description. "
            "One sentence, under 20 words, factual. Return only the description, no quotes or preamble. "
            "Do not invent quantities, prices or dates."},
        {"role": "user", "content": rough},
    ], temperature=0.3, max_tokens=60)
    if not answer:
        return {"available": False, "description": ""}
    charge_after_success(db, client.id, "ai_describe_item", 1, rough[:40])
    return {"available": True, "description": answer.strip().strip('"')}
