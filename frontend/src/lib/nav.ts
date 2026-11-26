import {
  BadgeIndianRupee,
  CalendarDays,
  Building2,
  CheckCheck,
  HardHat,
  Landmark,
  LayoutDashboard,
  type LucideIcon,
  Package,
  Megaphone,
 
  Settings,
  UserRound,
  Users,
  Wallet,
} from 'lucide-react'

/** Any of the Store module's six parts opens its hub. */
const STORE_ANY = ['masters', 'enquiry', 'inward', 'outward', 'control', 'reports'].map((s) => `store.${s}.view`).join('|')
/** The day's store work (receive, issue, stock, low stock), at the top of the Store page. */
export const STORE_DESK_PERM = 'store.enquiry.view|store.inward.view|store.outward.view'

/** What the Store page offers below the day's work, each shown only to somebody with its right. One menu entry, Store,
 * opens them all: `block` is the heading it sits under there. */
export type StoreSection = { label: string; path: string; perm: string; hint: string; block: 'purchase' | 'more' }
export const STORE_SECTIONS: StoreSection[] = [
  { label: 'Enquiries & Comparison', path: '/store/enquiries', perm: 'purchase.manage', block: 'purchase', hint: 'Ask suppliers for quotes and compare them' },
  { label: 'Purchase Orders', path: '/store/purchase-orders', perm: 'purchase.manage|bills.view_all', block: 'purchase', hint: 'Orders to suppliers and what has arrived' },
  { label: 'Item Sheet', path: '/store/item-sheet', perm: 'store.outward.view|store.inward.view|store.admin', block: 'purchase', hint: "Materials for every BOQ line; order, receive and issue them" },
  { label: 'Rate Contracts', path: '/store/rate-contracts', perm: 'purchase.manage', block: 'purchase', hint: 'Rates agreed with suppliers for the year' },
  { label: 'Invoice Tracker', path: '/store/invoice-tracker', perm: 'stores.receive|stores.manage|purchase.manage|bills.view_all', block: 'purchase', hint: "Suppliers' bills checked against what came" },
  // Every receipt, issue, transfer and count is in the Store Hub. The old store's screens are removed.
  { label: 'Full store (Hub)', path: '/store/hub', perm: STORE_ANY, block: 'more', hint: 'Transfers, counts, quality, returns, gate passes, reports' },
  { label: 'Item Master', path: '/store/items', perm: 'items.manage', block: 'more', hint: 'Every material with its unit, code and rate' },
  { label: 'E-way Bills', path: '/store/eway', perm: 'accounts.manage|stores.manage|stores.receive|bills.view_all|store.inward.view|store.outward.view', block: 'more', hint: 'Goods on the road and their validity' },
]
const STORE_OPENS = [STORE_DESK_PERM, ...STORE_SECTIONS.map((s) => s.perm)].join('|')

/**
 * The store's work in the order it is done, in plain words, for people who read little English: the menu lists these
 * as numbered steps (like Subcontractors), and the Store page shows them as big cards. `say` is the one line under it.
 */
