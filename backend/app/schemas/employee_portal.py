"""What the employee portal endpoints are sent."""
from typing import Optional

from pydantic import BaseModel


class EmployeeDocumentUpload(BaseModel):
    file_name: str
    file_type: Optional[str] = ""
    file_data: str
    expires_on: Optional[str] = ""
