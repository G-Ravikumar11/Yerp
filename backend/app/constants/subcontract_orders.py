"""The fixed lists, limits and statuses for subcontract orders."""
import re


WO_COLUMNS = ["fg_code", "item_name", "description", "qty", "uom", "rate"]
WO_HEADERS = ["FG Code", "Item Name", "Description", "Qty", "UOM", "Rate"]

# SUBCONTRACT WORK ORDERS
#
# The order issued out to a subcontractor: a BOQ, the clauses the trade argues
# over, statutory deductions, and a signature chain. Separate from the sales
# side work order, which prices scope sold to a customer.
# The only moves anybody can make. Written as a map rather than scattered
# through the endpoints, because "can this order be approved" is a question
# asked in four places and must not have four answers.
WO_TRANSITIONS = {
    "DRAFT":       {"SUBMIT": "PROVISIONAL", "CANCEL": "CANCELLED"},
    "PROVISIONAL": {"APPROVE": "APPROVED", "REJECT": "DRAFT", "CANCEL": "CANCELLED"},
    "APPROVED":    {"EXECUTE": "EXECUTED", "AMEND": "AMENDED", "CANCEL": "CANCELLED"},
    "EXECUTED":    {"AMEND": "AMENDED"},
    "AMENDED":     {},
    "CANCELLED":   {},
}
# Only a draft may be edited. Once submitted, the figures are what somebody is
# being asked to sign off, and they must not move underneath them.
WO_EDITABLE = ("DRAFT",)
WO_DEPARTMENTS = ("Civil", "STP", "Electrical", "Mechanical", "Plumbing", "Finishing")

# The only markup a scope of work may carry. Bold, italic, breaks and bullets
# are what somebody writing a scope actually reaches for; everything else is
# either decoration or an attack. The list is deliberately also the set
# ReportLab's Paragraph understands, so what is written on the screen is what
# comes out of the printer rather than an error halfway through a page.
WO_RICH_TAGS = ("b", "i", "u", "br", "ul", "ol", "li", "p")
_WO_TAG = re.compile(r"</?\s*([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")

# The clause headings this trade argues over, in the order they are read.
WO_CLAUSE_CATEGORIES = (
    "Scope of Work", "Mode of Measurement", "Rates and Taxes",
    "Payment Milestones", "Mobilization Advance", "Retention and Security",
    "Electricity and Water Supply", "Labour Hutment and Welfare",
    "Materials and Wastage", "Safety and Statutory Compliance",
    "Programme and Liquidated Damages", "Defect Liability",
    "Termination", "Arbitration and Jurisdiction", "General",
)

# The documents the registration form asks for, in its order.
REGISTRATION_DOCUMENTS = (("gst", "A) GST Certificate"), ("pan", "B) PAN Card"), ("aadhaar", "C) Aadhar Card"),
                          ("photos", "D) PassPort Size Photos 2Nos"), ("cheque", "E) Cancelled Cheque"),
                          ("esi_pf", "F) ESI & PF Reg (if any)"))
REGISTRATION_FIELDS = ("registered_project", "joining_date", "pin_code", "city", "state", "nature_of_work",
                       "entity_type", "aadhaar", "bank_branch")

#
# Administering the list is a different right from using it. Whoever
# provisions users and their permissions owns the taxonomy; an engineer
# raising orders can ask for a type but cannot mint one, because a list
# anybody may add to is free text with extra steps and the same trade ends up
# filed under four spellings.
WO_DEFAULT_WORK_TYPES = (
    ("CIV-SUP", "Civil - supply and commissioning", "Civil"),
    ("CIV-LAB", "Civil - labour only", "Civil"),
    ("CIV-CMP", "Civil - composite (material and labour)", "Civil"),
    ("STP-MEC", "STP - mechanical erection", "STP"),
    ("STP-CIV", "STP - civil works", "STP"),
    ("ELE-INT", "Electrical - internal wiring", "Electrical"),
    ("ELE-EXT", "Electrical - external and substation", "Electrical"),
    ("MEC-HVA", "Mechanical - HVAC", "Mechanical"),
    ("PLU-INT", "Plumbing - internal", "Plumbing"),
    ("FIN-PNT", "Finishing - painting", "Finishing"),
    ("FIN-FLR", "Finishing - flooring and tiling", "Finishing"),
)

#
# An order in one of these states has committed the money. A draft has not -
# pricing something up is how you find out it is too expensive, so a draft may
# be any figure at all. Cancelled and superseded orders release what they
# held, without anybody having to remember to release it.
WO_COMMITTED_STATUSES = ("PROVISIONAL", "APPROVED", "EXECUTED")

WO_BILLING_CYCLES = ("", "Monthly", "Fortnightly", "On milestone", "On completion")

# The head fields worth recording a change to. Named in the words the change
# history shows, because "completion_date" on a history line reads as a
# database and "Completion" reads as a decision.
WO_TRACKED = (
    ("contractor_id", "Contractor"), ("job_id", "Project"), ("work_type", "Work type"),
    ("subject", "Subject"), ("commencement_date", "Commencement"),
    ("completion_date", "Completion"), ("defect_liability_months", "Defect liability"),
    ("gst_rate", "GST %"), ("tds_rate", "TDS %"), ("retention_percent", "Retention %"),
    ("mobilization_advance_percent", "Mobilization advance %"),
    ("advance_recovery_percent", "Advance recovery %"),
    ("labour_cess_percent", "Labour cess %"), ("billing_cycle", "Billing cycle"),
    ("payment_days", "Payment days"), ("bank_guarantee_applicable", "Bank guarantee"),
    ("bank_guarantee_amount", "BG amount"), ("department", "Department"),
)

# What each move reads as once it has happened. Spelled out rather than built
# by adding "ed" to the verb, which produced "it cannot be approveed from
# there" - on the message somebody gets when they are already confused about
# why the button did not work.
WO_ACTION_PAST = {
    "SUBMIT": "submitted", "APPROVE": "approved", "REJECT": "sent back",
    "EXECUTE": "executed", "CANCEL": "cancelled", "AMEND": "amended",
}

# A sub contractor with no GST registration may not be given an order worth more than this.
UNREGISTERED_VENDOR_LIMIT = 1950000.0

#
# Cancelling keeps the record; deleting removes it, and everything that hangs
# off it, from every screen. It is the owner's alone. An order that has money
# behind it is refused: the payments are in the ledger and the bank book, and
# taking the order away would leave them standing against nothing.
# Rows that belong to an order and go with it, whether or not their link column may be empty.
OWNED_BY_AN_ORDER = {
    "retention_releases", "measurement_dimensions", "material_recoveries", "sub_bill_lines", "sub_measurements",
    "sub_bills", "measurements", "ra_bills", "ra_bill_lines", "variation_orders", "variation_lines",
    "work_order_lines", "bom_lines", "subcontract_items", "subcontract_terms", "subcontract_approvals", "order_access",
}

_FK_CACHE = {}

WIPE_PHRASE = "DELETE ALL WORK ORDERS"

# What a person may attach to a contractor's registration form.
DOCUMENT_UPLOAD_TYPES = ("application/pdf", "image/jpeg", "image/png", "image/webp")

REGISTRATION_DECLARATION = (
    "I declare that the information I have provided is correct to the best of my knowledge. "
    "I understand and agree to the terms of the \u2018Contract for Services\u2019.",
    "I agree to follow the Health & Safety guidance given overleaf (a full copy of the guide is "
    "available from %s upon request).",
    "I agree to inform immediately if i change any personal details such as bank details or address "
    "or contact numbers.",
    "I have provided the required documentation & Photo ID (See below)")
