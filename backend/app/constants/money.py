"""The fixed lists, limits and statuses for money."""



# WHERE THE MONEY IS, PER PROJECT
#
# Every figure in this system already exists somewhere - an order here, a bill
# there, a budget on a third screen. What nobody could do was see them on one
# line and answer the only question that matters on a running job: are we
# still making money on it.
# Contracting cost headings. A builder's costs do not sort into "office
# supplies" and "software"; they sort into who or what the money went on, and
# every cost report downstream is grouped by these.
COST_CATEGORIES = [
    ("labour", "Labour"),
    ("materials", "Materials"),
    ("subcontract", "Subcontract"),
    ("plant", "Plant & equipment"),
    ("other", "Other"),
]
COST_CATEGORY_KEYS = [c for c, _ in COST_CATEGORIES]
# Older bills carry the generic headings the app shipped with. Mapping them
# rather than migrating keeps history readable without rewriting anyone's data.
COST_CATEGORY_ALIASES = {
    "general": "other", "office": "other", "software": "other",
    "utilities": "other", "rent": "plant", "marketing": "other",
    "travel": "other", "professional": "subcontract",
    "material": "materials", "labor": "labour", "equipment": "plant",
    "hire": "plant", "sub": "subcontract",
}

# MONEY OWED, BOTH WAYS - AND THE RETENTION NOBODY CHASES
#
# The app could say what a project earned and what it cost. It could not say
# who owes what today, how long they have owed it, or how much of the money
# already earned is being held back as retention.
#
# On a contract that last one is the quiet killer: five per cent of every
# certified bill sits with the client, it is never invoiced, nobody diaries
# it, and a contractor can finish a job several lakhs down without once
# seeing the figure written anywhere.
AGEING_BUCKETS = ("Not due", "0-30", "31-60", "61-90", "90+")

# FINANCE: SUPPLIERS, RECEIPTS, PAYMENTS, LEDGERS, THE BANK BOOK
#
# A bill was paid or it was not. Part of a bill could not be paid, so a part-
# payment lived in a notebook; nothing said what a party owed across all their
# bills, so a statement of account lived in Tally; and nothing said what was
# in the bank, so that lived there too. This is those three books, kept from
# the documents that are already here, so none of them is typed twice.
MONEY_MODES = ("Bank transfer", "Cheque", "Cash", "UPI", "Adjustment")
PARTY_TYPES = ("client", "supplier", "contractor", "other")

# Money that moves with no bill behind it, as a site office pays it: diesel at the pump, the lorry, the room rent,
# tea for the gang. Each goes out on an expense voucher under one of these heads, charged to the project it was for;
# a bill with GST on it goes in as a supplier bill instead, so the input credit is claimed. Labour gangs are paid on
# their RA bills and staff on the payroll, so neither is a head here: paid again here they would be counted twice.
EXPENSE_HEADS = (
    "Site expenses", "Diesel & fuel", "Machinery hire", "Transport & freight", "Repairs & maintenance",
    "Rent", "Electricity & water", "Staff welfare & food", "Travel & conveyance", "Printing & stationery",
    "Telephone & internet", "Professional & legal fees", "Bank charges", "Insurance", "Taxes & govt fees",
    "Security", "Office expenses", "Other expenses",
)
# Money that comes in with no bill of ours behind it.
INCOME_HEADS = ("Scrap sale", "Interest received", "Deposit refunded", "Insurance claim", "Rent received", "Other income")
# Vouchers that are nobody's account: an expense or a sundry receipt, and money moved between our own bank and cash
# (a contra). They are in the bank book and the day's vouchers, never in a party's ledger.
NO_PARTY_DOCS = ("expense", "income", "contra")

ASSET_STATUSES = ("Available", "Deployed", "Under repair", "Disposed")
