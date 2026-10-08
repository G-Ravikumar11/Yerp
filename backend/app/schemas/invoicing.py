"""What the invoicing endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.crm import LineItem


class InvoiceCreate(BaseModel):
    contact: str
    email: Optional[str] = ""
    phone_number: Optional[str] = ""
    issue_date: str
    due_date: str
    invoice_number: Optional[str] = ""
    reference: Optional[str] = ""
    line_items: List[LineItem]
    tax_type: Optional[str] = "exclusive"
    status: Optional[str] = "Draft"
    currency: Optional[str] = ""
    bank_details: Optional[str] = ""
    job_id: Optional[int] = None


class SendInvoiceEmail(BaseModel):
    logo_data: Optional[str] = ""
    pdf_data: Optional[str] = ""


class PaymentCreate(BaseModel):
    amount: float
    paid_on: Optional[str] = ""
    method: Optional[str] = "bank_transfer"
    reference: Optional[str] = ""
    note: Optional[str] = ""


class RecurringIn(BaseModel):
    name: Optional[str] = ""
    contact: str
    email: Optional[str] = ""
    phone_number: Optional[str] = ""
    reference: Optional[str] = ""
    line_items: List[LineItem]
    tax_type: Optional[str] = "exclusive"
    currency: Optional[str] = ""
    bank_details: Optional[str] = ""
    frequency: Optional[str] = "monthly"
    payment_terms_days: Optional[int] = 14
    next_run: str
    end_date: Optional[str] = ""
    is_active: Optional[bool] = True
    auto_send: Optional[bool] = False


class CompanyGstIn(BaseModel):
    gstin: Optional[str] = ""
    state_code: Optional[str] = ""


class EwayLineIn(BaseModel):
    item_code: Optional[str] = ""
    product_name: Optional[str] = ""
    hsn: Optional[str] = ""
    qty: Optional[float] = 0
    unit: Optional[str] = ""
    taxable: Optional[float] = 0
    tax_rate: Optional[float] = 0


class EwayIn(BaseModel):
    source_type: Optional[str] = "manual"
    source_ref: Optional[str] = ""
    from_key: Optional[str] = ""          # a place from /api/eway-places, or give the fields
    to_key: Optional[str] = ""
    from_name: Optional[str] = None
    from_gstin: Optional[str] = None
    from_address: Optional[str] = None
    from_pincode: Optional[str] = None
    from_state: Optional[str] = None
    to_name: Optional[str] = None
    to_gstin: Optional[str] = None
    to_address: Optional[str] = None
    to_pincode: Optional[str] = None
    to_state: Optional[str] = None
    supply_type: Optional[str] = "O"
    sub_type: Optional[str] = ""
    sub_type_desc: Optional[str] = ""
    doc_type: Optional[str] = ""
    doc_no: Optional[str] = ""
    doc_date: Optional[str] = ""
    distance_km: Optional[int] = 0
    trans_mode: Optional[str] = "1"
    vehicle_no: Optional[str] = ""
    vehicle_type: Optional[str] = "R"
    transporter_id: Optional[str] = ""
    transporter_name: Optional[str] = ""
    trans_doc_no: Optional[str] = ""
    trans_doc_date: Optional[str] = ""
    lines: Optional[List[EwayLineIn]] = None


class EwayGeneratedIn(BaseModel):
    ewb_no: str
    ewb_date: Optional[str] = ""
    valid_upto: Optional[str] = ""


class EwayVehicleIn(BaseModel):
    vehicle_no: str
    reason: Optional[str] = ""


class EwayCancelIn(BaseModel):
    reason: str
