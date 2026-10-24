"""Levels, roles and what each role may do in the portal."""



# TEAM - more than one person per business
# owner  - everything, and the only role that can manage the team
# admin  - everything else, including billing and the wallet
# viewer - read-only
TEAM_ROLES = ("owner", "admin", "viewer")

# `level` is the seniority band; `role` is the person's place in the reporting
# line. They are deliberately separate: a senior engineer (L4) and a team lead
# can be the same band but different roles.
#
# L1 is the top of the ladder, as in the company's own org notes, so a HIGHER rank is a MORE senior level.
EMPLOYEE_LEVELS = [
    {"code": "L1", "label": "L1 - HOD", "rank": 7},
    {"code": "L2", "label": "L2 - MD", "rank": 6},
    {"code": "L3", "label": "L3 - Coordinator / HO", "rank": 5},
    {"code": "L4", "label": "L4 - Project Manager", "rank": 4},
    {"code": "L5", "label": "L5 - Site Director / Sr. Engineer", "rank": 3},
    {"code": "L6", "label": "L6 - Site Engineer", "rank": 2},
    {"code": "L7", "label": "L7 - Engineer / Assistant", "rank": 1},
]
LEVEL_CODES = {lvl["code"] for lvl in EMPLOYEE_LEVELS}
LEVEL_RANK = {lvl["code"]: lvl["rank"] for lvl in EMPLOYEE_LEVELS}

# The designations. `level` is where the role sits; `reports_to` is the role it normally reports to (the
# default reporting line, which HR still sets person by person); `access` is the access level (a
# PERMISSION_ROLES code) the Master would normally give it. Nothing here grants access by itself: the
# Master sets each person's access, as before.
EMPLOYEE_ROLES = [
    {"code": "hod", "label": "HOD", "level": "L1", "department": "Management",
     "reports_to": None, "access": "head_projects"},
    {"code": "md", "label": "MD", "level": "L2", "department": "Management",
     "reports_to": "hod", "access": "owner"},
    {"code": "coordinator", "label": "Coordinator", "level": "L3", "department": "Head office",
     "reports_to": "md", "access": "ho_coordinator"},
    {"code": "ho_planning_head", "label": "HO Planning Head", "level": "L3", "department": "Head office",
     "reports_to": "md", "access": "ho_coordinator"},
    {"code": "ho_qs", "label": "HO QS", "level": "L3", "department": "Head office",
     "reports_to": "md", "access": "ho_qs"},
    {"code": "store_coordinator", "label": "Coordinator Store / Sr. Store", "level": "L3",
     "department": "Store", "reports_to": "hod", "access": "store_incharge"},
    {"code": "project_manager", "label": "Project Manager", "level": "L4", "department": "Projects",
     "reports_to": "ho_planning_head", "access": "project_manager"},
    {"code": "safety_head", "label": "Safety Head", "level": "L4", "department": "Site",
     "reports_to": "ho_planning_head", "access": "construction"},
    {"code": "sr_hr", "label": "Sr. HR", "level": "L4", "department": "HR",
     "reports_to": "hod", "access": "hr_admin"},
    {"code": "tpt", "label": "TPT (Transport)", "level": "L4", "department": "Transport",
     "reports_to": "hod", "access": "staff"},
    {"code": "site_director", "label": "Site Director", "level": "L5", "department": "Site",
     "reports_to": "project_manager", "access": "construction"},
    {"code": "sr_engineer", "label": "Sr. Engineer", "level": "L5", "department": "Site",
     "reports_to": "project_manager", "access": "construction"},
    {"code": "site_engineer", "label": "Site Engineer", "level": "L6", "department": "Site",
     "reports_to": "site_director", "access": "construction"},
    {"code": "store_executive", "label": "Store Executive", "level": "L6", "department": "Store",
     "reports_to": "project_manager", "access": "stores"},
    {"code": "engineer", "label": "Engineer", "level": "L7", "department": "Site",
     "reports_to": "site_engineer", "access": "staff"},
    {"code": "store_assistant", "label": "Store Assistant", "level": "L7", "department": "Store",
     "reports_to": "store_executive", "access": "stores"},
]
ROLE_LEVEL = {r["code"]: r["level"] for r in EMPLOYEE_ROLES}
# Roles that can be held but never handed out: they are not in the role picker and no create, update or
# hire can give one to anybody. Whoever already holds one keeps it.
FIXED_ROLES = frozenset({"hod", "md", "coordinator", "ho_planning_head", "ho_qs", "store_coordinator"})
ASSIGNABLE_ROLES = [r for r in EMPLOYEE_ROLES if r["code"] not in FIXED_ROLES]
ROLE_CODES = {r["code"] for r in EMPLOYEE_ROLES}


