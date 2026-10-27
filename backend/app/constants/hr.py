"""The fixed lists, limits and statuses for hr."""
import re

from app.core.permissions import PERMISSION_ROLES


# ONBOARDING PIPELINE - hiring through to a working employee
DEFAULT_ONBOARDING_ITEMS = [
    ("Sign employment contract", "Legal", "HR"),
    ("Provide government-issued ID", "Legal", "HR"),
    ("Submit bank details for payroll", "Finance", "Finance"),
    ("Provide emergency contact information", "General", "HR"),
    ("Company policy acknowledgment", "Compliance", "HR"),
    ("IT equipment setup", "Technical", "IT"),
    ("Email and system access setup", "Technical", "IT"),
    ("Introduction to team members", "Social", "Manager"),
    ("Complete tax withholding forms (W-4)", "Finance", "Finance"),
    ("Review employee handbook", "Compliance", "HR"),
]

ONBOARDING_STAGES = [
    ("paperwork", "Documents requested", "Waiting on the new starter"),
    ("review", "In review", "Waiting on HR"),
    ("setup", "Setup", "Checklist still running"),
    ("ready", "Ready to start", "Nothing outstanding"),
]

PERMISSION_ROLE_CODES = {r["code"] for r in PERMISSION_ROLES}

# Staff sign in with an address the business issues, not a personal one. HR
# sets the domain once; from then on new accounts are created against it and
# the login is something the business can take back when somebody leaves.
ORG_DOMAIN_KEY = "org_email_domain"
_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

EMPLOYEE_MONEY_FIELDS = {
    "salary": "Salary", "hourly_rate": "Hourly rate", "deductions": "Deductions",
    "allowances": "Allowances", "bonus": "Bonus",
}

# What a new starter is asked to upload (a photo or a PDF). None is compulsory: the only thing onboarding insists on is an
# emergency contact (see onboarding_snapshot). HR can make any of these mandatory in Settings.
DEFAULT_DOCUMENT_REQUIREMENTS = [
    ("Aadhaar card", "A clear photo or PDF of your Aadhaar card", "identity", False, 7),
    ("PAN card", "A clear photo or PDF of your PAN card", "identity", False, 7),
    ("UAN (EPF) details", "Your UAN card, or a page of your EPF passbook that shows the number", "finance", False, 7),
    ("Passport-size photo", "A recent photo of your face", "identity", False, 7),
    ("Bank details", "A cancelled cheque or the first page of your passbook, so payroll can pay you", "finance", False, 7),
    ("Signed contract", "Your countersigned employment contract", "contract", False, 7),
]

GENDERS = ("Male", "Female", "Other", "Prefer not to say")


def emergency_contact_required():
    """On unless REQUIRE_EMERGENCY_CONTACT=0 (the shared test setup, which creates people in bulk without one)."""
    import os
    return os.getenv("REQUIRE_EMERGENCY_CONTACT", "1") != "0"