export type StoreStep = { n: number; label: string; path: string; perm: string; say: string }
export const STORE_STEPS: StoreStep[] = [
  { n: 1, label: 'Items', path: '/store/items', perm: 'items.manage', say: 'Add every material you use: cement, sand, steel.' },
  { n: 2, label: 'Item Sheet', path: '/store/item-sheet', perm: 'store.outward.view|store.inward.view|store.admin', say: 'List the materials each project needs.' },
  { n: 3, label: 'Buy (Purchase Order)', path: '/store/purchase-orders', perm: 'purchase.manage|bills.view_all', say: 'Order material from the supplier.' },
  { n: 4, label: 'Receive Material', path: '/store/receive', perm: 'store.inward.view|store.admin', say: 'Material came to the store? Enter it here.' },
  { n: 5, label: 'Material Request', path: '/store/hub/outward/indent', perm: 'store.outward.view|store.admin', say: 'Site asks the store for material.' },
  { n: 6, label: 'Issue Material', path: '/store/issue', perm: 'store.outward.view|store.admin', say: 'Give material to the site or contractor.' },
  { n: 7, label: 'Return Material', path: '/store/hub/outward/returns', perm: 'store.outward.view|store.admin', say: 'Unused material came back to the store.' },
  { n: 8, label: 'Stock', path: '/store/stock-register', perm: STORE_DESK_PERM + '|store.admin', say: 'See what is in the store now.' },
]
/** The rest of the store, after the steps: less often, still one click from the menu. */
export const STORE_MORE: { label: string; path: string; perm: string; say: string }[] = [
  { label: 'Low Stock', path: '/store/low-stock', perm: STORE_DESK_PERM + '|store.admin', say: 'Materials running out. Order these.' },
  { label: 'Supplier Quotes', path: '/store/enquiries', perm: 'purchase.manage', say: 'Ask suppliers for rates and compare.' },
  { label: 'Fixed Rates (Rate Contracts)', path: '/store/rate-contracts', perm: 'purchase.manage', say: 'Rates agreed with a supplier for the year.' },
  { label: 'Move Stock (Transfer)', path: '/store/hub/control/transfer', perm: 'store.control.view|store.admin', say: 'Send stock from one store to another.' },
  { label: 'Count Stock', path: '/store/hub/control/count', perm: 'store.control.view|store.admin', say: 'Count what is really in the store.' },
  { label: 'Damaged / Scrap', path: '/store/hub/control/scrap', perm: 'store.control.view|store.admin', say: 'Write off wasted or scrap material.' },
  { label: 'Gate Pass', path: '/store/hub/outward/gate-pass', perm: 'store.outward.view|store.admin', say: 'Paper for material leaving the gate.' },
  { label: 'Tools', path: '/store/hub/outward/tools', perm: 'store.outward.view|store.admin', say: 'Who has which tool.' },
  { label: 'Reports', path: '/store/hub/reports', perm: 'store.reports.view|store.admin', say: 'Stock, use and cost reports.' },
  { label: 'Supplier Bill Check', path: '/store/invoice-tracker', perm: 'stores.receive|stores.manage|purchase.manage|bills.view_all', say: "Check suppliers' bills against what came." },
  { label: 'E-way Bills', path: '/store/eway', perm: 'accounts.manage|stores.manage|stores.receive|bills.view_all|store.inward.view|store.outward.view', say: 'Goods on the road.' },
  { label: 'Store Settings', path: '/store/hub/masters', perm: 'store.masters.view|store.admin', say: 'Stores, people in each store, item units.' },
  { label: 'All Store Screens', path: '/store/hub', perm: STORE_ANY, say: 'Every store screen in one place.' },
]

/** notHeadOffice: left out for HO QS and HO Coordinator, whose front page is the HO portal. */
type NavItem = { label: string; path: string; perm?: string; notHeadOffice?: boolean }
/** staffOnly: the screens of a member of staff's own work (timesheet, payslips), which the account holder has no use for. */
/** perm: the right that puts the whole group in somebody's menu (a portal). Its items may ask for more on top. */
export type NavGroup = { id: string; label: string; icon: LucideIcon; items: NavItem[]; staffOnly?: boolean; ownerOnly?: boolean; perm?: string }
/** also: a second right a link needs on top of `perm` (the Store portal, and something to do in it). */
export type NavEntry = { kind: 'link'; id: string; label: string; icon: LucideIcon; path: string; perm?: string; also?: string; ownerOnly?: boolean; staffOnly?: boolean } | ({ kind: 'group' } & NavGroup)

/**
 * The same six groups the current app has, so nobody has to relearn where
 * things live - only what they look like. Every item gets a route; those not
 * yet ported render the migration placeholder.
 */