# HR decides this per employee. It is kept apart from `role` (the reporting
# line) and `level` (seniority) on purpose: on a contracting business the
# person who signs off costs, the person who runs the crew and the person who
# is most senior are frequently three different people.
PORTAL_PERMISSIONS = [
    {"key": "self.service", "group": "Everyone",
     "label": "My timesheet, payslips and leave"},
    # WHICH PORTALS A PERSON SEES. One right for each part of the menu that is not everybody's: with it the
    # group is in the person's sidebar, without it the group is not. What they may do inside is decided by
    # the rights below, as before. Calendar, Approvals and My work are everybody's; People and Settings are
    # the Master's; the HO portal has its own right (ho.view_all).
    {"key": "projects.view", "group": "Portals", "label": "Projects portal"},
    {"key": "clients.view", "group": "Portals", "label": "Clients portal"},
    {"key": "subcontractors.view", "group": "Portals", "label": "Subcontractors portal"},
    {"key": "store.view", "group": "Portals", "label": "Store portal"},
    {"key": "money.view", "group": "Portals", "label": "Money portal"},
    {"key": "bills.submit", "group": "Costs",
     "label": "Raise bills & expenses"},
    {"key": "bills.approve", "group": "Costs",
     "label": "Approve team bills"},
    {"key": "bills.view_all", "group": "Costs",
     "label": "View all bills"},
    {"key": "bills.pay", "group": "Costs",
     "label": "Pay approved bills"},
    {"key": "payments.approve", "group": "Costs",
     "label": "Check payments before they are made (accounts head)"},
    {"key": "payments.approve_high", "group": "Costs",
     "label": "Release payments over the MD's limit"},
    {"key": "invoices.manage", "group": "Sales",
     "label": "Invoices & quotes"},
    {"key": "reports.view", "group": "Sales",
     "label": "View reports"},
    {"key": "attendance.view_team", "group": "People",
     "label": "Team attendance"},
    {"key": "leave.approve", "group": "People",
     "label": "Approve leave"},
    {"key": "people.manage", "group": "People",
     "label": "Manage employees & access"},
    {"key": "payroll.manage", "group": "People",
     "label": "Payroll & payslips"},
    {"key": "recruitment.manage", "group": "People",
     "label": "Recruitment"},
    {"key": "items.manage", "group": "Contracts",
     "label": "Item master"},
    {"key": "siteprices.view", "group": "Contracts",
     "label": "View site item prices"},
    {"key": "siteprices.edit", "group": "Contracts",
     "label": "Edit site item prices"},
    {"key": "siteprices.finalize", "group": "Contracts",
     "label": "Finalise and reopen site item prices"},
    {"key": "workorders.manage", "group": "Contracts",
     "label": "Work orders & budgets"},
    {"key": "customers.manage", "group": "Contracts",
     "label": "Customers"},
    {"key": "subcontracts.approve", "group": "Contracts",
     "label": "Approve subcontract orders"},
    # Deliberately not part of any preset below except the owner's. Whoever
    # holds it signs off work that somebody else priced, and a right that
    # arrives with a job title is one nobody remembers deciding to give.
    {"key": "workorders.approve", "group": "Contracts",
     "label": "Final work order approval (MD)"},
    # Receiving is its own job, done by whoever is at the gate when the lorry
    # arrives - usually not the person who raised the order and never the one
    # who pays the bill. Kept separate so those three signatures stay apart.
    {"key": "stores.receive", "group": "Contracts",
     "label": "Receive goods"},
    # The departments' own work, split out of "workorders.manage", which had
    # grown to cover tenders, stock, purchasing and GST alike - so that giving
    # a storekeeper the store also gave them the tender book.
    {"key": "billing.manage", "group": "Planning & Billing",
     "label": "Tenders, RA bills & variations"},
    {"key": "purchase.manage", "group": "Purchase",
     "label": "Purchase & suppliers"},
    {"key": "stores.manage", "group": "Stores",
     "label": "Stock & plant register"},
    {"key": "accounts.manage", "group": "Accounts",
     "label": "GST, e-invoices & assets"},
    # The site's own record. Held by the people who are on the site, not only
    # by whoever manages the contract - a diary is written by the engineer
    # standing in the rain, and it could not be while writing it needed the
    # right to manage work orders.
    {"key": "site.record", "group": "Site",
     "label": "Record site work"},
    {"key": "site.signoff", "group": "Site",
     "label": "Sign off site work"},
    # HEAD OFFICE
    #
    # A vendor code, a work order and a BOQ are opened at head office, by its
    # quantity surveyor, and by nobody else in the business. Three sites each
    # registering contractors and raising orders is how one contractor ends up with two
    # vendor codes and one project with two BOQs. The Master holds these as
    # well. They are never handed out one by one (see HO_QS_ONLY): the way to
    # give somebody them is to make that person HO QS.
    {"key": "vendors.create", "group": "Head office", "only_role": "ho_qs",
     "label": "Open vendor codes"},
    {"key": "workorders.create", "group": "Head office", "only_role": "ho_qs",
     "label": "Open work orders"},
    {"key": "boq.create", "group": "Head office", "only_role": "ho_qs",
     "label": "Open project BOQ"},
    # Head office looks after every site, so it sees every order and every
    # bill - not only those it has a hand in, which is all a site sees.
    {"key": "ho.view_all", "group": "Head office",
     "label": "HO portal (all sites)"},
]

