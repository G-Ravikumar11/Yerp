"""The fixed lists, limits and statuses for invoicing."""
import re


# RECURRING INVOICES and OVERDUE REMINDERS - the work that happens on its own
RECURRING_FREQUENCIES = ("weekly", "monthly", "quarterly", "yearly")

# E-INVOICE: THE RA BILL IN THE GOVERNMENT'S SCHEMA
#
# A certified RA bill laid out as the e-invoice JSON (schema 1.1) that the
# Invoice Registration Portal accepts - seller, buyer, one item per line of
# the bill, the deductions as each line's discount so the taxable value is
# the one the bill charged GST on, and the tax split the way the bill split
# it. Uploaded to the portal it comes back with an IRN; asking the portal
# directly needs the business's own API credentials from a GSP, which this
# app does not hold. What it will not do is produce a file the portal would
# reject: whatever is missing is named instead.
# Units of measure as the GST portal spells them (UQC).
UQC = {"cum": "CBM", "sqm": "SQM", "rmt": "MTR", "Meters": "MTR", "Nos": "NOS", "Sets": "SET",
       "MT": "MTS", "Quintal": "QTL", "Kgs": "KGS", "Bags": "BAG", "Litres": "LTR", "KL": "KLR",
       "sqft": "SQF", "cft": "CCM", "Days": "OTH", "Hours": "OTH", "Months": "OTH",
       "Lot": "OTH", "Job": "OTH", "Brass": "OTH"}

# E-WAY BILLS
#
# Goods worth more than fifty thousand rupees do not go on the road without an
# e-way bill - a site-to-site transfer of the contractor's own cement as much
# as a sale. The bill is laid out here from the movement it covers, written
# as the file the NIC portal takes in bulk, and once the portal has issued it
# its number and validity are recorded against the movement. What the portal
# would refuse is named before the file is written, not after.
EWAY_THRESHOLD = 50000.0
# NIC sub-supply types a contractor meets.
EWAY_SUB_TYPES = {"1": "Supply", "4": "Job work", "5": "For own use", "6": "Job work returns",
                  "7": "Sales return", "8": "Others"}
EWAY_DOC_TYPES = {"CHL": "Delivery challan", "INV": "Tax invoice", "BIL": "Bill of supply",
                  "OTH": "Others"}
EWAY_MODES = {"1": "Road", "2": "Rail", "3": "Air", "4": "Ship"}

VEHICLE_NO = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$|^TM[A-Z0-9]{6}$")

# E-INVOICE: WHAT THE PORTAL GAVE BACK
#
# The file goes up to the Invoice Registration Portal and an IRN comes back,
# with an acknowledgement and a QR code the portal has signed. A B2B invoice
# without that QR printed on it is not a valid tax invoice, so the three are
# kept against the bill and the QR goes on the print.
#
# The QR is the portal's own signed statement of what it registered - the
# seller, the buyer, the invoice number, the value and the IRN - so it is
# read before it is accepted. A response pasted against the wrong bill is
# refused with what does not match, rather than printed on a bill it does
# not belong to. (Its signature is the portal's to vouch for; reading it
# needs no key, checking the signature would need NIC's.)
EINVOICE_DOC_TYPES = ("ra_bill", "retention_release")
IRN_CANCEL_HOURS = 24
