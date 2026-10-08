"""The fixed lists, limits and statuses for client billing."""



RA_TRANSITIONS = {
    "DRAFT":     {"SUBMIT": "SUBMITTED", "CANCEL": "CANCELLED"},
    "SUBMITTED": {"CERTIFY": "CERTIFIED", "REJECT": "DRAFT", "CANCEL": "CANCELLED"},
    "CERTIFIED": {"PAY": "PAID", "CANCEL": "CANCELLED"},
    "PAID":      {},
    "CANCELLED": {},
}
# Only a draft may be recomputed. Once it has been submitted the quantities are
# what somebody is being asked to certify, and a bill that changes underneath
# an approver is worse than no bill.
RA_EDITABLE = ("DRAFT",)

# VARIATION ORDERS
#
# The measurement book already knows which lines ran past their ordered
# quantity - it prints "5 over the order" against them. Until now that was
# where it stopped, and extra work stayed done, measured and unpaid.
#
# A variation drafts itself from that flag: the app proposes the lines, the
# quantities and the money without anybody retyping them, and approving it
# raises the order so the over-run disappears and the work becomes billable.
VO_TRANSITIONS = {
    "DRAFT":     {"SUBMIT": "SUBMITTED", "CANCEL": "CANCELLED"},
    "SUBMITTED": {"APPROVE": "APPROVED", "REJECT": "DRAFT", "CANCEL": "CANCELLED"},
    "APPROVED":  {},
    "REJECTED":  {},
    "CANCELLED": {},
}

# WHAT NEEDS LOOKING AT: THE REST OF THE BUSINESS
#
# The Monday list was written before the ledger, the plant register, the
# tender pipeline, the enquiries and the programme existed, so none of what
# goes wrong in them reached it. A certified RA bill nobody has paid, a
# roller past its service, an EMD on a tender lost months ago, a bid due on
# Thursday, a slab that has pushed the handover - each was on its own
# screen and nowhere else.
RA_CREDIT_DAYS = 30
