import { createElement, lazy, useState, type ComponentType } from 'react'

/**
 * Every screen inside the app shell and the address it lives at. Each loads on its own, so opening
 * the Item Master does not download the work order builder. The sidebar's menu is in lib/nav.ts;
 * a menu item needs its screen listed here too.
 */
export interface Screen {
  path: string
  Component: ComponentType & { preload?: () => Promise<unknown> }
}

/**
 * A screen loaded on first use that can also be loaded ahead (`preload`), so the first visit does not wait for its
 * code to come over the network: the sidebar starts it when a menu entry is pointed at, and quietly for the whole menu
 * once the browser is idle (lib/prefetch.ts).
 *
 * Once its code is in, the screen is drawn straight away. Through React.lazy alone it would still show the loading
 * placeholder first, and React holds a screen back for 300ms after a placeholder so the two do not flicker - every
 * first visit would wait that long however fast the code came. Which way a screen is drawn is fixed when it opens, so
 * it is never swapped (and its state lost) halfway through a visit.
 */
function page(load: () => Promise<{ default: ComponentType }>): Screen['Component'] {
  let loaded: ComponentType | null = null
  const preload = () => load().then((m) => ((loaded = m.default), m))
  const Lazy = lazy(preload)
  function LoadedOrLazy() {
    const [Ready] = useState(() => loaded)
    return createElement(Ready ?? Lazy)
  }
  return Object.assign(LoadedOrLazy, { preload })
}

/** Addresses that moved: a bookmark or an old link lands on the Store Hub screen that does the same job. */
export const REDIRECTS: { from: string; to: string }[] = [
  { from: '/store/goods-receipt', to: '/store/hub/inward/grn' },
  { from: '/store/stock', to: '/store/hub/enquiry' },
  { from: '/store/material-vouchers', to: '/store/hub/outward/issue' },
  { from: '/store/material-costing', to: '/store/hub/reports/norm-variance' },
]

