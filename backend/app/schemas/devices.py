"""What the app sends to register a phone for push."""
from pydantic import BaseModel, Field


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=4096)
    platform: str = Field(default="", max_length=20)
