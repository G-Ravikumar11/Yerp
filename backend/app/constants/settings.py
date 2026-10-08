"""The fixed lists, limits and statuses for settings."""
import re


# Settings keys that are the company itself. Saved here, they used to stay
# here: every RA bill, purchase order, statement and e-invoice reads the
# company record, so an address typed into Settings never reached a single
# document. They are written through to it.
SETTINGS_ON_THE_COMPANY = {"company_name": "company_name", "company_address": "address",
                           "company_phone": "phone_number"}

# TAX RATES - the list a tenant picks from when writing a line
# What every new tenant starts with. Chosen to render exactly the labels the
# app used before rates became editable, so nothing shifts under existing work.
# GST at the slabs a contractor bills and is billed at. The list this
# replaced was UK VAT - 20%, 5%, zero rated - left from the product the app
# grew out of, and every picker offered it to an Indian contractor.
DEFAULT_TAX_RATES = [
    ("GST", 18.0, True),
    ("GST", 12.0, False),
    ("GST", 5.0, False),
    ("GST", 28.0, False),
    ("No Tax", 0.0, False),
]
UK_TAX_RATES = [("VAT", 20.0), ("VAT", 5.0), ("Zero Rated", 0.0), ("No Tax", 0.0)]

# BRANDING THEMES - how invoices and quotes are presented
#
# Presentation only: nothing here changes what is owed. A theme is stored once
# and applied at render time, so editing it restyles every past document too
# rather than leaving a trail of differently-shaped PDFs.
LOGO_POSITIONS = ("left", "center", "right")
TAX_BREAKDOWNS = ("combined", "separate_rates", "separate_components")
ADDRESS_POSITIONS = ("default", "window_envelope")
# jsPDF ships three core families. Offering a font the renderer does not have
# would silently fall back and quietly change every invoice.
THEME_FONTS = ("helvetica", "times", "courier")
THEME_BOOLS = (
    "show_item", "show_quantity", "show_price", "show_discount", "show_tax",
    "exclude_zero_rates", "always_show_currency_code", "show_conversion_rate",
    "show_text_links", "show_qr_code", "show_page_numbers",
)
THEME_STRINGS = (
    "label_item", "label_description", "label_quantity", "label_price",
    "label_discount", "label_tax", "label_amount",
    "approved_invoice_title", "draft_invoice_title", "quote_title",
    "payment_terms", "footer_note",
)

#
# Photos, drawings and documents live in the database, so they are what makes it grow. Two kinds of thing
# are no use to anyone: files whose record has been deleted (their bytes stayed behind), and bell alerts
# long since read. The owner is shown both, with what clearing them frees, and clears them on purpose.
OLD_ALERT_DAYS = 90

# A FULL BACKUP, IN THE OWNER'S HANDS
#
# Everything the business has put into the app - every project, bill,
# measurement, diary day, payment and chat - as one download the owner can
# keep on their own disk. Nothing here restores it; this is the copy that
# makes the database not the only place the business exists.
#
# Each table the company owns, found by walking the schema rather than by a
# list, so a table added next year is in next year's backup without anybody
# remembering to add it. JSON for a machine to read back, CSV to open in a
# spreadsheet. Photos and drawings on request, because they are the bulk of
# it. Passwords, tokens and keys are left out: a backup is a file that gets
# copied about, and it must not be a way into the app.
BACKUP_SKIP_TABLES = {"password_resets", "admin_users", "super_admins", "code_sequences",
                      "job_runs", "pricing_rules"}
BACKUP_SECRET = re.compile(r"password|(^|_)token(_|$)|secret|api_?key|access_key|private_key|(^|_)otp(_|$)", re.I)
