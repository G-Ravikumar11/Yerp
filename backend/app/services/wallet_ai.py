"""The rules and workings behind the wallet ai endpoints."""
import os
from datetime import datetime

import httpx
from fastapi import HTTPException

from app import models

from app.constants.crm import OPEN_INVOICE_STATUSES
from app.constants.wallet_ai import DEFAULT_PRICING
from app.core.config import logger
from app.core.currency import (
    DEFAULT_CURRENCY,
    PLATFORM_CURRENCY,
    compute_invoice_totals,
    currency_symbol,
    to_major,
    to_minor,
)
from app.core.dates import _parse_date
from app.services.crm import invoice_overdue_days, quote_display_status


def seed_pricing_rules(db):
    """Make sure every known action has a price row, without disturbing any the
    operator has already edited."""
    existing = {r.action_key for r in db.query(models.DBPricingRule).all()}
    created = []
    for order, (key, label, module, price, allowance, desc) in enumerate(DEFAULT_PRICING):
        if key in existing:
            continue
        row = models.DBPricingRule(
            action_key=key, label=label, description=desc, module=module,
            unit_price_minor=price, currency=PLATFORM_CURRENCY,
            free_allowance=allowance, is_active=True, sort_order=order,
        )
        db.add(row)
        created.append(row)
    if created:
        db.flush()
    return created


def get_wallet(db, client_id, create=True):
    wallet = db.query(models.DBWallet).filter(models.DBWallet.client_id == client_id).first()
    if wallet or not create:
        return wallet
    wallet = models.DBWallet(
        client_id=client_id, balance_minor=0, currency=PLATFORM_CURRENCY,
        low_balance_minor=to_minor(os.getenv("WALLET_LOW_BALANCE", "5"), PLATFORM_CURRENCY),
    )
    db.add(wallet)
    db.flush()
    return wallet


def month_usage(db, client_id, action_key):
    """Units of one action already consumed this calendar month, for the free
    allowance."""
    prefix = datetime.now().strftime("%Y-%m")
    rows = db.query(models.DBWalletTransaction).filter(
        models.DBWalletTransaction.client_id == client_id,
        models.DBWalletTransaction.action_key == action_key,
        models.DBWalletTransaction.direction == "debit",
        models.DBWalletTransaction.created_at.like(prefix + "%"),
    ).all()
    return sum(r.quantity or 1 for r in rows)


def quote_action(db, client_id, action_key, quantity=1):
    """What an action would cost right now, after any free allowance.

    Returns (rule, chargeable_units, cost_minor). An unpriced or disabled
    action costs nothing, so metering can be rolled out gradually without
    blocking anyone.
    """
    rule = db.query(models.DBPricingRule).filter(
        models.DBPricingRule.action_key == action_key
    ).first()
    if not rule or not rule.is_active or rule.unit_price_minor <= 0:
        return rule, 0, 0
    quantity = max(1, int(quantity or 1))
    used = month_usage(db, client_id, action_key)
    remaining_free = max(0, (rule.free_allowance or 0) - used)
    chargeable = max(0, quantity - remaining_free)
    return rule, chargeable, chargeable * rule.unit_price_minor


class InsufficientCredit(Exception):
    def __init__(self, needed_minor, balance_minor, currency, label):
        self.needed_minor = needed_minor
        self.balance_minor = balance_minor
        self.currency = currency
        self.label = label
        super().__init__("Insufficient wallet balance")


def charge_wallet(db, client_id, action_key, quantity=1, reference="", performed_by=""):
    """Debit the wallet for one action.

    Raises InsufficientCredit when the balance will not cover it, so callers
    can refuse the action *before* doing the work rather than after.
    """
    rule, chargeable, cost = quote_action(db, client_id, action_key, quantity)
    if cost <= 0:
        return None

    wallet = get_wallet(db, client_id)
    if wallet.balance_minor < cost:
        raise InsufficientCredit(cost, wallet.balance_minor, wallet.currency, rule.label)

    wallet.balance_minor -= cost
    wallet.lifetime_spent_minor = (wallet.lifetime_spent_minor or 0) + cost
    wallet.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tx = models.DBWalletTransaction(
        client_id=client_id, wallet_id=wallet.id, direction="debit",
        amount_minor=cost, balance_after_minor=wallet.balance_minor,
        currency=wallet.currency, action_key=action_key,
        module=rule.module if rule else "", description=rule.label if rule else action_key,
        reference=reference, quantity=chargeable, performed_by=performed_by,
    )
    db.add(tx)
    return tx


