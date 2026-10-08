"""Prepaid credit, what things cost, and top-ups."""
from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String

from app.db.session import Base


# WALLET & BILLING
# Balances are held in integer minor units (pence, cents, paise). A wallet has
# to reconcile exactly, and repeated float arithmetic on a running balance
# drifts; the rest of the app uses floats because invoice totals are recomputed
# from their lines rather than accumulated.
class DBWallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, unique=True, index=True)
    balance_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")
    low_balance_minor = Column(Integer, default=500)      # warn under this
    is_suspended = Column(Boolean, default=False)
    lifetime_topped_up_minor = Column(Integer, default=0)
    lifetime_spent_minor = Column(Integer, default=0)
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBWalletTransaction(Base):
    """Append-only ledger. `balance_after_minor` is stored on every row so the
    running balance can be audited against the wallet at any point."""
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True, index=True)

    direction = Column(String, default="debit", index=True)   # credit | debit
    amount_minor = Column(Integer, default=0)
    balance_after_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")

    action_key = Column(String, default="", index=True)       # which billable action
    module = Column(String, default="", index=True)           # invoicing | hr | platform
    description = Column(String, default="")
    reference = Column(String, default="")                    # invoice number, payslip id...
    quantity = Column(Integer, default=1)

    performed_by = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), index=True)


class DBPricingRule(Base):
    """What each billable action costs. Set by the platform operator, not by
    tenants."""
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    action_key = Column(String, nullable=False, unique=True, index=True)
    label = Column(String, nullable=False)
    description = Column(String, default="")
    module = Column(String, default="platform", index=True)   # invoicing | hr | platform
    unit_price_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")
    free_allowance = Column(Integer, default=0)               # free units per calendar month
    is_active = Column(Boolean, default=True, index=True)
    sort_order = Column(Integer, default=0)
    updated_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


class DBTopUpOrder(Base):
    """A payment attempt against a gateway. Kept even when it fails, so a
    disputed or duplicated payment can be traced."""
    __tablename__ = "topup_orders"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    provider = Column(String, default="", index=True)         # stripe | razorpay | paypal | manual
    amount_minor = Column(Integer, default=0)
    currency = Column(String, default="INR")

    status = Column(String, default="created", index=True)    # created|pending|paid|failed|cancelled
    provider_order_id = Column(String, default="", index=True)
    provider_payment_id = Column(String, default="", index=True)
    checkout_url = Column(String, default="")
    failure_reason = Column(String, default="")

    credited = Column(Boolean, default=False)                 # guards double-crediting
    credited_at = Column(String, default="")
    created_at = Column(String, default=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
