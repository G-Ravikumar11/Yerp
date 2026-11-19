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
    # As on an expense voucher: taxable or non_taxable; a taxable one local or non_local (from a GST state code); the GST rate in
    # percent the amount includes; and for a bank transfer the payee's bank, account number and IFSC.
    tax: Optional[str] = None
    supply: Optional[str] = None
    supply_state: Optional[str] = None
    gst_rate: Optional[float] = None
    payee_bank: Optional[str] = None
    payee_account: Optional[str] = None
    payee_ifsc: Optional[str] = None