def credit_wallet(db, client_id, amount_minor, description, reference="",
                  performed_by="", action_key="topup"):
    """Add credit. Used by successful payments and by operator adjustments."""
    amount_minor = int(amount_minor or 0)
    if amount_minor <= 0:
        raise HTTPException(status_code=400, detail="Credit amount must be greater than zero")
    wallet = get_wallet(db, client_id)
    wallet.balance_minor += amount_minor
    if action_key == "topup":
        wallet.lifetime_topped_up_minor = (wallet.lifetime_topped_up_minor or 0) + amount_minor
    wallet.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tx = models.DBWalletTransaction(
        client_id=client_id, wallet_id=wallet.id, direction="credit",
        amount_minor=amount_minor, balance_after_minor=wallet.balance_minor,
        currency=wallet.currency, action_key=action_key, module="platform",
        description=description, reference=reference, quantity=1,
        performed_by=performed_by,
    )
    db.add(tx)
    return tx


def insufficient_credit_response(exc):
    """One consistent 402 so the UI can always offer a top-up."""
    return HTTPException(
        status_code=402,
        detail=(
            f"Not enough wallet credit for {exc.label}. "
            f"Needs {currency_symbol(exc.currency)}{to_major(exc.needed_minor, exc.currency):.2f}, "
            f"balance is {currency_symbol(exc.currency)}{to_major(exc.balance_minor, exc.currency):.2f}. "
            "Top up your wallet to continue."
        ),
    )


def require_credit(db, client_id, action_key, quantity=1, reference="", performed_by=""):
    """Charge, converting the shortfall into the standard 402."""
    try:
        return charge_wallet(db, client_id, action_key, quantity, reference, performed_by)
    except InsufficientCredit as exc:
        raise insufficient_credit_response(exc)


def wallet_state(db, client, include_rules=True):
    wallet = get_wallet(db, client.id)
    data = {
        "balance": to_major(wallet.balance_minor, wallet.currency),
        "balance_minor": wallet.balance_minor,
        "currency": wallet.currency,
        "symbol": currency_symbol(wallet.currency),
        "low_balance": to_major(wallet.low_balance_minor, wallet.currency),
        "is_low": wallet.balance_minor <= (wallet.low_balance_minor or 0),
        "is_empty": wallet.balance_minor <= 0,
        "is_suspended": bool(wallet.is_suspended),
        "lifetime_topped_up": to_major(wallet.lifetime_topped_up_minor, wallet.currency),
        "lifetime_spent": to_major(wallet.lifetime_spent_minor, wallet.currency),
    }
    if include_rules:
        rules = db.query(models.DBPricingRule).filter(
            models.DBPricingRule.is_active == True
        ).order_by(models.DBPricingRule.sort_order.asc()).all()
        if not rules:
            rules = seed_pricing_rules(db)
            db.commit()
        data["pricing"] = [{
            "action_key": r.action_key, "label": r.label, "description": r.description,
            "module": r.module,
            "unit_price": to_major(r.unit_price_minor, r.currency),
            "free_allowance": r.free_allowance,
            "used_this_month": month_usage(db, client.id, r.action_key),
        } for r in rules]
    return data


def ensure_can_afford(db, client_id, action_key, quantity=1):
    """Check the wallet covers an action without debiting it.

    Used before work that can fail (an LLM call, an external API). Charging up
    front would bill the tenant for a failure; charging without checking first
    would let a tenant with no credit consume the upstream call anyway.
    """
    rule, chargeable, cost = quote_action(db, client_id, action_key, quantity)
    if cost <= 0:
        return 0
    wallet = get_wallet(db, client_id)
    if wallet.balance_minor < cost:
        raise insufficient_credit_response(
            InsufficientCredit(cost, wallet.balance_minor, wallet.currency,
                               rule.label if rule else action_key)
        )
    return cost


def charge_after_success(db, client_id, action_key, quantity=1, reference="", performed_by=""):
    """Debit and commit once the work has actually produced something.

    The AI endpoints previously charged before calling the model and never
    committed, so the debit was rolled back at the end of the request and the
    action was billed to nobody.
    """
    try:
        charge_wallet(db, client_id, action_key, quantity, reference, performed_by)
        db.commit()
    except InsufficientCredit:
        # Affordability was checked before the work; a shortfall here means the
        # balance moved underneath us. The work is already done, so log it
        # rather than failing the response.
        db.rollback()
        logger.warning("Could not bill %s for %s: balance changed mid-request", client_id, action_key)