# THE STORE MODULE: store.<slice>.<action>. The six slices and five actions are every combination, so a new screen
# never has to add a right; the four extras are the ones worth deciding on their own and are never part of a card.
STORE_SLICES = ("masters", "enquiry", "inward", "outward", "control", "reports")
STORE_ACTIONS = ("view", "create", "approve", "post", "cancel")
STORE_EXTRAS = [
    {"key": "store.outward.direct_issue", "group": "Store module", "label": "Issue material without a requisition"},
    {"key": "store.control.reveal_count", "group": "Store module", "label": "See system quantity during a stock count"},
    {"key": "store.control.approve_high_value", "group": "Store module", "label": "Approve high-value adjustments and transfers"},
    # One tick that opens every store and every Store right, whatever the stores the person is assigned to. The Master alone sets
    # rights (hr.set_permissions); the warning is shown where it is ticked, so it is never given without being meant.
    {"key": "store.admin", "group": "Store module", "label": "Store administrator (every store, every right)",
     "warning": "Opens every store and every Store right - receiving, issuing, approving, cancelling and posting - whatever stores "
                "this person is assigned to. Give it only to whoever runs the stores for the whole company."},
]
STORE_KEYS = [f"store.{sl}.{act}" for sl in STORE_SLICES for act in STORE_ACTIONS]
PORTAL_PERMISSIONS += [{"key": k, "group": "Store module", "label": "Store %s: %s" % (k.split(".")[1], k.split(".")[2])}
                       for k in STORE_KEYS] + STORE_EXTRAS
