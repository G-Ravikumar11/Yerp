"""The fixed lists, limits and statuses for common."""
import os


# One business per install. Registration is how that business is created, so
# it is open until it has been - and shut afterwards. Set to 1 only if this
# install is genuinely meant to host more than one company.
ALLOW_SELF_REGISTRATION = os.getenv("ALLOW_SELF_REGISTRATION", "0") == "1"

#
# What the allocation is read back as. Grouped under the item that was sold,
# because the question being asked of it is never "what did we buy" but "what
# does this line cost us against what we are charging for it".
BUDGET_REPORT_HEADERS = ["Ordered Items", "RM code - Description", "Quantity",
                         "Units", "Price", "WO Qty", "Total Amount"]

# SIGNING IN WITH GOOGLE
#
# Separate from the Gmail connection under /api/auth/*, which asks for
# permission to send mail on a tenant's behalf. This asks only who somebody is.
# Keeping them apart means granting one never quietly grants the other.
GOOGLE_SIGNIN_SCOPES = "openid email profile"

# Days past due at which a chase goes out. Each rung is sent at most once.
REMINDER_LADDER = (1, 7, 14, 30)

PAYROLL_EXCLUDED_STATUSES = ("terminated", "inactive")

PAYSLIP_PAY_INPUTS = (
    "hours_worked", "overtime_hours", "overtime_rate", "basic_salary",
    "bonus", "allowances", "tax_amount", "insurance", "retirement", "other_deductions",
)
PAYSLIP_META_FIELDS = ("period_start", "period_end", "pay_date", "notes", "status")

# What a purchase order may be. Set here rather than accepted from the form,
# so a typo cannot invent a state nothing else in the system understands.
PURCHASE_ORDER_STATUSES = ("Draft", "Awaiting Approval", "Approved",
                           "Rejected", "Closed", "Cancelled")

# HR decides what a new starter must provide; the employee uploads it from
# their own portal; HR reviews it. The requirement is the template, the request
# is one person's obligation against it.
DOC_REQUEST_STATUSES = ("pending", "submitted", "approved", "rejected")

# GOODS RECEIPT AND THE THREE-WAY MATCH
#
# A purchase order says what was agreed. A bill says what is being charged.
# Neither says what actually came off the lorry, and without that third number
# nobody can tell the difference between a supplier who delivered and a
# supplier who invoiced. The receipt note supplies it, and the match report
# puts the three side by side.
GRN_TRANSITIONS = {
    "DRAFT":     {"POST": "POSTED", "CANCEL": "CANCELLED"},
    # A posted receipt is not editable. Somebody has asserted that this is what
    # arrived, and a bill is about to be paid against it.
    "POSTED":    {"CANCEL": "CANCELLED"},
    "CANCELLED": {},
}
GRN_EDITABLE = ("DRAFT",)

# STOCK AND MATERIAL CONTROL
#
# The item master said what may be bought and the goods receipt said what
# arrived. Nothing said what is in the store, what went out to site, or what
# is left - so material could be received, paid for, and quietly walk off
# without a single figure changing anywhere in the app.
#
# Every movement is a signed row and the balance is their sum, the same shape
# as the measurement book. A miscount is corrected by posting the correction,
# never by editing history.
STOCK_KINDS = ("RECEIPT", "ISSUE", "RETURN", "ADJUSTMENT", "TRANSFER_OUT", "TRANSFER_IN")

TRADES = ("Mason", "Helper", "Carpenter", "Bar bender", "Fitter", "Electrician",
          "Plumber", "Painter", "Operator", "Driver", "Surveyor", "Supervisor")

SUB_TRANSITIONS = {
    "DRAFT":     {"SUBMIT": "SUBMITTED", "CANCEL": "CANCELLED"},
    "SUBMITTED": {"CERTIFY": "CERTIFIED", "REJECT": "DRAFT", "CANCEL": "CANCELLED"},
    "CERTIFIED": {"PAY": "PAID", "CANCEL": "CANCELLED"},
    "PAID":      {},
    "CANCELLED": {},
}

HARDCOPY_TYPES = ("application/pdf", "image/jpeg", "image/png")

