"""What the settings endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class TaxRateIn(BaseModel):
    name: str
    percent: float = 0.0
    is_default: Optional[bool] = False


class TaxRatesIn(BaseModel):
    tax_rates: List[TaxRateIn]


class NotificationReadIn(BaseModel):
    ids: Optional[List[int]] = None
    all: Optional[bool] = False


class NotificationSettingsIn(BaseModel):
    emails: Optional[List[str]] = None
    whatsapp: Optional[List[str]] = None
    channels: Optional[dict] = None
    wa_phone_id: Optional[str] = None
    wa_token: Optional[str] = None