def gateway_config():
    """Which providers are usable right now, based on the keys present."""
    return {
        "stripe": {
            "secret": os.getenv("STRIPE_SECRET_KEY", ""),
            "publishable": os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
            "webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET", ""),
        },
        "razorpay": {
            "key_id": os.getenv("RAZORPAY_KEY_ID", ""),
            "key_secret": os.getenv("RAZORPAY_KEY_SECRET", ""),
            "webhook_secret": os.getenv("RAZORPAY_WEBHOOK_SECRET", ""),
        },
        "paypal": {
            "client_id": os.getenv("PAYPAL_CLIENT_ID", ""),
            "secret": os.getenv("PAYPAL_SECRET", ""),
            "mode": os.getenv("PAYPAL_MODE", "sandbox"),
        },
    }


def enabled_providers():
    cfg = gateway_config()
    return {
        "stripe": bool(cfg["stripe"]["secret"]),
        "razorpay": bool(cfg["razorpay"]["key_id"] and cfg["razorpay"]["key_secret"]),
        "paypal": bool(cfg["paypal"]["client_id"] and cfg["paypal"]["secret"]),
    }


def provider_unavailable(name, missing):
    return HTTPException(
        status_code=503,
        detail=f"{name} is not configured on this server. Missing: {', '.join(missing)}.",
    )


