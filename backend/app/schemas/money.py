"""What the money endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class BankAccountIn(BaseModel):
    name: str
    kind: Optional[str] = "Bank"
    bank_name: Optional[str] = ""
    account_no: Optional[str] = ""
    ifsc: Optional[str] = ""
    opening_balance: Optional[float] = 0
    opening_date: Optional[str] = ""


class BankAccountEditIn(BaseModel):
    """What may be corrected on an account; anything left out stays as it is."""
    name: Optional[str] = None
    bank_name: Optional[str] = None
    account_no: Optional[str] = None
    ifsc: Optional[str] = None
    opening_balance: Optional[float] = None
    opening_date: Optional[str] = None
    is_active: Optional[bool] = None


class MoneyLockIn(BaseModel):
    locked_upto: Optional[str] = ""        # YYYY-MM-DD, or empty to reopen


class MoneyIn(BaseModel):
    doc_type: Optional[str] = ""          # ra_bill | sub_bill | supplier_bill | on_account
    doc_id: Optional[int] = None
    amount: float
    paid_on: Optional[str] = ""
    mode: Optional[str] = "Bank transfer"
    reference: Optional[str] = ""
    account_id: Optional[int] = None
    note: Optional[str] = ""
    # On account only: who, and which way.
    direction: Optional[str] = ""
    party_type: Optional[str] = ""
    party_name: Optional[str] = ""
    job_id: Optional[int] = None
    # An expense voucher or a sundry receipt (doc_type "expense" / "income"): the head it is booked under.
    head: Optional[str] = ""
    # The approved payment request this payment settles, where payments need approval.
    request_id: Optional[int] = None


class PaymentRulesIn(BaseModel):
    on: bool = False
    free_below: Optional[float] = 0
    md_above: Optional[float] = 100000
    valid_days: Optional[int] = None       # an approval not paid within this many days expires; None leaves it as it is


class RequestPayIn(BaseModel):
    """Paying an approved request: only how and when; what and to whom were approved."""
    paid_on: Optional[str] = ""
    mode: Optional[str] = ""
    reference: Optional[str] = ""
    account_id: Optional[int] = None
    amount: Optional[float] = None         # less than approved, if only part is paid now


class SiteCashExpenseIn(BaseModel):
    """A payment made out of a site's cash box, as the site entered it."""
    account_id: int
    amount: float
    head: str
    paid_to: str
    spent_on: Optional[str] = ""
    note: Optional[str] = ""
    bill_no: Optional[str] = ""
    job_id: Optional[int] = None


class CashBoxIn(BaseModel):
    """A cash box set up as a site's imprest: the site, who holds it, and its float."""
    job_id: Optional[int] = None
    custodian_id: Optional[int] = None
    imprest_amount: Optional[float] = 0


class LineMatchIn(BaseModel):
    entry_id: int


class LineBookIn(BaseModel):
    """A line the bank booked on its own (charges, interest), booked in the books from the line."""
    head: str
    note: Optional[str] = ""


class ClearIn(BaseModel):
    cleared_on: Optional[str] = ""          # blank: not cleared after all


class TallySettingsIn(BaseModel):
    """The company's own Tally ledger names (by key), and the name of the company in Tally."""
    ledgers: Optional[dict] = None
    company: Optional[str] = ""


class PaymentDecisionIn(BaseModel):
    decision: str                       # approve | reject
    note: Optional[str] = ""


class TransferIn(BaseModel):
    """Money moved between our own accounts: cash drawn from the bank for a site, or deposited back."""
    from_account_id: int
    to_account_id: int
    amount: float
    paid_on: Optional[str] = ""
    mode: Optional[str] = ""
    reference: Optional[str] = ""
    note: Optional[str] = ""
