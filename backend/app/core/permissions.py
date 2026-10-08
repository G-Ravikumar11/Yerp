"""Levels, roles and what each role may do in the portal."""



# TEAM - more than one person per business
# owner  - everything, and the only role that can manage the team
# admin  - everything else, including billing and the wallet
# viewer - read-only
TEAM_ROLES = ("owner", "admin", "viewer")

# `level` is the seniority band; `role` is the person's place in the reporting
# line. They are deliberately separate: a senior engineer (L4) and a team lead
# can be the same band but different roles.
EMPLOYEE_LEVELS = [
    {"code": "L1", "label": "L1 - Intern / Trainee", "rank": 1},
    {"code": "L2", "label": "L2 - Junior", "rank": 2},
    {"code": "L3", "label": "L3 - Mid", "rank": 3},
    {"code": "L4", "label": "L4 - Senior", "rank": 4},
    {"code": "L5", "label": "L5 - Lead", "rank": 5},
    {"code": "L6", "label": "L6 - Principal / Manager", "rank": 6},
    {"code": "L7", "label": "L7 - Director", "rank": 7},
    {"code": "L8", "label": "L8 - Executive", "rank": 8},
]
LEVEL_CODES = {lvl["code"] for lvl in EMPLOYEE_LEVELS}
LEVEL_RANK = {lvl["code"]: lvl["rank"] for lvl in EMPLOYEE_LEVELS}
EMPLOYEE_ROLES = [
    {"code": "employee", "label": "Employee"},
    {"code": "team_lead", "label": "Team Lead"},
    {"code": "manager", "label": "Manager"},
    {"code": "department_head", "label": "Department Head"},
    {"code": "hr_admin", "label": "HR Admin"},
    {"code": "executive", "label": "Executive"},
]
ROLE_CODES = {r["code"] for r in EMPLOYEE_ROLES}


# HR decides this per employee. It is kept apart from `role` (the reporting
# line) and `level` (seniority) on purpose: on a contracting business the
# person who signs off costs, the person who runs the crew and the person who
# is most senior are frequently three different people.
PORTAL_PERMISSIONS = [
    {"key": "self.service", "group": "Everyone",
     "label": "Own timesheet, payslips, leave and documents"},
    {"key": "bills.submit", "group": "Costs",
     "label": "Raise a bill or expense for approval"},
    {"key": "bills.approve", "group": "Costs",
     "label": "Approve bills from people who report to them"},
    {"key": "bills.view_all", "group": "Costs",
     "label": "See every bill in the business"},
    {"key": "bills.pay", "group": "Costs",
     "label": "Release payment on an approved bill"},
    {"key": "invoices.manage", "group": "Sales",
     "label": "Raise and send invoices and quotes"},
    {"key": "reports.view", "group": "Sales",
     "label": "View financial reports"},
    {"key": "attendance.view_team", "group": "People",
     "label": "See the team's attendance"},
    {"key": "leave.approve", "group": "People",
     "label": "Approve leave requests"},
    {"key": "people.manage", "group": "People",
     "label": "Add and edit employees, and set what they can do"},
    {"key": "payroll.manage", "group": "People",
     "label": "Run payroll and issue payslips"},
    {"key": "recruitment.manage", "group": "People",
     "label": "Manage jobs, candidates and offers"},
    {"key": "items.manage", "group": "Contracts",
     "label": "Maintain the item master of material and finished goods codes"},
    {"key": "workorders.manage", "group": "Contracts",
     "label": "Raise work orders and allocate their budgets"},
    {"key": "customers.manage", "group": "Contracts",
     "label": "Add and edit customers"},
    {"key": "subcontracts.approve", "group": "Contracts",
     "label": "Approve subcontract work orders for execution"},
    # Deliberately not part of any preset below except the owner's. Whoever
    # holds it signs off work that somebody else priced, and a right that
    # arrives with a job title is one nobody remembers deciding to give.
    {"key": "workorders.approve", "group": "Contracts",
     "label": "Give final approval on a work order (MD sign-off)"},
    # Receiving is its own job, done by whoever is at the gate when the lorry
    # arrives - usually not the person who raised the order and never the one
    # who pays the bill. Kept separate so those three signatures stay apart.
    {"key": "stores.receive", "group": "Contracts",
     "label": "Record goods received against a purchase order"},
    # The departments' own work, split out of "workorders.manage", which had
    # grown to cover tenders, stock, purchasing and GST alike - so that giving
    # a storekeeper the store also gave them the tender book.
    {"key": "billing.manage", "group": "Planning & Billing",
     "label": "Tenders, estimates, RA bills to the client, variations and subcontractor bills"},
    {"key": "purchase.manage", "group": "Purchase",
     "label": "Enquiries, quote comparison, purchase orders and the supplier list"},
    {"key": "stores.manage", "group": "Stores",
     "label": "Issue, transfer and adjust stock, and keep the plant and machinery register"},
    {"key": "accounts.manage", "group": "Accounts",
     "label": "GST, e-invoices, e-way bills, fixed assets and retention release"},
    # The site's own record. Held by the people who are on the site, not only
    # by whoever manages the contract - a diary is written by the engineer
    # standing in the rain, and it could not be while writing it needed the
    # right to manage work orders.
    {"key": "site.record", "group": "Site",
     "label": "Record site work - diary, measurements, photos, quality, safety, plant and material"},
    {"key": "site.signoff", "group": "Site",
     "label": "Sign off site work - diary days, permits to work, incidents, inspections and NCRs"},
]
PERMISSION_KEYS = {p["key"] for p in PORTAL_PERMISSIONS}
# Presets rather than per-person checkboxes: with a workforce that turns over,
# the question asked at hiring is "what does this person do", and a fixed set
# of answers is far harder to get quietly wrong than twelve tick boxes. The
# answers are the firm's own departments.
#
# `rank` is the ladder a document climbs when the person who raised it has
# no manager set: it goes to the nearest rank above them that holds the right
# to approve it, and from the top of the staff to the owner.
_SITE = ["site.record"]
_PROJECT_MANAGER = ["self.service", "bills.submit", "bills.approve", "bills.view_all",
                    "attendance.view_team", "leave.approve", "reports.view",
                    "site.record", "site.signoff", "stores.receive",
                    "workorders.manage", "billing.manage", "subcontracts.approve",
                    "customers.manage", "items.manage"]