# STORES: SITE TO SITE, AND MATERIAL CHARGED TO A GANG
#
# Cement left over at one site is sent to the next; that is a transfer, not
# consumption, and it moves at what the stock cost rather than at a new price.
# Material handed to a gang whose rate includes it is theirs to pay for: it is
# recovered from their next bill on its own, up to what that bill can bear,
# and the project is credited back so the same cement is not counted twice.
TRANSFER_KINDS = ("TRANSFER_OUT", "TRANSFER_IN")

DRAWING_STATUSES = ("For information", "For approval", "Approved", "Good for construction", "Superseded")

# SAFETY: INCIDENTS, TOOLBOX TALKS AND PERMITS TO WORK
#
# A near miss written down is the cheapest lesson a site will ever get; the
# same one not written down is the next accident. Every incident is logged
# with what was done and why it happened, the morning toolbox talk with who
# stood through it, and dangerous work - hot work, heights, confined spaces -
# only on a permit that says until when, on which precautions, and is closed
# when the work stops.
INCIDENT_KINDS = ("Near miss", "First aid", "Medical treatment", "Lost time injury",
                  "Property damage", "Dangerous occurrence", "Fatality")

PERMIT_PRECAUTIONS = {
    "Work at height": ["Full body harness, anchored", "Scaffold tagged and inspected", "Guard rails and toe boards",
                       "Safety net or fall arrest below", "Area below barricaded", "Ladders tied and footed"],
    "Hot work": ["Combustibles cleared 11 m around", "Fire extinguisher at hand", "Fire watch posted, stays 30 min after",
                 "Gas cylinders upright, flashback arrestors fitted", "Welding screens in place"],
    "Confined space": ["Atmosphere tested - oxygen, gas", "Forced ventilation running", "Standby person at the entry",
                       "Rescue tripod and harness ready", "Entry and exit logged"],
    "Excavation": ["Underground services located and marked", "Shoring or benching per depth", "Spoil kept 1 m back from the edge",
                   "Edge barricaded and lit", "Ladder within reach every 30 m", "Dewatering arranged"],
    "Electrical isolation": ["Isolated at source", "Locked and tagged out", "Tested dead before touching",
                             "Earthed", "Authorised electrician only"],
    "Lifting": ["Crane certificate and operator licence checked", "Load within the chart", "Slings and shackles inspected",
                "Tag lines on the load", "Area cleared under the lift", "Signaller appointed"],
}

# RETENTION RELEASED
#
# The register above says how much is being held. This is what brings it
# back: a release on the client at practical completion or at the end of the
# defects period, and the same thing the other way for the gangs whose
# retention we hold. A release is a bill in its own right - it goes in the
# party's ledger, is received or paid through the same box as any other, ages
# in what is owed, and carries the GST the RA bills left off, because each of
# them charged tax only on what it asked for after the retention came off.
RETENTION_STAGES = ("Practical completion", "End of defects period",
                    "Against a bank guarantee", "Part release")

# THE PARTNER PORTAL
#
# "Has my bill been passed? When is the money coming?" is most of the phone
# calls a site office takes from gangs and suppliers. Each of them can now
# sign in and see it for themselves: their orders, their bills and where each
# one is, what has been paid and when, and a running statement. A supplier
# can send an invoice in, which lands as a draft for the office to check.
#
# Kept apart from every other login. A portal session carries only its own
# key, signing in clears any office or staff session in that browser, and
# every query below is filtered by the company and by the party - there is no
# route here that takes another party's id.
PORTAL_PARTY_TYPES = ("contractor", "supplier")
PORTAL_INVITE_DAYS = 7
PORTAL_INVOICE_TYPES = ("application/pdf", "image/jpeg", "image/png", "image/webp")

# PROJECT CHAT
#
# A site runs on conversation: the pour moved to Thursday, the client's
# engineer wants the cover blocks checked, here is a photo of the crack. It
# happened in WhatsApp groups - one per site, per trade, per mood - where it
# could not be found a month later and left with whoever left the company.
#
# Here each project has threads, each thread a subject, and everybody signed
# in to the business can take part: the owner, the office, and the site staff
# on their phones. Photos go in beside the words. Naming somebody with @ puts
# it on the bell, and each person's unread count is their own.
CHAT_MAX_BODY = 4000

