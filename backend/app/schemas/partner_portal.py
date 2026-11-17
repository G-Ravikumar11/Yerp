"""What the partner portal endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class PortalPasswordIn(BaseModel):
    token: str
    password: str


class PortalLoginIn(BaseModel):
    email: str
    password: str
    # The CAPTCHA, when the page has been asked for one (app/core/login_guard.py).
    captcha_token: Optional[str] = ""
    captcha_answer: Optional[str] = ""


class PortalDetailsIn(BaseModel):
    """The partner's own MSME status and bank account. msme_type: none | micro | small | medium."""
    msme_type: Optional[str] = None
    udyam_no: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
