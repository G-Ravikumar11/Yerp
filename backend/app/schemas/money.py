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


class RequestPayIn(BaseModel):
    """Paying an approved request: only how and when; what and to whom were approved."""
    paid_on: Optional[str] = ""
    mode: Optional[str] = ""
    reference: Optional[str] = ""
    account_id: Optional[int] = None
    amount: Optional[float] = None         # less than approved, if only part is paid now


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
