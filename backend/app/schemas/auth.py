"""What the auth endpoints are sent."""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ClientRegister(BaseModel):
    email: str
    password: str
    company_name: Optional[str] = ""
    contact_name: Optional[str] = ""
    # The CAPTCHA, when the page has been asked for one (app/core/login_guard.py).
    captcha_token: Optional[str] = ""
    captcha_answer: Optional[str] = ""


class ClientLogin(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    email: str
    password: str
    remember_me: bool = Field(False, alias="rememberMe")
    # "app" when the phone app signs in (it holds the session to the app's limits); anything else is the website.
    channel: str = "web"
    # The CAPTCHA, when the page has been asked for one (app/core/login_guard.py).
    captcha_token: Optional[str] = ""
    captcha_answer: Optional[str] = ""


class ClientOnboard(BaseModel):
    company_name: Optional[str] = ""
    contact_name: Optional[str] = ""
    phone_number: Optional[str] = ""
    address: Optional[str] = ""
    website: Optional[str] = ""
    abn: Optional[str] = ""
    industry: Optional[str] = ""
    logo_url: Optional[str] = ""


class LogoUpdate(BaseModel):
    logo_url: str = ""


class ForgotPasswordIn(BaseModel):
    email: str
    # The CAPTCHA, when the page has been asked for one (app/core/login_guard.py).
    captcha_token: Optional[str] = ""
    captcha_answer: Optional[str] = ""


class ResetPasswordIn(BaseModel):
    token: str
    password: str