const NAV: NavEntry[] = [
  { kind: 'link', id: 'dashboard', label: 'Command Center', icon: LayoutDashboard, path: '/', ownerOnly: true },
  { kind: 'link', id: 'calendar', label: 'Calendar', icon: CalendarDays, path: '/calendar' },
  { kind: 'link', id: 'feed', label: 'Feed', icon: Megaphone, path: '/feed' },
  // Head office's front page: every site's vendors, work orders, BOQs and bills, and what waits on whom.
  // HO QS and HO Coordinator land here. It is theirs, a staff login like any other: the Master manages
  // who they are in People and does not carry the HO portal in the Master's own menu.
  { kind: 'link', id: 'ho', label: 'HO Portal', icon: Landmark, path: '/ho', perm: 'ho.view_all', staffOnly: true },
  {
    kind: 'group',
    id: 'me',
    label: 'My work',
    icon: UserRound,
    staffOnly: true,
    items: [
      { label: 'Overview', path: '/', notHeadOffice: true },
      { label: 'Timesheet', path: '/me/timesheet' },
      { label: 'My Costs', path: '/me/costs', perm: 'bills.submit' },
      { label: 'Site Cash', path: '/me/site-cash' },
      { label: 'Expense Claims', path: '/me/claims' },
      { label: 'My Orders', path: '/me/orders', perm: 'bills.submit' },
      { label: 'My Leave', path: '/me/leave' },
      { label: 'Payslips', path: '/me/payslips' },
      { label: 'Documents', path: '/me/documents' },
      { label: 'My Goals', path: '/me/goals' },
      { label: 'Onboarding', path: '/me/onboarding' },
      { label: 'My Team', path: '/me/team' },
      { label: 'My Profile', path: '/me/profile' },
    ],
  },
  { kind: 'link', id: 'approvals', label: 'Approvals', icon: CheckCheck, path: '/approvals' },
  {
    kind: 'group',
    id: 'projects',
    perm: 'projects.view',
    label: 'Projects',
    icon: Building2,
    items: [
      { label: 'Projects', path: '/projects', perm: 'reports.view' },
      { label: 'Planning & Progress', path: '/projects/programme' },
      { label: 'Drawings', path: '/projects/drawings' },
      { label: 'Document Control', path: '/projects/documents' },
      { label: 'Quality', path: '/projects/quality' },
      { label: 'Workers and Safety', path: '/projects/safety' },
      { label: 'Site Diary', path: '/projects/diary' },
      { label: 'Project Chart', path: '/projects/chart' },
      { label: 'Equipment & Plant', path: '/projects/equipment' },
      { label: 'Bar Bending Schedule', path: '/projects/bbs' },
      { label: 'Budgeting', path: '/projects/budgeting', perm: 'budget.view|budget.edit' },
      { label: 'Project Profit', path: '/projects/profit', perm: 'reports.view' },
      { label: 'Cost by Project', path: '/projects/costs', perm: 'reports.view' },
    ],
  },
  {
    kind: 'group',
    id: 'clients',
    perm: 'clients.view',
    label: 'Clients',
    icon: BadgeIndianRupee,
    items: [
      { label: 'Tender Pipeline', path: '/clients/pipeline', perm: 'billing.manage' },
      { label: 'Tenders & Estimates', path: '/clients/estimates', perm: 'billing.manage' },
      { label: 'BOQ', path: '/projects/boq', perm: 'workorders.manage|reports.view' },
      { label: 'Site Item Pricing', path: '/projects/boq/rates', perm: 'siteprices.view|siteprices.edit|siteprices.finalize|workorders.manage|reports.view' },
      { label: 'Measurement & RA Bills', path: '/clients/measurement', perm: 'site.record|billing.manage' },
      { label: 'Customers', path: '/clients/customers', perm: 'customers.manage' },
      { label: 'Contacts', path: '/clients/contacts', perm: 'customers.manage' },
    ],
  },
  {
    kind: 'group',
    id: 'subcontractors',
    perm: 'subcontractors.view',
    label: 'Subcontractors',
    icon: HardHat,
    items: [
      { label: 'Sub Contract Registration', path: '/subcontractors/vendors' },
      { label: 'Work Orders', path: '/subcontractors/work-orders' },
      { label: 'Measurement Book', path: '/subcontractors/measurement-book' },
      { label: 'RA Bills', path: '/subcontractors/ra-bills' },
      { label: 'Compliance', path: '/subcontractors/compliance' },
      { label: 'Recoveries & Work Types', path: '/subcontractors/registers' },
    ],
  },
  // One entry for the whole store: the day's work at the top, purchase and the rest of the store below (STORE_SECTIONS).
  {
    kind: 'group',
    id: 'store',
    perm: 'store.view',
    label: 'Store',
    icon: Package,
    items: [
      { label: 'Store Home', path: '/store', perm: STORE_OPENS },
      ...STORE_STEPS.map((s) => ({ label: `${s.n}. ${s.label}`, path: s.path, perm: s.perm })),
      ...STORE_MORE.map((s) => ({ label: s.label, path: s.path, perm: s.perm })),
    ],
  },
  {
    kind: 'group',
    id: 'money',
    perm: 'money.view',
    label: 'Accounts',
    icon: Wallet,
    items: [
      { label: 'Finance Dashboard', path: '/money/dashboard', perm: 'bills.view_all' },
      // One page: to pay, to receive and retention are its tabs, and only its tabs.
      { label: 'Pay & Receive', path: '/money/owed', perm: 'bills.view_all' },
      { label: 'Supplier Bills', path: '/money/supplier-bills', perm: 'bills.view_all' },
      { label: 'Payment Approvals', path: '/money/approvals', perm: 'bills.view_all' },
      { label: 'Daily Expenses', path: '/money/expenses', perm: 'bills.view_all' },
      { label: 'Recurring Payments', path: '/money/recurring', perm: 'bills.view_all' },
      { label: 'Loans & EMIs', path: '/money/loans', perm: 'bills.view_all' },
      { label: 'Advances', path: '/money/advances', perm: 'bills.view_all' },
      { label: 'Journals & Debit Notes', path: '/money/adjustments', perm: 'bills.view_all' },
      { label: 'Ledgers & Bank', path: '/money/ledgers', perm: 'bills.view_all' },
      { label: 'Bank Payments & Cheques', path: '/money/bank-payments', perm: 'bills.view_all' },
      { label: 'GST', path: '/money/gst', perm: 'bills.view_all' },
      { label: 'TDS & Guarantees', path: '/money/registers', perm: 'bills.view_all' },
      { label: 'Fixed Assets', path: '/money/assets', perm: 'bills.view_all' },
      { label: 'Trial Balance & Day Book', path: '/money/books', perm: 'bills.view_all' },
      { label: 'Tally Export', path: '/money/tally', perm: 'bills.view_all' },
    ],
  },
  {
    kind: 'group',
    id: 'people',
    perm: 'people.manage',
    label: 'People',
    icon: Users,
    items: [
      { label: 'Employees', path: '/people/employees', perm: 'people.manage' },
      { label: 'Departments', path: '/people/departments', perm: 'people.manage' },
      { label: 'Attendance', path: '/people/attendance', perm: 'attendance.view_team|people.manage' },
      { label: 'Leave', path: '/people/leave', perm: 'leave.approve' },
      { label: 'Payroll', path: '/people/payroll', perm: 'payroll.manage' },
    ],
  },
  // The Master's (who holds every right); a member of staff only with "Manage website", and then sees only the Website tab.
  { kind: 'link', id: 'settings', label: 'Settings', icon: Settings, path: '/settings', perm: 'website.manage' },
]