PERMISSION_KEYS = {p["key"] for p in PORTAL_PERMISSIONS}

# The rights only HO QS (and the Master) can hold, whatever else is ticked.
HO_QS_ONLY = frozenset(p["key"] for p in PORTAL_PERMISSIONS if p.get("only_role") == "ho_qs")
HO_QS_ONLY_ROLES = frozenset({"ho_qs", "owner"})
# The HO Coordinator follows up and keeps drafts current; it starts nothing new: no project, tender, bill
# or variation. (It still edits what is already open.)
HO_FOLLOW_UP_ONLY_ROLES = frozenset({"ho_coordinator"})
# What is said to somebody who tries one of them: who does it instead.
HO_QS_ONLY_REFUSAL = {
    "vendors.create": "Vendor codes are opened by HO QS",
    "workorders.create": "Work orders are opened by HO QS",
    "boq.create": "BOQs are opened by HO QS",
}
# Presets rather than per-person checkboxes: with a workforce that turns over,
# the question asked at hiring is "what does this person do", and a fixed set
# of answers is far harder to get quietly wrong than twelve tick boxes. The
# answers are the firm's own departments.
#
# `rank` is the ladder a document climbs when the person who raised it has
# no manager set: it goes to the nearest rank above them that holds the right
# to approve it, and from the top of the staff to the owner.
_SITE = ["site.record"]
# Every portal, for the roles that oversee the whole business. The ladder is the hierarchy: the further up it, the
# more of the portals a role is given, and from the project manager (rank 3) up it is all of them. Nobody higher
# holds fewer portals than somebody below (tests/test_portal_access.py holds that).
MANAGEMENT_RANK = 3
_ALL_PORTALS = ["projects.view", "clients.view", "subcontractors.view", "store.view", "money.view"]
_PROJECT_MANAGER = ["self.service", "bills.submit", "bills.approve", "bills.view_all",
                    "attendance.view_team", "leave.approve", "reports.view",
                    "site.record", "site.signoff", "stores.receive",
                    "workorders.manage", "billing.manage", "subcontracts.approve",
                    "customers.manage", "items.manage", "siteprices.view", "siteprices.edit"] + _ALL_PORTALS
# What "workorders.manage" used to open on its own. The older presets keep all
# of it, so nobody already on one loses a screen the day the split lands.
_SPLIT_OUT = ["billing.manage", "purchase.manage", "stores.manage", "accounts.manage"]
# What both people at head office hold: every site's orders, BOQs and bills in
# sight, and the right to keep them up to date.
_HEAD_OFFICE = ["self.service", "bills.submit", "bills.view_all", "reports.view",
                "workorders.manage", "billing.manage", "customers.manage", "ho.view_all"] + _ALL_PORTALS
# THE STORE HUB, BY JOB. Every Hub screen asks for store.<slice>.<action>; the old store's rights (stores.receive,
# stores.manage) open none of them. Each bundle is what that job does in the Hub - and staff still work only in the
# stores they are assigned to.
_STORE_VIEW = ["store.%s.view" % s for s in STORE_SLICES]
# Asks for material and looks up stock: raises an indent (a draft issue too, which somebody else posts).
_STORE_REQUEST = ["store.enquiry.view", "store.outward.view", "store.outward.create"]
# Keeps a store: receives, issues, returns, moves and counts stock and posts it - but approves nothing.
_STORE_KEEPER = _STORE_VIEW + ["store.inward.create", "store.inward.post", "store.outward.create", "store.outward.post",
                               "store.control.create", "store.control.post"]
# Runs the stores: approves and cancels what the keepers raise, sets up stores and items, and the counts' controls.
_STORE_INCHARGE = _STORE_KEEPER + ["store.%s.%s" % (s, a) for s in ("inward", "outward", "control") for a in ("approve", "cancel")] + [
    "store.masters.create", "store.masters.approve", "store.reports.create", "store.outward.direct_issue",
    "store.control.reveal_count", "store.control.approve_high_value"]
