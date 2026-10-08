"""What the superadmin endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class PricingRuleIn(BaseModel):
    action_key: Optional[str] = ""
    label: Optional[str] = ""
    description: Optional[str] = ""
    module: Optional[str] = "platform"
    unit_price: Optional[float] = 0.0
    free_allowance: Optional[int] = 0
    is_active: Optional[bool] = True
    sort_order: Optional[int] = 0