export type Trail = { label: string; path?: string }[]

/** Home > Group > Page for whatever path is showing. */
export function trailFor(pathname: string, staff = false): Trail {
  const home: Trail = [{ label: 'Home', path: '/' }]
  if (pathname === '/') return [{ label: staff ? 'Overview' : 'Command Center' }]
  for (const e of NAV) {
    if (e.kind === 'link' && e.path === pathname) return [...home, { label: e.label }]
    if (e.kind === 'group') {
      const hit = e.items.find((i) => i.path === pathname)
      if (hit) return [...home, { label: e.label }, { label: hit.label }]
    }
  }
  // A page inside a section: /subcontractors/work-orders/12 sits under Work Orders.
  for (const e of NAV) {
    if (e.kind !== 'group') continue
    // Store Home is no parent: an address under /store that no step names is not a store page.
    const parent = e.items.filter((i) => i.path !== '/store' && pathname.startsWith(i.path + '/')).sort((a, b) => b.path.length - a.path.length)[0]
    if (parent) return [...home, { label: e.label }, { label: parent.label, path: parent.path }, { label: 'Details' }]
  }
  return [...home, { label: 'Not found' }]
}

/** The menu as this person may see it: items they lack the right to are left out, and so are groups left empty. */
export function visibleNav(can: (perm: string) => boolean, staff = false, headOffice = false): NavEntry[] {
  return NAV.flatMap((e): NavEntry[] => {
    if (e.kind === 'group' && e.staffOnly && !staff) return []
    if (e.kind === 'group' && e.ownerOnly && staff) return []
    if (e.kind === 'group' && e.perm && !can(e.perm)) return []
    if (e.kind === 'link' && e.ownerOnly && staff) return []
    if (e.kind === 'link' && e.staffOnly && !staff) return []
    if (e.kind === 'link') return (!e.perm || can(e.perm)) && (!e.also || can(e.also)) ? [e] : []
    const items = e.items.filter((i) => (!i.perm || can(i.perm)) && !(headOffice && i.notHeadOffice))
    return items.length ? [{ ...e, items }] : []
  })
}

export function groupFor(pathname: string): string | null {
  for (const e of NAV) if (e.kind === 'group' && e.items.some((i) => i.path === pathname || pathname.startsWith(i.path + '/'))) return e.id
  return null
}

export function allRoutes(): { path: string; label: string; group?: string }[] {
  return [...NAV.flatMap((e) =>
    e.kind === 'link'
      ? e.path === '/'
        ? []
        : [{ path: e.path, label: e.label }]
      : e.items.map((i) => ({ path: i.path, label: i.label, group: e.label })),
  ), ...STORE_SECTIONS.map((s) => ({ path: s.path, label: s.label, group: 'Store' }))]
}