# Approves the indents and issues of a project and reads its material cost.
_STORE_APPROVE_PROJECT = ["store.enquiry.view", "store.inward.view", "store.outward.view", "store.outward.create",
                          "store.outward.approve", "store.reports.view"]
_PROJECT_MANAGER = _PROJECT_MANAGER + _STORE_APPROVE_PROJECT
_HEAD_OFFICE = _HEAD_OFFICE + _STORE_VIEW
PERMISSION_ROLES = [
    {
        "code": "staff", "label": "Site staff", "rank": 1,
        "description": "Their own timesheet, leave and payslips; records site work "
                       "and sends a cost up for approval.",
        "permissions": ["self.service", "bills.submit", "projects.view"] + _SITE,
    },
    {
        "code": "construction", "label": "Construction management team", "rank": 2,
        "description": "Site engineers and supervisors running the work: the site's "
                       "record and its sign-offs, material received at the gate, and "
                       "their crew's costs, leave and attendance.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "attendance.view_team", "leave.approve", "stores.receive",
                        "site.record", "site.signoff",
                        "projects.view", "subcontractors.view", "store.view"] + _STORE_REQUEST,
    },
    {
        "code": "planning_billing", "label": "Planning & Billing", "rank": 2,
        "description": "Tenders, estimates and budgets; works on the work orders "
                       "HO QS opens; measures and bills the client; checks "
                       "subcontractor bills. Sends them for approval - does not "
                       "approve them.",
        "permissions": ["self.service", "bills.submit", "billing.manage",
                        "workorders.manage", "items.manage", "customers.manage",
                        "reports.view", "projects.view", "clients.view",
                        "subcontractors.view", "store.view", "store.enquiry.view", "store.reports.view"] + _SITE,
    },
    {
        "code": "purchase", "label": "Purchase", "rank": 2,
        "description": "Enquiries, quote comparison, purchase orders and suppliers. "
                       "An order goes for approval before it is placed.",
        "permissions": ["self.service", "bills.submit", "purchase.manage", "items.manage",
                        "projects.view", "store.view", "store.enquiry.view", "store.inward.view", "store.reports.view"],
    },
    {
        "code": "stores", "label": "Stores", "rank": 2,
        "description": "Receives material against orders, issues it to site, "
                       "transfers and adjusts stock, keeps the item master and the "
                       "plant register.",
        "permissions": ["self.service", "bills.submit", "stores.receive",
                        "stores.manage", "items.manage",
                        "projects.view", "store.view"] + _SITE + _STORE_KEEPER,
    },
    {
        "code": "store_incharge", "label": "Store in-charge", "rank": 2,
        "description": "Runs the stores: everything a storekeeper does, plus approving and cancelling "
                       "receipts, issues, transfers, counts and scrap, setting up stores and items, and "
                       "the stock-count controls.",
        "permissions": ["self.service", "bills.submit", "stores.receive",
                        "stores.manage", "items.manage",
                        "projects.view", "store.view"] + _SITE + _STORE_INCHARGE,
    },
    {
        "code": "accounts", "label": "Accounts", "rank": 2,
        "description": "The money: supplier bills, payments, GST, TDS, e-invoices, "
                       "fixed assets and the reports. Pays what has been approved; "
                       "does not approve it.",
        "permissions": ["self.service", "bills.submit", "bills.view_all", "bills.pay",
                        "invoices.manage", "reports.view", "accounts.manage",
                        "customers.manage",
                        "projects.view", "clients.view", "subcontractors.view", "store.view", "money.view",
                        "store.enquiry.view", "store.inward.view", "store.reports.view"],
    },
    {
        "code": "hr_admin", "label": "HR admin", "rank": 2,
        "description": "Looks after people. Adds employees, decides what each "
                       "can do, runs payroll, hiring and leave.",
        "permissions": ["self.service", "bills.submit", "attendance.view_team",
                        "leave.approve", "people.manage", "payroll.manage",
                        "recruitment.manage", "projects.view"],
    },
    {
        "code": "project_manager", "label": "Project manager", "rank": 3,
        "description": "Runs projects: everything on site, work orders and billing, "
                       "and approves the work orders, bills, variations and costs "
                       "raised below them.",
        "permissions": list(_PROJECT_MANAGER),
    },
    {
        "code": "head_projects", "label": "Head projects", "rank": 5,
        "description": "Over every project: a project manager's rights on all of "
                       "them plus purchase and stores, and the last approval before "
                       "the Master.",
        "permissions": _PROJECT_MANAGER + ["purchase.manage", "stores.manage"],
    },
    # HEAD OFFICE - its two people. They sign in at the same page as everybody
    # else and land on the HO portal rather than on a site's day. HO QS sits on
    # the approval ladder right after the project manager: what a site raises
    # goes site -> project manager -> HO QS -> head projects -> the Master. The
    # coordinator approves nothing; it follows up.
    {
        "code": "ho_qs", "label": "HO QS", "rank": 4, "head_office": True,
        "description": "Head office quantity surveyor. The only one who opens vendor "
                       "codes, work orders (the client's and the sub contractors') and "
                       "BOQs. Sees every order, BOQ and bill on every site and approves "
                       "what the project manager has approved, before head projects "
                       "and the Master.",
        "permissions": _HEAD_OFFICE + ["items.manage", "bills.approve",
                                       "subcontracts.approve", "vendors.create",
                                       "workorders.create", "boq.create", "siteprices.view",
                                       "siteprices.edit", "siteprices.finalize"],
    },
    {
        "code": "ho_coordinator", "label": "HO Coordinator", "rank": 2, "head_office": True,
        "description": "Head office coordinator. Sees every vendor, work order, BOQ and "
                       "bill on every site, follows up whatever is waiting and keeps "
                       "drafts up to date. Starts nothing new: no vendor codes, work "
                       "orders, BOQs, projects, tenders, bills or variations.",
        "permissions": list(_HEAD_OFFICE),
    },
    # The first presets, before the list followed the departments. Still
    # honoured for whoever holds one, and offered only to them.
    {
        "code": "supervisor", "label": "Supervisor", "rank": 2, "retired": True,
        "description": "Runs a crew. Everything staff can do, plus signing off "
                       "their crew's costs, leave and attendance.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "attendance.view_team", "leave.approve",
                        "stores.receive", "site.record", "site.signoff",
                        "projects.view", "subcontractors.view", "store.view"],
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
                        "stores.receive", "site.record", "site.signoff"] + _SPLIT_OUT + _ALL_PORTALS,
    },
    {
        "code": "finance", "label": "Finance", "rank": 3, "retired": True,
        "description": "Looks after the money. Approves and pays bills, raises "
                       "invoices and quotes, sees the reports.",
        "permissions": ["self.service", "bills.submit", "bills.approve",
                        "bills.view_all", "bills.pay", "invoices.manage",
                        "reports.view", "items.manage", "workorders.manage",
                        "customers.manage", "subcontracts.approve"] + _SPLIT_OUT + _ALL_PORTALS,
    },
    {
        "code": "owner", "label": "Master", "rank": 6,
        "description": "Full access to everything in the portal.",
        "permissions": sorted(PERMISSION_KEYS),
    },
]

