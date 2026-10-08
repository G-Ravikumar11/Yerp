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

DEFAULT_DOCUMENT_REQUIREMENTS = [
    ("Photo ID", "Passport or driving licence", "identity", True, 3),
    ("Proof of right to work", "Visa, share code or citizenship document", "compliance", True, 3),
    ("Bank details", "So payroll can pay you", "finance", True, 5),
    ("Signed contract", "Your countersigned employment contract", "contract", True, 7),
    ("Proof of address", "Utility bill or bank statement from the last 3 months", "identity", False, 14),
]
