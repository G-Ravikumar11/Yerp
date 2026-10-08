"""What the wallet ai endpoints are sent."""
from pydantic import BaseModel


class TopUpIn(BaseModel):
    amount: float
    provider: str


class AssistantQuery(BaseModel):
    question: str