# THE PORTALS, AS THE MASTER SEES THEM. Each is a card with three settings: No access, Read only, Read & write.
# They are not new rights but a way of setting the rights above together, so every check in the app is
# unchanged and a role's preset already says which setting it is:
#   read  - the right that puts the portal in the menu, and any right its screens need just to open;
#   write - the rights that let somebody create or change things in it.
# No access holds none of the portal's rights, Read only holds `read` alone, Read & write holds both.
# A right belongs to one portal only, so setting one card never moves another. Rights in none of them
# (approving a team's bills, signing off leave, the head office rights) stay as the role or the Master set them.
PORTALS = [
    {"code": "projects", "label": "Projects Portal",
     "blurb": "Sites, drawings, quality, safety and the site diary.",
     "read": ["projects.view"], "write": ["site.record", "site.signoff"]},
    {"code": "clients", "label": "Clients Portal",
     "blurb": "Tenders, estimates, BOQs, measurement and billing the client.",
     "read": ["clients.view"], "write": ["billing.manage", "customers.manage"]},
    {"code": "subcontractors", "label": "Subcontractors Portal",
     "blurb": "Contractors, work orders, the measurement book and RA bills.",
     "read": ["subcontractors.view"], "write": ["workorders.manage", "subcontracts.approve"]},
    {"code": "store", "label": "Store & Supplies",
     "blurb": "Items, enquiries, purchase orders, goods received and stock.",
     "read": ["store.view"] + [k for k in STORE_KEYS if k.endswith(".view")],
     "write": ["items.manage", "purchase.manage", "stores.manage", "stores.receive"]
              + [k for k in STORE_KEYS if not k.endswith(".view")]},
    {"code": "money", "label": "Money Portal",
     "blurb": "Supplier bills, payments, GST, assets and the registers.",
     "read": ["money.view", "bills.view_all"], "write": ["bills.pay", "invoices.manage", "accounts.manage"]},
    # Run by the Master alone for now: every People screen opens only for the Master's own login, so there is
    # nothing a staff login could be given. Shown, so the list of portals is complete, but not settable.
    {"code": "people", "label": "People Portal", "locked": "Master only",
     "blurb": "Employees, departments, attendance, leave and payroll.",
     "read": [], "write": []},
]
PORTAL_KEYS = {k for pt in PORTALS for k in pt["read"] + pt["write"]}