def _create_stripe_checkout(order, client, request):
    cfg = gateway_config()["stripe"]
    if not cfg["secret"]:
        raise provider_unavailable("Stripe", ["STRIPE_SECRET_KEY"])
    base = str(request.base_url).rstrip("/")
    resp = httpx.post(
        "https://api.stripe.com/v1/checkout/sessions",
        auth=(cfg["secret"], ""),
        data={
            "mode": "payment",
            "success_url": f"{base}/next/?topup=success",
            "cancel_url": f"{base}/next/?topup=cancelled",
            "client_reference_id": str(order.id),
            "metadata[order_id]": str(order.id),
            "metadata[client_id]": str(client.id),
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": order.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(order.amount_minor),
            "line_items[0][price_data][product_data][name]": "Wallet top-up",
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.error("Stripe session failed: %s", resp.text[:400])
        raise HTTPException(status_code=502, detail="Stripe rejected the payment request.")
    data = resp.json()
    order.provider_order_id = data.get("id", "")
    order.checkout_url = data.get("url", "")
    return {"provider": "stripe", "checkout_url": data.get("url", ""), "session_id": data.get("id", "")}


def _create_razorpay_order(order, client):
    cfg = gateway_config()["razorpay"]
    missing = [k for k, v in (("RAZORPAY_KEY_ID", cfg["key_id"]), ("RAZORPAY_KEY_SECRET", cfg["key_secret"])) if not v]
    if missing:
        raise provider_unavailable("Razorpay", missing)
    resp = httpx.post(
        "https://api.razorpay.com/v1/orders",
        auth=(cfg["key_id"], cfg["key_secret"]),
        json={
            "amount": order.amount_minor,
            "currency": order.currency.upper(),
            "receipt": f"wallet-{order.id}",
            "notes": {"order_id": str(order.id), "client_id": str(client.id)},
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.error("Razorpay order failed: %s", resp.text[:400])
        raise HTTPException(status_code=502, detail="Razorpay rejected the payment request.")
    data = resp.json()
    order.provider_order_id = data.get("id", "")
    return {
        "provider": "razorpay",
        "razorpay_order_id": data.get("id", ""),
        "key_id": cfg["key_id"],
        "amount_minor": order.amount_minor,
        "name": client.company_name or "Wallet top-up",
        "prefill_email": client.email,
    }


def _paypal_base():
    return ("https://api-m.paypal.com" if gateway_config()["paypal"]["mode"] == "live"
            else "https://api-m.sandbox.paypal.com")


def _paypal_token():
    cfg = gateway_config()["paypal"]
    resp = httpx.post(
        f"{_paypal_base()}/v1/oauth2/token",
        auth=(cfg["client_id"], cfg["secret"]),
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.error("PayPal token failed: %s", resp.text[:300])
        raise HTTPException(status_code=502, detail="Could not authenticate with PayPal.")
    return resp.json().get("access_token", "")


def _create_paypal_order(order, client, request):
    cfg = gateway_config()["paypal"]
    missing = [k for k, v in (("PAYPAL_CLIENT_ID", cfg["client_id"]), ("PAYPAL_SECRET", cfg["secret"])) if not v]
    if missing:
        raise provider_unavailable("PayPal", missing)
    token = _paypal_token()
    base = str(request.base_url).rstrip("/")
    resp = httpx.post(
        f"{_paypal_base()}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": str(order.id),
                "custom_id": str(order.id),
                "description": "Wallet top-up",
                "amount": {
                    "currency_code": order.currency.upper(),
                    "value": f"{to_major(order.amount_minor, order.currency):.2f}",
                },
            }],
            "application_context": {
                "return_url": f"{base}/next/?topup=success",
                "cancel_url": f"{base}/next/?topup=cancelled",
            },
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        logger.error("PayPal order failed: %s", resp.text[:400])
        raise HTTPException(status_code=502, detail="PayPal rejected the payment request.")
    data = resp.json()
    order.provider_order_id = data.get("id", "")
    approve = next((l.get("href") for l in data.get("links", []) if l.get("rel") == "approve"), "")
    order.checkout_url = approve
    return {"provider": "paypal", "paypal_order_id": data.get("id", ""), "approve_url": approve}


def credit_topup_once(db, order, payment_id=""):
    """Credit a paid order exactly once.

    Gateways retry webhooks and users refresh return pages, so this is the
    single place that moves money and it is guarded by `credited`.
    """
    if order.credited:
        return False
    order.status = "paid"
    order.provider_payment_id = payment_id or order.provider_payment_id
    order.credited = True
    order.credited_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    credit_wallet(
        db, order.client_id, order.amount_minor,
        f"Top-up via {order.provider.title()}",
        reference=order.provider_payment_id or order.provider_order_id,
        performed_by=order.provider,
    )
    return True


# AI ASSISTANT
# A general assistant over a tenant's own data.
#
# The important constraint: it is *grounded*. Real figures are gathered first
# and passed in as context, and the model is told to answer only from them. An
# ungrounded chatbot pointed at business data will confidently invent balances
# and headcounts, which is worse than having no assistant at all.
def build_business_context(db, client):
    """A compact, factual snapshot of this tenant. Everything the assistant is
    allowed to reason about."""
    today = datetime.now().date()
    sym = currency_symbol(client.currency or DEFAULT_CURRENCY)

    invoices = db.query(models.DBInvoice).filter(models.DBInvoice.client_id == client.id).all()
    overdue = [i for i in invoices if invoice_overdue_days(i, today) > 0]
    outstanding = sum(i.due or 0 for i in invoices if i.status in OPEN_INVOICE_STATUSES)
    collected = sum(i.paid or 0 for i in invoices)

    employees = db.query(models.DBEmployee).filter(models.DBEmployee.client_id == client.id).all()
    active = [e for e in employees if e.status == "active"]
    onboarding = [e for e in employees if e.status == "onboarding"]

    pending_leave = db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.client_id == client.id,
        models.DBLeaveRequest.status == "pending",
    ).all()
    on_leave_today = []
    for l in db.query(models.DBLeaveRequest).filter(
        models.DBLeaveRequest.client_id == client.id,
        models.DBLeaveRequest.status == "approved",
    ).all():
        start, end = _parse_date(l.start_date), _parse_date(l.end_date)
        if start and end and start <= today <= end:
            emp = next((e for e in employees if e.id == l.employee_id), None)
            if emp:
                on_leave_today.append(f"{emp.first_name} {emp.last_name}")

    payslips = db.query(models.DBPayslip).filter(models.DBPayslip.client_id == client.id).all()
    unpaid_payslips = [p for p in payslips if p.status != "Paid"]

    # Added when quotes and recurring billing were built. Without these the
    # assistant answered questions about them by denying they existed.
    quotes = db.query(models.DBQuote).filter(models.DBQuote.client_id == client.id).all()
    open_quotes = [q for q in quotes if quote_display_status(q) in ("Draft", "Sent")]
    accepted_quotes = [q for q in quotes if quote_display_status(q) == "Accepted"]
    quote_value = sum(compute_invoice_totals(q.line_items, q.tax_type)[2] for q in open_quotes)
    recurring = db.query(models.DBRecurringInvoice).filter(
        models.DBRecurringInvoice.client_id == client.id,
        models.DBRecurringInvoice.is_active == True,      # noqa: E712
    ).all()

    open_jobs = db.query(models.DBJobRequisition).filter(
        models.DBJobRequisition.client_id == client.id,
        models.DBJobRequisition.status == "open",
    ).all()
    applications = db.query(models.DBFormSubmission).filter(
        models.DBFormSubmission.client_id == client.id
    ).all()

    wallet = get_wallet(db, client.id)
    outstanding_docs = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.client_id == client.id,
        models.DBDocumentRequest.status.in_(["pending", "rejected"]),
    ).count()
    awaiting_review = db.query(models.DBDocumentRequest).filter(
        models.DBDocumentRequest.client_id == client.id,
        models.DBDocumentRequest.status == "submitted",
    ).count()

    lines = [
        f"Company: {client.company_name or client.email}",
        f"Today: {today.isoformat()}",
        f"Currency: {client.currency or 'GBP'} ({sym})",
        "",
        "INVOICING",
        f"- Invoices: {len(invoices)} total, {sum(1 for i in invoices if i.status == 'Paid')} paid, "
        f"{sum(1 for i in invoices if i.status == 'Draft')} draft",
        f"- Outstanding: {sym}{outstanding:.2f}",
        f"- Collected all time: {sym}{collected:.2f}",
        f"- Overdue: {len(overdue)} invoice(s), {sym}{sum(i.due or 0 for i in overdue):.2f}",
    ]
    for i in sorted(overdue, key=lambda x: invoice_overdue_days(x, today), reverse=True)[:5]:
        lines.append(f"  - {i.number} to {i.to_contact}: {sym}{i.due:.2f}, "
                     f"{invoice_overdue_days(i, today)} days overdue, due {i.due_date}")

    lines += [
        "",
        "QUOTES AND RECURRING BILLING",
        f"- Quotes: {len(quotes)} total, {len(open_quotes)} still open "
        f"({sym}{quote_value:.2f}), {len(accepted_quotes)} accepted but not yet invoiced",
        f"- Recurring invoices running: {len(recurring)}",
        "",
        "PEOPLE",
        f"- Employees: {len(employees)} ({len(active)} active, {len(onboarding)} onboarding)",
        f"- Departments: {db.query(models.DBDepartment).filter(models.DBDepartment.client_id == client.id).count()}",
        f"- Pending leave requests: {len(pending_leave)}",
        f"- On approved leave today: {', '.join(on_leave_today) if on_leave_today else 'nobody'}",
        f"- Payslips: {len(payslips)} total, {len(unpaid_payslips)} not yet marked paid",
        f"- Onboarding documents outstanding: {outstanding_docs}, awaiting HR review: {awaiting_review}",
    ]
    for l in pending_leave[:5]:
        emp = next((e for e in employees if e.id == l.employee_id), None)
        if emp:
            lines.append(f"  - {emp.first_name} {emp.last_name}: {l.leave_type} "
                         f"{l.start_date} to {l.end_date} ({l.days} days)")

    lines += [
        "",
        "RECRUITMENT",
        f"- Open roles: {len(open_jobs)}",
        f"- Applications: {len(applications)}, hired: {sum(1 for a in applications if a.hired_employee_id)}",
    ]
    for j in open_jobs[:5]:
        lines.append(f"  - {j.reference} {j.title} ({j.location or 'no location set'})")

    lines += [
        "",
        "ACCOUNT",
        f"- Wallet balance: {currency_symbol(wallet.currency)}{to_major(wallet.balance_minor, wallet.currency):.2f}",
    ]
    return "\n".join(lines)


def as_text(value, separator=None):
    """Models legitimately return a multi-paragraph field as either a string
    or a list of strings. Accept both rather than dropping the content."""
    if separator is None:
        separator = chr(10) + chr(10)
    if isinstance(value, list):
        return separator.join(str(v).strip() for v in value if str(v).strip())
    return str(value or "").strip()


def as_list(value):
    """Same tolerance for fields that should be a list of short strings."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [line.strip(" -*") for line in text.splitlines() if line.strip(" -*")]
