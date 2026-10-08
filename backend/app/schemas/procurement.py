"""What the procurement endpoints are sent."""
from typing import List, Optional

from pydantic import BaseModel


class GRNIn(BaseModel):
    purchase_order_id: int
    received_on: Optional[str] = ""
    challan_number: Optional[str] = ""
    invoice_number: Optional[str] = ""
    vehicle_number: Optional[str] = ""
    store_location: Optional[str] = ""
    inspected_by: Optional[str] = ""
    remarks: Optional[str] = ""


class GRNLineIn(BaseModel):
    id: Optional[int] = None
    received_qty: Optional[float] = 0.0
    accepted_qty: Optional[float] = None
    rejected_qty: Optional[float] = None
    rejection_reason: Optional[str] = ""


class GRNUpdateIn(BaseModel):
    received_on: Optional[str] = None
    challan_number: Optional[str] = None
    invoice_number: Optional[str] = None
    vehicle_number: Optional[str] = None
    store_location: Optional[str] = None
    inspected_by: Optional[str] = None
    remarks: Optional[str] = None
    lines: Optional[List[GRNLineIn]] = None


class GRNActionIn(BaseModel):
    comments: Optional[str] = ""


class SupplierIn(BaseModel):
    name: str
    contact_person: Optional[str] = ""
    phone: Optional[str] = ""
    email: Optional[str] = ""
    gstin: Optional[str] = ""
    pan: Optional[str] = ""
    address: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
    payment_days: Optional[int] = 30
    supplies: Optional[str] = ""
    is_active: Optional[bool] = True


# PURCHASE: ENQUIRY, QUOTES, THE COMPARATIVE STATEMENT, THE AWARD
#
# The question put to three or four suppliers, their answers, and the sheet
# that lays them side by side - lowest per line and lowest landed overall -
# then the award, which becomes the purchase orders without a figure being
# typed twice. Choosing anybody but the lowest has to say why, because that
# is the line an auditor reads first.
class RfqLineIn(BaseModel):
    item_code: Optional[str] = ""
    description: str
    uom: Optional[str] = ""
    qty: float


class RfqIn(BaseModel):
    title: str
    job_id: Optional[int] = None
    needed_by: Optional[str] = ""
    notes: Optional[str] = ""
    lines: List[RfqLineIn]


class QuoteLineIn(BaseModel):
    rfq_line_id: int
    rate: float
    tax_percent: Optional[float] = 18.0
    remarks: Optional[str] = ""


class QuoteIn(BaseModel):
    supplier_name: str
    quote_ref: Optional[str] = ""
    quote_date: Optional[str] = ""
    delivery_days: Optional[int] = 0
    payment_terms: Optional[str] = ""
    freight: Optional[float] = 0
    valid_until: Optional[str] = ""
    notes: Optional[str] = ""
    lines: List[QuoteLineIn]


class AwardIn(BaseModel):
    mode: Optional[str] = "lowest_per_line"     # lowest_per_line | one_supplier | per_line
    supplier_name: Optional[str] = ""
    awards: Optional[List[dict]] = None          # per_line: [{rfq_line_id, supplier_name}]
    reason: Optional[str] = ""
    needed_by: Optional[str] = ""