def portal_level(held, portal) -> str:
    """"none", "read" or "write": where a set of rights stands on one portal card."""
    if not portal["read"] or portal["read"][0] not in held:
        return "none"
    return "write" if any(k in held for k in portal["write"]) else "read"


ROLE_PERMISSIONS = {r["code"]: set(r["permissions"]) for r in PERMISSION_ROLES}
ROLE_RANK = {r["code"]: r.get("rank", 1) for r in PERMISSION_ROLES}
DEFAULT_PERMISSION_ROLE = "staff"
# The access levels that make somebody head office: they land on the HO portal.
HEAD_OFFICE_ROLES = frozenset(r["code"] for r in PERMISSION_ROLES if r.get("head_office"))


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
    if role not in HO_QS_ONLY_ROLES:
        # Ticked by hand for somebody who is not HO QS: not honoured. Opening
        # codes and orders stays with one desk however the boxes were set.
        held -= HO_QS_ONLY
    return held


def employee_can(emp, permission: str) -> bool:
    return permission in permissions_for(emp)


def is_head_office(emp) -> bool:
    """Whether this member of staff is one of head office's people (HO QS or HO Coordinator)."""
    return (getattr(emp, "permission_role", "") or "").lower() in HEAD_OFFICE_ROLES


# HO QS approves at rank 4, above the project manager - but the paper HO QS raises (the work orders it
# opens) is prepared like a department's: it climbs from the bottom, through the project manager.
RAISING_RANK = {"ho_qs": 2}


def raising_rank(emp):
    """Where a document climbs from when this person raised it."""
    role = (getattr(emp, "permission_role", "") or DEFAULT_PERMISSION_ROLE).lower()
    return RAISING_RANK.get(role, ROLE_RANK.get(role, 1))


def role_rank(emp):
    return ROLE_RANK.get((getattr(emp, "permission_role", "") or DEFAULT_PERMISSION_ROLE).lower(), 1)