export const SCREENS: Screen[] = [
  { path: '/calendar', Component: page(() => import('@/features/calendar/CalendarPage')) },
  { path: '/celebrations', Component: page(() => import('@/features/celebrations/CelebrationsPage')) },
  { path: '/ho', Component: page(() => import('@/features/headoffice/HoPortalPage')) },
  { path: '/projects/boq', Component: page(() => import('@/features/boq/BoqListPage')) },
  { path: '/projects/boq/rates', Component: page(() => import('@/features/boq/SiteRatesPage')) },
  { path: '/projects/boq/:id', Component: page(() => import('@/features/boq/BoqPage')) },
  { path: '/store/items', Component: page(() => import('@/features/items/ItemMasterPage')) },
  { path: '/store/rate-contracts', Component: page(() => import('@/features/items/RateContractsPage')) },
  { path: '/store/items/duplicates', Component: page(() => import('@/features/items/DuplicatesPage')) },
  { path: '/subcontractors/work-orders', Component: page(() => import('@/features/orders/OrdersPage')) },
  { path: '/subcontractors/measurement-book', Component: page(() => import('@/features/measurement/MeasurementBookPage')) },
  { path: '/settings', Component: page(() => import('@/features/settings/SettingsPage')) },
  { path: '/approvals', Component: page(() => import('@/features/approvals/ApprovalsPage')) },
  { path: '/subcontractors/vendors', Component: page(() => import('@/features/vendors/VendorsPage')) },
  { path: '/subcontractors/compliance', Component: page(() => import('@/features/compliance/CompliancePage')) },
  { path: '/subcontractors/registers', Component: page(() => import('@/features/orders/RegistersPage')) },
  { path: '/subcontractors/ra-bills', Component: page(() => import('@/features/subbills/RaBillsPage')) },
  { path: '/subcontractors/ra-bills/:id', Component: page(() => import('@/features/subbills/BillPage')) },
  { path: '/subcontractors/work-orders/:id', Component: page(() => import('@/features/orders/OrderPage')) },
  { path: '/clients/work-orders', Component: page(() => import('@/features/clientorders/ClientOrdersPage')) },
  { path: '/clients/measurement', Component: page(() => import('@/features/clientbook/ClientBookPage')) },
  { path: '/clients/work-orders/:id/budget-report', Component: page(() => import('@/features/budgetreport/BudgetReportPage')) },
  { path: '/clients/contacts', Component: page(() => import('@/features/contacts/ContactsPage')) },
  { path: '/clients/customers', Component: page(() => import('@/features/customers/CustomersPage')) },
  { path: '/clients/pipeline', Component: page(() => import('@/features/leads/LeadsPage')) },
  { path: '/clients/estimates', Component: page(() => import('@/features/estimates/EstimatesPage')) },
  { path: '/clients/estimates/:id', Component: page(() => import('@/features/estimates/EstimatePage')) },
  { path: '/money/owed', Component: page(() => import('@/features/owed/OwedPage')) },
  { path: '/money/ledgers', Component: page(() => import('@/features/ledger/LedgerPage')) },
  { path: '/money/supplier-bills', Component: page(() => import('@/features/bills/BillsPage')) },
  { path: '/money/gst', Component: page(() => import('@/features/gst/GstPage')) },
  { path: '/money/assets', Component: page(() => import('@/features/assets/AssetsPage')) },
  { path: '/money/registers', Component: page(() => import('@/features/registers/RegistersPage')) },
  { path: '/money/site-cash', Component: page(() => import('@/features/sitecash/SiteCashPage')) },
  { path: '/money/tally', Component: page(() => import('@/features/tally/TallyPage')) },
  { path: '/me/site-cash', Component: page(() => import('@/features/sitecash/SiteCashPage')) },
  { path: '/store/purchase-orders', Component: page(() => import('@/features/purchaseorders/PurchaseOrdersPage')) },
  { path: '/people/departments', Component: page(() => import('@/features/people/DepartmentsPage')) },
  { path: '/people/employees', Component: page(() => import('@/features/people/EmployeesPage')) },
  { path: '/people/employees/:id', Component: page(() => import('@/features/people/EmployeePage')) },
  { path: '/projects/safety', Component: page(() => import('@/features/safety/SafetyPage')) },
  { path: '/projects/quality', Component: page(() => import('@/features/quality/QualityPage')) },
  { path: '/projects/programme/:job/activity/:id', Component: page(() => import('@/features/schedule/ActivityPage')) },
  { path: '/projects/programme', Component: page(() => import('@/features/schedule/SchedulePage')) },
  { path: '/projects/chart', Component: page(() => import('@/features/chart/ChartPage')) },
  { path: '/projects/equipment', Component: page(() => import('@/features/equipment/EquipmentPage')) },
  { path: '/projects/bbs', Component: page(() => import('@/features/bbs/BbsPage')) },
  { path: '/projects/drawings', Component: page(() => import('@/features/drawings/DrawingsPage')) },
  { path: '/projects/documents', Component: page(() => import('@/features/doccontrol/DocControlPage')) },
  { path: '/projects', Component: page(() => import('@/features/projects/ProjectsPage')) },
  { path: '/projects/:id', Component: page(() => import('@/features/projects/ProjectPage')) },
  { path: '/projects/costs', Component: page(() => import('@/features/projects/CostByProjectPage')) },
  { path: '/projects/costs/:id', Component: page(() => import('@/features/projects/ProjectCostsPage')) },
  { path: '/projects/budgeting', Component: page(() => import('@/features/budgeting/BudgetingPage')) },
  { path: '/projects/profit', Component: page(() => import('@/features/projects/ProjectProfitPage')) },
  { path: '/store/hub', Component: page(() => import('@/features/store/StorePage')) },
  { path: '/store/hub/masters/*', Component: page(() => import('@/features/store/masters')) },
  { path: '/store/hub/enquiry/*', Component: page(() => import('@/features/store/enquiry')) },
  { path: '/store/hub/inward/*', Component: page(() => import('@/features/store/inward')) },
  { path: '/store/hub/outward/*', Component: page(() => import('@/features/store/outward')) },
  { path: '/store/hub/control/*', Component: page(() => import('@/features/store/control')) },
  { path: '/store/hub/reports/*', Component: page(() => import('@/features/store/reports')) },
  // The old store's screens: in use until the company moves into the Store Hub, then kept as records.
  { path: '/store/old/stock', Component: page(() => import('@/features/stock/StockPage')) },
  { path: '/store/old/material-vouchers', Component: page(() => import('@/features/stock/MaterialVouchersPage')) },
  { path: '/store/old/material-costing', Component: page(() => import('@/features/stock/ConsumptionPage')) },
  { path: '/store/old/goods-receipt', Component: page(() => import('@/features/grn/GrnPage')) },
  { path: '/store/invoice-tracker', Component: page(() => import('@/features/invoicetracker/InvoiceTrackerPage')) },
  { path: '/store/eway', Component: page(() => import('@/features/eway/EwayPage')) },
  { path: '/store/enquiries', Component: page(() => import('@/features/rfq/RfqPage')) },
  { path: '/store/enquiries/:id', Component: page(() => import('@/features/rfq/EnquiryPage')) },
  { path: '/projects/diary', Component: page(() => import('@/features/diary/DiaryPage')) },
  { path: '/people/attendance', Component: page(() => import('@/features/attendance/AttendancePage')) },
  { path: '/people/leave', Component: page(() => import('@/features/leave/LeavePage')) },
  { path: '/people/payroll', Component: page(() => import('@/features/payroll/PayrollPage')) },
  { path: '/me/timesheet', Component: page(() => import('@/features/staff/TimesheetPage')) },
  { path: '/me/costs', Component: page(() => import('@/features/staff/CostsPage')) },
  { path: '/me/orders', Component: page(() => import('@/features/purchaseorders/PurchaseOrdersPage')) },
  { path: '/me/leave', Component: page(() => import('@/features/staff/LeavePage')) },
  { path: '/me/payslips', Component: page(() => import('@/features/staff/PayslipsPage')) },
  { path: '/me/documents', Component: page(() => import('@/features/staff/DocumentsPage')) },
  { path: '/me/goals', Component: page(() => import('@/features/staff/GoalsPage')) },
  { path: '/me/onboarding', Component: page(() => import('@/features/staff/OnboardingPage')) },
  { path: '/me/team', Component: page(() => import('@/features/staff/TeamPage')) },
  { path: '/me/profile', Component: page(() => import('@/features/staff/ProfilePage')) },
]
