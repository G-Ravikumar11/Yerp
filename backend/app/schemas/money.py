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
