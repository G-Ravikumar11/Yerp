import {
  BadgeIndianRupee,
  Building2,
  CheckCheck,
  HardHat,
  LayoutDashboard,
  type LucideIcon,
  Package,
  Settings,
  UserRound,
  Users,
  Wallet,
} from 'lucide-react'

export type NavItem = { label: string; path: string; perm?: string }
/** staffOnly: the screens of a member of staff's own work (timesheet, payslips), which the account holder has no use for. */
export type NavGroup = { id: string; label: string; icon: LucideIcon; items: NavItem[]; staffOnly?: boolean; ownerOnly?: boolean }
export type NavEntry = { kind: 'link'; id: string; label: string; icon: LucideIcon; path: string; perm?: string; ownerOnly?: boolean } | ({ kind: 'group' } & NavGroup)

/**
 * The same six groups the current app has, so nobody has to relearn where
 * things live - only what they look like. Every item gets a route; those not
 * yet ported render the migration placeholder.
 */
export const NAV: NavEntry[] = [
  { kind: 'link', id: 'dashboard', label: 'Command Center', icon: LayoutDashboard, path: '/', ownerOnly: true },
  {
    kind: 'group',
    id: 'me',
    label: 'My work',
    icon: UserRound,
    staffOnly: true,
    items: [
      { label: 'Overview', path: '/' },
      { label: 'Timesheet', path: '/me/timesheet' },
      { label: 'My Costs', path: '/me/costs', perm: 'bills.submit' },
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
    label: 'Projects',
    icon: Building2,
    items: [
      { label: 'Projects', path: '/projects', perm: 'reports.view' },
      { label: 'Programme & Progress', path: '/projects/programme' },
      { label: 'Drawings & Photos', path: '/projects/drawings' },
      { label: 'Quality', path: '/projects/quality' },
      { label: 'Safety', path: '/projects/safety' },
      { label: 'Site Diary', path: '/projects/diary' },
      { label: 'Project Chat', path: '/projects/chat' },
      { label: 'Equipment & Plant', path: '/projects/equipment' },
      { label: 'BOQ', path: '/projects/boq', perm: 'workorders.manage|reports.view' },
      { label: 'Project Profit', path: '/projects/profit', perm: 'reports.view' },
      { label: 'Cost by Project', path: '/projects/costs', perm: 'reports.view' },
    ],
  },
  {
    kind: 'group',
    id: 'clients',
    label: 'Clients',
    icon: BadgeIndianRupee,
    items: [
      { label: 'Tender Pipeline', path: '/clients/pipeline', perm: 'billing.manage' },
      { label: 'Tenders & Estimates', path: '/clients/estimates', perm: 'billing.manage' },
      { label: 'Client Work Orders', path: '/clients/work-orders', perm: 'workorders.manage' },
      { label: 'Measurement & RA Bills', path: '/clients/measurement', perm: 'site.record|billing.manage' },
      { label: 'Customers', path: '/clients/customers', perm: 'customers.manage' },
      { label: 'Contacts', path: '/clients/contacts', perm: 'customers.manage' },
    ],
  },
  {
    kind: 'group',
    id: 'subcontractors',
    label: 'Subcontractors',
    icon: HardHat,
    items: [
      { label: 'Vendor Register', path: '/subcontractors/vendors' },
      { label: 'Work Orders', path: '/subcontractors/work-orders' },
      { label: 'Measurement Book', path: '/subcontractors/measurement-book' },
      { label: 'RA Bills', path: '/subcontractors/ra-bills' },
      { label: 'Compliance', path: '/subcontractors/compliance' },
    ],
  },
  {
    kind: 'group',
    id: 'store',
    label: 'Store',
    icon: Package,
    items: [
      { label: 'Item Master', path: '/store/items', perm: 'items.manage' },
      { label: 'Enquiries & Comparison', path: '/store/enquiries', perm: 'purchase.manage' },
      { label: 'Purchase Orders', path: '/store/purchase-orders', perm: 'purchase.manage|bills.view_all' },
      { label: 'E-way Bills', path: '/store/eway' },
      { label: 'Goods Receipt & Match', path: '/store/goods-receipt', perm: 'stores.receive' },
      { label: 'Stock & Issues', path: '/store/stock', perm: 'site.record|stores.manage' },
      { label: 'Material Used vs Costed', path: '/store/material-costing', perm: 'reports.view' },
    ],
  },
  {
    kind: 'group',
    id: 'money',
    label: 'Money',
    icon: Wallet,
    items: [
      { label: 'Payments & Ledgers', path: '/money/ledgers', perm: 'bills.view_all' },
      { label: 'Owed & Retention', path: '/money/owed', perm: 'bills.view_all' },
      { label: 'Supplier Bills', path: '/money/supplier-bills', perm: 'bills.view_all' },
      { label: 'GST', path: '/money/gst', perm: 'bills.view_all' },
      { label: 'Fixed Assets', path: '/money/assets', perm: 'bills.view_all' },
      { label: 'TDS, Guarantees & Advances', path: '/money/registers', perm: 'bills.view_all' },
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

/** Home > Group > Page for whatever path is showing. */
export function trailFor(pathname: string, staff = false): Trail {
  const home: Trail = [{ label: 'Home', path: '/' }]
  if (pathname === '/') return [{ label: staff ? 'Overview' : 'Command Center' }]
  if (pathname === '/design') return [...home, { label: 'Design system' }]
  if (pathname === '/design/grid') return [...home, { label: 'Design system', path: '/design' }, { label: 'Data grid' }]
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
    const parent = e.items.find((i) => pathname.startsWith(i.path + '/'))
    if (parent) return [...home, { label: e.label }, { label: parent.label, path: parent.path }, { label: 'Details' }]
  }
  return [...home, { label: 'Not found' }]
}

/** The menu as this person may see it: items they lack the right to are left out, and so are groups left empty. */
export function visibleNav(can: (perm: string) => boolean, staff = false): NavEntry[] {
  return NAV.flatMap((e): NavEntry[] => {
    if (e.kind === 'group' && e.staffOnly && !staff) return []
    if (e.kind === 'group' && e.ownerOnly && staff) return []
    if (e.kind === 'link' && e.ownerOnly && staff) return []
    if (e.kind === 'link') return !e.perm || can(e.perm) ? [e] : []
    const items = e.items.filter((i) => !i.perm || can(i.perm))
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