# What "workorders.manage" used to open on its own. The older presets keep all
# of it, so nobody already on one loses a screen the day the split lands.
_SPLIT_OUT = ["billing.manage", "purchase.manage", "stores.manage", "accounts.manage"]
PERMISSION_ROLES = [
    {
        "code": "staff", "label": "Site staff", "rank": 1,
        "description": "Their own timesheet, leave and payslips; records site work "
                       "and sends a cost up for approval.",
        "permissions": ["self.service", "bills.submit"] + _SITE,
    },
    {
        "code": "construction", "label": "Construction management team", "rank": 2,
        "description": "Site engineers and supervisors running the work: the site's "
                       "record and its sign-offs, material received at the gate, and "
                       "their crew's costs, leave and attendance.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "attendance.view_team", "leave.approve", "stores.receive",
                        "site.record", "site.signoff"],
    },
    {
        "code": "planning_billing", "label": "Planning & Billing", "rank": 2,
        "description": "Tenders, estimates and budgets; drafts work orders; measures "
                       "and bills the client; checks subcontractor bills. Sends them "
                       "for approval - does not approve them.",
        "permissions": ["self.service", "bills.submit", "billing.manage",
                        "workorders.manage", "items.manage", "customers.manage",
                        "reports.view"] + _SITE,
    },
    {
        "code": "purchase", "label": "Purchase", "rank": 2,
        "description": "Enquiries, quote comparison, purchase orders and suppliers. "
                       "An order goes for approval before it is placed.",
        "permissions": ["self.service", "bills.submit", "purchase.manage", "items.manage"],
    },
    {
        "code": "stores", "label": "Stores", "rank": 2,
        "description": "Receives material against orders, issues it to site, "
                       "transfers and adjusts stock, keeps the item master and the "
                       "plant register.",
        "permissions": ["self.service", "bills.submit", "stores.receive",
                        "stores.manage", "items.manage"] + _SITE,
    },
    {
        "code": "accounts", "label": "Accounts", "rank": 2,
        "description": "The money: supplier bills, payments, GST, TDS, e-invoices, "
                       "fixed assets and the reports. Pays what has been approved; "
                       "does not approve it.",
        "permissions": ["self.service", "bills.submit", "bills.view_all", "bills.pay",
                        "invoices.manage", "reports.view", "accounts.manage",
                        "customers.manage"],
    },
    {
        "code": "hr_admin", "label": "HR admin", "rank": 2,
        "description": "Looks after people. Adds employees, decides what each "
                       "can do, runs payroll, hiring and leave.",
        "permissions": ["self.service", "bills.submit", "attendance.view_team",
                        "leave.approve", "people.manage", "payroll.manage",
                        "recruitment.manage"],
    },
    {
        "code": "project_manager", "label": "Project manager", "rank": 3,
        "description": "Runs projects: everything on site, work orders and billing, "
                       "and approves the work orders, bills, variations and costs "
                       "raised below them.",
        "permissions": list(_PROJECT_MANAGER),
    },
    {
        "code": "head_projects", "label": "Head projects", "rank": 4,
        "description": "Over every project: a project manager's rights on all of "
                       "them plus purchase and stores, and the last approval before "
                       "the Master.",
        "permissions": _PROJECT_MANAGER + ["purchase.manage", "stores.manage"],
    },
    # The first presets, before the list followed the departments. Still
    # honoured for whoever holds one, and offered only to them.
    {
        "code": "supervisor", "label": "Supervisor", "rank": 2, "retired": True,
        "description": "Runs a crew. Everything staff can do, plus signing off "
                       "their crew's costs, leave and attendance.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "attendance.view_team", "leave.approve",
                        "stores.receive", "site.record", "site.signoff"],
    },
    {
        "code": "manager", "label": "Manager", "rank": 3, "retired": True,
        "description": "Runs a part of the business. A supervisor's rights plus "
                       "sight of all costs and the financial reports.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "bills.view_all", "attendance.view_team",
                        "leave.approve", "reports.view",
                        "items.manage", "workorders.manage",
                        "customers.manage", "subcontracts.approve",
                        "stores.receive", "site.record", "site.signoff"] + _SPLIT_OUT,
    },
    {
        "code": "finance", "label": "Finance", "rank": 3, "retired": True,
        "description": "Looks after the money. Approves and pays bills, raises "
                       "invoices and quotes, sees the reports.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "bills.view_all", "bills.pay", "invoices.manage",
                        "reports.view", "items.manage", "workorders.manage",
                        "customers.manage", "subcontracts.approve"] + _SPLIT_OUT,
    },
    {
        "code": "owner", "label": "Master", "rank": 5,
        "description": "Full access to everything in the portal.",
        "permissions": sorted(PERMISSION_KEYS),
    },
]

