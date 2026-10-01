import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

/**
 * The screens that have been moved across. Each loads on its own, so opening
 * the Item Master does not download the work order builder. Any menu item not
 * listed here still shows the "waiting to be ported" page.
 */
export interface PortedRoute {
  path: string
  Component: LazyExoticComponent<ComponentType>
}

export const PORTED: PortedRoute[] = [
  { path: '/store/items', Component: lazy(() => import('@/features/items/ItemMasterPage')) },
  { path: '/subcontractors/work-orders', Component: lazy(() => import('@/features/orders/OrdersPage')) },
  { path: '/subcontractors/measurement-book', Component: lazy(() => import('@/features/measurement/MeasurementBookPage')) },
  { path: '/approvals', Component: lazy(() => import('@/features/approvals/ApprovalsPage')) },
  { path: '/subcontractors/vendors', Component: lazy(() => import('@/features/vendors/VendorsPage')) },
  { path: '/subcontractors/ra-bills', Component: lazy(() => import('@/features/subbills/RaBillsPage')) },
  { path: '/subcontractors/ra-bills/:id', Component: lazy(() => import('@/features/subbills/BillPage')) },
  { path: '/subcontractors/work-orders/:id', Component: lazy(() => import('@/features/orders/OrderPage')) },
  { path: '/clients/work-orders', Component: lazy(() => import('@/features/clientorders/ClientOrdersPage')) },
  { path: '/clients/measurement', Component: lazy(() => import('@/features/clientbook/ClientBookPage')) },
  { path: '/clients/customers', Component: lazy(() => import('@/features/customers/CustomersPage')) },
  { path: '/clients/pipeline', Component: lazy(() => import('@/features/leads/LeadsPage')) },
  { path: '/clients/estimates', Component: lazy(() => import('@/features/estimates/EstimatesPage')) },
  { path: '/clients/estimates/:id', Component: lazy(() => import('@/features/estimates/EstimatePage')) },
  { path: '/money/owed', Component: lazy(() => import('@/features/owed/OwedPage')) },
  { path: '/money/ledgers', Component: lazy(() => import('@/features/ledger/LedgerPage')) },
  { path: '/money/supplier-bills', Component: lazy(() => import('@/features/bills/BillsPage')) },
  { path: '/money/gst', Component: lazy(() => import('@/features/gst/GstPage')) },
  { path: '/money/assets', Component: lazy(() => import('@/features/assets/AssetsPage')) },
  { path: '/money/registers', Component: lazy(() => import('@/features/registers/RegistersPage')) },
  { path: '/store/purchase-orders', Component: lazy(() => import('@/features/purchaseorders/PurchaseOrdersPage')) },
  { path: '/people/departments', Component: lazy(() => import('@/features/people/DepartmentsPage')) },
  { path: '/people/employees', Component: lazy(() => import('@/features/people/EmployeesPage')) },
  { path: '/people/employees/:id', Component: lazy(() => import('@/features/people/EmployeePage')) },
  { path: '/projects/safety', Component: lazy(() => import('@/features/safety/SafetyPage')) },
  { path: '/projects/quality', Component: lazy(() => import('@/features/quality/QualityPage')) },
  { path: '/projects/programme', Component: lazy(() => import('@/features/schedule/SchedulePage')) },
  { path: '/projects/chat', Component: lazy(() => import('@/features/chat/ChatPage')) },
  { path: '/projects/equipment', Component: lazy(() => import('@/features/equipment/EquipmentPage')) },
  { path: '/projects/drawings', Component: lazy(() => import('@/features/drawings/DrawingsPage')) },
  { path: '/projects', Component: lazy(() => import('@/features/projects/ProjectsPage')) },
  { path: '/projects/:id', Component: lazy(() => import('@/features/projects/ProjectPage')) },
  { path: '/projects/costs', Component: lazy(() => import('@/features/projects/CostByProjectPage')) },
  { path: '/projects/costs/:id', Component: lazy(() => import('@/features/projects/ProjectCostsPage')) },
  { path: '/projects/profit', Component: lazy(() => import('@/features/projects/ProjectProfitPage')) },
  { path: '/projects/diary', Component: lazy(() => import('@/features/diary/DiaryPage')) },
  { path: '/people/attendance', Component: lazy(() => import('@/features/attendance/AttendancePage')) },
  { path: '/people/leave', Component: lazy(() => import('@/features/leave/LeavePage')) },
  { path: '/people/payroll', Component: lazy(() => import('@/features/payroll/PayrollPage')) },
  { path: '/me/timesheet', Component: lazy(() => import('@/features/staff/TimesheetPage')) },
  { path: '/me/costs', Component: lazy(() => import('@/features/staff/CostsPage')) },
  { path: '/me/orders', Component: lazy(() => import('@/features/purchaseorders/PurchaseOrdersPage')) },
  { path: '/me/leave', Component: lazy(() => import('@/features/staff/LeavePage')) },
  { path: '/me/payslips', Component: lazy(() => import('@/features/staff/PayslipsPage')) },
  { path: '/me/documents', Component: lazy(() => import('@/features/staff/DocumentsPage')) },
  { path: '/me/goals', Component: lazy(() => import('@/features/staff/GoalsPage')) },
  { path: '/me/onboarding', Component: lazy(() => import('@/features/staff/OnboardingPage')) },
  { path: '/me/team', Component: lazy(() => import('@/features/staff/TeamPage')) },
  { path: '/me/profile', Component: lazy(() => import('@/features/staff/ProfilePage')) },
]
