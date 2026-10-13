"""The fixed lists, limits and statuses for approvals."""
from app import models


# A bill raised by a member of staff walks up the reporting line. The status on
# the bill mirrors where it has got to, so finance never has to read the chain
# to know whether they may pay it.
BILL_AWAITING_APPROVAL = "Awaiting Approval"
BILL_APPROVED_FOR_PAYMENT = "Approved for payment"
BILL_REJECTED = "Rejected"
PO_AWAITING_APPROVAL = "Awaiting Approval"
PO_APPROVED = "Approved"
PO_REJECTED = "Rejected"
WO_AWAITING_APPROVAL = "Awaiting Approval"
WO_APPROVED = "Approved"
WO_REJECTED = "Rejected"
APPROVAL_MODELS = {
    "invoice": models.DBInvoice,
    "bill": models.DBBill,
    "purchase_order": models.DBPurchaseOrder,
    "work_order": models.DBWorkOrder,
}
APPROVAL_ENTITY_TYPES = tuple(APPROVAL_MODELS)

AUTO_BELOW_KEY = "approval_auto_below"
FINANCE_ABOVE_KEY = "approval_finance_above"

#
# The certificate of payment is signed in a row: Prepared By (the QS or site
# engineer who drew it up), Certified By (the Head QS), Approved By (the site
# incharge). So certifying is not one click by anybody allowed to: the bill
# climbs the same route a work order does - the manager set for whoever sent
# it, then one person at each rank above, someone on the same site first -
# and is certified only when the last of them signs. The owner may sign at
# any point, and that is the last word; whether the owner must also sign
# every gang bill is a setting, on unless switched off (Settings > Approval rules).
SUB_BILL_OWNER_SIGNS_KEY = "sub_bill_owner_signs"

#
# Approvals used to live in five places: the reporting-line chain (bills,
# purchase orders, client work orders), the subcontract order's provisional
# state, RA bills and subcontractor bills waiting to be certified, variations
# waiting to be agreed, and leave. Each told somebody in its own way, or told
# nobody. The inbox below reads all of them for whoever is asking, and the
# decide route sends each decision back through that document's own rules.
# The right that approves each kind of paper on the reporting-line chain.
APPROVE_RIGHT = {"bill": "bills.approve", "purchase_order": "bills.approve",
                 "invoice": "bills.approve", "work_order": "subcontracts.approve"}

GONE_STATUSES = ("terminated", "inactive", "resigned", "left")

CHAIN_KIND = {"bill": ("Bill", "bills-view"), "purchase_order": ("Purchase order", "orders-view"),
              "work_order": ("Client work order", "workorders-view"), "invoice": ("Invoice", "invoices-view")}

#
# A work order is signed at every level above the person who raised it - the
# order form's own signature row: prepared, proposed, recommended, authorised.
# The route is fixed when the order is sent: the manager set for the raiser
# first, then one person at each rank above (someone on the same site first),
# and the owner last unless the owner has chosen not to sign every order.
WO_OWNER_SIGNS_KEY = "wo_owner_signs"
