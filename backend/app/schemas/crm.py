"""What the crm endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class LineItem(BaseModel):
    name: Optional[str] = ""
    description: str
    qty: float
    price: float
    disc: Optional[float] = 0.0
    account: Optional[str] = "200 - Sales"
    tax_rate: Optional[str] = "20% (VAT on Income)"

    class Config:
        from_attributes = True


# CUSTOMERS, PLACING AN ORDER, AND THE MD'S APPROVAL
#
# The last three steps of the contracts flow. A customer is the party a
# project belongs to; placing an order is the moment priced lines stop being a
# draft; and the inquiry screen is where the whole thing is signed off.
class CustomerIn(BaseModel):
    name: str
    contact_person: Optional[str] = ""
    email: Optional[str] = ""
    phone_number: Optional[str] = ""
    gstin: Optional[str] = ""
    pan: Optional[str] = ""
    address: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    pincode: Optional[str] = ""
    notes: Optional[str] = ""


# QUOTES - priced proposals that can become invoices
class QuoteCreate(BaseModel):
    contact: str
    email: Optional[str] = ""
    phone_number: Optional[str] = ""
    issue_date: str
    expiry_date: str
    quote_number: Optional[str] = ""
    reference: Optional[str] = ""
    line_items: List[LineItem]
    tax_type: Optional[str] = "exclusive"
    status: Optional[str] = "Draft"
    currency: Optional[str] = ""
    title: Optional[str] = ""
    summary: Optional[str] = ""
    terms: Optional[str] = ""
    job_id: Optional[int] = None


class SendQuoteEmail(BaseModel):
    logo_data: Optional[str] = ""
    pdf_data: Optional[str] = ""


class QuoteDecision(BaseModel):
    status: str


class QuoteConvert(BaseModel):
    issue_date: Optional[str] = ""
    due_date: Optional[str] = ""


class EstimateIn(BaseModel):
    title: str
    customer_name: Optional[str] = ""
    tender_reference: Optional[str] = ""
    due_on: Optional[str] = ""
    job_id: Optional[int] = None
    overhead_percent: Optional[float] = None
    profit_percent: Optional[float] = None
    notes: Optional[str] = ""


class EstimateItemIn(BaseModel):
    item_no: Optional[str] = ""
    fg_code: Optional[str] = ""
    description: str
    uom: Optional[str] = ""
    quantity: float = 0.0
    cost_rate: Optional[float] = None
    overhead_percent: Optional[float] = None
    profit_percent: Optional[float] = None


class RateLineIn(BaseModel):
    kind: str = "MATERIAL"
    item_code: Optional[str] = ""
    description: str
    uom: Optional[str] = ""
    quantity_per_unit: float = 0.0
    rate: float = 0.0
    wastage_percent: Optional[float] = 0.0


class LeadIn(BaseModel):
    title: str
    customer_name: Optional[str] = ""
    contact_person: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    location: Optional[str] = ""
    source: Optional[str] = ""
    tender_reference: Optional[str] = ""
    estimated_value: Optional[float] = 0
    site_visit_on: Optional[str] = ""
    prebid_on: Optional[str] = ""
    bid_due_on: Optional[str] = ""
    emd_amount: Optional[float] = 0
    emd_mode: Optional[str] = ""
    emd_reference: Optional[str] = ""
    emd_paid_on: Optional[str] = ""
    owner_name: Optional[str] = ""
    notes: Optional[str] = ""


class LeadMoveIn(BaseModel):
    status: str
    note: Optional[str] = ""
    lost_reason: Optional[str] = ""
    winning_bidder: Optional[str] = ""
    winning_price: Optional[float] = 0


class LeadActivityIn(BaseModel):
    kind: Optional[str] = "Note"
    note: str
    next_action: Optional[str] = ""
    next_on: Optional[str] = ""


class EmdReturnIn(BaseModel):
    returned_on: Optional[str] = ""
    note: Optional[str] = ""