ROLE_PERMISSIONS = {r["code"]: set(r["permissions"]) for r in PERMISSION_ROLES}
ROLE_RANK = {r["code"]: r.get("rank", 1) for r in PERMISSION_ROLES}
DEFAULT_PERMISSION_ROLE = "staff"


def permission_list(raw) -> set:
    """A stored comma separated permission list, ignoring anything unknown.

    Silently dropping a key that is not a real permission rather than trusting
    it: the column is written by the owner through a form, and a typo must not
    become a right nobody can see or audit.
    """
    return {p.strip() for p in (raw or "").split(",")
            if p.strip() in PERMISSION_KEYS}


def permissions_for(emp) -> set:
    """The action keys an employee holds.

    The role is the starting point; what the owner has granted or withheld for
    this person on top of it decides the rest. An unrecognised or missing role
    falls back to the least privileged one rather than to everything, and a
    denial always beats a grant - taking a right away has to be reliable in a
    way that handing one out does not.
    """
    if emp is None:
        return set()
    role = (getattr(emp, "permission_role", "") or DEFAULT_PERMISSION_ROLE).lower()
    held = set(ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS[DEFAULT_PERMISSION_ROLE]))
    held |= permission_list(getattr(emp, "extra_permissions", ""))
    held -= permission_list(getattr(emp, "denied_permissions", ""))
    return held


def employee_can(emp, permission: str) -> bool:
    return permission in permissions_for(emp)


def role_rank(emp):
    return ROLE_RANK.get((getattr(emp, "permission_role", "") or DEFAULT_PERMISSION_ROLE).lower(), 1)
