"""The fixed lists, limits and statuses for crm."""



OPEN_INVOICE_STATUSES = ("Awaiting Payment", "Sent", "Partially Paid", "Overdue")

SALES_STAGES = [
    ("drafted",  "Drafted",   "Not sent to anyone yet"),
    ("sent",     "Sent",      "Waiting on the customer"),
    ("accepted", "Accepted",  "Agreed, not yet invoiced"),
    ("invoiced", "Invoiced",  "Owed but not paid"),
    ("paid",     "Paid",      "Money in"),
]

QUOTE_STATUSES = ("Draft", "Sent", "Accepted", "Declined", "Expired", "Invoiced")

# ESTIMATION - THE FRONT OF THE CHAIN
#
# The chain used to start at a signed work order. Half of a contracting
# business happens before that: a tender arrives, somebody builds a rate for
# every item from material, labour, plant and overhead, adds a margin and
# submits a price. Win it and that priced schedule IS the work order - so
# winning creates one, line for line, with nothing retyped.
EST_TRANSITIONS = {
    "DRAFT":     {"SUBMIT": "SUBMITTED", "WITHDRAW": "WITHDRAWN"},
    "SUBMITTED": {"WIN": "WON", "LOSE": "LOST", "WITHDRAW": "WITHDRAWN", "REOPEN": "DRAFT"},
    "WON":       {},
    "LOST":      {"REOPEN": "DRAFT"},
    "WITHDRAWN": {"REOPEN": "DRAFT"},
}
RATE_KINDS = ("MATERIAL", "LABOUR", "PLANT", "OTHER")

# SALES: THE TENDER PIPELINE AND THE EMD REGISTER
#
# A tender before it is an estimate: the notice, the site visit, the pre-bid
# meeting, the bid date, and the earnest money sitting with the client. It
# becomes an estimate with one click, and the estimate's win or loss comes
# back to it - so the pipeline, the hit rate and the EMDs still out are all
# read from the same place the pricing is done.
LEAD_STATUSES = ("NEW", "QUALIFIED", "ESTIMATING", "SUBMITTED", "WON", "LOST", "DROPPED")
LEAD_OPEN = ("NEW", "QUALIFIED", "ESTIMATING", "SUBMITTED")
LEAD_SOURCES = ("Tender portal", "Client enquiry", "Referral", "Repeat client", "Newspaper", "Other")
EMD_MODES = ("DD", "BG", "Online", "FDR", "Cash", "Exempt")
