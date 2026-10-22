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
  Settings,
  UserRound,
  Users,
  Wallet,
} from 'lucide-react'

/** Any of the Store module's six parts opens its hub. */
const STORE_ANY = ['masters', 'enquiry', 'inward', 'outward', 'control', 'reports'].map((s) => `store.${s}.view`).join('|')

/** notHeadOffice: left out for HO QS and HO Coordinator, whose front page is the HO portal. */
type NavItem = { label: string; path: string; perm?: string; notHeadOffice?: boolean }
/** staffOnly: the screens of a member of staff's own work (timesheet, payslips), which the account holder has no use for. */
/** perm: the right that puts the whole group in somebody's menu (a portal). Its items may ask for more on top. */
export type NavGroup = { id: string; label: string; icon: LucideIcon; items: NavItem[]; staffOnly?: boolean; ownerOnly?: boolean; perm?: string }
export type NavEntry = { kind: 'link'; id: string; label: string; icon: LucideIcon; path: string; perm?: string; ownerOnly?: boolean; staffOnly?: boolean } | ({ kind: 'group' } & NavGroup)

/**
 * The same six groups the current app has, so nobody has to relearn where
 * things live - only what they look like. Every item gets a route; those not
 * yet ported render the migration placeholder.
 */
const NAV: NavEntry[] = [
  { kind: 'link', id: 'dashboard', label: 'Command Center', icon: LayoutDashboard, path: '/', ownerOnly: true },
  { kind: 'link', id: 'calendar', label: 'Calendar', icon: CalendarDays, path: '/calendar' },
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
      { label: 'Quality', path: '/projects/quality' },
      { label: 'Workers and Safety', path: '/projects/safety' },
      { label: 'Site Diary', path: '/projects/diary' },
      { label: 'Project Chart', path: '/projects/chart' },
      { label: 'Equipment & Plant', path: '/projects/equipment' },
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
  {
    kind: 'group',
    id: 'store',
    perm: 'store.view',
    label: 'Store',
    icon: Package,
    items: [
      // Every receipt, issue, transfer and count is in the Store Hub. The old store's screens are kept as records,
      // reached from the Hub (routes.tsx sends their old addresses there).
      { label: 'Store Hub', path: '/store/hub', perm: STORE_ANY },
      { label: 'Purchase Orders', path: '/store/purchase-orders', perm: 'purchase.manage|bills.view_all' },
      { label: 'Enquiries & Comparison', path: '/store/enquiries', perm: 'purchase.manage' },
      { label: 'Item Master', path: '/store/items', perm: 'items.manage' },
      { label: 'Invoice Tracker', path: '/store/invoice-tracker', perm: 'stores.receive|stores.manage|purchase.manage|bills.view_all' },
      { label: 'E-way Bills', path: '/store/eway' },
    ],
  },
  {
    kind: 'group',
    id: 'money',
    perm: 'money.view',
    label: 'Money',
    icon: Wallet,
    items: [
      { label: 'Payments & Ledgers', path: '/money/ledgers', perm: 'bills.view_all' },
      { label: 'Owed & Retention', path: '/money/owed', perm: 'bills.view_all' },
      { label: 'Supplier Bills', path: '/money/supplier-bills', perm: 'bills.view_all' },
      { label: 'GST', path: '/money/gst', perm: 'bills.view_all' },
      { label: 'Fixed Assets', path: '/money/assets', perm: 'bills.view_all' },
      { label: 'TDS, Guarantees & Advances', path: '/money/registers', perm: 'bills.view_all' },
      { label: 'Site Cash', path: '/money/site-cash', perm: 'bills.view_all' },
    ],
  },
  {
    kind: 'group',
    id: 'people',
    label: 'People',
    icon: Users,
    ownerOnly: true,
    items: [
      { label: 'Employees', path: '/people/employees', perm: 'people.manage' },
      { label: 'Departments', path: '/people/departments', perm: 'people.manage' },
      { label: 'Attendance', path: '/people/attendance', perm: 'attendance.view_team|people.manage' },
      { label: 'Leave', path: '/people/leave', perm: 'leave.approve' },
      { label: 'Payroll', path: '/people/payroll', perm: 'payroll.manage' },
    ],
  },
  { kind: 'link', id: 'settings', label: 'Settings', icon: Settings, path: '/settings', ownerOnly: true },
]

export type Trail = { label: string; path?: string }[]

/** Screens with no menu entry of their own: the old store's records, opened from the Store Hub. */
const OFF_MENU: Record<string, string> = {
  '/store/old/stock': 'Stock & Issues (old store)',
  '/store/old/goods-receipt': 'Goods Receipt & Match (old store)',
  '/store/old/material-vouchers': 'Material Issue Voucher (old store)',
  '/store/old/material-costing': 'Material Used vs Costed (old store)',
}

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
  const off = OFF_MENU[pathname]
  if (off) return [...home, { label: 'Store' }, { label: 'Store Hub', path: '/store/hub' }, { label: off }]
  // A page inside a section: /subcontractors/work-orders/12 sits under Work Orders.
  for (const e of NAV) {
    if (e.kind !== 'group') continue
    const parent = e.items.find((i) => pathname.startsWith(i.path + '/'))
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
    if (e.kind === 'link') return !e.perm || can(e.perm) ? [e] : []
    const items = e.items.filter((i) => (!i.perm || can(i.perm)) && !(headOffice && i.notHeadOffice))
    return items.length ? [{ ...e, items }] : []
  })
}

export function groupFor(pathname: string): string | null {
  for (const e of NAV) if (e.kind === 'group' && e.items.some((i) => i.path === pathname || pathname.startsWith(i.path + '/'))) return e.id
  return null
}

export function allRoutes(): { path: string; label: string; group?: string }[] {
  return NAV.flatMap((e) =>
    e.kind === 'link'
      ? e.path === '/'
        ? []
        : [{ path: e.path, label: e.label }]
      : e.items.map((i) => ({ path: i.path, label: i.label, group: e.label })),
  )
}
