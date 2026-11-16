"""What the recurring-payment form sends. Left out (None) on a change keeps what it was."""
from typing import Optional

from pydantic import BaseModel


class RecurringPaymentIn(BaseModel):
    payee: Optional[str] = None
    head: Optional[str] = None
    amount: Optional[float] = None
    day_of_month: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    job_id: Optional[int] = None
    account_id: Optional[int] = None
    mode: Optional[str] = None
    note: Optional[str] = None