# READ A SHEET, FIX IT HERE, THEN SAVE
#
# Lines arrive in Excel - a client's BOQ, a supplier's quotation. Read straight
# into a document they either all went in or nothing did, and a sheet with one
# bad row meant opening Excel again, fixing it blind and uploading again.
#
# Here a sheet is only read: every row comes back, the good and the bad, each
# with what is wrong with it, and nothing is saved. The rows land in a grid in
# the app where they are corrected, added to or struck out, and it is the
# ordinary save of the document that commits them. One reader, one template
# per kind of line; the grid on the screen is shared too.
IMPORT_SHEETS = {
    "po_lines": {
        "title": "Purchase order lines",
        "columns": [("item_code", "Item Code"), ("description", "Description"), ("uom", "UOM"),
                    ("qty", "Qty"), ("price", "Rate")],
        "aliases": {
            "item_code": ["itemcode", "code", "materialcode", "rmcode", "sku", "erpcode"],
            "description": ["description", "item", "itemname", "material", "materialname", "particulars",
                            "name", "specification"],
            "uom": ["uom", "unit", "units", "unitofmeasure", "measure"],
            "qty": ["qty", "quantity", "orderqty", "reqqty", "requiredqty"],
            "price": ["rate", "price", "unitrate", "unitprice", "basicrate"],
        },
        "numbers": ("qty", "price"),
        "example": ["", "OPC 53 grade cement", "Bags", "400", "385"],
    },
    "bills": {
        "title": "Supplier bills",
        # Deliberately loose: whatever a supplier's own statement or an
        # accountant's own workbook happens to call these columns, in
        # whatever order, is read the same way - not one fixed template.
        "columns": [("vendor_name", "Vendor"), ("amount", "Amount"), ("tax_amount", "Tax"),
                    ("issue_date", "Bill Date"), ("due_date", "Due Date"), ("reference", "Reference")],
        "aliases": {
            "vendor_name": ["vendor", "vendorname", "supplier", "suppliername", "party", "partyname",
                            "payee", "billedby", "from", "company"],
            "amount": ["amount", "basic", "basicamount", "value", "billamount", "billamt", "subtotal",
                      "taxable", "taxablevalue", "grossamount", "invoiceamount", "invoiceamt", "netamount"],
            "tax_amount": ["tax", "taxamount", "gst", "gstamount", "vat", "igst"],
            "issue_date": ["date", "billdate", "issuedate", "invoicedate", "billeddate"],
            "due_date": ["duedate", "paymentdue", "payby", "duedt"],
            "reference": ["reference", "ref", "invoiceno", "billno", "invoicenumber",
                         "billnumber", "description", "notes", "particulars"],
        },
        "numbers": ("amount", "tax_amount"),
        "example": ["Sri Sai Steels", "50000", "9000", "2026-09-01", "2026-09-30", "INV-1145"],
    },
    "subcontract_orders": {
        "title": "Subcontract work orders",
        "columns": [("contractor", "Contractor"), ("project", "Project"), ("department", "Department"),
                    ("subject", "Subject"), ("commencement_date", "Start Date"), ("completion_date", "End Date")],
        "aliases": {
            "contractor": ["contractor", "subcontractor", "vendor", "vendorname", "gang", "party",
                          "company", "contractorname", "agency"],
            "project": ["project", "job", "site", "projectname", "jobname", "sitename"],
            "department": ["department", "dept", "trade", "discipline"],
            "subject": ["subject", "scope", "description", "workdescription", "particulars", "title",
                       "scopeofwork"],
            "commencement_date": ["startdate", "commencementdate", "fromdate", "start", "commencement"],
            "completion_date": ["enddate", "completiondate", "todate", "end", "duedate", "completion"],
        },
        "numbers": (),
        "example": ["Rani Labour Contractors", "Kokapet Towers", "Civil", "Shuttering, tower C",
                    "2026-11-01", "2027-03-31"],
    },
}
