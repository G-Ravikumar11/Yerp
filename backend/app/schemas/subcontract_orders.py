"""What the subcontract orders endpoints are sent."""
from typing import Dict, List, Optional

from pydantic import BaseModel


class BusinessUnitIn(BaseModel):
    name: str
    code: Optional[str] = ""
    gstin: Optional[str] = ""
    pan: Optional[str] = ""
    address: Optional[str] = ""
    logo_url: Optional[str] = ""


class ContractorIn(BaseModel):
    company_name: str
    vendor_code: Optional[str] = ""
    contact_person: Optional[str] = ""
    email: Optional[str] = ""
    phone_number: Optional[str] = ""
    pan: Optional[str] = ""
    gst_number: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
    address: Optional[str] = ""
    # The rest of the Sub Contractor Registration Form. None on an update
    # means "not on this form" - the quick-add from a work order sends only
    # the name and tax numbers, and must not blank the rest.
    registered_project: Optional[str] = None
    joining_date: Optional[str] = None
    pin_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    nature_of_work: Optional[str] = None
    entity_type: Optional[str] = None
    aadhaar: Optional[str] = None
    bank_branch: Optional[str] = None
    documents: Optional[List[str]] = None
    document_files: Optional[Dict[str, Optional[Dict[str, str]]]] = None
    declaration_signed: Optional[bool] = None


class WorkTypeIn(BaseModel):
    name: str
    code: Optional[str] = ""
    department: Optional[str] = ""
    request_reason: Optional[str] = ""


class ProjectBudgetIn(BaseModel):
    code: Optional[str] = ""
    name: str
    department: Optional[str] = ""
    allocated_amount: float = 0
    notes: Optional[str] = ""
    # The order the budget is being set from, when it is - so the limit on a contractor without GST reaches it too.
    order_id: Optional[int] = None


class WorkOrderHeadIn(BaseModel):
    business_unit_id: Optional[int] = None
    contractor_id: Optional[int] = None
    job_id: Optional[int] = None
    department: Optional[str] = ""
    work_type: Optional[str] = ""
    subject: Optional[str] = ""
    scope_of_work: Optional[str] = ""
    commencement_date: Optional[str] = ""
    completion_date: Optional[str] = ""
    duration_months: Optional[float] = 0
    defect_liability_months: Optional[int] = 0
    bank_guarantee_applicable: Optional[bool] = False
    bank_guarantee_amount: Optional[float] = 0
    bank_guarantee_validity: Optional[str] = ""
    gst_rate: Optional[float] = 18.0
    tds_rate: Optional[float] = 1.0
    retention_percent: Optional[float] = 0
    mobilization_advance_percent: Optional[float] = 0
    advance_recovery_percent: Optional[float] = 0
    labour_cess_percent: Optional[float] = 0
    billing_cycle: Optional[str] = ""
    payment_days: Optional[int] = 0


class BoqLineIn(BaseModel):
    activity_no: Optional[str] = ""
    item_code: Optional[str] = ""
    item_description: str
    technical_spec: Optional[str] = ""
    uom: Optional[str] = ""
    quantity: float = 0
    unit_rate: float = 0
    budget_id: Optional[int] = None
    cost_centre: Optional[str] = ""
    is_header: Optional[bool] = False
    tolerance_percent: Optional[float] = 0
    # The line of the project BOQ it is part of.
    boq_key: Optional[str] = ""


class BoqIn(BaseModel):
    lines: List[BoqLineIn]


class TermIn(BaseModel):
    clause_category: str
    clause_text: str


class TermsIn(BaseModel):
    terms: List[TermIn]


class WoActionIn(BaseModel):
    comments: Optional[str] = ""
    # Approve an order that overruns its project allocation anyway. Deliberate
    # and recorded: the reason goes into the approval history beside the
    # figures it overran.
    override: Optional[bool] = False


class ChargeBudgetIn(BaseModel):
    budget_id: int
    only_blank: Optional[bool] = True
