"""What the loan forms send."""
from typing import Optional

from pydantic import BaseModel


class LoanIn(BaseModel):
    lender: Optional[str] = None
    name: Optional[str] = None
    kind: Optional[str] = "secured"
    principal: Optional[float] = None
    annual_rate: Optional[float] = None
    months: Optional[int] = None                 # the number of monthly instalments
    first_due: Optional[str] = None
    emi: Optional[float] = None                  # the bank's own EMI, when it is not the standard one
    existing: Optional[bool] = False             # already running before these books began
    taken_on: Optional[str] = None               # the day the money was received, or (existing) the day the balance stood at
    account_id: Optional[int] = None             # where the money was received (a new loan)
    mode: Optional[str] = None
    reference: Optional[str] = None
    note: Optional[str] = None


class InstalmentIn(BaseModel):
    """What the bank charged, where it differs from the schedule: the day, and how the instalment splits."""
    due_on: Optional[str] = None
    principal: Optional[float] = None
    interest: Optional[float] = None
