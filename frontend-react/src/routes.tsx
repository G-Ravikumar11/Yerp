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
]
